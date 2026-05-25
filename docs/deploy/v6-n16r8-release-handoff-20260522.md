# V6 N16R8 Release Handoff - 2026-05-22

## Scope

This handoff covers the ESP32-S3 16MB Flash + 8MB PSRAM v6 N16R8 canary flow for
the three current samples:

- `miaoban-v1p2-002`: OTA canary only.
- `miaoban-v1p2-003`: powered sample, must remain blocked until 002 passes.
- `miaoban-v1p2-004`: powered sample, must remain blocked until 002 passes.

The active hardware binding is ESP-VoCat V1.0 audio routing:

- I2S DIN/DSIN: `GPIO15`
- PA enable: `GPIO4`
- GPIO48 speaker/mic enable: disabled

V1.2 audio routing is deprecated for this N16R8 sample line.

## Current Release State

- Repo: `/mnt/data100/GMT/20260521_16flash_8psram`
- Source commit: `9f086ac2b6807e3a2bbc714e275b65553e2cdb53`
- Baseline package:
  `/mnt/data100/GMT/20260521_16flash_8psram/tmp/esp_flash_v6_n16r8_002_ota_baseline_20260522.tar.gz`
- Baseline app version: `v6-n16r8-002-ota-baseline`
- Active canary release id: `2026-05-22-v6-n16r8-004-002-p3d`
- Active canary app version: `v6-n16r8-004-ota-canary`
- Active canary artifact:
  `esp_idf_demo_v6_n16r8_004_ota_canary_002_20260522.bin`
- Active canary SHA256:
  `20910a48f358691291547d14e98a1db56426c35c8f7ea5f4161b9cd9f0340b04`
- Active canary size: `1254784` bytes
- OTA slot size: `3145728` bytes
- Server: `106.54.240.51`
- Docker API container: `religion_demo_v5_realtime_opus-api-1`
- Artifact directory in container: `/app/data/ota_artifacts`
- Artifact directory on host:
  `/app/religion_demo_v5_realtime_opus/data/ota_artifacts`

The prior release `2026-05-22-v6-n16r8-003-002-p3d` was disabled after it booted
with empty `wifi_ssid` and `server_base_url` in the OTA image.

## Non-Negotiable Guardrails

- Do not read, print, or modify `.env`, Wi-Fi passwords, credentials, or secrets.
- Do not add `miaoban-v1p2-003` or `miaoban-v1p2-004` to this release.
- Do not enable a release until artifact SHA, size, and manifest targeting pass.
- Do not treat compile-only, boot-only, or one successful prompt playback as
  customer readiness.
- Do not modify the old P3c/P3d flow while handling this v6 N16R8 canary.
- Do not change `esp_idf_demo/partitions.csv` for this flow.
- Keep source defaults safe: `DEMO_OTA_BOOT_SWITCH_ENABLED=0` and
  `DEMO_OTA_ROLLBACK_VALIDATION_ENABLED=0`. Only temporary canary builds may turn
  them on.

## Required Runtime Markers

The canary must show these boot/runtime markers before it can be promoted:

```text
App version:      v6-n16r8-004-ota-canary
Board: ESP-VoCat v1.0
target_profile=vocat_lowcost_16m8m
audio_pcb_rev=v1.0
audio_i2s_din_gpio=15
audio_pa_gpio=4
audio_gpio48_enable=0
wifi_ssid=GMT-G60
server_base_url=http://106.54.240.51
ota_boot_switch_enabled=1
ota_rollback_validation_enabled=1
stage=ota_post_reboot_confirm event=success
```

These markers are blockers if present:

```text
DEMO_WIFI_SSID is empty
wifi_ssid=
server_base_url=
audio_pcb_rev=v1.2
audio_i2s_din_gpio=3
audio_pa_gpio=15
audio_gpio48_enable=1
stage=ota_post_reboot_confirm event=failed
stage=ota_rollback event=recovered
```

## Automated Gate

