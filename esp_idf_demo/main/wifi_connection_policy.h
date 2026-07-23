#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct WifiPolicyScanResult {
    std::string ssid;
    int rssi;
};

struct WifiPolicyCredential {
    std::string ssid;
    std::string password;
    uint64_t last_success;
};

struct WifiPolicyCandidate {
    std::string ssid;
    std::string password;
    int rssi;
    uint64_t last_success;
};

std::vector<WifiPolicyCandidate> wifi_policy_rank_scan(
    const std::vector<WifiPolicyScanResult>& scan,
    const std::vector<WifiPolicyCredential>& credentials);

int64_t wifi_policy_candidate_deadline(
    int64_t candidate_started_ms,
    int64_t global_deadline_ms,
    int64_t candidate_cap_ms = 3000);

int64_t wifi_policy_next_rescan_deadline(
    int64_t outage_started_ms,
    size_t rescan_index);
