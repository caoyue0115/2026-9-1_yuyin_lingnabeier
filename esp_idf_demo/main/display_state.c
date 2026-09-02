#include "display_state.h"

#include "config.h"
#include "idle_video.h"

#include "bsp/esp_vocat.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"
#include "lvgl.h"

#include <stdint.h>
#include <stdlib.h>

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
static TaskHandle_t s_idle_video_task;
static lv_obj_t *s_idle_image;
static lv_obj_t *s_orb;
static lv_obj_t *s_title;
static lv_obj_t *s_subtitle;
static lv_image_dsc_t s_idle_image_dsc;
static idle_video_t *s_idle_video;
static uint8_t *s_idle_frame_buffers[2];
static int s_idle_displayed_buffer;
static bool s_idle_video_ready;
static bool s_rendered_video_ready;

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

    s_idle_image = lv_image_create(screen);
    lv_obj_remove_flag(s_idle_image, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_align(s_idle_image, LV_ALIGN_CENTER, 0, 0);
    lv_obj_add_flag(s_idle_image, LV_OBJ_FLAG_HIDDEN);

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

static void display_set_standard_ui_visible(bool visible)
{
    if (visible) {
        lv_obj_remove_flag(s_orb, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_title, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_subtitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_idle_image, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_orb, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_title, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_subtitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_idle_image, LV_OBJ_FLAG_HIDDEN);
    }
}

static void display_render_state(display_ui_state_t state, bool idle_video_ready)
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

    const bool show_idle_video = state == DISPLAY_UI_IDLE && idle_video_ready;
    display_set_standard_ui_visible(!show_idle_video);
    if (show_idle_video) {
        return;
    }

    lv_label_set_text(s_title, title);
    lv_label_set_text(s_subtitle, subtitle);
    lv_obj_set_style_bg_color(s_orb, lv_color_hex(color), 0);
    lv_obj_set_style_shadow_color(s_orb, lv_color_hex(color), 0);
    lv_obj_align(s_title, LV_ALIGN_CENTER, 0, -10);
    lv_obj_align(s_subtitle, LV_ALIGN_CENTER, 0, 86);
}

static bool display_idle_video_is_active(void)
{
    bool active;
    taskENTER_CRITICAL(&s_lock);
    active = s_ui_state == DISPLAY_UI_IDLE && s_power_state != DISPLAY_POWER_OFF;
    taskEXIT_CRITICAL(&s_lock);
    return active;
}

