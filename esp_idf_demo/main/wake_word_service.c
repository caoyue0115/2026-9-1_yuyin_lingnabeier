#include "wake_word_service.h"

#include "board_audio.h"
#include "config.h"

#include <stdbool.h>
#include <string.h>

#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_codec_dev.h"
#include "esp_doa.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "model_path.h"

static const char *TAG = "wake_word";
static const char *const s_expected_spike_model = "wn9_xiaomingtongxue_tts2";

typedef struct {
    int16_t degrees;
    uint16_t channel_difference_permille;
    uint32_t mean_energy;
    int64_t captured_us;
} direction_sample_t;

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
    doa_handle_t *doa;
    volatile bool latest_direction_valid;
    volatile int latest_direction_degrees;
    volatile int64_t latest_direction_us;
    direction_sample_t direction_history[DEMO_SOUND_DIRECTION_HISTORY_FRAMES];
    size_t direction_history_next;
    size_t direction_history_count;
    char detected_word[64];
    char detected_model[64];
    bool detected_direction_valid;
    int detected_direction_degrees;
} wake_word_state_t;

static wake_word_state_t s_wake = {0};
static portMUX_TYPE s_direction_lock = portMUX_INITIALIZER_UNLOCKED;

static void wake_word_store_direction_sample(int degrees,
                                             uint32_t mean_energy,
                                             uint16_t channel_difference_permille,
                                             int64_t captured_us)
{
    taskENTER_CRITICAL(&s_direction_lock);
    s_wake.latest_direction_degrees = degrees;
    s_wake.latest_direction_us = captured_us;
    s_wake.latest_direction_valid = true;
    direction_sample_t *sample = &s_wake.direction_history[s_wake.direction_history_next];
    sample->degrees = (int16_t)degrees;
    sample->mean_energy = mean_energy;
    sample->channel_difference_permille = channel_difference_permille;
    sample->captured_us = captured_us;
    s_wake.direction_history_next =
        (s_wake.direction_history_next + 1U) % DEMO_SOUND_DIRECTION_HISTORY_FRAMES;
    if (s_wake.direction_history_count < DEMO_SOUND_DIRECTION_HISTORY_FRAMES) {
        s_wake.direction_history_count++;
    }
    taskEXIT_CRITICAL(&s_direction_lock);
}

