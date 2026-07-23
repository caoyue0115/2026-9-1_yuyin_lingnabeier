# V7 Phase 1 Network And Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver deterministic five-network Wi-Fi switching, startup/network prompts, and a v6 persistent WebSocket conversation with up to three follow-ups while preserving v5 behavior.

**Architecture:** The server gains a separate v6 protocol/FSM and an owned conversation session with bounded audio buffering and cancellation. Firmware vendors the Wi-Fi component, introduces pure policy/controller modules, a single prompt arbiter, and a cancellable playback session before wiring them into `main.c`. Phase 1 keeps WakeNet paused during cloud playback but exposes the cancellation boundary required by Phase 2.

**Tech Stack:** Python 3.11, FastAPI/WebSocket, Pydantic, pytest/unittest, ESP-IDF v5.5.4, ESP32-S3, FreeRTOS, ESP WebSocket Client, ESP-SR/Opus, NVS, gitleaks.

---

## File Structure

- Create `src/models/conversation_v6.py`: v6 message enums, validation, correlation fields, limits, and turn outcomes.
- Create `src/services/conversation_v6.py`: conversation FSM, current-turn owner, cancellation token, bounded worker lifecycle, and context commit rules.
- Create `src/storage/conversation_v6_store.py`: bounded byte queue and temporary conversation/turn records.
- Create `src/api/realtime_v6.py`: `/api/v6/realtime/conversation/opus-stream` and canceled-audio HTTP 410 handling.
- Modify `src/app.py`, `src/settings.py`: register v6 and expose explicit limits.
- Create `tests/test_realtime_v6_protocol.py`, `tests/test_realtime_v6_session.py`, `tests/test_realtime_v6_api.py`: fake-clock FSM, cancellation, limits, and golden traces.
- Create `esp_idf_demo/host_tests/v7_policy_test.cc` and `v7_conversation_controller_test.c`: Linux host tests for pure firmware policy/FSM code.
- Vendor `esp_idf_demo/components/esp-wifi-connect/`: tracked fork of registry version 3.1.4 with license/source record.
- Create `esp_idf_demo/main/wifi_credential_store.{h,cc}`: versioned NVS migration and five-entry LRU policy.
- Create `esp_idf_demo/main/wifi_connection_policy.{h,cc}`: scan grouping, RSSI order, 3-second candidate cap, 8-second boot deadline, and 15/30/60 schedule.
- Create `esp_idf_demo/main/prompt_arbiter.{h,c}`: one prompt queue, priorities, dedupe, and deferred network prompts.
- Create `esp_idf_demo/main/playback_session.{h,c}`: owned HTTP/decode/jitter/output lifecycle with idempotent cancel/join.
- Create `esp_idf_demo/main/cloud_conversation.{h,c}`: v6 persistent WebSocket and correlated turn messages.
- Create `esp_idf_demo/main/conversation_controller.{h,c}`: initial question, three follow-ups, re-prompt, and normal/error endings.
- Modify `esp_idf_demo/main/app_network.{h,cc}`, `cloud_client.{h,c}`, `main.c`, `config.h`, `CMakeLists.txt`, `idf_component.yml`: integration only.
- Add `esp_idf_demo/spiffs/network_required_1.pcm` and `esp_idf_demo/spiffs/conversation_done_1.pcm`: fixed “请联网” and “善哉” resources.
- Create `scripts/v7_phase1_gate.py`: authoritative protocol/resource/build gate.
- Create `docs/deploy/v7-production-security-gate.md`: tracked customer-release security checklist; it does not block COM4 demo work.
- Create `docs/deploy/v7-phase1-acceptance.md`: sanitized build, server, COM4, and soak evidence.
- Modify `tests/test_esp_assets.py`, `tests/test_esp_runtime_guards.py`: tracked-component, asset, OTA order, and integration guards.

## Task 1: Lock The V6 Protocol And FSM

