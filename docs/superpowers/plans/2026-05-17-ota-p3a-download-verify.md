# OTA P3a Download Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OTA P3a artifact download verification without writing OTA partitions, plus a local release creation CLI.

**Architecture:** Keep OTA network logic in `esp_idf_demo/main/cloud_client.c` and orchestration logs in `esp_idf_demo/main/main.c`. Keep cloud release creation in `scripts/ota_release_create.py` using existing SQLite helpers.

**Tech Stack:** ESP-IDF C firmware, mbedTLS SHA256, FastAPI/SQLite storage helpers, Python unittest/pytest.

---

### Task 1: Board-Side P3a Static Contract

**Files:**
- Modify: `tests/test_esp_assets.py`
- Modify: `esp_idf_demo/main/cloud_client.h`
- Modify: `esp_idf_demo/main/cloud_client.c`
- Modify: `esp_idf_demo/main/main.c`

- [ ] **Step 1: Write failing tests**

Assert `cloud_ota_artifact_verify_t`, `cloud_client_verify_ota_artifact`, `stage=ota_artifact_verify`, `download_verify_only`, and SHA256 comparison code are present. Assert forbidden OTA partition APIs remain absent.

- [ ] **Step 2: Run focused tests**

Run `env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_esp_assets.py`. Expected before implementation: fail because P3a symbols do not exist.

- [ ] **Step 3: Implement artifact verifier**

Add `cloud_ota_artifact_verify_t` and `cloud_client_verify_ota_artifact()` that streams HTTP response bytes, updates SHA256, counts bytes, compares against manifest `size` and `sha256`, and returns `ESP_OK` only on full match.

- [ ] **Step 4: Wire verifier into dry-run task**

When manifest has an update, log `update_available ... action=download_verify_only`, call the verifier, and log `stage=ota_artifact_verify event=done|failed`.

### Task 2: Cloud Release CLI

**Files:**
- Create: `scripts/ota_release_create.py`
- Create: `tests/test_ota_release_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Test that the CLI creates a release from a temporary artifact, computes size/SHA256, whitelists devices, and makes `/api/v5/ota/manifest` return the release.

- [ ] **Step 2: Run CLI test**

Run `env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_release_cli.py`. Expected before implementation: fail because the script does not exist.

- [ ] **Step 3: Implement CLI**

Use argparse. Validate artifact path is a file under `settings.ota_artifact_path`. Parse `--device-id` repeated and `--device-ids` comma-separated. Call `storage_db.init_db()` and `storage_db.create_ota_release()`.

### Task 3: Verification and Compile-Only Package

**Files:**
- Read: `tmp/`
- Create: `tmp/esp_compile_only_2026-05-17_v30.tar.gz`

- [ ] **Step 1: Run full Python tests**

Run `env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q`. Expected: pass.

- [ ] **Step 2: Run ESP-IDF build**

Run the standard ESP-IDF build command. Expected: `Project build complete`.

- [ ] **Step 3: Create compile-only package**

Create `tmp/esp_compile_only_2026-05-17_v30.tar.gz` from `esp_idf_demo/`, excluding `.env*`, `.git`, `build/`, `managed_components/`, `tmp/`, `data/`, `indices/`, and caches.

- [ ] **Step 4: Record package evidence**

Report path, bytes, SHA256, file count, and forbidden-content check result.