static bool wake_word_select_direction(int64_t now_us,
                                       int *out_degrees,
                                       size_t *out_sample_count,
                                       int *out_min_degrees,
                                       int *out_max_degrees,
                                       uint32_t *out_peak_energy,
                                       uint16_t *out_channel_difference_permille)
{
    // esp_doa currently returns 0..180 degrees at 20-degree resolution.
    uint64_t bucket_energy[10] = {0};
    uint32_t peak_energy = 0;
    size_t sample_count = 0;
    int min_degrees = 180;
    int max_degrees = 0;
    int peak_degrees = 90;
    uint16_t peak_difference = 0;
    const int64_t max_age_us = (int64_t)DEMO_SOUND_DIRECTION_HISTORY_MAX_AGE_MS * 1000;

    taskENTER_CRITICAL(&s_direction_lock);
    for (size_t index = 0; index < s_wake.direction_history_count; ++index) {
        const direction_sample_t *sample = &s_wake.direction_history[index];
        const int64_t age_us = now_us - sample->captured_us;
        if (sample->captured_us <= 0 || age_us < 0 || age_us > max_age_us) {
            continue;
        }
        int degrees = sample->degrees;
        if (degrees < 0) {
            degrees = 0;
        } else if (degrees > 180) {
            degrees = 180;
        }
        int bucket = (degrees + 10) / 20;
        if (bucket > 9) {
            bucket = 9;
        }
        bucket_energy[bucket] += sample->mean_energy;
        sample_count++;
        if (degrees < min_degrees) {
            min_degrees = degrees;
        }
        if (degrees > max_degrees) {
            max_degrees = degrees;
        }
        if (sample->mean_energy > peak_energy) {
            peak_energy = sample->mean_energy;
            peak_degrees = degrees;
            peak_difference = sample->channel_difference_permille;
        }
    }
    const bool latest_valid = s_wake.latest_direction_valid &&
                              now_us >= s_wake.latest_direction_us &&
                              now_us - s_wake.latest_direction_us <= max_age_us;
    const int latest_degrees = s_wake.latest_direction_degrees;
    taskEXIT_CRITICAL(&s_direction_lock);

    if (sample_count == 0) {
        if (!latest_valid) {
            return false;
        }
        *out_degrees = latest_degrees;
        *out_sample_count = 1;
        *out_min_degrees = latest_degrees;
        *out_max_degrees = latest_degrees;
        *out_peak_energy = 0;
        *out_channel_difference_permille = 0;
        return true;
    }

    int best_bucket = 0;
    uint64_t best_neighborhood_energy = 0;
    for (int bucket = 0; bucket < 10; ++bucket) {
        uint64_t neighborhood_energy = bucket_energy[bucket];
        if (bucket > 0) {
            neighborhood_energy += bucket_energy[bucket - 1];
        }
        if (bucket < 9) {
            neighborhood_energy += bucket_energy[bucket + 1];
        }
        if (neighborhood_energy > best_neighborhood_energy) {
            best_neighborhood_energy = neighborhood_energy;
            best_bucket = bucket;
        }
    }

    // Prefer the highest-energy speech frame inside the winning cluster. This
    // avoids the quiet tail after the wake word pulling every result to 90°.
    int selected_degrees = peak_degrees;
    uint32_t selected_energy = 0;
    uint16_t selected_difference = peak_difference;
    taskENTER_CRITICAL(&s_direction_lock);
    for (size_t index = 0; index < s_wake.direction_history_count; ++index) {
        const direction_sample_t *sample = &s_wake.direction_history[index];
        const int64_t age_us = now_us - sample->captured_us;
        if (sample->captured_us <= 0 || age_us < 0 || age_us > max_age_us) {
            continue;
        }
        int bucket = ((int)sample->degrees + 10) / 20;
        if (bucket < 0) {
            bucket = 0;
        } else if (bucket > 9) {
            bucket = 9;
        }
        if (bucket >= best_bucket - 1 && bucket <= best_bucket + 1 &&
            sample->mean_energy > selected_energy) {
            selected_energy = sample->mean_energy;
            selected_degrees = sample->degrees;
            selected_difference = sample->channel_difference_permille;
        }
    }
    taskEXIT_CRITICAL(&s_direction_lock);

    *out_degrees = selected_degrees;
    *out_sample_count = sample_count;
    *out_min_degrees = min_degrees;
    *out_max_degrees = max_degrees;
    *out_peak_energy = peak_energy;
    *out_channel_difference_permille = selected_difference;
    return true;
}

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
        .channel = DEMO_WAKE_AUDIO_CHANNELS,
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
             DEMO_WAKE_AUDIO_CHANNELS,
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

    const char *input_format = DEMO_SOUND_DIRECTION_ENABLED ? "MM" : "M";
    afe_config_t *afe_config = afe_config_init(input_format, s_wake.models, AFE_TYPE_SR, AFE_MODE_LOW_COST);
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

#if DEMO_SOUND_DIRECTION_ENABLED
    s_wake.doa = esp_doa_create(DEMO_AUDIO_SAMPLE_RATE,
                                DEMO_SOUND_DIRECTION_RESOLUTION_DEGREES,
                                DEMO_SOUND_DIRECTION_MIC_SPACING_METERS,
                                DEMO_SOUND_DIRECTION_FRAME_SAMPLES);
    if (s_wake.doa == NULL) {
        ESP_LOGW(TAG, "sound_direction_init_failed; wake word remains available");
    } else {
        ESP_LOGI(TAG,
                 "sound_direction_ready channels=%d spacing_m=%.3f frame_samples=%d resolution_deg=%.1f",
                 s_wake.feed_channels,
                 (double)DEMO_SOUND_DIRECTION_MIC_SPACING_METERS,
                 DEMO_SOUND_DIRECTION_FRAME_SAMPLES,
                 (double)DEMO_SOUND_DIRECTION_RESOLUTION_DEGREES);
    }
#endif

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

    int16_t *doa_left = NULL;
    int16_t *doa_right = NULL;
    size_t doa_fill = 0;