**Files:**
- Create: `src/models/conversation_v6.py`
- Create: `tests/test_realtime_v6_protocol.py`

- [ ] **Step 1: Write failing schema and transition tests**

Add tests that construct every message with `conversation_id`, `turn_id`, and `turn_index`, reject mismatches, reset binary sequence per turn, and cover `asr_empty`, `technical_error`, `rejected`, `played`, cancel, duplicate frame, and sequence conflict. Use this golden trace as the minimum happy path:

```python
GOLDEN_PLAYED = [
    ("conversation_start", "conversation_ready"),
    ("turn_start", "ack"),
    ("binary:0", "ack:0"),
    ("turn_end", "asr_final"),
    ("asr_final", "turn_result"),
    ("turn_playback_complete", "turn_complete:played"),
    ("conversation_end", "conversation_done"),
]

def test_empty_asr_finishes_before_reprompt() -> None:
    fsm = TurnStateMachine(turn_id="t1", turn_index=1)
    fsm.on_turn_start()
    fsm.on_turn_end()
    event = fsm.on_asr_empty()
    assert event.type == "turn_complete"
    assert event.outcome == TurnOutcome.ASR_EMPTY
    assert fsm.is_terminal
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_realtime_v6_protocol.py -q`

Expected: import failure for `src.models.conversation_v6`.

- [ ] **Step 3: Implement the protocol module**

Define these exact public types and limits:

```python
class TurnState(StrEnum):
    IDLE = "idle"
    RECEIVING = "receiving"
    PROCESSING = "processing"
    RESULT_READY = "result_ready"
    PLAYING = "playing"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class TurnOutcome(StrEnum):
    PLAYED = "played"
    ASR_EMPTY = "asr_empty"
    TECHNICAL_ERROR = "technical_error"
    REJECTED = "rejected"

MAX_TURNS = 4
MAX_FRAME_BYTES = 4096
MAX_TURN_AUDIO_BYTES = 16_000 * 2 * 8
MAX_CONNECTION_SECONDS = 180
```

Implement `parse_client_control(payload)`, `TurnStateMachine`, `accept_frame(sequence, digest)`, and event builders. ACK means highest contiguous frame only. Duplicate sequence plus same digest is accepted; a changed digest raises `ProtocolError("sequence_conflict")`.

- [ ] **Step 4: Run protocol tests and commit**

Run: `python -m pytest tests/test_realtime_v6_protocol.py -q`

Expected: all pass.

Commit: `git add src/models/conversation_v6.py tests/test_realtime_v6_protocol.py; git commit -m "feat: define v6 conversation protocol"`

## Task 2: Add Bounded Conversation Ownership And Cancellation

**Files:**
- Create: `src/storage/conversation_v6_store.py`
- Create: `src/services/conversation_v6.py`
- Create: `tests/test_realtime_v6_session.py`
- Modify: `src/settings.py`

- [ ] **Step 1: Write failing bounded-buffer and cancellation tests**

Cover byte-based backpressure, producer wakeup, `cancel()` idempotence, worker join within two seconds, canceled URL state, context status, and quota idempotence by `turn_id`:

```python
def test_cancel_is_a_barrier_and_revokes_audio() -> None:
    session = ConversationSession.for_test(max_audio_queue_bytes=8)
    turn = session.start_turn("t1", 0)
    turn.audio.put(b"12345678")
    session.cancel_turn("t1")
    assert turn.join(timeout=2.0)
    assert turn.audio.revoked
    assert session.event_log[-1].type == "turn_cancelled"
    assert session.audio_http_status("t1") == 410
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_realtime_v6_session.py -q`

Expected: missing modules.

- [ ] **Step 3: Implement the store and owner**

