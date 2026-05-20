#include "config.h"
#include "trigger_input.h"
#include "audio_in.h"
#include "audio_out.h"
#include "cloud_client.h"

#include "esp_err.h"
#include "esp_event.h"
#include "esp_app_desc.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_spiffs.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"

#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

static const char *TAG = "esp_idf_demo";
static EventGroupHandle_t s_wifi_event_group;
static int s_wifi_retry_count = 0;
static TaskHandle_t s_pipeline_task_handle = NULL;
static TaskHandle_t s_ota_manifest_task_handle = NULL;
static int64_t s_last_pipeline_finish_us = 0;
static int64_t s_next_ota_manifest_check_us = 0;

#define APP_WIFI_CONNECTED_BIT BIT0
#define APP_WIFI_FAILED_BIT    BIT1

#define APP_OTA_P3C_NVS_NAMESPACE "ota_p3c"
#define APP_OTA_P3C_KEY_PENDING   "pending"
#define APP_OTA_P3C_KEY_RELEASE   "rel"
#define APP_OTA_P3C_KEY_VERSION   "ver"
#define APP_OTA_P3C_KEY_LABEL     "label"
#define APP_OTA_P3C_KEY_ADDRESS   "addr"
#define APP_OTA_P3C_KEY_SHA256    "sha"
#define APP_OTA_P3C_KEY_LAST_STAGE "last"

typedef enum {
    APP_STATE_IDLE = 0,
    APP_STATE_PLAYING_PROMPT,
    APP_STATE_WAITING_SPEECH,
    APP_STATE_RECORDING,
    APP_STATE_POSTING_SESSION,
    APP_STATE_POLLING,
    APP_STATE_DOWNLOADING,
    APP_STATE_OPENING_AUDIO,
    APP_STATE_STREAMING_AUDIO,
    APP_STATE_PLAYING,
    APP_STATE_DONE,
    APP_STATE_ERROR,
} app_state_t;

static app_state_t s_app_state = APP_STATE_ERROR;

static const char *app_state_to_string(app_state_t state)
{
    switch (state) {
    case APP_STATE_IDLE:
        return "idle";
    case APP_STATE_PLAYING_PROMPT:
        return "playing_prompt";
    case APP_STATE_WAITING_SPEECH:
        return "waiting_speech";
    case APP_STATE_RECORDING:
        return "recording";
    case APP_STATE_POSTING_SESSION:
        return "posting_session";
    case APP_STATE_POLLING:
        return "polling";
    case APP_STATE_DOWNLOADING:
        return "downloading";
    case APP_STATE_OPENING_AUDIO:
        return "opening_audio";
    case APP_STATE_STREAMING_AUDIO:
        return "streaming_audio";
    case APP_STATE_PLAYING:
        return "playing";
    case APP_STATE_DONE:
        return "done";
    case APP_STATE_ERROR:
    default:
        return "error";
    }
}

static const char *app_audio_mode_name(void)
{
    switch (DEMO_AUDIO_MODE) {
    case DEMO_AUDIO_MODE_V3_REALTIME:
        return "v3_realtime";
    case DEMO_AUDIO_MODE_V2_ASYNC:
    default:
        return "v2_async";
    }
}

static void app_set_state(app_state_t *current_state, app_state_t next_state)
{
    if (*current_state == next_state) {
        return;
    }

    ESP_LOGI(TAG, "State transition: %s -> %s",
             app_state_to_string(*current_state),
             app_state_to_string(next_state));
    *current_state = next_state;
}

typedef struct {
    trigger_event_t event;
} app_pipeline_task_args_t;

static void app_runtime_task(void *arg);

static void app_cleanup_pipeline_resources(void)
{
    audio_in_deinit();
    audio_out_deinit();
}

static void app_log_runtime_config(void)
{
    ESP_LOGI(TAG, "Runtime config:");
    ESP_LOGI(TAG, "  board=%s %s", DEMO_BOARD_NAME, DEMO_BOARD_REVISION);
    ESP_LOGI(TAG, "  trigger_source=%s", trigger_input_source_name(trigger_input_configured_source()));
    ESP_LOGI(TAG, "  wifi_ssid=%s", DEMO_WIFI_SSID);
    ESP_LOGI(TAG, "  server_base_url=%s", DEMO_SERVER_BASE_URL);
    ESP_LOGI(TAG, "  device_id=%s", DEMO_DEVICE_ID);
    ESP_LOGI(TAG, "  app_runtime_task_stack_size=%d", DEMO_APP_RUNTIME_TASK_STACK_SIZE);
    ESP_LOGI(TAG, "  audio_mode=%s", app_audio_mode_name());
    ESP_LOGI(TAG, "  wifi_power_save_none=%d", DEMO_WIFI_POWER_SAVE_NONE);
    ESP_LOGI(TAG, "  audio_format=%dHz/%d-bit/%dch", DEMO_AUDIO_SAMPLE_RATE,
             DEMO_AUDIO_BITS_PER_SAMPLE, DEMO_AUDIO_CHANNELS);
    ESP_LOGI(TAG, "  record_duration_sec=%d", DEMO_RECORD_DURATION_SEC);
    ESP_LOGI(TAG, "  record_prompt_enabled=%d", DEMO_RECORD_PROMPT_ENABLED);
    ESP_LOGI(TAG, "  record_prompt_path=%s", DEMO_RECORD_PROMPT_PATH);
    ESP_LOGI(TAG, "  record_retry_rearm_prompt_path=%s", DEMO_RECORD_RETRY_REARM_PROMPT_PATH);
    ESP_LOGI(TAG, "  record_retry_timeout_prompt_path=%s", DEMO_RECORD_RETRY_TIMEOUT_PROMPT_PATH);
    ESP_LOGI(TAG, "  record_retry_error_prompt_path=%s", DEMO_RECORD_RETRY_ERROR_PROMPT_PATH);
    ESP_LOGI(TAG, "  wait_for_speech_timeout_ms=%d", DEMO_WAIT_FOR_SPEECH_TIMEOUT_MS);
    ESP_LOGI(TAG, "  waiting_speech_arm_ms=%d", DEMO_WAITING_SPEECH_ARM_MS);
    ESP_LOGI(TAG, "  speech_start_hold_ms=%d", DEMO_SPEECH_START_HOLD_MS);
    ESP_LOGI(TAG, "  record_after_speech_max_ms=%d", DEMO_RECORD_AFTER_SPEECH_MAX_MS);
    ESP_LOGI(TAG, "  mic_init_retry_count=%d", DEMO_MIC_INIT_RETRY_COUNT);
    ESP_LOGI(TAG, "  mic_init_retry_delay_ms=%d", DEMO_MIC_INIT_RETRY_DELAY_MS);
    ESP_LOGI(TAG, "  audio_input_gain_db=%.1f", (double)DEMO_AUDIO_INPUT_GAIN_DB);
    ESP_LOGI(TAG, "  audio_output_volume=%d", DEMO_AUDIO_OUTPUT_VOLUME);
    ESP_LOGI(TAG, "  cloud_poll_timeout_ms=%d", DEMO_CLOUD_POLL_TIMEOUT_MS);
    ESP_LOGI(TAG, "  cloud_poll_interval_ms=%d", DEMO_CLOUD_POLL_INTERVAL_MS);
    ESP_LOGI(TAG, "  ota_manifest_dry_run_enabled=%d", DEMO_OTA_MANIFEST_DRY_RUN_ENABLED);
    ESP_LOGI(TAG, "  ota_manifest_poll_interval_ms=%d", DEMO_OTA_MANIFEST_POLL_INTERVAL_MS);
    ESP_LOGI(TAG, "  ota_idle_after_ws_delay_ms=%d", DEMO_OTA_IDLE_AFTER_WS_DELAY_MS);
    ESP_LOGI(TAG, "  ota_manifest_task_stack_size=%d", DEMO_OTA_MANIFEST_TASK_STACK_SIZE);
    ESP_LOGI(TAG, "  ota_partition_write_enabled=%d", DEMO_OTA_PARTITION_WRITE_ENABLED);
    ESP_LOGI(TAG, "  ota_boot_switch_enabled=%d", DEMO_OTA_BOOT_SWITCH_ENABLED);
    ESP_LOGI(TAG, "  ota_post_reboot_task_stack_size=%d", DEMO_OTA_POST_REBOOT_TASK_STACK_SIZE);
    ESP_LOGI(TAG, "  ota_rollback_validation_enabled=%d", DEMO_OTA_ROLLBACK_VALIDATION_ENABLED);
    ESP_LOGI(TAG, "  ota_rollback_validation_timeout_ms=%d", DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS);
    ESP_LOGI(TAG, "  ota_rollback_validation_task_stack_size=%d", DEMO_OTA_ROLLBACK_VALIDATION_TASK_STACK_SIZE);
    ESP_LOGI(TAG, "  realtime_session_timeout_ms=%d", DEMO_REALTIME_SESSION_TIMEOUT_MS);
    ESP_LOGI(TAG, "  v5_uplink_enabled=%d", V5_OPUS_UPLINK_WS_ENABLED);
    ESP_LOGI(TAG, "  v5_uplink_fallback_legacy_audio=%d", V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO);
    ESP_LOGI(TAG, "  v5_uplink_behavior_fallback_enabled=%d", V5_OPUS_UPLINK_BEHAVIOR_FALLBACK_ENABLED);
    ESP_LOGI(TAG, "  v5_uplink_frame_ms=%d", V5_OPUS_UPLINK_FRAME_MS);
    ESP_LOGI(TAG, "  v5_uplink_asr_provider=%s", V5_OPUS_UPLINK_ASR_PROVIDER);
    ESP_LOGI(TAG, "  v5_uplink_answer_mode=%s", V5_OPUS_UPLINK_ANSWER_MODE);
    ESP_LOGI(TAG, "  realtime_audio_open_timeout_ms=%d", DEMO_REALTIME_AUDIO_OPEN_TIMEOUT_MS);
    ESP_LOGI(TAG, "  realtime_audio_read_timeout_ms=%d", DEMO_REALTIME_AUDIO_READ_TIMEOUT_MS);
    ESP_LOGI(TAG, "  realtime_audio_jitter_buffer_bytes=%d", DEMO_REALTIME_AUDIO_JITTER_BUFFER_BYTES);
    ESP_LOGI(TAG, "  realtime_audio_jitter_prebuffer_bytes=%d", DEMO_REALTIME_AUDIO_JITTER_PREBUFFER_BYTES);
    ESP_LOGI(TAG, "  realtime_intro_enabled=%d", DEMO_REALTIME_INTRO_ENABLED);
    ESP_LOGI(TAG, "  realtime_intro_audio_parallel_enabled=%d", DEMO_REALTIME_INTRO_AUDIO_PARALLEL_ENABLED);
    ESP_LOGI(TAG, "  realtime_intro_path=%s", DEMO_REALTIME_INTRO_PATH);
    ESP_LOGI(TAG, "  realtime_audio_gate_wait_timeout_ms=%d", DEMO_REALTIME_AUDIO_GATE_WAIT_TIMEOUT_MS);
    ESP_LOGI(TAG, "  realtime_audio_parallel_task_stack_size=%d", DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE);
    ESP_LOGI(TAG, "  trigger_poll_interval_ms=%d", DEMO_TRIGGER_POLL_INTERVAL_MS);
}

static void app_log_heap_snapshot(const char *stage)
{
    ESP_LOGI(TAG,
             "heap stage=%s free_8bit=%u largest_8bit=%u free_spiram=%u largest_spiram=%u",
             stage != NULL ? stage : "unknown",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
}

static esp_err_t app_mount_spiffs(void)
{
    esp_vfs_spiffs_conf_t conf = {
        .base_path = DEMO_SPIFFS_BASE_PATH,
        .partition_label = DEMO_SPIFFS_PARTITION_LABEL,
        .max_files = DEMO_SPIFFS_MAX_FILES,
        .format_if_mount_failed = false,
    };

    esp_err_t ret = esp_vfs_spiffs_register(&conf);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "SPIFFS mount failed: label=%s base=%s err=%s",
                 DEMO_SPIFFS_PARTITION_LABEL,
                 DEMO_SPIFFS_BASE_PATH,
                 esp_err_to_name(ret));
        return ret;
    }

    size_t total = 0;
    size_t used = 0;
    ret = esp_spiffs_info(DEMO_SPIFFS_PARTITION_LABEL, &total, &used);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "SPIFFS mounted: label=%s total=%u used=%u",
                 DEMO_SPIFFS_PARTITION_LABEL,
                 (unsigned)total,
                 (unsigned)used);
    } else {
        ESP_LOGW(TAG, "SPIFFS mounted but info failed: %s", esp_err_to_name(ret));
    }
    return ESP_OK;
}

typedef struct {
    bool saw_first_chunk;
    size_t total_bytes;
    int64_t pipeline_start_us;
    int64_t first_chunk_us;
    int64_t intro_end_us;
    int64_t open_audio_done_us;
    uint32_t callback_count;
    int64_t total_enqueue_us;
    int64_t max_enqueue_us;
    volatile bool playback_gate_open;
    bool playback_gate_wait_logged;
    int64_t playback_gate_wait_us;
} app_realtime_stream_ctx_t;

typedef struct {
    TaskHandle_t task_handle;
    volatile bool done;
    esp_err_t result;
    char audio_stream_url[DEMO_CLOUD_AUDIO_URL_MAX_LEN];
    app_realtime_stream_ctx_t *stream_ctx;
    cloud_realtime_audio_metrics_t *metrics;
} app_realtime_parallel_task_t;

