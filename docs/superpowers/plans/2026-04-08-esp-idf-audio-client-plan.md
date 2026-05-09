# ESP-IDF Audio Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt the independent ESP-IDF demo project to `ESP-VoCat v1.2（喵伴）` on `ESP-IDF 5.5.4`, using a board-native trigger and board-native audio pipeline that records, uploads, polls, downloads, and plays audio.

**Architecture:** Keep the existing `esp_idf_demo/` as the integration base, but refactor it around four explicit boundaries: trigger input, board audio input, cloud transport, and board audio output. First land a touch-triggered path on `ESP-VoCat v1.2`, then leave a second trigger slot for future prompt-word or wake-word support without rewriting the state machine.

**Tech Stack:** ESP-IDF 5.5.4, C, esp_http_client, esp_wifi, FreeRTOS, ESP-VoCat BSP, esp_codec_dev, touch input driver

---

### Task 1: Re-baseline the project for ESP-VoCat v1.2 and ESP-IDF 5.5.4

**Files:**
- Modify: `esp_idf_demo/CMakeLists.txt`
- Modify: `esp_idf_demo/main/CMakeLists.txt`
- Modify: `esp_idf_demo/main/config.h`
- Modify: `esp_idf_demo/main/main.c`
- Modify: `esp_idf_demo/README.md`

- [x] Remove outdated external-peripheral assumptions from `main/config.h`.
- [x] Add `ESP-IDF 5.5.4` as the documented toolchain baseline in `esp_idf_demo/README.md`.
- [x] Identify and declare any `ESP-VoCat v1.2` BSP or component dependencies in the build files.
- [x] Update the startup banner in `main.c` to print the detected build target and trigger mode.

### Task 2: Implement a trigger abstraction

**Files:**
- Modify: `esp_idf_demo/main/main.c`
- Create: `esp_idf_demo/main/trigger_input.h`
- Create: `esp_idf_demo/main/trigger_input.c`
- Delete: obsolete single-source trigger files

- [x] Add a small application state enum for `idle`, `recording`, `uploading`, `polling`, `downloading`, `playing`, and `error`.
- [x] Define a trigger event API that can represent `touch` now and `wake_word` later.
- [x] Implement touch-based trigger initialization and an event read helper against the board-supported input path.
- [x] Wire the main loop so a trigger event starts the audio pipeline only while idle.
- [x] Keep every state transition and trigger source visible in serial logs.

### Task 3: Replace external mic capture with board-native audio input

**Files:**
- Modify: `esp_idf_demo/main/audio_in.h`
- Modify: `esp_idf_demo/main/audio_in.c`
- Modify: `esp_idf_demo/main/config.h`

- [x] Replace raw external pin setup with the `ESP-VoCat v1.2` board recording path or the exact codec/I2S path exposed by the board support package.
- [x] Preserve the output contract of `16kHz / 16-bit / mono PCM` even if the internal slot width remains `32-bit`.
- [x] Implement a helper that records a fixed-duration PCM buffer after trigger.
- [x] Return both the captured byte buffer and byte length to the caller.
- [x] Log the capture size and elapsed record time.

### Task 4: Implement cloud upload and polling

**Files:**
- Modify: `esp_idf_demo/main/cloud_client.h`
- Modify: `esp_idf_demo/main/cloud_client.c`
- Modify: `esp_idf_demo/main/config.h`

- [x] Add a helper to `POST /api/v2/tasks` with raw PCM and the required headers.
- [x] Parse the JSON response and extract `task_id`.
- [x] Add a polling helper for `GET /api/v2/tasks/{task_id}` that waits for `done` or `failed`.
- [x] Parse `audio_url`, `question_text`, `error_code`, and `status` from the result payload.
- [x] Keep the parser minimal and targeted to the current cloud contract.
- [x] Ensure no board-specific assumptions leak into the transport layer.

### Task 5: Replace external playback with board-native audio output

**Files:**
- Modify: `esp_idf_demo/main/audio_out.h`
- Modify: `esp_idf_demo/main/audio_out.c`
- Modify: `esp_idf_demo/main/config.h`

- [x] Add an HTTP download helper or cloud helper function that retrieves the returned WAV.
- [x] Parse the WAV header and locate the PCM data region.
- [x] Replace the old speaker-specific path with the board-native speaker playback path.
- [x] Implement PCM playback using the decoded WAV payload and the board-supported output driver.
- [x] Log playback start and finish.

### Task 6: Integrate the full trigger-driven pipeline

**Files:**
- Modify: `esp_idf_demo/main/main.c`

- [x] Connect the trigger flow to recording, upload, polling, download, and playback.
- [x] Ensure failure in any stage logs a clear error and returns to `idle`.
- [x] Keep only one in-flight request at a time.
- [x] Print the recognized `question_text` and the cloud error code when present.
- [x] Prevent recording from starting until trigger input and board audio are both initialized successfully.

### Task 7: Document ESP-VoCat v1.2 usage and wake-up strategy

**Files:**
- Modify: `README.md`
- Create: `esp_idf_demo/README.md`
- Modify: `docs/superpowers/summaries/2026-04-08-hardware-handoff.md`

- [x] Replace old assumptions with `ESP-VoCat v1.2` hardware notes.
- [x] Document that `ESP-IDF 5.5.4` is the required baseline.
- [x] Document touch-triggered testing first, with wake-word support marked as a future extension.
- [x] Document the expected serial output for a successful round trip.
- [x] Add a short “flash and monitor” command sequence for ESP-IDF users.

### Task 8: Verification and cleanup under the new board target

**Files:**
- Verify: `esp_idf_demo/**`

- [x] Run a quick source sanity pass to ensure headers and source files match.
- [x] Build with `ESP-IDF 5.5.4` against the `ESP-VoCat v1.2` target configuration.
- [x] Record any remaining gaps for wake-word integration separately from the touch-triggered MVP.
- [x] Re-scan the repo status to ensure only intended files changed.
- [x] Commit the finished ESP-IDF demo client.
