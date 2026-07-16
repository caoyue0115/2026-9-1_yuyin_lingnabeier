#include "cloud_conversation.h"

#include "config.h"

#include "cJSON.h"
#include "esp_audio_enc.h"
#include "esp_log.h"
#include "esp_opus_enc.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *TAG = "cloud_conversation";

#define V6_WAIT_MS 30000
#define V6_CLOSE_WAIT_MS 2000
#define V6_SEND_WAIT_MS 3000
#define V6_JSON_BYTES 1024

struct cloud_conversation {
    esp_websocket_client_handle_t client;
    void *encoder;
    uint8_t *pcm_frame;
    size_t pcm_frame_size;
    size_t pcm_frame_len;
    uint8_t *opus_frame;
    size_t opus_frame_size;
    uint8_t *ws_frame;
    size_t ws_frame_size;
    uint32_t sequence;
    uint8_t turn_index;
    char turn_id[64];
    char conversation_id[64];
    char client_conversation_id[96];
    char ws_url[DEMO_CLOUD_AUDIO_URL_MAX_LEN];
    char ws_headers[512];
    char rx_json[V6_JSON_BYTES];
    size_t rx_json_len;
    cloud_realtime_session_t result;
    volatile bool connected;
    volatile bool disconnected;
    volatile bool ready;
    volatile bool turn_started;
    volatile bool turn_terminal;
    volatile bool turn_cancelled;
    volatile bool playback_complete;
    volatile bool conversation_done;
    volatile bool error_received;
};

static void v6_write_be32(uint8_t *data, uint32_t value)
{
    data[0] = (uint8_t)(value >> 24);
    data[1] = (uint8_t)(value >> 16);
    data[2] = (uint8_t)(value >> 8);
    data[3] = (uint8_t)value;
}

static void v6_write_be16(uint8_t *data, uint16_t value)
{
    data[0] = (uint8_t)(value >> 8);
    data[1] = (uint8_t)value;
}

static const char *v6_json_string(const cJSON *root, const char *name)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(root, name);
    return cJSON_IsString(item) && item->valuestring != NULL ? item->valuestring : NULL;
}

static bool v6_event_matches_turn(cloud_conversation_t *conversation, const cJSON *root)
{
    const char *conversation_id = v6_json_string(root, "conversation_id");
    const char *turn_id = v6_json_string(root, "turn_id");
    const cJSON *turn_index = cJSON_GetObjectItemCaseSensitive(root, "turn_index");
    return conversation_id != NULL && turn_id != NULL && cJSON_IsNumber(turn_index) &&
           strcmp(conversation_id, conversation->conversation_id) == 0 &&
           strcmp(turn_id, conversation->turn_id) == 0 &&
           turn_index->valueint == conversation->turn_index;
}

static int v6_send_text(cloud_conversation_t *conversation, const char *text)
{
    if (conversation == NULL || conversation->client == NULL || text == NULL ||
        !esp_websocket_client_is_connected(conversation->client)) {
        return -1;
    }
    const int len = (int)strlen(text);
    return esp_websocket_client_send_text(conversation->client,
                                          text,
                                          len,
                                          pdMS_TO_TICKS(V6_SEND_WAIT_MS));
}

