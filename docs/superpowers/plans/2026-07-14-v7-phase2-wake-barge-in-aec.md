# V7 Phase 2 Wake Barge-In And AEC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let “小明同学” interrupt a cloud answer safely and start a follow-up or new conversation without self-wake from speaker audio.

**Architecture:** Phase 2 keeps the Phase 1 conversation protocol and `playback_session` intact, adds one board-level duplex lease owner beneath it, and uses a single persistent MR AFE. The codec-write PCM is copied into a bounded reference queue with sample counters, aligned with microphone samples, and fed through AEC before WakeNet. A barge-in event mutes locally first, then waits for the server cancellation barrier before uploading the next turn.

**Tech Stack:** ESP-IDF v5.5.4, ESP32-S3, ESP-SR 2.4.6 AFE/WakeNet, ES8311, ES7210, I2S duplex, FreeRTOS, Python firmware guards, COM4 acoustic measurements.

---

## File Structure

- Create `esp_idf_demo/main/audio_duplex_session.{h,c}`: sole codec/I2S configuration owner and TX/RX leases.
- Create `esp_idf_demo/main/audio_reference.{h,c}`: bounded sample-counter reference queue and alignment metrics.
- Create `esp_idf_demo/main/barge_in_service.{h,c}`: MR AFE lifecycle, AEC/WakeNet feed, and accepted wake event.
- Modify `esp_idf_demo/main/board_audio.{h,c}`: expose owner-only codec open/mute/close primitives.
- Modify `esp_idf_demo/main/audio_out.{h,c}`: route writes through TX lease and emit the exact codec-write reference block.
- Modify `esp_idf_demo/main/audio_in.{h,c}`: route microphone reads through RX lease and expose sample counters.
- Modify `esp_idf_demo/main/playback_session.{h,c}`: use TX lease and report cancel/mute timing without changing HTTP/decode ownership.
- Modify `esp_idf_demo/main/wake_word_service.{h,c}`: feature-off M path; feature-on persistent MR path with idle AEC disabled.
- Modify `esp_idf_demo/main/conversation_controller.{h,c}`, `main.c`, `config.h`, `Kconfig.projbuild`, `CMakeLists.txt`: barge-in state transitions and feature gate.
- Modify `tests/test_esp_runtime_guards.py`, `tests/test_esp_assets.py`: owner, MR lifecycle, cancellation barrier, and resource guards.
- Create `scripts/v7_barge_in_metrics.py`: parse sanitized serial/acoustic measurements and enforce release thresholds.
- Create `tests/test_v7_barge_in_metrics.py`: parser and threshold tests.
- Create `docs/deploy/v7-barge-in-acceptance.md`: sanitized acoustic matrix and resource evidence.

## Task 1: Introduce The Sole Duplex Codec/I2S Owner

**Files:**
- Create: `esp_idf_demo/main/audio_duplex_session.h`
- Create: `esp_idf_demo/main/audio_duplex_session.c`
- Modify: `esp_idf_demo/main/board_audio.h`
- Modify: `esp_idf_demo/main/board_audio.c`
- Modify: `esp_idf_demo/main/CMakeLists.txt`
- Modify: `tests/test_esp_runtime_guards.py`

- [ ] **Step 1: Add failing ownership guards**

Assert only `audio_duplex_session.c` calls board codec configure/open/close functions when the feature is enabled. Require independent TX/RX leases and idempotent release; reject direct codec destruction from WakeNet, playback, or recording callbacks.

- [ ] **Step 2: Define the lease API**

```c
typedef struct audio_duplex_session audio_duplex_session_t;
typedef struct { audio_duplex_session_t *owner; uint32_t generation; } audio_tx_lease_t;
typedef struct { audio_duplex_session_t *owner; uint32_t generation; } audio_rx_lease_t;

esp_err_t audio_duplex_init(audio_duplex_session_t **out);
esp_err_t audio_duplex_acquire_tx(audio_duplex_session_t *, audio_tx_lease_t *);
esp_err_t audio_duplex_acquire_rx(audio_duplex_session_t *, audio_rx_lease_t *);
esp_err_t audio_duplex_write(audio_tx_lease_t *, const int16_t *, size_t samples, uint64_t *first_sample);
esp_err_t audio_duplex_read(audio_rx_lease_t *, int16_t *, size_t samples, uint64_t *first_sample);
esp_err_t audio_duplex_mute_tx(audio_tx_lease_t *);
void audio_duplex_release_tx(audio_tx_lease_t *);
void audio_duplex_release_rx(audio_rx_lease_t *);
```

