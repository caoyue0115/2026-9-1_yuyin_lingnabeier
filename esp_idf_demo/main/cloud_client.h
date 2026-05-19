#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#include "esp_err.h"

#ifndef DEMO_CLOUD_TASK_ID_MAX_LEN
#define DEMO_CLOUD_TASK_ID_MAX_LEN 64
#endif

#ifndef DEMO_CLOUD_STATUS_MAX_LEN
#define DEMO_CLOUD_STATUS_MAX_LEN 32
#endif

#ifndef DEMO_CLOUD_AUDIO_URL_MAX_LEN
#define DEMO_CLOUD_AUDIO_URL_MAX_LEN 512
#endif

#ifndef DEMO_CLOUD_QUESTION_TEXT_MAX_LEN
#define DEMO_CLOUD_QUESTION_TEXT_MAX_LEN 512
#endif

#ifndef DEMO_CLOUD_ERROR_CODE_MAX_LEN
#define DEMO_CLOUD_ERROR_CODE_MAX_LEN 128
#endif

#ifndef DEMO_CLOUD_OTA_FIELD_MAX_LEN
#define DEMO_CLOUD_OTA_FIELD_MAX_LEN 128
#endif

#ifndef DEMO_CLOUD_OTA_URL_MAX_LEN
#define DEMO_CLOUD_OTA_URL_MAX_LEN 512
#endif

#ifndef DEMO_CLOUD_ERR_BASE
#define DEMO_CLOUD_ERR_BASE 0x7000
#endif

#ifndef DEMO_CLOUD_ERR_INVALID_RESPONSE
#define DEMO_CLOUD_ERR_INVALID_RESPONSE (DEMO_CLOUD_ERR_BASE + 1)
#endif

#ifndef DEMO_CLOUD_ERR_UNSAFE_TASK_ID
#define DEMO_CLOUD_ERR_UNSAFE_TASK_ID (DEMO_CLOUD_ERR_BASE + 2)
#endif

#ifndef DEMO_CLOUD_ERR_AUDIO_HEADER_MISMATCH
#define DEMO_CLOUD_ERR_AUDIO_HEADER_MISMATCH (DEMO_CLOUD_ERR_BASE + 3)
#endif

#ifndef DEMO_CLOUD_ERR_AUDIO_STREAM_EARLY_EOF
#define DEMO_CLOUD_ERR_AUDIO_STREAM_EARLY_EOF (DEMO_CLOUD_ERR_BASE + 4)
#endif

typedef struct {
    char status[DEMO_CLOUD_STATUS_MAX_LEN];
    char audio_url[DEMO_CLOUD_AUDIO_URL_MAX_LEN];
    char question_text[DEMO_CLOUD_QUESTION_TEXT_MAX_LEN];
    char error_code[DEMO_CLOUD_ERROR_CODE_MAX_LEN];
} cloud_task_result_t;

typedef struct {
    char session_id[DEMO_CLOUD_TASK_ID_MAX_LEN];
    char status[DEMO_CLOUD_STATUS_MAX_LEN];
    char audio_stream_url[DEMO_CLOUD_AUDIO_URL_MAX_LEN];
} cloud_realtime_session_t;