static void v6_handle_json(cloud_conversation_t *conversation, const char *json)
{
    cJSON *root = cJSON_Parse(json);
    if (root == NULL) {
        conversation->error_received = true;
        return;
    }
    const char *type = v6_json_string(root, "type");
    if (type == NULL) {
        conversation->error_received = true;
    } else if (strcmp(type, "ping") == 0) {
        char pong[160];
        snprintf(pong, sizeof(pong),
                 "{\"type\":\"pong\",\"conversation_id\":\"%s\"}",
                 conversation->conversation_id);
        (void)v6_send_text(conversation, pong);
    } else if (strcmp(type, "conversation_ready") == 0) {
        const char *client_id = v6_json_string(root, "client_conversation_id");
        const char *conversation_id = v6_json_string(root, "conversation_id");
        if (client_id != NULL && conversation_id != NULL &&
            strcmp(client_id, conversation->client_conversation_id) == 0) {
            snprintf(conversation->conversation_id,
                     sizeof(conversation->conversation_id), "%s", conversation_id);
            conversation->ready = true;
        } else {
            conversation->error_received = true;
        }
    } else if (strcmp(type, "error") == 0) {
        conversation->error_received = true;
    } else if (strcmp(type, "conversation_done") == 0) {
        const char *id = v6_json_string(root, "conversation_id");
        if (id != NULL && strcmp(id, conversation->conversation_id) == 0) {
            conversation->conversation_done = true;
        }
    } else if (v6_event_matches_turn(conversation, root)) {
        if (strcmp(type, "ack") == 0) {
            const char *acknowledged = v6_json_string(root, "acknowledged_type");
            if (acknowledged != NULL && strcmp(acknowledged, "turn_start") == 0) {
                conversation->turn_started = true;
            }
        } else if (strcmp(type, "turn_result") == 0) {
            const char *session_id = v6_json_string(root, "session_id");
            const char *audio_url = v6_json_string(root, "audio_stream_url");
            if (session_id != NULL && audio_url != NULL) {
                snprintf(conversation->result.session_id,
                         sizeof(conversation->result.session_id), "%s", session_id);
                if (audio_url[0] == '/') {
                    size_t base_len = strlen(DEMO_SERVER_BASE_URL);
                    while (base_len > 0 && DEMO_SERVER_BASE_URL[base_len - 1] == '/') {
                        --base_len;
                    }
                    snprintf(conversation->result.audio_stream_url,
                             sizeof(conversation->result.audio_stream_url), "%.*s%s",
                             (int)base_len, DEMO_SERVER_BASE_URL, audio_url);
                } else {
                    snprintf(conversation->result.audio_stream_url,
                             sizeof(conversation->result.audio_stream_url), "%s", audio_url);
                }
                snprintf(conversation->result.status,
                         sizeof(conversation->result.status), "%s", "done");
                conversation->turn_terminal = true;
            }
        } else if (strcmp(type, "turn_complete") == 0) {
            const char *outcome = v6_json_string(root, "outcome");
            conversation->playback_complete = true;
            if (conversation->result.audio_stream_url[0] == '\0') {
                snprintf(conversation->result.status,
                         sizeof(conversation->result.status), "%s",
                         outcome != NULL ? outcome : "completed");
                conversation->turn_terminal = true;
            }
        } else if (strcmp(type, "turn_cancelled") == 0) {
            conversation->turn_cancelled = true;
            conversation->turn_terminal = true;
        }
    } else {
        conversation->error_received = true;
    }
    cJSON_Delete(root);
}

static void v6_ws_event(void *handler_args,
                        esp_event_base_t base,
                        int32_t event_id,
                        void *event_data)
{
    (void)base;
    cloud_conversation_t *conversation = (cloud_conversation_t *)handler_args;
    if (conversation == NULL) {
        return;
    }
    if (event_id == WEBSOCKET_EVENT_CONNECTED) {
        conversation->connected = true;
        return;
    }
    if (event_id == WEBSOCKET_EVENT_DISCONNECTED || event_id == WEBSOCKET_EVENT_CLOSED) {
        conversation->disconnected = true;
        return;
    }
    if (event_id == WEBSOCKET_EVENT_ERROR) {
        conversation->error_received = true;
        return;
    }
    if (event_id != WEBSOCKET_EVENT_DATA || event_data == NULL) {
        return;
    }
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;
    if (data->data_ptr == NULL || data->data_len <= 0 || data->payload_len <= 0) {
        return;
    }
    if (data->payload_offset == 0) {
        conversation->rx_json_len = 0;
    }
    if (conversation->rx_json_len + (size_t)data->data_len >= sizeof(conversation->rx_json)) {
        conversation->rx_json_len = 0;
        conversation->error_received = true;
        return;
    }
    memcpy(conversation->rx_json + conversation->rx_json_len,
           data->data_ptr, (size_t)data->data_len);
    conversation->rx_json_len += (size_t)data->data_len;
    conversation->rx_json[conversation->rx_json_len] = '\0';
    if (data->payload_offset + data->data_len >= data->payload_len) {
        v6_handle_json(conversation, conversation->rx_json);
        conversation->rx_json_len = 0;
    }
}

static esp_err_t v6_wait_flag(cloud_conversation_t *conversation,
                              volatile bool *flag,
                              int timeout_ms)
{
    const int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000;
    while (!*flag && !conversation->error_received && !conversation->disconnected &&
           esp_timer_get_time() < deadline) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (*flag) {
        return ESP_OK;
    }
    return conversation->error_received || conversation->disconnected ? ESP_FAIL : ESP_ERR_TIMEOUT;
}

