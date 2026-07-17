#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    PROMPT_BOOT_BELL = 10,
    PROMPT_NETWORK_CONNECTED = 20,
    PROMPT_CONVERSATION_DONE = 30,
    PROMPT_FOLLOWUP_CUE = 35,
    PROMPT_SPEAK = 40,
    PROMPT_REPROMPT = 45,
    PROMPT_NETWORK_REQUIRED = 50,
    PROMPT_TECHNICAL_ERROR = 60,
} prompt_id_t;

esp_err_t prompt_arbiter_init(void);
esp_err_t prompt_arbiter_submit(prompt_id_t id, const char *dedupe_key);
esp_err_t prompt_arbiter_wait_idle(int timeout_ms);
esp_err_t prompt_arbiter_wait_key(const char *dedupe_key, int timeout_ms);
void prompt_arbiter_set_conversation_active(bool active);
void prompt_arbiter_set_network_connected(bool connected);

#ifdef __cplusplus
}
#endif
