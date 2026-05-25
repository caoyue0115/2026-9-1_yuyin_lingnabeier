#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t app_network_start(void);
bool app_network_is_connected(void);
esp_err_t app_network_enter_config_mode(void);
const char *app_network_get_ssid(void);

#ifdef __cplusplus
}
#endif