static esp_err_t v6_build_ws_url(char *out, size_t out_size)
{
    const char *base = DEMO_SERVER_BASE_URL;
    const char *scheme = "ws://";
    if (strncmp(base, "https://", 8) == 0) {
        base += 8;
        scheme = "wss://";
    } else if (strncmp(base, "http://", 7) == 0) {
        base += 7;
    }
    size_t base_len = strlen(base);
    while (base_len > 0 && base[base_len - 1] == '/') {
        --base_len;
    }
    const int written = snprintf(out, out_size,
                                 "%s%.*s/api/v6/realtime/conversation/opus-stream",
                                 scheme, (int)base_len, base);
    return written > 0 && (size_t)written < out_size ? ESP_OK : ESP_ERR_NO_MEM;
}

static esp_err_t v6_open_encoder(cloud_conversation_t *conversation)
{
    esp_opus_enc_config_t config = ESP_OPUS_ENC_CONFIG_DEFAULT();
    config.sample_rate = DEMO_AUDIO_SAMPLE_RATE;
    config.channel = DEMO_AUDIO_CHANNELS;
    config.bits_per_sample = DEMO_AUDIO_BITS_PER_SAMPLE;
    config.bitrate = V5_OPUS_UPLINK_BITRATE;
    config.frame_duration = ESP_OPUS_ENC_FRAME_DURATION_60_MS;
    config.application_mode = ESP_OPUS_ENC_APPLICATION_AUDIO;
    config.complexity = 1;
    config.enable_vbr = true;
    if (esp_opus_enc_open(&config, sizeof(config), &conversation->encoder) != ESP_AUDIO_ERR_OK) {
        return ESP_FAIL;
    }
    int input_size = 0;
    int output_size = 0;
    if (esp_opus_enc_get_frame_size(conversation->encoder, &input_size, &output_size) != ESP_AUDIO_ERR_OK ||
        input_size <= 0 || output_size <= 0) {
        return ESP_FAIL;
    }
    conversation->pcm_frame_size = (size_t)input_size;
    conversation->opus_frame_size = (size_t)output_size;
    conversation->ws_frame_size = 10 + conversation->opus_frame_size;
    conversation->pcm_frame = calloc(1, conversation->pcm_frame_size);
    conversation->opus_frame = calloc(1, conversation->opus_frame_size);
    conversation->ws_frame = calloc(1, conversation->ws_frame_size);
    return conversation->pcm_frame != NULL && conversation->opus_frame != NULL &&
                   conversation->ws_frame != NULL
               ? ESP_OK
               : ESP_ERR_NO_MEM;
}

static esp_err_t v6_send_current_frame(cloud_conversation_t *conversation)
{
    esp_audio_enc_in_frame_t input = {
        .buffer = conversation->pcm_frame,
        .len = (uint32_t)conversation->pcm_frame_size,
    };
    esp_audio_enc_out_frame_t output = {
        .buffer = conversation->opus_frame,
        .len = (uint32_t)conversation->opus_frame_size,
    };
    if (esp_opus_enc_process(conversation->encoder, &input, &output) != ESP_AUDIO_ERR_OK ||
        output.encoded_bytes == 0 || output.encoded_bytes > UINT16_MAX) {
        return ESP_FAIL;
    }
    const uint32_t payload_len = 2 + output.encoded_bytes;
    const size_t frame_len = 8 + payload_len;
    v6_write_be32(conversation->ws_frame, conversation->sequence);
    v6_write_be32(conversation->ws_frame + 4, payload_len);
    v6_write_be16(conversation->ws_frame + 8, (uint16_t)output.encoded_bytes);
    memcpy(conversation->ws_frame + 10, conversation->opus_frame, output.encoded_bytes);
    const int sent = esp_websocket_client_send_bin(conversation->client,
                                                   (const char *)conversation->ws_frame,
                                                   (int)frame_len,
                                                   pdMS_TO_TICKS(V6_SEND_WAIT_MS));
    if (sent != (int)frame_len) {
        return ESP_FAIL;
    }
    conversation->sequence++;
    conversation->pcm_frame_len = 0;
    return ESP_OK;
}

static void v6_destroy(cloud_conversation_t *conversation)
{
    if (conversation == NULL) {
        return;
    }
    if (conversation->client != NULL) {
        if (esp_websocket_client_is_connected(conversation->client)) {
            (void)esp_websocket_client_stop(conversation->client);
        }
        (void)esp_websocket_client_destroy(conversation->client);
    }
    if (conversation->encoder != NULL) {
        esp_opus_enc_close(conversation->encoder);
    }
    free(conversation->pcm_frame);
    free(conversation->opus_frame);
    free(conversation->ws_frame);
    free(conversation);
}