Use `collections.deque`, `threading.Condition`, and a byte counter rather than `chunks: []`. `BoundedAudioQueue.put()` waits only while space is unavailable and immediately raises `TurnCancelled` when the shared `threading.Event` is set. `ConversationSession` retains the worker `Future`, calls provider close hooks, joins before emitting `turn_cancelled`, and never logs full question, answer, URL, device ID, or conversation ID. Refactor the current question-to-LLM/TTS worker behind a `run_turn(question, history, cancel_event, audio_queue)` adapter; check cancellation between ASR, retrieval, every LLM chunk, every TTS segment, and every queue write. Build `history` from at most the previous three committed turns and include `interrupted=true` on partial answers.

Add settings:

```python
conversation_v6_audio_queue_bytes: int = 256 * 1024
conversation_v6_cancel_timeout_seconds: float = 2.0
conversation_v6_close_timeout_seconds: float = 2.0
conversation_v6_question_chars: int = 512
conversation_v6_answer_chars: int = 4096
```

- [ ] **Step 4: Run focused and v5 regression tests**

Run: `python -m pytest tests/test_realtime_v6_session.py tests/test_realtime_api.py -q`

Expected: v6 tests pass and existing v5 tests remain unchanged.

- [ ] **Step 5: Commit**

Commit: `git add src/storage/conversation_v6_store.py src/services/conversation_v6.py src/settings.py tests/test_realtime_v6_session.py; git commit -m "feat: own and cancel v6 conversation turns"`

## Task 3: Expose The V6 WebSocket And Audio Contract

**Files:**
- Create: `src/api/realtime_v6.py`
- Create: `tests/test_realtime_v6_api.py`
- Modify: `src/app.py`

- [ ] **Step 1: Write failing API tests**

Use FastAPI `TestClient` and fake providers. Assert one connection handles four turns, a fifth returns `turn_limit_exceeded`, malformed and late events are rejected, two missing pong intervals close with `keepalive_timeout`, canceled audio returns 410, and v5 golden behavior still closes after one result.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_realtime_v6_api.py -q`

Expected: route not found.

- [ ] **Step 3: Implement and register the router**

Create `router = APIRouter()` with:

```python
@router.websocket("/api/v6/realtime/conversation/opus-stream")
async def conversation_opus_stream(websocket: WebSocket, x_device_id: str = Header(default="")) -> None:
    await websocket.accept()
    session = conversation_registry.create(device_id=x_device_id)
    await ConversationSocket(websocket, session).run()

@router.get("/api/v6/realtime/conversations/{conversation_id}/turns/{turn_id}/audio")
def conversation_audio(conversation_id: str, turn_id: str, token: str):
    return conversation_registry.open_audio(conversation_id, turn_id, token)
```

The WebSocket adapter owns only transport and delegates state to `ConversationSession`. Bind binary frames to the sole active `RECEIVING` turn. Reject absent/mismatched correlation fields. Generate a cryptographically random, short-lived per-turn audio token, require it on the HTTP route, bind it to device/conversation/turn, and return 410 after cancellation. Send transport ping every 15 seconds and close after 30 seconds with no pong or server data. Register `realtime_v6.router` in `src/app.py` without editing the v5 endpoint.

- [ ] **Step 4: Run API, protocol, and v5 tests**

Run: `python -m pytest tests/test_realtime_v6_api.py tests/test_realtime_v6_protocol.py tests/test_realtime_api.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

Commit: `git add src/api/realtime_v6.py src/app.py tests/test_realtime_v6_api.py; git commit -m "feat: expose persistent v6 conversations"`

## Task 4: Vendor Wi-Fi 3.1.4 And Implement Versioned Credentials

**Files:**
- Create: `esp_idf_demo/components/esp-wifi-connect/**`
- Create: `esp_idf_demo/components/esp-wifi-connect/UPSTREAM.md`
- Create: `esp_idf_demo/main/wifi_credential_store.h`
- Create: `esp_idf_demo/main/wifi_credential_store.cc`
- Modify: `esp_idf_demo/main/idf_component.yml`
- Modify: `esp_idf_demo/main/CMakeLists.txt`
- Modify: `tests/test_esp_assets.py`

