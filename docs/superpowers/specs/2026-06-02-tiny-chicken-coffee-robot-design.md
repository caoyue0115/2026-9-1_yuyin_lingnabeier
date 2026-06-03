# Tiny Chicken Coffee Robot v6_tiny Design

## Purpose

Create a new `v6_tiny` variant for the coffee-focused tiny chicken robot business line. It should reuse the proven v6 device/cloud foundations where they reduce risk, while separating repository, deployment, data, configuration, assets, and product behavior from the current v6 line.

The first implementation target is a 32MB Flash + 8MB PSRAM ESP32-S3-style board with display. The product name and future custom wake-word spelling are standardized as `小机仔`. The uploaded robot materials are product references for display, motion assets, interaction states, and future app/device behavior, but the first implementation remains on the 32MB/8MB hardware baseline rather than the BK7258/128MB Flash baseline shown in the material spreadsheet.

## Confirmed Decisions

- New project directory: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot`.
- New GitHub repository: `https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git`.
- Initial implementation style: create a clean copy from current v6, then isolate and slim into a tiny chicken variant.
- Deployment target: Guangzhou server, not `greenunion-sh`.
- Guangzhou server has no prepared directory yet; Codex will SSH later and create the deployment layout.
- First deployment entry: IP + port for bring-up, domain/HTTPS later.
- Product persona: a lively coffee-savvy tiny chicken shop assistant, Chinese, concise 1-3 sentence answers.
- Wake word for phase 1: keep current `小明同学`; custom `小机仔` wake word is deferred.
- App/mini-program: not built in phase 1; reserve cloud/device interfaces for later.
- OTA code: keep from v6 but default to no publishing/release actions in phase 1.
- RAG: no coffee RAG in phase 1; use model built-in knowledge.
- Doubao output: text only, then synthesize speech through the existing Volcengine TTS path.
- Doubao input target: audio direct to Doubao-Seed-2.0-mini if the official API supports it; otherwise fallback to current ASR -> Doubao text -> TTS.

## Source Material Notes

Uploaded material archive:

- Original archive after normalized naming: `/mnt/data100/20260602_小机仔.rar`.
- Extracted material root: `/mnt/data100/GMT/assets/20260602_tiny_chicken_materials`.
- The original archive extraction produced a 0-byte `互动avi素材/1_base_sta_and_wakeup/device_unused.avi`; this has been replaced by a separately uploaded valid AVI at the extracted material path.

Important material facts:

- Product definition file: `XB01机器人产品与应用定义`.
- Material hardware target differs from this phase: BK7258, 128MB Flash, 16MB PSRAM.
- This phase uses 32MB Flash + 8MB PSRAM instead.
- Display in material: 320x240, safe expression region 240x240, actual mount rotation not yet confirmed.
- Existing visual assets are AVI Motion JPEG, mostly 240x320 at 25fps, with emotion/state names in English.
- Future material table requests MP4, but MCU phase should not depend on AVI/MP4 containers at runtime.
- Alarm requirements exist and should be tracked as a future feature: create/query/delete/close/snooze, at least 5 persistent alarms.

## Architecture

### Repository Safety

The new repository must not be a GitHub fork that carries the full v6 git history.

Required approach:

- Create a clean working copy from the current v6 source tree.
- Remove the old `.git` history before initializing the tiny repository.
- Initialize a new git history for `20260601_tiny_chicken_coffee_robot`.
- Set the new GitHub repository to private by default for phase 1 unless a separate public-release approval is given.
- Before the first commit, verify `.gitignore` blocks `.env`, token files, Wi-Fi credentials, private keys, certificates, local deployment files, build outputs, and generated binary artifacts that should not be tracked.
- Do not read, print, modify, or commit existing v6 secrets, tokens, Wi-Fi passwords, private keys, certificates, or production `.env` files during copy, cleanup, tests, or deployment preparation.
- If secret-like material is detected by filename or scan, remove it from the clean copy without printing the value.

### Repository Split

The new repository starts as a clean v6 source copy so it inherits stable device/cloud building blocks:

- ESP-IDF board bring-up patterns.
- Wi-Fi provisioning and reprovisioning patterns.
- WakeNet service structure.
- Opus uplink and realtime playback pipeline.
- OTA partition and rollback scaffolding.
- FastAPI, Docker Compose, Redis, SQLite, health check, and logging patterns.

After the copy, rename and isolate:

- Python package/project names where practical.
- Docker Compose project and service names.
- Runtime directories.
- Environment variable names.
- Device default `server_base_url`.
- Product persona and model provider.
- Asset conversion and display module.

Do not keep religion/v6 public naming in user-facing logs, README, deployment files, or product prompts, except in migration notes that explain the origin.

Also explicitly remove or disable copied v6 religion-specific behavior:

- Old religion system prompts.
- Old religion few-shot examples.
- Old religion/RAG knowledge data.
- Old runtime defaults that route to v6 production cloud state.

Phase 1 has no coffee RAG. It also must not accidentally preserve or query any old v6 RAG data.

### Cloud Deployment Isolation

Target Guangzhou server layout:

```text
/app/20260601_tiny_chicken_coffee_robot
/app/20260601_tiny_chicken_coffee_robot/data
/app/20260601_tiny_chicken_coffee_robot/logs
/app/20260601_tiny_chicken_coffee_robot/assets
```

Suggested Compose project:

```text
tiny_chicken_coffee_robot
```

Suggested containers:

```text
tiny_chicken_coffee_robot-api-1
tiny_chicken_coffee_robot-worker-1
tiny_chicken_coffee_robot-redis-1
```

Data must be separate from v6:

- Separate SQLite file.
- Separate Redis instance or at minimum a strict key prefix; a separate Redis container is preferred.
- Separate logs.
- Separate `.env` with tiny-specific variable names.
- No shared `greenunion-sh` runtime state.

Phase 1 deployment can use IP + port. Domain and TLS are deferred until device/cloud behavior is stable.

Secrets and certificates:

- Runtime secrets are supplied only on the Guangzhou server through a local `.env` or equivalent secret injection mechanism.
- `.env`, private keys, API tokens, Wi-Fi credentials, and certificates must never be committed.
- Health checks and probes must report presence/status only, never full values.
- The implementation plan must identify who supplies `TINY_ARK_API_KEY`, Volcengine TTS credentials, and any ASR fallback credentials before deployment.
- Key rotation and TLS certificate handling are deferred operational tasks, but the repo must not bake in placeholder real credentials.

## Device Design

### Hardware Baseline

Use the v6 ESP32-S3-style baseline but target:

- 32MB Flash.
- 8MB PSRAM.
- Display connected through SPI/QSPI-class interface; exact driver and rotation are not yet fixed.
- Existing v6 audio chain, Wi-Fi, WakeNet, OTA structure as the starting point.

The source material's BK7258/128MB Flash line is not the phase 1 implementation target.

The implementation plan must include a 32MB Flash partition design before packaging assets. The partition budget must account for:

- Bootloader and partition table.
- NVS and OTA metadata.
- Two OTA app slots if OTA rollback is retained.
- WakeNet/model partition.
- SPIFFS or asset storage for prompt audio and display assets.
- Optional reserved space for future config/assets.

Do not assume the current 16MB v6 partition table is valid for the 32MB display variant. Measure the converted MJPEG asset set and app binary before finalizing the table.

### Wake and Reprovisioning

Phase 1 keeps:

- Wake word: `小明同学`.
- Existing WakeNet integration.
- GPIO7 voice/wake trigger behavior from current v6.
- GPIO0 runtime long-press Wi-Fi reprovision behavior from current v6 if copied after the GPIO0 change.

Future wake word customization to `小机仔` or variants like `你好小机仔` is explicitly deferred because wake word model production takes time.

### Display Module

Add a display abstraction but do not lock the driver too early.

Configuration should include:

```text
DISPLAY_WIDTH=320
DISPLAY_HEIGHT=240
DISPLAY_SAFE_SIZE=240
DISPLAY_SAFE_X=<configurable>
DISPLAY_SAFE_Y=<configurable>
DISPLAY_ROTATION=0|90|180|270
```

The 240x240 safe region exists to protect expressions and text from rounded-corner, circular, or other physical mask occlusion. The implementation plan must confirm the actual screen shape/mask and choose `DISPLAY_SAFE_X/Y` from hardware observation or customer material.

Phase 1 display behavior:

- Provide a display service/state machine that can show standby, wakeup, listening, thinking, speaking, happy, sad, angry, surprise, shutdown states.
- If actual display driver/GPIO details are not ready, provide stubbed driver interfaces and compile-time guards.
- Do not make the audio pipeline depend on display readiness.
- Display errors should degrade to audio-only behavior.

### Visual Asset Format

Runtime format should be MCU-friendly:

```text
<asset>.mjpeg
<asset>.idx
```

Conversion target:

- Safe frame size: 240x240.
- FPS: 15.
- JPEG quality baseline: `-q:v 5`.
- Source: uploaded AVI Motion JPEG assets.
- Runtime: pure MJPEG stream plus index, not AVI/MP4 parsing.

Baseline conversion command:

```bash
ffmpeg -y -i input.avi \
  -vf "fps=15,scale=240:240:force_original_aspect_ratio=decrease,pad=240:240:(ow-iw)/2:(oh-ih)/2:black" \
  -q:v 5 -an -f mjpeg output.mjpeg
