# OTA P3b Partition Write Design

## Goal

OTA P3b moves v31 P3a from download-verify-only to writing the verified artifact stream into the inactive ESP-IDF OTA app partition, while still refusing to switch boot partition or reboot.

P3b is now closed. It must not be interpreted as OTA boot switching. This document records the P3b boundary; P3c was later authorized separately and has since passed the 002 v34 canary.

## Scope

- The board continues polling `/api/v5/ota/manifest` only while idle.
- If `updates[0]` exists, the board validates required manifest fields before any write:
  - `url`
  - `size`
  - `sha256`
  - `release_id`
  - `target`
- The board queries the running app partition with `esp_ota_get_running_partition()`.
- The board queries the next update partition with `esp_ota_get_next_update_partition(NULL)`.
- The board requires the update partition to be non-null and different from the running partition.
- The board streams the artifact once over HTTP, updates SHA256, writes each chunk with `esp_ota_write()`, then calls `esp_ota_end()`.
- The board verifies `bytes_written == expected_size` and computed SHA256 equals `expected_sha256`.
- The board reports `stage=partition_write` to `/api/v5/ota/report`.

## Explicit Non-Goals

P3b must not:

- call `esp_ota_set_boot_partition()`
- call `esp_restart()`
- call rollback or app-valid mutation APIs
- modify `otadata`
- switch the boot partition automatically
- implement any P3c behavior
- deploy cloud code or create production releases
- be reused as a P3c release

If a future P3c release is created, the operator must first confirm it does not reuse the P3b release `2026-05-18-v32-002-p3b`.

## Architecture

`cloud_client.c` keeps ownership of HTTP download and SHA256 streaming. P3a's verifier and P3b's partition writer use the same internal artifact streaming helper so there is not a second HTTP/SHA256 implementation.

`main.c` keeps ownership of ESP-IDF OTA partition decisions because it already orchestrates board state and logs. It validates the manifest fields, discovers running/update partitions, opens the OTA handle, passes a chunk writer callback to the cloud streaming helper, closes or aborts the OTA handle, and submits the report.

`cloud_client.h` extends the OTA report structs with partition-write fields:

- `partition_label`
- `partition_subtype`
- `partition_address`
- `bytes_written`
- `expected_size`
- `sha256`
- `expected_sha256`

`src/api/ota.py` accepts these fields in `OtaReportRequest` and stores them in `payload_json` through the existing `record_ota_report()` path. No schema migration is needed because `payload_json` already stores the full report body.

## Log Contract

When an update is available, P3b logs:

```text
stage=ota_manifest_dry_run event=update_available ... action=write_inactive_only
stage=ota_partition_write event=start ... action=write_inactive_only no_boot_switch=1 no_reboot=1 running_partition=... update_partition=...
stage=ota_partition_write event=done ... action=write_inactive_only no_boot_switch=1 no_reboot=1
```

On failure:

```text
stage=ota_partition_write event=failed ... action=write_inactive_only no_boot_switch=1 no_reboot=1
```

Report logs use:

```text
stage=ota_report event=done report_stage=partition_write ...
stage=ota_report event=failed report_stage=partition_write ...
```

## Failure Handling

- If manifest validation fails, no OTA handle is opened and report uses `ok=false`.
- If `esp_ota_begin()` succeeds and a later step fails, `esp_ota_abort()` is called.
- `esp_ota_end()` is called only after stream reading finishes without earlier errors.
- Report `error_code` uses `esp_err_to_name()` for ESP errors and short fixed strings for validation failures that do not have an `esp_err_t`.
- Report `error_message` is short and traceable.

## Verification

- Static ESP tests allow `esp_ota_begin`, `esp_ota_write`, `esp_ota_end`, and `esp_ota_abort`.
- Static ESP tests continue forbidding `esp_ota_set_boot_partition`, `esp_restart`, rollback mutation, and app-valid mutation APIs.
- Static ESP tests assert partition-write logs and no-boot/no-reboot markers exist.
- API tests assert report payload preserves partition-write fields.
- Full Python tests, `git diff --check`, and ESP-IDF build must pass.
- The delivery artifact is compile-only: `tmp/esp_compile_only_2026-05-18_v32.tar.gz`.

## Closure Evidence

P3a is complete. P3b is complete for the current acceptance scope:

- `miaoban-v1p2-001` remains excluded from OTA and should continue returning `updates=[]`.
- `miaoban-v1p2-002` completed the single-device P3b canary.
- `miaoban-v1p2-003` is user-confirmed as passing by default under the same acceptance scope.

002 P3b canary evidence:

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

Production release used for P3b canary:

```text
release_id=2026-05-18-v32-002-p3b
artifact=esp_idf_demo_v32_p3b_20260518.bin
bytes=226432
sha256=abfe6cafc29a10af0cbfbd79296ddb316030d04c4207039a393e564adbd7b26a
whitelist=miaoban-v1p2-002 only at release creation time
```

greenunion-sh currently has the v32 P3b report schema, including:

- `partition_label`
- `partition_subtype`
- `partition_address`
- `bytes_written`
- `expected_size`
- `sha256`
- `expected_sha256`
