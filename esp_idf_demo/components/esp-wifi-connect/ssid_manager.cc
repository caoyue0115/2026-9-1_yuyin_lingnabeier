#include "ssid_manager.h"

#include <algorithm>
#include <esp_log.h>
#include <utility>

#define TAG "SsidManager"
#define MAX_WIFI_SSID_COUNT 5

SsidManager::SsidManager() = default;

SsidManager::~SsidManager() {
}

bool SsidManager::Clear() {
    const auto previous = ssid_list_;
    ssid_list_.clear();
    if (!NotifyChanged()) {
        ssid_list_ = previous;
        return false;
    }
    return true;
}

void SsidManager::ReplaceAll(const std::vector<SsidItem>& items) {
    ssid_list_ = items;
    if (ssid_list_.size() > MAX_WIFI_SSID_COUNT) {
        ssid_list_.resize(MAX_WIFI_SSID_COUNT);
    }
}

void SsidManager::SetChangeCallback(ChangeCallback callback) {
    change_callback_ = std::move(callback);
}

bool SsidManager::NotifyChanged() {
    if (change_callback_) {
        return change_callback_(ssid_list_);
    }
    return true;
}

bool SsidManager::AddSsid(const std::string& ssid, const std::string& password) {
    const auto previous = ssid_list_;
    for (auto& item : ssid_list_) {
        ESP_LOGI(TAG, "compare [%s:%d] [%s:%d]", item.ssid.c_str(), item.ssid.size(), ssid.c_str(), ssid.size());
        if (item.ssid == ssid) {
            ESP_LOGW(TAG, "SSID %s already exists, overwrite it", ssid.c_str());
            item.password = password;
            if (!NotifyChanged()) {
                ssid_list_ = previous;
                return false;
            }
            return true;
        }
    }

    if (ssid_list_.size() >= MAX_WIFI_SSID_COUNT) {
        ESP_LOGW(TAG, "SSID list is full, pop one");
        ssid_list_.pop_back();
    }
    // Add the new ssid to the front of the list
    ssid_list_.insert(ssid_list_.begin(), {ssid, password});
    if (!NotifyChanged()) {
        ssid_list_ = previous;
        return false;
    }
    return true;
}

bool SsidManager::RemoveSsid(int index) {
    if (index < 0 || static_cast<size_t>(index) >= ssid_list_.size()) {
        ESP_LOGW(TAG, "Invalid index %d", index);
        return false;
    }
    const auto previous = ssid_list_;
    ssid_list_.erase(ssid_list_.begin() + index);
    if (!NotifyChanged()) {
        ssid_list_ = previous;
        return false;
    }
    return true;
}

bool SsidManager::SetDefaultSsid(int index) {
    if (index < 0 || static_cast<size_t>(index) >= ssid_list_.size()) {
        ESP_LOGW(TAG, "Invalid index %d", index);
        return false;
    }
    const auto previous = ssid_list_;
    // Move the ssid at index to the front of the list
    auto item = ssid_list_[index];
    ssid_list_.erase(ssid_list_.begin() + index);
    ssid_list_.insert(ssid_list_.begin(), item);
    if (!NotifyChanged()) {
        ssid_list_ = previous;
        return false;
    }
    return true;
}
