#ifndef _DNS_SERVER_H_
#define _DNS_SERVER_H_

#include <string>
#include <atomic>
#include <mutex>
#include <esp_netif_ip_addr.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

class DnsServer {
public:
    DnsServer();
    ~DnsServer();

    void Start(esp_ip4_addr_t gateway);
    void Stop();

private:
    int port_ = 53;
    std::atomic<int> fd_{-1};
    esp_ip4_addr_t gateway_;
    std::atomic<bool> running_{false};
    std::mutex socket_mutex_;
    TaskHandle_t task_handle_ = nullptr;
    SemaphoreHandle_t stopped_signal_ = nullptr;
    void Run();
};

#endif // _DNS_SERVER_H_