static double app_elapsed_ms_since(int64_t start_us, int64_t end_us)
{
    return (double)(end_us - start_us) / 1000.0;
}

static void app_log_pipeline_stack_watermark(const char *stage)
{
    UBaseType_t words = uxTaskGetStackHighWaterMark(NULL);
    ESP_LOGI(TAG,
             "pipeline_stack stage=%s high_water_words=%u high_water_bytes=%u configured_stack_bytes=%u",
             stage != NULL ? stage : "unknown",
             (unsigned)words,
             (unsigned)(words * sizeof(StackType_t)),
             (unsigned)DEMO_PIPELINE_TASK_STACK_SIZE);
}

static esp_err_t app_realtime_audio_chunk_sink(const uint8_t *chunk,
                                               size_t chunk_bytes,
                                               void *user_ctx)
{
    if (chunk == NULL || chunk_bytes == 0 || user_ctx == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    app_realtime_stream_ctx_t *ctx = (app_realtime_stream_ctx_t *)user_ctx;
    if (!ctx->playback_gate_open) {
        const int64_t gate_wait_start_us = esp_timer_get_time();
        while (!ctx->playback_gate_open &&
               (esp_timer_get_time() - gate_wait_start_us) <
                   ((int64_t)DEMO_REALTIME_AUDIO_GATE_WAIT_TIMEOUT_MS * 1000)) {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
        if (!ctx->playback_gate_open) {
            ESP_LOGE(TAG, "error_code=audio_gate_timeout wait_ms=%d",
                     DEMO_REALTIME_AUDIO_GATE_WAIT_TIMEOUT_MS);
            return ESP_ERR_TIMEOUT;
        }
        ctx->playback_gate_wait_us += esp_timer_get_time() - gate_wait_start_us;
        if (!ctx->playback_gate_wait_logged) {
            ctx->playback_gate_wait_logged = true;
            ESP_LOGI(TAG,
                     "stage=intro_and_audio_parallel event=release playback_gate_wait_ms=%.1f",
                     (double)ctx->playback_gate_wait_us / 1000.0);
        }
    }

    size_t written_bytes = 0;
    const int64_t enqueue_start_us = esp_timer_get_time();
    esp_err_t ret = audio_out_write_pcm_chunk_buffered(chunk, chunk_bytes, &written_bytes);
    const int64_t enqueue_us = esp_timer_get_time() - enqueue_start_us;
    ctx->callback_count++;
    ctx->total_enqueue_us += enqueue_us;
    if (enqueue_us > ctx->max_enqueue_us) {
        ctx->max_enqueue_us = enqueue_us;
    }
    if (enqueue_us > (int64_t)DEMO_REALTIME_AUDIO_ENQUEUE_WARN_MS * 1000) {
        ESP_LOGW(TAG,
                 "realtime_audio_enqueue_slow chunk_bytes=%u enqueue_ms=%.1f callback_count=%u total_bytes=%u",
                 (unsigned)chunk_bytes,
                 (double)enqueue_us / 1000.0,
                 (unsigned)ctx->callback_count,
                 (unsigned)ctx->total_bytes);
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "error_code=codec_write_failed err=%s", esp_err_to_name(ret));
        return ret;
    }

    if (!ctx->saw_first_chunk) {
        ctx->saw_first_chunk = true;
        ctx->first_chunk_us = esp_timer_get_time();
        ESP_LOGI(TAG,
                 "first_audio_byte_local_ms=%.1f",
                 (double)(ctx->first_chunk_us - ctx->pipeline_start_us) / 1000.0);
        ESP_LOGI(TAG,
                 "first_audio_play_ms=%.1f",
                 (double)(ctx->first_chunk_us - ctx->pipeline_start_us) / 1000.0);
        if (ctx->intro_end_us > 0) {
            ESP_LOGI(TAG,
                     "intro_end_to_first_audio_byte_ms=%.1f",
                     app_elapsed_ms_since(ctx->intro_end_us, ctx->first_chunk_us));
        }
        if (ctx->open_audio_done_us > 0) {
            ESP_LOGI(TAG,
                     "open_audio_to_first_audio_byte_ms=%.1f",
                     app_elapsed_ms_since(ctx->open_audio_done_us, ctx->first_chunk_us));
        }
    }
    ctx->total_bytes += written_bytes;
    return ESP_OK;
}

#if DEMO_REALTIME_INTRO_ENABLED && DEMO_REALTIME_INTRO_AUDIO_PARALLEL_ENABLED
static void app_realtime_parallel_stream_task(void *arg)
{
    app_realtime_parallel_task_t *task = (app_realtime_parallel_task_t *)arg;
    if (task == NULL || task->stream_ctx == NULL || task->metrics == NULL ||
        task->audio_stream_url[0] == '\0') {
        vTaskDelete(NULL);
        return;
    }

    task->result = cloud_client_stream_realtime_audio(task->audio_stream_url,
                                                      app_realtime_audio_chunk_sink,
                                                      task->stream_ctx,
                                                      task->metrics);
    task->done = true;
    task->task_handle = NULL;
    vTaskDelete(NULL);
}
#endif

static void app_log_stage_start(const char *stage)
{
    ESP_LOGI(TAG, "stage=%s event=start", stage);
}

static void app_log_stage_result(const char *stage, esp_err_t ret, int64_t elapsed_us)
{
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "stage=%s event=done elapsed_ms=%.1f", stage, (double)elapsed_us / 1000.0);
    } else {
        ESP_LOGE(TAG, "stage=%s event=failed err=%s elapsed_ms=%.1f",
                 stage, esp_err_to_name(ret), (double)elapsed_us / 1000.0);
    }
}

static esp_err_t app_v5_opus_uplink_pcm_sink(const uint8_t *pcm,
                                             size_t pcm_bytes,
                                             void *user_ctx)
{
    return cloud_client_opus_uplink_send_pcm((cloud_opus_uplink_t *)user_ctx, pcm, pcm_bytes);
}

static void app_log_v5_uplink_metrics(const cloud_opus_uplink_metrics_t *metrics,
                                      int64_t pipeline_start_us)
{
    if (metrics == NULL) {
        return;
    }
    const double compression_ratio =
        metrics->uplink_opus_bytes > 0
            ? (double)metrics->uplink_pcm_bytes / (double)metrics->uplink_opus_bytes
            : 0.0;
    ESP_LOGI(TAG,
             "v5_uplink_summary asr_provider=%s first_pcm_frame_ms=%.1f first_opus_frame_ms=%.1f first_ws_frame_sent_ms=%.1f last_ws_frame_sent_ms=%.1f end_sent_ms=%.1f first_ack_ms=%.1f asr_final_received_ms=%.1f done_received_ms=%.1f uplink_frame_count=%u uplink_opus_bytes=%u uplink_pcm_bytes=%u compression_ratio=%.3f heap_free=%u psram_free=%u question_text=%s error_code=%s",
             metrics->asr_provider[0] != '\0' ? metrics->asr_provider : V5_OPUS_UPLINK_ASR_PROVIDER,
             metrics->first_pcm_frame_us > 0 ? (double)metrics->first_pcm_frame_us / 1000.0 : -1.0,
             metrics->first_opus_frame_us > 0 ? (double)metrics->first_opus_frame_us / 1000.0 : -1.0,
             metrics->first_ws_frame_sent_us > 0 ? (double)metrics->first_ws_frame_sent_us / 1000.0 : -1.0,
             metrics->last_ws_frame_sent_us > 0 ? (double)metrics->last_ws_frame_sent_us / 1000.0 : -1.0,
             metrics->end_sent_us > 0 ? (double)metrics->end_sent_us / 1000.0 : -1.0,
             metrics->first_ack_us > 0 ? (double)metrics->first_ack_us / 1000.0 : -1.0,
             metrics->asr_final_received_us > 0 ? (double)metrics->asr_final_received_us / 1000.0 : -1.0,
             metrics->done_received_us > 0 ? (double)metrics->done_received_us / 1000.0 : -1.0,
             (unsigned)metrics->uplink_frame_count,
             (unsigned)metrics->uplink_opus_bytes,
             (unsigned)metrics->uplink_pcm_bytes,
             compression_ratio,
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             metrics->question_text[0] != '\0' ? metrics->question_text : "(empty)",
             metrics->error_code[0] != '\0' ? metrics->error_code : "(none)");
    ESP_LOGI(TAG,
             "v5_uplink_total_ms=%.1f",
             (double)(esp_timer_get_time() - pipeline_start_us) / 1000.0);
}

static void app_play_retry_prompt(const char *reason, const char *path)
{
    if (path == NULL || path[0] == '\0') {
        return;
    }

    ESP_LOGI(TAG, "stage=retry_prompt event=start reason=%s path=%s",
             reason != NULL ? reason : "unknown",
             path);
    const int64_t start_us = esp_timer_get_time();
    esp_err_t ret = audio_out_play_pcm_file(path,
                                            DEMO_AUDIO_SAMPLE_RATE,
                                            DEMO_AUDIO_CHANNELS,
                                            DEMO_AUDIO_BITS_PER_SAMPLE,
                                            DEMO_RECORD_RETRY_PROMPT_MAX_BYTES);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "stage=retry_prompt event=done reason=%s elapsed_ms=%.1f",
                 reason != NULL ? reason : "unknown",
                 (double)(esp_timer_get_time() - start_us) / 1000.0);
    } else {
        ESP_LOGW(TAG, "stage=retry_prompt event=failed reason=%s path=%s err=%s elapsed_ms=%.1f",
                 reason != NULL ? reason : "unknown",
                 path,
                 esp_err_to_name(ret),
                 (double)(esp_timer_get_time() - start_us) / 1000.0);
    }
}

static esp_err_t app_validate_runtime_config(void)
{
    if (DEMO_WIFI_SSID[0] == '\0') {
        ESP_LOGE(TAG, "DEMO_WIFI_SSID is empty");
        return ESP_ERR_INVALID_STATE;
    }

    if (DEMO_SERVER_BASE_URL[0] == '\0') {
        ESP_LOGE(TAG, "DEMO_SERVER_BASE_URL is empty");
        return ESP_ERR_INVALID_STATE;
    }

    if (DEMO_DEVICE_ID[0] == '\0') {
        ESP_LOGE(TAG, "DEMO_DEVICE_ID is empty");
        return ESP_ERR_INVALID_STATE;
    }

    return ESP_OK;
}

static void app_wifi_event_handler(void *arg,
                                   esp_event_base_t event_base,
                                   int32_t event_id,
                                   void *event_data)
{
    (void)arg;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_wifi_event_group, APP_WIFI_CONNECTED_BIT);
        if (s_wifi_retry_count < DEMO_WIFI_MAXIMUM_RETRY) {
            s_wifi_retry_count++;
            ESP_LOGW(TAG, "Wi-Fi disconnected, retrying (%d/%d)",
                     s_wifi_retry_count,
                     DEMO_WIFI_MAXIMUM_RETRY);
            esp_wifi_connect();
        } else {
            xEventGroupSetBits(s_wifi_event_group, APP_WIFI_FAILED_BIT);
        }
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = (const ip_event_got_ip_t *)event_data;
        s_wifi_retry_count = 0;
        ESP_LOGI(TAG, "Wi-Fi connected, IP=" IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(s_wifi_event_group, APP_WIFI_CONNECTED_BIT);
    }
}

static esp_err_t app_wifi_connect(void)
{
    esp_err_t ret = app_validate_runtime_config();
    if (ret != ESP_OK) {
        return ret;
    }

    ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to init NVS: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_netif_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to init esp_netif: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_event_loop_create_default();
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "Failed to create default event loop: %s", esp_err_to_name(ret));
        return ret;
    }

    esp_netif_t *sta_netif = esp_netif_create_default_wifi_sta();
    if (sta_netif == NULL) {
        ESP_LOGE(TAG, "Failed to create default Wi-Fi station");
        return ESP_FAIL;
    }

    wifi_init_config_t wifi_init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ret = esp_wifi_init(&wifi_init_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to init Wi-Fi: %s", esp_err_to_name(ret));
        return ret;
    }

    if (s_wifi_event_group == NULL) {
        s_wifi_event_group = xEventGroupCreate();
    }
    if (s_wifi_event_group == NULL) {
        ESP_LOGE(TAG, "Failed to create Wi-Fi event group");
        return ESP_ERR_NO_MEM;
    }
    xEventGroupClearBits(s_wifi_event_group, APP_WIFI_CONNECTED_BIT | APP_WIFI_FAILED_BIT);

    ret = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &app_wifi_event_handler, NULL);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to register Wi-Fi event handler: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &app_wifi_event_handler, NULL);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to register IP event handler: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_wifi_set_mode(WIFI_MODE_STA);
    if (ret == ESP_OK && DEMO_WIFI_PASSWORD[0] != '\0') {
        wifi_config_t wifi_cfg = {0};
        snprintf((char *)wifi_cfg.sta.ssid, sizeof(wifi_cfg.sta.ssid), "%s", DEMO_WIFI_SSID);
        snprintf((char *)wifi_cfg.sta.password, sizeof(wifi_cfg.sta.password), "%s", DEMO_WIFI_PASSWORD);
        wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
        wifi_cfg.sta.pmf_cfg.capable = true;
        wifi_cfg.sta.pmf_cfg.required = false;
        ret = esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg);
    } else if (ret == ESP_OK) {
        ESP_LOGW(TAG,
                 "DEMO_WIFI_PASSWORD is empty; using stored Wi-Fi station credentials from NVS for SSID %s",
                 DEMO_WIFI_SSID);
    }
    if (ret == ESP_OK) {
        ret = esp_wifi_start();
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start Wi-Fi station: %s", esp_err_to_name(ret));
        return ret;
    }

