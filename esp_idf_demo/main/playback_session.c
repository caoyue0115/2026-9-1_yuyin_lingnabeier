#include "playback_session.h"

#include "audio_out.h"
#include "cloud_client.h"
#include "config.h"

#include "freertos/event_groups.h"
#include "freertos/task.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PLAYBACK_SESSION_DONE_BIT BIT0

struct playback_session {
    char url[DEMO_CLOUD_AUDIO_URL_MAX_LEN];
    EventGroupHandle_t events;
    TaskHandle_t task;
    volatile bool cancel_requested;
    int cancel_reason;
    esp_err_t result;
};

static esp_err_t playback_session_pcm_sink(const uint8_t *pcm,
                                           size_t pcm_bytes,
                                           void *user_ctx)
{
    playback_session_t *session = (playback_session_t *)user_ctx;
    if (session == NULL || session->cancel_requested) {
        return DEMO_CLOUD_ERR_AUDIO_CANCELLED;
    }
    size_t written = 0;
    return audio_out_write_pcm_chunk_buffered(pcm, pcm_bytes, &written);
}

static void playback_session_owner(void *arg)
{
    playback_session_t *session = (playback_session_t *)arg;
    esp_err_t ret = audio_out_open_pcm_stream(DEMO_AUDIO_SAMPLE_RATE,
                                              DEMO_AUDIO_CHANNELS,
                                              DEMO_AUDIO_BITS_PER_SAMPLE);
    if (ret == ESP_OK) {
        cloud_realtime_audio_metrics_t metrics = {0};
        ret = cloud_client_stream_realtime_audio_cancellable(
            session->url,
            playback_session_pcm_sink,
            session,
            &metrics,
            &session->cancel_requested);
        const esp_err_t close_ret = audio_out_close_pcm_stream();
        if (ret == ESP_OK) {
            ret = close_ret;
        }
    }
    session->result = ret;
    session->task = NULL;
    xEventGroupSetBits(session->events, PLAYBACK_SESSION_DONE_BIT);
    vTaskDelete(NULL);
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
    session->cancel_requested = true;
    return ESP_OK;
}

esp_err_t playback_session_join(playback_session_t *session, TickType_t timeout)
{
    if (session == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const EventBits_t bits = xEventGroupWaitBits(session->events,
                                                 PLAYBACK_SESSION_DONE_BIT,
                                                 pdFALSE,
                                                 pdFALSE,
                                                 timeout);
    if ((bits & PLAYBACK_SESSION_DONE_BIT) == 0) {
        return ESP_ERR_TIMEOUT;
    }
    const esp_err_t result = session->result;
    vEventGroupDelete(session->events);
    free(session);
    return result;
}
