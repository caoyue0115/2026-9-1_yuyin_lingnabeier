#include "trigger_input.h"

#include "config.h"
#include "wake_word_service.h"

#include "bsp/touch.h"
#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "trigger_input";

const char *trigger_input_source_name(trigger_event_type_t type)
{
    switch (type) {
    case TRIGGER_EVENT_BUTTON:
        return "button";
    case TRIGGER_EVENT_TOUCH:
        return "touch";
    case TRIGGER_EVENT_WAKE_WORD:
        return "wake_word";
    case TRIGGER_EVENT_BUTTON_AND_WAKE_WORD:
        return "button+wake_word";
    case TRIGGER_EVENT_WIFI_RECONFIG:
        return "wifi_reconfig";
    case TRIGGER_EVENT_NONE:
    default:
        return "none";
    }
}

trigger_event_type_t trigger_input_configured_source(void)
{
    switch (DEMO_TRIGGER_SOURCE) {
    case DEMO_TRIGGER_SOURCE_BUTTON:
        return TRIGGER_EVENT_BUTTON;
    case DEMO_TRIGGER_SOURCE_TOUCH:
        return TRIGGER_EVENT_TOUCH;
    case DEMO_TRIGGER_SOURCE_WAKE_WORD:
        return TRIGGER_EVENT_WAKE_WORD;
    case DEMO_TRIGGER_SOURCE_BUTTON_AND_WAKE_WORD:
        return TRIGGER_EVENT_BUTTON_AND_WAKE_WORD;
    default:
        return TRIGGER_EVENT_NONE;
    }
}

static esp_err_t trigger_input_init_button(trigger_input_t *trigger)
{
    gpio_config_t io_conf = {
        .pin_bit_mask = 1ULL << DEMO_BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = DEMO_BUTTON_PULL_UP_ENABLE ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
        .pull_down_en = DEMO_BUTTON_PULL_DOWN_ENABLE ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    esp_err_t ret = gpio_config(&io_conf);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to configure trigger GPIO %d: %s",
                 DEMO_BUTTON_GPIO, esp_err_to_name(ret));
        return ret;
    }

    const int initial_level = gpio_get_level(DEMO_BUTTON_GPIO);
    trigger->initialized = true;
    trigger->active_level = DEMO_BUTTON_ACTIVE_LEVEL;
    trigger->debounced_level = initial_level;
    trigger->last_sample_level = initial_level;
    trigger->last_change_tick = xTaskGetTickCount();
    trigger->debounce_ticks = pdMS_TO_TICKS(DEMO_BUTTON_DEBOUNCE_MS);
    trigger->button_active_since_tick = 0;
    trigger->button_press_in_progress = false;

    ESP_LOGI(TAG,
             "Initialized GPIO7 voice/wake trigger: gpio=%d active_level=%d initial_level=%d",
             DEMO_BUTTON_GPIO,
             DEMO_BUTTON_ACTIVE_LEVEL,
             initial_level);
    return ESP_OK;
}

static esp_err_t trigger_input_init_wifi_reconfig_button(trigger_input_t *trigger)
{
    gpio_config_t io_conf = {
        .pin_bit_mask = 1ULL << DEMO_WIFI_RECONFIG_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = DEMO_WIFI_RECONFIG_PULL_UP_ENABLE ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
        .pull_down_en = DEMO_WIFI_RECONFIG_PULL_DOWN_ENABLE ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    esp_err_t ret = gpio_config(&io_conf);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to configure Wi-Fi reconfig GPIO %d: %s",
                 DEMO_WIFI_RECONFIG_GPIO, esp_err_to_name(ret));
        return ret;
    }

    const int initial_level = gpio_get_level(DEMO_WIFI_RECONFIG_GPIO);
    trigger->wifi_reconfig_initialized = true;
    trigger->wifi_reconfig_active_level = DEMO_WIFI_RECONFIG_ACTIVE_LEVEL;
    trigger->wifi_reconfig_debounced_level = initial_level;
    trigger->wifi_reconfig_last_sample_level = initial_level;
    trigger->wifi_reconfig_last_change_tick = xTaskGetTickCount();
    trigger->wifi_reconfig_active_since_tick = 0;
    trigger->wifi_reconfig_press_in_progress = false;
    trigger->wifi_reconfig_long_press_reported = false;
    trigger->debounce_ticks = pdMS_TO_TICKS(DEMO_BUTTON_DEBOUNCE_MS);

    ESP_LOGI(TAG,
             "Initialized GPIO0 boot key Wi-Fi reconfig long press: gpio=%d active_level=%d hold_ms=%d initial_level=%d",
             DEMO_WIFI_RECONFIG_GPIO,
             DEMO_WIFI_RECONFIG_ACTIVE_LEVEL,
             DEMO_WIFI_RECONFIG_LONG_PRESS_MS,
             initial_level);
    return ESP_OK;
}

