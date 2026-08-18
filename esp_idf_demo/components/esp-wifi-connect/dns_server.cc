#include "dns_server.h"
#include <esp_log.h>
#include <lwip/sockets.h>
#include <lwip/netdb.h>

#define TAG "DnsServer"

DnsServer::DnsServer()
    : stopped_signal_(xSemaphoreCreateBinary()) {
    if (stopped_signal_ == nullptr) {
        ESP_LOGE(TAG, "Failed to create DNS stop signal");
    }
}

DnsServer::~DnsServer() {
    Stop();
    if (stopped_signal_ != nullptr) {
        vSemaphoreDelete(stopped_signal_);
        stopped_signal_ = nullptr;
    }
}

void DnsServer::Start(esp_ip4_addr_t gateway) {
    // If already running, stop first
    if (running_ || task_handle_ != nullptr) {
        Stop();
    }
    if (stopped_signal_ == nullptr) {
        ESP_LOGE(TAG, "Cannot start DNS server without stop signal");
        return;
    }
    (void)xSemaphoreTake(stopped_signal_, 0);

    ESP_LOGI(TAG, "Starting DNS server");
    gateway_ = gateway;

    const int socket_fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (socket_fd < 0) {
        ESP_LOGE(TAG, "Failed to create socket");
        return;
    }
    fd_.store(socket_fd);

    struct sockaddr_in server_addr;
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    server_addr.sin_port = htons(port_);

    if (bind(socket_fd, (struct sockaddr *)&server_addr, sizeof(server_addr)) < 0) {
        ESP_LOGE(TAG, "failed to bind port %d", port_);
        close(socket_fd);
        fd_.store(-1);
        return;
    }

    running_ = true;
    const BaseType_t created = xTaskCreate([](void* arg) {
        DnsServer* dns_server = static_cast<DnsServer*>(arg);
        dns_server->Run();
        xSemaphoreGive(dns_server->stopped_signal_);
        vTaskDelete(NULL);
    }, "DnsServerTask", 4096, this, 5, &task_handle_);
    if (created != pdPASS) {
        ESP_LOGE(TAG, "Failed to create DNS server task");
        running_ = false;
        task_handle_ = nullptr;
        const int failed_fd = fd_.exchange(-1);
        if (failed_fd >= 0) {
            close(failed_fd);
        }
    }
}

void DnsServer::Stop() {
    if (!running_ && task_handle_ == nullptr) {
        return;
    }

    ESP_LOGI(TAG, "Stopping DNS server");
    running_ = false;

    // Close socket to unblock recvfrom
    {
        std::lock_guard<std::mutex> socket_lock(socket_mutex_);
        const int socket_fd = fd_.exchange(-1);
        if (socket_fd >= 0) {
            shutdown(socket_fd, SHUT_RDWR);
            close(socket_fd);
        }
    }

    // Run() and the task wrapper must stop touching this object before return.
    if (task_handle_ != nullptr) {
        if (xTaskGetCurrentTaskHandle() == task_handle_) {
            ESP_LOGE(TAG, "DNS task cannot synchronously stop itself");
            return;
        }
        xSemaphoreTake(stopped_signal_, portMAX_DELAY);
        task_handle_ = nullptr;
    }
}

void DnsServer::Run() {
    char buffer[512];
    const int socket_fd = fd_.load();
    while (running_) {
        struct sockaddr_in client_addr;
        socklen_t client_addr_len = sizeof(client_addr);
        int len = recvfrom(socket_fd, buffer, sizeof(buffer) - 16, 0,
                           (struct sockaddr *)&client_addr, &client_addr_len);
        if (len < 0) {
            if (!running_) {
                // Socket was closed during Stop(), exit gracefully
                break;
            }
            ESP_LOGE(TAG, "recvfrom failed, errno=%d", errno);
            continue;
        }
        if (len < 12) {
            ESP_LOGW(TAG, "Ignoring malformed DNS packet: %d bytes", len);
            continue;
        }

        if (!running_) {
            break;
        }

        // Simple DNS response: point all queries to 192.168.4.1
        buffer[2] |= 0x80;  // Set response flag
        buffer[3] |= 0x80;  // Set Recursion Available
        buffer[7] = 1;      // Set answer count to 1

        // Add answer section
        memcpy(&buffer[len], "\xc0\x0c", 2);  // Name pointer
        len += 2;
        memcpy(&buffer[len], "\x00\x01\x00\x01\x00\x00\x00\x1c\x00\x04", 10);  // Type, class, TTL, data length
        len += 10;
        memcpy(&buffer[len], &gateway_.addr, 4);  // 192.168.4.1
        len += 4;
        ESP_LOGI(TAG, "Sending DNS response to %s", inet_ntoa(gateway_.addr));

        {
            std::lock_guard<std::mutex> socket_lock(socket_mutex_);
            if (!running_ || fd_.load() != socket_fd) {
                break;
            }
            sendto(socket_fd, buffer, len, 0,
                   (struct sockaddr *)&client_addr, client_addr_len);
        }
    }

    ESP_LOGI(TAG, "DNS server task exiting");
}
