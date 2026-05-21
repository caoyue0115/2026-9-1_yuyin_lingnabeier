# V6 Low-Cost 16MB Flash + 8MB PSRAM Baseline

This repository was forked from the v5 realtime opus codebase for the v6 low-cost
board adaptation.

- Source repository path: `/home/hanxiao_zhu_us/GMT/20260508_v5_realtime_opus`
- Source commit: `b3b0bdf46fc3472f2391eaefd17364066301c60e`
- Target board class: ESP32-S3 N16R8 low-cost board using ESP-VoCat V1.0 audio
  PCB routing, 16MB Flash, and 8MB PSRAM.
- First implementation stage: add an explicit low-cost build profile for the
  N16R8 hardware without changing the default v5 mainline behavior.

## Guardrails

- Do not read, store, or commit `.env`, Wi-Fi passwords, credentials, or secrets.
- Do not change the default P3c/P3d release flow.
- Do not add `miaoban-v1p2-003` to any P3c/P3d whitelist.
- Keep `DEMO_OTA_BOOT_SWITCH_ENABLED` defaulting to `0`.
- Keep `DEMO_OTA_ROLLBACK_VALIDATION_ENABLED` defaulting to `0`.
- Do not claim customer readiness from compile-only or boot-only validation.

## Stage 1 Profile

The first implementation stage uses an explicit ESP-IDF defaults profile for
the v6 N16R8 low-cost target:

```bash
SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.vocat_lowcost_16m8m"
idf.py -C esp_idf_demo build
```

This profile targets the ESP-VoCat V1.0 audio PCB binding:

- I2S DIN/DSIN: `GPIO15`
- PA enable: `GPIO4`
- GPIO48 speaker/mic enable: not used (`audio_gpio48_enable=0`)

The board and BSP can still be identified as `ESP-VoCat`, but runtime logs must
make the audio PCB revision explicit as `audio_pcb_rev=v1.0`.

Stage 1 intentionally keeps `esp_idf_demo/partitions.csv` unchanged. Partition
geometry must not be mixed into this hardware-binding fix.

Compile-only validation is not customer readiness. Runtime validation must still
capture free heap, largest SPIRAM block, task stack watermarks, realtime jitter
underruns, audio latency, OTA size, and P3c/P3d safety gates.
