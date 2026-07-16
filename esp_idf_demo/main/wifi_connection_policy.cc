#include "wifi_connection_policy.h"

#include <algorithm>
#include <map>

std::vector<WifiPolicyCandidate> wifi_policy_rank_scan(
    const std::vector<WifiPolicyScanResult>& scan,
    const std::vector<WifiPolicyCredential>& credentials) {
    std::map<std::string, int> strongest_by_ssid;
    for (const auto& result : scan) {
        if (result.ssid.empty()) {
            continue;
        }
        auto found = strongest_by_ssid.find(result.ssid);
        if (found == strongest_by_ssid.end() || result.rssi > found->second) {
            strongest_by_ssid[result.ssid] = result.rssi;
        }
    }

    std::vector<WifiPolicyCandidate> candidates;
    for (const auto& credential : credentials) {
        const auto visible = strongest_by_ssid.find(credential.ssid);
        if (visible == strongest_by_ssid.end()) {
            continue;
        }
        candidates.push_back({
            credential.ssid,
            credential.password,
            visible->second,
            credential.last_success,
        });
    }
    std::stable_sort(candidates.begin(), candidates.end(),
                     [](const WifiPolicyCandidate& lhs, const WifiPolicyCandidate& rhs) {
                         if (lhs.rssi != rhs.rssi) {
                             return lhs.rssi > rhs.rssi;
                         }
                         return lhs.last_success > rhs.last_success;
                     });
    return candidates;
}

int64_t wifi_policy_candidate_deadline(
    int64_t candidate_started_ms,
    int64_t global_deadline_ms,
    int64_t candidate_cap_ms) {
    if (candidate_cap_ms < 0) {
        candidate_cap_ms = 0;
    }
    return std::min(candidate_started_ms + candidate_cap_ms, global_deadline_ms);
}

int64_t wifi_policy_next_rescan_deadline(
    int64_t outage_started_ms,
    size_t rescan_index) {
    static constexpr int64_t kInitialDeadlinesMs[] = {15000, 30000, 60000};
    if (rescan_index < 3) {
        return outage_started_ms + kInitialDeadlinesMs[rescan_index];
    }
    return outage_started_ms + 60000 * static_cast<int64_t>(rescan_index - 1);
}
