# Config AP STA netif Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore DHCP during repeated Wi-Fi provisioning while preventing duplicate default STA netifs and stale asynchronous configuration exits.

**Architecture:** `WifiConfigurationAp` owns temporary STA and AP netifs for its APSTA lifetime. A small host-testable lifecycle header provides a full-transition mutex and generation-based configuration sessions; `WifiManager` and the portal use those primitives to serialize ownership changes and invalidate stale callbacks.

**Tech Stack:** ESP-IDF v5.5.4, C++17, FreeRTOS event groups/tasks, ESP Wi-Fi/netif, Python pytest, native C++ host test.

---

### Task 1: Add host-testable lifecycle primitives

**Files:**
- Create: `esp_idf_demo/components/esp-wifi-connect/include/wifi_lifecycle.h`
- Create: `esp_idf_demo/host_tests/wifi_lifecycle_test.cc`

- [ ] **Step 1: Write the failing host test**

Create `wifi_lifecycle_test.cc` with these behaviors:

```cpp
#include "wifi_lifecycle.h"

#include <atomic>
#include <cassert>
#include <chrono>
#include <thread>
#include <vector>

int main() {
    WifiTransitionGate gate;
    std::atomic<int> active{0};
    std::atomic<int> max_active{0};
    std::vector<std::thread> workers;
    for (int i = 0; i < 8; ++i) {
        workers.emplace_back([&]() {
            auto guard = gate.Acquire();
            const int now = ++active;
            int observed = max_active.load();
            while (now > observed &&
                   !max_active.compare_exchange_weak(observed, now)) {}
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            --active;
        });
    }
    for (auto& worker : workers) worker.join();
    assert(max_active.load() == 1);

    WifiConfigSession session;
    const uint32_t first = session.Begin();
    assert(session.IsCurrent(first));
    session.Stop();
    assert(!session.IsCurrent(first));
    const uint32_t second = session.Begin();
    assert(second != first);
    assert(session.IsCurrent(second));
    assert(!session.IsCurrent(first));
    return 0;
}
```

- [ ] **Step 2: Run the host test and verify RED**

Run:

```powershell
g++ -std=c++17 -pthread -Iesp_idf_demo/components/esp-wifi-connect/include esp_idf_demo/host_tests/wifi_lifecycle_test.cc -o C:\tmp\wifi_lifecycle_test.exe
```

Expected: compilation fails because `wifi_lifecycle.h` does not exist. If no native compiler is installed, install a scoped MinGW-w64/LLVM host compiler before repeating this RED check.

- [ ] **Step 3: Implement the lifecycle header**

Create a header-only implementation:

```cpp
#pragma once

#include <atomic>
#include <cstdint>
#include <mutex>

class WifiTransitionGate {
public:
    std::unique_lock<std::mutex> Acquire() {
        return std::unique_lock<std::mutex>(mutex_);
    }

private:
    std::mutex mutex_;
};

class WifiConfigSession {
public:
    uint32_t Begin() {
        const uint32_t next = generation_.fetch_add(1) + 1;
        stopping_.store(false);
        return next;
    }

    void Stop() {
        stopping_.store(true);
        generation_.fetch_add(1);
    }

    bool IsCurrent(uint32_t generation) const {
        return !stopping_.load() && generation_.load() == generation;
    }

    bool IsStopping() const { return stopping_.load(); }

private:
    std::atomic<uint32_t> generation_{0};
    std::atomic<bool> stopping_{true};
};
```

- [ ] **Step 4: Run the host test and verify GREEN**

Compile with the command above, then run `C:\tmp\wifi_lifecycle_test.exe`.
Expected: exit code `0` and no assertion output.

- [ ] **Step 5: Commit**

```powershell
git add esp_idf_demo/components/esp-wifi-connect/include/wifi_lifecycle.h esp_idf_demo/host_tests/wifi_lifecycle_test.cc
git commit -m "test: add wifi lifecycle concurrency policy"
```

### Task 2: Serialize complete WifiManager transitions

**Files:**
- Modify: `esp_idf_demo/components/esp-wifi-connect/include/wifi_manager.h`
- Modify: `esp_idf_demo/components/esp-wifi-connect/wifi_manager.cc`
- Modify: `tests/test_esp_assets.py`

