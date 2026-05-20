# V6 Low-Cost 16MB Flash + 8MB PSRAM Baseline

This repository was forked from the v5 realtime opus codebase for the v6 low-cost
board adaptation.

- Source repository path: `/home/hanxiao_zhu_us/GMT/20260508_v5_realtime_opus`
- Source commit: `b3b0bdf46fc3472f2391eaefd17364066301c60e`
- Target board class: ESP32-S3 ESP-VoCat v1.2 compatible, 16MB Flash + 8MB PSRAM
- First implementation stage: add an explicit low-cost build profile without
  changing the default v5 mainline behavior.

## Guardrails

- Do not read, store, or commit `.env`, Wi-Fi passwords, credentials, or secrets.
- Do not change the default P3c/P3d release flow.
- Do not add `miaoban-v1p2-003` to any P3c/P3d whitelist.
- Keep `DEMO_OTA_BOOT_SWITCH_ENABLED` defaulting to `0`.
- Keep `DEMO_OTA_ROLLBACK_VALIDATION_ENABLED` defaulting to `0`.
- Do not claim customer readiness from compile-only or boot-only validation.