typedef struct {
    char target[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char version[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char artifact[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char url[DEMO_CLOUD_OTA_URL_MAX_LEN];
    char sha256[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char min_version[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char release_id[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char notes[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    int size;
    bool force;
} cloud_ota_update_t;

typedef struct {
    int http_status;
    int poll_interval_sec;
    bool has_update;
    cloud_ota_update_t update;
} cloud_ota_manifest_t;

typedef struct {
    int http_status;
    int expected_size;
    int bytes_read;
    int bytes_written;
    int partition_subtype;
    uint32_t partition_address;
    char partition_label[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char expected_sha256[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
    char sha256[DEMO_CLOUD_OTA_FIELD_MAX_LEN];
} cloud_ota_artifact_verify_t;

typedef struct {
    const char *stage;
    bool ok;
    const char *target;
    const char *from_version;
    const char *to_version;
    const char *release_id;
    const char *error_code;
    const char *error_message;
    int free_heap;
    int rssi;
    const char *boot_partition_before;
    const char *boot_partition_after_set;
    const char *running_partition_after_reboot;
    const char *reboot_reason;
    const cloud_ota_artifact_verify_t *verify;
} cloud_ota_report_t;

typedef esp_err_t (*cloud_ota_artifact_chunk_callback_t)(const uint8_t *chunk,
                                                         size_t chunk_bytes,
                                                         void *user_ctx);

typedef struct cloud_opus_uplink cloud_opus_uplink_t;

typedef struct {
    char error_code[DEMO_CLOUD_ERROR_CODE_MAX_LEN];
    char error_message[160];
    char asr_provider[32];
    char question_text[DEMO_CLOUD_QUESTION_TEXT_MAX_LEN];
    size_t uplink_frame_count;
    size_t uplink_opus_bytes;
    size_t uplink_pcm_bytes;
    int64_t ws_connect_elapsed_us;
    int64_t first_pcm_frame_us;
    int64_t first_opus_frame_us;
    int64_t first_ws_frame_sent_us;
    int64_t last_ws_frame_sent_us;
    int64_t end_sent_us;
    int64_t first_ack_us;
    int64_t asr_final_received_us;
    int64_t done_received_us;
    bool session_started;
} cloud_opus_uplink_metrics_t;

typedef struct {
    char audio_format[16];
    char audio_packetization[16];
    int http_status;
    int64_t connect_elapsed_us;
    int64_t first_chunk_elapsed_us;
    size_t total_audio_bytes;
    size_t chunk_count;
    size_t packet_count;
    size_t first_chunk_bytes;
    size_t last_chunk_bytes;
    int64_t max_inter_chunk_gap_us;
    int64_t total_inter_chunk_gap_us;
    uint32_t seq_gap_count;
    size_t receive_queue_peak;
    uint32_t receive_queue_full_count;
    size_t decode_queue_peak;
    uint32_t decode_queue_full_count;
    uint32_t decode_packet_count;
    uint32_t decode_fail_count;
    int64_t decode_total_us;
    int64_t decode_max_us;
    int64_t pcm_queue_drain_us;
    bool headers_validated;
} cloud_realtime_audio_metrics_t;

typedef esp_err_t (*cloud_realtime_audio_chunk_callback_t)(const uint8_t *chunk,
                                                           size_t chunk_bytes,
                                                           void *user_ctx);

esp_err_t cloud_client_submit_pcm_task(const uint8_t *pcm,
                                       size_t pcm_bytes,
                                       char *task_id,
                                       size_t task_id_size);

esp_err_t cloud_client_poll_task(const char *task_id,
                                 cloud_task_result_t *result,
                                 int timeout_ms,
                                 int poll_interval_ms);

esp_err_t cloud_client_submit_realtime_session(const uint8_t *pcm,
                                               size_t pcm_bytes,
                                               cloud_realtime_session_t *session);

esp_err_t cloud_client_stream_realtime_audio(const char *audio_stream_url,
                                             cloud_realtime_audio_chunk_callback_t callback,
                                             void *user_ctx,
                                             cloud_realtime_audio_metrics_t *metrics);

esp_err_t cloud_client_fetch_ota_manifest(const char *board,
                                          const char *hw_rev,
                                          const char *app_version,
                                          cloud_ota_manifest_t *manifest);

esp_err_t cloud_client_verify_ota_artifact(const cloud_ota_update_t *update,
                                           cloud_ota_artifact_verify_t *result);

esp_err_t cloud_client_stream_ota_artifact(const cloud_ota_update_t *update,
                                           cloud_ota_artifact_verify_t *result,
                                           cloud_ota_artifact_chunk_callback_t callback,
                                           void *user_ctx);

esp_err_t cloud_client_submit_ota_report(const cloud_ota_report_t *report,
                                         int *http_status);

esp_err_t cloud_client_opus_uplink_begin(cloud_opus_uplink_t **out_uplink,
                                         cloud_opus_uplink_metrics_t *metrics);

esp_err_t cloud_client_opus_uplink_send_pcm(cloud_opus_uplink_t *uplink,
                                            const uint8_t *pcm,
                                            size_t pcm_bytes);

esp_err_t cloud_client_opus_uplink_finish(cloud_opus_uplink_t *uplink,
                                          cloud_realtime_session_t *session);

void cloud_client_opus_uplink_abort(cloud_opus_uplink_t *uplink);
