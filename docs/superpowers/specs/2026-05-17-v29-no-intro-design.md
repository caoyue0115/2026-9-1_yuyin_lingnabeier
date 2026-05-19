# v29 No-Intro Design

## Goal

v29 disables the realtime answer intro prompt while keeping the touch-to-record prompt unchanged.

## Scope

- Default `DEMO_REALTIME_INTRO_ENABLED` becomes `0`.
- `record_prompt_1.pcm` remains enabled through `DEMO_RECORD_PROMPT_ENABLED=1`.
- `intro_1.pcm` stays in SPIFFS for rollback and A/B comparison.
- OTA dry-run polling remains unchanged.
- No cloud deployment is required for this change.

## Runtime Behavior

After ASR returns a realtime session, the board skips `stage=intro` and opens the cloud audio stream directly. Startup still mounts SPIFFS when either the realtime intro or record prompt path may be used, so disabling intro must not break the pre-record prompt.

## Verification

- Asset tests must prove no-intro is the default and record prompt stays enabled.
- Asset tests must prove SPIFFS is mounted when the record prompt is enabled even if intro is disabled.
- Full Python tests and ESP-IDF build must pass before packaging.
- Daily hardware delivery must use a compile-only package with SHA256. Full handoff packages are archival only, and flash-only packages are temporary quick-flash artifacts.
