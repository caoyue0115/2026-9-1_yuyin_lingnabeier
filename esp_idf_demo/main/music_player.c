#include "music_player.h"

#include "config.h"
#include "cloud_client.h"
#include "playback_session.h"

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/event_groups.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"


#define MUSIC_PLAYER_DONE_BIT BIT0

static const char *TAG = "music_player";
static StaticEventGroup_t s_event_storage;
static EventGroupHandle_t s_events;
static volatile bool s_active;
static volatile bool s_stop_requested;

static void music_player_task(void *arg)
{
    (void)arg;
    playback_session_t *playback = NULL;
    esp_err_t playback_result = ESP_FAIL;
    esp_err_t result = playback_session_start(DEMO_MUSIC_STREAM_URL, &playback);
    if (result == ESP_OK) {
        bool interrupted = false;
        result = playback_session_join_interruptible(
            &playback,
            portMAX_DELAY,
            &playback_result,
            &s_stop_requested,
            &interrupted);
        if (result == ESP_OK) {
            result = playback_result;
        }
        if (interrupted && result == DEMO_CLOUD_ERR_AUDIO_CANCELLED) {
            result = ESP_OK;
        }
    }

    ESP_LOGI(TAG,
             "music_finished result=%s stopped=%d",
             esp_err_to_name(result),
             __atomic_load_n(&s_stop_requested, __ATOMIC_ACQUIRE) ? 1 : 0);
    __atomic_store_n(&s_active, false, __ATOMIC_RELEASE);
    xEventGroupSetBits(s_events, MUSIC_PLAYER_DONE_BIT);
    vTaskDelete(NULL);
}

esp_err_t music_player_init(void)
{
    if (s_events != NULL) {
        return ESP_OK;
    }
    s_events = xEventGroupCreateStatic(&s_event_storage);
    return s_events != NULL ? ESP_OK : ESP_ERR_NO_MEM;
}

esp_err_t music_player_start(void)
{
    esp_err_t ret = music_player_init();
    if (ret != ESP_OK) {
        return ret;
    }
    bool expected = false;
    if (!__atomic_compare_exchange_n(&s_active,
                                     &expected,
                                     true,
                                     false,
                                     __ATOMIC_ACQ_REL,
                                     __ATOMIC_ACQUIRE)) {
        return ESP_ERR_INVALID_STATE;
    }
    __atomic_store_n(&s_stop_requested, false, __ATOMIC_RELEASE);
    xEventGroupClearBits(s_events, MUSIC_PLAYER_DONE_BIT);

    TaskHandle_t task = NULL;
    BaseType_t created = pdFAIL;
#if CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM
    created = xTaskCreateWithCaps(music_player_task,
                                  "judy_music",
                                  DEMO_MUSIC_PLAYER_TASK_STACK_SIZE,
                                  NULL,
                                  DEMO_PIPELINE_TASK_PRIORITY,
                                  &task,
                                  MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
#else
    created = xTaskCreate(music_player_task,
                          "judy_music",
                          DEMO_MUSIC_PLAYER_TASK_STACK_SIZE,
                          NULL,
                          DEMO_PIPELINE_TASK_PRIORITY,
                          &task);
#endif
    if (created != pdPASS) {
        __atomic_store_n(&s_active, false, __ATOMIC_RELEASE);
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "music_started url=%s", DEMO_MUSIC_STREAM_URL);
    return ESP_OK;
}

esp_err_t music_player_stop(TickType_t timeout)
{
    if (!__atomic_load_n(&s_active, __ATOMIC_ACQUIRE)) {
        return ESP_OK;
    }
    __atomic_store_n(&s_stop_requested, true, __ATOMIC_RELEASE);
    const EventBits_t bits = xEventGroupWaitBits(s_events,
                                                 MUSIC_PLAYER_DONE_BIT,
                                                 pdFALSE,
                                                 pdFALSE,
                                                 timeout);
    return (bits & MUSIC_PLAYER_DONE_BIT) != 0 ? ESP_OK : ESP_ERR_TIMEOUT;
}

bool music_player_is_active(void)
{
    return __atomic_load_n(&s_active, __ATOMIC_ACQUIRE);
}
