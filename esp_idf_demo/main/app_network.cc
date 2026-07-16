#include "app_network.h"

#include "config.h"

#include "wifi_manager.h"
#include "wifi_credential_store.h"
#include "wifi_connection_policy.h"
#include "prompt_arbiter.h"

#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include <string>
#include <stdint.h>
#include <stdio.h>

static const char *TAG = "app_network";

#define APP_NETWORK_CONNECTED_BIT   BIT0
#define APP_NETWORK_CONFIG_EXIT_BIT BIT1
#define APP_NETWORK_NO_CANDIDATES_BIT BIT2
#define APP_NETWORK_OUTAGE_CHANGE_BIT BIT3

static EventGroupHandle_t s_network_event_group;
static bool s_network_initialized;
static bool s_build_credentials_seeded;
static portMUX_TYPE s_outage_lock = portMUX_INITIALIZER_UNLOCKED;
static bool s_suppress_runtime_outage;
static bool s_outage_active;
static bool s_outage_prompted;
static uint32_t s_outage_generation;
static int64_t s_outage_started_ms;
static char s_connected_ssid[33];

static void app_network_set_outage_suppressed(bool suppressed)
{
    portENTER_CRITICAL(&s_outage_lock);
    s_suppress_runtime_outage = suppressed;
    portEXIT_CRITICAL(&s_outage_lock);
    if (s_network_event_group != nullptr) {
        xEventGroupSetBits(s_network_event_group, APP_NETWORK_OUTAGE_CHANGE_BIT);
    }
}

static void app_network_runtime_outage_task(void *arg)
{
    (void)arg;
    while (true) {
        xEventGroupWaitBits(s_network_event_group,
                            APP_NETWORK_OUTAGE_CHANGE_BIT,
                            pdTRUE,
                            pdFALSE,
                            portMAX_DELAY);
        while (true) {
            portENTER_CRITICAL(&s_outage_lock);
            const bool active = s_outage_active && !s_suppress_runtime_outage;
            const bool prompted = s_outage_prompted;
            const uint32_t generation = s_outage_generation;
            const int64_t started_ms = s_outage_started_ms;
            portEXIT_CRITICAL(&s_outage_lock);
            if (!active || prompted) {
                break;
            }

            const int64_t deadline_ms = started_ms + DEMO_WIFI_RUNTIME_PROMPT_MS;
            const int64_t now_ms = esp_timer_get_time() / 1000;
            if (now_ms < deadline_ms) {
                const TickType_t wait_ticks = pdMS_TO_TICKS(
                    static_cast<uint32_t>(deadline_ms - now_ms));
                const EventBits_t bits = xEventGroupWaitBits(
                    s_network_event_group,
                    APP_NETWORK_OUTAGE_CHANGE_BIT,
                    pdTRUE,
                    pdFALSE,
                    wait_ticks);
                if ((bits & APP_NETWORK_OUTAGE_CHANGE_BIT) != 0) {
                    continue;
                }
            }

            if (WifiManager::GetInstance().IsConnected()) {
                break;
            }
            bool submit = false;
            portENTER_CRITICAL(&s_outage_lock);
            if (s_outage_active && !s_suppress_runtime_outage &&
                !s_outage_prompted && generation == s_outage_generation) {
                s_outage_prompted = true;
                submit = true;
            }
            portEXIT_CRITICAL(&s_outage_lock);
            if (submit) {
                char dedupe_key[48];
                snprintf(dedupe_key, sizeof(dedupe_key), "need_network:%lu",
                         (unsigned long)generation);
                (void)prompt_arbiter_submit(PROMPT_NETWORK_REQUIRED, dedupe_key);
                ESP_LOGI(TAG,
                         "wifi_runtime_outage_prompt deadline_ms=%lld next_rescan_ms=%lld",
                         (long long)deadline_ms,
                         (long long)wifi_policy_next_rescan_deadline(started_ms, 0));
            }
            break;
        }
    }
}

static void app_network_begin_runtime_outage(void)
{
    portENTER_CRITICAL(&s_outage_lock);
    if (s_suppress_runtime_outage || s_outage_active) {
        portEXIT_CRITICAL(&s_outage_lock);
        return;
    }
    s_outage_active = true;
    s_outage_prompted = false;
    s_outage_started_ms = esp_timer_get_time() / 1000;
    ++s_outage_generation;
    portEXIT_CRITICAL(&s_outage_lock);
    if (s_network_event_group != nullptr) {
        xEventGroupSetBits(s_network_event_group, APP_NETWORK_OUTAGE_CHANGE_BIT);
    }
}

