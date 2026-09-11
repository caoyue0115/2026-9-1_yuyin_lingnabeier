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

typedef enum {
    DISPLAY_VIDEO_NONE = -1,
    DISPLAY_VIDEO_IDLE = 0,
    DISPLAY_VIDEO_LISTENING_THINKING,
    DISPLAY_VIDEO_SPEAKING,
    DISPLAY_VIDEO_COUNT,
} display_video_asset_t;

typedef enum {
    DISPLAY_IDLE_PAGE_ASSISTANT = 0,
    DISPLAY_IDLE_PAGE_DESKTOP,
} display_idle_page_t;

#define DISPLAY_IDLE_SWIPE_MIN_DISTANCE_PX (BSP_LCD_H_RES / 6)
#define DISPLAY_IDLE_TAP_MAX_MOVEMENT_PX 24
#define DISPLAY_MUSIC_CARD_WIDTH 270
#define DISPLAY_MUSIC_CARD_HEIGHT 156
#define DISPLAY_MUSIC_CARD_CENTER_Y (-5)

static const char *TAG = "disney_display";
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static display_ui_state_t s_ui_state = DISPLAY_UI_BOOT;
static display_ui_state_t s_rendered_state = (display_ui_state_t)-1;
static display_power_state_t s_power_state = DISPLAY_POWER_ACTIVE;
static display_idle_page_t s_idle_page = DISPLAY_IDLE_PAGE_ASSISTANT;
static uint32_t s_idle_page_revision;
static uint32_t s_rendered_idle_page_revision;
static bool s_music_playing;
static uint32_t s_music_revision;
static uint32_t s_rendered_music_revision;
static bool s_idle_swipe_tracking;
static lv_point_t s_idle_swipe_start;
static lv_point_t s_idle_swipe_last;
static display_video_asset_t s_published_video_asset = DISPLAY_VIDEO_NONE;
static display_video_asset_t s_rendered_video_asset = DISPLAY_VIDEO_NONE;
static bool s_initialized;
static int64_t s_last_activity_us;
static TaskHandle_t s_display_task;
static TaskHandle_t s_state_video_task;
static lv_obj_t *s_state_image;
static lv_obj_t *s_orb;
static lv_obj_t *s_title;
static lv_obj_t *s_subtitle;
static lv_obj_t *s_direction_marker;
static lv_obj_t *s_desktop_root;
static lv_obj_t *s_desktop_title;
static lv_obj_t *s_desktop_voice_card;
static lv_obj_t *s_desktop_voice_title;
static lv_obj_t *s_desktop_voice_hint;
static lv_obj_t *s_desktop_music_hint;
static lv_obj_t *s_desktop_swipe_hint;
static bool s_direction_valid;
static int s_direction_degrees = 90;
static uint32_t s_direction_revision;
static uint32_t s_rendered_direction_revision;
static lv_image_dsc_t s_state_image_dsc;
static idle_video_t *s_state_videos[DISPLAY_VIDEO_COUNT];
static idle_video_decoder_t *s_video_decoder;
static uint8_t *s_video_frame_buffers[2];
static int s_video_displayed_buffer;
static display_touch_callback_t s_touch_callback;
static void *s_touch_callback_ctx;
static display_music_toggle_callback_t s_music_toggle_callback;
static void *s_music_toggle_callback_ctx;
static lv_indev_t *s_touch_indev;

static display_video_asset_t display_video_asset_for_state(display_ui_state_t state)
{
    switch (state) {
    case DISPLAY_UI_IDLE:
        return DISPLAY_VIDEO_IDLE;
    case DISPLAY_UI_LISTENING:
    case DISPLAY_UI_THINKING:
        return DISPLAY_VIDEO_LISTENING_THINKING;
    case DISPLAY_UI_SPEAKING:
        return DISPLAY_VIDEO_SPEAKING;
    default:
        return DISPLAY_VIDEO_NONE;
    }
}

