# OTA P3c Boot Switch Design

## Goal

OTA P3c adds the first explicit boot switch flow after P3b has already proven that a verified artifact can be written into the inactive ESP-IDF OTA app partition.

P3c is intentionally separate from P3b. P3b remains write-inactive-only. P3c is the first phase that may call `esp_ota_set_boot_partition()` and `esp_restart()`, and it must only run when a new P3c-specific safety switch is enabled.

## Current Baseline

- P3a is complete.
- P3b is closed: it writes the inactive OTA partition, reports `stage=partition_write`, does not switch boot partition, and does not reboot.
- The P3b production release `2026-05-18-v32-002-p3b` must not be reused or edited into a P3c release.
- P3c must use a new release id, a new artifact, and a new version such as `v33`.
- `miaoban-v1p2-001` remains excluded from OTA.
- `miaoban-v1p2-002` is the first P3c canary.
- `miaoban-v1p2-003` is not included by default for P3c.

## Rollback Configuration

Current local `esp_idf_demo/sdkconfig` shows:

```text
# CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not set
# CONFIG_APP_ROLLBACK_ENABLE is not set
```

With rollback disabled, P3c must not call:

- `esp_ota_mark_app_valid_cancel_rollback()`
- `esp_ota_mark_app_invalid_rollback_and_reboot()`

If rollback is enabled in a later build, the design must be revised before implementation. In that revised design, the post-reboot path must call `esp_ota_mark_app_valid_cancel_rollback()` only after the board confirms it booted the expected new partition and the minimal health checks have passed. No rollback mutation is part of the current P3c design because rollback is not enabled.

## Safety Switches

P3c must introduce a separate compile-time switch:

```c
#ifndef DEMO_OTA_BOOT_SWITCH_ENABLED
#define DEMO_OTA_BOOT_SWITCH_ENABLED 0
#endif
```

The switches have separate meanings:

- `DEMO_OTA_MANIFEST_DRY_RUN_ENABLED`: allows idle manifest polling.
- `DEMO_OTA_PARTITION_WRITE_ENABLED`: allows P3b-style inactive partition writes.
- `DEMO_OTA_BOOT_SWITCH_ENABLED`: allows P3c boot switch and reboot after a successful write.

`DEMO_OTA_BOOT_SWITCH_ENABLED` must default to `0` in source so a P3b build cannot accidentally become P3c. A v33 P3c canary build may override it explicitly to `1` through the controlled build/package process.

## State Machine

### First Boot Before Switch

1. Idle board polls `/api/v5/ota/manifest`.
2. Manifest returns `updates[0]` for `miaoban-v1p2-002`.
3. Board validates required manifest fields before opening an OTA handle:
   - `url`
   - `size`
   - `sha256`
   - `release_id`
   - `target`
4. Board queries:
   - `running = esp_ota_get_running_partition()`
   - `update = esp_ota_get_next_update_partition(NULL)`
   - `boot_before = esp_ota_get_boot_partition()`
5. Board requires `update != running` and `update->address != running->address`.
6. Board logs `action=write_switch_reboot`.
7. Board writes the artifact to the inactive partition through the existing P3b stream path:
   - `esp_ota_begin(update, expected_size, &handle)`
   - HTTP stream read
   - SHA256 update
   - `esp_ota_write(handle, chunk, len)`
   - `esp_ota_end(handle)`
8. Board verifies:
   - `bytes_read == expected_size`
   - `bytes_written == expected_size`
   - `sha256 == expected_sha256`
9. Board reports `stage=partition_write`.
10. If partition write report fails, the board logs the report failure but may continue to boot switch only if the local write and verification succeeded. The report failure must be visible in logs.
11. Board calls `esp_ota_set_boot_partition(update)`.
12. Board queries `boot_after_set = esp_ota_get_boot_partition()` and requires it matches `update`.
13. Board reports `stage=boot_switch_scheduled`.
14. Board logs `reboot_scheduled=1`.
15. Board calls `esp_restart()`.

### Reboot Confirmation

On the next boot:

1. Board reads:
   - `running_after = esp_ota_get_running_partition()`
   - `boot_after = esp_ota_get_boot_partition()`
   - reset reason from `esp_reset_reason()`
2. Board confirms `running_after` matches the previously scheduled update partition.
3. Board reports `stage=post_reboot_confirm`.
4. With rollback disabled, no app-valid API is called.
5. If rollback is enabled in a later build, this is the only point where `esp_ota_mark_app_valid_cancel_rollback()` may be considered, and only after health checks pass.

## Log Contract

When P3c is enabled and an update is available:

```text
stage=ota_manifest_dry_run event=update_available ... action=write_switch_reboot
stage=ota_partition_write event=start ... action=write_switch_reboot running_partition=... update_partition=... boot_partition_before=... no_boot_switch=0 reboot_scheduled=0
stage=ota_partition_write event=done ... action=write_switch_reboot running_partition=... update_partition=... boot_partition_before=... no_boot_switch=0 reboot_scheduled=0
stage=ota_report event=done report_stage=partition_write ...
stage=ota_boot_switch event=start ... running_partition=... update_partition=... boot_partition_before=... action=write_switch_reboot no_boot_switch=0
stage=ota_boot_switch event=done ... boot_partition_after_set=... reboot_scheduled=1
stage=ota_report event=done report_stage=boot_switch_scheduled ...
stage=ota_reboot event=scheduled release_id=... update_partition=... reboot_scheduled=1
```

After reboot:

```text
stage=ota_post_reboot_confirm event=start release_id=... running_partition_after_reboot=... reboot_reason=...
stage=ota_post_reboot_confirm event=done release_id=... running_partition_after_reboot=...
stage=ota_report event=done report_stage=post_reboot_confirm ...
```

Required fields in P3c logs:

- `action=write_switch_reboot`
- `running_partition`
- `update_partition`
- `boot_partition_before`
- `boot_partition_after_set`
- `no_boot_switch=0`
- `reboot_scheduled=1`

## Report Contract

The existing `/api/v5/ota/report` path should be extended locally before any deployment. Reports must preserve the P3b fields and add boot-switch fields.

Required report fields for `partition_write`:

- `partition_label`
- `partition_subtype`
- `partition_address`
- `bytes_written`
- `expected_size`
- `sha256`
- `expected_sha256`

Additional report fields for P3c:

- `boot_partition_before`
- `boot_partition_after_set`
- `running_partition_after_reboot`
- `reboot_reason`

Report stages:

- `partition_write`: local write and verification result before boot switch.
- `boot_switch_scheduled`: result of setting the next boot partition.
- `post_reboot_confirm`: result after reboot when the board verifies the running partition changed.

## Failure Handling

### Download Failure

- Abort the OTA handle if `esp_ota_begin()` already succeeded.
- Do not call `esp_ota_set_boot_partition()`.
- Do not reboot.
- Report `stage=partition_write`, `ok=false`.
- Use HTTP status and byte counters in logs and report.

### Size or SHA256 Mismatch

- Treat as a write/verification failure.
- Abort the OTA handle if still open.
- Do not switch boot partition.
- Do not reboot.
- Report `stage=partition_write`, `ok=false`, `error_code=bytes_written_mismatch`, `bytes_read_mismatch`, or `sha256_mismatch`.

### `esp_ota_begin`, `esp_ota_write`, or `esp_ota_end` Failure

- If `esp_ota_begin()` succeeded and a later step fails, call `esp_ota_abort()`.
- Do not call `esp_ota_set_boot_partition()`.
- Do not reboot.
- Report `stage=partition_write`, `ok=false`, with `error_code=esp_err_to_name(ret)`.

### `esp_ota_set_boot_partition` Failure

- The artifact may remain written to the inactive partition, but the boot partition was not switched.
- Do not reboot.
- Report `stage=boot_switch_scheduled`, `ok=false`.
- Log `boot_partition_before` and the failed update partition.

### Boot Partition Confirmation Failure

- After `esp_ota_set_boot_partition(update)`, read `esp_ota_get_boot_partition()`.
- If the returned partition is null or does not match `update`, do not reboot.
- Report `stage=boot_switch_scheduled`, `ok=false`, `error_code=boot_partition_after_set_mismatch`.

### Report Failure

- If `partition_write` report fails after local write verification succeeds, P3c may continue to boot switch because the local state is authoritative. The log must show `stage=ota_report event=failed report_stage=partition_write`.
- If `boot_switch_scheduled` report fails after `esp_ota_set_boot_partition()` succeeds, reboot may continue because the device has already scheduled the new partition. The log must show the report failure before reboot.
- If `post_reboot_confirm` report fails, the board must log failure and retry on the next allowed idle poll only if the implementation persists enough pending confirmation state.

### Reboot Confirmation Failure

- If `running_partition_after_reboot` does not match the scheduled update partition, report `stage=post_reboot_confirm`, `ok=false`, `error_code=running_partition_after_reboot_mismatch`.
- Do not call rollback mutation APIs in the current build because rollback is disabled.
- Do not create another boot switch attempt without a new manifest/release decision.

## Persistence Requirement

