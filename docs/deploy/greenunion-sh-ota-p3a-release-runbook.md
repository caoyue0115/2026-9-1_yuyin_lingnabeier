# greenunion-sh OTA P3a Release Runbook

## Scope

This runbook is for tomorrow's v31 dual-device OTA P3a joint test on `greenunion-sh`.

It prepares manifest release rows and artifact hosting only. It does not deploy, restart, write ESP32 OTA partitions, switch boot partitions, or reboot devices.

## Devices

Only whitelist these two devices:

- `miaoban-v1p2-002`
- `miaoban-v1p2-003`

Do not include `miaoban-v1p2-001`; it is reserved as the v3 reference unit.

## Preconditions

- The cloud service on `greenunion-sh` must include the latest OTA API if report fields such as `bytes_read`, `sha256`, and `expected_sha256` need to be recorded.
- If `greenunion-sh` is still only at OTA P1 API level, confirm and deploy the latest cloud code before expecting v31 report payload fields to persist.
- Any deployment, restart, or rollback on `greenunion-sh` requires explicit approval first.

## Artifact Placement

Place the firmware artifact under the configured OTA artifact directory on `greenunion-sh`.

Default local setting is `./data/ota_artifacts`; on `greenunion-sh`, confirm the effective path from the running service configuration before creating the release.

Example after confirming the artifact directory:

```bash
mkdir -p /home/ubuntu/religion_demo_shared/data/ota_artifacts
cp /path/to/esp_idf_demo.bin /home/ubuntu/religion_demo_shared/data/ota_artifacts/esp_idf_demo_v31.bin
sha256sum /home/ubuntu/religion_demo_shared/data/ota_artifacts/esp_idf_demo_v31.bin
wc -c /home/ubuntu/religion_demo_shared/data/ota_artifacts/esp_idf_demo_v31.bin
```

## Create Release

Run from the current release checkout that matches the running service code:

```bash
cd /home/ubuntu/releases/religion_demo/20260407_宗教大模型云服务器Demo
python3 scripts/ota_release_create.py \
  --release-id 2026-05-17-v31-dual-p3a \
  --version v31 \
  --artifact /home/ubuntu/religion_demo_shared/data/ota_artifacts/esp_idf_demo_v31.bin \
  --device-id miaoban-v1p2-002 \
  --device-id miaoban-v1p2-003 \
  --board ESP-VoCat \
  --hw-rev v1.2 \
  --min-version 1 \
  --priority 10 \
  --notes "v31 P3a dual-device download-verify report test"
```

The first matching enabled release wins by `priority ASC, created_at ASC, release_id ASC`. Keep tomorrow's test release priority lower than stale test releases, or disable stale releases before testing.

## Manifest Checks

Whitelist hit should return one update:

```bash
curl -sS "http://127.0.0.1/api/v5/ota/manifest?device_id=miaoban-v1p2-002&board=ESP-VoCat&hw_rev=v1.2&app_version=1"
curl -sS "http://127.0.0.1/api/v5/ota/manifest?device_id=miaoban-v1p2-003&board=ESP-VoCat&hw_rev=v1.2&app_version=1"
```

Non-whitelist device should return no update:

```bash
curl -sS "http://127.0.0.1/api/v5/ota/manifest?device_id=miaoban-v1p2-001&board=ESP-VoCat&hw_rev=v1.2&app_version=1"
```

Expected non-whitelist shape:

```json
{"device_id":"miaoban-v1p2-001","poll_interval_sec":3600,"updates":[]}
```

## Device Log Checks

On v31 devices, expected startup and OTA lines:

```text
realtime_intro_enabled=0
record_prompt_enabled=1
stage=ota_manifest_dry_run event=no_update
```

If the manifest returns an update:

```text
stage=ota_manifest_dry_run event=update_available ... action=download_verify_only
stage=ota_artifact_verify event=start
stage=ota_artifact_verify event=done
stage=ota_report event=done
```

Failure is acceptable only as a diagnostic result and must include `event=failed` with status, bytes, and SHA fields.

Forbidden P3a behavior:

```text
esp_ota_begin
esp_ota_write
esp_ota_set_boot_partition
esp_restart
```

## Current Hardware Package

Use only the v31 compile-only package for tomorrow's hardware test:

```text
/home/hanxiao_zhu_us/GMT/20260508_v5_realtime_opus/tmp/esp_compile_only_2026-05-17_v31.tar.gz
bytes=327566
sha256=ea1779bfafb1c70731dee9ddc40b87e52fe123656d4a8b554560ab6497bbe515
files=28
```
