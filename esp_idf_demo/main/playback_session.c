#include "playback_session.h"

#include "audio_out.h"
#include "cloud_client.h"
#include "config.h"

#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PLAYBACK_SESSION_DONE_BIT BIT0
#define PLAYBACK_REAPER_STACK_WORDS 1024

static const char *TAG = "playback_session";
static StaticTask_t s_playback_reaper_task;
static StackType_t s_playback_reaper_stack[PLAYBACK_REAPER_STACK_WORDS];
static portMUX_TYPE s_playback_reaper_lock = portMUX_INITIALIZER_UNLOCKED;
static bool s_playback_reaper_active;

struct playback_session {
    char url[DEMO_CLOUD_AUDIO_URL_MAX_LEN];
    EventGroupHandle_t events;
    TaskHandle_t task;
    volatile bool cancel_requested;
    bool completion_published;
    int cancel_reason;
    esp_err_t result;
    int64_t last_progress_us;
};

static esp_err_t playback_session_pcm_sink(const uint8_t *pcm,
                                           size_t pcm_bytes,
                                           void *user_ctx)
{
    playback_session_t *session = (playback_session_t *)user_ctx;
    if (session == NULL ||
        __atomic_load_n(&session->cancel_requested, __ATOMIC_ACQUIRE)) {
        return DEMO_CLOUD_ERR_AUDIO_CANCELLED;
    }
    size_t written = 0;
    const esp_err_t ret = audio_out_write_pcm_chunk_buffered(pcm, pcm_bytes, &written);
    if (ret == ESP_OK && written > 0) {
        __atomic_store_n(&session->last_progress_us, esp_timer_get_time(), __ATOMIC_RELEASE);
    }
    return ret;
}

static void playback_session_owner(void *arg)
{
    playback_session_t *session = (playback_session_t *)arg;
    esp_err_t ret = audio_out_open_pcm_stream(DEMO_AUDIO_SAMPLE_RATE,
                                              DEMO_AUDIO_CHANNELS,
                                              DEMO_AUDIO_BITS_PER_SAMPLE);
    if (ret == ESP_OK) {
        cloud_realtime_audio_metrics_t metrics = {0};
        const esp_err_t stream_ret = cloud_client_stream_realtime_audio_cancellable(
            session->url,
            playback_session_pcm_sink,
            session,
            &metrics,
            &session->cancel_requested);
        const esp_err_t close_ret = audio_out_close_pcm_stream();
        ret = stream_ret;
        if (ret == ESP_OK) {
            ret = close_ret;
        }
        ESP_LOGI(TAG,
                 "playback_owner_complete stream_result=%s close_result=%s final_result=%s",
                 esp_err_to_name(stream_ret),
                 esp_err_to_name(close_ret),
                 esp_err_to_name(ret));
    }
    session->result = ret;
    xEventGroupSetBits(session->events, PLAYBACK_SESSION_DONE_BIT);
    __atomic_store_n(&session->completion_published, true, __ATOMIC_RELEASE);
    vTaskSuspend(NULL);
}

