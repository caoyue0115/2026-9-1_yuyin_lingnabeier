# OTA P3c Formalization Design

## Status

Approved scope: formalize the P3c release mechanism only.

Out of scope for this phase:

- No 003 canary.
- No production release creation.
- No greenunion-sh deployment.
- No `.env` changes.
- No device operation.

## Background

P3c has passed the `miaoban-v1p2-002` v34 canary. The device wrote the inactive OTA app partition, set the next boot partition, restarted, booted from the OTA partition, preserved runtime configuration, connected to Wi-Fi, and reported `post_reboot_confirm ok=1`.

Two incidents from the canary define the formalization requirements:

- v33 target artifact was built without runtime config, causing empty `wifi_ssid`, `server_base_url`, and `device_id` after boot.
- v34 suppress logic was initially copied to the host source tree but not rebuilt into the API image, so restart alone did not activate the fix.

The current long-term anti-repeat mechanism is server-side manifest suppression: once the same `device_id + release_id` has a successful `boot_switch_scheduled` or `post_reboot_confirm` report, `/api/v5/ota/manifest` must not return that release again for that device.

## Goal

Turn P3c from a hand-operated canary into a repeatable, auditable, semi-automatic release workflow that keeps destructive operations explicit and prevents repeat delivery of consumed boot-switch releases.

## Chosen Approach

Use a semi-automatic formalization flow.

Release creation and closeout remain explicit operator actions, but local tooling and tests enforce the rules:

1. Create a new release id for every P3c attempt.
2. Require explicit whitelist devices.
3. Validate artifact path, size, and SHA256 from the artifact file.
4. Require board, hardware revision, minimum version, and notes for P3c release creation.
5. Prefer creating P3c releases disabled unless an operator explicitly requests enabled creation.
6. Keep manifest suppression as the automatic anti-repeat mechanism.
7. Close out a passed canary by setting the release `enabled=0` and verifying target devices return `updates=[]`.

This avoids a per-device release-state table for now. It also avoids auto-disabling the release on first successful `post_reboot_confirm`, which would be unsafe for future multi-device gray releases because one device could disable the release before other whitelisted devices consume it.

## Release Lifecycle

### 1. Artifact Preparation

The artifact must be built by an explicit P3c artifact script or an equivalent controlled build command.

For canary builds, the artifact must include non-secret runtime identity values:

- board-specific runtime config
- `server_base_url`
- `device_id`
- an app version string that identifies the canary or release

Wi-Fi password handling must remain controlled:

- Preferred canary artifact does not embed the Wi-Fi password.
- If `DEMO_WIFI_PASSWORD` is empty, firmware must not overwrite stored NVS Wi-Fi station credentials.
- A password-bearing build requires separate authorization and must not print or commit the password.

### 2. Release Creation

The release creation tool should support a P3c mode with stricter validation than generic P3a/P3b release creation.

Required P3c fields:

- `release_id`
- `version`
- `artifact`
- at least one `device_id`
- `board`
- `hw_rev`
- `min_version`
- `notes`
- explicit enabled/disabled intent

P3c release id rules:

- Must be new.
- Must not reuse P3a/P3b/P3c canary release ids.
- Must not reuse `2026-05-18-v32-002-p3b`.
- Must not reuse `2026-05-18-v34-002-p3c`.

Whitelist rules:

- 001 remains excluded from OTA.
- 003 is not included in this formalization phase.
- Future 003 or batch rollout requires separate authorization and a new release id.

### 3. Manifest Delivery

Manifest delivery keeps the existing priority and whitelist behavior, with P3c suppress applied before returning an update.

Suppress condition:

```text
device_id = requested device_id
release_id = candidate release_id
stage in ("boot_switch_scheduled", "post_reboot_confirm")
ok = 1
```

If a matching report exists, that exact release is skipped for that exact device.

Suppress must not hide:

- another release id
- another device
- failed reports (`ok=0`)
- ordinary P3a/P3b stages like `download_verify` or `partition_write`

### 4. Device Execution

P3c remains gated by `DEMO_OTA_BOOT_SWITCH_ENABLED`.

Default source must keep:

```c
#define DEMO_OTA_BOOT_SWITCH_ENABLED 0
```

Only explicitly built P3c canary or release artifacts may set it to `1`.

P3c device flow:

1. Manifest returns a P3c release.
2. Device downloads and writes the inactive OTA partition.
3. Device validates size and SHA256.
4. Device reports `partition_write ok=1`.
5. Device stores pending boot state in NVS.
6. Device calls `esp_ota_set_boot_partition(update_partition)`.
7. Device reports `boot_switch_scheduled ok=1`.
8. Device calls `esp_restart()`.
9. After reboot, device reports `post_reboot_confirm ok=1` when running partition matches expected partition.

Rollback/app-valid APIs remain out of scope while ESP-IDF rollback is disabled.

### 5. Closeout

After a canary passes:

1. Query reports for the release.
2. Confirm `partition_write ok=1`.
3. Confirm `boot_switch_scheduled ok=1`.
4. Confirm `post_reboot_confirm ok=1`.
5. Set the release `enabled=0`.
6. Verify the target device manifest returns `updates=[]`.
7. Leave whitelist rows intact as historical release scope unless there is an incident requiring stopgap removal.

Manual whitelist deletion is not standard closeout. It is only an incident stopgap.

## greenunion-sh Deployment Rule

The API container runs code from the Docker image, not a bind-mounted source tree.

After backend `src/` changes, the required authorized deploy shape is:

```bash
docker compose build api
docker compose up -d api
```

A plain restart is insufficient for backend source changes.

## Testing Requirements

Server-side tests:

- P3c suppress after `boot_switch_scheduled ok=1`.
- P3c suppress after `post_reboot_confirm ok=1`.
- Failed reports do not suppress.
- Other release ids are still eligible.
- Other devices are still eligible.
- P3a/P3b stages do not suppress.
- P3c release creation mode rejects missing board, hardware revision, min version, notes, and device whitelist.
- P3c release creation mode can create disabled releases by default or requires explicit enabled intent.

Firmware static tests:

- Default source keeps `DEMO_OTA_BOOT_SWITCH_ENABLED=0`.
- `esp_ota_set_boot_partition()` and `esp_restart()` appear only inside P3c gated blocks.
- Rollback/app-valid APIs are absent unless rollback is explicitly redesigned.

Operational verification:

- `git diff --check`
- full pytest
- default ESP-IDF build when firmware code changes
- manifest checks for target and non-target devices after any authorized deploy

## Risks and Mitigations

- Risk: operator creates an enabled P3c release with too broad a whitelist.
  - Mitigation: require explicit whitelist and explicit enabled intent.

- Risk: repeated release delivery after boot switch.
  - Mitigation: server-side suppress by exact `device_id + release_id`.

- Risk: backend source changes are copied but not loaded by the API container.
  - Mitigation: document and test the build/up deploy rule.

- Risk: artifact lacks runtime config.
  - Mitigation: controlled artifact script and artifact string checks for non-secret runtime identity values.

- Risk: future rollback behavior is assumed.
  - Mitigation: keep rollback/app-valid APIs out of P3c formalization until rollback is separately enabled and redesigned.

## Acceptance Criteria

- P3c formalization adds release tooling/tests/docs but does not include 003.
- No new production release is created during implementation.
- No deployment occurs during implementation.
- Existing v34 canary result remains documented as passed.
- Operators have a repeatable release creation and closeout workflow.
- Tests prove consumed P3c releases are not returned again to the same device.
