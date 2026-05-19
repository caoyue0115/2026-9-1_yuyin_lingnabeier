# greenunion-sh OTA P3c Canary Runbook

This runbook records the P3c canary operating rules after the 002 v34 validation.

## Current Status

- P3c mechanism passed on `miaoban-v1p2-002`.
- The device booted from the OTA partition with `App version=v34-p3c-canary`.
- Runtime Wi-Fi, server, and device id configuration were present after reboot.
- `post_reboot_confirm ok=1` was reported successfully.
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

## Deployment Note

On greenunion-sh, the API container code comes from the Docker image. After changing `src/` backend code, a plain restart is not enough.

Required deployment shape after explicit deployment authorization:

```bash
docker compose build api
docker compose up -d api
```

Do not deploy, restart, or recreate containers without explicit authorization.

## Verification After Authorized Deploy

After an authorized API rebuild/recreate, verify:

- 001 manifest returns `updates=[]`
- 002 manifest returns `updates=[]` after its successful P3c report for the same release
- 003 behavior follows its explicitly authorized release scope
- A new release id for the same device is still eligible when whitelisted
- `docker compose ps` shows the expected API container state
