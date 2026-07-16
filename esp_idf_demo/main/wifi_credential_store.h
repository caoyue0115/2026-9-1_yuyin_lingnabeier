#pragma once

#include "esp_err.h"

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

struct SsidItem;

struct WifiCredential {
    std::string ssid;
    std::string password;
    uint64_t last_success;

    bool operator==(const WifiCredential& other) const {
        return ssid == other.ssid && password == other.password &&
               last_success == other.last_success;
    }
};

class WifiCredentialStore {
public:
    static constexpr size_t MAX_WIFI_CREDENTIALS = 5;

    static WifiCredentialStore& GetInstance();

    esp_err_t LoadAndMigrate();
    std::vector<WifiCredential> List() const;
    esp_err_t Upsert(const std::string& ssid, const std::string& password);
    esp_err_t MarkSuccessful(const std::string& ssid);
    bool CanSeedBuildCredentials() const;

private:
    WifiCredentialStore() = default;

    esp_err_t PersistLocked();
    esp_err_t ReplaceFromRuntime(const std::vector<SsidItem>& items);
    void SyncRuntimeList();

    mutable std::mutex mutex_;
    std::vector<WifiCredential> credentials_;
    bool active_schema_present_ = false;
    bool legacy_credentials_present_ = false;
};