Protect configuration transitions with one mutex. A stale generation returns `ESP_ERR_INVALID_STATE`. Releasing one lease must not close hardware while the other lease is active.

- [ ] **Step 3: Route board codec operations through the owner**

Keep low-level ES8311/ES7210 helpers private to `board_audio.c`; expose only owner-facing functions. Add explicit codec mute before close and record monotonic timestamps for mute request/completion.

- [ ] **Step 4: Build, run guards, and commit**

Run:

```powershell
python -m unittest tests.test_esp_runtime_guards
idf.py -C esp_idf_demo build
```

Expected: pass and app below 3 MiB.

Commit: `git add esp_idf_demo/main/audio_duplex_session.h esp_idf_demo/main/audio_duplex_session.c esp_idf_demo/main/board_audio.h esp_idf_demo/main/board_audio.c esp_idf_demo/main/CMakeLists.txt tests/test_esp_runtime_guards.py; git commit -m "feat: add duplex audio lease owner"`

## Task 2: Add The Non-Blocking Playback Reference Queue

**Files:**
- Create: `esp_idf_demo/main/audio_reference.h`
- Create: `esp_idf_demo/main/audio_reference.c`
- Modify: `esp_idf_demo/main/audio_out.c`
- Modify: `tests/test_esp_runtime_guards.py`

- [ ] **Step 1: Add failing queue contract guards**

Require fixed-size blocks with `first_sample`, no producer blocking, drop-oldest behavior, reset on start/cancel/end/underrun/volume change, and counters for writes, drops, depth, and sample discontinuities.

- [ ] **Step 2: Define and implement the queue**

```c
typedef struct {
    uint64_t first_sample;
    uint16_t sample_count;
    int16_t samples[160];
} audio_reference_block_t;

typedef struct {
    uint32_t writes;
    uint32_t drops;
    uint32_t resets;
    size_t max_depth;
} audio_reference_metrics_t;
```

Use a statically sized ring covering the measured AFE window; allocate the sample storage in PSRAM when available and keep indices/metrics in internal RAM. `audio_reference_push()` never waits: when full, discard the oldest block and increment `drops`.

- [ ] **Step 3: Tap the exact codec-write samples**

After all software format/gain processing and immediately before `audio_duplex_write`, copy the same mono 16kHz samples and returned sample counter into the reference queue. Record codec volume separately because ES8311 gain is not present in PCM.

- [ ] **Step 4: Build and commit**

Run: `python -m unittest tests.test_esp_runtime_guards; idf.py -C esp_idf_demo build`

Expected: pass.

Commit: `git add esp_idf_demo/main/audio_reference.h esp_idf_demo/main/audio_reference.c esp_idf_demo/main/audio_out.c tests/test_esp_runtime_guards.py; git commit -m "feat: tap bounded aec playback reference"`

## Task 3: Keep One MR AFE And Align Microphone/Reference Samples

**Files:**
- Create: `esp_idf_demo/main/barge_in_service.h`
- Create: `esp_idf_demo/main/barge_in_service.c`
- Modify: `esp_idf_demo/main/wake_word_service.{h,c}`
- Modify: `esp_idf_demo/main/audio_in.c`
- Modify: `esp_idf_demo/main/config.h`
- Modify: `tests/test_esp_runtime_guards.py`

- [ ] **Step 1: Add failing feature-path guards**

Require the compile-off `afe_config_init` call to use feed string `M`. Require the compile-on call to use feed string `MR`, `aec_init=true`, one model creation, idle `disable_aec`, playback `enable_aec` plus `reset_buffer`, and no runtime feed-shape switch.

- [ ] **Step 2: Add explicit configuration**

```c
#ifndef DEMO_WAKE_WORD_BARGE_IN_ENABLED
#define DEMO_WAKE_WORD_BARGE_IN_ENABLED 0
#endif
#ifndef DEMO_AEC_MIC_MINUS_REFERENCE_DELAY_SAMPLES
#define DEMO_AEC_MIC_MINUS_REFERENCE_DELAY_SAMPLES 0
#endif
#ifndef DEMO_AEC_REFERENCE_BLOCK_SAMPLES
#define DEMO_AEC_REFERENCE_BLOCK_SAMPLES 160
#endif
```

- [ ] **Step 3: Implement aligned MR feed**

Acquire an RX lease, read microphone samples with `first_sample`, and select reference samples at `mic_first_sample - configured_delay`. Feed interleaved `MR` blocks only when both sides cover the requested interval. On missing reference, counter jump, underrun, volume change, or cancel: discard the block, increment a metric, call `reset_buffer`, and restart alignment. Never bypass AEC during cloud playback.

