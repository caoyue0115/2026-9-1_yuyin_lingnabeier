#include "wake_word_service.h"

#include "board_audio.h"
#include "config.h"

#include <stdbool.h>
#include <string.h>

#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_codec_dev.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "model_path.h"

static const char *TAG = "wake_word";
static const char *const s_expected_spike_model = "wn9_xiaomingtongxue_tts2";

typedef struct {
    bool initialized;
    bool unavailable;
    volatile bool running;
    volatile bool stop_requested;
    volatile bool event_pending;
    volatile bool mic_opened;
    esp_codec_dev_handle_t mic_handle;
    srmodel_list_t *models;
    const esp_afe_sr_iface_t *afe_iface;
    esp_afe_sr_data_t *afe_data;
    TaskHandle_t feed_task;
    TaskHandle_t fetch_task;
    int feed_samples;
    int feed_channels;
    char detected_word[64];
    char detected_model[64];
} wake_word_state_t;

static wake_word_state_t s_wake = {0};

static void wake_word_log_heap(const char *stage)
{
    ESP_LOGI(TAG,
             "wake_word_heap stage=%s free_8bit=%u largest_8bit=%u free_spiram=%u largest_spiram=%u",
             stage != NULL ? stage : "unknown",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
}

static esp_codec_dev_sample_info_t wake_word_sample_info(void)
{
    esp_codec_dev_sample_info_t fs = {
        .sample_rate = DEMO_AUDIO_SAMPLE_RATE,
        .channel = DEMO_AUDIO_CHANNELS,
        .channel_mask = 0,
        .bits_per_sample = DEMO_AUDIO_BITS_PER_SAMPLE,
        .mclk_multiple = 0,
    };
    return fs;
}

static void wake_word_close_mic(void)
{
    if (s_wake.mic_opened && s_wake.mic_handle != NULL) {
        (void)esp_codec_dev_close(s_wake.mic_handle);
        s_wake.mic_opened = false;
        ESP_LOGI(TAG, "wake_word_mic_released model=%s", DEMO_WAKE_WORD_MODEL_NAME);
    }
}

static esp_err_t wake_word_open_mic(void)
{
    if (s_wake.mic_handle == NULL) {
        s_wake.mic_handle = board_audio_codec_microphone_init();
        if (s_wake.mic_handle == NULL) {
            ESP_LOGE(TAG, "wake_word_mic_init_failed");
            return ESP_FAIL;
        }
    }

    if (s_wake.mic_opened) {
        return ESP_OK;
    }

    esp_err_t ret = esp_codec_dev_set_in_gain(s_wake.mic_handle, DEMO_AUDIO_INPUT_GAIN_DB);
    if (ret != ESP_CODEC_DEV_OK) {
        ESP_LOGW(TAG,
                 "wake_word_set_gain_failed gain_db=%.1f err=%s",
                 (double)DEMO_AUDIO_INPUT_GAIN_DB,
                 esp_err_to_name(ret));
    }

    esp_codec_dev_sample_info_t fs = wake_word_sample_info();
    ret = esp_codec_dev_open(s_wake.mic_handle, &fs);
    if (ret != ESP_CODEC_DEV_OK) {
        ESP_LOGE(TAG, "wake_word_mic_open_failed err=%s", esp_err_to_name(ret));
        return ret;
    }

    s_wake.mic_opened = true;
    ESP_LOGI(TAG,
             "wake_word_mic_acquired sample_rate=%d channels=%d model=%s",
             DEMO_AUDIO_SAMPLE_RATE,
             DEMO_AUDIO_CHANNELS,
             DEMO_WAKE_WORD_MODEL_NAME);
    return ESP_OK;
}

static esp_err_t wake_word_init_once(void)
{
    if (s_wake.initialized) {
        return ESP_OK;
    }
    if (s_wake.unavailable) {
        return ESP_ERR_NOT_SUPPORTED;
    }

    if (strcmp(DEMO_WAKE_WORD_MODEL_NAME, s_expected_spike_model) != 0 ||
        strcmp(WAKE_WORD_SERVICE_SPIKE_MODEL_NAME, s_expected_spike_model) != 0) {
        ESP_LOGE(TAG,
                 "wake_word_model_mismatch configured=%s expected=%s",
                 DEMO_WAKE_WORD_MODEL_NAME,
                 s_expected_spike_model);
        s_wake.unavailable = true;
        return ESP_ERR_INVALID_STATE;
    }

    wake_word_log_heap("init_before");
    esp_err_t ret = board_audio_init(NULL);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "wake_word_board_audio_init_failed err=%s", esp_err_to_name(ret));
        s_wake.unavailable = true;
        return ret;
    }

    s_wake.models = esp_srmodel_init("model");
    if (s_wake.models == NULL || s_wake.models->num <= 0) {
        ESP_LOGE(TAG,
                 "wake_word_model_partition_required label=model model=%s model_partition_required=1",
                 DEMO_WAKE_WORD_MODEL_NAME);
        s_wake.unavailable = true;
        return ESP_ERR_NOT_FOUND;
    }

    if (esp_srmodel_exists(s_wake.models, (char *)DEMO_WAKE_WORD_MODEL_NAME) < 0) {
        ESP_LOGE(TAG, "wake_word_model_not_found model=%s", DEMO_WAKE_WORD_MODEL_NAME);
        s_wake.unavailable = true;
        return ESP_ERR_NOT_FOUND;
    }

    afe_config_t *afe_config = afe_config_init("M", s_wake.models, AFE_TYPE_SR, AFE_MODE_LOW_COST);
    if (afe_config == NULL) {
        ESP_LOGE(TAG, "wake_word_afe_config_failed");
        s_wake.unavailable = true;
        return ESP_ERR_NO_MEM;
    }
    afe_config->aec_init = false;
    afe_config->se_init = false;
    afe_config->ns_init = false;
    afe_config->vad_init = false;
    afe_config->agc_init = false;
    afe_config->wakenet_init = true;
    afe_config->wakenet_model_name = (char *)DEMO_WAKE_WORD_MODEL_NAME;
    afe_config->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    afe_config->afe_perferred_core = 1;
    afe_config->afe_perferred_priority = 3;

    s_wake.afe_iface = esp_afe_handle_from_config(afe_config);
    if (s_wake.afe_iface == NULL) {
        afe_config_free(afe_config);
        ESP_LOGE(TAG, "wake_word_afe_iface_failed");
        s_wake.unavailable = true;
        return ESP_FAIL;
    }

    s_wake.afe_data = s_wake.afe_iface->create_from_config(afe_config);
    afe_config_free(afe_config);
    if (s_wake.afe_data == NULL) {
        ESP_LOGE(TAG, "wake_word_afe_create_failed model=%s", DEMO_WAKE_WORD_MODEL_NAME);
        s_wake.unavailable = true;
        return ESP_FAIL;
    }

    s_wake.feed_samples = s_wake.afe_iface->get_feed_chunksize(s_wake.afe_data);
    s_wake.feed_channels = s_wake.afe_iface->get_feed_channel_num(s_wake.afe_data);
    if (s_wake.feed_samples <= 0 || s_wake.feed_channels <= 0) {
        ESP_LOGE(TAG,
                 "wake_word_afe_invalid_feed_shape samples=%d channels=%d",
                 s_wake.feed_samples,
                 s_wake.feed_channels);
        s_wake.unavailable = true;
        return ESP_ERR_INVALID_STATE;
    }

    s_wake.initialized = true;
    wake_word_log_heap("init_after");
    ESP_LOGI(TAG,
             "wake_word_service_initialized wake_word_enabled=%d wake_word_model=%s wake_word_text=%s model_partition=model feed_samples=%d feed_channels=%d",
             DEMO_WAKE_WORD_ENABLED,
             DEMO_WAKE_WORD_MODEL_NAME,
             DEMO_WAKE_WORD_TEXT,
             s_wake.feed_samples,
             s_wake.feed_channels);
    return ESP_OK;
}