#if DEMO_WIFI_POWER_SAVE_NONE
    ret = esp_wifi_set_ps(WIFI_PS_NONE);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Failed to disable Wi-Fi power save: %s", esp_err_to_name(ret));
    } else {
        ESP_LOGI(TAG, "Wi-Fi power save disabled for realtime audio");
    }
#endif

    ESP_LOGI(TAG, "Connecting to Wi-Fi SSID %s", DEMO_WIFI_SSID);

    const EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                                                 APP_WIFI_CONNECTED_BIT | APP_WIFI_FAILED_BIT,
                                                 pdFALSE,
                                                 pdFALSE,
                                                 pdMS_TO_TICKS(DEMO_WIFI_CONNECT_TIMEOUT_MS));
    if ((bits & APP_WIFI_CONNECTED_BIT) != 0) {
        return ESP_OK;
    }

    if ((bits & APP_WIFI_FAILED_BIT) != 0) {
        ESP_LOGE(TAG, "Failed to connect to Wi-Fi after %d retries", DEMO_WIFI_MAXIMUM_RETRY);
        return ESP_FAIL;
    }

    ESP_LOGE(TAG, "Timed out waiting for Wi-Fi connection");
    return ESP_ERR_TIMEOUT;
}

static bool app_wifi_is_connected(void)
{
    if (s_wifi_event_group == NULL) {
        return false;
    }

    return (xEventGroupGetBits(s_wifi_event_group) & APP_WIFI_CONNECTED_BIT) != 0;
}

static esp_err_t run_trigger_pipeline(app_state_t *state)
{
    esp_err_t ret = ESP_OK;
    int64_t pipeline_start_us = esp_timer_get_time();
    uint8_t *pcm_buffer = NULL;
    uint8_t *speech_prefix = NULL;
    size_t speech_prefix_bytes = 0;
    size_t pcm_bytes = 0;
    uint8_t *wav_buffer = NULL;
    size_t wav_bytes = 0;
    char task_id[DEMO_CLOUD_TASK_ID_MAX_LEN] = {0};
    cloud_task_result_t result = {0};
    cloud_realtime_session_t realtime_session = {0};
    cloud_realtime_audio_metrics_t realtime_metrics = {0};
    cloud_opus_uplink_metrics_t opus_uplink_metrics = {0};
    app_realtime_stream_ctx_t realtime_stream_ctx = {
        .saw_first_chunk = false,
        .total_bytes = 0,
        .pipeline_start_us = pipeline_start_us,
        .first_chunk_us = 0,
        .playback_gate_open = false,
        .playback_gate_wait_logged = false,
        .playback_gate_wait_us = 0,
    };
    app_realtime_parallel_task_t realtime_parallel_task = {0};
    audio_in_wait_metrics_t wait_metrics = {0};
    audio_in_record_metrics_t record_metrics = {0};
    const char *pipeline_error_code = "unknown";
    int64_t stage_start_us = 0;
    int waiting_speech_attempt = 0;
    bool realtime_session_ready = false;
    bool v5_uplink_attempted = false;

    if (!app_wifi_is_connected()) {
        ESP_LOGE(TAG, "Wi-Fi is not connected; refusing to start pipeline");
        return ESP_ERR_INVALID_STATE;
    }

    app_log_pipeline_stack_watermark("pipeline_start");
    app_log_heap_snapshot("pipeline_start");
    ESP_LOGI(TAG, "touch_trigger_ms=0.0");
    ESP_LOGI(TAG, "v5_uplink_enabled=%d", V5_OPUS_UPLINK_WS_ENABLED);

#if DEMO_RECORD_PROMPT_ENABLED
    app_set_state(state, APP_STATE_PLAYING_PROMPT);
    ESP_LOGI(TAG, "prompt_play_start_ms=%.1f",
             (double)(esp_timer_get_time() - pipeline_start_us) / 1000.0);
    app_log_stage_start("record_prompt");
    stage_start_us = esp_timer_get_time();
    esp_err_t prompt_ret = audio_out_play_pcm_file(DEMO_RECORD_PROMPT_PATH,
                                                   DEMO_AUDIO_SAMPLE_RATE,
                                                   DEMO_AUDIO_CHANNELS,
                                                   DEMO_AUDIO_BITS_PER_SAMPLE,
                                                   DEMO_RECORD_PROMPT_MAX_BYTES);
    app_log_stage_result("record_prompt", prompt_ret, esp_timer_get_time() - stage_start_us);
    ESP_LOGI(TAG, "prompt_play_end_ms=%.1f",
             (double)(esp_timer_get_time() - pipeline_start_us) / 1000.0);
    if (prompt_ret != ESP_OK) {
        ESP_LOGW(TAG,
                 "record_prompt_failed path=%s err=%s",
                 DEMO_RECORD_PROMPT_PATH,
                 esp_err_to_name(prompt_ret));
    }
#endif

    app_set_state(state, APP_STATE_WAITING_SPEECH);
    while (true) {
        app_log_stage_start("waiting_speech");
        stage_start_us = esp_timer_get_time();
        for (int attempt = 0; attempt <= DEMO_MIC_INIT_RETRY_COUNT; ++attempt) {
            ret = audio_in_wait_for_speech_start(&speech_prefix, &speech_prefix_bytes, &wait_metrics);
            if (ret == ESP_OK || ret == DEMO_AUDIO_IN_ERR_WAIT_TIMEOUT) {
                break;
            }
            if (attempt < DEMO_MIC_INIT_RETRY_COUNT) {
                ESP_LOGW(TAG,
                         "stage=waiting_speech event=mic_init_retry attempt=%d err=%s delay_ms=%d",
                         attempt + 1,
                         esp_err_to_name(ret),
                         DEMO_MIC_INIT_RETRY_DELAY_MS);
                audio_in_deinit();
                vTaskDelay(pdMS_TO_TICKS(DEMO_MIC_INIT_RETRY_DELAY_MS));
            }
        }
        if (ret == ESP_OK) {
            ESP_LOGI(TAG,
                     "stage=waiting_speech event=speech_detected elapsed_ms=%u max_level=%u speech_prefix_bytes=%u",
                     (unsigned)wait_metrics.elapsed_ms,
                     (unsigned)wait_metrics.max_level,
                     (unsigned)wait_metrics.speech_prefix_bytes);
            ESP_LOGI(TAG, "speech_start_ms=%.1f",
                     (double)(esp_timer_get_time() - pipeline_start_us) / 1000.0);
        } else if (ret == DEMO_AUDIO_IN_ERR_WAIT_TIMEOUT) {
            ESP_LOGW(TAG,
                     "stage=waiting_speech event=timeout elapsed_ms=%u max_level=%u retry_index=%d retry_limit=%d",
                     (unsigned)wait_metrics.elapsed_ms,
                     (unsigned)wait_metrics.max_level,
                     waiting_speech_attempt,
                     DEMO_WAITING_SPEECH_RETRY_COUNT);
        }
        app_log_stage_result("waiting_speech", ret == DEMO_AUDIO_IN_ERR_WAIT_TIMEOUT ? ESP_OK : ret,
                             esp_timer_get_time() - stage_start_us);
        if (ret != DEMO_AUDIO_IN_ERR_WAIT_TIMEOUT) {
            break;
        }

        audio_in_deinit();
        if (waiting_speech_attempt < DEMO_WAITING_SPEECH_RETRY_COUNT) {
            waiting_speech_attempt++;
            ESP_LOGI(TAG,
                     "stage=waiting_speech event=retry_prompt_then_rearm retry_index=%d retry_limit=%d",
                     waiting_speech_attempt,
                     DEMO_WAITING_SPEECH_RETRY_COUNT);
            app_play_retry_prompt("waiting_timeout_retry", DEMO_RECORD_RETRY_REARM_PROMPT_PATH);
            continue;
        }

        app_play_retry_prompt("waiting_timeout_final", DEMO_RECORD_RETRY_TIMEOUT_PROMPT_PATH);
        ret = ESP_OK;
        goto cleanup;
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "stage=waiting_speech event=mic_init_retry_failed err=%s", esp_err_to_name(ret));
        audio_in_deinit();
        app_play_retry_prompt("mic_init_failed", DEMO_RECORD_RETRY_ERROR_PROMPT_PATH);
        ESP_LOGE(TAG, "Waiting for speech failed: %s", esp_err_to_name(ret));
        goto cleanup;
    }

#if V5_OPUS_UPLINK_WS_ENABLED
    if (DEMO_AUDIO_MODE == DEMO_AUDIO_MODE_V3_REALTIME) {
        cloud_opus_uplink_t *uplink = NULL;
        v5_uplink_attempted = true;
        app_set_state(state, APP_STATE_RECORDING);
        app_log_stage_start("v5_opus_uplink");
        stage_start_us = esp_timer_get_time();
        ESP_LOGI(TAG,
                 "v5_uplink_begin asr_provider=%s answer_mode=%s frame_ms=%d fallback_legacy_audio=%d",
                 V5_OPUS_UPLINK_ASR_PROVIDER,
                 V5_OPUS_UPLINK_ANSWER_MODE,
                 V5_OPUS_UPLINK_FRAME_MS,
                 V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO);
        ret = cloud_client_opus_uplink_begin(&uplink, &opus_uplink_metrics);
        if (ret == ESP_OK) {
            ret = audio_in_stream_after_speech_start(speech_prefix,
                                                     speech_prefix_bytes,
                                                     app_v5_opus_uplink_pcm_sink,
                                                     uplink,
                                                     &record_metrics);
        }
        if (ret == ESP_OK) {
            ret = cloud_client_opus_uplink_finish(uplink, &realtime_session);
            uplink = NULL;
        } else if (uplink != NULL) {
            cloud_client_opus_uplink_abort(uplink);
            uplink = NULL;
        }
        app_log_stage_result("v5_opus_uplink", ret, esp_timer_get_time() - stage_start_us);
        app_log_v5_uplink_metrics(&opus_uplink_metrics, pipeline_start_us);
        if (ret == ESP_OK) {
            realtime_session_ready = true;
            ESP_LOGI(TAG,
                     "stage=v5_opus_uplink session_id=%s audio_stream_url=%s pcm_bytes=%u vad_stopped=%d voice_started=%d max_level=%u",
                     realtime_session.session_id,
                     realtime_session.audio_stream_url,
                     (unsigned)record_metrics.pcm_bytes,
                     record_metrics.vad_stopped,
                     record_metrics.voice_started,
                     (unsigned)record_metrics.max_level);
        } else if (V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO) {
            const char *fallback_reason = opus_uplink_metrics.error_code[0] != '\0'
                                              ? opus_uplink_metrics.error_code
                                              : "v5_opus_uplink_failed";
            ESP_LOGW(TAG,
                     "legacy_audio_fallback=true fallback_to_legacy_audio=true fallback_reason=%s error_code=%s err=%s",
                     fallback_reason,
                     fallback_reason,
                     esp_err_to_name(ret));
            audio_in_deinit();
            speech_prefix_bytes = 0;
        } else if (V5_OPUS_UPLINK_BEHAVIOR_FALLBACK_ENABLED) {
            pipeline_error_code = opus_uplink_metrics.error_code[0] != '\0'
                                      ? opus_uplink_metrics.error_code
                                      : "v5_opus_uplink_failed";
            ESP_LOGW(TAG,
                     "v5_uplink_failed error_code=%s fallback_behavior=local_prompt legacy_audio_fallback=false err=%s",
                     pipeline_error_code,
                     esp_err_to_name(ret));
            audio_in_deinit();
            app_play_retry_prompt("v5_uplink_failed", DEMO_RECORD_RETRY_ERROR_PROMPT_PATH);
            ret = ESP_OK;
            goto cleanup;
        } else {
            pipeline_error_code = opus_uplink_metrics.error_code[0] != '\0'
                                      ? opus_uplink_metrics.error_code
                                      : "v5_opus_uplink_failed";
            ESP_LOGE(TAG,
                     "v5_uplink_failed error_code=%s fallback_behavior=disabled legacy_audio_fallback=false err=%s",
                     pipeline_error_code,
                     esp_err_to_name(ret));
            goto cleanup;
        }
    }
