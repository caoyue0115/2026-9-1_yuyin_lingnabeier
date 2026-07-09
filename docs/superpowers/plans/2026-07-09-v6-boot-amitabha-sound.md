# V6 Boot Amitabha Sound Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local, early-boot "Amitabha" sound to the ESP-VoCat V1.0 v6 N16R8 firmware and flash it to `COM4`.

**Architecture:** Generate one board-ready raw PCM asset from the current server TTS voice and package it in SPIFFS. Reuse the existing `audio_out_play_pcm_file` path from `app_runtime_task`, with a default-on compile-time guard and warning-only failure behavior. App-only OTA canary build scripts must disable this SPIFFS-backed sound in their temp source copies until that release path also updates SPIFFS.

**Tech Stack:** ESP-IDF v5.5.4, ESP32-S3, SPIFFS, raw PCM 16kHz mono 16-bit, Python `unittest`, PowerShell, SSH/SCP.

---

## File Structure

- Modify `tests/test_esp_assets.py`: add red tests for the boot sound asset, config macros, SPIFFS mount condition, and non-fatal early playback call.
- Add `esp_idf_demo/spiffs/boot_amitabha_1.pcm`: board-ready boot sound PCM generated from the server's current TTS configuration.
- Modify `esp_idf_demo/main/config.h`: add boot sound path/enabled/max-byte defaults.
- Modify `esp_idf_demo/main/main.c`: mount SPIFFS when boot sound is enabled and play the boot sound before network initialization.
- Modify `scripts/build_esp_p3c_canary_artifact.sh` and `scripts/build_esp_p3d_canary_artifact.sh`: disable the SPIFFS-backed boot sound in app-only OTA canary temp copies.
- Use existing `esp_idf_demo/main/audio_out.c`: no new playback primitive is needed.

## Task 1: Red Tests For Boot Sound Contract

**Files:**
- Modify: `tests/test_esp_assets.py`

- [ ] **Step 1: Add failing tests**

Insert these tests near the existing prompt asset/config tests:

```python
    def test_boot_sound_audio_asset_is_small_pcm_resource(self) -> None:
        boot_sound = ESP_DIR / "spiffs" / "boot_amitabha_1.pcm"

        self.assertTrue(boot_sound.exists())
        self.assertGreater(boot_sound.stat().st_size, 0)
        self.assertLessEqual(boot_sound.stat().st_size, 64 * 1024)

    def test_boot_sound_config_is_explicit_and_enabled_by_default(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")

        self.assertIn("DEMO_BOOT_SOUND_ENABLED", config)
        self.assertEqual("1", _read_macro_value(config, "DEMO_BOOT_SOUND_ENABLED"))
        self.assertIn("DEMO_BOOT_SOUND_PATH", config)
        self.assertEqual('"/spiffs/boot_amitabha_1.pcm"', _read_macro_value(config, "DEMO_BOOT_SOUND_PATH"))
        self.assertIn("DEMO_BOOT_SOUND_MAX_BYTES", config)
        self.assertEqual("(64 * 1024)", _read_macro_value(config, "DEMO_BOOT_SOUND_MAX_BYTES"))

    def test_boot_sound_mount_and_playback_are_early_and_nonfatal(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("DEMO_BOOT_SOUND_ENABLED || DEMO_REALTIME_INTRO_ENABLED || DEMO_RECORD_PROMPT_ENABLED", main_source)
        self.assertIn("static void app_play_boot_sound(void)", main_source)
        self.assertIn("stage=boot_sound event=start", main_source)
        self.assertIn("stage=boot_sound event=done", main_source)
        self.assertIn("stage=boot_sound event=failed", main_source)
        self.assertIn("audio_out_play_pcm_file(DEMO_BOOT_SOUND_PATH", main_source)

        boot_sound_call = main_source.index("app_play_boot_sound();")
        validate_config = main_source.index("app_validate_runtime_config()")
        network_start = main_source.index("app_network_start()")
        self.assertLess(boot_sound_call, validate_config)
        self.assertLess(boot_sound_call, network_start)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m unittest tests.test_esp_assets.EspAssetTests.test_boot_sound_audio_asset_is_small_pcm_resource tests.test_esp_assets.EspAssetTests.test_boot_sound_config_is_explicit_and_enabled_by_default tests.test_esp_assets.EspAssetTests.test_boot_sound_mount_and_playback_are_early_and_nonfatal
```