static void wake_word_feed_task(void *arg)
{
    (void)arg;
    const size_t buffer_bytes = (size_t)s_wake.feed_samples * (size_t)s_wake.feed_channels * sizeof(int16_t);
    int16_t *buffer = heap_caps_malloc(buffer_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (buffer == NULL) {
        buffer = heap_caps_malloc(buffer_bytes, MALLOC_CAP_8BIT);
    }

    if (buffer == NULL) {
        ESP_LOGE(TAG, "wake_word_feed_alloc_failed bytes=%u", (unsigned)buffer_bytes);
        s_wake.stop_requested = true;
    }

    while (!s_wake.stop_requested && buffer != NULL) {
        esp_err_t ret = esp_codec_dev_read(s_wake.mic_handle, buffer, (int)buffer_bytes);
        if (ret != ESP_CODEC_DEV_OK) {
            ESP_LOGW(TAG, "wake_word_mic_read_failed err=%s", esp_err_to_name(ret));
            s_wake.stop_requested = true;
            break;
        }
        if (s_wake.afe_iface != NULL && s_wake.afe_data != NULL) {
            (void)s_wake.afe_iface->feed(s_wake.afe_data, buffer);
        }
    }

    if (buffer != NULL) {
        heap_caps_free(buffer);
    }
    wake_word_close_mic();
    s_wake.running = false;
    s_wake.feed_task = NULL;
    ESP_LOGI(TAG, "wake_word_feed_task_exit model=%s", DEMO_WAKE_WORD_MODEL_NAME);
    vTaskDelete(NULL);
}

static void wake_word_fetch_task(void *arg)
{
    (void)arg;
    while (!s_wake.stop_requested) {
        afe_fetch_result_t *result = s_wake.afe_iface->fetch_with_delay(s_wake.afe_data, pdMS_TO_TICKS(100));
        if (result == NULL || result->ret_value == ESP_FAIL) {
            continue;
        }
        if (result->wakeup_state == WAKENET_DETECTED) {
            strlcpy(s_wake.detected_word, DEMO_WAKE_WORD_TEXT, sizeof(s_wake.detected_word));
            strlcpy(s_wake.detected_model, DEMO_WAKE_WORD_MODEL_NAME, sizeof(s_wake.detected_model));
            s_wake.event_pending = true;
            s_wake.stop_requested = true;
            ESP_LOGI(TAG,
                     "wake_word_detected word=%s model=%s wake_word_index=%d wakenet_model_index=%d",
                     s_wake.detected_word,
                     s_wake.detected_model,
                     result->wake_word_index,
                     result->wakenet_model_index);
            break;
        }
    }

    s_wake.fetch_task = NULL;
    ESP_LOGI(TAG, "wake_word_fetch_task_exit model=%s", DEMO_WAKE_WORD_MODEL_NAME);
    vTaskDelete(NULL);
}

esp_err_t wake_word_service_start(void)
{
    if (!DEMO_WAKE_WORD_ENABLED) {
        return ESP_ERR_NOT_SUPPORTED;
    }
    if (s_wake.running) {
        return ESP_OK;
    }
    if (s_wake.feed_task != NULL || s_wake.fetch_task != NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    if (s_wake.event_pending) {
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t ret = wake_word_init_once();
    if (ret != ESP_OK) {
        return ret;
    }

    ret = wake_word_open_mic();
    if (ret != ESP_OK) {
        return ret;
    }

    if (s_wake.afe_iface != NULL && s_wake.afe_data != NULL) {
        (void)s_wake.afe_iface->reset_buffer(s_wake.afe_data);
    }
    s_wake.stop_requested = false;
    s_wake.event_pending = false;
    s_wake.detected_word[0] = '\0';
    s_wake.detected_model[0] = '\0';
    s_wake.running = true;

    BaseType_t ok = xTaskCreate(wake_word_feed_task,
                                "wake_word_feed",
                                DEMO_WAKE_WORD_TASK_STACK_SIZE,
                                NULL,
                                tskIDLE_PRIORITY + 3,
                                &s_wake.feed_task);
    if (ok != pdPASS) {
        s_wake.stop_requested = true;
        s_wake.running = false;
        wake_word_close_mic();
        ESP_LOGE(TAG, "wake_word_feed_task_start_failed");
        return ESP_ERR_NO_MEM;
    }

    ok = xTaskCreate(wake_word_fetch_task,
                     "wake_word_fetch",
                     DEMO_WAKE_WORD_TASK_STACK_SIZE,
                     NULL,
                     tskIDLE_PRIORITY + 3,
                     &s_wake.fetch_task);
    if (ok != pdPASS) {
        s_wake.stop_requested = true;
        ESP_LOGE(TAG, "wake_word_fetch_task_start_failed");
        (void)wake_word_service_stop_and_wait(DEMO_WAKE_WORD_STOP_TIMEOUT_MS);
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG,
             "wake_word_service_start wake_word_enabled=%d wake_word_model=%s wake_word_text=%s",
             DEMO_WAKE_WORD_ENABLED,
             DEMO_WAKE_WORD_MODEL_NAME,
             DEMO_WAKE_WORD_TEXT);
    return ESP_OK;
}

void wake_word_service_stop(void)
{
    if (!s_wake.initialized || (!s_wake.running && s_wake.feed_task == NULL && s_wake.fetch_task == NULL)) {
        return;
    }
    s_wake.stop_requested = true;
    ESP_LOGI(TAG, "wake_word_service_stop model=%s", DEMO_WAKE_WORD_MODEL_NAME);
}

esp_err_t wake_word_service_stop_and_wait(uint32_t timeout_ms)
{
    wake_word_service_stop();
    const TickType_t start_tick = xTaskGetTickCount();
    const TickType_t timeout_ticks = pdMS_TO_TICKS(timeout_ms);
    while (wake_word_service_is_active()) {
        if ((xTaskGetTickCount() - start_tick) >= timeout_ticks) {
            ESP_LOGW(TAG,
                     "wake_word_stop_timeout timeout_ms=%u running=%d feed_task=%p fetch_task=%p mic_opened=%d",
                     (unsigned)timeout_ms,
                     s_wake.running,
                     s_wake.feed_task,
                     s_wake.fetch_task,
                     s_wake.mic_opened);
            return ESP_ERR_TIMEOUT;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    ESP_LOGI(TAG, "wake_word_service_stopped");
    return ESP_OK;
}

esp_err_t wake_word_service_set_accepting(bool accepting)
{
    if (accepting) {
        return wake_word_service_start();
    }
    return wake_word_service_stop_and_wait(DEMO_WAKE_WORD_STOP_TIMEOUT_MS);
}

bool wake_word_service_is_active(void)
{
    return s_wake.running ||
           s_wake.feed_task != NULL ||
           s_wake.fetch_task != NULL ||
           s_wake.mic_opened;
}

bool wake_word_service_poll(wake_word_detection_t *out_detection)
{
    if (out_detection == NULL) {
        return false;
    }
    if (!s_wake.event_pending || s_wake.running || s_wake.feed_task != NULL || s_wake.fetch_task != NULL) {
        return false;
    }

    memset(out_detection, 0, sizeof(*out_detection));
    strlcpy(out_detection->word, s_wake.detected_word, sizeof(out_detection->word));
    strlcpy(out_detection->model, s_wake.detected_model, sizeof(out_detection->model));
    s_wake.event_pending = false;
    return true;
}