- [ ] **Step 1: Add failing ownership and migration guards**

Assert the tracked component exists, `idf_component.yml` no longer contains `78/esp-wifi-connect`, max credentials equals five, legacy keys are read-only, active schema is committed only after verification, and build credentials are seeded only when both schemas are empty.

- [ ] **Step 2: Copy the locked component without generated metadata**

Copy registry version 3.1.4 from `esp_idf_demo/managed_components/78__esp-wifi-connect` to `esp_idf_demo/components/esp-wifi-connect`, preserving license files. Add `UPSTREAM.md` containing package `78/esp-wifi-connect`, version `3.1.4`, and the old `dependencies.lock` integrity value. Do not copy build output or secrets.

- [ ] **Step 3: Implement the credential API**

Expose:

```cpp
struct WifiCredential { std::string ssid; std::string password; uint64_t last_success; };
class WifiCredentialStore {
 public:
  esp_err_t LoadAndMigrate();
  std::vector<WifiCredential> List() const;
  esp_err_t Upsert(const std::string&, const std::string&);
  esp_err_t MarkSuccessful(const std::string&);
};
```

Write new records to a temporary namespace, commit, read back and validate, then set the active marker. Keep legacy keys untouched. Deduplicate SSIDs, retain five, and evict the smallest `last_success`. Replace the fork's direct `SsidManager` reads/writes in station and configuration-AP paths with this store so there is only one credential owner.

- [ ] **Step 4: Run guards and compile the component**

Run: `python -m unittest tests.test_esp_assets.EspAssetTests.test_wifi_board_lite_uses_esp_wifi_connect_hotspot_provisioning`

Then load ESP-IDF and run: `idf.py -C esp_idf_demo reconfigure build`

Expected: dependency resolves from `components/`, not `managed_components`.

- [ ] **Step 5: Commit**

Commit: `git add esp_idf_demo/components/esp-wifi-connect esp_idf_demo/main/wifi_credential_store.h esp_idf_demo/main/wifi_credential_store.cc esp_idf_demo/main/idf_component.yml esp_idf_demo/main/CMakeLists.txt tests/test_esp_assets.py; git commit -m "feat: own wifi credentials and migration"`

## Task 5: Implement Deterministic Network Policy And Prompt Arbitration

**Files:**
- Create: `esp_idf_demo/main/wifi_connection_policy.{h,cc}`
- Create: `esp_idf_demo/main/prompt_arbiter.{h,c}`
- Modify: `esp_idf_demo/main/app_network.{h,cc}`
- Modify: `esp_idf_demo/main/config.h`
- Modify: `esp_idf_demo/main/CMakeLists.txt`
- Add: `esp_idf_demo/spiffs/network_required_1.pcm`
- Add: `esp_idf_demo/spiffs/conversation_done_1.pcm`
- Create: `esp_idf_demo/host_tests/v7_policy_test.cc`
- Modify: `tests/test_esp_assets.py`

- [ ] **Step 1: Add red contract tests**

Assert `GreenMotive`, five credentials, boot deadline `8000`, candidate cap `3000`, runtime prompt `12000`, retries `{15000,30000,60000}`, no-credential AP persistence, five-minute reconfigure timeout, SmartConfig disabled, and semantic prompt IDs rather than direct playback from network callbacks.

- [ ] **Step 2: Implement policy with monotonic deadlines**

Expose pure functions `wifi_policy_rank_scan()`, `wifi_policy_candidate_deadline()`, and `wifi_policy_next_rescan_deadline()`. Group BSSIDs by SSID and retain strongest RSSI. On a 3-second candidate timeout call disconnect before trying the next candidate. Use absolute timestamps so scan duration does not shift 15/30/60 schedules.

Keep this module free of ESP/FreeRTOS calls. In `v7_policy_test.cc`, inject timestamps and scans for duplicate BSSIDs, strongest-invalid/second-valid, five stored credentials, the 8-second global cutoff, and exact 15/30/60/120-second deadlines. Compile and run it in the Linux gate with `g++ -std=c++17`.

