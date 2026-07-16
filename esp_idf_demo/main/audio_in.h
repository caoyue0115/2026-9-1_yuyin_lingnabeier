#pragma once

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#define DEMO_AUDIO_IN_ERR_WAIT_TIMEOUT ((esp_err_t)0x7101)

typedef struct {
    uint32_t elapsed_ms;
    uint32_t max_level;
    size_t speech_prefix_bytes;
} audio_in_wait_metrics_t;

typedef struct {
    bool vad_stopped;
    bool voice_started;
    uint32_t max_level;
    uint32_t elapsed_ms;
    size_t pcm_bytes;
} audio_in_record_metrics_t;

typedef esp_err_t (*audio_in_pcm_chunk_callback_t)(const uint8_t *pcm,
                                                   size_t pcm_bytes,
                                                   void *user_ctx);

esp_err_t audio_in_probe(void);

// Opens the mic, waits for real speech start, and returns a small speech prefix buffer
// that should be prepended to the formal recording buffer. The caller owns the returned
// prefix buffer and must free() it. On timeout no audio is retained.
esp_err_t audio_in_wait_for_speech_start(uint8_t **out_speech_prefix,
                                         size_t *out_speech_prefix_bytes,
                                         audio_in_wait_metrics_t *out_metrics);

// Continues capture from an already-open microphone after speech start was detected.
// The caller owns the returned buffer and must free() it.
esp_err_t audio_in_record_after_speech_start(const uint8_t *speech_prefix,
                                             size_t speech_prefix_bytes,
                                             uint8_t **out_buffer,
                                             size_t *out_bytes,
                                             audio_in_record_metrics_t *out_metrics);

// Continues capture from an already-open microphone after speech start was detected
// and streams PCM chunks to callback without allocating the full recording buffer.
esp_err_t audio_in_stream_after_speech_start(const uint8_t *speech_prefix,
                                             size_t speech_prefix_bytes,
                                             audio_in_pcm_chunk_callback_t callback,
                                             void *user_ctx,
                                             audio_in_record_metrics_t *out_metrics);

// Records mono PCM into heap memory. VAD may stop before the fixed maximum duration.
// The caller owns the returned buffer and must free() it.
esp_err_t audio_in_record_fixed_duration(uint8_t **out_buffer,
                                         size_t *out_bytes);

void audio_in_deinit(void);