- [ ] **Step 4: Implement lifecycle**

At idle, feed zero R with AEC disabled and accept normal WakeNet. Before cloud playback, clear queues, enable AEC, call `reset_buffer`, and enable barge event acceptance only after valid aligned frames arrive. At playback end/cancel/error, reject barge events, disable AEC, clear real reference, and return to idle zero-R feed without deleting the model.

- [ ] **Step 5: Build, compare idle metrics, and commit**

Run compile-off and compile-on builds. On COM4 idle for five minutes in each build, record CPU, minimum heap, stack high-water, and ten wake attempts; compile-on idle must not materially regress the baseline.

Commit: `git add esp_idf_demo/main/barge_in_service.h esp_idf_demo/main/barge_in_service.c esp_idf_demo/main/wake_word_service.h esp_idf_demo/main/wake_word_service.c esp_idf_demo/main/audio_in.c esp_idf_demo/main/config.h tests/test_esp_runtime_guards.py; git commit -m "feat: add persistent mr afe barge service"`

## Task 4: Make Local Cancellation Reach Hardware Mute Within 200ms

**Files:**
- Modify: `esp_idf_demo/main/playback_session.{h,c}`
- Modify: `esp_idf_demo/main/audio_out.{h,c}`
- Modify: `esp_idf_demo/main/audio_duplex_session.{h,c}`
- Modify: `tests/test_esp_runtime_guards.py`

- [ ] **Step 1: Add failing timing and idempotence guards**

Require timestamps for wake detection, cancel signal, last PCM write, codec/PA mute, and owner join. Require repeated cancel, EOF+cancel, and error+cancel to return one terminal status and one hardware release.

- [ ] **Step 2: Extend cancellation without changing ownership**

`playback_session_cancel(BARGE_IN)` sets the existing Phase 1 token, immediately asks the TX lease owner to mute, then lets HTTP/decode/jitter tasks exit. It must not wait for server `turn_cancelled`. `playback_session_join()` retains the one-second owner cleanup deadline.

- [ ] **Step 3: Add hardware mute fallback**

If queued DMA cannot be flushed within the time budget, call ES8311 codec mute or board PA disable through `audio_duplex_session`. Do not report success based only on the last software write.

- [ ] **Step 4: Build, run guards, and commit**

Run: `python -m unittest tests.test_esp_runtime_guards; idf.py -C esp_idf_demo build`

Expected: pass.

Commit: `git add esp_idf_demo/main/playback_session.h esp_idf_demo/main/playback_session.c esp_idf_demo/main/audio_out.h esp_idf_demo/main/audio_out.c esp_idf_demo/main/audio_duplex_session.h esp_idf_demo/main/audio_duplex_session.c tests/test_esp_runtime_guards.py; git commit -m "feat: mute playback on wake cancellation"`

## Task 5: Integrate Barge-In With The Conversation Controller

**Files:**
- Modify: `esp_idf_demo/main/conversation_controller.{h,c}`
- Modify: `esp_idf_demo/main/cloud_conversation.{h,c}`
- Modify: `esp_idf_demo/main/main.c`
- Modify: `tests/test_esp_runtime_guards.py`

- [ ] **Step 1: Add failing transition guards**

Cover: barge accepted only in cloud `PLAYING`; all local prompts reject it; first wake event wins; remaining quota keeps conversation; exhausted quota closes old conversation and opens new; new upload waits for matching `turn_cancelled`; two-second barrier timeout discards recording and plays “请重试”.

- [ ] **Step 2: Add controller events and states**

```c
typedef enum {
    CONV_EVENT_BARGE_IN,
    CONV_EVENT_LOCAL_MUTED,
    CONV_EVENT_TURN_CANCELLED,
    CONV_EVENT_CANCEL_TIMEOUT,
} conversation_barge_event_t;
```

On wake, atomically latch the first event, cancel/mute locally, send `turn_cancel`, stop playback-period AEC, wait 150ms of silence, play “请讲”, and record. Hold the encoded upload until the matching cancellation barrier arrives. A timeout closes the old conversation and discards the recorded follow-up.

- [ ] **Step 3: Handle exhausted follow-up quota**

After local mute, send `turn_cancel`, close the old conversation with `barge_in_new_conversation`, skip “善哉”, create a fresh v6 connection, and submit the recorded question only after old cleanup is complete. Reset follow-up quota and do not copy old context.

- [ ] **Step 4: Run server/firmware regressions and commit**

