#pragma once

#include <stddef.h>
#include <stdint.h>

#include "cloud_client.h"
#include "esp_err.h"

typedef struct cloud_conversation cloud_conversation_t;

esp_err_t cloud_conversation_open(cloud_conversation_t **out);
esp_err_t cloud_conversation_start_turn(cloud_conversation_t *conversation, uint8_t turn_index, const char *turn_id);
esp_err_t cloud_conversation_send_pcm(cloud_conversation_t *conversation, const uint8_t *pcm, size_t pcm_bytes);
esp_err_t cloud_conversation_finish_turn(cloud_conversation_t *conversation, cloud_realtime_session_t *result);
esp_err_t cloud_conversation_complete_playback(cloud_conversation_t *conversation, const char *turn_id);
esp_err_t cloud_conversation_cancel_turn(cloud_conversation_t *conversation, const char *turn_id);
esp_err_t cloud_conversation_close(cloud_conversation_t *conversation, const char *reason);
