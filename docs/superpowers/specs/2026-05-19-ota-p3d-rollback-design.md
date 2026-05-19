# OTA P3d Rollback Design

## Goal

P3d turns the P3c boot-switch flow into a customer-safe OTA flow for `miaoban-v1p2-002` by enabling ESP-IDF OTA rollback and marking the new app valid only after the board proves that the new firmware is actually usable.

P3c already proved write, boot switch, post-reboot confirmation, suppress, and closeout. P3d adds the missing safety property: if the new firmware starts but cannot finish the required health path, the next reset must return the board to the previous app partition.

## Scope

P3d is for `miaoban-v1p2-002` first. It does not include `miaoban-v1p2-003`.

The implementation must not reuse the completed v35 release:

- Completed release: `2026-05-19-v35-002-p3c`
- P3d must use a new release id, artifact, and version, for example `2026-05-19-v36-002-p3d` and `v36-p3d-canary`.

## Baseline

Current P3c source has:

- `DEMO_OTA_BOOT_SWITCH_ENABLED` defaulting to `0`.
- A dedicated `app_ota_post_reboot_confirm_task`.
- Persistent pending state in the `ota_p3c` NVS namespace.
- Post-reboot confirmation after Wi-Fi connects.
- No calls to:
  - `esp_ota_mark_app_valid_cancel_rollback()`
  - `esp_ota_mark_app_invalid_rollback_and_reboot()`

P3d must preserve the P3c path and add rollback validation behind a separate compile-time switch.

## Configuration

Add a separate source-default-off switch:

```c
#ifndef DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 0
#endif
```

P3d artifacts must explicitly build with:

```text
DEMO_OTA_BOOT_SWITCH_ENABLED=1
DEMO_OTA_ROLLBACK_VALIDATION_ENABLED=1
CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y
CONFIG_APP_ROLLBACK_ENABLE=y
```

The repository default must remain safe for normal compile-only builds:

- `DEMO_OTA_BOOT_SWITCH_ENABLED=0`
- `DEMO_OTA_ROLLBACK_VALIDATION_ENABLED=0`

## Validation Boundary

`post_reboot_confirm` is not enough to mark the app valid.

P3d may report `post_reboot_confirm ok=1` after Wi-Fi works and the board confirms it booted the expected partition. The app must still remain unvalidated until the board completes the local business-health gate.

The minimum business-health gate is:

1. Wi-Fi connected.
2. Pending P3d partition matches the running partition.
3. `post_reboot_confirm ok=1` report is accepted by the cloud.
4. Touch trigger initialization succeeds.
5. The app reaches normal idle state after initialization.

Only after all five conditions pass may the firmware call:

```c
esp_ota_mark_app_valid_cancel_rollback()
```

If any condition fails, the firmware must not mark the app valid.

## Critical Edge Case

The key customer-safety scenario is:

1. New firmware boots.
2. Wi-Fi connects.
3. `post_reboot_confirm ok=1` is reported.
4. A later business initialization step hangs, for example audio or trigger initialization blocks forever.
5. `app_validated` is never reported.
6. `esp_ota_mark_app_valid_cancel_rollback()` is never called.
7. A watchdog or business-layer timeout resets the board.
8. ESP-IDF bootloader rollback returns the device to the previous valid app partition.

This scenario must be represented in tests or static guards. P3d is not complete if a code path can mark valid immediately after `post_reboot_confirm` without proving that business initialization reached idle.

The implementation must also make the reset source visible in logs and reports after rollback so an operator can distinguish a successful app validation from a rollback recovery.

## Watchdog Requirement

Rollback only helps if a stuck new firmware eventually resets. P3d must explicitly verify one of these reset paths before customer handoff:

- Existing task watchdog covers the business initialization task that can hang.
- A new rollback-validation timeout task triggers `esp_restart()` if validation has not completed within the configured window.

The preferred first implementation is a small timeout task because it is deterministic and easier to test:

```c
#ifndef DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS
#define DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS 30000
#endif
```

The timeout starts only when rollback validation is pending on a freshly booted OTA app. If app validation completes, the timeout task exits. If validation remains pending past the timeout, it logs `stage=ota_app_validation event=timeout` and restarts the board without marking the app valid.