static esp_err_t display_prepare_idle_video(void)
{
    idle_video_t *video = NULL;
    esp_err_t result = idle_video_open(DEMO_IDLE_VIDEO_PATH,
                                       DEMO_IDLE_VIDEO_MAX_BYTES,
                                       DEMO_IDLE_VIDEO_MAX_FRAMES,
                                       &video);
    if (result != ESP_OK) {
        return result;
    }
    if (idle_video_width(video) != DEMO_IDLE_VIDEO_WIDTH ||
        idle_video_height(video) != DEMO_IDLE_VIDEO_HEIGHT ||
        idle_video_frame_count(video) == 0) {
        idle_video_close(video);
        return ESP_ERR_INVALID_SIZE;
    }

    const size_t frame_bytes = (size_t)DEMO_IDLE_VIDEO_WIDTH * DEMO_IDLE_VIDEO_HEIGHT * sizeof(uint16_t);
    uint8_t *buffers[2] = {0};
    for (size_t index = 0; index < 2; ++index) {
        buffers[index] = heap_caps_malloc(frame_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (buffers[index] == NULL) {
            free(buffers[0]);
            free(buffers[1]);
            idle_video_close(video);
            return ESP_ERR_NO_MEM;
        }
    }
    result = idle_video_decode_frame(video, 0, buffers[0], frame_bytes);
    if (result != ESP_OK) {
        free(buffers[0]);
        free(buffers[1]);
        idle_video_close(video);
        return result;
    }

    s_idle_video = video;
    s_idle_frame_buffers[0] = buffers[0];
    s_idle_frame_buffers[1] = buffers[1];
    s_idle_displayed_buffer = 0;
    s_idle_image_dsc = (lv_image_dsc_t) {
        .header = {
            .magic = LV_IMAGE_HEADER_MAGIC,
            .cf = LV_COLOR_FORMAT_RGB565,
            .flags = LV_IMAGE_FLAGS_MODIFIABLE,
            .w = DEMO_IDLE_VIDEO_WIDTH,
            .h = DEMO_IDLE_VIDEO_HEIGHT,
            .stride = DEMO_IDLE_VIDEO_WIDTH * sizeof(uint16_t),
        },
        .data_size = frame_bytes,
        .data = s_idle_frame_buffers[0],
    };

    if (!bsp_display_lock(500)) {
        s_idle_video = NULL;
        s_idle_frame_buffers[0] = NULL;
        s_idle_frame_buffers[1] = NULL;
        free(buffers[0]);
        free(buffers[1]);
        idle_video_close(video);
        return ESP_ERR_TIMEOUT;
    }
    lv_image_set_src(s_idle_image, &s_idle_image_dsc);
    lv_obj_align(s_idle_image, LV_ALIGN_CENTER, 0, 0);
    bsp_display_unlock();

    taskENTER_CRITICAL(&s_lock);
    s_idle_video_ready = true;
    taskEXIT_CRITICAL(&s_lock);
    ESP_LOGI(TAG,
             "idle_video_ready path=%s frames=%u size=%ux%u frame_interval_ms=%d",
             DEMO_IDLE_VIDEO_PATH,
             (unsigned)idle_video_frame_count(s_idle_video),
             (unsigned)idle_video_width(s_idle_video),
             (unsigned)idle_video_height(s_idle_video),
             DEMO_IDLE_VIDEO_FRAME_INTERVAL_MS);
    return ESP_OK;
}

static void display_idle_video_task(void *arg)
{
    (void)arg;
    while (!display_idle_video_is_active()) {
        vTaskDelay(pdMS_TO_TICKS(100));
    }

    esp_err_t result;
    while ((result = display_prepare_idle_video()) != ESP_OK) {
        ESP_LOGW(TAG, "idle_video_prepare_failed path=%s err=%s",
                 DEMO_IDLE_VIDEO_PATH,
                 esp_err_to_name(result));
        vTaskDelay(pdMS_TO_TICKS(1000));
    }

    const size_t frame_bytes = (size_t)DEMO_IDLE_VIDEO_WIDTH * DEMO_IDLE_VIDEO_HEIGHT * sizeof(uint16_t);
    const size_t frame_count = idle_video_frame_count(s_idle_video);
    size_t frame_index = frame_count > 1 ? 1 : 0;
    while (true) {
        if (!display_idle_video_is_active()) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        const int64_t frame_started_us = esp_timer_get_time();
        const int decode_buffer = s_idle_displayed_buffer == 0 ? 1 : 0;
        result = idle_video_decode_frame(s_idle_video,
                                         frame_index,
                                         s_idle_frame_buffers[decode_buffer],
                                         frame_bytes);
        if (result != ESP_OK) {
            ESP_LOGW(TAG, "idle_video_decode_failed frame=%u err=%s",
                     (unsigned)frame_index,
                     esp_err_to_name(result));
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        if (display_idle_video_is_active() && bsp_display_lock(100)) {
            s_idle_image_dsc.data = s_idle_frame_buffers[decode_buffer];
            lv_image_set_src(s_idle_image, &s_idle_image_dsc);
            lv_obj_invalidate(s_idle_image);
            s_idle_displayed_buffer = decode_buffer;
            bsp_display_unlock();
        }
        frame_index = (frame_index + 1) % frame_count;

        const int elapsed_ms = (int)((esp_timer_get_time() - frame_started_us) / 1000);
        const int remaining_ms = DEMO_IDLE_VIDEO_FRAME_INTERVAL_MS - elapsed_ms;
        if (remaining_ms > 0) {
            vTaskDelay(pdMS_TO_TICKS(remaining_ms));
        } else {
            taskYIELD();
        }
    }
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
        bool idle_video_ready;
        taskENTER_CRITICAL(&s_lock);
        ui_state = s_ui_state;
        current_power = s_power_state;
        last_activity_us = s_last_activity_us;
        idle_video_ready = s_idle_video_ready;
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

        if ((ui_state != s_rendered_state || idle_video_ready != s_rendered_video_ready) &&
            bsp_display_lock(100)) {
            display_render_state(ui_state, idle_video_ready);
            s_rendered_state = ui_state;
            s_rendered_video_ready = idle_video_ready;
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
    const bsp_display_cfg_t display_cfg = {
        .lvgl_port_cfg = ESP_LVGL_PORT_INIT_CONFIG(),
        .buffer_size = BSP_LCD_H_RES * DEMO_DISPLAY_BUFFER_HEIGHT,
        .double_buffer = DEMO_DISPLAY_DOUBLE_BUFFER != 0,
        .flags = {
            .buff_dma = true,
            .buff_spiram = false,
            .sw_rotate = false,
        },
    };
    ESP_LOGI(TAG,
             "display_buffer rows=%d double=%d bytes=%u",
             DEMO_DISPLAY_BUFFER_HEIGHT,
             DEMO_DISPLAY_DOUBLE_BUFFER,
             (unsigned)(display_cfg.buffer_size * sizeof(lv_color_t)));
    if (bsp_display_start_with_config(&display_cfg) == NULL) {
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
    if (created != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
#if DEMO_IDLE_VIDEO_ENABLED
#if CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM
    BaseType_t video_created = xTaskCreateWithCaps(display_idle_video_task,
                                                   "judy_idle_video",
                                                   DEMO_IDLE_VIDEO_TASK_STACK_SIZE,
                                                   NULL,
                                                   tskIDLE_PRIORITY + 1,
                                                   &s_idle_video_task,
                                                   MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
#else
    BaseType_t video_created = xTaskCreate(display_idle_video_task,
                                           "judy_idle_video",
                                           DEMO_IDLE_VIDEO_TASK_STACK_SIZE,
                                           NULL,
                                           tskIDLE_PRIORITY + 1,
                                           &s_idle_video_task);
#endif
    if (video_created != pdPASS) {
        ESP_LOGW(TAG, "idle_video_task_start_failed; READY text fallback remains active");
    }
#endif
    return ESP_OK;
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
