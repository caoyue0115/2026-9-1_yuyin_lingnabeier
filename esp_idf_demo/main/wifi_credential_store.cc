#include "wifi_credential_store.h"

#include "ssid_manager.h"

#include "nvs.h"

#include <algorithm>
#include <array>
#include <cstdio>
#include <set>
#include <utility>

namespace {

constexpr char kMetaNamespace[] = "wifi_cred_meta";
constexpr char kSlotNamespaces[][12] = {"wifi_cred_a", "wifi_cred_b"};
constexpr char kActiveSlotKey[] = "active_slot";
constexpr char kSchemaKey[] = "schema";
constexpr char kCountKey[] = "count";
constexpr uint8_t kSchemaVersion = 2;
constexpr size_t kLegacyCredentialLimit = 10;

std::string IndexedKey(const char* prefix, size_t index) {
    char key[16];
    std::snprintf(key, sizeof(key), "%s%u", prefix, static_cast<unsigned>(index));
    return key;
}

esp_err_t ReadString(nvs_handle_t handle, const std::string& key, std::string* value) {
    size_t size = 0;
    esp_err_t ret = nvs_get_str(handle, key.c_str(), nullptr, &size);
    if (ret != ESP_OK || size == 0) {
        return ret == ESP_OK ? ESP_ERR_INVALID_SIZE : ret;
    }
    std::vector<char> buffer(size);
    ret = nvs_get_str(handle, key.c_str(), buffer.data(), &size);
    if (ret == ESP_OK) {
        *value = buffer.data();
    }
    return ret;
}

esp_err_t ReadSlot(int slot, std::vector<WifiCredential>* credentials) {
    if (slot < 0 || slot > 1 || credentials == nullptr) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle = 0;
    esp_err_t ret = nvs_open(kSlotNamespaces[slot], NVS_READONLY, &handle);
    if (ret != ESP_OK) {
        return ret;
    }
    uint8_t schema = 0;
    uint8_t count = 0;
    ret = nvs_get_u8(handle, kSchemaKey, &schema);
    if (ret == ESP_OK) {
        ret = nvs_get_u8(handle, kCountKey, &count);
    }
    if (ret != ESP_OK || schema != kSchemaVersion || count > WifiCredentialStore::MAX_WIFI_CREDENTIALS) {
        nvs_close(handle);
        return ret == ESP_OK ? ESP_ERR_INVALID_VERSION : ret;
    }

    std::vector<WifiCredential> loaded;
    std::set<std::string> seen;
    for (size_t index = 0; index < count && ret == ESP_OK; ++index) {
        WifiCredential item{};
        ret = ReadString(handle, IndexedKey("ssid", index), &item.ssid);
        if (ret == ESP_OK) {
            ret = ReadString(handle, IndexedKey("pass", index), &item.password);
        }
        if (ret == ESP_OK) {
            ret = nvs_get_u64(handle, IndexedKey("seen", index).c_str(), &item.last_success);
        }
        if (ret == ESP_OK && (item.ssid.empty() || !seen.insert(item.ssid).second)) {
            ret = ESP_ERR_INVALID_STATE;
        }
        if (ret == ESP_OK) {
            loaded.push_back(std::move(item));
        }
    }
    nvs_close(handle);
    if (ret == ESP_OK) {
        *credentials = std::move(loaded);
    }
    return ret;
}

esp_err_t WriteSlot(int slot, const std::vector<WifiCredential>& credentials) {
    if (slot < 0 || slot > 1 || credentials.size() > WifiCredentialStore::MAX_WIFI_CREDENTIALS) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle = 0;
    esp_err_t ret = nvs_open(kSlotNamespaces[slot], NVS_READWRITE, &handle);
    if (ret != ESP_OK) {
        return ret;
    }
    ret = nvs_erase_all(handle);
    if (ret == ESP_OK) {
        ret = nvs_set_u8(handle, kSchemaKey, kSchemaVersion);
    }
    if (ret == ESP_OK) {
        ret = nvs_set_u8(handle, kCountKey, static_cast<uint8_t>(credentials.size()));
    }
    for (size_t index = 0; index < credentials.size() && ret == ESP_OK; ++index) {
        const auto& item = credentials[index];
        ret = nvs_set_str(handle, IndexedKey("ssid", index).c_str(), item.ssid.c_str());
        if (ret == ESP_OK) {
            ret = nvs_set_str(handle, IndexedKey("pass", index).c_str(), item.password.c_str());
        }
        if (ret == ESP_OK) {
            ret = nvs_set_u64(handle, IndexedKey("seen", index).c_str(), item.last_success);
        }
    }
    if (ret == ESP_OK) {
        ret = nvs_commit(handle);
    }
    nvs_close(handle);
    return ret;
}

int GetActiveSlot() {
    nvs_handle_t handle = 0;
    if (nvs_open(kMetaNamespace, NVS_READONLY, &handle) != ESP_OK) {
        return -1;
    }
    uint8_t slot = 0xff;
    const esp_err_t ret = nvs_get_u8(handle, kActiveSlotKey, &slot);
    nvs_close(handle);
    return ret == ESP_OK && slot <= 1 ? static_cast<int>(slot) : -1;
}

esp_err_t SetActiveSlot(int slot) {
    nvs_handle_t handle = 0;
    esp_err_t ret = nvs_open(kMetaNamespace, NVS_READWRITE, &handle);
    if (ret == ESP_OK) {
        ret = nvs_set_u8(handle, kActiveSlotKey, static_cast<uint8_t>(slot));
    }
    if (ret == ESP_OK) {
        ret = nvs_commit(handle);
    }
    if (handle != 0) {
        nvs_close(handle);
    }
    return ret;
}

esp_err_t ReadLegacy(std::vector<WifiCredential>* credentials) {
    nvs_handle_t handle = 0;
    esp_err_t ret = nvs_open("wifi", NVS_READONLY, &handle);
    if (ret == ESP_ERR_NVS_NOT_FOUND) {
        credentials->clear();
        return ESP_OK;
    }
    if (ret != ESP_OK) {
        return ret;
    }
    std::vector<WifiCredential> loaded;
    std::set<std::string> seen;
    for (size_t index = 0; index < kLegacyCredentialLimit; ++index) {
        std::string ssid_key = index == 0 ? "ssid" : IndexedKey("ssid", index);
        std::string password_key = index == 0 ? "password" : IndexedKey("password", index);
        WifiCredential item{};
        ret = ReadString(handle, ssid_key, &item.ssid);
        if (ret == ESP_ERR_NVS_NOT_FOUND) {
            continue;
        }
        if (ret != ESP_OK) {
            break;
        }
        ret = ReadString(handle, password_key, &item.password);
        if (ret != ESP_OK) {
            break;
        }
        if (!item.ssid.empty() && seen.insert(item.ssid).second) {
            item.last_success = kLegacyCredentialLimit - index;
            loaded.push_back(std::move(item));
        }
    }
    nvs_close(handle);
    if (ret == ESP_ERR_NVS_NOT_FOUND) {
        ret = ESP_OK;
    }
    if (ret == ESP_OK) {
        if (loaded.size() > WifiCredentialStore::MAX_WIFI_CREDENTIALS) {
            loaded.resize(WifiCredentialStore::MAX_WIFI_CREDENTIALS);
        }
        *credentials = std::move(loaded);
    }
    return ret;
}

}  // namespace