## Report Contract

Add a report stage:

```text
app_validated
```

When validation succeeds:

```text
stage=ota_app_validation event=start release_id=...
stage=ota_app_validation event=done release_id=... running_partition=... rollback_state=...
stage=ota_report event=done report_stage=app_validated http_status=202 ok=1 release_id=...
```

If `esp_ota_mark_app_valid_cancel_rollback()` fails:

```text
stage=ota_app_validation event=failed release_id=... error_code=...
stage=ota_report event=done report_stage=app_validated http_status=202 ok=0 release_id=...
```

If validation times out before business initialization reaches idle:

```text
stage=ota_app_validation event=timeout release_id=... timeout_ms=...
```

The timeout path must not report `app_validated ok=1`.

## Closeout Rule

P3d closeout must require all four successful stages for the same `device_id + release_id`:

- `partition_write`
- `boot_switch_scheduled`
- `post_reboot_confirm`
- `app_validated`

`post_reboot_confirm` alone must not close out a P3d release.

P3c closeout can keep the three-stage rule for completed P3c releases. P3d should either add a P3d-specific closeout mode or infer the required stages from the release/version notes without weakening P3c behavior.

## Suppress Rule

Manifest suppress for the same `device_id + release_id` may still suppress after `boot_switch_scheduled` or `post_reboot_confirm`, because repeated re-delivery of the same release during validation is unsafe and unnecessary.

This suppress behavior does not replace closeout. Closeout is still blocked until `app_validated ok=1`.

## Failure Handling

### Running Partition Mismatch

If the rebooted partition does not match the pending OTA partition:

- Report `post_reboot_confirm ok=0`.
- Do not mark valid.
- Do not report `app_validated ok=1`.
- Clear or retain pending state only according to the implementation plan; the chosen behavior must avoid repeated false positives.

### Cloud Report Failure

If `post_reboot_confirm` cannot be reported:

- Do not mark valid.
- Keep pending state so the board can retry on a later boot or idle window.
- Let the validation timeout reset the board if confirmation never succeeds.

### Business Initialization Failure

If trigger/audio/business initialization fails synchronously:

- Log the failure.
- Do not mark valid.
- Allow timeout or watchdog reset to roll back.

### Business Initialization Hang

If trigger/audio/business initialization hangs:

- `app_validated` is never reported.
- The rollback validation timeout or watchdog must reset the board.
- The new app remains pending verification and must roll back on the next boot.

## Tests

Required static or unit coverage:

- `DEMO_OTA_ROLLBACK_VALIDATION_ENABLED` defaults to `0`.
- Rollback validation code only calls `esp_ota_mark_app_valid_cancel_rollback()` after `post_reboot_confirm` report success and business initialization reaches idle.
- No code calls `esp_ota_mark_app_invalid_rollback_and_reboot()` in the first P3d implementation.
- Closeout for P3d requires `app_validated ok=1`.
- `post_reboot_confirm ok=1` without `app_validated ok=1` is not enough for P3d closeout.
- The business-initialization-hang edge case is represented: Wi-Fi and `post_reboot_confirm` can succeed while `app_validated` is absent, and the expected outcome is no mark-valid call plus timeout/watchdog reset.

Required manual 002 validation:

1. Build P3d artifact with rollback enabled.
2. Create disabled P3d release for `miaoban-v1p2-002` only.
3. Verify 001 has `updates=[]`.
4. Verify 002 receives the update only after explicit enable.
5. Confirm logs for `partition_write`, `boot_switch_scheduled`, `post_reboot_confirm`, and `app_validated`.
6. Confirm closeout disables the release only after all four stages.
7. Confirm 002 manifest returns `updates=[]` after closeout.
8. Fault-inject the business-initialization-hang case or an equivalent validation timeout and confirm the old valid partition is restored after reset.

## Non-Goals

- No rollout to `miaoban-v1p2-003`.
- No customer release before the rollback path is validated on 002.
- No password-bearing artifact.
- No reuse of v35 P3c release or artifact.