#endif

    if (realtime_session_ready) {
        goto submit_complete;
    }

    app_set_state(state, APP_STATE_RECORDING);
    ESP_LOGI(TAG,
             "stage=recording event=start reason=speech_detected record_budget_ms=%u",
             (unsigned)DEMO_RECORD_AFTER_SPEECH_MAX_MS);
    app_log_stage_start("record");
    stage_start_us = esp_timer_get_time();
    if (v5_uplink_attempted && speech_prefix_bytes == 0) {
        ret = audio_in_record_fixed_duration(&pcm_buffer, &pcm_bytes);
        if (ret == ESP_OK) {
            memset(&record_metrics, 0, sizeof(record_metrics));
            record_metrics.voice_started = true;
            record_metrics.pcm_bytes = pcm_bytes;
        }
    } else {
        ret = audio_in_record_after_speech_start(speech_prefix,
                                                 speech_prefix_bytes,
                                                 &pcm_buffer,
                                                 &pcm_bytes,
                                                 &record_metrics);
    }
    app_log_stage_result("record", ret, esp_timer_get_time() - stage_start_us);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Recording failed: %s", esp_err_to_name(ret));
        goto cleanup;
    }
    ESP_LOGI(TAG,
             "stage=record pcm_bytes=%u vad_stopped=%d voice_started=%d max_level=%u",
             (unsigned)pcm_bytes,
             record_metrics.vad_stopped,
             record_metrics.voice_started,
             (unsigned)record_metrics.max_level);

    app_set_state(state, APP_STATE_POSTING_SESSION);
    app_log_stage_start(DEMO_AUDIO_MODE == DEMO_AUDIO_MODE_V3_REALTIME ? "post_session" : "upload");
    stage_start_us = esp_timer_get_time();
    if (DEMO_AUDIO_MODE == DEMO_AUDIO_MODE_V3_REALTIME) {
        ret = cloud_client_submit_realtime_session(pcm_buffer, pcm_bytes, &realtime_session);
    } else {
        ret = cloud_client_submit_pcm_task(pcm_buffer, pcm_bytes, task_id, sizeof(task_id));
    }
    app_log_stage_result(DEMO_AUDIO_MODE == DEMO_AUDIO_MODE_V3_REALTIME ? "post_session" : "upload",
                         ret,
                         esp_timer_get_time() - stage_start_us);
    if (ret != ESP_OK) {
        pipeline_error_code = "session_create_failed";
        ESP_LOGE(TAG, "error_code=%s err=%s", pipeline_error_code, esp_err_to_name(ret));
        goto cleanup;
    }
    if (DEMO_AUDIO_MODE == DEMO_AUDIO_MODE_V3_REALTIME) {
        ESP_LOGI(TAG, "stage=post_session session_id=%s audio_stream_url=%s",
                 realtime_session.session_id,
                 realtime_session.audio_stream_url);
    } else {
        ESP_LOGI(TAG, "stage=upload task_id=%s", task_id);
    }
    free(pcm_buffer);
    pcm_buffer = NULL;
    app_log_heap_snapshot("after_record_buffer_free");

submit_complete:
    if (DEMO_AUDIO_MODE == DEMO_AUDIO_MODE_V3_REALTIME) {
        bool parallel_intro_started = false;
#if DEMO_REALTIME_INTRO_ENABLED && DEMO_REALTIME_INTRO_AUDIO_PARALLEL_ENABLED
        snprintf(realtime_parallel_task.audio_stream_url,
                 sizeof(realtime_parallel_task.audio_stream_url),
                 "%s",
                 realtime_session.audio_stream_url);
        realtime_parallel_task.stream_ctx = &realtime_stream_ctx;
        realtime_parallel_task.metrics = &realtime_metrics;
        app_log_stage_start("intro_and_audio_parallel");
        if (xTaskCreate(app_realtime_parallel_stream_task,
                        "rt_audio_bg",
                        DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE,
                        &realtime_parallel_task,
                        DEMO_PIPELINE_TASK_PRIORITY,
                        &realtime_parallel_task.task_handle) == pdPASS) {
            parallel_intro_started = true;
            ESP_LOGI(TAG, "stage=intro_and_audio_parallel event=stream_opened");
        } else {
            ESP_LOGW(TAG, "stage=intro_and_audio_parallel event=stream_open_failed_fallback");
        }
#endif
#if DEMO_REALTIME_INTRO_ENABLED
        app_set_state(state, APP_STATE_PLAYING);
        app_log_stage_start("intro");
        stage_start_us = esp_timer_get_time();
        esp_err_t intro_ret = audio_out_play_pcm_file(DEMO_REALTIME_INTRO_PATH,
                                                      DEMO_AUDIO_SAMPLE_RATE,
                                                      DEMO_AUDIO_CHANNELS,
                                                      DEMO_AUDIO_BITS_PER_SAMPLE,
                                                      DEMO_REALTIME_INTRO_MAX_BYTES);
        app_log_stage_result("intro", intro_ret, esp_timer_get_time() - stage_start_us);
        realtime_stream_ctx.intro_end_us = esp_timer_get_time();
        if (intro_ret != ESP_OK) {
            ESP_LOGW(TAG, "realtime_intro_failed err=%s; continuing with cloud audio",
                     esp_err_to_name(intro_ret));
        }
#endif

        app_set_state(state, APP_STATE_OPENING_AUDIO);
        app_log_stage_start("open_audio");
        stage_start_us = esp_timer_get_time();
        ret = audio_out_open_pcm_stream(DEMO_AUDIO_SAMPLE_RATE,
                                        DEMO_AUDIO_CHANNELS,
                                        DEMO_AUDIO_BITS_PER_SAMPLE);
        app_log_stage_result("open_audio", ret, esp_timer_get_time() - stage_start_us);
        realtime_stream_ctx.open_audio_done_us = esp_timer_get_time();
        if (ret != ESP_OK) {
            pipeline_error_code = "codec_open_failed";
            ESP_LOGE(TAG, "error_code=%s err=%s", pipeline_error_code, esp_err_to_name(ret));
            goto cleanup;
        }

        app_set_state(state, APP_STATE_STREAMING_AUDIO);
        app_log_stage_start("stream_audio");
        app_log_pipeline_stack_watermark("before_stream_audio");
        stage_start_us = esp_timer_get_time();
        if (parallel_intro_started) {
            realtime_stream_ctx.playback_gate_open = true;
            const int64_t parallel_wait_start_us = esp_timer_get_time();
            while (!realtime_parallel_task.done &&
                   (esp_timer_get_time() - parallel_wait_start_us) <
                       ((int64_t)DEMO_REALTIME_AUDIO_TASK_JOIN_TIMEOUT_MS * 1000)) {
                vTaskDelay(pdMS_TO_TICKS(10));
            }
            if (!realtime_parallel_task.done) {
                ret = ESP_ERR_TIMEOUT;
                ESP_LOGE(TAG,
                         "stage=intro_and_audio_parallel event=wait_timeout join_timeout_ms=%d",
                         DEMO_REALTIME_AUDIO_TASK_JOIN_TIMEOUT_MS);
                if (realtime_parallel_task.task_handle != NULL) {
                    vTaskDelete(realtime_parallel_task.task_handle);
                    realtime_parallel_task.task_handle = NULL;
                }
            } else {
                ret = realtime_parallel_task.result;
            }
        } else {
            realtime_stream_ctx.playback_gate_open = true;
            ret = cloud_client_stream_realtime_audio(realtime_session.audio_stream_url,
                                                     app_realtime_audio_chunk_sink,
                                                     &realtime_stream_ctx,
                                                     &realtime_metrics);
        }
        const int64_t stream_end_us = esp_timer_get_time();
        app_log_pipeline_stack_watermark("after_stream_audio");
        app_log_stage_result("stream_audio", ret, stream_end_us - stage_start_us);
        const double avg_inter_chunk_gap_ms =
            realtime_metrics.chunk_count > 1
                ? (double)realtime_metrics.total_inter_chunk_gap_us /
                      (double)(realtime_metrics.chunk_count - 1) / 1000.0
                : 0.0;
        ESP_LOGI(TAG,
                 "session_id=%s http_status=%d audio_format=%s audio_packetization=%s headers_validated=%s audio_connect_ms=%.1f first_chunk_ms=%.1f first_audio_byte_local_ms=%.1f intro_end_to_first_audio_byte_ms=%.1f open_audio_to_first_audio_byte_ms=%.1f playback_end_ms=%.1f total_stream_bytes=%u chunk_count=%u packet_count=%u seq_gap_count=%u first_chunk_bytes=%u last_chunk_bytes=%u max_inter_chunk_gap_ms=%.1f avg_inter_chunk_gap_ms=%.1f max_enqueue_ms=%.1f avg_enqueue_ms=%.1f receive_queue_peak=%u receive_queue_full_count=%u decode_queue_peak=%u decode_queue_full_count=%u decode_packet_count=%u decode_fail_count=%u decode_avg_ms=%.1f decode_max_ms=%.1f pcm_queue_drain_ms=%.1f",
                 realtime_session.session_id,
                 realtime_metrics.http_status,
                 realtime_metrics.audio_format[0] != '\0' ? realtime_metrics.audio_format : "pcm",
                 realtime_metrics.audio_packetization[0] != '\0' ? realtime_metrics.audio_packetization : "legacy",
                 realtime_metrics.headers_validated ? "true" : "false",
                 (double)realtime_metrics.connect_elapsed_us / 1000.0,
                 (double)realtime_metrics.first_chunk_elapsed_us / 1000.0,
                 realtime_stream_ctx.saw_first_chunk
                     ? app_elapsed_ms_since(realtime_stream_ctx.pipeline_start_us,
                                            realtime_stream_ctx.first_chunk_us)
                     : -1.0,
                 (realtime_stream_ctx.saw_first_chunk && realtime_stream_ctx.intro_end_us > 0)
                     ? app_elapsed_ms_since(realtime_stream_ctx.intro_end_us,
                                            realtime_stream_ctx.first_chunk_us)
                     : -1.0,
                 (realtime_stream_ctx.saw_first_chunk && realtime_stream_ctx.open_audio_done_us > 0)
                     ? app_elapsed_ms_since(realtime_stream_ctx.open_audio_done_us,
                                            realtime_stream_ctx.first_chunk_us)
                     : -1.0,
                 realtime_stream_ctx.saw_first_chunk
                     ? app_elapsed_ms_since(realtime_stream_ctx.pipeline_start_us, stream_end_us)
                     : -1.0,
                 (unsigned)realtime_metrics.total_audio_bytes,
                 (unsigned)realtime_metrics.chunk_count,
                 (unsigned)realtime_metrics.packet_count,
                 (unsigned)realtime_metrics.seq_gap_count,
                 (unsigned)realtime_metrics.first_chunk_bytes,
                 (unsigned)realtime_metrics.last_chunk_bytes,
                 (double)realtime_metrics.max_inter_chunk_gap_us / 1000.0,
                 avg_inter_chunk_gap_ms,
                 (double)realtime_stream_ctx.max_enqueue_us / 1000.0,
                 realtime_stream_ctx.callback_count > 0
                     ? (double)realtime_stream_ctx.total_enqueue_us /
                           (double)realtime_stream_ctx.callback_count / 1000.0
                     : 0.0,
                 (unsigned)realtime_metrics.receive_queue_peak,
                 (unsigned)realtime_metrics.receive_queue_full_count,
                 (unsigned)realtime_metrics.decode_queue_peak,
                 (unsigned)realtime_metrics.decode_queue_full_count,
                 (unsigned)realtime_metrics.decode_packet_count,
                 (unsigned)realtime_metrics.decode_fail_count,
                 realtime_metrics.decode_packet_count > 0
                     ? (double)realtime_metrics.decode_total_us /
                           (double)realtime_metrics.decode_packet_count / 1000.0
                     : 0.0,
                 (double)realtime_metrics.decode_max_us / 1000.0,
                 (double)realtime_metrics.pcm_queue_drain_us / 1000.0);
        audio_out_jitter_metrics_t jitter_metrics = {0};
        esp_err_t close_ret = audio_out_close_pcm_stream_with_metrics(&jitter_metrics);
        ESP_LOGI(TAG,
                 "realtime_audio_summary session_id=%s total_bytes=%u chunk_count=%u max_gap_ms=%.1f avg_gap_ms=%.1f prebuffer_wait_ms=%.1f playback_actual_start_ms=%.1f underrun_count=%u underrun_ms=%.1f min_level=%u max_level=%u total_in=%u total_out=%u",
                 realtime_session.session_id,
                 (unsigned)realtime_metrics.total_audio_bytes,
                 (unsigned)realtime_metrics.chunk_count,
                 (double)realtime_metrics.max_inter_chunk_gap_us / 1000.0,
                 avg_inter_chunk_gap_ms,
                 (double)jitter_metrics.prebuffer_wait_us / 1000.0,
                 jitter_metrics.playback_started
                     ? app_elapsed_ms_since(realtime_stream_ctx.pipeline_start_us,
                                            jitter_metrics.playback_start_us)
                     : -1.0,
                 (unsigned)jitter_metrics.underrun_count,
                 (double)jitter_metrics.underrun_us / 1000.0,
                 (unsigned)jitter_metrics.min_level,
                 (unsigned)jitter_metrics.max_level,
                 (unsigned)jitter_metrics.total_in,
                 (unsigned)jitter_metrics.total_out);
        if (ret == ESP_OK && close_ret != ESP_OK) {
            ret = close_ret;
        }
        app_log_heap_snapshot("after_audio_close");
        if (ret != ESP_OK) {
            if (ret == DEMO_CLOUD_ERR_AUDIO_HEADER_MISMATCH) {
                pipeline_error_code = "audio_header_mismatch";
            } else if (ret == DEMO_CLOUD_ERR_AUDIO_STREAM_EARLY_EOF) {
                pipeline_error_code = "early_eof";
            } else if (realtime_stream_ctx.saw_first_chunk) {
                pipeline_error_code = "audio_stream_read_failed";
            } else {
                pipeline_error_code = "audio_connect_failed";
            }
            ESP_LOGE(TAG, "error_code=%s err=%s", pipeline_error_code, esp_err_to_name(ret));
            goto cleanup;
        }

        app_set_state(state, APP_STATE_DONE);
        goto cleanup;
    }

    app_set_state(state, APP_STATE_POLLING);
    app_log_stage_start("poll");
    stage_start_us = esp_timer_get_time();
    ret = cloud_client_poll_task(task_id,
                                 &result,
                                 DEMO_CLOUD_POLL_TIMEOUT_MS,
                                 DEMO_CLOUD_POLL_INTERVAL_MS);
    app_log_stage_result("poll", ret, esp_timer_get_time() - stage_start_us);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Polling failed for task %s: %s", task_id, esp_err_to_name(ret));
        goto cleanup;
    }

    ESP_LOGI(TAG, "question_text: %s",
             result.question_text[0] != '\0' ? result.question_text : "(empty)");
    if (result.error_code[0] != '\0') {
        ESP_LOGI(TAG, "error_code: %s", result.error_code);
    }

    if (strcmp(result.status, "failed") == 0) {
        ESP_LOGE(TAG, "Cloud task reported failed status");
        ret = ESP_FAIL;
        pipeline_error_code = result.error_code[0] != '\0' ? result.error_code : "cloud_task_failed";
        goto cleanup;
    }

    if (result.audio_url[0] == '\0') {
        ESP_LOGE(TAG, "Cloud task completed without audio_url");
        ret = ESP_FAIL;
        pipeline_error_code = "audio_url_missing";
        goto cleanup;
    }

    app_set_state(state, APP_STATE_DOWNLOADING);
    app_log_stage_start("download");
    stage_start_us = esp_timer_get_time();
    ret = audio_out_download_wav_url(result.audio_url, &wav_buffer, &wav_bytes);
    app_log_stage_result("download", ret, esp_timer_get_time() - stage_start_us);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Download failed: %s", esp_err_to_name(ret));
        pipeline_error_code = "audio_download_failed";
        goto cleanup;
    }

    ESP_LOGI(TAG, "Downloaded WAV: %u bytes", (unsigned)wav_bytes);

    app_set_state(state, APP_STATE_PLAYING);
    app_log_stage_start("play");
    stage_start_us = esp_timer_get_time();
    ret = audio_out_play_wav_buffer(wav_buffer, wav_bytes);
    app_log_stage_result("play", ret, esp_timer_get_time() - stage_start_us);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Playback failed: %s", esp_err_to_name(ret));
        pipeline_error_code = "codec_write_failed";
        goto cleanup;
    }

