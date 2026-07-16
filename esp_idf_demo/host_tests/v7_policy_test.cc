#include "wifi_connection_policy.h"

#include <cassert>

int main() {
    const std::vector<WifiPolicyCredential> credentials = {
        {"home", "h", 5},
        {"phone", "p", 4},
        {"office", "o", 3},
        {"temple", "t", 2},
        {"guest", "g", 1},
    };
    const std::vector<WifiPolicyScanResult> scan = {
        {"unknown", -20},
        {"home", -80},
        {"home", -45},
        {"phone", -50},
        {"office", -70},
    };

    const auto ranked = wifi_policy_rank_scan(scan, credentials);
    assert(ranked.size() == 3);
    assert(ranked[0].ssid == "home");
    assert(ranked[0].rssi == -45);
    assert(ranked[1].ssid == "phone");
    assert(ranked[2].ssid == "office");

    assert(wifi_policy_candidate_deadline(1000, 9000) == 4000);
    assert(wifi_policy_candidate_deadline(7500, 9000) == 9000);
    assert(wifi_policy_next_rescan_deadline(1000, 0) == 16000);
    assert(wifi_policy_next_rescan_deadline(1000, 1) == 31000);
    assert(wifi_policy_next_rescan_deadline(1000, 2) == 61000);
    assert(wifi_policy_next_rescan_deadline(1000, 3) == 121000);
    return 0;
}
