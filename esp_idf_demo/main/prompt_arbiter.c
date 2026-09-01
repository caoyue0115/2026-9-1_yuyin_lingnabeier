#include "prompt_arbiter.h"

#include "audio_out.h"
#include "config.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

extern const uint8_t prompt_intro_start[] asm("_binary_intro_1_pcm_start");
extern const uint8_t prompt_intro_end[] asm("_binary_intro_1_pcm_end");
extern const uint8_t prompt_followup_bell_start[] asm("_binary_followup_bell_1_pcm_start");
extern const uint8_t prompt_followup_bell_end[] asm("_binary_followup_bell_1_pcm_end");
extern const uint8_t prompt_speak_start[] asm("_binary_speak_1_pcm_start");
extern const uint8_t prompt_speak_end[] asm("_binary_speak_1_pcm_end");
extern const uint8_t prompt_followup_start[] asm("_binary_followup_1_pcm_start");
extern const uint8_t prompt_followup_end[] asm("_binary_followup_1_pcm_end");

static const char *TAG = "prompt_arbiter";

#define PROMPT_ARBITER_CAPACITY 8
#define PROMPT_DEDUPE_KEY_BYTES 64

typedef struct {
    prompt_id_t id;
    char dedupe_key[PROMPT_DEDUPE_KEY_BYTES];
    bool used;
} prompt_entry_t;

static prompt_entry_t s_entries[PROMPT_ARBITER_CAPACITY];
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t s_owner_task;
static bool s_conversation_active;
static bool s_network_connected;
static bool s_playing;
static char s_playing_key[PROMPT_DEDUPE_KEY_BYTES];
static bool s_last_result_valid;
static char s_last_result_key[PROMPT_DEDUPE_KEY_BYTES];
static esp_err_t s_last_result;

static bool prompt_arbiter_is_network_prompt(prompt_id_t id)
{
    return id == PROMPT_NETWORK_REQUIRED || id == PROMPT_NETWORK_CONNECTED;
}

static bool prompt_arbiter_network_prompt_is_relevant(prompt_id_t id)
{
    if (id == PROMPT_NETWORK_REQUIRED) {
        return !s_network_connected;
    }
    if (id == PROMPT_NETWORK_CONNECTED) {
        return s_network_connected;
    }
    return true;
}

static esp_err_t prompt_arbiter_play(prompt_id_t id)
{
    const uint8_t *start = NULL;
    const uint8_t *end = NULL;
    switch (id) {
    case PROMPT_BOOT_BELL:
        start = prompt_intro_start;
        end = prompt_intro_end;
        break;
    case PROMPT_NETWORK_CONNECTED:
        start = prompt_intro_start;
        end = prompt_intro_end;
        break;
    case PROMPT_NETWORK_REQUIRED:
        start = prompt_followup_bell_start;
        end = prompt_followup_bell_end;
        break;
    case PROMPT_CONVERSATION_DONE:
        start = prompt_followup_bell_start;
        end = prompt_followup_bell_end;
        break;
    case PROMPT_FOLLOWUP_CUE:
        start = prompt_followup_start;
        end = prompt_followup_end;
        break;
    case PROMPT_SPEAK:
    case PROMPT_REPROMPT:
        start = prompt_speak_start;
        end = prompt_speak_end;
        break;
    case PROMPT_TECHNICAL_ERROR:
        start = prompt_followup_bell_start;
        end = prompt_followup_bell_end;
        break;
    default:
        return ESP_ERR_NOT_SUPPORTED;
    }

    const size_t bytes = (size_t)(end - start);
    if (bytes == 0 || (bytes & 1U) != 0U) {
        return ESP_ERR_INVALID_SIZE;
    }
    return audio_out_play_pcm_buffer(start,
                                     bytes,
                                     DEMO_AUDIO_SAMPLE_RATE,
                                     DEMO_AUDIO_CHANNELS,
                                     DEMO_AUDIO_BITS_PER_SAMPLE,
                                     64 * 1024);
}

static bool prompt_arbiter_take_next(prompt_entry_t *out)
{
    int selected = -1;
    taskENTER_CRITICAL(&s_lock);
    for (int index = 0; index < PROMPT_ARBITER_CAPACITY; ++index) {
        if (!s_entries[index].used) {
            continue;
        }
        if (!prompt_arbiter_network_prompt_is_relevant(s_entries[index].id)) {
            s_entries[index].used = false;
            continue;
        }
        if (s_conversation_active && prompt_arbiter_is_network_prompt(s_entries[index].id)) {
            continue;
        }
        if (selected < 0 || s_entries[index].id > s_entries[selected].id) {
            selected = index;
        }
    }
    if (selected >= 0) {
        *out = s_entries[selected];
        s_entries[selected].used = false;
        s_playing = true;
        snprintf(s_playing_key, sizeof(s_playing_key), "%s", out->dedupe_key);
    }
    taskEXIT_CRITICAL(&s_lock);
    return selected >= 0;
}

