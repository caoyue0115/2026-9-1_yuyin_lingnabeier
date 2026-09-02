#include "idle_video.h"

#include "esp_heap_caps.h"
#include "jpeg_decoder.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IDLE_VIDEO_JPEG_WORK_BYTES (8 * 1024)

typedef struct {
    size_t offset;
    size_t size;
} idle_video_frame_t;

struct idle_video {
    uint8_t *avi_data;
    size_t avi_size;
    idle_video_frame_t *frames;
    size_t frame_count;
    size_t frame_capacity;
    uint16_t width;
    uint16_t height;
    uint8_t *jpeg_working_buffer;
};

static bool idle_video_has_avi_header(const uint8_t *data, size_t size)
{
    return size >= 12 && memcmp(data, "RIFF", 4) == 0 && memcmp(data + 8, "AVI ", 4) == 0;
}

static esp_err_t idle_video_index_jpeg_frames(idle_video_t *video)
{
    size_t cursor = 12;
    while (cursor + 1 < video->avi_size) {
        if (video->avi_data[cursor] != 0xFF || video->avi_data[cursor + 1] != 0xD8) {
            cursor++;
            continue;
        }

        size_t end = cursor + 2;
        while (end + 1 < video->avi_size &&
               !(video->avi_data[end] == 0xFF && video->avi_data[end + 1] == 0xD9)) {
            end++;
        }
        if (end + 1 >= video->avi_size) {
            return ESP_ERR_INVALID_RESPONSE;
        }
        if (video->frame_count >= video->frame_capacity) {
            return ESP_ERR_INVALID_SIZE;
        }

        video->frames[video->frame_count++] = (idle_video_frame_t) {
            .offset = cursor,
            .size = end + 2 - cursor,
        };
        cursor = end + 2;
    }
    return video->frame_count > 0 ? ESP_OK : ESP_ERR_NOT_FOUND;
}

static esp_err_t idle_video_read_file(const char *path, size_t max_file_bytes, idle_video_t *video)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return ESP_ERR_NOT_FOUND;
    }

    esp_err_t result = ESP_FAIL;
    if (fseek(file, 0, SEEK_END) != 0) {
        goto done;
    }
    long file_size = ftell(file);
    if (file_size <= 0 || (size_t)file_size > max_file_bytes) {
        result = ESP_ERR_INVALID_SIZE;
        goto done;
    }
    if (fseek(file, 0, SEEK_SET) != 0) {
        goto done;
    }

    video->avi_size = (size_t)file_size;
    video->avi_data = heap_caps_malloc(video->avi_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (video->avi_data == NULL) {
        result = ESP_ERR_NO_MEM;
        goto done;
    }
    if (fread(video->avi_data, 1, video->avi_size, file) != video->avi_size) {
        result = ESP_ERR_INVALID_RESPONSE;
        goto done;
    }
    result = ESP_OK;

done:
    fclose(file);
    return result;
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
    video->frames = calloc(max_frames, sizeof(*video->frames));
    video->jpeg_working_buffer = heap_caps_malloc(IDLE_VIDEO_JPEG_WORK_BYTES,
                                                   MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (video->frames == NULL || video->jpeg_working_buffer == NULL) {
        idle_video_close(video);
        return ESP_ERR_NO_MEM;
    }

    esp_err_t result = idle_video_read_file(path, max_file_bytes, video);
    if (result != ESP_OK || !idle_video_has_avi_header(video->avi_data, video->avi_size)) {
        idle_video_close(video);
        return result == ESP_OK ? ESP_ERR_INVALID_RESPONSE : result;
    }
    result = idle_video_index_jpeg_frames(video);
    if (result != ESP_OK) {
        idle_video_close(video);
        return result;
    }

    idle_video_frame_t first = video->frames[0];
    esp_jpeg_image_cfg_t info_cfg = {
        .indata = video->avi_data + first.offset,
        .indata_size = first.size,
        .out_format = JPEG_IMAGE_FORMAT_RGB565,
        .out_scale = JPEG_IMAGE_SCALE_0,
    };
    esp_jpeg_image_output_t info = {0};
    result = esp_jpeg_get_image_info(&info_cfg, &info);
    if (result != ESP_OK || info.width == 0 || info.height == 0) {
        idle_video_close(video);
        return result == ESP_OK ? ESP_ERR_INVALID_SIZE : result;
    }

    video->width = info.width;
    video->height = info.height;
    *out_video = video;
    return ESP_OK;
}

void idle_video_close(idle_video_t *video)
{
    if (video == NULL) {
        return;
    }
    free(video->jpeg_working_buffer);
    free(video->frames);
    free(video->avi_data);
    free(video);
}

size_t idle_video_frame_count(const idle_video_t *video)
{
    return video != NULL ? video->frame_count : 0;
}

uint16_t idle_video_width(const idle_video_t *video)
{
    return video != NULL ? video->width : 0;
}

uint16_t idle_video_height(const idle_video_t *video)
{
    return video != NULL ? video->height : 0;
}

esp_err_t idle_video_decode_frame(idle_video_t *video,
                                  size_t frame_index,
                                  uint8_t *rgb565_out,
                                  size_t rgb565_out_size)
{
    if (video == NULL || rgb565_out == NULL || frame_index >= video->frame_count) {
        return ESP_ERR_INVALID_ARG;
    }

    const size_t required_size = (size_t)video->width * video->height * 2;
    if (rgb565_out_size < required_size) {
        return ESP_ERR_INVALID_SIZE;
    }

    idle_video_frame_t frame = video->frames[frame_index];
    esp_jpeg_image_cfg_t decode_cfg = {
        .indata = video->avi_data + frame.offset,
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
            .working_buffer = video->jpeg_working_buffer,
            .working_buffer_size = IDLE_VIDEO_JPEG_WORK_BYTES,
        },
    };
    esp_jpeg_image_output_t output = {0};
    esp_err_t result = esp_jpeg_decode(&decode_cfg, &output);
    if (result != ESP_OK) {
        return result;
    }
    if (output.width != video->width || output.height != video->height || output.output_len != required_size) {
        return ESP_ERR_INVALID_SIZE;
    }
    return ESP_OK;
}