Run:

```powershell
python -m pytest tests/test_realtime_v6_protocol.py tests/test_realtime_v6_session.py tests/test_realtime_v6_api.py -q
python -m unittest tests.test_esp_assets tests.test_esp_runtime_guards
idf.py -C esp_idf_demo build
```

Expected: all pass and Phase 1 feature-off behavior remains unchanged.

Commit: `git add esp_idf_demo/main/conversation_controller.h esp_idf_demo/main/conversation_controller.c esp_idf_demo/main/cloud_conversation.h esp_idf_demo/main/cloud_conversation.c esp_idf_demo/main/main.c tests/test_esp_runtime_guards.py; git commit -m "feat: connect wake barge-in to conversations"`

## Task 6: Add Metrics And Automated Release Gates

**Files:**
- Create: `scripts/v7_barge_in_metrics.py`
- Create: `tests/test_v7_barge_in_metrics.py`
- Modify: `tests/test_esp_runtime_guards.py`
- Modify: `esp_idf_demo/main/barge_in_service.c`
- Modify: `esp_idf_demo/main/playback_session.c`

- [ ] **Step 1: Add failing parser tests**

Test sanitized metric lines for reference drops/depth, sample offset, alignment resets, AEC errors, wake-to-mute, worker cleanup, underrun duration/playback duration, heap/PSRAM, stack high-water, and false/true wake counts. Reject logs containing full URLs, device IDs, conversation IDs, raw questions, answers, or audio.

- [ ] **Step 2: Emit structured, non-sensitive metrics**

Use numeric counters and coarse reason enums only. Define underrun ratio exactly as `underrun_duration_us / total_playback_duration_us`; also record underruns per playback minute.

- [ ] **Step 3: Implement the gate script**

Fail when wake-to-hardware-mute exceeds 200ms, owner cleanup exceeds 1s, server barrier exceeds 2s, stack reserve is below 25%, memory declines monotonically, underrun ratio rises by more than one percentage point, 30-minute self-wake count is nonzero, or any distance/volume cell is below 9/10 successful wakes.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_v7_barge_in_metrics.py -q`

Expected: all pass.

Commit: `git add scripts/v7_barge_in_metrics.py tests/test_v7_barge_in_metrics.py tests/test_esp_runtime_guards.py esp_idf_demo/main/barge_in_service.c esp_idf_demo/main/playback_session.c; git commit -m "test: gate v7 barge-in metrics"`

## Task 7: COM4 Acoustic Matrix And Canary Release

**Files:**
- Create: `docs/deploy/v7-barge-in-acceptance.md`
- Build artifacts only beyond the report.

- [ ] **Step 1: Run full software verification**

Run authoritative Linux/container Python tests, firmware guards, `git diff --check`, staged gitleaks, and both feature-off/on ESP-IDF builds. Record app size against the 3,145,728-byte slot.

- [ ] **Step 2: Flash the feature-on build to COM4**

Run: `idf.py -p COM4 flash monitor`

Expected: one MR AFE is created, idle AEC is disabled, playback enables AEC, and no watchdog/reset occurs.

- [ ] **Step 3: Execute the acoustic matrix**

For low/medium/high volume and near/mid/room distance, run at least ten wake attempts per cell in quiet, daily noise, and Buddhist-answer playback. Run 30 minutes of answers without speaking the wake word. Test first answer, first follow-up, third follow-up, and exhausted-quota interruption.

- [ ] **Step 4: Verify acoustic mute and resource soak**

Capture a local measurement microphone trace and correlate wake event to acoustic energy threshold. Run 50 answers and 20 interrupts; confirm no monotonic heap/PSRAM loss, stack reserve at least 25%, no handle/task growth, and underrun gate pass.

Write aggregate cell counts, wake-to-mute percentiles, false-wake count, resource minima, public firmware hash, and pass/fail to `docs/deploy/v7-barge-in-acceptance.md`; do not include raw audio or identifiers.

- [ ] **Step 5: Keep default off unless every gate passes**

If any 200ms, false-wake, success-rate, memory, stack, or underrun gate fails, leave `DEMO_WAKE_WORD_BARGE_IN_ENABLED=0`. If all pass, enable only a single-device canary build, monitor metrics, then prepare the separate OTA release under `v6-n16r8-ota-release`.

- [ ] **Step 6: Commit the sanitized acceptance record**

Commit public hashes, aggregate metrics, build size, and pass/fail only: `git add docs/deploy/v7-barge-in-acceptance.md; git commit -m "test: record v7 barge-in acceptance"`.