```

The `.idx` should store at minimum:

```text
magic/version
width=240
height=240
fps=15
frame_count
frame offset + frame size entries
```

The implementation plan must define `.idx` byte order, loop markers, animation names, and the asset manifest/registry format before firmware playback code depends on it.

The first firmware iteration may include only a curated subset of assets if partition size remains tight. With 32MB Flash, full current converted asset set is plausible but still must be measured after conversion.

Early device validation must include a display throughput test for 240x240 MJPEG playback at the target frame rate. If 15fps is not stable with the chosen decoder and display bus, reduce FPS or asset complexity before broadening the asset set.

## Cloud Model Flow

### Preferred Flow

Target flow:

```text
ESP32-S3 Opus audio uplink
-> tiny cloud realtime session
-> Doubao-Seed-2.0-mini multimodal audio request
-> text answer
-> Volcengine TTS
-> Opus/PCM audio stream back to device
```

### Fallback Flow

If official Doubao-Seed-2.0-mini API does not support direct audio input, or the audio request fails with a capability/format error, fallback to:

```text
ESP32-S3 Opus audio uplink
-> current ASR provider
-> Doubao-Seed-2.0-mini text request
-> text answer
-> Volcengine TTS
-> Opus/PCM audio stream back to device
```

Fallback must be explicit in logs and trace fields. It must not silently pretend to be direct multimodal audio.

### Doubao Provider

Create a dedicated provider layer, for example:

```text
src/providers/tiny_doubao.py
```

Environment variables should be tiny-specific:

```text
TINY_ARK_API_KEY=...
TINY_DOUBAO_MODEL=doubao-seed-2-0-mini-260428
TINY_DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com
TINY_DOUBAO_ENDPOINT=<official endpoint from Volcengine doc>
```

The exact endpoint and payload shape must follow the official Volcengine documentation for Doubao-Seed-2.0-mini. If the docs require a `responses` endpoint, use it. If they require chat completions or a model-specific endpoint, isolate that choice inside the provider so the rest of the app remains stable.

Do not reuse v6 DashScope/Qwen LLM env names for tiny Doubao settings.

### Persona Prompt

Initial system/persona behavior:

- Identity: coffee-savvy tiny chicken shop assistant.
- Language: Chinese by default.
- Style: lively, short, concrete, friendly.
- Answer length: 1-3 sentences by default.
- Domain: coffee beans, hand brew, espresso, milk drinks, grind size, extraction, tasting notes, beginner recommendations.
- No coffee RAG in phase 1.

## App/Mini-Program Boundary

Do not implement app or mini-program in phase 1.

Reserve API surfaces for future:

- Device registration/binding.
- Device status.
- Firmware version and OTA status.
- Volume setting.
- Wake word setting placeholder.
- Display/animation state command placeholder.
- Alarm list/config placeholder.

BLE provisioning from the product material is future scope. Phase 1 may keep current Wi-Fi provisioning path unless a dedicated BLE provisioning requirement is later approved.

## Alarm Boundary

Alarm is documented but not part of phase 1 implementation unless separately approved.

Future alarm requirements from material:

- Create, query, delete, close, snooze by voice or app.
- Single, daily, and weekday repeat modes.
- At least 5 persisted alarms.
- Survive power loss.
- Ring for 60 seconds, auto-stop if no action.
- Standard error prompts for invalid time, past time, limit exceeded, no matching alarm, or time source failure.

## Testing Strategy

### Spec/Scaffold Phase

- Confirm new repo history and remote.
- Confirm copied v6 tests run before tiny-specific edits where practical.
- Add tests that guard renamed env/project defaults and prevent greenunion/v6 state leakage.
- Add regression tests or static checks that fail if copied v6 religion prompts, few-shot content, RAG data, or religion-specific runtime defaults remain enabled.

### Cloud Tests

- Run a secret scanner such as `gitleaks` or `trufflehog` before first push, then keep it as a pre-push or CI gate for the new repository.
- Unit-test Doubao provider request construction without printing secrets.
- Mock success text output.
- Mock audio-capability failure and verify fallback to ASR -> Doubao text.
- Verify TTS path remains compatible with text output.
- Verify healthz includes tiny Doubao/TTS readiness without exposing key material.

### Device Tests

- Keep existing ESP asset/release gate checks adapted for 32MB Flash.
- Add display config/static tests:
  - 320x240 display base.
  - 240x240 safe region.
  - configurable rotation.
  - MJPEG asset manifest format.
- Add asset conversion tests for `.mjpeg + .idx` if conversion scripts are added.

### Integration Tests

- Simulated audio upload to tiny API.
- Confirm session trace identifies whether direct Doubao audio path or fallback path was used.
- Confirm first audio chunk logs remain available.
- Confirm display state changes do not block audio.

## Deployment Plan Outline

1. Create `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot` from current v6 baseline.
2. Remove old `.git`, clean secret-bearing files by path/pattern without printing values, and initialize a new private repository history.
3. Confirm `.gitignore` and secret-scan rules before the first commit.
4. Initialize/bind new GitHub repository.
5. Rename product, compose project, env examples, README, and docs.
6. Explicitly remove or disable copied v6 religion prompts, few-shot data, RAG data, and production cloud defaults.
7. Design and validate the 32MB Flash partition table against app, model, prompt, and display asset sizes.
8. Add tiny Doubao provider and config.
9. Add fallback trace fields.
10. Add display module scaffolding and asset conversion scripts, including `.idx` byte order, loop markers, animation names, and manifest format.
11. Add Guangzhou deployment runbook, including secret injection and owner checklist.
12. SSH to Guangzhou server and create deployment directory only after the repo is ready and approved.
13. Deploy to IP + port for bring-up.
14. Move to domain/HTTPS only after device/cloud smoke tests pass.

## Open Risks

- Official Doubao-Seed-2.0-mini audio input support is not yet confirmed from a locally readable API example. The provider must isolate this uncertainty.
- Screen rotation and exact QSPI/SPI driver pins are not confirmed.
- 32MB Flash is likely enough for converted selected assets, but the partition table and full selected asset set must be measured after conversion.
- New-repository creation can leak secrets if v6 history or secret-bearing files are copied incorrectly. Use a clean copy, new git history, default-private repository, `.gitignore`, and no-value secret cleanup before first commit.
- Guangzhou server secret injection, certificate handling, and credential ownership must be defined before deployment.
- Copied v6 religion prompts/RAG data must be explicitly removed or disabled so product behavior cannot leak old domain content.
- Existing material says BLE provisioning, but phase 1 is not implementing app/mini-program or BLE provisioning.
- Product naming and future custom wake word are standardized as `小机仔`, while phase 1 uses `小明同学`.
- The extracted `device_unused.avi` was replaced by a valid separately uploaded AVI; still verify converted framing during asset conversion.

## Non-Goals For Phase 1

- Coffee RAG.
- Full app or mini-program.
- BLE provisioning.
- Custom `小机仔` wake word model.
- Doubao audio output.
- Alarm implementation.
- OTA publishing or release actions.
- Domain/HTTPS production hardening.
- Cloud deployment on `greenunion-sh`.
- Hardware migration to BK7258/128MB Flash.

## Success Criteria

- New repository and project are fully separated from v6 naming and deployment state.
- Cloud can run on Guangzhou server without touching greenunion-sh.
- Device can use the tiny server endpoint for audio interaction.
- Doubao provider either uses direct audio input or clearly falls back to ASR -> Doubao text.
- Text answer is converted to speech through Volcengine TTS and streamed back to the device.
- Display module can compile with configurable 320x240 display and 240x240 safe expression region.
- Converted MJPEG asset subset can be packaged and played through the display abstraction when hardware driver details are ready.