WifiCredentialStore& WifiCredentialStore::GetInstance() {
    static WifiCredentialStore instance;
    return instance;
}

esp_err_t WifiCredentialStore::LoadAndMigrate() {
    esp_err_t ret = ESP_OK;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const int active_slot = GetActiveSlot();
        active_schema_present_ = active_slot >= 0;
        if (active_schema_present_) {
            ret = ReadSlot(active_slot, &credentials_);
            if (ret != ESP_OK) {
                const esp_err_t active_error = ret;
                const int fallback_slot = 1 - active_slot;
                ret = ReadSlot(fallback_slot, &credentials_);
                if (ret == ESP_OK) {
                    ret = SetActiveSlot(fallback_slot);
                } else {
                    ret = ReadLegacy(&credentials_);
                    legacy_credentials_present_ = ret == ESP_OK && !credentials_.empty();
                    if (legacy_credentials_present_) {
                        ret = PersistLocked();
                    } else {
                        ret = active_error;
                    }
                }
            }
        } else {
            ret = ReadLegacy(&credentials_);
            legacy_credentials_present_ = ret == ESP_OK && !credentials_.empty();
            if (ret == ESP_OK && legacy_credentials_present_) {
                ret = PersistLocked();
            }
        }
    }
    if (ret == ESP_OK) {
        SyncRuntimeList();
        SsidManager::GetInstance().SetChangeCallback(
            [this](const std::vector<SsidItem>& items) {
                return ReplaceFromRuntime(items) == ESP_OK;
            });
    }
    return ret;
}