- [ ] **Step 1: Write the failing manager wiring test**

Extend `test_v7_wifi_review_regressions_are_guarded` to load
`wifi_manager.h` and assert:

```python
self.assertIn('#include "wifi_lifecycle.h"', manager_header)
self.assertIn("WifiTransitionGate transition_gate_", manager_header)
for method in ("StartStation", "StopStation", "StartConfigAp", "StopConfigAp"):
    body = manager.split(f"void WifiManager::{method}()", 1)[1].split("\n}", 1)[0]
    self.assertIn("transition_gate_.Acquire()", body)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run `python -m pytest -q tests/test_esp_assets.py::EspAssetTests::test_v7_wifi_review_regressions_are_guarded` using the class name reported by pytest collection if it differs.

Expected: failure because the transition gate and generation-aware stop are absent.

- [ ] **Step 3: Wire the transition gate**

In `wifi_manager.h`, include `wifi_lifecycle.h` and add
`WifiTransitionGate transition_gate_;`.

At the beginning of every public Start/Stop method, acquire the gate before
inspecting or changing mode state:

```cpp
auto transition = transition_gate_.Acquire();
```

Keep the gate held through each underlying `station_->Stop()`,
`station_->Start()`, `config_ap_->Stop()`, or `config_ap_->Start()` call. Store
which manager events must be emitted, release the gate, and only then call
`NotifyEvent`.

Auto-stop paths perform the underlying opposite-mode stop directly while the
gate is already held so they do not recursively acquire the gate.

- [ ] **Step 4: Verify manager wiring**

Run the focused pytest again. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add esp_idf_demo/components/esp-wifi-connect/include/wifi_manager.h esp_idf_demo/components/esp-wifi-connect/wifi_manager.cc tests/test_esp_assets.py
git commit -m "fix: serialize wifi mode transitions"
```

### Task 3: Give Config AP a temporary STA netif and cancellable session

**Files:**
- Modify: `esp_idf_demo/components/esp-wifi-connect/include/wifi_manager.h`
- Modify: `esp_idf_demo/components/esp-wifi-connect/wifi_manager.cc`
- Modify: `esp_idf_demo/components/esp-wifi-connect/include/wifi_configuration_ap.h`
- Modify: `esp_idf_demo/components/esp-wifi-connect/wifi_configuration_ap.cc`
- Modify: `tests/test_esp_assets.py`

- [ ] **Step 1: Write failing portal lifecycle assertions**

Add assertions to the Wi-Fi regression test:

```python
self.assertIn("esp_netif_t* station_netif_ = nullptr", portal_header)
self.assertIn("std::atomic<bool> is_connecting_{false}", portal_header)
self.assertIn("std::shared_ptr<WifiConfigSession> session_", portal_header)
self.assertIn("StopConfigApForGeneration", manager)
self.assertIn("esp_netif_create_default_wifi_sta()", portal)
self.assertIn("session_->Stop()", portal)
self.assertIn("xEventGroupSetBits(event_group_, WIFI_FAIL_BIT)", portal)
self.assertIn("esp_netif_destroy_default_wifi(station_netif_)", portal)
self.assertLess(portal.index("esp_wifi_stop();"), portal.index("esp_netif_destroy_default_wifi(station_netif_)"))
self.assertNotIn("static_cast<WifiConfigurationAp*>(ctx)", portal)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run the same focused pytest. Expected: failure on the missing temporary STA
netif and session-aware shutdown.

- [ ] **Step 3: Update the portal interface and state**

In `wifi_configuration_ap.h`:

```cpp
#include <atomic>
#include "wifi_lifecycle.h"

void OnExitRequested(std::function<void(uint32_t)> callback);
bool IsGenerationCurrent(uint32_t generation) const;