static void app_network_store_ssid(const std::string &ssid)
{
    snprintf(s_connected_ssid, sizeof(s_connected_ssid), "%s", ssid.c_str());
}

static void app_network_handle_wifi_event(WifiEvent event, const std::string &data)
{
    auto &wifi = WifiManager::GetInstance();

    switch (event) {
    case WifiEvent::Scanning:
        ESP_LOGI(TAG, "wifi_scanning");
        break;
    case WifiEvent::Connecting:
        ESP_LOGI(TAG, "wifi_connecting ssid=%s", data.c_str());
        break;
    case WifiEvent::Connected:
        app_network_store_ssid(data);
        (void)WifiCredentialStore::GetInstance().MarkSuccessful(data);
        prompt_arbiter_set_network_connected(true);
        portENTER_CRITICAL(&s_outage_lock);
        if (s_outage_active) {
            const bool announce_recovery = s_outage_prompted;
            const uint32_t generation = s_outage_generation;
            s_outage_active = false;
            s_outage_prompted = false;
            ++s_outage_generation;
            portEXIT_CRITICAL(&s_outage_lock);
            if (announce_recovery) {
                char dedupe_key[48];
                snprintf(dedupe_key, sizeof(dedupe_key), "network_recovered:%lu",
                         (unsigned long)generation);
                (void)prompt_arbiter_submit(PROMPT_NETWORK_CONNECTED, dedupe_key);
            }
        } else {
            portEXIT_CRITICAL(&s_outage_lock);
        }
        xEventGroupSetBits(s_network_event_group, APP_NETWORK_OUTAGE_CHANGE_BIT);
        ESP_LOGI(TAG,
                 "wifi_connected ssid=%s ip=%s rssi=%d channel=%d",
                 data.c_str(),
                 wifi.GetIpAddress().c_str(),
                 wifi.GetRssi(),
                 wifi.GetChannel());
        if (s_network_event_group != nullptr) {
            xEventGroupSetBits(s_network_event_group, APP_NETWORK_CONNECTED_BIT);
        }
        break;
    case WifiEvent::Disconnected:
        ESP_LOGW(TAG, "wifi_disconnected reason=%s", data.c_str());
        prompt_arbiter_set_network_connected(false);
        if (s_network_event_group != nullptr) {
            xEventGroupClearBits(s_network_event_group, APP_NETWORK_CONNECTED_BIT);
        }
        app_network_begin_runtime_outage();
        break;
    case WifiEvent::NoCandidates:
        ESP_LOGI(TAG, "wifi_no_candidates");
        if (s_network_event_group != nullptr) {
            xEventGroupSetBits(s_network_event_group, APP_NETWORK_NO_CANDIDATES_BIT);
        }
        break;
    case WifiEvent::ConfigModeEnter:
        ESP_LOGI(TAG, "wifi_config_mode_enter");
        ESP_LOGI(TAG, "wifi_config_ap_ssid=%s", wifi.GetApSsid().c_str());
        ESP_LOGI(TAG, "wifi_config_url=http://192.168.4.1");
        break;
    case WifiEvent::ConfigModeExit:
        ESP_LOGI(TAG, "wifi_config_mode_exit");
        if (s_network_event_group != nullptr) {
            xEventGroupSetBits(s_network_event_group, APP_NETWORK_CONFIG_EXIT_BIT);
        }
        break;
    default:
        break;
    }
}