static void prompt_arbiter_owner_task(void *arg)
{
    (void)arg;
    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        prompt_entry_t entry = {0};
        while (prompt_arbiter_take_next(&entry)) {
            taskENTER_CRITICAL(&s_lock);
            const bool relevant = prompt_arbiter_network_prompt_is_relevant(entry.id);
            const bool deferred = s_conversation_active &&
                                  prompt_arbiter_is_network_prompt(entry.id);
            if (deferred) {
                for (int index = 0; index < PROMPT_ARBITER_CAPACITY; ++index) {
                    if (!s_entries[index].used) {
                        s_entries[index] = entry;
                        s_entries[index].used = true;
                        break;
                    }
                }
            }
            if (!relevant || deferred) {
                s_playing = false;
                s_playing_key[0] = '\0';
            }
            taskEXIT_CRITICAL(&s_lock);
            if (!relevant) {
                continue;
            }
            if (deferred) {
                break;
            }
            ESP_LOGI(TAG, "prompt_start id=%d key=%s", (int)entry.id, entry.dedupe_key);
            const esp_err_t ret = prompt_arbiter_play(entry.id);
            ESP_LOGI(TAG, "prompt_done id=%d err=%s", (int)entry.id, esp_err_to_name(ret));
            taskENTER_CRITICAL(&s_lock);
            s_last_result = ret;
            s_last_result_valid = true;
            snprintf(s_last_result_key,
                     sizeof(s_last_result_key),
                     "%s",
                     entry.dedupe_key);
            s_playing = false;
            s_playing_key[0] = '\0';
            taskEXIT_CRITICAL(&s_lock);
        }
    }
}

esp_err_t prompt_arbiter_wait_key(const char *dedupe_key, int timeout_ms)
{
    if (dedupe_key == NULL || dedupe_key[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    const int64_t deadline_us = esp_timer_get_time() + (int64_t)timeout_ms * 1000;
    while (true) {
        bool pending = false;
        bool completed = false;
        esp_err_t completed_result = ESP_OK;
        taskENTER_CRITICAL(&s_lock);
        pending = s_playing &&
                  strncmp(s_playing_key, dedupe_key, PROMPT_DEDUPE_KEY_BYTES) == 0;
        for (int index = 0; index < PROMPT_ARBITER_CAPACITY && !pending; ++index) {
            pending = s_entries[index].used &&
                      strncmp(s_entries[index].dedupe_key,
                              dedupe_key,
                              PROMPT_DEDUPE_KEY_BYTES) == 0;
        }
        completed = s_last_result_valid &&
                    strncmp(s_last_result_key,
                            dedupe_key,
                            PROMPT_DEDUPE_KEY_BYTES) == 0;
        if (completed) {
            completed_result = s_last_result;
        }
        taskEXIT_CRITICAL(&s_lock);
        if (!pending) {
            return completed ? completed_result : ESP_OK;
        }
        if (esp_timer_get_time() >= deadline_us) {
            return ESP_ERR_TIMEOUT;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

esp_err_t prompt_arbiter_wait_idle(int timeout_ms)
{
    const int64_t deadline_us = esp_timer_get_time() + (int64_t)timeout_ms * 1000;
    while (true) {
        bool busy = false;
        taskENTER_CRITICAL(&s_lock);
        busy = s_playing;
        for (int index = 0; index < PROMPT_ARBITER_CAPACITY && !busy; ++index) {
            busy = s_entries[index].used;
        }
        taskEXIT_CRITICAL(&s_lock);
        if (!busy) {
            return ESP_OK;
        }
        if (esp_timer_get_time() >= deadline_us) {
            return ESP_ERR_TIMEOUT;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

esp_err_t prompt_arbiter_init(void)
{
    if (s_owner_task != NULL) {
        return ESP_OK;
    }
    const BaseType_t created = xTaskCreate(prompt_arbiter_owner_task,
                                           "prompt_owner",
                                           4096,
                                           NULL,
                                           tskIDLE_PRIORITY + 2,
                                           &s_owner_task);
    return created == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}

esp_err_t prompt_arbiter_submit(prompt_id_t id, const char *dedupe_key)
{
    if (s_owner_task == NULL || dedupe_key == NULL || dedupe_key[0] == '\0') {
        return ESP_ERR_INVALID_STATE;
    }
    int free_index = -1;
    taskENTER_CRITICAL(&s_lock);
    if (s_playing &&
        strncmp(s_playing_key, dedupe_key, PROMPT_DEDUPE_KEY_BYTES) == 0) {
        taskEXIT_CRITICAL(&s_lock);
        return ESP_OK;
    }
    for (int index = 0; index < PROMPT_ARBITER_CAPACITY; ++index) {
        if (s_entries[index].used &&
            strncmp(s_entries[index].dedupe_key, dedupe_key, PROMPT_DEDUPE_KEY_BYTES) == 0) {
            taskEXIT_CRITICAL(&s_lock);
            return ESP_OK;
        }
        if (!s_entries[index].used && free_index < 0) {
            free_index = index;
        }
    }
    if (free_index >= 0) {
        s_entries[free_index].id = id;
        snprintf(s_entries[free_index].dedupe_key,
                 sizeof(s_entries[free_index].dedupe_key),
                 "%s",
                 dedupe_key);
        s_entries[free_index].used = true;
    }
    taskEXIT_CRITICAL(&s_lock);
    if (free_index < 0) {
        return ESP_ERR_NO_MEM;
    }
    xTaskNotifyGive(s_owner_task);
    return ESP_OK;
}

void prompt_arbiter_set_conversation_active(bool active)
{
    taskENTER_CRITICAL(&s_lock);
    s_conversation_active = active;
    taskEXIT_CRITICAL(&s_lock);
    if (!active && s_owner_task != NULL) {
        xTaskNotifyGive(s_owner_task);
    }
}

void prompt_arbiter_set_network_connected(bool connected)
{
    taskENTER_CRITICAL(&s_lock);
    s_network_connected = connected;
    taskEXIT_CRITICAL(&s_lock);
    if (s_owner_task != NULL) {
        xTaskNotifyGive(s_owner_task);
    }
}
