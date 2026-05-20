# 2026-05-20 OTA P3D Closeout

## Scope

P3D validated ESP32-S3 OTA rollback safety on ESP-VoCat v1.2 for device `miaoban-v1p2-002`.

## Incident

Release `2026-05-20-v37-002-p3d` booted into `ota_1` but repeatedly crashed during rollback validation:

- `stage=ota_app_validation event=start`
- `***ERROR*** A stack overflow in task main has been detected.`

Root cause: rollback validation marked the app valid and submitted the `app_validated` OTA report from the ESP-IDF `main` task. The `main` task stack was too small for that synchronous OTA/HTTP reporting path.

## Fix

`v38-p3d-canary` moved rollback app validation and reporting into a dedicated `ota_app_validate` FreeRTOS task with `DEMO_OTA_ROLLBACK_VALIDATION_TASK_STACK_SIZE=8192`.

The ESP app now also has a guard for future work: `app_main` starts a dedicated `app_runtime` task with `DEMO_APP_RUNTIME_TASK_STACK_SIZE=12288` and then calls `vTaskDelete(NULL)`.

## Verification

Device log showed the expected OTA boot and validation sequence:

- `Loaded app from partition at offset 0x320000`
- `stage=ota_post_reboot_confirm event=done release_id=2026-05-20-v38-002-p3d running_partition_after_reboot=ota_1`
- `stage=ota_report event=done report_stage=post_reboot_confirm http_status=202 ok=1`
- `stage=ota_app_validation event=done release_id=2026-05-20-v38-002-p3d running_partition=ota_1`
- `stage=ota_report event=done report_stage=app_validated http_status=202 ok=1`

The post-validation business pipeline also completed:

- `pipeline result=ok`
- `underrun_count=0`

Cloud closeout disabled the single-device release:

- `release_id=2026-05-20-v38-002-p3d`
- `device_id=miaoban-v1p2-002`
- `enabled=0`
- manifest returned `updates: []`

## Follow-Up

Keep realtime audio throughput as a separate task. Logs still show frequent `realtime_audio_enqueue_slow`; this is not part of OTA rollback correctness but can affect playback smoothness under load.
