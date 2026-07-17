---
name: religion-v6-n16r8-ota-release
description: Use when preparing, enabling, validating, disabling, or rolling back the authorized ESP-VoCat V1.0 ESP32-S3 N16R8 single-device OTA canary in this repository.
---

# V6 N16R8 OTA Release

## Core Principle

Treat OTA as a gated single-device release, not as a normal firmware upload. Keep repository defaults inert and inject release-only values only into an isolated temporary build copy.

## Read First

From the repository root, read only the sections needed for the task:

- `docs/v6-lowcost-16flash-8psram-baseline.md`
- `docs/deploy/v6-n16r8-release-handoff-20260522.md`
- `docs/deploy/greenunion-sh-ota-p3c-runbook.md`
- Run `python .agents/skills/religion-v6-n16r8-ota-release/scripts/run_gate.py --help` (`python3` on POSIX).

The P3a/P3b runbooks are historical evidence only. Never use their operational instructions for a V1.0 N16R8 release. Do not use an older repository or the deprecated V1.2 audio profile as the implementation source.

## Hard Guardrails

- Never read, print, modify, or commit `.env`, Wi-Fi passwords, credentials, tokens, private headers, or secrets.
- Never print raw serial logs, MAC addresses, SSIDs, device identifiers, questions, answers, task IDs, full audio URLs, or derived fingerprints of those values.
- Require explicit authorization before flashing hardware, creating/enabling/disabling an OTA release, uploading an artifact, or changing server runtime/configuration.
- Use `greenunion-sh` for the Shanghai server. Begin with read-only inspection and never inspect `.env`.
- Keep `DEMO_OTA_BOOT_SWITCH_ENABLED` and `DEMO_OTA_ROLLBACK_VALIDATION_ENABLED` at `0` in committed defaults.
- Inject release-only settings into a temporary source copy; never commit them.
- Target exactly the single canary device configured by the release gate. Never add another sample device to that release.
- Device expansion is out of scope. It requires a separate gate/configuration change, review, and explicit authorization.
- Never reuse a failed release ID or version string.
- Stop after a failed gate. Do not retry hardware, OTA, or server mutations automatically.
- Do not call compile-only, boot-only, or one successful conversation a production pass.

## Required Build Facts

The temporary canary build must show:

- Version format `v6-n16r8-<N>-ota-canary`.
- `SDKCONFIG_DEFAULTS` includes `sdkconfig.defaults.vocat_lowcost_16m8m` and rollback defaults.
- `CONFIG_DEMO_TARGET_PROFILE_VOCAT_LOWCOST_16M8M=1`.
- `CONFIG_DEMO_AUDIO_PCB_ESP_VOCAT_V1_0=1`.
- `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=1`.
- OTA boot switch and rollback validation are enabled only in the temporary build.
- Server URL and the authorized canary identity are non-empty in the temporary build.
- The application binary is smaller than `3,145,728` bytes.

Record the reviewed Git SHA, artifact path, byte size, SHA-256, version, and release ID without exposing protected runtime values.

## Release Workflow

1. Confirm repository, branch, reviewed Git SHA, board profile, authorization scope, and current server health.
2. Disable any known-bad release before preparing its replacement.
3. Build from an isolated temporary source copy and verify every required build fact.
4. Run the fixed release-safety suite only through the summary-only test runner below, then run firmware compile and `git diff --check`. Scan committed history with `gitleaks git --redact --log-opts="<base>..HEAD"`; never recursively scan the working tree or `.env`.
5. Upload the verified app artifact to the configured OTA artifact directory on `greenunion-sh`.
6. Create one release for exactly the gate-configured canary device.
7. Verify the allowed-device manifest and every blocked-device manifest.
8. Capture a full boot-through-realtime hardware log and run the log gate.
9. Verify post-reboot rollback confirmation and run 3-5 realtime conversations before promotion.

## Automated Gate

On Windows use `python`; on POSIX replace it with `python3`. Commands are intentionally single-line so they work in PowerShell and POSIX shells after replacing quoted placeholders.

```powershell
python .agents/skills/religion-v6-n16r8-ota-release/scripts/run_gate.py --self-test
python .agents/skills/religion-v6-n16r8-ota-release/scripts/run_tests.py
```

The wrappers capture raw output but emit only pass/fail summaries and preserve exit codes. The test runner uses an isolated working directory so settings cannot load the repository `.env`. Never invoke the underlying gate or these release tests directly in a Codex-visible command. The gate wrapper fixes device scope, board/hardware defaults, and artifact-size ceiling; it rejects override arguments, invalid versions or hashes, empty selectors, manifest checks without an artifact/release ID, and log checks without OTA-success validation.

Use placeholders in commands and shared output:

```powershell
python .agents/skills/religion-v6-n16r8-ota-release/scripts/run_gate.py --artifact "tmp/<artifact>.bin" --expected-sha256 "<sha256>" --expected-version "v6-n16r8-<N>-ota-canary" --expected-release-id "<release-id>" --manifest-base-url "<authorized-base-url>"
```

After the canary consumes the release, verify repeat suppression:

```powershell
python .agents/skills/religion-v6-n16r8-ota-release/scripts/run_gate.py --artifact "tmp/<artifact>.bin" --expected-sha256 "<sha256>" --expected-version "v6-n16r8-<N>-ota-canary" --expected-release-id "<release-id>" --manifest-base-url "<authorized-base-url>" --allowed-device-mode no-update
```

Validate the sanitized hardware log:

```powershell
python .agents/skills/religion-v6-n16r8-ota-release/scripts/run_gate.py --log "<sanitized-serial.log>" --expected-version "v6-n16r8-<N>-ota-canary" --require-ota-success
```

## Pass And Block

Pass only when runtime confirms ESP-VoCat V1.0, the N16R8 target profile, correct V1.0 audio routing, enabled canary safety switches, successful post-reboot confirmation, stable memory/stack/audio metrics, and 3-5 successful realtime runs.

Block promotion on empty release configuration, V1.2 audio routing, an oversized artifact, manifest leakage to another device, rollback recovery, post-reboot confirmation failure, repeated resets, audio truncation, resource decline, or any failed gate.

## Reporting

Report only public Git SHAs, artifact size, pass/fail booleans, counts, coarse reason enums, summary-only gate results, and the next authorized action. Never include protected runtime values or raw logs.