Use the v6 release gate before and after enabling OTA:

```bash
python3 scripts/v6_n16r8_release_gate.py \
  --artifact tmp/esp_idf_demo_v6_n16r8_004_ota_canary_002_20260522.bin \
  --expected-sha256 20910a48f358691291547d14e98a1db56426c35c8f7ea5f4161b9cd9f0340b04 \
  --expected-version v6-n16r8-004-ota-canary \
  --expected-release-id 2026-05-22-v6-n16r8-004-002-p3d \
  --manifest-base-url http://106.54.240.51
```

Expected output includes:

```text
PASS: v6 N16R8 release gate
manifest_allowed_update=miaoban-v1p2-002
manifest_blocked=miaoban-v1p2-003
manifest_blocked=miaoban-v1p2-004
```

After 002 has already polled and reported `boot_switch_scheduled` or
`post_reboot_confirm`, the server suppresses the same release for that device.
Use the post-pickup manifest mode:

```bash
python3 scripts/v6_n16r8_release_gate.py \
  --artifact tmp/esp_idf_demo_v6_n16r8_004_ota_canary_002_20260522.bin \
  --expected-sha256 20910a48f358691291547d14e98a1db56426c35c8f7ea5f4161b9cd9f0340b04 \
  --expected-version v6-n16r8-004-ota-canary \
  --expected-release-id 2026-05-22-v6-n16r8-004-002-p3d \
  --manifest-base-url http://106.54.240.51 \
  --allowed-device-mode no-update
```

After hardware provides a boot log:

```bash
python3 scripts/v6_n16r8_release_gate.py \
  --log /path/to/002-v6-n16r8-004-boot.log \
  --expected-version v6-n16r8-004-ota-canary \
  --require-ota-success
```

## Release Procedure

1. Build the canary app from a temporary source copy, not by editing checked-in
   defaults. Inject only the canary runtime values into the temp copy:
   `DEMO_WIFI_SSID`, `DEMO_SERVER_BASE_URL`, `DEMO_DEVICE_ID`,
   `DEMO_OTA_BOOT_SWITCH_ENABLED=1`,
   `DEMO_OTA_ROLLBACK_VALIDATION_ENABLED=1`, and
   `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`.
2. Confirm build config:
   `CONFIG_DEMO_TARGET_PROFILE_VOCAT_LOWCOST_16M8M=1`,
   `CONFIG_DEMO_AUDIO_PCB_ESP_VOCAT_V1_0=1`, and rollback bootloader enabled.
3. Confirm artifact size is below `3145728` bytes and record SHA256.
4. Upload the artifact to the server artifact directory.
5. Create the release with exactly one device id: `miaoban-v1p2-002`.
6. Run manifest gate and confirm 003/004 still return `updates: []`.
7. Wait for 002 to boot the OTA slot and collect a complete serial log.
8. Run the log gate with `--require-ota-success`.
9. Only after 3-5 clean realtime runs on 002 should 003 be considered for a
   separate release. 004 remains blocked until 003 passes.

## Hardware Acceptance Checklist

- OTA downloads and boots from `ota_1`.
- Post-reboot confirmation succeeds and no rollback recovery appears.
- Prompt playback is audible.
- Speech detection fires with non-trivial `max_level`.
- V5 opus uplink reaches `question_text=... error_code=(none)`.
- Realtime audio stream returns `http_status=200`.
- `realtime_audio_summary` appears.
- `underrun_count` is acceptable for the test network and there is no crash.
- Heap and SPIRAM largest-block metrics remain stable after cleanup.

## Rollback Instructions

If the canary logs empty network config, V1.2 audio routing, post-reboot confirm
failure, or repeated websocket failures from a stable network:

1. Disable the active release on the server.
2. Verify 002/003/004 manifests return `updates: []` from the baseline version.
3. Keep the device on baseline `v6-n16r8-002-ota-baseline`.
4. Build a new release id. Do not reuse the failed release id or version string.