Expected: fail because `boot_amitabha_1.pcm`, `DEMO_BOOT_SOUND_*`, and `app_play_boot_sound` do not exist yet.

## Task 2: Generate Board-Ready Audio Asset

**Files:**
- Add: `esp_idf_demo/spiffs/boot_amitabha_1.pcm`

- [ ] **Step 1: Generate server-side source audio without printing secrets**

Use `ssh greenunion-sh` to run the deployed app's current TTS code or an equivalent container command. The command must not print environment variables, tokens, request bodies, response bodies, full audio URLs, or audio bytes. It may print only coarse success/failure and a temporary file path.

- [ ] **Step 2: Copy the generated WAV/audio file locally**

Use `scp` or another binary-safe file transfer from the server temp path into a local temp path under `C:\tmp`. Do not print file contents.

- [ ] **Step 3: Convert to board PCM**

Use Python `wave`/`audioop` or `ffmpeg` to produce:

```text
esp_idf_demo/spiffs/boot_amitabha_1.pcm
16000 Hz, mono, signed 16-bit little-endian raw PCM
```

The conversion must fail if the output is empty or exceeds `64 * 1024` bytes.

- [ ] **Step 4: Re-run the asset test**

Run:

```powershell
python -m unittest tests.test_esp_assets.EspAssetTests.test_boot_sound_audio_asset_is_small_pcm_resource
```

Expected: pass.

## Task 3: Firmware Config And Startup Playback

**Files:**
- Modify: `esp_idf_demo/main/config.h`
- Modify: `esp_idf_demo/main/main.c`

- [ ] **Step 1: Add config defaults**

Add this block near the existing realtime intro / record prompt settings:

```c
#ifndef DEMO_BOOT_SOUND_ENABLED
#define DEMO_BOOT_SOUND_ENABLED 1
#endif

#ifndef DEMO_BOOT_SOUND_PATH
#define DEMO_BOOT_SOUND_PATH "/spiffs/boot_amitabha_1.pcm"
#endif

#ifndef DEMO_BOOT_SOUND_MAX_BYTES
#define DEMO_BOOT_SOUND_MAX_BYTES (64 * 1024)
#endif
```

- [ ] **Step 2: Add runtime config observability**

In `app_log_runtime_config`, add:

```c
    ESP_LOGI(TAG, "  boot_sound_enabled=%d", DEMO_BOOT_SOUND_ENABLED);
    ESP_LOGI(TAG, "  boot_sound_path=%s", DEMO_BOOT_SOUND_PATH);
```

- [ ] **Step 3: Add warning-only boot playback helper**

Add near `app_play_retry_prompt`:

```c
static void app_play_boot_sound(void)
{
    if (!DEMO_BOOT_SOUND_ENABLED || DEMO_BOOT_SOUND_PATH[0] == '\0') {
        return;
    }

    ESP_LOGI(TAG, "stage=boot_sound event=start");
    const int64_t start_us = esp_timer_get_time();
    esp_err_t ret = audio_out_play_pcm_file(DEMO_BOOT_SOUND_PATH,
                                            DEMO_AUDIO_SAMPLE_RATE,
                                            DEMO_AUDIO_CHANNELS,
                                            DEMO_AUDIO_BITS_PER_SAMPLE,
                                            DEMO_BOOT_SOUND_MAX_BYTES);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "stage=boot_sound event=done elapsed_ms=%.1f",
                 (double)(esp_timer_get_time() - start_us) / 1000.0);
    } else {
        ESP_LOGW(TAG, "stage=boot_sound event=failed err=%s elapsed_ms=%.1f",
                 esp_err_to_name(ret),
                 (double)(esp_timer_get_time() - start_us) / 1000.0);
    }
}
```

