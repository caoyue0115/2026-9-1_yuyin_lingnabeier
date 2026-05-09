# V3 Opus And Close Hardening Design

## Goal

Stabilize the ESP32 realtime playback pipeline so `stream_audio done` always converges to `pipeline result -> idle`, and add optional v3 downlink Opus transport with PCM fallback to reduce weak-network starvation.

## Scope

In scope:

- Harden ESP-IDF realtime audio close/playback shutdown so the pipeline cannot wait indefinitely for jitter playback task completion.
- Keep existing diagnostics and surface an explicit close-timeout failure instead of hanging forever.
- Add server-side v3 audio format negotiation for `pcm` and `opus`.
- Keep existing PCM behavior as fallback and default-safe path.
- Add ESP-IDF v3 downlink Opus decode path for framed Opus chunks.
- Use lower-quality speech settings intentionally: Opus `16 kHz`, mono, low bitrate to prioritize continuity over fidelity.

Out of scope:

- Uplink Opus.
- WebSocket migration.
- MQTT/UDP.
- Wake-word changes.
- Intro audio/SPIFFS fixes.

## Design

### 1. Close/playback hardening

Current close behavior depends on the jitter playback task exiting by itself after `stream_task_started=false` and ringbuffer drains to zero. When that does not happen, the pipeline can stall before `pipeline result` and never return to `idle`.

Change:

- Add a bounded close wait timeout in `audio_out_close_pcm_stream_with_metrics()`.
- Keep the existing periodic `Realtime jitter close waiting ...` log.
- If timeout expires before `stream_task_done=true`, log an explicit timeout summary and return `ESP_ERR_TIMEOUT` to the pipeline.
- Do not silently pretend success. A failed close should surface as a pipeline failure instead of freezing the device state.

This does not solve the underlying starvation cause by itself, but it removes the worst failure mode: indefinite busy state.

### 2. V3 downlink audio negotiation

The v3 `/audio` endpoint will support two formats:

- `pcm`
- `opus`

The ESP request will advertise support using a request header such as:

- `X-Accept-Audio-Format: opus,pcm`

The server will choose one format and return:

- `X-Audio-Format: pcm|opus`
- existing PCM headers for PCM mode
- Opus-specific headers for Opus mode:
  - `X-Opus-Sample-Rate: 16000`
  - `X-Opus-Channels: 1`
  - `X-Opus-Frame-Duration-Ms: 60`

The server default remains PCM unless Opus is explicitly enabled and requested.

### 3. Server-side Opus streaming

Server realtime audio generation already yields PCM chunks. We will add an Opus encoding stage on the v3 `/audio` path only.

For Opus mode:

- normalize PCM to `16 kHz`, mono, 16-bit
- accumulate PCM into fixed 60 ms frames
- encode each frame to Opus
- stream framed packets as:

```text
uint16_be payload_len + opus_payload
```

Reason for length-prefix framing:

- HTTP chunk boundaries are not a transport contract
- ESP side needs deterministic packet boundaries
- keeps parsing simple

Recommended quality target:

- sample rate: `16 kHz`
- channels: `1`
- bitrate: low, roughly `16-24 kbps`

This is a deliberate quality tradeoff. The goal is intelligible speech and lower starvation risk, not high-fidelity TTS.

### 4. ESP-IDF Opus playback path

Current ESP path assumes raw PCM bytes and pushes them directly into the jitter ringbuffer.

Change:

- inspect `X-Audio-Format`
- if `pcm`: keep current behavior
- if `opus`:
  - parse length-prefixed Opus packets from the HTTP stream
  - decode each packet to PCM using Espressif Opus decoder APIs
  - feed decoded PCM into the existing jitter/playback path

This preserves the existing playback queue and metrics logic. The change is limited to stream ingestion and decode.

### 5. Metrics and failure semantics

For PCM and Opus both:

- preserve `session_id`, `first_audio_byte_local_ms`, `max_inter_chunk_gap_ms`, `realtime_audio_summary`
- preserve `max_enqueue_ms` / `avg_enqueue_ms`
- if Opus decode fails, fail the pipeline explicitly
- do not silently switch formats mid-session

## Files

Likely changes:

- `docs/superpowers/specs/2026-04-13-v3-opus-close-hardening-design.md`
- `docs/superpowers/plans/2026-04-13-v3-opus-close-hardening-plan.md`
- `src/settings.py`
- `src/api/realtime.py`
- `src/services/realtime_session.py`
- `src/storage/realtime_store.py` if stream metadata needs persistence
- `src/providers/realtime_tts.py` and/or new Opus encoder helper
- `tests/test_realtime_api.py`
- `tests/test_realtime_tts_provider.py` if encoder helpers live there
- `esp_idf_demo/main/cloud_client.h`
- `esp_idf_demo/main/cloud_client.c`
- `esp_idf_demo/main/audio_out.h`
- `esp_idf_demo/main/audio_out.c`
- `esp_idf_demo/main/main.c`
- `esp_idf_demo/main/config.h`
- `esp_idf_demo/main/idf_component.yml`

## Acceptance

### Close hardening

- `stream_audio done` never leaves the device permanently busy.
- If close succeeds: logs include playback task done, summary, pipeline result, and transition to idle.
- If close cannot finish before timeout: pipeline fails explicitly and still returns control to idle.

### Opus

- v3 `/audio` can stream either PCM or Opus.
- PCM fallback remains functional.
- ESP decodes Opus and plays it through existing jitter pipeline.
- Weak-network audio transfer size is materially lower than PCM.
- Speech remains intelligible at reduced quality.