cleanup:
    app_log_pipeline_stack_watermark("cleanup");
    app_log_heap_snapshot("cleanup");
    realtime_stream_ctx.playback_gate_open = true;
    if (realtime_parallel_task.task_handle != NULL && !realtime_parallel_task.done) {
        vTaskDelete(realtime_parallel_task.task_handle);
        realtime_parallel_task.task_handle = NULL;
    }
    free(speech_prefix);
    free(pcm_buffer);
    free(wav_buffer);
    if (DEMO_AUDIO_MODE == DEMO_AUDIO_MODE_V3_REALTIME) {
        (void)audio_out_close_pcm_stream();
    }
    app_cleanup_pipeline_resources();
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "pipeline result=ok total_elapsed_ms=%.1f",
                 (double)(esp_timer_get_time() - pipeline_start_us) / 1000.0);
        app_set_state(state, APP_STATE_IDLE);
    } else {
        ESP_LOGE(TAG, "pipeline result=failed error_code=%s total_elapsed_ms=%.1f",
                 pipeline_error_code,
                 (double)(esp_timer_get_time() - pipeline_start_us) / 1000.0);
        app_set_state(state, APP_STATE_ERROR);
        app_set_state(state, APP_STATE_IDLE);
    }
    return ret;
}

static void app_pipeline_task(void *arg)
{
    app_pipeline_task_args_t *task_args = (app_pipeline_task_args_t *)arg;
    if (task_args != NULL) {
        ESP_LOGI(TAG, "pipeline task started for trigger=%s x=%u y=%u",
                 trigger_input_source_name(task_args->event.type),
                 (unsigned)task_args->event.x,
                 (unsigned)task_args->event.y);
    }

    (void)run_trigger_pipeline(&s_app_state);

    free(task_args);
    s_pipeline_task_handle = NULL;
    s_last_pipeline_finish_us = esp_timer_get_time();
    ESP_LOGI(TAG, "pipeline task finished");
    vTaskDelete(NULL);
}