#if DEMO_SOUND_DIRECTION_ENABLED
    if (s_wake.doa != NULL && s_wake.feed_channels >= 2) {
        const size_t channel_bytes = DEMO_SOUND_DIRECTION_FRAME_SAMPLES * sizeof(int16_t);
        doa_left = heap_caps_malloc(channel_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        doa_right = heap_caps_malloc(channel_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (doa_left == NULL || doa_right == NULL) {
            heap_caps_free(doa_left);
            heap_caps_free(doa_right);
            doa_left = NULL;
            doa_right = NULL;
            ESP_LOGW(TAG, "sound_direction_frame_alloc_failed bytes_per_channel=%u",
                     (unsigned)channel_bytes);
        }
    }
#endif

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
#if DEMO_SOUND_DIRECTION_ENABLED
        if (doa_left != NULL && doa_right != NULL) {
            for (int sample = 0; sample < s_wake.feed_samples; ++sample) {
                doa_left[doa_fill] = buffer[(sample * s_wake.feed_channels)];
                doa_right[doa_fill] = buffer[(sample * s_wake.feed_channels) + 1];
                doa_fill++;
                if (doa_fill == DEMO_SOUND_DIRECTION_FRAME_SAMPLES) {
                    int64_t energy = 0;
                    int64_t difference_energy = 0;
                    for (size_t index = 0; index < doa_fill; ++index) {
                        const int32_t left = doa_left[index];
                        const int32_t right = doa_right[index];
                        const int32_t difference = left - right;
                        energy += ((int64_t)left * left + (int64_t)right * right) / 2;
                        difference_energy += (int64_t)difference * difference;
                    }
                    const int64_t minimum_energy =
                        (int64_t)DEMO_SOUND_DIRECTION_MIN_RMS *
                        (int64_t)DEMO_SOUND_DIRECTION_MIN_RMS *
                        (int64_t)doa_fill;
                    if (energy >= minimum_energy) {
                        float angle = esp_doa_process(s_wake.doa, doa_left, doa_right);
                        if (angle >= 0.0f && angle <= 180.0f) {
#if DEMO_SOUND_DIRECTION_REVERSED
                            angle = 180.0f - angle;
#endif
                            const uint32_t mean_energy = (uint32_t)(energy / (int64_t)doa_fill);
                            uint64_t difference_permille =
                                energy > 0 ? ((uint64_t)difference_energy * 1000ULL) / (uint64_t)energy : 0;
                            if (difference_permille > UINT16_MAX) {
                                difference_permille = UINT16_MAX;
                            }
                            wake_word_store_direction_sample((int)(angle + 0.5f),
                                                             mean_energy,
                                                             (uint16_t)difference_permille,
                                                             esp_timer_get_time());
                        }
                    }
                    doa_fill = 0;
                }
            }
        }
#endif
    }

    heap_caps_free(doa_left);
    heap_caps_free(doa_right);
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
            size_t direction_sample_count = 0;
            int direction_min_degrees = 90;
            int direction_max_degrees = 90;
            uint32_t direction_peak_energy = 0;
            uint16_t direction_channel_difference = 0;
            s_wake.detected_direction_valid =
                wake_word_select_direction(esp_timer_get_time(),
                                           &s_wake.detected_direction_degrees,
                                           &direction_sample_count,
                                           &direction_min_degrees,
                                           &direction_max_degrees,
                                           &direction_peak_energy,
                                           &direction_channel_difference);
            s_wake.event_pending = true;
            s_wake.stop_requested = true;
            ESP_LOGI(TAG,
                     "wake_word_detected word=%s model=%s wake_word_index=%d wakenet_model_index=%d direction_valid=%d direction_degrees=%d direction_samples=%u direction_range=%d..%d peak_energy=%u channel_difference_permille=%u",
                     s_wake.detected_word,
                     s_wake.detected_model,
                     result->wake_word_index,
                     result->wakenet_model_index,
                     s_wake.detected_direction_valid ? 1 : 0,
                     s_wake.detected_direction_degrees,
                     (unsigned)direction_sample_count,
                     direction_min_degrees,
                     direction_max_degrees,
                     (unsigned)direction_peak_energy,
                     (unsigned)direction_channel_difference);
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
    s_wake.detected_direction_valid = false;
    s_wake.detected_direction_degrees = 90;
    taskENTER_CRITICAL(&s_direction_lock);
    s_wake.latest_direction_valid = false;
    s_wake.latest_direction_degrees = 90;
    s_wake.latest_direction_us = 0;
    s_wake.direction_history_next = 0;
    s_wake.direction_history_count = 0;
    memset(s_wake.direction_history, 0, sizeof(s_wake.direction_history));
    taskEXIT_CRITICAL(&s_direction_lock);
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
    out_detection->direction_valid = s_wake.detected_direction_valid;
    out_detection->direction_degrees = (int16_t)s_wake.detected_direction_degrees;
    s_wake.event_pending = false;
    return true;
}
