#pragma once

#include <stdbool.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"

esp_err_t music_player_init(void);
esp_err_t music_player_start(void);
esp_err_t music_player_stop(TickType_t timeout);
bool music_player_is_active(void);