std::atomic<bool> is_connecting_{false};
esp_netif_t* station_netif_ = nullptr;
std::shared_ptr<WifiConfigSession> session_ = std::make_shared<WifiConfigSession>();
uint32_t active_generation_ = 0;
std::function<void(uint32_t)> on_exit_requested_;
```

In `wifi_manager.h`, declare `StopConfigApForGeneration(uint32_t)` and
`StopConfigApLocked(const uint32_t*)`. Configure the portal callback to pass
its expected generation. Public `StopConfigAp()` and the generation-aware path
each acquire the transition gate once and call the locked helper; the helper
rejects a stale generation before changing manager state or stopping the AP.

At the start of `Start()`, set
`active_generation_ = session_->Begin()`. In `StartAccessPoint()`, create both
default netifs before selecting APSTA mode:

```cpp
station_netif_ = esp_netif_create_default_wifi_sta();
ap_netif_ = esp_netif_create_default_wifi_ap();
```

- [ ] **Step 4: Make connection and event work stoppable**

`ConnectToWifi()` returns false immediately when `session_->IsStopping()`, uses
atomic stores for `is_connecting_`, and treats the stop-triggered
`WIFI_FAIL_BIT` as cancellation. Timer, Wi-Fi, IP, and SmartConfig callbacks
return before touching state when the session is stopping. Protect
`scan_timer_` reads/restarts with the existing portal mutex and check it for
null before every `esp_timer_start_once` call.

- [ ] **Step 5: Replace raw delayed-exit tasks**

Use one `ScheduleExit(delay_ms)` implementation for `/submit`, `/exit`, and
SmartConfig. Allocate a task context containing only a shared session, expected
generation, copied `std::function<void(uint32_t)>`, and delay. After the delay,
invoke the callback only when `session->IsCurrent(generation)`. The manager
performs the final generation check while holding the transition gate.

- [ ] **Step 6: Implement ordered shutdown**

At the beginning of `Stop()`, call `session_->Stop()`, set `WIFI_FAIL_BIT`, and
stop active scanning. Then stop the HTTP server, unregister SmartConfig/Wi-Fi/IP
handlers, stop and delete the scan timer under `mutex_`, call `esp_wifi_stop()`,
destroy `station_netif_`, destroy `ap_netif_`, and null both pointers. Reset
`is_connecting_` after resources are quiet.

- [ ] **Step 7: Verify portal lifecycle tests**

Run the focused pytest. Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add esp_idf_demo/components/esp-wifi-connect/include/wifi_manager.h esp_idf_demo/components/esp-wifi-connect/wifi_manager.cc esp_idf_demo/components/esp-wifi-connect/include/wifi_configuration_ap.h esp_idf_demo/components/esp-wifi-connect/wifi_configuration_ap.cc tests/test_esp_assets.py
git commit -m "fix: restore DHCP during repeated wifi provisioning"
```

### Task 4: Build and regression verification

**Files:**
- Verify only; no release or flashing files are changed.

- [ ] **Step 1: Run host and Python regressions**

```powershell
C:\tmp\wifi_lifecycle_test.exe
python -m pytest -q tests/test_esp_assets.py
python -m pytest -q tests/test_esp_runtime_guards.py
```

Expected: all commands exit `0`.

- [ ] **Step 2: Build the ESP32-S3 firmware**

```powershell
. C:\esp\v5.5.4\esp-idf\export.ps1
Set-Location esp_idf_demo
idf.py -B C:\tmp\wifi-netif-build build
```

Expected: `Project build complete` with no compile or link errors.

- [ ] **Step 3: Inspect the final diff**

Run `git diff --check origin/main...HEAD` and
`git diff --stat origin/main...HEAD`. Confirm changes are limited to the design,
plan, lifecycle header/test, Wi-Fi Manager, Config AP, and regression tests.

- [ ] **Step 4: Request a final sub-agent review**

Ask the reviewer to inspect `origin/main...HEAD` for duplicate netif ownership,
transition deadlocks, stale generations, shutdown races, and missing tests.
Resolve every Critical issue and technically valid Important issue before any
PR or merge.

- [ ] **Step 5: Hardware acceptance remains gated**

Do not flash or publish OTA. After explicit authorization, validate on the
named serial device: connect, delete the saved network, submit the same network
again, observe `IP_EVENT_STA_GOT_IP`, and confirm the configuration portal exits
without timeout or reboot.
