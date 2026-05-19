# OTA P3b Partition Write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OTA P3b inactive partition writing without boot switching or rebooting.

**Architecture:** Keep HTTP/SHA256 artifact streaming in `esp_idf_demo/main/cloud_client.c` and expose a chunk callback so P3a verification and P3b partition writing share the same stream. Keep ESP-IDF OTA partition selection, handle lifecycle, logs, and report orchestration in `esp_idf_demo/main/main.c`. Extend the existing OTA report payload schema locally so partition-write details are persisted in `payload_json`.

**Tech Stack:** ESP-IDF C firmware, `esp_ota_ops`, mbedTLS SHA256, FastAPI/Pydantic report schema, Python unittest/pytest static contract tests.

---

## Closure Status

P3b is closed for the current acceptance scope. This plan implemented write-inactive-only behavior and must not be read as P3c or boot-switch completion.

Final accepted behavior:

- P3a is complete.
- P3b writes inactive OTA partition only.
- P3b does not call `esp_ota_set_boot_partition`.
- P3b does not reboot.
- P3b does not mark app valid or trigger rollback mutation.
- This plan records the P3b boundary. P3c was later authorized separately and has since passed the 002 v34 canary.

Current device acceptance:

- `miaoban-v1p2-001` does not participate in OTA.
- `miaoban-v1p2-002` completed P3b single-device canary.
- `miaoban-v1p2-003` is user-confirmed as passing by default.

002 P3b evidence:

```text
device_id=miaoban-v1p2-002
release_id=2026-05-18-v32-002-p3b
running_partition=ota_0
update_partition=ota_1
partition_label=ota_1
partition_subtype=17
partition_address=0x320000
bytes_read=226432
bytes_written=226432
expected_size=226432
sha256=abfe6cafc29a10af0cbfbd79296ddb316030d04c4207039a393e564adbd7b26a
expected_sha256=abfe6cafc29a10af0cbfbd79296ddb316030d04c4207039a393e564adbd7b26a
ota_report http_status=202 ok=1
cloud ota_reports id=7 stage=partition_write ok=1
```

002 voice-chain evidence:

```text
session_id=a74bc5a9-8a20-4324-be79-3c92d5af9e81
question_text=什么是金刚经？
pipeline result=ok
underrun_count=0
```

Current production P3b release:

```text
release_id=2026-05-18-v32-002-p3b
artifact=esp_idf_demo_v32_p3b_20260518.bin
bytes=226432
sha256=abfe6cafc29a10af0cbfbd79296ddb316030d04c4207039a393e564adbd7b26a
whitelist=miaoban-v1p2-002 only at release creation time
```

Do not reuse this P3b release for P3c. Any P3c release must be created only after explicit P3c authorization and review.

### Task 1: P3b Static Contract Tests

**Files:**
- Modify: `tests/test_esp_assets.py`

- [ ] **Step 1: Add a P3b ESP asset test**

Assert that the firmware contains `esp_ota_get_running_partition`, `esp_ota_get_next_update_partition`, `esp_ota_begin`, `esp_ota_write`, `esp_ota_end`, `esp_ota_abort`, `stage=ota_partition_write event=start`, `stage=ota_partition_write event=done`, `stage=ota_partition_write event=failed`, `action=write_inactive_only`, `no_boot_switch=1`, `no_reboot=1`, `running_partition`, `update_partition`, and `report_stage=partition_write`.

- [ ] **Step 2: Keep P3b forbidden API assertions**

Assert that combined firmware source does not contain `esp_ota_set_boot_partition`, `esp_restart`, `esp_ota_mark_app_valid_cancel_rollback`, or `esp_ota_mark_app_invalid_rollback_and_reboot`.

- [ ] **Step 3: Run focused test and verify RED**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_esp_assets.py
```

Expected before implementation: fail because P3b partition-write symbols and logs do not exist.

### Task 2: OTA Report Payload Tests

**Files:**
- Modify: `tests/test_ota_api.py`
- Modify: `src/api/ota.py`

- [ ] **Step 1: Extend report test**

Add `partition_label`, `partition_subtype`, `partition_address`, `bytes_written`, `expected_size`, `sha256`, and `expected_sha256` to the submitted report and assert each value appears in `payload_json`.

- [ ] **Step 2: Run focused API test and verify RED**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_api.py
```

