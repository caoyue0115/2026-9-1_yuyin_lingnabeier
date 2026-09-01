#include "playback_session.h"

#include "audio_out.h"
#include "cloud_client.h"
#include "config.h"

#include "freertos/event_groups.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PLAYBACK_SESSION_DONE_BIT BIT0
#define PLAYBACK_REAPER_STACK_BYTES 4096

static const char *TAG = "playback_session";
static StaticTask_t s_playback_reaper_task;
static StackType_t
    s_playback_reaper_stack[PLAYBACK_REAPER_STACK_BYTES / sizeof(StackType_t)];
static StaticQueue_t s_playback_reaper_queue;
static uint8_t s_playback_reaper_queue_storage[sizeof(playback_session_t *)];
static portMUX_TYPE s_playback_reaper_lock = portMUX_INITIALIZER_UNLOCKED;
static QueueHandle_t s_playback_reaper_queue_handle;
static TaskHandle_t s_playback_reaper_task_handle;
static bool s_playback_reaper_initializing;

static void playback_log_internal_heap(const char *stage)
{
    ESP_LOGI(TAG,
             "playback_heap stage=%s free_internal=%u largest_internal=%u",
             stage != NULL ? stage : "unknown",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
}

struct playback_session {
    char url[DEMO_CLOUD_AUDIO_URL_MAX_LEN];
    EventGroupHandle_t events;
    TaskHandle_t task;
    bool task_stack_with_caps;
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
    playback_log_internal_heap("owner_start");
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
    } else {
        ESP_LOGE(TAG, "playback_owner_audio_open_failed result=%s", esp_err_to_name(ret));
    }
    session->result = ret;
    xEventGroupSetBits(session->events, PLAYBACK_SESSION_DONE_BIT);
    __atomic_store_n(&session->completion_published, true, __ATOMIC_RELEASE);
    vTaskSuspend(NULL);
}

static void playback_session_reaper(void *arg)
{
    QueueHandle_t queue = (QueueHandle_t)arg;
    while (true) {
        playback_session_t *session = NULL;
        if (xQueueReceive(queue, &session, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        esp_err_t playback_result = ESP_FAIL;
        while (session != NULL &&
               playback_session_join(&session, portMAX_DELAY, &playback_result) != ESP_OK) {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
}

static esp_err_t playback_session_ensure_reaper(void)
{
    taskENTER_CRITICAL(&s_playback_reaper_lock);
    if (s_playback_reaper_task_handle != NULL) {
        taskEXIT_CRITICAL(&s_playback_reaper_lock);
        return ESP_OK;
    }
    if (s_playback_reaper_initializing) {
        taskEXIT_CRITICAL(&s_playback_reaper_lock);
        return ESP_ERR_INVALID_STATE;
    }
    s_playback_reaper_initializing = true;
    taskEXIT_CRITICAL(&s_playback_reaper_lock);

    QueueHandle_t queue = xQueueCreateStatic(1,
                                             sizeof(playback_session_t *),
                                             s_playback_reaper_queue_storage,
                                             &s_playback_reaper_queue);
    TaskHandle_t task = NULL;
    if (queue != NULL) {
        task = xTaskCreateStatic(playback_session_reaper,
                                 "playback_reaper",
                                 PLAYBACK_REAPER_STACK_BYTES,
                                 queue,
                                 tskIDLE_PRIORITY + 1,
                                 s_playback_reaper_stack,
                                 &s_playback_reaper_task);
    }

    taskENTER_CRITICAL(&s_playback_reaper_lock);
    if (task != NULL) {
        s_playback_reaper_queue_handle = queue;
        s_playback_reaper_task_handle = task;
    }
    s_playback_reaper_initializing = false;
    taskEXIT_CRITICAL(&s_playback_reaper_lock);
    return task != NULL ? ESP_OK : ESP_FAIL;
}

esp_err_t playback_session_start(const char *url, playback_session_t **out)
{
    if (url == NULL || url[0] == '\0' || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out = NULL;
    ESP_LOGI(TAG, "playback_start url_len=%u", (unsigned)strlen(url));
    playback_log_internal_heap("start_before_reaper");
    esp_err_t ret = playback_session_ensure_reaper();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "playback_start reaper_failed result=%s", esp_err_to_name(ret));
        return ret;
    }
    playback_session_t *session = calloc(1, sizeof(*session));
    if (session == NULL) {
        ESP_LOGE(TAG, "playback_start session_alloc_failed");
        return ESP_ERR_NO_MEM;
    }
    const int written = snprintf(session->url, sizeof(session->url), "%s", url);
    if (written < 0 || (size_t)written >= sizeof(session->url)) {
        ESP_LOGE(TAG, "playback_start url_invalid_size written=%d capacity=%u",
                 written, (unsigned)sizeof(session->url));
        free(session);
        return ESP_ERR_INVALID_SIZE;
    }
    session->events = xEventGroupCreate();
    if (session->events == NULL) {
        ESP_LOGE(TAG, "playback_start event_group_alloc_failed");
        free(session);
        return ESP_ERR_NO_MEM;
    }
    session->last_progress_us = esp_timer_get_time();
    BaseType_t task_ret = pdFAIL;
#if CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM
    task_ret = xTaskCreateWithCaps(playback_session_owner,
                                   "playback_owner",
                                   DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE,
                                   session,
                                   DEMO_PIPELINE_TASK_PRIORITY,
                                   &session->task,
                                   MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    session->task_stack_with_caps = task_ret == pdPASS;
#else
    task_ret = xTaskCreate(playback_session_owner,
                           "playback_owner",
                           DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE,
                           session,
                           DEMO_PIPELINE_TASK_PRIORITY,
                           &session->task);
#endif
    if (task_ret != pdPASS) {
        playback_log_internal_heap("owner_task_create_failed");
        ESP_LOGE(TAG, "playback_start owner_task_create_failed stack_bytes=%u",
                 (unsigned)DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE);
        vEventGroupDelete(session->events);
        free(session);
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "playback_start owner_task_created stack_bytes=%u",
             (unsigned)DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE);
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

esp_err_t playback_session_detach(playback_session_t **session)
{
    if (session == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (*session == NULL) {
        return ESP_OK;
    }
    taskENTER_CRITICAL(&s_playback_reaper_lock);
    QueueHandle_t queue = s_playback_reaper_queue_handle;
    const bool ready = s_playback_reaper_task_handle != NULL && queue != NULL;
    taskEXIT_CRITICAL(&s_playback_reaper_lock);
    if (!ready) {
        ESP_LOGE(TAG, "Playback reaper unavailable");
        esp_restart();
        return ESP_ERR_INVALID_STATE;
    }
    playback_session_t *owned = *session;
    if (xQueueSend(queue, &owned, 0) != pdTRUE) {
        ESP_LOGE(TAG, "Playback reaper queue full");
        esp_restart();
        return ESP_ERR_TIMEOUT;
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
        if (owned->task_stack_with_caps) {
            vTaskDeleteWithCaps(task);
        } else {
            vTaskDelete(task);
        }
        owned->task = NULL;
    }
    vEventGroupDelete(owned->events);
    free(owned);
    *session = NULL;
    *playback_result = result;
    return ESP_OK;
}
