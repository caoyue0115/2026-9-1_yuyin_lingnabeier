#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_lcd_touch.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"

typedef enum {
    TRIGGER_EVENT_NONE = 0,
    TRIGGER_EVENT_BUTTON,
    TRIGGER_EVENT_TOUCH,
    TRIGGER_EVENT_WAKE_WORD,
    TRIGGER_EVENT_BUTTON_AND_WAKE_WORD,
    TRIGGER_EVENT_WIFI_RECONFIG,
} trigger_event_type_t;

typedef struct {
    bool initialized;
    bool warned_unsupported;
    bool accepting_events;
    bool wake_word_fallback_logged;
    bool wake_word_ready;
    TickType_t wake_word_next_retry_tick;
    int active_level;
    int debounced_level;
    int last_sample_level;
    TickType_t last_change_tick;
    TickType_t debounce_ticks;
    TickType_t button_active_since_tick;
    bool button_press_in_progress;
    bool wifi_reconfig_initialized;
    int wifi_reconfig_active_level;
    int wifi_reconfig_debounced_level;
    int wifi_reconfig_last_sample_level;
    TickType_t wifi_reconfig_last_change_tick;
    TickType_t wifi_reconfig_active_since_tick;
    bool wifi_reconfig_press_in_progress;
    bool wifi_reconfig_long_press_reported;
    trigger_event_type_t configured_source;
    esp_lcd_touch_handle_t touch_handle;
    bool touch_pressed;
} trigger_input_t;

typedef struct {
    trigger_event_type_t type;
    uint16_t x;
    uint16_t y;
    bool sound_direction_valid;
    int16_t sound_direction_degrees;
} trigger_event_t;

const char *trigger_input_source_name(trigger_event_type_t type);
trigger_event_type_t trigger_input_configured_source(void);
esp_err_t trigger_input_init(trigger_input_t *trigger);
esp_err_t trigger_input_set_accepting(trigger_input_t *trigger, bool accepting);
bool trigger_input_poll(trigger_input_t *trigger, trigger_event_t *out_event);
