# OTA P3c Boot Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for implementation, then superpowers:verification-before-completion before delivery. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add OTA P3c boot switch scheduling and reboot behind an independent safety switch, without changing P3a/P3b behavior when the switch is disabled.

**Architecture:** Keep P3b's shared HTTP/SHA256/inactive partition write flow as the prerequisite. Add a P3c-only branch in `main.c` guarded by `DEMO_OTA_BOOT_SWITCH_ENABLED`, persist a minimal pending confirmation record in NVS before reboot, submit `boot_switch_scheduled`, reboot, then submit `post_reboot_confirm` on the next boot. Extend local OTA report payload handling with boot-switch fields.

**Tech Stack:** ESP-IDF C firmware, `esp_ota_ops`, NVS, FastAPI/Pydantic report schema, Python unittest/pytest static contract tests.

---

## Scope

P3c may call `esp_ota_set_boot_partition()` and `esp_restart()` only inside code guarded by `#if DEMO_OTA_BOOT_SWITCH_ENABLED`. Source defaults must keep `DEMO_OTA_BOOT_SWITCH_ENABLED` at `0`, so normal local builds remain P3b write-inactive-only unless explicitly overridden by a controlled v33 canary build.

P3c must not call rollback/app-valid APIs because local sdkconfig has rollback disabled:

```text
# CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not set
# CONFIG_APP_ROLLBACK_ENABLE is not set
```

No deployment, production release creation, `.env` changes, git commit, or hardware action is part of this plan.

## Files

- Modify: `tests/test_esp_assets.py`
- Modify: `tests/test_ota_api.py`
- Modify: `esp_idf_demo/main/config.h`
- Modify: `esp_idf_demo/main/cloud_client.h`
- Modify: `esp_idf_demo/main/cloud_client.c`
- Modify: `esp_idf_demo/main/main.c`
- Modify: `src/api/ota.py`
- Create: `tmp/esp_compile_only_2026-05-18_v33.tar.gz`

## Tasks

### Task 1: Static Contract Tests

- [x] Add tests proving P3a `download_verify_only` and P3b `write_inactive_only` still exist.
- [x] Add tests proving `DEMO_OTA_BOOT_SWITCH_ENABLED` defaults to `0`.
- [x] Add tests proving `esp_ota_set_boot_partition` and `esp_restart` appear only inside the P3c-gated source path.
- [x] Add tests for P3c logs: `action=write_switch_reboot`, `no_boot_switch=0`, `reboot_scheduled=1`, `boot_partition_before`, `boot_partition_after_set`, `stage=ota_boot_switch event=start/done/failed`, `report_stage=boot_switch_scheduled`, `stage=ota_post_reboot_confirm`, and `report_stage=post_reboot_confirm`.
- [x] Keep rollback/app-valid APIs forbidden.

### Task 2: API Report Tests

- [x] Extend `tests/test_ota_api.py` report test to include `boot_partition_before`, `boot_partition_after_set`, `running_partition_after_reboot`, and `reboot_reason`.
- [x] Verify the test fails before schema extension.

### Task 3: Report Schema And Serialization

- [x] Extend `OtaReportRequest` in `src/api/ota.py` with P3c report fields.
- [x] Extend `cloud_ota_artifact_verify_t` or the report envelope with boot-switch/post-reboot fields.
- [x] Serialize those fields in `cloud_client_submit_ota_report()`.

### Task 4: P3c Firmware Flow

- [x] Add `DEMO_OTA_BOOT_SWITCH_ENABLED`, default `0`, and print it in runtime config.
- [x] Add pending confirmation NVS helpers for release id, target version, expected partition label/address, expected SHA256, and scheduled flag.
- [x] On startup, check pending confirmation and report `post_reboot_confirm`.
- [x] After P3b write success, if P3c is enabled, call `esp_ota_set_boot_partition(update_partition)`.
- [x] Confirm `esp_ota_get_boot_partition()` matches the update partition.
- [x] Report `boot_switch_scheduled`; warning-only if report fails.
- [x] Call `esp_restart()` only after local boot switch success.
- [x] If boot switch fails or confirmation mismatches, do not reboot and report `ok=false`.

### Task 5: Verification And Package

- [x] Run full pytest.
- [x] Run `git diff --check`.
- [x] Run rollback forbidden API scan.
- [x] Run ESP-IDF build.
- [x] Create v33 compile-only package.
- [x] Record package bytes, sha256, file count, and forbidden-entry scan result.

### Task 6: P3c Canary Closure

- [x] Validate 002 v34 P3c canary on hardware.
- [x] Confirm OTA partition boot with `App version=v34-p3c-canary`.
- [x] Confirm Wi-Fi/server/device_id runtime configuration is present after reboot.
- [x] Confirm `post_reboot_confirm ok=1`.
- [x] Record v33 issue: OTA target bin lacked runtime configuration.
- [x] Record v34 issue: server suppress fix required API image rebuild/recreate, not just source copy or restart.
- [x] Add server-side tests proving `boot_switch_scheduled ok=1` and `post_reboot_confirm ok=1` suppress only the same `device_id + release_id`.
- [x] Document that manual whitelist removal was a stopgap, not the standard P3c completion mechanism.

Current closeout recommendation: keep automatic suppress as the anti-repeat mechanism, then set the canary release `enabled=0` after validation to avoid accidental whitelist expansion or release reuse.