esp_err_t cloud_conversation_open(cloud_conversation_t **out)
{
    if (out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out = NULL;
    cloud_conversation_t *conversation = calloc(1, sizeof(*conversation));
    if (conversation == NULL) {
        return ESP_ERR_NO_MEM;
    }
    snprintf(conversation->client_conversation_id,
             sizeof(conversation->client_conversation_id),
             "GreenMotive-%08lx-%08lx",
             (unsigned long)esp_random(), (unsigned long)esp_random());
    esp_err_t ret = v6_build_ws_url(conversation->ws_url, sizeof(conversation->ws_url));
    if (ret == ESP_OK) {
        ret = v6_open_encoder(conversation);
    }
    if (ret != ESP_OK) {
        v6_destroy(conversation);
        return ret;
    }
    snprintf(conversation->ws_headers, sizeof(conversation->ws_headers),
             "X-Device-Id: %s\r\nX-Audio-Packetization: framed-v1\r\n",
             DEMO_DEVICE_ID);
    esp_websocket_client_config_t config = {
        .uri = conversation->ws_url,
        .headers = conversation->ws_headers,
        .disable_auto_reconnect = true,
        .network_timeout_ms = V6_SEND_WAIT_MS,
        .buffer_size = V5_OPUS_UPLINK_WS_BUFFER_SIZE,
        .task_stack = V5_OPUS_UPLINK_WS_TASK_STACK_SIZE,
    };
    conversation->client = esp_websocket_client_init(&config);
    if (conversation->client == NULL ||
        esp_websocket_register_events(conversation->client, WEBSOCKET_EVENT_ANY,
                                      v6_ws_event, conversation) != ESP_OK ||
        esp_websocket_client_start(conversation->client) != ESP_OK) {
        v6_destroy(conversation);
        return ESP_FAIL;
    }
    ret = v6_wait_flag(conversation, &conversation->connected, 10000);
    if (ret != ESP_OK) {
        v6_destroy(conversation);
        return ret;
    }
    char start[384];
    const int written = snprintf(
        start, sizeof(start),
        "{\"type\":\"conversation_start\",\"client_conversation_id\":\"%s\","
        "\"device_id\":\"%s\",\"audio_format\":\"opus\","
        "\"protocol_version\":\"v6\",\"answer_mode\":\"streaming\"}",
        conversation->client_conversation_id, DEMO_DEVICE_ID);
    if (written <= 0 || (size_t)written >= sizeof(start) || v6_send_text(conversation, start) != written) {
        v6_destroy(conversation);
        return ESP_FAIL;
    }
    ret = v6_wait_flag(conversation, &conversation->ready, V6_WAIT_MS);
    if (ret != ESP_OK) {
        v6_destroy(conversation);
        return ret;
    }
    ESP_LOGI(TAG, "v6 conversation ready");
    *out = conversation;
    return ESP_OK;
}

esp_err_t cloud_conversation_start_turn(cloud_conversation_t *conversation,
                                        uint8_t turn_index,
                                        const char *turn_id)
{
    if (conversation == NULL || turn_id == NULL || turn_id[0] == '\0' ||
        strlen(turn_id) >= sizeof(conversation->turn_id)) {
        return ESP_ERR_INVALID_ARG;
    }
    snprintf(conversation->turn_id, sizeof(conversation->turn_id), "%s", turn_id);
    conversation->turn_index = turn_index;
    conversation->sequence = 0;
    conversation->pcm_frame_len = 0;
    conversation->turn_started = false;
    conversation->turn_terminal = false;
    conversation->turn_cancelled = false;
    conversation->playback_complete = false;
    memset(&conversation->result, 0, sizeof(conversation->result));
    char json[256];
    const int written = snprintf(json, sizeof(json),
                                 "{\"type\":\"turn_start\",\"conversation_id\":\"%s\","
                                 "\"turn_id\":\"%s\",\"turn_index\":%u}",
                                 conversation->conversation_id, conversation->turn_id,
                                 (unsigned)conversation->turn_index);
    if (written <= 0 || (size_t)written >= sizeof(json) || v6_send_text(conversation, json) != written) {
        return ESP_FAIL;
    }
    return v6_wait_flag(conversation, &conversation->turn_started, V6_WAIT_MS);
}

esp_err_t cloud_conversation_send_pcm(cloud_conversation_t *conversation,
                                      const uint8_t *pcm,
                                      size_t pcm_bytes)
{
    if (conversation == NULL || pcm == NULL || pcm_bytes == 0 || !conversation->turn_started) {
        return ESP_ERR_INVALID_ARG;
    }
    size_t offset = 0;
    while (offset < pcm_bytes) {
        const size_t capacity = conversation->pcm_frame_size - conversation->pcm_frame_len;
        const size_t amount = pcm_bytes - offset < capacity ? pcm_bytes - offset : capacity;
        memcpy(conversation->pcm_frame + conversation->pcm_frame_len, pcm + offset, amount);
        conversation->pcm_frame_len += amount;
        offset += amount;
        if (conversation->pcm_frame_len == conversation->pcm_frame_size) {
            esp_err_t ret = v6_send_current_frame(conversation);
            if (ret != ESP_OK) {
                return ret;
            }
        }
    }
    return ESP_OK;
}

esp_err_t cloud_conversation_finish_turn(cloud_conversation_t *conversation,
                                         cloud_realtime_session_t *result)
{
    if (conversation == NULL || result == NULL || !conversation->turn_started) {
        return ESP_ERR_INVALID_ARG;
    }
    if (conversation->pcm_frame_len > 0) {
        memset(conversation->pcm_frame + conversation->pcm_frame_len, 0,
               conversation->pcm_frame_size - conversation->pcm_frame_len);
        conversation->pcm_frame_len = conversation->pcm_frame_size;
        esp_err_t ret = v6_send_current_frame(conversation);
        if (ret != ESP_OK) {
            return ret;
        }
    }
    char json[256];
    const int written = snprintf(json, sizeof(json),
                                 "{\"type\":\"turn_end\",\"conversation_id\":\"%s\","
                                 "\"turn_id\":\"%s\",\"turn_index\":%u}",
                                 conversation->conversation_id, conversation->turn_id,
                                 (unsigned)conversation->turn_index);
    if (written <= 0 || (size_t)written >= sizeof(json) || v6_send_text(conversation, json) != written) {
        return ESP_FAIL;
    }
    esp_err_t ret = v6_wait_flag(conversation, &conversation->turn_terminal, V6_WAIT_MS);
    if (ret == ESP_OK) {
        *result = conversation->result;
    }
    return ret;
}

esp_err_t cloud_conversation_complete_playback(cloud_conversation_t *conversation,
                                               const char *turn_id)
{
    if (conversation == NULL || turn_id == NULL || strcmp(turn_id, conversation->turn_id) != 0) {
        return ESP_ERR_INVALID_ARG;
    }
    char json[280];
    const int written = snprintf(json, sizeof(json),
                                 "{\"type\":\"turn_playback_complete\","
                                 "\"conversation_id\":\"%s\",\"turn_id\":\"%s\","
                                 "\"turn_index\":%u}",
                                 conversation->conversation_id, conversation->turn_id,
                                 (unsigned)conversation->turn_index);
    conversation->playback_complete = false;
    if (written <= 0 || (size_t)written >= sizeof(json) ||
        v6_send_text(conversation, json) != written) {
        return ESP_FAIL;
    }
    return v6_wait_flag(conversation, &conversation->playback_complete, V6_WAIT_MS);
}

esp_err_t cloud_conversation_cancel_turn(cloud_conversation_t *conversation, const char *turn_id)
{
    if (conversation == NULL || turn_id == NULL || strcmp(turn_id, conversation->turn_id) != 0) {
        return ESP_ERR_INVALID_ARG;
    }
    char json[256];
    const int written = snprintf(json, sizeof(json),
                                 "{\"type\":\"turn_cancel\",\"conversation_id\":\"%s\","
                                 "\"turn_id\":\"%s\",\"turn_index\":%u}",
                                 conversation->conversation_id, conversation->turn_id,
                                 (unsigned)conversation->turn_index);
    if (written <= 0 || (size_t)written >= sizeof(json) || v6_send_text(conversation, json) != written) {
        return ESP_FAIL;
    }
    return v6_wait_flag(conversation, &conversation->turn_cancelled, V6_WAIT_MS);
}

esp_err_t cloud_conversation_close(cloud_conversation_t *conversation, const char *reason)
{
    if (conversation == NULL || reason == NULL || reason[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    char json[256];
    const int written = snprintf(json, sizeof(json),
                                 "{\"type\":\"conversation_end\","
                                 "\"conversation_id\":\"%s\",\"reason\":\"%s\"}",
                                 conversation->conversation_id, reason);
    esp_err_t ret = ESP_FAIL;
    if (written > 0 && (size_t)written < sizeof(json) && v6_send_text(conversation, json) == written) {
        ret = v6_wait_flag(conversation, &conversation->conversation_done, V6_CLOSE_WAIT_MS);
    }
    v6_destroy(conversation);
    return ret;
}