esp_err_t playback_session_start(const char *url, playback_session_t **out)
{
    if (url == NULL || url[0] == '\0' || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out = NULL;
    playback_session_t *session = calloc(1, sizeof(*session));
    if (session == NULL) {
        return ESP_ERR_NO_MEM;
    }
    const int written = snprintf(session->url, sizeof(session->url), "%s", url);
    if (written < 0 || (size_t)written >= sizeof(session->url)) {
        free(session);
        return ESP_ERR_INVALID_SIZE;
    }
    session->events = xEventGroupCreate();
    if (session->events == NULL) {
        free(session);
        return ESP_ERR_NO_MEM;
    }
    session->last_progress_us = esp_timer_get_time();
    if (xTaskCreate(playback_session_owner,
                    "playback_owner",
                    DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE,
                    session,
                    DEMO_PIPELINE_TASK_PRIORITY,
                    &session->task) != pdPASS) {
        vEventGroupDelete(session->events);
        free(session);
        return ESP_ERR_NO_MEM;
    }
    *out = session;
    return ESP_OK;
}

esp_err_t playback_session_cancel(playback_session_t *session, int reason)
{
    if (session == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    session->cancel_reason = reason;
    __atomic_store_n(&session->cancel_requested, true, __ATOMIC_RELEASE);
    __atomic_store_n(&session->last_progress_us, esp_timer_get_time(), __ATOMIC_RELEASE);
    return ESP_OK;
}

static void playback_session_reaper(void *arg)
{
    playback_session_t *session = (playback_session_t *)arg;
    esp_err_t playback_result = ESP_FAIL;
    while (session != NULL &&
           playback_session_join(&session, portMAX_DELAY, &playback_result) != ESP_OK) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    taskENTER_CRITICAL(&s_playback_reaper_lock);
    s_playback_reaper_active = false;
    taskEXIT_CRITICAL(&s_playback_reaper_lock);
    vTaskDelete(NULL);
}

esp_err_t playback_session_detach(playback_session_t **session)
{
    if (session == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (*session == NULL) {
        return ESP_OK;
    }
    taskENTER_CRITICAL(&s_playback_reaper_lock);
    if (s_playback_reaper_active) {
        taskEXIT_CRITICAL(&s_playback_reaper_lock);
        return ESP_ERR_INVALID_STATE;
    }
    s_playback_reaper_active = true;
    taskEXIT_CRITICAL(&s_playback_reaper_lock);
    TaskHandle_t reaper = xTaskCreateStatic(playback_session_reaper,
                                           "playback_reaper",
                                           PLAYBACK_REAPER_STACK_WORDS,
                                           *session,
                                           tskIDLE_PRIORITY + 1,
                                           s_playback_reaper_stack,
                                           &s_playback_reaper_task);
    if (reaper == NULL) {
        taskENTER_CRITICAL(&s_playback_reaper_lock);
        s_playback_reaper_active = false;
        taskEXIT_CRITICAL(&s_playback_reaper_lock);
        return ESP_FAIL;
    }
    *session = NULL;
    return ESP_OK;
}

esp_err_t playback_session_join(playback_session_t **session,
                                TickType_t inactivity_timeout,
                                esp_err_t *playback_result)
{
    if (session == NULL || playback_result == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (*session == NULL) {
        return ESP_OK;
    }
    playback_session_t *owned = *session;
    const int64_t inactivity_timeout_us =
        inactivity_timeout == portMAX_DELAY
            ? INT64_MAX
            : (int64_t)inactivity_timeout * portTICK_PERIOD_MS * 1000;
    while (true) {
        const EventBits_t bits = xEventGroupWaitBits(owned->events,
                                                     PLAYBACK_SESSION_DONE_BIT,
                                                     pdFALSE,
                                                     pdFALSE,
                                                     pdMS_TO_TICKS(250));
        if ((bits & PLAYBACK_SESSION_DONE_BIT) != 0) {
            break;
        }
        const int64_t last_progress_us =
            __atomic_load_n(&owned->last_progress_us, __ATOMIC_ACQUIRE);
        if (inactivity_timeout_us != INT64_MAX &&
            esp_timer_get_time() - last_progress_us >= inactivity_timeout_us) {
            (void)playback_session_cancel(owned, ESP_ERR_TIMEOUT);
            return ESP_ERR_TIMEOUT;
        }
    }
    while (!__atomic_load_n(&owned->completion_published, __ATOMIC_ACQUIRE)) {
        taskYIELD();
    }
    const esp_err_t result = owned->result;
    TaskHandle_t task = owned->task;
    if (task != NULL) {
        const int64_t suspend_deadline_us =
            esp_timer_get_time() +
            (int64_t)DEMO_REALTIME_AUDIO_CLOSE_WAIT_TIMEOUT_MS * 1000;
        while (eTaskGetState(task) != eSuspended &&
               esp_timer_get_time() < suspend_deadline_us) {
            taskYIELD();
        }
        if (eTaskGetState(task) != eSuspended) {
            return ESP_ERR_TIMEOUT;
        }
        vTaskDelete(task);
        owned->task = NULL;
    }
    vEventGroupDelete(owned->events);
    free(owned);
    *session = NULL;
    *playback_result = result;
    return ESP_OK;
}