- [ ] **Step 3: Implement the prompt arbiter**

Use these IDs and priorities:

```c
typedef enum {
    PROMPT_BOOT_BELL = 10,
    PROMPT_NETWORK_CONNECTED = 20,
    PROMPT_CONVERSATION_DONE = 30,
    PROMPT_SPEAK = 40,
    PROMPT_NETWORK_REQUIRED = 50,
    PROMPT_TECHNICAL_ERROR = 60,
} prompt_id_t;
```

Provide `prompt_arbiter_submit(id, dedupe_key)`, `prompt_arbiter_set_conversation_active(bool)`, and a single owner task. Defer network prompts during recording/cloud playback and discard them if connectivity has recovered before dequeue.

- [ ] **Step 4: Add and validate PCM resources**

Both files must be 16kHz mono signed 16-bit LE. Embed them, `intro_1.pcm`, and the existing `boot_amitabha_1.pcm` into the app with `target_add_binary_data`; assert nonzero, even byte length, SHA-256 recorded in the test, and app-only OTA reachability. The network prompt player must use linker symbols, not SPIFFS paths.

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest tests.test_esp_assets tests.test_esp_runtime_guards`

Expected: pass.

Commit: `git add esp_idf_demo/main/wifi_connection_policy.h esp_idf_demo/main/wifi_connection_policy.cc esp_idf_demo/main/prompt_arbiter.h esp_idf_demo/main/prompt_arbiter.c esp_idf_demo/main/app_network.h esp_idf_demo/main/app_network.cc esp_idf_demo/main/config.h esp_idf_demo/main/CMakeLists.txt esp_idf_demo/spiffs/network_required_1.pcm esp_idf_demo/spiffs/conversation_done_1.pcm esp_idf_demo/host_tests/v7_policy_test.cc tests/test_esp_assets.py; git commit -m "feat: add deterministic wifi and prompt policy"`

## Task 6: Add Cancellable Playback And Persistent Firmware Conversation

**Files:**
- Create: `esp_idf_demo/main/playback_session.{h,c}`
- Create: `esp_idf_demo/main/cloud_conversation.{h,c}`
- Modify: `esp_idf_demo/main/cloud_client.{h,c}`
- Modify: `esp_idf_demo/main/CMakeLists.txt`
- Modify: `tests/test_esp_runtime_guards.py`

- [ ] **Step 1: Add failing interface/race guards**

Require these exact public APIs:

```c
typedef struct playback_session playback_session_t;
esp_err_t playback_session_start(const char *url, playback_session_t **out);
esp_err_t playback_session_cancel(playback_session_t *session, int reason);
esp_err_t playback_session_join(playback_session_t *session, TickType_t timeout);