- [ ] **Step 4: Mount SPIFFS and play early**

Replace the existing mount condition:

```c
    if (DEMO_REALTIME_INTRO_ENABLED || DEMO_RECORD_PROMPT_ENABLED) {
        (void)app_mount_spiffs();
    }
```

with:

```c
    if (DEMO_BOOT_SOUND_ENABLED || DEMO_REALTIME_INTRO_ENABLED || DEMO_RECORD_PROMPT_ENABLED) {
        (void)app_mount_spiffs();
    }

    app_play_boot_sound();
```

- [ ] **Step 5: Run config/startup tests**

Run:

```powershell
python -m unittest tests.test_esp_assets.EspAssetTests.test_boot_sound_config_is_explicit_and_enabled_by_default tests.test_esp_assets.EspAssetTests.test_boot_sound_mount_and_playback_are_early_and_nonfatal tests.test_esp_assets.EspAssetTests.test_spiffs_mount_is_kept_for_record_prompt_when_intro_is_disabled
```

Expected: pass.

## Task 4: Focused Verification

**Files:**
- No new edits expected.

- [ ] **Step 1: Run focused Python tests**

Run:

```powershell
python -m unittest tests.test_esp_assets tests.test_esp_runtime_guards
```

Expected: pass.

- [ ] **Step 2: Run whitespace checks**

Run:

```powershell
git diff --check
git diff --cached --check
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run secret scan**

Run:

```powershell
gitleaks dir esp_idf_demo/main/config.h --redact --no-banner --no-color
gitleaks dir esp_idf_demo/main/main.c --redact --no-banner --no-color
gitleaks dir tests/test_esp_assets.py --redact --no-banner --no-color
gitleaks dir docs/superpowers/plans/2026-07-09-v6-boot-amitabha-sound.md --redact --no-banner --no-color
gitleaks dir docs/superpowers/specs/2026-07-09-v6-boot-amitabha-sound-design.md --redact --no-banner --no-color
gitleaks dir esp_idf_demo/spiffs/boot_amitabha_1.pcm --redact --no-banner --no-color
```

Expected: changed files report no leaks. If a full-repo gitleaks run reports pre-existing findings outside this change, record those separately and do not treat them as newly introduced by this feature.

## Task 5: ESP-IDF Compile-Only

**Files:**
- Build output only.

- [ ] **Step 1: Load ESP-IDF and build v6 low-cost profile**

Run from `esp_idf_demo`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
. 'C:\esp\v5.5.4\esp-idf\export.ps1'
$env:SDKCONFIG_DEFAULTS='sdkconfig.defaults;sdkconfig.defaults.vocat_lowcost_16m8m'
$env:PROJECT_VER='v6-boot-amitabha-local'
python "$env:IDF_PATH\tools\idf.py" fullclean
python "$env:IDF_PATH\tools\idf.py" -D "PROJECT_VER=v6-boot-amitabha-local" build
```

Expected: build succeeds for target `esp32s3`, v1.0 low-cost profile remains enabled, app binary is below the 3MB OTA slot.

## Task 6: Flash To COM4

**Files:**
- Hardware only.

- [ ] **Step 1: Flash after compile-only passes**

Run from `esp_idf_demo`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
. 'C:\esp\v5.5.4\esp-idf\export.ps1'
$env:PROJECT_VER='v6-boot-amitabha-local'
python "$env:IDF_PATH\tools\idf.py" -p COM4 flash
```

Expected: esptool writes all segments and verifies hashes.

- [ ] **Step 2: Report coarse hardware result**

Report only build/flash success or failure, public git SHA, target, and non-sensitive boot sound status. Do not paste raw serial logs or sensitive runtime values.
