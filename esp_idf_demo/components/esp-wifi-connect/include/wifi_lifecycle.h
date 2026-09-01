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

    bool IsStopping() const {
        return stopping_.load();
    }

private:
    std::atomic<uint32_t> generation_{0};
    std::atomic<bool> stopping_{true};
};
