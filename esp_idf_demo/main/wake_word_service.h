#pragma once

#include <stdbool.h>

#include "esp_err.h"

#define WAKE_WORD_SERVICE_SPIKE_MODEL_NAME "wn9_xiaomingtongxue_tts2"

typedef struct {
    char word[64];
    char model[64];
} wake_word_detection_t;

esp_err_t wake_word_service_start(void);
void wake_word_service_stop(void);
esp_err_t wake_word_service_set_accepting(bool accepting);
bool wake_word_service_poll(wake_word_detection_t *out_detection);
