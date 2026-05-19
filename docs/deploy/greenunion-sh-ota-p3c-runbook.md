# greenunion-sh OTA P3c Canary Runbook

This runbook records the P3c canary operating rules after the 002 v35 validation and closeout.

## Current Status

- P3c mechanism passed on `miaoban-v1p2-002`.
- The device booted from the OTA partition with `App version=v35-p3c-canary`.
- Runtime Wi-Fi, server, and device id configuration were present after reboot.
- `partition_write ok=1`, `boot_switch_scheduled ok=1`, and `post_reboot_confirm ok=1` were reported successfully for `2026-05-19-v35-002-p3c`.
- The v35 release has been closed out with `enabled=0`.
- `miaoban-v1p2-001` remains excluded from OTA.
- `miaoban-v1p2-003` is not automatically included in P3c.

P3c is now proven for the 002 canary path, but it is not a blanket authorization for wider rollout.

## Known Issues Closed During P3c

v33 artifact issue:

- `tmp/esp_idf_demo_v33_p3c_canary_20260518.bin` was built without runtime configuration.
- After booting the OTA partition, `wifi_ssid`, `server_base_url`, and `device_id` were empty.
- v34 fixed this with a dedicated canary artifact build flow that injects the 002 canary runtime values.

v34 suppress deployment issue:

- The first server-side suppress fix was copied to the host source tree but the API image was not rebuilt.
- Because the API container runs code from the image, a simple container restart did not activate the source change.
- Rebuilding and recreating the API container made suppress effective.

v35 port mapping issue:

- A source sync overwrote the greenunion-sh v5 compose default port back to `8020`.
- Device firmware uses `http://106.54.240.51` without an explicit port, so public port 80 must serve v5.
- The mapping was restored to `0.0.0.0:80->8010/tcp` and committed as `bb60c9d Restore greenunion v5 public port default`.

## Manifest Suppress Rule

Manifest must suppress only the exact consumed release:

```text
device_id = report.device_id
release_id = report.release_id
stage in ("boot_switch_scheduled", "post_reboot_confirm")
ok = 1
```

If such a report exists, `/api/v5/ota/manifest` must not return that same release again for that same device.

This must not suppress:

- a different `release_id`
- another device
- reports with `ok=0`
- ordinary P3a/P3b reports such as `download_verify` or `partition_write`

Manual removal of `miaoban-v1p2-002` from a release whitelist was a one-time stopgap during the v34 incident. Do not write it into the normal canary flow.

## Release Operating Rules

- P3c release ids must be new and must not reuse a P3b release.
- Do not reuse `2026-05-18-v32-002-p3b`.
- Do not reuse the v34 canary release for a later phase.
- First P3c canary remains 002-only unless separately authorized.
- Do not add `miaoban-v1p2-001` to any OTA whitelist.
- Do not add `miaoban-v1p2-003` to P3c by default.
- After a canary passes, keep suppress as the automatic anti-repeat mechanism, then set the canary release `enabled=0` as an operational closeout to prevent accidental whitelist expansion or release reuse.

## Semi-Automatic P3c Workflow

Create a P3c release only after a new artifact has been uploaded to the OTA artifact directory and the release scope has been explicitly authorized.

Example disabled creation from inside the API container:

```bash
python scripts/ota_release_create.py \
  --p3c \
  --release-id 2026-05-19-v35-002-p3c \
  --version v35 \
  --artifact /app/data/ota_artifacts/esp_idf_demo_v35_p3c_002_20260519.bin \
  --device-id miaoban-v1p2-002 \
  --board ESP-VoCat \
  --hw-rev v1.2 \
  --min-version 1 \
  --notes "P3c 002 canary" \
  --disabled
```

Use `--enable` only when the release should immediately become visible to the whitelisted device.

After the canary passes and reports `partition_write ok=1`, `boot_switch_scheduled ok=1`, and `post_reboot_confirm ok=1`, close it out:

```bash
python scripts/ota_release_closeout.py \
  --release-id 2026-05-19-v35-002-p3c \
  --device-id miaoban-v1p2-002
```

Then verify the target device manifest returns `updates=[]`.

## 2026-05-19 v35 002 Canary Result

- release_id: `2026-05-19-v35-002-p3c`
- artifact: `esp_idf_demo_v35_p3c_002_20260519.bin`
- bytes: `1248352`
- sha256: `4b8a1111977d2da7b07151135de98bf5e72c37c372c48540fd9d7ff8ee7eddaa`
- device whitelist: `miaoban-v1p2-002` only
- boot result: loaded from `ota_1` at offset `0x320000`
- app version after reboot: `v35-p3c-canary`
- reports: `partition_write ok=1`, `boot_switch_scheduled ok=1`, `post_reboot_confirm ok=1`
- post reboot confirm: `running_partition_after_reboot=ota_1`, `reboot_reason=software_reset`
- closeout: release set to `enabled=0`
- final manifests: 001 `updates=[]`, 002 `updates=[]`, 003 still follows its existing v31 P3a scope

## P3d Rollback Gate Before Customer Handoff

Do not ship `miaoban-v1p2-002` to a customer on a new OTA artifact unless P3d rollback validation has passed.

P3d requires:

- rollback-enabled bootloader on the device; app-only OTA cannot add bootloader rollback support
- rollback-enabled artifact, not the completed v35 P3c artifact
- new release id, for example `2026-05-19-v36-002-p3d`
- whitelist only `miaoban-v1p2-002`
- successful reports for `partition_write`, `boot_switch_scheduled`, `post_reboot_confirm`, and `app_validated`
- `scripts/ota_release_closeout.py --p3d`
- a fault-injection or timeout validation showing that no `app_validated` report is emitted when business initialization hangs

If 002's current bootloader was built without `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`, do not rely on an OTA app artifact for customer rollback safety. Prepare and flash a controlled full package with rollback-enabled bootloader before treating P3d as effective.

Do not include `miaoban-v1p2-003` in P3d.

## Deployment Note

On greenunion-sh, the API container code comes from the Docker image. After changing `src/` backend code, a plain restart is not enough.

Required deployment shape after explicit deployment authorization:

```bash
docker compose build api
docker compose up -d api
```

The v5 API must be published on public port 80. Do not let source sync or compose defaults move it back to 8020 while device firmware uses `http://106.54.240.51`.

Do not deploy, restart, or recreate containers without explicit authorization.

## Verification After Authorized Deploy

After an authorized API rebuild/recreate, verify:

- 001 manifest returns `updates=[]`
- 002 manifest returns `updates=[]` after its successful P3c report for the same release
- 003 behavior follows its explicitly authorized release scope
- A new release id for the same device is still eligible when whitelisted
- `docker compose ps` shows the expected API container state
