# V3 Opus And Close Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden ESP realtime playback shutdown so v3 sessions always converge to idle, and add optional v3 downlink Opus with PCM fallback.

**Architecture:** Keep the current HTTP chunked v3 pipeline. Add a bounded close timeout on the ESP playback shutdown path, and add format negotiation so the server can stream either raw PCM or framed Opus while the ESP keeps one shared PCM jitter/playback path after decode.

**Tech Stack:** FastAPI, Python realtime session service, ESP-IDF C, Espressif Opus codec APIs, unittest.

---

### Task 1: Server format negotiation tests

**Files:**
- Modify: `tests/test_realtime_api.py`
- Modify: `src/api/realtime.py`
- Modify: `src/services/realtime_session.py`

- [ ] **Step 1: Write failing tests for PCM default and Opus opt-in**
- [ ] **Step 2: Run targeted realtime API tests and verify failure**
- [ ] **Step 3: Implement session/audio metadata for selected format and headers**
- [ ] **Step 4: Re-run targeted tests and verify pass**

### Task 2: Server Opus stream encoding

**Files:**
- Modify: `src/services/realtime_session.py`
- Modify: `src/settings.py`
- Modify: `tests/test_realtime_api.py`

- [ ] **Step 1: Write failing tests for framed Opus output and PCM fallback**
- [ ] **Step 2: Run targeted tests and verify failure**
- [ ] **Step 3: Implement PCM-to-Opus framed stream conversion with low-quality 16 kHz mono defaults**
- [ ] **Step 4: Re-run targeted tests and verify pass**

### Task 3: ESP close timeout hardening

**Files:**
- Modify: `esp_idf_demo/main/config.h`
- Modify: `esp_idf_demo/main/audio_out.c`

- [ ] **Step 1: Add a failing regression-oriented unit/integration surrogate if feasible; otherwise add explicit timeout behavior assertion in code comments and logs**
- [ ] **Step 2: Implement bounded close wait timeout and explicit timeout error path**
- [ ] **Step 3: Verify code still preserves summary logging and idle recovery path**

### Task 4: ESP v3 Opus ingest/decode

**Files:**
- Modify: `esp_idf_demo/main/idf_component.yml`
- Modify: `esp_idf_demo/main/cloud_client.h`
- Modify: `esp_idf_demo/main/cloud_client.c`
- Modify: `esp_idf_demo/main/main.c`

- [ ] **Step 1: Extend stream metadata structures for negotiated format**
- [ ] **Step 2: Parse audio-format headers and keep PCM path unchanged**
- [ ] **Step 3: Add framed Opus parsing and decode-to-PCM path**
- [ ] **Step 4: Keep existing jitter metrics and summary logs intact**

### Task 5: Verification

**Files:**
- Modify: `tests/test_realtime_api.py`
- Modify: `tests/test_realtime_tts_provider.py` if needed

- [ ] **Step 1: Run targeted Python tests**
- [ ] **Step 2: Build `esp_idf_demo`**
- [ ] **Step 3: Review logs/headers for PCM and Opus cases**
- [ ] **Step 4: Summarize residual risks**