static esp_err_t app_network_ensure_initialized(void)
{
    if (s_network_event_group == nullptr) {
        s_network_event_group = xEventGroupCreate();
        if (s_network_event_group == nullptr) {
            ESP_LOGE(TAG, "failed to create network event group");
            return ESP_ERR_NO_MEM;
        }
    }

    if (s_network_initialized) {
        return ESP_OK;
    }

    WifiManagerConfig config;
    config.ssid_prefix = "GreenMotive";
    config.language = "zh-CN";
    config.station_scan_min_interval_seconds = 15;
    config.station_scan_max_interval_seconds = 60;
    config.station_candidate_timeout_ms = DEMO_WIFI_CANDIDATE_TIMEOUT_MS;

    auto &wifi = WifiManager::GetInstance();
    if (!wifi.Initialize(config)) {
        ESP_LOGE(TAG, "wifi_manager_initialize_failed");
        return ESP_FAIL;
    }

    static bool outage_task_started;
    if (!outage_task_started) {
        const BaseType_t created = xTaskCreate(app_network_runtime_outage_task,
                                               "wifi_outage",
                                               3072,
                                               NULL,
                                               tskIDLE_PRIORITY + 1,
                                               NULL);
        if (created != pdPASS) {
            ESP_LOGE(TAG, "wifi_outage_task_start_failed");
            return ESP_ERR_NO_MEM;
        }
        outage_task_started = true;
    }

    esp_err_t credential_ret = WifiCredentialStore::GetInstance().LoadAndMigrate();
    if (credential_ret != ESP_OK) {
        ESP_LOGE(TAG, "wifi_credential_load_failed err=%s", esp_err_to_name(credential_ret));
        return credential_ret;
    }

    wifi.SetEventCallback([](WifiEvent event, const std::string &data) {
        app_network_handle_wifi_event(event, data);
    });

    esp_err_t prompt_ret = prompt_arbiter_init();
    if (prompt_ret != ESP_OK) {
        ESP_LOGE(TAG, "prompt_arbiter_init_failed err=%s", esp_err_to_name(prompt_ret));
        return prompt_ret;
    }

    s_network_initialized = true;
    return ESP_OK;
}

static void app_network_seed_build_time_credentials(void)
{
    if (s_build_credentials_seeded) {
        return;
    }
    s_build_credentials_seeded = true;

    if (DEMO_WIFI_SSID[0] != '\0' && DEMO_WIFI_PASSWORD[0] != '\0') {
        auto &credential_store = WifiCredentialStore::GetInstance();
        if (!credential_store.CanSeedBuildCredentials()) {
            return;
        }
        (void)credential_store.Upsert(DEMO_WIFI_SSID, DEMO_WIFI_PASSWORD);
        ESP_LOGI(TAG, "wifi_build_credentials_seeded ssid=%s", DEMO_WIFI_SSID);
    }
}

static bool app_network_has_saved_credentials(void)
{
    return !WifiCredentialStore::GetInstance().List().empty();
}

static void app_network_apply_power_save_policy(void)
{
#if DEMO_WIFI_POWER_SAVE_NONE
    WifiManager::GetInstance().SetPowerSaveLevel(WifiPowerSaveLevel::PERFORMANCE);
    ESP_LOGI(TAG, "Wi-Fi power save disabled for realtime audio");
#endif
}

static esp_err_t app_network_try_station_connect(void)
{
    auto &wifi = WifiManager::GetInstance();
    xEventGroupClearBits(s_network_event_group,
                         APP_NETWORK_CONNECTED_BIT | APP_NETWORK_CONFIG_EXIT_BIT |
                         APP_NETWORK_NO_CANDIDATES_BIT);

    ESP_LOGI(TAG, "wifi_connecting");
    const int64_t started_ms = esp_timer_get_time() / 1000;
    const int64_t global_deadline_ms = started_ms + DEMO_WIFI_BOOT_DEADLINE_MS;
    ESP_LOGI(TAG,
             "wifi_deadlines global_ms=%lld candidate_ms=%lld",
             (long long)global_deadline_ms,
             (long long)wifi_policy_candidate_deadline(started_ms,
                                                       global_deadline_ms,
                                                       DEMO_WIFI_CANDIDATE_TIMEOUT_MS));
    wifi.StartStation();

    const EventBits_t bits = xEventGroupWaitBits(s_network_event_group,
                                                 APP_NETWORK_CONNECTED_BIT |
                                                     APP_NETWORK_NO_CANDIDATES_BIT,
                                                 pdFALSE,
                                                 pdFALSE,
                                                 pdMS_TO_TICKS(DEMO_WIFI_BOOT_DEADLINE_MS));
    if ((bits & APP_NETWORK_CONNECTED_BIT) != 0) {
        app_network_apply_power_save_policy();
        return ESP_OK;
    }

    ESP_LOGW(TAG, "wifi_connect_failed timeout_ms=%d no_candidates=%d",
             DEMO_WIFI_BOOT_DEADLINE_MS,
             (bits & APP_NETWORK_NO_CANDIDATES_BIT) != 0);
    (void)esp_wifi_disconnect();
    wifi.StopStation();
    return ESP_ERR_TIMEOUT;
}

