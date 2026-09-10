#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    DISPLAY_UI_BOOT = 0,
    DISPLAY_UI_IDLE,
    DISPLAY_UI_LISTENING,
    DISPLAY_UI_THINKING,
    DISPLAY_UI_SPEAKING,
    DISPLAY_UI_NETWORK_REQUIRED,
    DISPLAY_UI_ERROR,
} display_ui_state_t;

typedef void (*display_touch_callback_t)(void *user_ctx);

esp_err_t display_state_init(void);
void display_state_set_touch_callback(display_touch_callback_t callback, void *user_ctx);
void display_state_set(display_ui_state_t state);
void display_state_notify_wake_word(void);
void display_state_set_sound_direction(int degrees, bool valid);
bool display_state_is_off(void);

#ifdef __cplusplus
}
#endif
