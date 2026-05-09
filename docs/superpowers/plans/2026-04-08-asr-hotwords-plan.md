# ASR Hotwords Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DashScope hotword support and a first Buddhism vocabulary pack to improve ASR recognition quality.

**Architecture:** Keep the current upload and worker flow unchanged. Add optional ASR runtime config, thread it into the Recognition constructor, and provide an operator script plus default hotword data for creating a DashScope vocabulary.

**Tech Stack:** Python, DashScope SDK, unittest, JSON config

---

### Task 1: Add failing ASR provider tests

**Files:**
- Modify: `tests/test_asr_provider.py`

- [ ] Add tests that expect `language_hints=["zh"]` and `vocabulary_id` to be passed into the Recognition constructor.
- [ ] Run: `python3 -m unittest tests.test_asr_provider -v`
- [ ] Confirm the new tests fail for the current implementation.

### Task 2: Implement runtime hotword config

**Files:**
- Modify: `src/settings.py`
- Modify: `src/providers/asr.py`
- Modify: `.env.example`

- [ ] Add settings for `ASR_LANGUAGE_HINTS` and `ASR_VOCABULARY_ID`.
- [ ] Build Recognition kwargs from settings and include `vocabulary_id` only when present.
- [ ] Re-run: `python3 -m unittest tests.test_asr_provider -v`
- [ ] Confirm all ASR provider tests pass.

### Task 3: Add vocabulary creation assets

**Files:**
- Create: `config/asr_hotwords.buddhism.json`
- Create: `scripts/create_asr_vocabulary.py`
- Modify: `tests/test_smoke_scripts.py`

- [ ] Add a first Buddhism hotword list with explicit weights and `lang`.
- [ ] Add a helper script that creates or updates a DashScope vocabulary and prints the resulting `ASR_VOCABULARY_ID`.
- [ ] Add tests for loading the hotword file and shaping the request payload.

### Task 4: Document and verify

**Files:**
- Modify: `README.md`

- [ ] Document how to create/update the hotword vocabulary and set `ASR_VOCABULARY_ID`.
- [ ] Run: `python3 -m unittest tests.test_asr_provider tests.test_pipeline tests.test_smoke_scripts tests.test_app_healthz -v`
- [ ] Run: `python3 -m py_compile $(find src scripts tests -name '*.py' | sort)`
- [ ] If verification passes, commit the feature.
