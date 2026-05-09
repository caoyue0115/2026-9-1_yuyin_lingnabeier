# Record Prompt And Waiting Speech Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local pre-record prompt plus a waiting-for-speech state so formal recording starts only after real speech begins.

**Architecture:** Keep the first phase fully serial. Play a local PCM prompt, wait for prompt playback to drain, then initialize microphone capture and enter a new waiting window that uses the existing energy threshold plus arm/hold timing to detect real speech start before consuming the formal recording budget.

**Tech Stack:** ESP-IDF, ESP-VoCat BSP, local SPIFFS PCM assets, existing lightweight energy VAD.

---

### Task 1: Add Config And State Definitions

**Files:**
- Modify: `esp_idf_demo/main/config.h`
- Modify: `esp_idf_demo/main/main.c`

- [ ] Add `DEMO_RECORD_PROMPT_*` and waiting-speech timing constants in `config.h`.
- [ ] Add `APP_STATE_PLAYING_PROMPT` and `APP_STATE_WAITING_SPEECH` in `main.c`.
- [ ] Add log labels for the new stages.

### Task 2: Add Local Prompt Resource Wiring

**Files:**
- Modify: `esp_idf_demo/main/config.h`
- Modify: `esp_idf_demo/main/main.c`
- Modify: `esp_idf_demo/spiffs/`

- [ ] Define local prompt path such as `/spiffs/record_prompt_1.pcm`.
- [ ] Add playback stage before microphone init.
- [ ] On missing file or playback failure, log path and error clearly, then continue into waiting-for-speech.

### Task 3: Split Waiting-For-Speech From Formal Recording

**Files:**
- Modify: `esp_idf_demo/main/audio_in.h`
- Modify: `esp_idf_demo/main/audio_in.c`

- [ ] Add a helper to initialize microphone capture for waiting mode without immediately consuming formal recording budget.
- [ ] Add waiting-for-speech detection using:
  - arm window
  - hold duration above threshold
  - timeout without upload
- [ ] Add a helper to continue into formal recording after speech start using the current lightweight VAD ending logic.

### Task 4: Wire Pipeline State Flow

**Files:**
- Modify: `esp_idf_demo/main/main.c`

- [ ] Change realtime trigger flow to:
  - play prompt
  - wait for speech
  - record after speech
  - post session
- [ ] Ensure prompt drain completes before entering waiting state.
- [ ] Ensure wait timeout returns to `idle` without upload.

### Task 5: Add Observability

**Files:**
- Modify: `esp_idf_demo/main/main.c`
- Modify: `esp_idf_demo/main/audio_in.c`

- [ ] Add logs:
  - `stage=record_prompt event=start/done`
  - `stage=waiting_speech event=start/armed/speech_detected/timeout`
  - `stage=recording event=start reason=speech_detected`
  - `record_budget_ms=...`
- [ ] Keep existing heap/stack logs intact.

### Task 6: Verify

**Files:**
- Test by build: `esp_idf_demo`

- [ ] Run `idf.py build` and confirm success.
- [ ] Sanity-check that no new warnings or obvious regressions appear in modified files.

