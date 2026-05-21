#pragma once

#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_err.h"

esp_err_t board_audio_init(const i2s_std_config_t *i2s_config);
esp_codec_dev_handle_t board_audio_codec_speaker_init(void);
esp_codec_dev_handle_t board_audio_codec_microphone_init(void);