P3c needs minimal local pending state so the rebooted firmware can report `post_reboot_confirm`. The state should include:

- `release_id`
- `target version`
- expected partition label/address
- expected artifact `sha256`
- whether boot switch was scheduled

Recommended storage is NVS under a small OTA namespace because SPIFFS assets are unrelated and the state must survive reboot. The state should be cleared only after `post_reboot_confirm` succeeds or after a terminal mismatch is reported.

## Production Operation Boundary

- Do not deploy greenunion-sh during local design or development unless separately authorized.
- Do not create a production release during local design or development.
- P3c production release must use a new release id, new artifact, and version `v33` or later.
- The first P3c release must be `miaoban-v1p2-002` only.
- `miaoban-v1p2-001` must never be added to the P3c whitelist.
- `miaoban-v1p2-003` must not be added by default.
- The P3b release `2026-05-18-v32-002-p3b` must not be reused or edited for P3c.

## P3c Canary Closure

The 002 v34 P3c canary passed:

- Device: `miaoban-v1p2-002`
- App version after OTA boot: `v34-p3c-canary`
- Result: device booted from the OTA partition, runtime Wi-Fi/server/device_id configuration was present, and `post_reboot_confirm ok=1` was reported.

Two issues were found and closed during the canary:

- v33 OTA target bin lacked runtime configuration, so the device booted into the OTA partition with empty `wifi_ssid`, `server_base_url`, and `device_id`.
- v34 initially repeated the same release because the server-side suppress fix had been copied to host source but the API image had not been rebuilt. On greenunion-sh, backend `src/` changes require `docker compose build api && docker compose up -d api`; a simple restart does not load new image code.

Long-term manifest behavior must not depend on manually removing the device from a whitelist. For the same `device_id + release_id`, manifest must suppress a release after either `boot_switch_scheduled ok=1` or `post_reboot_confirm ok=1`. The suppress check must not affect other release ids, other devices, or failed reports. After a canary passes, operators should still set the canary release `enabled=0` as a closeout guard against accidental whitelist expansion or release reuse.

## Files Expected To Change During Implementation

- `esp_idf_demo/main/config.h`
  - Add `DEMO_OTA_BOOT_SWITCH_ENABLED`, default `0`.
- `esp_idf_demo/main/cloud_client.h`
  - Extend report structs with boot-switch and post-reboot fields.
- `esp_idf_demo/main/cloud_client.c`
  - Serialize new report fields to `/api/v5/ota/report`.
- `esp_idf_demo/main/main.c`
  - Add P3c branch gated by `DEMO_OTA_BOOT_SWITCH_ENABLED`.
  - Call `esp_ota_set_boot_partition()` and `esp_restart()` only in that branch.
  - Add post-reboot confirmation and pending-state handling.
- `src/api/ota.py`
  - Accept boot-switch report fields locally.
- `tests/test_esp_assets.py`
  - Add P3c static contract tests that require the boot-switch APIs only when guarded by the P3c switch.
  - Keep P3b tests proving P3b does not imply boot switch.
- `tests/test_ota_api.py`
  - Assert boot-switch report fields are accepted and persisted in `payload_json`.
- Optional new docs:
  - `docs/superpowers/plans/2026-05-18-ota-p3c-boot-switch.md`
  - `docs/deploy/greenunion-sh-ota-p3c-runbook.md`

## Verification Plan For Implementation

Before any hardware or production operation:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q
git diff --check
```

ESP build:

```bash
cd esp_idf_demo
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export IDF_TOOLS_PATH=/data/esp/tools
export IDF_PATH=/data/esp/esp-idf-v5.5.4-full
export IDF_PATH_FORCE=1
. /data/esp/esp-idf-v5.5.4-full/export.sh
timeout 120 idf.py build
```

Static scan must show:

- P3c source contains `DEMO_OTA_BOOT_SWITCH_ENABLED`.
- `esp_ota_set_boot_partition` and `esp_restart` are only used in the P3c-gated branch.
- Current rollback-disabled build does not call `esp_ota_mark_app_valid_cancel_rollback` or `esp_ota_mark_app_invalid_rollback_and_reboot`.

## Recommendation

Proceed to implementation only after this design is reviewed. The recommended implementation order is:

1. Add tests for P3c switch isolation, boot-switch logs, report fields, and rollback-disabled behavior.
2. Extend report structs/API schema.
3. Add pending NVS state for post-reboot confirmation.
4. Add the P3c-gated boot switch and reboot path.
5. Build v33 compile-only package for review.

No P3c production release should be created until local tests, ESP build, and a separate release runbook are reviewed.
