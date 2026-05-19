# greenunion-sh OTA P3b Runbook

## Scope

This runbook records the closed P3b acceptance state on `greenunion-sh`.

P3b means write inactive OTA partition only. It does not mean OTA boot switch is complete. P3b must not call `esp_ota_set_boot_partition`, must not reboot, and must not modify `otadata` to select the new partition.

This runbook records the P3b boundary. P3c was later authorized separately and has since passed the 002 v34 canary. Do not reuse the P3b release for P3c.

## Device Policy

- `miaoban-v1p2-001` does not participate in OTA and remains the no-update reference unit.
- `miaoban-v1p2-002` completed the P3b single-device canary.
- `miaoban-v1p2-003` is user-confirmed as passing by default under the same acceptance scope.

## greenunion-sh Schema

greenunion-sh currently has the v32 P3b report schema. OTA reports can store:

- `partition_label`
- `partition_subtype`
- `partition_address`
- `bytes_written`
- `expected_size`
- `sha256`
- `expected_sha256`

## P3b Canary Evidence

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

Voice-chain evidence from the same device:

```text
session_id=a74bc5a9-8a20-4324-be79-3c92d5af9e81
question_text=什么是金刚经？
pipeline result=ok
underrun_count=0
```

## Production P3b Release

```text
release_id=2026-05-18-v32-002-p3b
artifact=esp_idf_demo_v32_p3b_20260518.bin
bytes=226432
sha256=abfe6cafc29a10af0cbfbd79296ddb316030d04c4207039a393e564adbd7b26a
whitelist=miaoban-v1p2-002 only at release creation time
```

Do not reuse this release for P3c.

## Acceptance Log Markers

Expected P3b markers:

```text
stage=ota_manifest_dry_run event=update_available ... action=write_inactive_only
stage=ota_partition_write event=start ... running_partition=ota_0 update_partition=ota_1 no_boot_switch=1 no_reboot=1
stage=ota_partition_write event=done ... bytes_read=226432 bytes_written=226432 expected_size=226432
stage=ota_report event=done report_stage=partition_write http_status=202 ok=1
```

Forbidden P3b markers:

```text
esp_ota_set_boot_partition
esp_restart
esp_ota_mark_app_valid_cancel_rollback
esp_ota_mark_app_invalid_rollback_and_reboot
```

## Current Hardware Package

```text
tmp/esp_compile_only_2026-05-18_v32.tar.gz
bytes=330475
sha256=a8e865dd922e661f46113ddd2ff9c03399e33b0a3f526b3527c39aa3f7cf44d0
files=28
```
