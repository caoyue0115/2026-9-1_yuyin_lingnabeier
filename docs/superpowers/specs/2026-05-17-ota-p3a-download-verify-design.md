# OTA P3a Download Verify Design

## Goal

OTA P3a moves the device from manifest-only dry-run to real artifact download verification, without writing OTA partitions or changing boot state.

## Scope

- ESP32-S3 fetches `/api/v5/ota/manifest` as before.
- If `updates[0]` exists, the board downloads the artifact URL and streams bytes through SHA256.
- The board verifies HTTP 200, downloaded byte count equals manifest `size`, and computed SHA256 equals manifest `sha256`.
- The board logs `stage=ota_artifact_verify event=start|done|failed` and keeps `action=download_verify_only`.
- The board must not call `esp_ota_begin`, `esp_ota_write`, `esp_ota_end`, `esp_ota_set_boot_partition`, or reboot.
- Cloud release management is a local CLI script only. It creates an OTA release row from an existing artifact path and whitelisted device IDs. No cloud deployment is part of this task.

## Design

Board-side download verification belongs in `cloud_client.c` because it already owns HTTP client code and manifest parsing. The public API will expose a small result struct with `http_status`, `bytes_read`, `expected_size`, `sha256`, and `expected_sha256`. `main.c` remains orchestration-only: when manifest has an update, call the verifier and log the result.

Cloud-side release management belongs in `scripts/ota_release_create.py`. It uses `src.storage.db.create_ota_release`, computes artifact `size` and `sha256`, validates the artifact is under `settings.ota_artifact_path`, and accepts comma-separated device IDs. It does not copy firmware and does not deploy.

## Verification

- Static ESP asset tests prove P3a symbols and logs exist and OTA partition write/switch APIs remain absent.
- Python CLI tests create a temporary artifact, invoke the release script, and verify the resulting manifest returns that release.
- Full Python tests, `git diff --check`, and ESP-IDF build must pass.
- Hardware handoff default remains compile-only package, not flash-only or full handoff.