static const char *display_video_path(display_video_asset_t asset)
{
    switch (asset) {
    case DISPLAY_VIDEO_IDLE:
        return DEMO_IDLE_VIDEO_PATH;
    case DISPLAY_VIDEO_LISTENING_THINKING:
        return DEMO_LISTENING_THINKING_VIDEO_PATH;
    case DISPLAY_VIDEO_SPEAKING:
        return DEMO_SPEAKING_VIDEO_PATH;
    default:
        return "";
    }
}

static const char *display_video_name(display_video_asset_t asset)
{
    switch (asset) {
    case DISPLAY_VIDEO_IDLE:
        return "idle";
    case DISPLAY_VIDEO_LISTENING_THINKING:
        return "listening_thinking";
    case DISPLAY_VIDEO_SPEAKING:
        return "speaking";
    default:
        return "none";
    }
}

static int display_video_frame_interval_ms(display_video_asset_t asset)
{
    return asset == DISPLAY_VIDEO_IDLE ? DEMO_IDLE_VIDEO_FRAME_INTERVAL_MS
                                       : DEMO_STATE_VIDEO_FRAME_INTERVAL_MS;
}

static display_video_asset_t display_desired_video_asset(void)
{
    display_ui_state_t state;
    display_power_state_t power;
    display_idle_page_t idle_page;
    taskENTER_CRITICAL(&s_lock);
    state = s_ui_state;
    power = s_power_state;
    idle_page = s_idle_page;
    taskEXIT_CRITICAL(&s_lock);
    if (power == DISPLAY_POWER_OFF ||
        (state == DISPLAY_UI_IDLE && idle_page == DISPLAY_IDLE_PAGE_DESKTOP)) {
        return DISPLAY_VIDEO_NONE;
    }
    return display_video_asset_for_state(state);
}

