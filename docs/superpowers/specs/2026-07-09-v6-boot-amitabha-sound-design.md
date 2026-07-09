# V6 Boot Amitabha Sound Design

## Goal

Add a local boot sound that plays "Amitabha" in the currently configured server TTS voice on the ESP-VoCat V1.0 / v6 N16R8 16MB Flash + 8MB PSRAM line.

## Scope

- Generate the boot sound from the current server TTS configuration via `greenunion-sh`.
- Store only the board-ready PCM asset in firmware source.
- Play the sound from SPIFFS early in `app_runtime_task`, before Wi-Fi connection and trigger initialization.
- Keep playback non-blocking for product function: boot sound failure logs a warning and startup continues.
- Keep app-only OTA canary artifacts from enabling the SPIFFS-backed boot sound unless that release path also updates SPIFFS.
- Build and flash to `COM4` after compile-only passes.

Out of scope:

- OTA release creation or promotion.
- Production server/runtime/env changes.
- Printing or storing secrets, request bodies, raw serial logs, tokens, full URLs, device ids, SSIDs, MACs, transcripts, answers, or their hashes/digests.
- Reusing or replacing existing `intro_1.pcm` or record prompt assets.

## Asset

Create `esp_idf_demo/spiffs/boot_amitabha_1.pcm`.

Required format:

- Raw PCM
- 16000 Hz
- Mono
- 16-bit little-endian
- Small enough for the existing SPIFFS partition and default max playback limit

The source audio may be generated as WAV on the server or locally, but only the converted PCM asset is committed.

## Release Boundary

The boot sound asset lives in SPIFFS, so a full `idf.py flash` includes it through `storage.bin`. The existing OTA canary artifact scripts publish an app binary only; those temp build copies must disable `DEMO_BOOT_SOUND_ENABLED` until the OTA path gains storage-image delivery or the asset is embedded in the app.

## Firmware Behavior

Add configuration defaults in `esp_idf_demo/main/config.h`:

- `DEMO_BOOT_SOUND_ENABLED` defaults to `1`
- `DEMO_BOOT_SOUND_PATH` defaults to `/spiffs/boot_amitabha_1.pcm`
- `DEMO_BOOT_SOUND_MAX_BYTES` defaults to `(64 * 1024)`

Update `app_runtime_task`:

1. Log runtime config as today.
2. Mount SPIFFS when boot sound, realtime intro, or record prompt assets may be used.
3. If `DEMO_BOOT_SOUND_ENABLED` is true, play `DEMO_BOOT_SOUND_PATH` with `audio_out_play_pcm_file`.
4. Log `stage=boot_sound event=start`.
5. Log `stage=boot_sound event=done` on success or `stage=boot_sound event=failed` on failure.
6. Continue to runtime config validation, Wi-Fi startup, trigger initialization, and OTA dry-run flow regardless of boot sound result.

## Error Handling

- Missing SPIFFS or missing PCM file is not fatal.
- Playback/open/codec failures are not fatal.
- All boot sound failures remain warnings.
- Existing record prompt, realtime intro, and retry prompt behavior remains unchanged.

## Tests

Update focused asset/runtime tests to verify:

- `boot_amitabha_1.pcm` exists in `esp_idf_demo/spiffs`.
- The boot sound asset is below the configured max size.
- The boot sound asset is raw even-length PCM, not a WAV/RIFF file.
- `DEMO_BOOT_SOUND_ENABLED`, `DEMO_BOOT_SOUND_PATH`, and `DEMO_BOOT_SOUND_MAX_BYTES` exist in `config.h`.
- `app_runtime_task` mounts SPIFFS when boot sound is enabled.
- `app_runtime_task` invokes `audio_out_play_pcm_file` for the boot sound and does not return/stop on failure.
- App-only OTA canary scripts disable the SPIFFS-backed boot sound in their temporary source copies.

## Verification

Run:

- Focused tests for ESP assets/runtime guards.
- `git diff --check`
- `git diff --cached --check`
- Secret scan with available repo/tooling.
- ESP-IDF compile-only for the v6 N16R8 low-cost profile.
- Flash to `COM4` only after compile-only succeeds.

Hardware reporting must stay coarse: success/failure, public git SHA, and non-sensitive build facts only.