static esp_err_t app_start_pipeline_task(const trigger_event_t *event)
{
    if (event == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_pipeline_task_handle != NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    app_pipeline_task_args_t *task_args = calloc(1, sizeof(*task_args));
    if (task_args == NULL) {
        return ESP_ERR_NO_MEM;
    }
    task_args->event = *event;

    BaseType_t ok = xTaskCreate(app_pipeline_task,
                                "audio_pipeline",
                                DEMO_PIPELINE_TASK_STACK_SIZE,
                                task_args,
                                DEMO_PIPELINE_TASK_PRIORITY,
                                &s_pipeline_task_handle);
    if (ok != pdPASS) {
        free(task_args);
        s_pipeline_task_handle = NULL;
        return ESP_FAIL;
    }

    return ESP_OK;
}

static bool app_ota_manifest_idle_ready(int64_t now_us)
{
    if (s_app_state != APP_STATE_IDLE || s_pipeline_task_handle != NULL ||
        s_ota_manifest_task_handle != NULL) {
        return false;
    }
    if (!app_wifi_is_connected()) {
        return false;
    }
    if (s_last_pipeline_finish_us > 0 &&
        now_us - s_last_pipeline_finish_us < (int64_t)DEMO_OTA_IDLE_AFTER_WS_DELAY_MS * 1000) {
        return false;
    }
    return true;
}

#if DEMO_OTA_BOOT_SWITCH_ENABLED
static const char *app_partition_label_or_empty(const esp_partition_t *partition)
{
    return partition != NULL ? partition->label : "";
}

typedef struct {
    bool pending;
    char release_id[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char version[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char partition_label[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char sha256[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char last_stage[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    uint32_t partition_address;
} app_ota_p3c_pending_t;

#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
static volatile bool s_ota_rollback_validation_pending = false;
static volatile bool s_ota_rollback_business_ready = false;
static TaskHandle_t s_ota_rollback_validation_task_handle = NULL;
static TaskHandle_t s_ota_rollback_timeout_task_handle = NULL;
static app_ota_p3c_pending_t s_ota_rollback_pending = {0};
static void app_ota_rollback_validation_task(void *arg);
static void app_ota_rollback_validation_timeout_task(void *arg);
#endif

static const char *app_reset_reason_to_string(esp_reset_reason_t reason)
{
    switch (reason) {
    case ESP_RST_POWERON:
        return "poweron";
    case ESP_RST_EXT:
        return "external_reset";
    case ESP_RST_SW:
        return "software_reset";
    case ESP_RST_PANIC:
        return "panic";
    case ESP_RST_INT_WDT:
        return "interrupt_watchdog";
    case ESP_RST_TASK_WDT:
        return "task_watchdog";
    case ESP_RST_WDT:
        return "watchdog";
    case ESP_RST_DEEPSLEEP:
        return "deepsleep";
    case ESP_RST_BROWNOUT:
        return "brownout";
    case ESP_RST_SDIO:
        return "sdio";
    case ESP_RST_UNKNOWN:
    default:
        return "unknown";
    }
}

static esp_err_t app_ota_p3c_clear_pending(void)
{
    nvs_handle_t handle = 0;
    esp_err_t ret = nvs_open(APP_OTA_P3C_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (ret == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    if (ret != ESP_OK) {
        return ret;
    }
    ret = nvs_erase_all(handle);
    if (ret == ESP_OK || ret == ESP_ERR_NVS_NOT_FOUND) {
        ret = nvs_commit(handle);
    }
    nvs_close(handle);
    return ret;
}

static esp_err_t app_ota_p3c_store_pending(const cloud_ota_update_t *update,
                                           const cloud_ota_artifact_verify_t *verify)
{
    if (update == NULL || verify == NULL || verify->partition_label[0] == '\0' ||
        verify->partition_address == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle = 0;
    esp_err_t ret = nvs_open(APP_OTA_P3C_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = nvs_set_u8(handle, APP_OTA_P3C_KEY_PENDING, 1);
    }
    if (ret == ESP_OK) {
        ret = nvs_set_str(handle, APP_OTA_P3C_KEY_RELEASE, update->release_id);
    }
    if (ret == ESP_OK) {
        ret = nvs_set_str(handle, APP_OTA_P3C_KEY_VERSION, update->version);
    }
    if (ret == ESP_OK) {
        ret = nvs_set_str(handle, APP_OTA_P3C_KEY_LABEL, verify->partition_label);
    }
    if (ret == ESP_OK) {
        ret = nvs_set_u32(handle, APP_OTA_P3C_KEY_ADDRESS, verify->partition_address);
    }
    if (ret == ESP_OK) {
        ret = nvs_set_str(handle, APP_OTA_P3C_KEY_SHA256, verify->sha256);
    }
    if (ret == ESP_OK) {
        ret = nvs_set_str(handle, APP_OTA_P3C_KEY_LAST_STAGE, "boot_switch_pending");
    }
    if (ret == ESP_OK) {
        ret = nvs_commit(handle);
    }
    nvs_close(handle);
    return ret;
}

static esp_err_t app_ota_p3c_load_pending(app_ota_p3c_pending_t *pending)
{
    if (pending == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(pending, 0, sizeof(*pending));

    nvs_handle_t handle = 0;
    esp_err_t ret = nvs_open(APP_OTA_P3C_NVS_NAMESPACE, NVS_READONLY, &handle);
    if (ret != ESP_OK) {
        return ret;
    }

    uint8_t pending_flag = 0;
    ret = nvs_get_u8(handle, APP_OTA_P3C_KEY_PENDING, &pending_flag);
    if (ret != ESP_OK || pending_flag == 0) {
        nvs_close(handle);
        return ret == ESP_OK ? ESP_ERR_NOT_FOUND : ret;
    }

    size_t len = sizeof(pending->release_id);
    ret = nvs_get_str(handle, APP_OTA_P3C_KEY_RELEASE, pending->release_id, &len);
    if (ret == ESP_OK) {
        len = sizeof(pending->version);
        ret = nvs_get_str(handle, APP_OTA_P3C_KEY_VERSION, pending->version, &len);
    }
    if (ret == ESP_OK) {
        len = sizeof(pending->partition_label);
        ret = nvs_get_str(handle, APP_OTA_P3C_KEY_LABEL, pending->partition_label, &len);
    }
    if (ret == ESP_OK) {
        ret = nvs_get_u32(handle, APP_OTA_P3C_KEY_ADDRESS, &pending->partition_address);
    }
    if (ret == ESP_OK) {
        len = sizeof(pending->sha256);
        ret = nvs_get_str(handle, APP_OTA_P3C_KEY_SHA256, pending->sha256, &len);
    }
    if (ret == ESP_OK) {
        len = sizeof(pending->last_stage);
        esp_err_t stage_ret = nvs_get_str(handle, APP_OTA_P3C_KEY_LAST_STAGE, pending->last_stage, &len);
        if (stage_ret == ESP_ERR_NVS_NOT_FOUND) {
            pending->last_stage[0] = '\0';
        } else {
            ret = stage_ret;
        }
    }
    nvs_close(handle);
    if (ret != ESP_OK) {
        return ret;
    }
    pending->pending = true;
    return ESP_OK;
}

static esp_err_t app_ota_p3c_store_last_stage(const char *last_stage)
{
    if (last_stage == NULL || last_stage[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle = 0;
    esp_err_t ret = nvs_open(APP_OTA_P3C_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (ret != ESP_OK) {
        return ret;
    }

    uint8_t pending_flag = 0;
    ret = nvs_get_u8(handle, APP_OTA_P3C_KEY_PENDING, &pending_flag);
    if (ret == ESP_OK && pending_flag != 0) {
        ret = nvs_set_str(handle, APP_OTA_P3C_KEY_LAST_STAGE, last_stage);
        if (ret == ESP_OK) {
            ret = nvs_commit(handle);
        }
    }
    nvs_close(handle);
    return ret;
}

static esp_err_t app_ota_find_partition_from_verify(const cloud_ota_artifact_verify_t *verify,
                                                    const esp_partition_t **partition)
{
    if (verify == NULL || partition == NULL || verify->partition_label[0] == '\0' ||
        verify->partition_subtype < 0 || verify->partition_address == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    const esp_partition_t *found =
        esp_partition_find_first(ESP_PARTITION_TYPE_APP,
                                 (esp_partition_subtype_t)verify->partition_subtype,
                                 verify->partition_label);
    if (found == NULL || found->address != verify->partition_address) {
        return ESP_ERR_NOT_FOUND;
    }
    *partition = found;
    return ESP_OK;
}
#endif /* DEMO_OTA_BOOT_SWITCH_ENABLED */

typedef struct {
    esp_ota_handle_t handle;
    bool handle_started;
} app_ota_partition_write_ctx_t;

static const char *app_validate_ota_update_for_partition_write(const cloud_ota_update_t *update)
{
    if (update == NULL) {
        return "missing_update";
    }
    if (update->url[0] == '\0') {
        return "missing_url";
    }
    if (update->size <= 0) {
        return "missing_size";
    }
    if (update->sha256[0] == '\0') {
        return "missing_sha256";
    }
    if (update->release_id[0] == '\0') {
        return "missing_release_id";
    }
    if (update->target[0] == '\0') {
        return "missing_target";
    }
    if (strcmp(update->target, "esp32s3") != 0) {
        return "unsupported_target";
    }
    return NULL;
}

static void app_ota_result_set_partition_info(cloud_ota_artifact_verify_t *result,
                                              const esp_partition_t *partition)
{
    if (result == NULL || partition == NULL) {
        return;
    }
    snprintf(result->partition_label, sizeof(result->partition_label), "%s", partition->label);
    result->partition_subtype = (int)partition->subtype;
    result->partition_address = partition->address;
}

static esp_err_t app_ota_partition_write_chunk(const uint8_t *chunk,
                                               size_t chunk_bytes,
                                               void *user_ctx)
{
    app_ota_partition_write_ctx_t *ctx = (app_ota_partition_write_ctx_t *)user_ctx;
    if (chunk == NULL || chunk_bytes == 0 || ctx == NULL || !ctx->handle_started) {
        return ESP_ERR_INVALID_ARG;
    }
    return esp_ota_write(ctx->handle, chunk, chunk_bytes);
}

static esp_err_t app_write_ota_inactive_partition(const cloud_ota_update_t *update,
                                                  cloud_ota_artifact_verify_t *result,
                                                  char *error_code,
                                                  size_t error_code_size,
                                                  char *error_message,
                                                  size_t error_message_size)
{
    if (result == NULL || error_code == NULL || error_code_size == 0 ||
        error_message == NULL || error_message_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(result, 0, sizeof(*result));
    result->partition_subtype = -1;
    error_code[0] = '\0';
    error_message[0] = '\0';

    const char *validation_error = app_validate_ota_update_for_partition_write(update);
    if (validation_error != NULL) {
        snprintf(error_code, error_code_size, "%s", validation_error);
        snprintf(error_message, error_message_size, "ota manifest missing required field");
        if (update != NULL) {
            result->expected_size = update->size;
            snprintf(result->expected_sha256, sizeof(result->expected_sha256), "%s", update->sha256);
        }
        return DEMO_CLOUD_ERR_INVALID_RESPONSE;
    }

    const esp_partition_t *running = esp_ota_get_running_partition();
    const esp_partition_t *partition = esp_ota_get_next_update_partition(NULL);
    if (running == NULL || partition == NULL) {
        snprintf(error_code, error_code_size, "%s", "partition_not_found");
        snprintf(error_message, error_message_size, "ota partition lookup failed");
        result->expected_size = update->size;
        snprintf(result->expected_sha256, sizeof(result->expected_sha256), "%s", update->sha256);
        return ESP_ERR_NOT_FOUND;
    }
    app_ota_result_set_partition_info(result, partition);
    result->expected_size = update->size;
    snprintf(result->expected_sha256, sizeof(result->expected_sha256), "%s", update->sha256);

#if DEMO_OTA_BOOT_SWITCH_ENABLED
    const esp_partition_t *boot_before = esp_ota_get_boot_partition();
    ESP_LOGI(TAG,
             "stage=ota_partition_write event=start release_id=%s running_partition=%s update_partition=%s boot_partition_before=%s partition_label=%s partition_subtype=%d partition_address=0x%lx expected_size=%d expected_sha256=%s action=write_switch_reboot no_boot_switch=0 reboot_scheduled=0",
             update->release_id,
             running->label,
             partition->label,
             app_partition_label_or_empty(boot_before),
             result->partition_label,
             result->partition_subtype,
             (unsigned long)result->partition_address,
             result->expected_size,
             result->expected_sha256);
#else
    ESP_LOGI(TAG,
             "stage=ota_partition_write event=start release_id=%s running_partition=%s update_partition=%s partition_label=%s partition_subtype=%d partition_address=0x%lx expected_size=%d expected_sha256=%s action=write_inactive_only no_boot_switch=1 no_reboot=1",
             update->release_id,
             running->label,
             partition->label,
             result->partition_label,
             result->partition_subtype,
             (unsigned long)result->partition_address,
             result->expected_size,
             result->expected_sha256);
#endif

    if (partition == running || partition->address == running->address) {
        snprintf(error_code, error_code_size, "%s", "update_partition_is_running");
        snprintf(error_message, error_message_size, "ota update partition matches running partition");
        return ESP_ERR_INVALID_STATE;
    }

    app_ota_partition_write_ctx_t write_ctx = {0};
    esp_err_t ret = esp_ota_begin(partition, update->size, &write_ctx.handle);
    if (ret != ESP_OK) {
        snprintf(error_code, error_code_size, "%s", esp_err_to_name(ret));
        snprintf(error_message, error_message_size, "ota begin failed");
        return ret;
    }
    write_ctx.handle_started = true;

    ret = cloud_client_stream_ota_artifact(update,
                                           result,
                                           app_ota_partition_write_chunk,
                                           &write_ctx);
    app_ota_result_set_partition_info(result, partition);
    if (ret == ESP_OK) {
        ret = esp_ota_end(write_ctx.handle);
        write_ctx.handle_started = false;
        if (ret != ESP_OK) {
            snprintf(error_code, error_code_size, "%s", esp_err_to_name(ret));
            snprintf(error_message, error_message_size, "ota end failed");
            return ret;
        }
    } else {
        if (write_ctx.handle_started) {
            (void)esp_ota_abort(write_ctx.handle);
            write_ctx.handle_started = false;
        }
        snprintf(error_code, error_code_size, "%s", esp_err_to_name(ret));
        snprintf(error_message, error_message_size, "ota artifact partition write failed");
        return ret;
    }

    if (result->bytes_written != update->size) {
        snprintf(error_code, error_code_size, "%s", "bytes_written_mismatch");
        snprintf(error_message, error_message_size, "ota written byte count mismatch");
        return DEMO_CLOUD_ERR_AUDIO_STREAM_EARLY_EOF;
    }
    if (strcasecmp(result->sha256, update->sha256) != 0) {
        snprintf(error_code, error_code_size, "%s", "sha256_mismatch");
        snprintf(error_message, error_message_size, "ota artifact sha256 mismatch");
        return DEMO_CLOUD_ERR_INVALID_RESPONSE;
    }
    return ESP_OK;
}

#if DEMO_OTA_BOOT_SWITCH_ENABLED
static esp_err_t app_submit_ota_boot_report(const char *stage,
                                            bool ok,
                                            const cloud_ota_update_t *update,
                                            const char *app_version,
                                            const char *error_code,
                                            const char *error_message,
                                            const char *boot_partition_before,
                                            const char *boot_partition_after_set,
                                            const char *running_partition_after_reboot,
                                            const char *reboot_reason,
                                            const char *last_stage,
                                            int *http_status)
{
    cloud_ota_report_t report = {
        .stage = stage,
        .ok = ok,
        .target = update != NULL && update->target[0] != '\0' ? update->target : "esp32s3",
        .from_version = app_version,
        .to_version = update != NULL ? update->version : NULL,
        .release_id = update != NULL ? update->release_id : NULL,
        .error_code = ok ? NULL : error_code,
        .error_message = ok ? NULL : error_message,
        .free_heap = (int)heap_caps_get_free_size(MALLOC_CAP_8BIT),
        .rssi = 0,
        .boot_partition_before = boot_partition_before,
        .boot_partition_after_set = boot_partition_after_set,
        .running_partition_after_reboot = running_partition_after_reboot,
        .reboot_reason = reboot_reason,
        .last_stage = last_stage,
        .verify = NULL,
    };
    return cloud_client_submit_ota_report(&report, http_status);
}

static esp_err_t app_submit_ota_rollback_recovered_report(const app_ota_p3c_pending_t *pending,
                                                          const char *app_version,
                                                          const char *running_partition,
                                                          const char *reboot_reason,
                                                          int *http_status)
{
    if (pending == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    cloud_ota_report_t report = {
        .stage = "ota_rollback",
        .ok = true,
        .target = "esp32s3",
        .from_version = app_version,
        .to_version = pending->version,
        .release_id = pending->release_id,
        .free_heap = (int)heap_caps_get_free_size(MALLOC_CAP_8BIT),
        .rssi = 0,
        .running_partition_after_reboot = running_partition,
        .reboot_reason = reboot_reason,
        .previous_partition = pending->partition_label,
        .last_stage = pending->last_stage,
        .verify = NULL,
    };
    return cloud_client_submit_ota_report(&report, http_status);
}

#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
static esp_err_t app_submit_ota_app_validated_report(const app_ota_p3c_pending_t *pending,
                                                     const char *app_version,
                                                     bool ok,
                                                     const char *error_code,
                                                     int *http_status)
{
    cloud_ota_update_t update = {0};
    snprintf(update.target, sizeof(update.target), "%s", "esp32s3");
    if (pending != NULL) {
        snprintf(update.version, sizeof(update.version), "%s", pending->version);
        snprintf(update.release_id, sizeof(update.release_id), "%s", pending->release_id);
    }
    return app_submit_ota_boot_report("app_validated",
                                      ok,
                                      &update,
                                      app_version,
                                      ok ? NULL : error_code,
                                      ok ? NULL : "ota app validation failed",
                                      NULL,
                                      NULL,
                                      NULL,
                                      app_reset_reason_to_string(esp_reset_reason()),
                                      NULL,
                                      http_status);
}
#endif

static void app_ota_schedule_boot_switch(const cloud_ota_update_t *update,
                                         const cloud_ota_artifact_verify_t *verify,
                                         const char *app_version)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    const esp_partition_t *update_partition = NULL;
    const esp_partition_t *boot_before = esp_ota_get_boot_partition();
    const char *error_code = NULL;
    const char *error_message = NULL;
    int report_http_status = 0;

    ESP_LOGI(TAG,
             "stage=ota_boot_switch event=start release_id=%s running_partition=%s update_partition=%s boot_partition_before=%s action=write_switch_reboot no_boot_switch=0 reboot_scheduled=0",
             update != NULL && update->release_id[0] != '\0' ? update->release_id : "(empty)",
             app_partition_label_or_empty(running),
             verify != NULL && verify->partition_label[0] != '\0' ? verify->partition_label : "(empty)",
             app_partition_label_or_empty(boot_before));

    esp_err_t ret = app_ota_find_partition_from_verify(verify, &update_partition);
    if (ret != ESP_OK) {
        error_code = esp_err_to_name(ret);
        error_message = "ota update partition lookup failed";
        goto fail;
    }
    if (running == NULL || update_partition == running ||
        update_partition->address == running->address) {
        ret = ESP_ERR_INVALID_STATE;
        error_code = "update_partition_is_running";
        error_message = "ota update partition matches running partition";
        goto fail;
    }

    ret = app_ota_p3c_store_pending(update, verify);
    if (ret != ESP_OK) {
        error_code = esp_err_to_name(ret);
        error_message = "ota pending boot state persist failed";
        goto fail;
    }

    ret = esp_ota_set_boot_partition(update_partition);
    if (ret != ESP_OK) {
        (void)app_ota_p3c_clear_pending();
        error_code = esp_err_to_name(ret);
        error_message = "ota set boot partition failed";
        goto fail;
    }

    const esp_partition_t *boot_after = esp_ota_get_boot_partition();
    if (boot_after == NULL || boot_after->address != update_partition->address) {
        (void)app_ota_p3c_clear_pending();
        error_code = "boot_partition_after_set_mismatch";
        error_message = "ota boot partition confirmation mismatch";
        ret = ESP_ERR_INVALID_STATE;
        goto fail;
    }

    ESP_LOGI(TAG,
             "stage=ota_boot_switch event=done release_id=%s running_partition=%s update_partition=%s boot_partition_before=%s boot_partition_after_set=%s action=write_switch_reboot no_boot_switch=0 reboot_scheduled=1",
             update->release_id,
             app_partition_label_or_empty(running),
             update_partition->label,
             app_partition_label_or_empty(boot_before),
             app_partition_label_or_empty(boot_after));
    esp_err_t report_ret = app_submit_ota_boot_report("boot_switch_scheduled",
                                                      true,
                                                      update,
                                                      app_version,
                                                      NULL,
                                                      NULL,
                                                      app_partition_label_or_empty(boot_before),
                                                      app_partition_label_or_empty(boot_after),
                                                      NULL,
                                                      NULL,
                                                      NULL,
                                                      &report_http_status);
    if (report_ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_report event=done report_stage=boot_switch_scheduled http_status=%d ok=1 release_id=%s",
                 report_http_status,
                 update->release_id);
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_report event=failed report_stage=boot_switch_scheduled err=%s http_status=%d ok=1 release_id=%s",
                 esp_err_to_name(report_ret),
                 report_http_status,
                 update->release_id);
    }
    ESP_LOGI(TAG,
             "stage=ota_reboot event=scheduled release_id=%s update_partition=%s reboot_scheduled=1",
             update->release_id,
             update_partition->label);
    (void)app_ota_p3c_store_last_stage("boot_switch_reboot_scheduled");
    esp_restart();
    return;

fail:
    ESP_LOGW(TAG,
             "stage=ota_boot_switch event=failed release_id=%s err=%s error_code=%s running_partition=%s update_partition=%s boot_partition_before=%s action=write_switch_reboot no_boot_switch=0 reboot_scheduled=0",
             update != NULL && update->release_id[0] != '\0' ? update->release_id : "(empty)",
             esp_err_to_name(ret),
             error_code != NULL ? error_code : esp_err_to_name(ret),
             app_partition_label_or_empty(running),
             update_partition != NULL ? update_partition->label
                                      : (verify != NULL && verify->partition_label[0] != '\0'
                                             ? verify->partition_label
                                             : "(empty)"),
             app_partition_label_or_empty(boot_before));
    esp_err_t fail_report_ret =
        app_submit_ota_boot_report("boot_switch_scheduled",
                                   false,
                                   update,
                                   app_version,
                                   error_code != NULL ? error_code : esp_err_to_name(ret),
                                   error_message != NULL ? error_message : "ota boot switch failed",
                                   app_partition_label_or_empty(boot_before),
                                   NULL,
                                   NULL,
                                   NULL,
                                   NULL,
                                   &report_http_status);
    if (fail_report_ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_report event=done report_stage=boot_switch_scheduled http_status=%d ok=0 release_id=%s",
                 report_http_status,
                 update != NULL && update->release_id[0] != '\0' ? update->release_id : "(empty)");
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_report event=failed report_stage=boot_switch_scheduled err=%s http_status=%d ok=0 release_id=%s",
                 esp_err_to_name(fail_report_ret),
                 report_http_status,
                 update != NULL && update->release_id[0] != '\0' ? update->release_id : "(empty)");
    }
}

static void app_ota_post_reboot_confirm_if_pending(const char *app_version)
{
    app_ota_p3c_pending_t pending = {0};
    esp_err_t ret = app_ota_p3c_load_pending(&pending);
    if (ret == ESP_ERR_NVS_NOT_FOUND || ret == ESP_ERR_NVS_NOT_INITIALIZED) {
        return;
    }
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "stage=ota_post_reboot_confirm event=failed err=%s", esp_err_to_name(ret));
        return;
    }

    const esp_partition_t *running = esp_ota_get_running_partition();
    const char *running_label = app_partition_label_or_empty(running);
    const char *reboot_reason = app_reset_reason_to_string(esp_reset_reason());
    const bool ok = running != NULL &&
                    running->address == pending.partition_address &&
                    strcmp(running->label, pending.partition_label) == 0;
    (void)app_ota_p3c_store_last_stage(ok ? "post_reboot_confirm_start" : "rollback_recovered");
    ESP_LOGI(TAG,
             "stage=ota_post_reboot_confirm event=start release_id=%s expected_partition=%s expected_address=0x%lx running_partition_after_reboot=%s reboot_reason=%s",
             pending.release_id,
             pending.partition_label,
             (unsigned long)pending.partition_address,
             running_label[0] != '\0' ? running_label : "(empty)",
             reboot_reason);
    if (ok) {
        ESP_LOGI(TAG,
                 "stage=ota_post_reboot_confirm event=done release_id=%s running_partition_after_reboot=%s",
                 pending.release_id,
                 running_label);
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_post_reboot_confirm event=failed release_id=%s error_code=running_partition_after_reboot_mismatch expected_partition=%s running_partition_after_reboot=%s",
                 pending.release_id,
                 pending.partition_label,
                 running_label[0] != '\0' ? running_label : "(empty)");
    }

    cloud_ota_update_t update = {0};
    snprintf(update.target, sizeof(update.target), "%s", "esp32s3");
    snprintf(update.version, sizeof(update.version), "%s", pending.version);
    snprintf(update.release_id, sizeof(update.release_id), "%s", pending.release_id);
    int report_http_status = 0;
    esp_err_t report_ret =
        app_submit_ota_boot_report("post_reboot_confirm",
                                   ok,
                                   &update,
                                   app_version,
                                   ok ? NULL : "running_partition_after_reboot_mismatch",
                                   ok ? NULL : "ota post reboot partition mismatch",
                                   NULL,
                                   NULL,
                                   running_label,
                                   reboot_reason,
                                   ok ? "post_reboot_confirm_start" : "rollback_recovered",
                                   &report_http_status);
    if (report_ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_report event=done report_stage=post_reboot_confirm http_status=%d ok=%d release_id=%s",
                 report_http_status,
                 ok ? 1 : 0,
                 pending.release_id);
#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
        if (ok) {
            (void)app_ota_p3c_store_last_stage("post_reboot_confirm_reported");
            s_ota_rollback_pending = pending;
            s_ota_rollback_validation_pending = true;
            s_ota_rollback_business_ready = false;
            BaseType_t timeout_ok = xTaskCreate(app_ota_rollback_validation_timeout_task,
                                                "ota_valid_timeout",
                                                DEMO_OTA_POST_REBOOT_TASK_STACK_SIZE,
                                                NULL,
                                                tskIDLE_PRIORITY + 1,
                                                &s_ota_rollback_timeout_task_handle);
            if (timeout_ok != pdPASS) {
                s_ota_rollback_timeout_task_handle = NULL;
                ESP_LOGW(TAG,
                         "stage=ota_app_validation_timeout event=task_start_failed release_id=%s",
                         pending.release_id);
            } else {
                (void)app_ota_p3c_store_last_stage("app_validation_waiting");
            }
        } else {
            int recovered_http_status = 0;
            esp_err_t recovered_ret =
                app_submit_ota_rollback_recovered_report(&pending,
                                                         app_version,
                                                         running_label,
                                                         reboot_reason,
                                                         &recovered_http_status);
            if (recovered_ret == ESP_OK) {
                ESP_LOGI(TAG,
                         "stage=ota_rollback event=recovered previous_release_id=%s previous_partition=%s running_partition_after_reboot=%s last_stage=%s http_status=%d",
                         pending.release_id,
                         pending.partition_label,
                         running_label[0] != '\0' ? running_label : "(empty)",
                         pending.last_stage[0] != '\0' ? pending.last_stage : "(empty)",
                         recovered_http_status);
            } else {
                ESP_LOGW(TAG,
                         "stage=ota_rollback event=report_failed previous_release_id=%s err=%s http_status=%d",
                         pending.release_id,
                         esp_err_to_name(recovered_ret),
                         recovered_http_status);
            }
            (void)app_ota_p3c_clear_pending();
        }
#else
        (void)app_ota_p3c_clear_pending();
#endif
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_report event=failed report_stage=post_reboot_confirm err=%s http_status=%d ok=%d release_id=%s",
                 esp_err_to_name(report_ret),
                 report_http_status,
                 ok ? 1 : 0,
                 pending.release_id);
    }
}

static void app_ota_post_reboot_confirm_task(void *arg)
{
    (void)arg;

    const esp_app_desc_t *app_desc = esp_app_get_description();
    app_ota_post_reboot_confirm_if_pending(app_desc != NULL ? app_desc->version : "");
    vTaskDelete(NULL);
}

#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
static void app_ota_rollback_note_business_ready(const char *app_version)
{
    (void)app_version;
    if (!s_ota_rollback_validation_pending || s_ota_rollback_business_ready) {
        return;
    }
    s_ota_rollback_business_ready = true;
    (void)app_ota_p3c_store_last_stage("app_validation_start");
    ESP_LOGI(TAG,
             "stage=ota_app_validation event=start release_id=%s running_partition=%s",
             s_ota_rollback_pending.release_id,
             app_partition_label_or_empty(esp_ota_get_running_partition()));
    BaseType_t ok = xTaskCreate(app_ota_rollback_validation_task,
                                "ota_app_validate",
                                DEMO_OTA_ROLLBACK_VALIDATION_TASK_STACK_SIZE,
                                NULL,
                                tskIDLE_PRIORITY + 1,
                                &s_ota_rollback_validation_task_handle);
    if (ok != pdPASS) {
        s_ota_rollback_validation_task_handle = NULL;
        s_ota_rollback_business_ready = false;
        ESP_LOGW(TAG,
                 "stage=ota_app_validation event=task_start_failed release_id=%s",
                 s_ota_rollback_pending.release_id);
    }
}

static void app_ota_rollback_validation_task(void *arg)
{
    (void)arg;
    const esp_app_desc_t *app_desc = esp_app_get_description();
    const char *app_version = app_desc != NULL ? app_desc->version : "";

    esp_err_t ret = esp_ota_mark_app_valid_cancel_rollback();
    int report_http_status = 0;
    esp_err_t report_ret = app_submit_ota_app_validated_report(&s_ota_rollback_pending,
                                                               app_version,
                                                               ret == ESP_OK,
                                                               esp_err_to_name(ret),
                                                               &report_http_status);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_app_validation event=done release_id=%s running_partition=%s",
                 s_ota_rollback_pending.release_id,
                 app_partition_label_or_empty(esp_ota_get_running_partition()));
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_app_validation event=failed release_id=%s error_code=%s",
                 s_ota_rollback_pending.release_id,
                 esp_err_to_name(ret));
    }
    if (report_ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_report event=done report_stage=app_validated http_status=%d ok=%d release_id=%s",
                 report_http_status,
                 ret == ESP_OK ? 1 : 0,
                 s_ota_rollback_pending.release_id);
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_report event=failed report_stage=app_validated err=%s http_status=%d ok=%d release_id=%s",
                 esp_err_to_name(report_ret),
                 report_http_status,
                 ret == ESP_OK ? 1 : 0,
                 s_ota_rollback_pending.release_id);
    }
    if (ret == ESP_OK && report_ret == ESP_OK) {
        (void)app_ota_p3c_store_last_stage("app_validation_done");
        (void)app_ota_p3c_clear_pending();
        s_ota_rollback_validation_pending = false;
    } else {
        s_ota_rollback_business_ready = false;
    }
    s_ota_rollback_validation_task_handle = NULL;
    vTaskDelete(NULL);
}

static void app_ota_rollback_validation_timeout_task(void *arg)
{
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS));
    if (s_ota_rollback_validation_pending && !s_ota_rollback_business_ready) {
        ESP_LOGW(TAG,
                 "stage=ota_app_validation event=timeout release_id=%s timeout_ms=%d",
                 s_ota_rollback_pending.release_id,
                 DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS);
        (void)app_ota_p3c_store_last_stage("app_validation_timeout");
        esp_restart();
    }
    s_ota_rollback_timeout_task_handle = NULL;
    vTaskDelete(NULL);
}
#endif
#endif /* DEMO_OTA_BOOT_SWITCH_ENABLED */

