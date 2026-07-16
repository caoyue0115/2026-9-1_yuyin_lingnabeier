# v7 Phase 1 Acceptance

## Scope

Phase 1 covers the startup chime, deterministic multi-Wi-Fi selection, local network prompts, persistent v6 conversation WebSocket, up to three follow-up turns, and the fixed final "善哉" prompt. Wake-word barge-in remains phase 2.

## Automated Gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Focused v6 API and release-gate tests | Pass | 4 tests passed on Windows |
| ESP-IDF compile | Pass | Clean ESP32-S3 N16R8 build completed |
| App partition size gate | Pass | 2,006,752 bytes; 1,138,976 bytes remain in the 3 MiB OTA slot |
| Source contract gate | Pass | v6, five-slot Wi-Fi policy, conversation controller, and pre-network OTA watchdog verified |
| Linux full suite | Pass | 311 tests, 5 subtests, and both C/C++ host binaries passed in the release container |

App SHA-256: `f56ddac92c596358031453b21ed05e06602d279506a8ae7fcca8b2ffeecd2c01`

## Deployment And Hardware

| Check | Result | Notes |
| --- | --- | --- |
| greenunion-sh API rebuild and health check | Pass | Revision `e53d6f4`; local/public health checks passed on port 80 |
| v6 production control-plane smoke | Pass | Four-turn limit and the single same-index ASR-empty retry both passed |
| COM4 full flash | Pending | Device re-enumerated as COM10 before flash; awaiting explicit port authorization |
| Boot chime and network prompt sequence | Pending | Chime first; "请联网" only after foreground failure; "阿弥陀佛" after connection |
| Stored Wi-Fi switching | Pending | Validate at least two saved networks and an unavailable preferred network |
| Four-turn conversation | Pending | Initial answer plus three follow-ups on one WebSocket |
| Final prompt | Pending | About 500 ms after the fourth answer completes, play "善哉" |
| Button and wake-word start | Pending | Both entry paths must start phase 1 conversation |

## Privacy Rules

Acceptance records contain only pass/fail status, timings, artifact hashes, and truncated identifiers. Do not record credentials, SSIDs, complete device or session identifiers, signed audio URLs, access tokens, or customer audio/transcripts.

## Production Boundary

This acceptance is for the authorized COM4 demo device. Customer-batch release remains blocked by [v7-production-security-gate.md](v7-production-security-gate.md).
