#include "app_network.h"

#include "config.h"

#include "ssid_manager.h"
#include "wifi_manager.h"

#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include <string>
#include <stdio.h>

static const char *TAG = "app_network";

#define APP_NETWORK_CONNECTED_BIT   BIT0
#define APP_NETWORK_CONFIG_EXIT_BIT BIT1

static EventGroupHandle_t s_network_event_group;
static bool s_network_initialized;
static bool s_build_credentials_seeded;
static char s_connected_ssid[33];

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
        if (s_network_event_group != nullptr) {
            xEventGroupClearBits(s_network_event_group, APP_NETWORK_CONNECTED_BIT);
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
    config.ssid_prefix = "Miaoban";
    config.language = "zh-CN";

    auto &wifi = WifiManager::GetInstance();
    if (!wifi.Initialize(config)) {
        ESP_LOGE(TAG, "wifi_manager_initialize_failed");
        return ESP_FAIL;
    }

    wifi.SetEventCallback([](WifiEvent event, const std::string &data) {
        app_network_handle_wifi_event(event, data);
    });

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
        SsidManager::GetInstance().AddSsid(DEMO_WIFI_SSID, DEMO_WIFI_PASSWORD);
        ESP_LOGI(TAG, "wifi_build_credentials_seeded ssid=%s", DEMO_WIFI_SSID);
    }
}

static bool app_network_has_saved_credentials(void)
{
    const auto &ssid_list = SsidManager::GetInstance().GetSsidList();
    return !ssid_list.empty();
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
                         APP_NETWORK_CONNECTED_BIT | APP_NETWORK_CONFIG_EXIT_BIT);

    ESP_LOGI(TAG, "wifi_connecting");
    wifi.StartStation();

    const EventBits_t bits = xEventGroupWaitBits(s_network_event_group,
                                                 APP_NETWORK_CONNECTED_BIT,
                                                 pdFALSE,
                                                 pdFALSE,
                                                 pdMS_TO_TICKS(DEMO_WIFI_CONNECT_TIMEOUT_MS));
    if ((bits & APP_NETWORK_CONNECTED_BIT) != 0) {
        app_network_apply_power_save_policy();
        return ESP_OK;
    }

    ESP_LOGW(TAG, "wifi_connect_timeout timeout_ms=%d", DEMO_WIFI_CONNECT_TIMEOUT_MS);
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

    esp_err_t ret = app_network_enter_config_mode();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "wifi_reconfig_enter_config_failed err=%s", esp_err_to_name(ret));
        return ret;
    }

    xEventGroupWaitBits(s_network_event_group,
                        APP_NETWORK_CONFIG_EXIT_BIT,
                        pdTRUE,
                        pdFALSE,
                        portMAX_DELAY);
    ESP_LOGI(TAG, "wifi_reconfig_config_done");

    if (!app_network_has_saved_credentials()) {
        ESP_LOGW(TAG, "wifi_reconfig_no_saved_credentials_after_config");
        return ESP_ERR_NOT_FOUND;
    }

    ret = app_network_try_station_connect();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "wifi_reconfig_station_connect_failed err=%s", esp_err_to_name(ret));
        return ret;
    }

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

    while (true) {
        if (app_network_has_saved_credentials()) {
            ESP_LOGI(TAG, "wifi_saved_credentials_found");
            ret = app_network_try_station_connect();
            if (ret == ESP_OK) {
                return ESP_OK;
            }
        } else {
            ESP_LOGI(TAG, "wifi_no_saved_credentials");
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