static void app_ota_manifest_dry_run_task(void *arg)
{
    (void)arg;

    const esp_app_desc_t *app_desc = esp_app_get_description();
    const char *app_version = app_desc != NULL ? app_desc->version : "";
    cloud_ota_manifest_t manifest = {0};
    const int64_t start_us = esp_timer_get_time();
    ESP_LOGI(TAG,
             "stage=ota_manifest_dry_run event=start device_id=%s board=%s hw_rev=%s app_version=%s",
             DEMO_DEVICE_ID,
             DEMO_BOARD_NAME,
             DEMO_BOARD_REVISION,
             app_version);
    esp_err_t ret = cloud_client_fetch_ota_manifest(DEMO_BOARD_NAME,
                                                    DEMO_BOARD_REVISION,
                                                    app_version,
                                                    &manifest);
    const double elapsed_ms = (double)(esp_timer_get_time() - start_us) / 1000.0;
    if (ret != ESP_OK) {
        ESP_LOGW(TAG,
                 "stage=ota_manifest_dry_run event=failed err=%s http_status=%d elapsed_ms=%.1f",
                 esp_err_to_name(ret),
                 manifest.http_status,
                 elapsed_ms);
        goto finish;
    }
    if (!manifest.has_update) {
        ESP_LOGI(TAG,
                 "stage=ota_manifest_dry_run event=no_update http_status=%d poll_interval_sec=%d elapsed_ms=%.1f",
                 manifest.http_status,
                 manifest.poll_interval_sec,
                 elapsed_ms);
        goto finish;
    }

    cloud_ota_artifact_verify_t verify = {0};
    int report_http_status = 0;
#if DEMO_OTA_PARTITION_WRITE_ENABLED
#if DEMO_OTA_BOOT_SWITCH_ENABLED
    ESP_LOGI(TAG,
             "stage=ota_manifest_dry_run event=update_available release_id=%s target=%s version=%s artifact=%s size=%d sha256=%s force=%d min_version=%s url=%s elapsed_ms=%.1f action=write_switch_reboot",
             manifest.update.release_id[0] != '\0' ? manifest.update.release_id : "(empty)",
             manifest.update.target,
             manifest.update.version,
             manifest.update.artifact,
             manifest.update.size,
             manifest.update.sha256,
             manifest.update.force,
             manifest.update.min_version[0] != '\0' ? manifest.update.min_version : "(none)",
             manifest.update.url,
             elapsed_ms);
#else
    ESP_LOGI(TAG,
             "stage=ota_manifest_dry_run event=update_available release_id=%s target=%s version=%s artifact=%s size=%d sha256=%s force=%d min_version=%s url=%s elapsed_ms=%.1f action=write_inactive_only",
             manifest.update.release_id[0] != '\0' ? manifest.update.release_id : "(empty)",
             manifest.update.target,
             manifest.update.version,
             manifest.update.artifact,
             manifest.update.size,
             manifest.update.sha256,
             manifest.update.force,
             manifest.update.min_version[0] != '\0' ? manifest.update.min_version : "(none)",
             manifest.update.url,
             elapsed_ms);
#endif

    char ota_error_code[64] = {0};
    char ota_error_message[128] = {0};
    const int64_t partition_start_us = esp_timer_get_time();
    ret = app_write_ota_inactive_partition(&manifest.update,
                                           &verify,
                                           ota_error_code,
                                           sizeof(ota_error_code),
                                           ota_error_message,
                                           sizeof(ota_error_message));
    const double partition_elapsed_ms = (double)(esp_timer_get_time() - partition_start_us) / 1000.0;
    if (ret == ESP_OK) {
#if DEMO_OTA_BOOT_SWITCH_ENABLED
        const esp_partition_t *boot_before = esp_ota_get_boot_partition();
        ESP_LOGI(TAG,
                 "stage=ota_partition_write event=done http_status=%d bytes_read=%d bytes_written=%d expected_size=%d sha256=%s expected_sha256=%s partition_label=%s partition_subtype=%d partition_address=0x%lx boot_partition_before=%s elapsed_ms=%.1f action=write_switch_reboot no_boot_switch=0 reboot_scheduled=0",
                 verify.http_status,
                 verify.bytes_read,
                 verify.bytes_written,
                 verify.expected_size,
                 verify.sha256,
                 verify.expected_sha256,
                 verify.partition_label,
                 verify.partition_subtype,
                 (unsigned long)verify.partition_address,
                 app_partition_label_or_empty(boot_before),
                 partition_elapsed_ms);
#else
        ESP_LOGI(TAG,
                 "stage=ota_partition_write event=done http_status=%d bytes_read=%d bytes_written=%d expected_size=%d sha256=%s expected_sha256=%s partition_label=%s partition_subtype=%d partition_address=0x%lx elapsed_ms=%.1f action=write_inactive_only no_boot_switch=1 no_reboot=1",
                 verify.http_status,
                 verify.bytes_read,
                 verify.bytes_written,
                 verify.expected_size,
                 verify.sha256,
                 verify.expected_sha256,
                 verify.partition_label,
                 verify.partition_subtype,
                 (unsigned long)verify.partition_address,
                 partition_elapsed_ms);
#endif
    } else {
#if DEMO_OTA_BOOT_SWITCH_ENABLED
        ESP_LOGW(TAG,
                 "stage=ota_partition_write event=failed err=%s error_code=%s http_status=%d bytes_read=%d bytes_written=%d expected_size=%d sha256=%s expected_sha256=%s partition_label=%s partition_subtype=%d partition_address=0x%lx elapsed_ms=%.1f action=write_switch_reboot no_boot_switch=0 reboot_scheduled=0",
                 esp_err_to_name(ret),
                 ota_error_code[0] != '\0' ? ota_error_code : esp_err_to_name(ret),
                 verify.http_status,
                 verify.bytes_read,
                 verify.bytes_written,
                 verify.expected_size,
                 verify.sha256[0] != '\0' ? verify.sha256 : "(empty)",
                 verify.expected_sha256[0] != '\0' ? verify.expected_sha256 : manifest.update.sha256,
                 verify.partition_label[0] != '\0' ? verify.partition_label : "(empty)",
                 verify.partition_subtype,
                 (unsigned long)verify.partition_address,
                 partition_elapsed_ms);
#else
        ESP_LOGW(TAG,
                 "stage=ota_partition_write event=failed err=%s error_code=%s http_status=%d bytes_read=%d bytes_written=%d expected_size=%d sha256=%s expected_sha256=%s partition_label=%s partition_subtype=%d partition_address=0x%lx elapsed_ms=%.1f action=write_inactive_only no_boot_switch=1 no_reboot=1",
                 esp_err_to_name(ret),
                 ota_error_code[0] != '\0' ? ota_error_code : esp_err_to_name(ret),
                 verify.http_status,
                 verify.bytes_read,
                 verify.bytes_written,
                 verify.expected_size,
                 verify.sha256[0] != '\0' ? verify.sha256 : "(empty)",
                 verify.expected_sha256[0] != '\0' ? verify.expected_sha256 : manifest.update.sha256,
                 verify.partition_label[0] != '\0' ? verify.partition_label : "(empty)",
                 verify.partition_subtype,
                 (unsigned long)verify.partition_address,
                 partition_elapsed_ms);
#endif
    }
    const esp_err_t verify_ret = ret;
    cloud_ota_report_t report = {
        .stage = "partition_write",
        .ok = verify_ret == ESP_OK,
        .target = manifest.update.target[0] != '\0' ? manifest.update.target : "esp32s3",
        .from_version = app_version,
        .to_version = manifest.update.version,
        .release_id = manifest.update.release_id,
        .error_code = verify_ret == ESP_OK ? NULL
                                           : (ota_error_code[0] != '\0' ? ota_error_code : esp_err_to_name(verify_ret)),
        .error_message = verify_ret == ESP_OK ? NULL
                                              : (ota_error_message[0] != '\0'
                                                     ? ota_error_message
                                                     : "ota inactive partition write failed"),
        .free_heap = (int)heap_caps_get_free_size(MALLOC_CAP_8BIT),
        .rssi = 0,
        .verify = &verify,
    };
    esp_err_t report_ret = cloud_client_submit_ota_report(&report, &report_http_status);
    if (report_ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_report event=done report_stage=partition_write http_status=%d ok=%d release_id=%s",
                 report_http_status,
                 verify_ret == ESP_OK ? 1 : 0,
                 manifest.update.release_id[0] != '\0' ? manifest.update.release_id : "(empty)");
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_report event=failed report_stage=partition_write err=%s http_status=%d ok=%d release_id=%s",
                 esp_err_to_name(report_ret),
                 report_http_status,
                 verify_ret == ESP_OK ? 1 : 0,
                 manifest.update.release_id[0] != '\0' ? manifest.update.release_id : "(empty)");
    }
