#pragma once

#include "esp_err.h"
#include "freertos/FreeRTOS.h"

typedef struct playback_session playback_session_t;

esp_err_t playback_session_start(const char *url, playback_session_t **out);
esp_err_t playback_session_cancel(playback_session_t *session, int reason);
esp_err_t playback_session_detach(playback_session_t **session);
esp_err_t playback_session_join(playback_session_t **session,
                                TickType_t inactivity_timeout,
                                esp_err_t *playback_result);
