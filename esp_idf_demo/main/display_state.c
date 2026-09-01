#include "display_state.h"

#include "config.h"

#include "bsp/esp_vocat.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"

#include <stdint.h>

typedef enum {
    DISPLAY_POWER_ACTIVE = 0,
    DISPLAY_POWER_DIMMED,
    DISPLAY_POWER_OFF,
} display_power_state_t;

static const char *TAG = "disney_display";
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static display_ui_state_t s_ui_state = DISPLAY_UI_BOOT;
static display_ui_state_t s_rendered_state = (display_ui_state_t)-1;
static display_power_state_t s_power_state = DISPLAY_POWER_ACTIVE;
static bool s_initialized;
static int64_t s_last_activity_us;
static TaskHandle_t s_display_task;
static lv_obj_t *s_orb;
static lv_obj_t *s_title;
static lv_obj_t *s_subtitle;

static void display_orb_size_anim(void *object, int32_t size)
{
    lv_obj_set_size((lv_obj_t *)object, size, size);
    lv_obj_align((lv_obj_t *)object, LV_ALIGN_CENTER, 0, -8);
}

static void display_create_ui(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x17112A), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);

    s_orb = lv_obj_create(screen);
    lv_obj_remove_flag(s_orb, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_size(s_orb, 138, 138);
    lv_obj_align(s_orb, LV_ALIGN_CENTER, 0, -8);
    lv_obj_set_style_radius(s_orb, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(s_orb, 0, 0);
    lv_obj_set_style_shadow_width(s_orb, 32, 0);
    lv_obj_set_style_shadow_opa(s_orb, LV_OPA_40, 0);

    s_title = lv_label_create(screen);
    lv_obj_set_style_text_color(s_title, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_text_letter_space(s_title, 2, 0);
    lv_obj_align(s_title, LV_ALIGN_CENTER, 0, -10);

    s_subtitle = lv_label_create(screen);
    lv_obj_set_style_text_color(s_subtitle, lv_color_hex(0xD8CFF2), 0);
    lv_obj_set_style_text_letter_space(s_subtitle, 1, 0);
    lv_obj_align(s_subtitle, LV_ALIGN_CENTER, 0, 86);

    lv_anim_t animation;
    lv_anim_init(&animation);
    lv_anim_set_var(&animation, s_orb);
    lv_anim_set_exec_cb(&animation, display_orb_size_anim);
    lv_anim_set_values(&animation, 132, 148);
    lv_anim_set_duration(&animation, 900);
    lv_anim_set_playback_duration(&animation, 900);
    lv_anim_set_repeat_count(&animation, LV_ANIM_REPEAT_INFINITE);
    lv_anim_start(&animation);
}

static void display_render_state(display_ui_state_t state)
{
    const char *title = "DISNEY DEMO";
    const char *subtitle = "STARTING";
    uint32_t color = 0xF28AB2;

    switch (state) {
    case DISPLAY_UI_IDLE:
        title = "READY";
        subtitle = "SAY XIAO MING";
        color = 0xB59BFF;
        break;
    case DISPLAY_UI_LISTENING:
        title = "LISTENING";
        subtitle = "I'M ALL EARS";
        color = 0x66D4E8;
        break;
    case DISPLAY_UI_THINKING:
        title = "THINKING";
        subtitle = "ONE MOMENT";
        color = 0xFFD166;
        break;
    case DISPLAY_UI_SPEAKING:
        title = "SPEAKING";
        subtitle = "HERE WE GO";
        color = 0xF28AB2;
        break;
    case DISPLAY_UI_NETWORK_REQUIRED:
        title = "NETWORK";
        subtitle = "SETUP REQUIRED";
        color = 0xFF9F68;
        break;
    case DISPLAY_UI_ERROR:
        title = "OOPS";
        subtitle = "TRY AGAIN";
        color = 0xFF6B7A;
        break;
    case DISPLAY_UI_BOOT:
    default:
        break;
    }

    lv_label_set_text(s_title, title);
    lv_label_set_text(s_subtitle, subtitle);
    lv_obj_set_style_bg_color(s_orb, lv_color_hex(color), 0);
    lv_obj_set_style_shadow_color(s_orb, lv_color_hex(color), 0);
    lv_obj_align(s_title, LV_ALIGN_CENTER, 0, -10);
    lv_obj_align(s_subtitle, LV_ALIGN_CENTER, 0, 86);
}

static void display_touch_event(lv_event_t *event)
{
    (void)event;
    bool should_wake = false;
    taskENTER_CRITICAL(&s_lock);
    if (s_power_state == DISPLAY_POWER_OFF) {
        s_last_activity_us = esp_timer_get_time();
        s_power_state = DISPLAY_POWER_ACTIVE;
        should_wake = true;
    }
    taskEXIT_CRITICAL(&s_lock);

    if (should_wake) {
        ESP_LOGI(TAG, "display_wake source=touch");
        (void)bsp_display_brightness_set(DEMO_DISPLAY_ACTIVE_BRIGHTNESS);
    }
}

static void display_apply_power(display_power_state_t power)
{
    int brightness = DEMO_DISPLAY_ACTIVE_BRIGHTNESS;
    if (power == DISPLAY_POWER_DIMMED) {
        brightness = DEMO_DISPLAY_DIM_BRIGHTNESS;
    } else if (power == DISPLAY_POWER_OFF) {
        brightness = 0;
    }
    (void)bsp_display_brightness_set(brightness);
    ESP_LOGI(TAG, "display_power=%s brightness=%d",
             power == DISPLAY_POWER_ACTIVE ? "active" :
             power == DISPLAY_POWER_DIMMED ? "dimmed" : "off",
             brightness);
}

static void display_task(void *arg)
{
    (void)arg;
    while (true) {
        display_ui_state_t ui_state;
        display_power_state_t current_power;
        int64_t last_activity_us;
        taskENTER_CRITICAL(&s_lock);
        ui_state = s_ui_state;
        current_power = s_power_state;
        last_activity_us = s_last_activity_us;
        taskEXIT_CRITICAL(&s_lock);

        display_power_state_t desired_power = DISPLAY_POWER_ACTIVE;
        if (ui_state == DISPLAY_UI_IDLE) {
            const int64_t idle_ms = (esp_timer_get_time() - last_activity_us) / 1000;
            if (idle_ms >= DEMO_DISPLAY_OFF_AFTER_MS) {
                desired_power = DISPLAY_POWER_OFF;
            } else if (idle_ms >= DEMO_DISPLAY_DIM_AFTER_MS) {
                desired_power = DISPLAY_POWER_DIMMED;
            }
        }

        if (desired_power != current_power) {
            taskENTER_CRITICAL(&s_lock);
            s_power_state = desired_power;
            taskEXIT_CRITICAL(&s_lock);
            display_apply_power(desired_power);
        }

        if (ui_state != s_rendered_state && bsp_display_lock(100)) {
            display_render_state(ui_state);
            s_rendered_state = ui_state;
            bsp_display_unlock();
        }
        vTaskDelay(pdMS_TO_TICKS(DEMO_DISPLAY_POLL_MS));
    }
}

esp_err_t display_state_init(void)
{
    if (s_display_task != NULL) {
        return ESP_OK;
    }
    if (bsp_display_start() == NULL) {
        return ESP_FAIL;
    }
    if (!bsp_display_lock(1000)) {
        return ESP_ERR_TIMEOUT;
    }
    display_create_ui();
    lv_indev_t *touch = bsp_display_get_input_dev();
    if (touch != NULL) {
        lv_indev_add_event_cb(touch, display_touch_event, LV_EVENT_PRESSED, NULL);
    }
    bsp_display_unlock();

    s_last_activity_us = esp_timer_get_time();
    s_power_state = DISPLAY_POWER_ACTIVE;
    s_initialized = true;
    (void)bsp_display_brightness_set(DEMO_DISPLAY_ACTIVE_BRIGHTNESS);
    BaseType_t created = xTaskCreate(display_task,
                                     "disney_display",
                                     DEMO_DISPLAY_TASK_STACK_SIZE,
                                     NULL,
                                     tskIDLE_PRIORITY + 1,
                                     &s_display_task);
    return created == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}

void display_state_set(display_ui_state_t state)
{
    if (!s_initialized) {
        return;
    }
    taskENTER_CRITICAL(&s_lock);
    s_ui_state = state;
    s_last_activity_us = esp_timer_get_time();
    s_power_state = DISPLAY_POWER_ACTIVE;
    taskEXIT_CRITICAL(&s_lock);
    (void)bsp_display_brightness_set(DEMO_DISPLAY_ACTIVE_BRIGHTNESS);
}

void display_state_notify_wake_word(void)
{
    ESP_LOGI(TAG, "display_wake source=wake_word");
    display_state_set(DISPLAY_UI_LISTENING);
}

bool display_state_is_off(void)
{
    if (!s_initialized) {
        return false;
    }
    bool is_off;
    taskENTER_CRITICAL(&s_lock);
    is_off = s_power_state == DISPLAY_POWER_OFF;
    taskEXIT_CRITICAL(&s_lock);
    return is_off;
}