esp_err_t app_network_enter_config_mode(void)
{
    esp_err_t ret = app_network_ensure_initialized();
    if (ret != ESP_OK) {
        return ret;
    }

    xEventGroupClearBits(s_network_event_group, APP_NETWORK_CONFIG_EXIT_BIT);
    WifiManager::GetInstance().StartConfigAp();
    return ESP_OK;
}

esp_err_t app_network_reconfigure_blocking(void)
{
    ESP_LOGI(TAG, "wifi_reconfig_start");
    app_network_set_outage_suppressed(true);

    esp_err_t ret = app_network_enter_config_mode();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "wifi_reconfig_enter_config_failed err=%s", esp_err_to_name(ret));
        app_network_set_outage_suppressed(false);
        return ret;
    }

    const EventBits_t config_bits = xEventGroupWaitBits(s_network_event_group,
                                                        APP_NETWORK_CONFIG_EXIT_BIT,
                                                        pdTRUE,
                                                        pdFALSE,
                                                        pdMS_TO_TICKS(DEMO_WIFI_RECONFIG_TIMEOUT_MS));
    if ((config_bits & APP_NETWORK_CONFIG_EXIT_BIT) == 0) {
        ESP_LOGW(TAG, "wifi_reconfig_timeout timeout_ms=%d", DEMO_WIFI_RECONFIG_TIMEOUT_MS);
        WifiManager::GetInstance().StopConfigAp();
        if (app_network_has_saved_credentials()) {
            ret = app_network_try_station_connect();
        } else {
            ret = ESP_ERR_NOT_FOUND;
        }
        if (ret != ESP_OK) {
            (void)app_network_enter_config_mode();
        }
        app_network_set_outage_suppressed(false);
        return ret == ESP_OK ? ESP_ERR_TIMEOUT : ret;
    }
    ESP_LOGI(TAG, "wifi_reconfig_config_done");

    if (!app_network_has_saved_credentials()) {
        ESP_LOGW(TAG, "wifi_reconfig_no_saved_credentials_after_config");
        (void)app_network_enter_config_mode();
        app_network_set_outage_suppressed(false);
        return ESP_ERR_NOT_FOUND;
    }

    ret = app_network_try_station_connect();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "wifi_reconfig_station_connect_failed err=%s", esp_err_to_name(ret));
        (void)app_network_enter_config_mode();
        app_network_set_outage_suppressed(false);
        return ret;
    }

    (void)prompt_arbiter_submit(PROMPT_NETWORK_CONNECTED,
                                "network_connected:reconfigure");
    app_network_set_outage_suppressed(false);
    ESP_LOGI(TAG, "wifi_reconfig_done ssid=%s", app_network_get_ssid());
    return ESP_OK;
}

esp_err_t app_network_start(void)
{
    ESP_LOGI(TAG, "network_start");

    esp_err_t ret = app_network_ensure_initialized();
    if (ret != ESP_OK) {
        return ret;
    }

    app_network_seed_build_time_credentials();
    app_network_set_outage_suppressed(true);
    bool network_required_submitted = false;

    while (true) {
        if (app_network_has_saved_credentials()) {
            ESP_LOGI(TAG, "wifi_saved_credentials_found");
            ret = app_network_try_station_connect();
            if (ret == ESP_OK) {
                (void)prompt_arbiter_submit(PROMPT_NETWORK_CONNECTED,
                                            "network_connected:startup");
                app_network_set_outage_suppressed(false);
                return ESP_OK;
            }
        } else {
            ESP_LOGI(TAG, "wifi_no_saved_credentials");
        }

        if (!network_required_submitted) {
            (void)prompt_arbiter_submit(PROMPT_NETWORK_REQUIRED,
                                        "need_network:startup");
            network_required_submitted = true;
        }

        ret = app_network_enter_config_mode();
        if (ret != ESP_OK) {
            return ret;
        }

        xEventGroupWaitBits(s_network_event_group,
                            APP_NETWORK_CONFIG_EXIT_BIT,
                            pdTRUE,
                            pdFALSE,
                            portMAX_DELAY);
    }
}

bool app_network_is_connected(void)
{
    if (!s_network_initialized) {
        return false;
    }

    return WifiManager::GetInstance().IsConnected();
}

const char *app_network_get_ssid(void)
{
    return s_connected_ssid;
}
