#include "idle_video.h"

#include "esp_heap_caps.h"
#include "jpeg_decoder.h"

#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IDLE_VIDEO_JPEG_WORK_BYTES (8 * 1024)
#define IDLE_VIDEO_SCAN_CHUNK_BYTES 4096

typedef struct {
    size_t offset;
    size_t size;
} idle_video_frame_t;

struct idle_video {
    FILE *file;
    size_t avi_size;
    idle_video_frame_t *frames;
    size_t frame_count;
    size_t frame_capacity;
    size_t max_frame_bytes;
    uint16_t width;
    uint16_t height;
};

struct idle_video_decoder {
    uint8_t *jpeg_buffer;
    size_t jpeg_buffer_size;
    uint8_t *jpeg_working_buffer;
};

static bool idle_video_has_avi_header(FILE *file)
{
    uint8_t header[12];
    if (fseek(file, 0, SEEK_SET) != 0 || fread(header, 1, sizeof(header), file) != sizeof(header)) {
        return false;
    }
    return memcmp(header, "RIFF", 4) == 0 && memcmp(header + 8, "AVI ", 4) == 0;
}

static esp_err_t idle_video_index_jpeg_frames(idle_video_t *video)
{
    uint8_t *chunk = heap_caps_malloc(IDLE_VIDEO_SCAN_CHUNK_BYTES,
                                      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (chunk == NULL) {
        return ESP_ERR_NO_MEM;
    }
    if (fseek(video->file, 12, SEEK_SET) != 0) {
        free(chunk);
        return ESP_FAIL;
    }

    esp_err_t result = ESP_OK;
    bool inside_frame = false;
    bool have_previous = false;
    uint8_t previous = 0;
    size_t frame_start = 0;
    size_t absolute_offset = 12;
    size_t bytes_read;

    while ((bytes_read = fread(chunk, 1, IDLE_VIDEO_SCAN_CHUNK_BYTES, video->file)) > 0) {
        for (size_t index = 0; index < bytes_read; ++index) {
            const uint8_t current = chunk[index];
            const size_t current_offset = absolute_offset + index;
            if (have_previous && !inside_frame && previous == 0xFF && current == 0xD8) {
                frame_start = current_offset - 1;
                inside_frame = true;
            } else if (have_previous && inside_frame && previous == 0xFF && current == 0xD9) {
                if (video->frame_count >= video->frame_capacity) {
                    result = ESP_ERR_INVALID_SIZE;
                    goto done;
                }
                const size_t frame_size = current_offset + 1 - frame_start;
                video->frames[video->frame_count++] = (idle_video_frame_t) {
                    .offset = frame_start,
                    .size = frame_size,
                };
                if (frame_size > video->max_frame_bytes) {
                    video->max_frame_bytes = frame_size;
                }
                inside_frame = false;
            }
            previous = current;
            have_previous = true;
        }
        absolute_offset += bytes_read;
    }

    if (ferror(video->file)) {
        result = ESP_ERR_INVALID_RESPONSE;
    } else if (inside_frame) {
        result = ESP_ERR_INVALID_RESPONSE;
    } else if (video->frame_count == 0) {
        result = ESP_ERR_NOT_FOUND;
    }

done:
    free(chunk);
    return result;
}

static esp_err_t idle_video_read_compressed_frame(idle_video_t *video,
                                                  size_t frame_index,
                                                  uint8_t *buffer,
                                                  size_t buffer_size)
{
    if (video == NULL || buffer == NULL || frame_index >= video->frame_count) {
        return ESP_ERR_INVALID_ARG;
    }
    const idle_video_frame_t frame = video->frames[frame_index];
    if (frame.size > buffer_size || frame.offset > LONG_MAX) {
        return ESP_ERR_INVALID_SIZE;
    }
    if (fseek(video->file, (long)frame.offset, SEEK_SET) != 0 ||
        fread(buffer, 1, frame.size, video->file) != frame.size) {
        return ESP_ERR_INVALID_RESPONSE;
    }
    return ESP_OK;
}

esp_err_t idle_video_open(const char *path,
                          size_t max_file_bytes,
                          size_t max_frames,
                          idle_video_t **out_video)
{
    if (path == NULL || path[0] == '\0' || max_file_bytes == 0 || max_frames == 0 || out_video == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out_video = NULL;

    idle_video_t *video = calloc(1, sizeof(*video));
    if (video == NULL) {
        return ESP_ERR_NO_MEM;
    }
    video->frame_capacity = max_frames;
    video->frames = heap_caps_calloc(max_frames,
                                     sizeof(*video->frames),
                                     MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    video->file = fopen(path, "rb");
    if (video->frames == NULL || video->file == NULL) {
        const esp_err_t allocation_result = video->file == NULL ? ESP_ERR_NOT_FOUND : ESP_ERR_NO_MEM;
        idle_video_close(video);
        return allocation_result;
    }

    esp_err_t result = ESP_FAIL;
    if (fseek(video->file, 0, SEEK_END) != 0) {
        idle_video_close(video);
        return result;
    }
    const long file_size = ftell(video->file);
    if (file_size <= 0 || (size_t)file_size > max_file_bytes) {
        idle_video_close(video);
        return ESP_ERR_INVALID_SIZE;
    }
    video->avi_size = (size_t)file_size;
    if (!idle_video_has_avi_header(video->file)) {
        idle_video_close(video);
        return ESP_ERR_INVALID_RESPONSE;
    }
    result = idle_video_index_jpeg_frames(video);
    if (result != ESP_OK) {
        idle_video_close(video);
        return result;
    }

    const size_t first_size = video->frames[0].size;
    uint8_t *first_frame = heap_caps_malloc(first_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (first_frame == NULL) {
        idle_video_close(video);
        return ESP_ERR_NO_MEM;
    }
    result = idle_video_read_compressed_frame(video, 0, first_frame, first_size);
    if (result == ESP_OK) {
        esp_jpeg_image_cfg_t info_cfg = {
            .indata = first_frame,
            .indata_size = first_size,
            .out_format = JPEG_IMAGE_FORMAT_RGB565,
            .out_scale = JPEG_IMAGE_SCALE_0,
        };
        esp_jpeg_image_output_t info = {0};
        result = esp_jpeg_get_image_info(&info_cfg, &info);
        if (result == ESP_OK && info.width > 0 && info.height > 0) {
            video->width = info.width;
            video->height = info.height;
        } else if (result == ESP_OK) {
            result = ESP_ERR_INVALID_SIZE;
        }
    }
    free(first_frame);
    if (result != ESP_OK) {
        idle_video_close(video);
        return result;
    }

    *out_video = video;
    return ESP_OK;
}

void idle_video_close(idle_video_t *video)
{
    if (video == NULL) {
        return;
    }
    if (video->file != NULL) {
        fclose(video->file);
    }
    free(video->frames);
    free(video);
}

size_t idle_video_frame_count(const idle_video_t *video)
{
    return video != NULL ? video->frame_count : 0;
}

size_t idle_video_max_frame_bytes(const idle_video_t *video)
{
    return video != NULL ? video->max_frame_bytes : 0;
}

uint16_t idle_video_width(const idle_video_t *video)
{
    return video != NULL ? video->width : 0;
}

uint16_t idle_video_height(const idle_video_t *video)
{
    return video != NULL ? video->height : 0;
}

esp_err_t idle_video_decoder_create(size_t max_jpeg_bytes,
                                    idle_video_decoder_t **out_decoder)
{
    if (max_jpeg_bytes == 0 || out_decoder == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out_decoder = NULL;

    idle_video_decoder_t *decoder = calloc(1, sizeof(*decoder));
    if (decoder == NULL) {
        return ESP_ERR_NO_MEM;
    }
    decoder->jpeg_buffer = heap_caps_malloc(max_jpeg_bytes,
                                            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    decoder->jpeg_working_buffer = heap_caps_malloc(IDLE_VIDEO_JPEG_WORK_BYTES,
                                                    MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (decoder->jpeg_buffer == NULL || decoder->jpeg_working_buffer == NULL) {
        idle_video_decoder_close(decoder);
        return ESP_ERR_NO_MEM;
    }
    decoder->jpeg_buffer_size = max_jpeg_bytes;
    *out_decoder = decoder;
    return ESP_OK;
}

void idle_video_decoder_close(idle_video_decoder_t *decoder)
{
    if (decoder == NULL) {
        return;
    }
    free(decoder->jpeg_working_buffer);
    free(decoder->jpeg_buffer);
    free(decoder);
}

esp_err_t idle_video_decode_frame(idle_video_t *video,
                                  idle_video_decoder_t *decoder,
                                  size_t frame_index,
                                  uint8_t *rgb565_out,
                                  size_t rgb565_out_size)
{
    if (video == NULL || decoder == NULL || rgb565_out == NULL || frame_index >= video->frame_count) {
        return ESP_ERR_INVALID_ARG;
    }

    const size_t required_size = (size_t)video->width * video->height * 2;
    if (rgb565_out_size < required_size) {
        return ESP_ERR_INVALID_SIZE;
    }

    const idle_video_frame_t frame = video->frames[frame_index];
    esp_err_t result = idle_video_read_compressed_frame(video,
                                                        frame_index,
                                                        decoder->jpeg_buffer,
                                                        decoder->jpeg_buffer_size);
    if (result != ESP_OK) {
        return result;
    }

    esp_jpeg_image_cfg_t decode_cfg = {
        .indata = decoder->jpeg_buffer,
        .indata_size = frame.size,
        .outbuf = rgb565_out,
        .outbuf_size = rgb565_out_size,
        .out_format = JPEG_IMAGE_FORMAT_RGB565,
        .out_scale = JPEG_IMAGE_SCALE_0,
        .flags = {
            // LVGL owns the RGB565-to-panel byte swap for this display.
            .swap_color_bytes = 0,
        },
        .advanced = {
            .working_buffer = decoder->jpeg_working_buffer,
            .working_buffer_size = IDLE_VIDEO_JPEG_WORK_BYTES,
        },
    };
    esp_jpeg_image_output_t output = {0};
    result = esp_jpeg_decode(&decode_cfg, &output);
    if (result != ESP_OK) {
        return result;
    }
    if (output.width != video->width || output.height != video->height || output.output_len != required_size) {
        return ESP_ERR_INVALID_SIZE;
    }
    return ESP_OK;
}
