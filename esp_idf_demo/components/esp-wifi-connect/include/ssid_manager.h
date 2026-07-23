#ifndef SSID_MANAGER_H
#define SSID_MANAGER_H

#include <string>
#include <vector>
#include <functional>

struct SsidItem {
    std::string ssid;
    std::string password;
};

class SsidManager {
public:
    using ChangeCallback = std::function<bool(const std::vector<SsidItem>&)>;

    static SsidManager& GetInstance() {
        static SsidManager instance;
        return instance;
    }

    bool AddSsid(const std::string& ssid, const std::string& password);
    bool RemoveSsid(int index);
    bool SetDefaultSsid(int index);
    bool Clear();
    void ReplaceAll(const std::vector<SsidItem>& items);
    void SetChangeCallback(ChangeCallback callback);
    const std::vector<SsidItem>& GetSsidList() const { return ssid_list_; }

private:
    SsidManager();
    ~SsidManager();

    bool NotifyChanged();

    std::vector<SsidItem> ssid_list_;
    ChangeCallback change_callback_;
};

#endif // SSID_MANAGER_H