std::vector<WifiCredential> WifiCredentialStore::List() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return credentials_;
}

esp_err_t WifiCredentialStore::Upsert(const std::string& ssid, const std::string& password) {
    if (ssid.empty() || ssid.size() > 32 || password.size() > 64) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_err_t ret = ESP_OK;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto previous = credentials_;
        auto found = std::find_if(credentials_.begin(), credentials_.end(),
                                  [&ssid](const WifiCredential& item) { return item.ssid == ssid; });
        if (found != credentials_.end()) {
            found->password = password;
        } else {
            if (credentials_.size() >= MAX_WIFI_CREDENTIALS) {
                auto oldest = std::min_element(
                    credentials_.begin(), credentials_.end(),
                    [](const WifiCredential& lhs, const WifiCredential& rhs) {
                        return lhs.last_success < rhs.last_success;
                    });
                credentials_.erase(oldest);
            }
            credentials_.push_back({ssid, password, 0});
        }
        ret = PersistLocked();
        if (ret != ESP_OK) {
            credentials_ = previous;
        }
    }
    if (ret == ESP_OK) {
        SyncRuntimeList();
    }
    return ret;
}

esp_err_t WifiCredentialStore::MarkSuccessful(const std::string& ssid) {
    esp_err_t ret = ESP_ERR_NOT_FOUND;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto previous = credentials_;
        auto found = std::find_if(credentials_.begin(), credentials_.end(),
                                  [&ssid](const WifiCredential& item) { return item.ssid == ssid; });
        if (found != credentials_.end()) {
            uint64_t newest = 0;
            for (const auto& item : credentials_) {
                newest = std::max(newest, item.last_success);
            }
            found->last_success = newest + 1;
            std::stable_sort(credentials_.begin(), credentials_.end(),
                             [](const WifiCredential& lhs, const WifiCredential& rhs) {
                                 return lhs.last_success > rhs.last_success;
                             });
            ret = PersistLocked();
            if (ret != ESP_OK) {
                credentials_ = previous;
            }
        }
    }
    if (ret == ESP_OK) {
        SyncRuntimeList();
    }
    return ret;
}

bool WifiCredentialStore::CanSeedBuildCredentials() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return credentials_.empty() && !active_schema_present_ && !legacy_credentials_present_;
}

esp_err_t WifiCredentialStore::PersistLocked() {
    const int active_slot = GetActiveSlot();
    const int inactive_slot = active_slot == 0 ? 1 : 0;
    esp_err_t ret = WriteSlot(inactive_slot, credentials_);
    std::vector<WifiCredential> verified;
    if (ret == ESP_OK) {
        ret = ReadSlot(inactive_slot, &verified);
    }
    if (ret == ESP_OK && verified != credentials_) {
        ret = ESP_ERR_INVALID_STATE;
    }
    if (ret == ESP_OK) {
        ret = SetActiveSlot(inactive_slot);
    }
    if (ret == ESP_OK) {
        active_schema_present_ = true;
    }
    return ret;
}

esp_err_t WifiCredentialStore::ReplaceFromRuntime(const std::vector<SsidItem>& items) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto previous = credentials_;
    std::vector<WifiCredential> replacement;
    std::set<std::string> seen;
    for (const auto& item : items) {
        if (item.ssid.empty() || !seen.insert(item.ssid).second) {
            continue;
        }
        uint64_t last_success = 0;
        auto existing = std::find_if(credentials_.begin(), credentials_.end(),
                                     [&item](const WifiCredential& value) {
                                         return value.ssid == item.ssid;
                                     });
        if (existing != credentials_.end()) {
            last_success = existing->last_success;
        }
        replacement.push_back({item.ssid, item.password, last_success});
        if (replacement.size() == MAX_WIFI_CREDENTIALS) {
            break;
        }
    }
    credentials_ = std::move(replacement);
    const esp_err_t ret = PersistLocked();
    if (ret != ESP_OK) {
        credentials_ = previous;
    }
    return ret;
}

void WifiCredentialStore::SyncRuntimeList() {
    std::vector<SsidItem> items;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        items.reserve(credentials_.size());
        for (const auto& credential : credentials_) {
            items.push_back({credential.ssid, credential.password});
        }
    }
    SsidManager::GetInstance().ReplaceAll(items);
}