static esp_err_t trigger_input_init_touch(trigger_input_t *trigger)
{
    esp_err_t ret = bsp_touch_new(NULL, &trigger->touch_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to initialize %s %s touch input: %s",
                 DEMO_BOARD_NAME, DEMO_BOARD_REVISION, esp_err_to_name(ret));
        return ret;
    }

    trigger->initialized = true;
    trigger->touch_pressed = false;
    ESP_LOGI(TAG, "Initialized %s %s touch trigger", DEMO_BOARD_NAME, DEMO_BOARD_REVISION);
    return ESP_OK;
}

static bool trigger_input_is_button_enabled(const trigger_input_t *trigger)
{
    return trigger->configured_source == TRIGGER_EVENT_BUTTON ||
           trigger->configured_source == TRIGGER_EVENT_BUTTON_AND_WAKE_WORD;
}

static bool trigger_input_is_wake_word_enabled(const trigger_input_t *trigger)
{
    return trigger->configured_source == TRIGGER_EVENT_WAKE_WORD ||
           trigger->configured_source == TRIGGER_EVENT_BUTTON_AND_WAKE_WORD;
}

static esp_err_t trigger_input_start_wake_word(trigger_input_t *trigger)
{
#if DEMO_WAKE_WORD_ENABLED
    esp_err_t ret = wake_word_service_start();
    if (ret != ESP_OK && !trigger->wake_word_fallback_logged) {
        ESP_LOGW(TAG,
                 "wake_word_start_failed err=%s; keeping GPIO7 button fallback active",
                 esp_err_to_name(ret));
        trigger->wake_word_fallback_logged = true;
    }
    return ret;
#else
    if (!trigger->wake_word_fallback_logged) {
        ESP_LOGI(TAG, "wake_word_disabled; keeping GPIO7 button fallback active");
        trigger->wake_word_fallback_logged = true;
    }
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t trigger_input_init(trigger_input_t *trigger)
{
    if (trigger == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    trigger->configured_source = trigger_input_configured_source();
    trigger->accepting_events = true;
    esp_err_t reconfig_ret = trigger_input_init_wifi_reconfig_button(trigger);
    if (reconfig_ret != ESP_OK) {
        return reconfig_ret;
    }
    switch (trigger->configured_source) {
    case TRIGGER_EVENT_BUTTON:
        return trigger_input_init_button(trigger);
    case TRIGGER_EVENT_TOUCH:
        return trigger_input_init_touch(trigger);
    case TRIGGER_EVENT_WAKE_WORD: {
        esp_err_t wake_word_ret = trigger_input_start_wake_word(trigger);
        if (wake_word_ret == ESP_OK) {
            trigger->initialized = true;
        }
        return wake_word_ret;
    }
    case TRIGGER_EVENT_BUTTON_AND_WAKE_WORD: {
        esp_err_t button_ret = trigger_input_init_button(trigger);
        if (button_ret != ESP_OK) {
            return button_ret;
        }
        (void)trigger_input_start_wake_word(trigger);
        ESP_LOGI(TAG, "Initialized combined GPIO7 voice/wake trigger + WakeNet wake_word trigger with GPIO0 boot key Wi-Fi reconfig long press");
        return ESP_OK;
    }
    case TRIGGER_EVENT_NONE:
    default:
        return ESP_ERR_INVALID_STATE;
    }
}

void trigger_input_set_accepting(trigger_input_t *trigger, bool accepting)
{
    if (trigger == NULL) {
        return;
    }

    if (trigger->accepting_events == accepting) {
        return;
    }

    trigger->accepting_events = accepting;
    if (!trigger_input_is_wake_word_enabled(trigger)) {
        return;
    }

    if (accepting) {
        (void)trigger_input_start_wake_word(trigger);
    } else {
        wake_word_service_stop();
        ESP_LOGI(TAG, "wake_word_paused_for_pipeline; button fallback remains active");
    }
}

static bool trigger_input_poll_wifi_reconfig_button(trigger_input_t *trigger, trigger_event_t *out_event)
{
    if (!trigger->wifi_reconfig_initialized) {
        return false;
    }

    const TickType_t now = xTaskGetTickCount();
    const int current_level = gpio_get_level(DEMO_WIFI_RECONFIG_GPIO);

    if (current_level != trigger->wifi_reconfig_last_sample_level) {
        ESP_LOGI(TAG,
                 "Wi-Fi reconfig boot key raw level change: gpio=%d level=%d",
                 DEMO_WIFI_RECONFIG_GPIO,
                 current_level);
        trigger->wifi_reconfig_last_sample_level = current_level;
        trigger->wifi_reconfig_last_change_tick = now;
        return false;
    }

    if ((now - trigger->wifi_reconfig_last_change_tick) < trigger->debounce_ticks) {
        return false;
    }

    if (trigger->wifi_reconfig_debounced_level == current_level) {
        if (current_level == trigger->wifi_reconfig_active_level &&
            trigger->wifi_reconfig_press_in_progress &&
            !trigger->wifi_reconfig_long_press_reported &&
            (now - trigger->wifi_reconfig_active_since_tick) >= pdMS_TO_TICKS(DEMO_WIFI_RECONFIG_LONG_PRESS_MS)) {
            trigger->wifi_reconfig_long_press_reported = true;
            out_event->type = TRIGGER_EVENT_WIFI_RECONFIG;
            ESP_LOGI(TAG,
                     "boot_key_long_press_wifi_reconfig gpio=%d hold_ms=%d",
                     DEMO_WIFI_RECONFIG_GPIO,
                     DEMO_WIFI_RECONFIG_LONG_PRESS_MS);
            return true;
        }
        return false;
    }

    trigger->wifi_reconfig_debounced_level = current_level;
    ESP_LOGI(TAG,
             "Wi-Fi reconfig boot key debounced level: gpio=%d level=%d",
             DEMO_WIFI_RECONFIG_GPIO,
             current_level);
    if (current_level == trigger->wifi_reconfig_active_level) {
        trigger->wifi_reconfig_press_in_progress = true;
        trigger->wifi_reconfig_active_since_tick = now;
        trigger->wifi_reconfig_long_press_reported = false;
        ESP_LOGI(TAG,
                 "Wi-Fi reconfig boot key press started: gpio=%d level=%d",
                 DEMO_WIFI_RECONFIG_GPIO,
                 current_level);
        return false;
    }

    if (trigger->wifi_reconfig_press_in_progress) {
        trigger->wifi_reconfig_press_in_progress = false;
        trigger->wifi_reconfig_active_since_tick = 0;
        trigger->wifi_reconfig_long_press_reported = false;
    }

    return false;
}

static bool trigger_input_poll_button(trigger_input_t *trigger, trigger_event_t *out_event)
{
    const TickType_t now = xTaskGetTickCount();
    const int current_level = gpio_get_level(DEMO_BUTTON_GPIO);

    if (current_level != trigger->last_sample_level) {
        ESP_LOGI(TAG, "GPIO trigger raw level change: gpio=%d level=%d", DEMO_BUTTON_GPIO, current_level);
        trigger->last_sample_level = current_level;
        trigger->last_change_tick = now;
        return false;
    }

    if ((now - trigger->last_change_tick) < trigger->debounce_ticks) {
        return false;
    }

    if (trigger->debounced_level == current_level) {
        return false;
    }

    trigger->debounced_level = current_level;
    ESP_LOGI(TAG, "GPIO trigger debounced level: gpio=%d level=%d", DEMO_BUTTON_GPIO, current_level);
    if (current_level == trigger->active_level) {
        trigger->button_press_in_progress = true;
        trigger->button_active_since_tick = now;
        ESP_LOGI(TAG, "Button press started: gpio=%d level=%d", DEMO_BUTTON_GPIO, current_level);
        return false;
    }

    if (trigger->button_press_in_progress) {
        const TickType_t held_ticks = now - trigger->button_active_since_tick;
        trigger->button_press_in_progress = false;
        trigger->button_active_since_tick = 0;

        if (held_ticks >= pdMS_TO_TICKS(DEMO_WIFI_RECONFIG_LONG_PRESS_MS)) {
            ESP_LOGI(TAG,
                     "voice_button_long_press_ignored gpio=%d held_ms=%u wifi_reconfig_gpio=%d",
                     DEMO_BUTTON_GPIO,
                     (unsigned)(held_ticks * portTICK_PERIOD_MS),
                     DEMO_WIFI_RECONFIG_GPIO);
            return false;
        }

        out_event->type = TRIGGER_EVENT_BUTTON;
        ESP_LOGI(TAG,
                 "Button trigger event: gpio=%d level=%d held_ms=%u",
                 DEMO_BUTTON_GPIO,
                 current_level,
                 (unsigned)(held_ticks * portTICK_PERIOD_MS));
        return true;
    }

    return false;
}

bool trigger_input_poll(trigger_input_t *trigger, trigger_event_t *out_event)
{
    if (trigger == NULL || out_event == NULL) {
        return false;
    }

    out_event->type = TRIGGER_EVENT_NONE;
    out_event->x = 0;
    out_event->y = 0;

    if (!trigger->initialized) {
        if (trigger_input_init(trigger) != ESP_OK) {
            return false;
        }
    }

    if (trigger_input_poll_wifi_reconfig_button(trigger, out_event)) {
        return true;
    }

    if (trigger_input_is_wake_word_enabled(trigger) && trigger->accepting_events) {
        wake_word_detection_t detection = {0};
        if (wake_word_service_poll(&detection)) {
            out_event->type = TRIGGER_EVENT_WAKE_WORD;
            ESP_LOGI(TAG,
                     "Wake word trigger event: word=%s model=%s; GPIO7 button fallback remains active",
                     detection.word,
                     detection.model);
            return true;
        }
    }

    if (trigger->configured_source == TRIGGER_EVENT_TOUCH) {
        esp_lcd_touch_point_data_t point = {0};
        uint8_t point_count = 0;
        bool pressed = false;

        if (esp_lcd_touch_read_data(trigger->touch_handle) != ESP_OK) {
            return false;
        }

        if (esp_lcd_touch_get_data(trigger->touch_handle, &point, &point_count, 1) == ESP_OK &&
            point_count > 0) {
            pressed = true;
        }

        if (pressed && !trigger->touch_pressed) {
            trigger->touch_pressed = true;
            out_event->type = TRIGGER_EVENT_TOUCH;
            out_event->x = point.x;
            out_event->y = point.y;
            ESP_LOGI(TAG, "Touch trigger event: x=%u y=%u", (unsigned)point.x, (unsigned)point.y);
            return true;
        }

        trigger->touch_pressed = pressed;
        return false;
    }

    if (trigger->configured_source == TRIGGER_EVENT_WAKE_WORD) {
        return false;
    }

    if (!trigger_input_is_button_enabled(trigger)) {
        if (!trigger->warned_unsupported) {
            ESP_LOGW(TAG,
                     "Trigger source %s is configured but not active in this build",
                     trigger_input_source_name(trigger->configured_source));
            trigger->warned_unsupported = true;
        }
        return false;
    }

    return trigger_input_poll_button(trigger, out_event);
}