static void display_create_ui(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x17112A), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);

    s_state_image = lv_image_create(screen);
    lv_obj_remove_flag(s_state_image, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_align(s_state_image, LV_ALIGN_CENTER, 0, 0);
    lv_obj_add_flag(s_state_image, LV_OBJ_FLAG_HIDDEN);

    s_orb = lv_obj_create(screen);
    lv_obj_remove_flag(s_orb, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_size(s_orb, 138, 138);
    lv_obj_align(s_orb, LV_ALIGN_CENTER, 0, -8);
    lv_obj_set_style_radius(s_orb, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(s_orb, 0, 0);
    /*
     * Keep the boot/network/error fallback cheap to draw.  A continuously
     * resized 32 px software shadow starved IDLE0 on a cold boot before the
     * Judy video task could take over, which then tripped the task watchdog.
     */

    s_title = lv_label_create(screen);
    lv_obj_set_style_text_color(s_title, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_text_letter_space(s_title, 2, 0);
    lv_obj_align(s_title, LV_ALIGN_CENTER, 0, -10);

    s_subtitle = lv_label_create(screen);
    lv_obj_set_style_text_color(s_subtitle, lv_color_hex(0xD8CFF2), 0);
    lv_obj_set_style_text_letter_space(s_subtitle, 1, 0);
    lv_obj_align(s_subtitle, LV_ALIGN_CENTER, 0, 86);

    s_direction_marker = lv_obj_create(screen);
    lv_obj_remove_flag(s_direction_marker, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_size(s_direction_marker, 18, 18);
    lv_obj_set_style_radius(s_direction_marker, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(s_direction_marker, 3, 0);
    lv_obj_set_style_border_color(s_direction_marker, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_bg_color(s_direction_marker, lv_color_hex(0xFF80B5), 0);
    lv_obj_set_style_shadow_color(s_direction_marker, lv_color_hex(0xFF80B5), 0);
    lv_obj_set_style_shadow_width(s_direction_marker, 16, 0);
    lv_obj_add_flag(s_direction_marker, LV_OBJ_FLAG_HIDDEN);

    s_desktop_root = lv_obj_create(screen);
    lv_obj_remove_flag(s_desktop_root, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_size(s_desktop_root, BSP_LCD_H_RES, BSP_LCD_V_RES);
    lv_obj_align(s_desktop_root, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_radius(s_desktop_root, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(s_desktop_root, 0, 0);
    lv_obj_set_style_pad_all(s_desktop_root, 0, 0);
    lv_obj_set_style_bg_color(s_desktop_root, lv_color_hex(0xFFF2F8), 0);
    lv_obj_set_style_bg_opa(s_desktop_root, LV_OPA_COVER, 0);

    s_desktop_title = lv_label_create(s_desktop_root);
    lv_label_set_text(s_desktop_title, "JUDY MUSIC");
    lv_obj_set_style_text_color(s_desktop_title, lv_color_hex(0x5A315D), 0);
    lv_obj_set_style_text_letter_space(s_desktop_title, 2, 0);
    lv_obj_align(s_desktop_title, LV_ALIGN_CENTER, 0, -116);

    s_desktop_voice_card = lv_obj_create(s_desktop_root);
    lv_obj_remove_flag(s_desktop_voice_card, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_size(s_desktop_voice_card, DISPLAY_MUSIC_CARD_WIDTH, DISPLAY_MUSIC_CARD_HEIGHT);
    lv_obj_align(s_desktop_voice_card, LV_ALIGN_CENTER, 0, DISPLAY_MUSIC_CARD_CENTER_Y);
    lv_obj_set_style_radius(s_desktop_voice_card, 30, 0);
    lv_obj_set_style_border_width(s_desktop_voice_card, 2, 0);
    lv_obj_set_style_border_color(s_desktop_voice_card, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_bg_color(s_desktop_voice_card, lv_color_hex(0xF7B8D4), 0);
    lv_obj_set_style_bg_opa(s_desktop_voice_card, LV_OPA_COVER, 0);

    s_desktop_voice_title = lv_label_create(s_desktop_voice_card);
    lv_label_set_text(s_desktop_voice_title, "TRY EVERYTHING");
    lv_obj_set_style_text_color(s_desktop_voice_title, lv_color_hex(0x5A315D), 0);
    lv_obj_set_style_text_letter_space(s_desktop_voice_title, 2, 0);
    lv_obj_align(s_desktop_voice_title, LV_ALIGN_CENTER, 0, -38);

    s_desktop_voice_hint = lv_label_create(s_desktop_voice_card);
    lv_label_set_text(s_desktop_voice_hint, "ZOOTOPIA  |  SHAKIRA");
    lv_obj_set_style_text_color(s_desktop_voice_hint, lv_color_hex(0x7B517D), 0);
    lv_obj_align(s_desktop_voice_hint, LV_ALIGN_CENTER, 0, -4);

    s_desktop_music_hint = lv_label_create(s_desktop_root);
    lv_label_set_text(s_desktop_music_hint, "TAP TO PLAY");
    lv_obj_set_style_text_color(s_desktop_music_hint, lv_color_hex(0x5A315D), 0);
    lv_obj_align(s_desktop_music_hint, LV_ALIGN_CENTER, 0, 39);

    s_desktop_swipe_hint = lv_label_create(s_desktop_root);
    lv_label_set_text(s_desktop_swipe_hint, "<  SWIPE RIGHT");
    lv_obj_set_style_text_color(s_desktop_swipe_hint, lv_color_hex(0xB07A9D), 0);
    lv_obj_align(s_desktop_swipe_hint, LV_ALIGN_CENTER, 0, 126);
    lv_obj_add_flag(s_desktop_root, LV_OBJ_FLAG_HIDDEN);
}

static void display_set_standard_ui_visible(bool visible)
{
    lv_obj_add_flag(s_desktop_root, LV_OBJ_FLAG_HIDDEN);
    if (visible) {
        lv_obj_remove_flag(s_orb, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_title, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_subtitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_state_image, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_orb, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_title, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_subtitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_state_image, LV_OBJ_FLAG_HIDDEN);
    }
}

static void display_set_desktop_visible(bool visible)
{
    if (!visible) {
        lv_obj_add_flag(s_desktop_root, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_add_flag(s_state_image, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_orb, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_title, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_subtitle, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_direction_marker, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_desktop_root, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_desktop_root);
}

static void display_render_state(display_ui_state_t state,
                                 display_video_asset_t published_asset,
                                 display_idle_page_t idle_page,
                                 bool music_playing)
{
    const bool show_desktop = state == DISPLAY_UI_IDLE &&
                              idle_page == DISPLAY_IDLE_PAGE_DESKTOP;
    display_set_desktop_visible(show_desktop);
    if (show_desktop) {
        lv_label_set_text(s_desktop_music_hint,
                          music_playing ? "TAP TO STOP" : "TAP TO PLAY");
        return;
    }

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

    const display_video_asset_t desired_asset = display_video_asset_for_state(state);
    const bool show_video = desired_asset != DISPLAY_VIDEO_NONE && desired_asset == published_asset;
    display_set_standard_ui_visible(!show_video);
    if (show_video) {
        return;
    }

    lv_label_set_text(s_title, title);
    lv_label_set_text(s_subtitle, subtitle);
    lv_obj_set_style_bg_color(s_orb, lv_color_hex(color), 0);
    lv_obj_align(s_title, LV_ALIGN_CENTER, 0, -10);
    lv_obj_align(s_subtitle, LV_ALIGN_CENTER, 0, 86);
}

static void display_render_sound_direction(display_ui_state_t state, bool valid, int degrees)
{
    if (s_direction_marker == NULL || !valid || state == DISPLAY_UI_IDLE ||
        state == DISPLAY_UI_BOOT || state == DISPLAY_UI_NETWORK_REQUIRED ||
        state == DISPLAY_UI_ERROR) {
        if (s_direction_marker != NULL) {
            lv_obj_add_flag(s_direction_marker, LV_OBJ_FLAG_HIDDEN);
        }
        return;
    }
    if (degrees < 0) {
        degrees = 0;
    } else if (degrees > 180) {
        degrees = 180;
    }
    const int x = ((degrees - 90) * 128) / 90;
    lv_obj_align(s_direction_marker, LV_ALIGN_CENTER, x, 136);
    lv_obj_remove_flag(s_direction_marker, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_direction_marker);
}

static void display_close_video_set(idle_video_t **videos,
                                    idle_video_decoder_t *decoder,
                                    uint8_t **buffers)
{
    idle_video_decoder_close(decoder);
    for (size_t index = 0; index < DISPLAY_VIDEO_COUNT; ++index) {
        idle_video_close(videos[index]);
    }
    free(buffers[0]);
    free(buffers[1]);
}

static esp_err_t display_prepare_state_videos(void)
{
    idle_video_t *videos[DISPLAY_VIDEO_COUNT] = {0};
    idle_video_decoder_t *decoder = NULL;
    uint8_t *buffers[2] = {0};
    size_t max_jpeg_bytes = 0;
    esp_err_t result = ESP_OK;

    for (display_video_asset_t asset = DISPLAY_VIDEO_IDLE; asset < DISPLAY_VIDEO_COUNT; ++asset) {
        result = idle_video_open(display_video_path(asset),
                                 DEMO_IDLE_VIDEO_MAX_BYTES,
                                 DEMO_IDLE_VIDEO_MAX_FRAMES,
                                 &videos[asset]);
        if (result != ESP_OK) {
            goto failed;
        }
        if (idle_video_width(videos[asset]) != DEMO_IDLE_VIDEO_WIDTH ||
            idle_video_height(videos[asset]) != DEMO_IDLE_VIDEO_HEIGHT ||
            idle_video_frame_count(videos[asset]) == 0) {
            result = ESP_ERR_INVALID_SIZE;
            goto failed;
        }
        const size_t asset_max_frame = idle_video_max_frame_bytes(videos[asset]);
        if (asset_max_frame > max_jpeg_bytes) {
            max_jpeg_bytes = asset_max_frame;
        }
        ESP_LOGI(TAG,
                 "state_video_indexed asset=%s path=%s frames=%u max_jpeg_bytes=%u",
                 display_video_name(asset),
                 display_video_path(asset),
                 (unsigned)idle_video_frame_count(videos[asset]),
                 (unsigned)asset_max_frame);
    }

    result = idle_video_decoder_create(max_jpeg_bytes, &decoder);
    if (result != ESP_OK) {
        goto failed;
    }

    const size_t frame_bytes = (size_t)DEMO_IDLE_VIDEO_WIDTH * DEMO_IDLE_VIDEO_HEIGHT * sizeof(uint16_t);
    for (size_t index = 0; index < 2; ++index) {
        buffers[index] = heap_caps_malloc(frame_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (buffers[index] == NULL) {
            result = ESP_ERR_NO_MEM;
            goto failed;
        }
    }

    display_video_asset_t initial_asset = display_desired_video_asset();
    if (initial_asset == DISPLAY_VIDEO_NONE) {
        initial_asset = DISPLAY_VIDEO_IDLE;
    }
    result = idle_video_decode_frame(videos[initial_asset], decoder, 0, buffers[0], frame_bytes);
    if (result != ESP_OK) {
        goto failed;
    }

    for (size_t index = 0; index < DISPLAY_VIDEO_COUNT; ++index) {
        s_state_videos[index] = videos[index];
    }
    s_video_decoder = decoder;
    s_video_frame_buffers[0] = buffers[0];
    s_video_frame_buffers[1] = buffers[1];
    s_video_displayed_buffer = 0;
    s_state_image_dsc = (lv_image_dsc_t) {
        .header = {
            .magic = LV_IMAGE_HEADER_MAGIC,
            .cf = LV_COLOR_FORMAT_RGB565,
            .flags = LV_IMAGE_FLAGS_MODIFIABLE,
            .w = DEMO_IDLE_VIDEO_WIDTH,
            .h = DEMO_IDLE_VIDEO_HEIGHT,
            .stride = DEMO_IDLE_VIDEO_WIDTH * sizeof(uint16_t),
        },
        .data_size = frame_bytes,
        .data = s_video_frame_buffers[0],
    };

    if (!bsp_display_lock(500)) {
        for (size_t index = 0; index < DISPLAY_VIDEO_COUNT; ++index) {
            s_state_videos[index] = NULL;
        }
        s_video_decoder = NULL;
        s_video_frame_buffers[0] = NULL;
        s_video_frame_buffers[1] = NULL;
        display_close_video_set(videos, decoder, buffers);
        return ESP_ERR_TIMEOUT;
    }
    lv_image_set_src(s_state_image, &s_state_image_dsc);
    lv_obj_align(s_state_image, LV_ALIGN_CENTER, 0, 0);
    bsp_display_unlock();

    const display_video_asset_t current_desired = display_desired_video_asset();
    taskENTER_CRITICAL(&s_lock);
    s_published_video_asset = current_desired == initial_asset ? initial_asset : DISPLAY_VIDEO_NONE;
    taskEXIT_CRITICAL(&s_lock);
    ESP_LOGI(TAG,
             "state_video_ready assets=%d size=%ux%u shared_frame_bytes=%u shared_jpeg_bytes=%u",
             DISPLAY_VIDEO_COUNT,
             DEMO_IDLE_VIDEO_WIDTH,
             DEMO_IDLE_VIDEO_HEIGHT,
             (unsigned)(frame_bytes * 2),
             (unsigned)max_jpeg_bytes);
    return ESP_OK;

failed:
    display_close_video_set(videos, decoder, buffers);
    return result;
}

static void display_state_video_task(void *arg)
{
    (void)arg;
    while (display_desired_video_asset() == DISPLAY_VIDEO_NONE) {
        vTaskDelay(pdMS_TO_TICKS(100));
    }

    esp_err_t result;
    while ((result = display_prepare_state_videos()) != ESP_OK) {
        ESP_LOGW(TAG, "state_video_prepare_failed err=%s", esp_err_to_name(result));
        vTaskDelay(pdMS_TO_TICKS(1000));
    }

    const size_t frame_bytes = (size_t)DEMO_IDLE_VIDEO_WIDTH * DEMO_IDLE_VIDEO_HEIGHT * sizeof(uint16_t);
    display_video_asset_t active_asset = DISPLAY_VIDEO_NONE;
    size_t frame_index = 0;
    while (true) {
        const display_video_asset_t desired_asset = display_desired_video_asset();
        if (desired_asset == DISPLAY_VIDEO_NONE) {
            active_asset = DISPLAY_VIDEO_NONE;
            frame_index = 0;
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        if (desired_asset != active_asset) {
            active_asset = desired_asset;
            frame_index = 0;
        }

        const int64_t frame_started_us = esp_timer_get_time();
        const int decode_buffer = s_video_displayed_buffer == 0 ? 1 : 0;
        result = idle_video_decode_frame(s_state_videos[active_asset],
                                         s_video_decoder,
                                         frame_index,
                                         s_video_frame_buffers[decode_buffer],
                                         frame_bytes);
        if (result != ESP_OK) {
            ESP_LOGW(TAG,
                     "state_video_decode_failed asset=%s frame=%u err=%s",
                     display_video_name(active_asset),
                     (unsigned)frame_index,
                     esp_err_to_name(result));
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        if (display_desired_video_asset() == active_asset && bsp_display_lock(100)) {
            const bool publish = display_desired_video_asset() == active_asset;
            if (publish) {
                s_state_image_dsc.data = s_video_frame_buffers[decode_buffer];
                lv_image_set_src(s_state_image, &s_state_image_dsc);
                lv_obj_invalidate(s_state_image);
                s_video_displayed_buffer = decode_buffer;

                bool switched;
                taskENTER_CRITICAL(&s_lock);
                switched = s_published_video_asset != active_asset;
                s_published_video_asset = active_asset;
                taskEXIT_CRITICAL(&s_lock);
                if (switched) {
                    ESP_LOGI(TAG,
                             "state_video_switch asset=%s frames=%u",
                             display_video_name(active_asset),
                             (unsigned)idle_video_frame_count(s_state_videos[active_asset]));
                }
            }
            bsp_display_unlock();
        }

        const size_t frame_count = idle_video_frame_count(s_state_videos[active_asset]);
        frame_index = (frame_index + 1) % frame_count;
        const int elapsed_ms = (int)((esp_timer_get_time() - frame_started_us) / 1000);
        const int remaining_ms = display_video_frame_interval_ms(active_asset) - elapsed_ms;
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
    display_touch_callback_t callback;
    void *callback_ctx;

    lv_point_t point = {0};
    if (s_touch_indev != NULL) {
        lv_indev_get_point(s_touch_indev, &point);
    }
    taskENTER_CRITICAL(&s_lock);
    s_last_activity_us = esp_timer_get_time();
    s_idle_swipe_tracking = s_touch_indev != NULL &&
                            s_power_state == DISPLAY_POWER_ACTIVE &&
                            s_ui_state == DISPLAY_UI_IDLE;
    if (s_idle_swipe_tracking) {
        s_idle_swipe_start = point;
        s_idle_swipe_last = point;
    }
    if (s_power_state != DISPLAY_POWER_ACTIVE) {
        s_power_state = DISPLAY_POWER_ACTIVE;
        should_wake = true;
    }
    callback = s_touch_callback;
    callback_ctx = s_touch_callback_ctx;
    taskEXIT_CRITICAL(&s_lock);

    if (should_wake) {
        ESP_LOGI(TAG, "display_wake source=touch");
        (void)bsp_display_brightness_set(DEMO_DISPLAY_ACTIVE_BRIGHTNESS);
    }
    if (callback != NULL) {
        callback(callback_ctx);
    }
}

static void display_touch_pressing_event(lv_event_t *event)
{
    (void)event;
    if (!s_idle_swipe_tracking || s_touch_indev == NULL) {
        return;
    }
    lv_indev_get_point(s_touch_indev, &s_idle_swipe_last);
}

static void display_touch_release_event(lv_event_t *event)
{
    (void)event;
    if (s_idle_swipe_tracking && s_touch_indev != NULL) {
        lv_indev_get_point(s_touch_indev, &s_idle_swipe_last);
    }

    const int distance_x = (int)s_idle_swipe_last.x - (int)s_idle_swipe_start.x;
    const int distance_y = (int)s_idle_swipe_last.y - (int)s_idle_swipe_start.y;
    display_idle_page_t next_page;
    bool changed = false;
    bool tracked = false;
    bool music_toggle = false;
    display_music_toggle_callback_t music_callback = NULL;
    void *music_callback_ctx = NULL;

    taskENTER_CRITICAL(&s_lock);
    next_page = s_idle_page;
    tracked = s_idle_swipe_tracking;
    if (tracked && s_ui_state == DISPLAY_UI_IDLE &&
        abs(distance_x) >= DISPLAY_IDLE_SWIPE_MIN_DISTANCE_PX &&
        abs(distance_x) > abs(distance_y)) {
        if (s_idle_page == DISPLAY_IDLE_PAGE_ASSISTANT && distance_x < 0) {
            next_page = DISPLAY_IDLE_PAGE_DESKTOP;
            changed = true;
        } else if (s_idle_page == DISPLAY_IDLE_PAGE_DESKTOP && distance_x > 0) {
            next_page = DISPLAY_IDLE_PAGE_ASSISTANT;
            changed = true;
        }
    }
    if (changed) {
        s_idle_page = next_page;
        s_idle_page_revision++;
        s_published_video_asset = DISPLAY_VIDEO_NONE;
        s_last_activity_us = esp_timer_get_time();
    } else if (tracked && s_ui_state == DISPLAY_UI_IDLE &&
               s_idle_page == DISPLAY_IDLE_PAGE_DESKTOP &&
               abs(distance_x) <= DISPLAY_IDLE_TAP_MAX_MOVEMENT_PX &&
               abs(distance_y) <= DISPLAY_IDLE_TAP_MAX_MOVEMENT_PX) {
        const int card_left = (BSP_LCD_H_RES - DISPLAY_MUSIC_CARD_WIDTH) / 2;
        const int card_top = (BSP_LCD_V_RES - DISPLAY_MUSIC_CARD_HEIGHT) / 2 +
                             DISPLAY_MUSIC_CARD_CENTER_Y;
        music_toggle = s_idle_swipe_last.x >= card_left &&
                       s_idle_swipe_last.x < card_left + DISPLAY_MUSIC_CARD_WIDTH &&
                       s_idle_swipe_last.y >= card_top &&
                       s_idle_swipe_last.y < card_top + DISPLAY_MUSIC_CARD_HEIGHT;
        if (music_toggle) {
            music_callback = s_music_toggle_callback;
            music_callback_ctx = s_music_toggle_callback_ctx;
            s_last_activity_us = esp_timer_get_time();
        }
    }
    s_idle_swipe_tracking = false;
    taskEXIT_CRITICAL(&s_lock);

    if (tracked) {
        ESP_LOGI(TAG,
                 "idle_swipe dx=%d dy=%d changed=%d page=%s",
                 distance_x,
                 distance_y,
                 changed ? 1 : 0,
                 next_page == DISPLAY_IDLE_PAGE_DESKTOP ? "desktop" : "assistant");
    }
    if (music_toggle && music_callback != NULL) {
        ESP_LOGI(TAG, "desktop_music_toggle source=touch");
        music_callback(music_callback_ctx);
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
    ESP_LOGI(TAG,
             "display_power=%s brightness=%d",
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
        display_video_asset_t published_asset;
        bool direction_valid;
        int direction_degrees;
        uint32_t direction_revision;
        display_idle_page_t idle_page;
        uint32_t idle_page_revision;
        bool music_playing;
        uint32_t music_revision;
        int64_t last_activity_us;
        taskENTER_CRITICAL(&s_lock);
        ui_state = s_ui_state;
        current_power = s_power_state;
        last_activity_us = s_last_activity_us;
        published_asset = s_published_video_asset;
        direction_valid = s_direction_valid;
        direction_degrees = s_direction_degrees;
        direction_revision = s_direction_revision;
        idle_page = s_idle_page;
        idle_page_revision = s_idle_page_revision;
        music_playing = s_music_playing;
        music_revision = s_music_revision;
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

        if ((ui_state != s_rendered_state || published_asset != s_rendered_video_asset ||
             direction_revision != s_rendered_direction_revision ||
             idle_page_revision != s_rendered_idle_page_revision ||
             music_revision != s_rendered_music_revision) &&
            bsp_display_lock(100)) {
            display_render_state(ui_state, published_asset, idle_page, music_playing);
            display_render_sound_direction(ui_state, direction_valid, direction_degrees);
            s_rendered_state = ui_state;
            s_rendered_video_asset = published_asset;
            s_rendered_direction_revision = direction_revision;
            s_rendered_idle_page_revision = idle_page_revision;
            s_rendered_music_revision = music_revision;
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
        s_touch_indev = touch;
        lv_indev_add_event_cb(touch, display_touch_event, LV_EVENT_PRESSED, NULL);
        lv_indev_add_event_cb(touch, display_touch_pressing_event, LV_EVENT_PRESSING, NULL);
        lv_indev_add_event_cb(touch, display_touch_release_event, LV_EVENT_RELEASED, NULL);
    }
    bsp_display_unlock();

    s_last_activity_us = esp_timer_get_time();
    s_power_state = DISPLAY_POWER_ACTIVE;
    s_initialized = true;
    (void)bsp_display_brightness_set(DEMO_DISPLAY_ACTIVE_BRIGHTNESS);
    BaseType_t created = pdFAIL;
#if CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM
    created = xTaskCreateWithCaps(display_task,
                                  "disney_display",
                                  DEMO_DISPLAY_TASK_STACK_SIZE,
                                  NULL,
                                  tskIDLE_PRIORITY + 1,
                                  &s_display_task,
                                  MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
#else
    created = xTaskCreate(display_task,
                          "disney_display",
                          DEMO_DISPLAY_TASK_STACK_SIZE,
                          NULL,
                          tskIDLE_PRIORITY + 1,
                          &s_display_task);
#endif
    if (created != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
#if DEMO_IDLE_VIDEO_ENABLED
#if CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM
    BaseType_t video_created = xTaskCreateWithCaps(display_state_video_task,
                                                   "judy_state_video",
                                                   DEMO_IDLE_VIDEO_TASK_STACK_SIZE,
                                                   NULL,
                                                   tskIDLE_PRIORITY + 1,
                                                   &s_state_video_task,
                                                   MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
#else
    BaseType_t video_created = xTaskCreate(display_state_video_task,
                                           "judy_state_video",
                                           DEMO_IDLE_VIDEO_TASK_STACK_SIZE,
                                           NULL,
                                           tskIDLE_PRIORITY + 1,
                                           &s_state_video_task);
#endif
    if (video_created != pdPASS) {
        ESP_LOGW(TAG, "state_video_task_start_failed; text fallback remains active");
    }
#endif
    return ESP_OK;
}

void display_state_set_touch_callback(display_touch_callback_t callback, void *user_ctx)
{
    taskENTER_CRITICAL(&s_lock);
    s_touch_callback = callback;
    s_touch_callback_ctx = user_ctx;
    taskEXIT_CRITICAL(&s_lock);
}

void display_state_set_music_toggle_callback(display_music_toggle_callback_t callback,
                                             void *user_ctx)
{
    taskENTER_CRITICAL(&s_lock);
    s_music_toggle_callback = callback;
    s_music_toggle_callback_ctx = user_ctx;
    taskEXIT_CRITICAL(&s_lock);
}

void display_state_set_music_playing(bool playing)
{
    taskENTER_CRITICAL(&s_lock);
    if (s_music_playing != playing) {
        s_music_playing = playing;
        s_music_revision++;
    }
    taskEXIT_CRITICAL(&s_lock);
}

void display_state_set(display_ui_state_t state)
{
    if (!s_initialized) {
        return;
    }
    taskENTER_CRITICAL(&s_lock);
    if (display_video_asset_for_state(s_ui_state) != display_video_asset_for_state(state)) {
        s_published_video_asset = DISPLAY_VIDEO_NONE;
    }
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

void display_state_set_sound_direction(int degrees, bool valid)
{
    if (!s_initialized) {
        return;
    }
    if (degrees < 0) {
        degrees = 0;
    } else if (degrees > 180) {
        degrees = 180;
    }
    taskENTER_CRITICAL(&s_lock);
    s_direction_valid = valid;
    s_direction_degrees = degrees;
    s_direction_revision++;
    taskEXIT_CRITICAL(&s_lock);
    ESP_LOGI(TAG, "sound_direction valid=%d degrees=%d", valid ? 1 : 0, degrees);
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