#if DEMO_OTA_BOOT_SWITCH_ENABLED
    if (verify_ret == ESP_OK) {
        app_ota_schedule_boot_switch(&manifest.update, &verify, app_version);
    }
#endif /* DEMO_OTA_BOOT_SWITCH_ENABLED */
#else
    ESP_LOGI(TAG,
             "stage=ota_manifest_dry_run event=update_available release_id=%s target=%s version=%s artifact=%s size=%d sha256=%s force=%d min_version=%s url=%s elapsed_ms=%.1f action=download_verify_only",
             manifest.update.release_id[0] != '\0' ? manifest.update.release_id : "(empty)",
             manifest.update.target,
             manifest.update.version,
             manifest.update.artifact,
             manifest.update.size,
             manifest.update.sha256,
             manifest.update.force,
             manifest.update.min_version[0] != '\0' ? manifest.update.min_version : "(none)",
             manifest.update.url,
             elapsed_ms);

    const int64_t verify_start_us = esp_timer_get_time();
    ESP_LOGI(TAG,
             "stage=ota_artifact_verify event=start release_id=%s artifact=%s size=%d sha256=%s action=download_verify_only",
             manifest.update.release_id[0] != '\0' ? manifest.update.release_id : "(empty)",
             manifest.update.artifact,
             manifest.update.size,
             manifest.update.sha256);
    ret = cloud_client_verify_ota_artifact(&manifest.update, &verify);
    const double verify_elapsed_ms = (double)(esp_timer_get_time() - verify_start_us) / 1000.0;
    if (ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_artifact_verify event=done http_status=%d bytes=%d expected_size=%d sha256=%s elapsed_ms=%.1f action=download_verify_only",
                 verify.http_status,
                 verify.bytes_read,
                 verify.expected_size,
                 verify.sha256,
                 verify_elapsed_ms);
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_artifact_verify event=failed err=%s http_status=%d bytes=%d expected_size=%d sha256=%s expected_sha256=%s elapsed_ms=%.1f action=download_verify_only",
                 esp_err_to_name(ret),
                 verify.http_status,
                 verify.bytes_read,
                 verify.expected_size,
                 verify.sha256[0] != '\0' ? verify.sha256 : "(empty)",
                 verify.expected_sha256[0] != '\0' ? verify.expected_sha256 : manifest.update.sha256,
                 verify_elapsed_ms);
    }
    const esp_err_t verify_ret = ret;
    cloud_ota_report_t report = {
        .stage = "artifact_verify",
        .ok = verify_ret == ESP_OK,
        .target = manifest.update.target[0] != '\0' ? manifest.update.target : "esp32s3",
        .from_version = app_version,
        .to_version = manifest.update.version,
        .release_id = manifest.update.release_id,
        .error_code = verify_ret == ESP_OK ? NULL : esp_err_to_name(verify_ret),
        .error_message = verify_ret == ESP_OK ? NULL : "ota artifact download verification failed",
        .free_heap = (int)heap_caps_get_free_size(MALLOC_CAP_8BIT),
        .rssi = 0,
        .verify = &verify,
    };
    esp_err_t report_ret = cloud_client_submit_ota_report(&report, &report_http_status);
    if (report_ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_report event=done report_stage=artifact_verify http_status=%d ok=%d release_id=%s",
                 report_http_status,
                 verify_ret == ESP_OK ? 1 : 0,
                 manifest.update.release_id[0] != '\0' ? manifest.update.release_id : "(empty)");
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_report event=failed report_stage=artifact_verify err=%s http_status=%d ok=%d release_id=%s",
                 esp_err_to_name(report_ret),
                 report_http_status,
                 verify_ret == ESP_OK ? 1 : 0,
                 manifest.update.release_id[0] != '\0' ? manifest.update.release_id : "(empty)");
    }
#endif

finish:
    s_ota_manifest_task_handle = NULL;
    vTaskDelete(NULL);
}

static void app_poll_ota_manifest_dry_run_if_due(void)
{
#if DEMO_OTA_MANIFEST_DRY_RUN_ENABLED
    const int64_t now_us = esp_timer_get_time();
    if (s_next_ota_manifest_check_us > 0 && now_us < s_next_ota_manifest_check_us) {
        return;
    }
    if (!app_ota_manifest_idle_ready(now_us)) {
        return;
    }

    s_next_ota_manifest_check_us =
        now_us + (int64_t)DEMO_OTA_MANIFEST_POLL_INTERVAL_MS * 1000;

    BaseType_t ok = xTaskCreate(app_ota_manifest_dry_run_task,
                                "ota_manifest",
                                DEMO_OTA_MANIFEST_TASK_STACK_SIZE,
                                NULL,
                                tskIDLE_PRIORITY + 1,
                                &s_ota_manifest_task_handle);
    if (ok != pdPASS) {
        s_ota_manifest_task_handle = NULL;
        ESP_LOGW(TAG, "stage=ota_manifest_dry_run event=task_start_failed");
    }
#endif
}

void app_main(void)
{
    BaseType_t ok = xTaskCreate(app_runtime_task,
                                "app_runtime",
                                DEMO_APP_RUNTIME_TASK_STACK_SIZE,
                                NULL,
                                tskIDLE_PRIORITY + 1,
                                NULL);
    if (ok != pdPASS) {
        ESP_LOGE(TAG, "Failed to start app_runtime task");
    }
    vTaskDelete(NULL);
}

static void app_runtime_task(void *arg)
{
    (void)arg;
    trigger_input_t trigger = {0};

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "ESP-IDF audio demo starting");
    ESP_LOGI(TAG, "Board: %s %s", DEMO_BOARD_NAME, DEMO_BOARD_REVISION);
    app_log_runtime_config();
    ESP_LOGI(TAG, "========================================");

    if (DEMO_REALTIME_INTRO_ENABLED || DEMO_RECORD_PROMPT_ENABLED) {
        (void)app_mount_spiffs();
    }

    if (app_wifi_connect() != ESP_OK) {
        app_set_state(&s_app_state, APP_STATE_ERROR);
        ESP_LOGE(TAG, "Wi-Fi initialization failed; stopping demo");
        vTaskDelete(NULL);
        return;
    }
#if DEMO_OTA_BOOT_SWITCH_ENABLED
    (void)app_ota_p3c_store_last_stage("wifi_connected");
#endif /* DEMO_OTA_BOOT_SWITCH_ENABLED */

#if DEMO_OTA_BOOT_SWITCH_ENABLED
    BaseType_t ota_confirm_task_ok = xTaskCreate(app_ota_post_reboot_confirm_task,
                                                 "ota_post_reboot",
                                                 DEMO_OTA_POST_REBOOT_TASK_STACK_SIZE,
                                                 NULL,
                                                 tskIDLE_PRIORITY + 1,
                                                 NULL);
    if (ota_confirm_task_ok != pdPASS) {
        ESP_LOGW(TAG, "stage=ota_post_reboot_confirm event=task_start_failed");
    }
#endif /* DEMO_OTA_BOOT_SWITCH_ENABLED */

#if DEMO_OTA_BOOT_SWITCH_ENABLED
    (void)app_ota_p3c_store_last_stage("trigger_init_start");
#endif /* DEMO_OTA_BOOT_SWITCH_ENABLED */
    if (trigger_input_init(&trigger) != ESP_OK) {
        app_set_state(&s_app_state, APP_STATE_ERROR);
        ESP_LOGE(TAG, "Trigger initialization failed; stopping demo");
        vTaskDelete(NULL);
        return;
    }
#if DEMO_OTA_BOOT_SWITCH_ENABLED
    (void)app_ota_p3c_store_last_stage("trigger_init_done");
#endif /* DEMO_OTA_BOOT_SWITCH_ENABLED */
    app_set_state(&s_app_state, APP_STATE_IDLE);
#if DEMO_OTA_BOOT_SWITCH_ENABLED && DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
    const esp_app_desc_t *rollback_app_desc = esp_app_get_description();
    app_ota_rollback_note_business_ready(rollback_app_desc != NULL ? rollback_app_desc->version : "");
#endif

    while (true) {
#if DEMO_OTA_BOOT_SWITCH_ENABLED && DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
        app_ota_rollback_note_business_ready(rollback_app_desc != NULL ? rollback_app_desc->version : "");
#endif
        app_poll_ota_manifest_dry_run_if_due();

        trigger_event_t event = {0};
        if (trigger_input_poll(&trigger, &event)) {
            if (s_app_state == APP_STATE_IDLE && s_pipeline_task_handle == NULL) {
                ESP_LOGI(TAG, "trigger source=%s x=%u y=%u -> starting pipeline",
                         trigger_input_source_name(event.type),
                         (unsigned)event.x,
                         (unsigned)event.y);
                esp_err_t ret = app_start_pipeline_task(&event);
                if (ret != ESP_OK) {
                    ESP_LOGE(TAG, "Failed to start pipeline task: %s", esp_err_to_name(ret));
                    app_set_state(&s_app_state, APP_STATE_ERROR);
                    app_set_state(&s_app_state, APP_STATE_IDLE);
                }
            } else {
                ESP_LOGW(TAG,
                         "Trigger ignored: source=%s state=%s pipeline_task=%s",
                         trigger_input_source_name(event.type),
                         app_state_to_string(s_app_state),
                         s_pipeline_task_handle == NULL ? "none" : "busy");
            }
        }

        vTaskDelay(pdMS_TO_TICKS(DEMO_TRIGGER_POLL_INTERVAL_MS));
    }
}