typedef struct cloud_conversation cloud_conversation_t;
esp_err_t cloud_conversation_open(cloud_conversation_t **out);
esp_err_t cloud_conversation_start_turn(cloud_conversation_t *, uint8_t turn_index, const char *turn_id);
esp_err_t cloud_conversation_finish_turn(cloud_conversation_t *, cloud_realtime_session_t *result);
esp_err_t cloud_conversation_cancel_turn(cloud_conversation_t *, const char *turn_id);
esp_err_t cloud_conversation_close(cloud_conversation_t *, const char *reason);
```

- [ ] **Step 2: Move downlink ownership into `playback_session`**

Move HTTP handle, decode task, jitter queues, playback task, and one atomic cancel flag out of call-local `cloud_client_stream_realtime_audio`. All tasks check the same flag. `cancel` only signals; the owner joins tasks, drains queues, closes HTTP/output, and records one terminal result. Natural EOF, cancel, and network error must converge on the same cleanup function.

- [ ] **Step 3: Implement v6 WebSocket transport**

Reuse framed-v1 Opus packets but reset sequence for each `turn_id`. Validate all correlation fields, ACK semantics, turn outcomes, 15-second ping, 30-second timeout, and two-second close timeout. Do not alter `cloud_client_opus_uplink_*` v5 functions.

- [ ] **Step 4: Build and commit**

Run: `idf.py -C esp_idf_demo build`

Expected: ESP32-S3 build succeeds and app remains below 3,145,728 bytes.

Commit: `git add esp_idf_demo/main/playback_session.h esp_idf_demo/main/playback_session.c esp_idf_demo/main/cloud_conversation.h esp_idf_demo/main/cloud_conversation.c esp_idf_demo/main/cloud_client.h esp_idf_demo/main/cloud_client.c esp_idf_demo/main/CMakeLists.txt tests/test_esp_runtime_guards.py; git commit -m "feat: add cancellable v6 playback session"`

## Task 7: Integrate The Four-Turn Conversation Controller

**Files:**
- Create: `esp_idf_demo/main/conversation_controller.{h,c}`
- Create: `esp_idf_demo/host_tests/v7_conversation_controller_test.c`
- Modify: `esp_idf_demo/main/main.c`
- Modify: `esp_idf_demo/main/config.h`
- Modify: `tests/test_esp_runtime_guards.py`

- [ ] **Step 1: Add failing controller transition tests/guards**

Cover 0/1/2/3 follow-ups, five-second wait for speech start, 700ms tail VAD, one re-prompt with new `turn_id`, no quota use for empty ASR, 0.5-second delay after the third answer, “善哉” on normal end, and “请重试” only on technical failure.

- [ ] **Step 2: Implement a table-driven controller**

Expose `conversation_controller_handle(event)` over explicit states `IDLE`, `PROMPTING`, `RECORDING`, `WAITING_RESULT`, `PLAYING`, `FOLLOWUP_WINDOW`, `REPROMPT`, `ENDING`, and `FAILED`. The controller owns `turn_index` and follow-up count; it does not own sockets, codec handles, or prompt files.

Keep transition logic free of FreeRTOS calls. The host test drives a fake monotonic clock through 0/1/2/3 follow-ups, five-second start windows, one ASR-empty re-prompt with a new `turn_id`, technical failure, and the 0.5-second final delay.

- [ ] **Step 3: Replace the single long pipeline entry**

Keep the existing v5 path behind its current feature selection. Route v7 through the controller, preconnect WebSocket while “请讲” plays, pause WakeNet during cloud playback, keep the socket open through follow-up windows, and close only after `conversation_done` or two seconds.

- [ ] **Step 4: Run focused tests and commit**

Run:

```powershell
python -m pytest tests/test_realtime_v6_protocol.py tests/test_realtime_v6_session.py tests/test_realtime_v6_api.py -q
python -m unittest tests.test_esp_assets tests.test_esp_runtime_guards
```

Expected: all pass.

Commit: `git add esp_idf_demo/main/conversation_controller.h esp_idf_demo/main/conversation_controller.c esp_idf_demo/main/main.c esp_idf_demo/main/config.h esp_idf_demo/host_tests/v7_conversation_controller_test.c tests/test_esp_runtime_guards.py; git commit -m "feat: add three-turn follow-up controller"`

## Task 8: Move OTA Validation Before Blocking Network Startup

**Files:**
- Modify: `esp_idf_demo/main/main.c`
- Modify: `tests/test_esp_assets.py`

- [ ] **Step 1: Add a failing source-order guard**

Assert the pending-state read and rollback timeout task creation appear before `app_network_start()`. Assert `esp_ota_mark_app_valid_cancel_rollback()` requires migration success, audio initialization, and `APP_NETWORK_CONNECTED_BIT`; missing credentials or timeout calls `esp_restart()` without marking valid.

- [ ] **Step 2: Split local validation from deferred reporting**

Start the pending watchdog before network startup. Factory images without pending state may remain in provisioning indefinitely. Pending OTA images never validate without credentials and an IP. Queue the cloud validation report after connectivity returns; reporting failure must not undo an already valid local decision.

- [ ] **Step 3: Run OTA guards and commit**

Run: `python -m unittest tests.test_esp_assets -k ota`

Expected: all OTA tests pass.

Commit: `git add esp_idf_demo/main/main.c tests/test_esp_assets.py; git commit -m "fix: start ota rollback validation before network"`

## Task 9: Authoritative Verification, Deploy, And COM4 Acceptance

**Files:**
- Create: `scripts/v7_phase1_gate.py`
- Create: `docs/deploy/v7-production-security-gate.md`
- Create: `docs/deploy/v7-phase1-acceptance.md`
- Build output only for firmware/server artifacts.

- [ ] **Step 1: Run the authoritative Linux/container suite**

Run in the project container with `libopus` installed:

```bash
python -m pytest -q
python -m unittest tests.test_esp_assets tests.test_esp_runtime_guards
g++ -std=c++17 -Iesp_idf_demo/main esp_idf_demo/host_tests/v7_policy_test.cc esp_idf_demo/main/wifi_connection_policy.cc -o /tmp/v7_policy_test && /tmp/v7_policy_test
gcc -std=c11 -Iesp_idf_demo/main esp_idf_demo/host_tests/v7_conversation_controller_test.c esp_idf_demo/main/conversation_controller.c -o /tmp/v7_controller_test && /tmp/v7_controller_test
python scripts/v7_phase1_gate.py
```

Expected: zero failures; record passed/skipped totals and golden v5/v6 traces.

- [ ] **Step 2: Run source and secret checks**

Run:

```powershell
git diff --check
gitleaks git --staged --redact --no-banner
```

Expected: no new findings; pre-existing vendor/example findings are recorded separately.

- [ ] **Step 3: Record the customer-release security gate**

Create `docs/deploy/v7-production-security-gate.md` with unchecked release blockers for HTTPS/WSS CA validation, per-device signed identity, replay protection, token revocation, signed OTA/secure boot, Flash/NVS encryption, debug-interface policy, and credential rotation/revocation. State explicitly that COM4 demo may use HTTP/WS and open AP, while customer batch release may not pass until every item has evidence.

- [ ] **Step 4: Build the N16R8 firmware**

Run from `esp_idf_demo` after ESP-IDF export:

```powershell
$env:SDKCONFIG_DEFAULTS='sdkconfig.defaults;sdkconfig.defaults.vocat_lowcost_16m8m'
idf.py fullclean build
```

Expected: build succeeds; app is below 3,145,728 bytes and the report includes remaining bytes, internal heap baseline, largest block, PSRAM, task stacks, and handle counts.

- [ ] **Step 5: Deploy server v5+v6 and run smoke tests**

Deploy to `greenunion-sh`, then run existing v5 smoke plus a v6 four-turn golden trace. Do not print credentials, full questions/answers, device IDs, session IDs, or audio URLs.

- [ ] **Step 6: Flash and accept on COM4**

Run: `idf.py -p COM4 flash monitor`

Verify no credentials, two saved networks with strongest invalid, home-to-hotspot switch, one “请联网” per outage, one recovery “阿弥陀佛”, provisioning success, 0/1/2/3 follow-ups, re-prompt, normal “善哉”, technical “请重试”, and OTA pending rollback with invalid migration/no IP. Run 50 valid turns and confirm resources return to baseline.

Write aggregate results, public firmware hash, app size, pass/fail, and non-sensitive resource minima to `docs/deploy/v7-phase1-acceptance.md`.

- [ ] **Step 7: Commit gate records**

Commit only non-sensitive summaries and public hashes after staging the named acceptance document: `git add docs/deploy/v7-phase1-acceptance.md scripts/v7_phase1_gate.py docs/deploy/v7-production-security-gate.md; git commit -m "test: record v7 phase1 acceptance"`.
