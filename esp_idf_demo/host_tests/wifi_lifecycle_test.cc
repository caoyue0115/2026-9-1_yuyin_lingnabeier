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
                   !max_active.compare_exchange_weak(observed, now)) {
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            --active;
        });
    }
    for (auto& worker : workers) {
        worker.join();
    }
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