Expected before implementation: fail because `OtaReportRequest` does not accept the new partition-write fields.

- [ ] **Step 3: Extend local API schema**

Add optional fields to `OtaReportRequest` in `src/api/ota.py`. Keep storage unchanged because `record_ota_report()` already stores the full payload JSON.

### Task 3: Shared Artifact Stream

**Files:**
- Modify: `esp_idf_demo/main/cloud_client.h`
- Modify: `esp_idf_demo/main/cloud_client.c`

- [ ] **Step 1: Add callback types and result fields**

Add a chunk callback typedef and extend `cloud_ota_artifact_verify_t` with `bytes_written`, partition label/subtype/address, and expected SHA fields.

- [ ] **Step 2: Refactor P3a verifier onto shared stream**

Move the existing HTTP/SHA256 loop into a helper that accepts an optional chunk callback. `cloud_client_verify_ota_artifact()` calls the helper with no callback and keeps P3a behavior.

- [ ] **Step 3: Expose a P3b stream function**

Expose `cloud_client_stream_ota_artifact()` so `main.c` can pass an OTA write callback while still using the same HTTP/SHA256 and byte-count validation.

### Task 4: Inactive Partition Write Orchestration

**Files:**
- Modify: `esp_idf_demo/main/main.c`
- Modify: `esp_idf_demo/main/config.h`

- [ ] **Step 1: Include ESP-IDF OTA APIs**

Include `esp_ota_ops.h` in `main.c`. Add a compile-time P3b marker such as `DEMO_OTA_PARTITION_WRITE_ENABLED` in `config.h`, defaulting to enabled for v32 P3b.

- [ ] **Step 2: Validate manifest fields**

Add a helper that rejects missing `url`, non-positive `size`, missing `sha256`, missing `release_id`, or missing `target` before opening an OTA handle.

- [ ] **Step 3: Implement write context and chunk callback**

Create a small context struct carrying `esp_ota_handle_t`, `bytes_written`, and begin state. The callback calls `esp_ota_write()` and increments `bytes_written` only after success.

- [ ] **Step 4: Implement partition write helper**

In the helper, get running/update partitions, reject null or identical partitions, call `esp_ota_begin(update, expected_size, &handle)`, stream through `cloud_client_stream_ota_artifact()`, call `esp_ota_end()` on stream success, call `esp_ota_abort()` on failures after begin, and never call boot switch or reboot APIs.

- [ ] **Step 5: Wire P3b into update handling**

Replace the P3a `cloud_client_verify_ota_artifact()` call in `app_ota_manifest_dry_run_task()` with the partition-write helper, update logs to `action=write_inactive_only`, and submit report with `stage="partition_write"`.

### Task 5: Full Verification

**Files:**
- Read: project tree

- [ ] **Step 1: Run full Python tests**

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run ESP-IDF build**

```bash
cd esp_idf_demo
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export IDF_TOOLS_PATH=/data/esp/tools
export IDF_PATH=/data/esp/esp-idf-v5.5.4-full
export IDF_PATH_FORCE=1
. /data/esp/esp-idf-v5.5.4-full/export.sh
timeout 120 idf.py build
```

Expected: `Project build complete`.

- [ ] **Step 3: Run diff whitespace check**

```bash
git diff --check
```

Expected: no output.

### Task 6: v32 Compile-Only Package

**Files:**
- Create: `tmp/esp_compile_only_2026-05-18_v32.tar.gz`

- [ ] **Step 1: Create package**

```bash
tar \
  --exclude='esp_idf_demo/build' \
  --exclude='esp_idf_demo/managed_components' \
  --exclude='esp_idf_demo/**/__pycache__' \
  --exclude='esp_idf_demo/**/*.pyc' \
  -czf tmp/esp_compile_only_2026-05-18_v32.tar.gz \
  esp_idf_demo
```

- [ ] **Step 2: Record evidence**

Run `stat`, `sha256sum`, `tar -tzf | wc -l`, and forbidden-content `rg` checks. Expected: no `.env`, `.env.*`, `.git`, `build/`, `managed_components/`, `tmp/`, `data/`, `indices/`, cache, `__pycache__`, or `.pyc` entries.
