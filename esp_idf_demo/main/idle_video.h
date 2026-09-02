#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct idle_video idle_video_t;

esp_err_t idle_video_open(const char *path,
                          size_t max_file_bytes,
                          size_t max_frames,
                          idle_video_t **out_video);
void idle_video_close(idle_video_t *video);

size_t idle_video_frame_count(const idle_video_t *video);
uint16_t idle_video_width(const idle_video_t *video);
uint16_t idle_video_height(const idle_video_t *video);

esp_err_t idle_video_decode_frame(idle_video_t *video,
                                  size_t frame_index,
                                  uint8_t *rgb565_out,
                                  size_t rgb565_out_size);

#ifdef __cplusplus
}
#endif
