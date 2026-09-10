from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import Future

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.app import app
from src.api import realtime_v6
from src.models.conversation_v6 import ConversationLimits, MAX_CONNECTION_SECONDS, ProtocolError
from src.providers.asr import ASRResult
from src.services.conversation_v6 import TurnRunResult


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    realtime_v6.conversation_registry.reset()
    yield
    realtime_v6.conversation_registry.reset()


def _conversation_start(client_conversation_id: str = "client-1") -> dict:
    return {
        "type": "conversation_start",
        "client_conversation_id": client_conversation_id,
        "device_id": "board-1",
        "audio_format": "opus",
        "protocol_version": "v6",
        "answer_mode": "streaming",
    }


def test_websocket_accepts_four_cancelled_turns_then_rejects_fifth() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v6/realtime/conversation/opus-stream",
            headers={"x-device-id": "board-1"},
        ) as websocket:
            websocket.send_json(_conversation_start())
            ready = websocket.receive_json()
            assert ready["type"] == "conversation_ready"
            conversation_id = ready["conversation_id"]

            for index in range(4):
                turn_id = f"turn-{index}"
                websocket.send_json(
                    {
                        "type": "turn_start",
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "turn_index": index,
                    }
                )
                assert websocket.receive_json()["type"] == "ack"
                websocket.send_json(
                    {
                        "type": "turn_cancel",
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "turn_index": index,
                    }
                )
                assert websocket.receive_json()["type"] == "turn_cancelled"

            websocket.send_json(
                {
                    "type": "turn_start",
                    "conversation_id": conversation_id,
                    "turn_id": "turn-4",
                    "turn_index": 4,
                }
            )
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "turn_limit_exceeded"


def test_websocket_allows_one_asr_empty_retry_with_same_turn_index() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v6/realtime/conversation/opus-stream",
            headers={"x-device-id": "board-1"},
        ) as websocket:
            websocket.send_json(_conversation_start())
            conversation_id = websocket.receive_json()["conversation_id"]

            for turn_id in ("turn-0", "turn-0-retry"):
                control = {
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "turn_index": 0,
                }
                websocket.send_json({"type": "turn_start", **control})
                assert websocket.receive_json()["type"] == "ack"
                websocket.send_json({"type": "turn_end", **control})
                complete = websocket.receive_json()
                assert complete["type"] == "turn_complete"
                assert complete["outcome"] == "asr_empty"

            websocket.send_json(
                {
                    "type": "turn_start",
                    "conversation_id": conversation_id,
                    "turn_id": "turn-0-retry-2",
                    "turn_index": 0,
                }
            )
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "turn_index_conflict"


def test_websocket_allows_touch_relisten_cancel_at_same_turn_index() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v6/realtime/conversation/opus-stream",
            headers={"x-device-id": "board-1"},
        ) as websocket:
            websocket.send_json(_conversation_start())
            conversation_id = websocket.receive_json()["conversation_id"]

            for attempt in range(3):
                control = {
                    "conversation_id": conversation_id,
                    "turn_id": f"turn-0-touch-{attempt}",
                    "turn_index": 0,
                }
                websocket.send_json({"type": "turn_start", **control})
                assert websocket.receive_json()["type"] == "ack"
                websocket.send_json(
                    {"type": "turn_cancel", "reason": "restart_listening", **control}
                )
                assert websocket.receive_json()["type"] == "turn_cancelled"


def test_websocket_cancels_thinking_without_waiting_for_asr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asr_started = threading.Event()
    release_asr = threading.Event()

    def blocked_transcription(_socket: object, _turn_id: str) -> str:
        asr_started.set()
        release_asr.wait(timeout=5.0)
        return "这条已取消的问题不应进入上下文"

    monkeypatch.setattr(
        realtime_v6.ConversationSocket,
        "_transcribe_turn",
        blocked_transcription,
    )

    try:
        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/v6/realtime/conversation/opus-stream",
                headers={"x-device-id": "board-1"},
            ) as websocket:
                websocket.send_json(_conversation_start())
                conversation_id = websocket.receive_json()["conversation_id"]
                control = {
                    "conversation_id": conversation_id,
                    "turn_id": "turn-0-thinking",
                    "turn_index": 0,
                }
                websocket.send_json({"type": "turn_start", **control})
                assert websocket.receive_json()["type"] == "ack"
                websocket.send_json({"type": "turn_end", **control})
                assert asr_started.wait(timeout=1.0)

                cancel_started = time.monotonic()
                websocket.send_json(
                    {"type": "turn_cancel", "reason": "restart_listening", **control}
                )
                assert websocket.receive_json()["type"] == "turn_cancelled"
                assert time.monotonic() - cancel_started < 1.0

                websocket.send_json(
                    {
                        "type": "turn_start",
                        "conversation_id": conversation_id,
                        "turn_id": "turn-0-after-thinking-touch",
                        "turn_index": 0,
                    }
                )
                assert websocket.receive_json()["type"] == "ack"
                release_asr.set()
    finally:
        release_asr.set()


def test_websocket_disconnect_removes_registry_session() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v6/realtime/conversation/opus-stream",
            headers={"x-device-id": "board-1"},
        ) as websocket:
            websocket.send_json(_conversation_start())
            conversation_id = websocket.receive_json()["conversation_id"]
            websocket.send_json(
                {
                    "type": "conversation_end",
                    "conversation_id": conversation_id,
                    "reason": "normal",
                }
            )
            assert websocket.receive_json()["type"] == "conversation_done"

        assert realtime_v6.conversation_registry.get(conversation_id) is None


def test_malformed_and_late_controls_are_rejected_without_mutating_turn() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v6/realtime/conversation/opus-stream",
            headers={"x-device-id": "board-1"},
        ) as websocket:
            websocket.send_text("{")
            assert websocket.receive_json()["code"] == "invalid_control_json"

            websocket.send_json(_conversation_start())
            ready = websocket.receive_json()
            conversation_id = ready["conversation_id"]
            start = {
                "type": "turn_start",
                "conversation_id": conversation_id,
                "turn_id": "turn-0",
                "turn_index": 0,
            }
            websocket.send_json(start)
            websocket.receive_json()
            websocket.send_json({**start, "type": "turn_cancel"})
            websocket.receive_json()
            websocket.send_json({**start, "type": "turn_end"})
            late = websocket.receive_json()
            assert late["type"] == "error"
            assert late["code"] == "invalid_state"


def test_binary_without_receiving_turn_is_rejected() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v6/realtime/conversation/opus-stream",
            headers={"x-device-id": "board-1"},
        ) as websocket:
            websocket.send_json(_conversation_start())
            websocket.receive_json()
            websocket.send_bytes(b"\x00\x00\x00\x00\x00\x00\x00\x01x")
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "no_receiving_turn"


def test_unknown_turn_returns_stable_error() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v6/realtime/conversation/opus-stream",
            headers={"x-device-id": "board-1"},
        ) as websocket:
            websocket.send_json(_conversation_start())
            conversation_id = websocket.receive_json()["conversation_id"]
            websocket.send_json(
                {
                    "type": "turn_cancel",
                    "conversation_id": conversation_id,
                    "turn_id": "missing",
                    "turn_index": 0,
                }
            )

            error = websocket.receive_json()

            assert error["type"] == "error"
            assert error["code"] == "turn_not_found"


def test_sequence_conflict_sends_error_then_closes_socket() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v6/realtime/conversation/opus-stream",
            headers={"x-device-id": "board-1"},
        ) as websocket:
            websocket.send_json(_conversation_start())
            conversation_id = websocket.receive_json()["conversation_id"]
            websocket.send_json(
                {
                    "type": "turn_start",
                    "conversation_id": conversation_id,
                    "turn_id": "turn-0",
                    "turn_index": 0,
                }
            )
            assert websocket.receive_json()["type"] == "ack"
            websocket.send_bytes(b"\x00\x00\x00\x00\x00\x00\x00\x01a")
            assert websocket.receive_json()["type"] == "ack"
            websocket.send_bytes(b"\x00\x00\x00\x00\x00\x00\x00\x01b")
            assert websocket.receive_json()["code"] == "sequence_conflict"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_pong_still_checks_absolute_connection_deadline() -> None:
    class FakeWebSocket:
        async def send_json(self, _payload: dict) -> None:
            pass

    session = realtime_v6.ConversationSession.for_test()
    session._limits = ConversationLimits(
        started_at=0.0,
        monotonic=lambda: MAX_CONNECTION_SECONDS + 1.0,
    )
    socket = realtime_v6.ConversationSocket(FakeWebSocket(), session, device_id="board-1")

    with pytest.raises(ProtocolError, match="connection_time_exceeded"):
        asyncio.run(socket._handle_text('{"type":"pong"}'))


def test_cancelled_audio_token_returns_410() -> None:
    session = realtime_v6.conversation_registry.create(device_id="board-1")
    session.start_turn("turn-0", 0)
    token = realtime_v6.conversation_registry.issue_audio_token(
        session.conversation_id,
        "turn-0",
        device_id="board-1",
    )
    session.cancel_turn("turn-0")

    with TestClient(app) as client:
        response = client.get(
            f"/api/v6/realtime/conversations/{session.conversation_id}/turns/turn-0/audio",
            params={"token": token},
            headers={"x-device-id": "board-1"},
        )

    assert response.status_code == 410
    assert response.json()["detail"] == "audio_revoked"


def test_audio_token_is_bound_to_device_conversation_turn_and_expiry() -> None:
    session = realtime_v6.conversation_registry.create(device_id="board-1")
    session.start_turn("turn-0", 0)
    token = realtime_v6.conversation_registry.issue_audio_token(
        session.conversation_id,
        "turn-0",
        device_id="board-1",
        ttl_seconds=0.01,
    )

    with TestClient(app) as client:
        wrong_device = client.get(
            f"/api/v6/realtime/conversations/{session.conversation_id}/turns/turn-0/audio",
            params={"token": token},
            headers={"x-device-id": "board-2"},
        )
        assert wrong_device.status_code == 403
        time.sleep(0.02)
        expired = client.get(
            f"/api/v6/realtime/conversations/{session.conversation_id}/turns/turn-0/audio",
            params={"token": token},
            headers={"x-device-id": "board-1"},
        )
        assert expired.status_code == 410


def test_audio_stream_declares_exact_pcm_format() -> None:
    session = realtime_v6.conversation_registry.create(device_id="board-1")
    turn = session.start_turn("turn-0", 0)
    turn.audio.put(b"\x01\x00\x02\x00")
    turn.audio.finish()
    token = realtime_v6.conversation_registry.issue_audio_token(
        session.conversation_id,
        "turn-0",
        device_id="board-1",
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v6/realtime/conversations/{session.conversation_id}/turns/turn-0/audio",
            params={"token": token},
            headers={"x-device-id": "board-1"},
        )

    assert response.status_code == 200
    assert response.content == b"\x01\x00\x02\x00"
    assert response.headers["x-audio-format"] == "pcm"
    assert response.headers["x-audio-sample-rate"] == "16000"
    assert response.headers["x-audio-sample-width"] == "16"
    assert response.headers["x-audio-channels"] == "1"
    assert response.headers["x-audio-endian"] == "little"


def test_audio_stream_returns_framed_opus_when_requested_and_enabled(monkeypatch) -> None:
    session = realtime_v6.conversation_registry.create(device_id="board-1")
    turn = session.start_turn("turn-0", 0)
    turn.audio.put(b"\x01\x00\x02\x00")
    turn.audio.finish()
    token = realtime_v6.conversation_registry.issue_audio_token(
        session.conversation_id,
        "turn-0",
        device_id="board-1",
    )
    monkeypatch.setattr(realtime_v6.settings, "realtime_audio_enable_opus", True)
    monkeypatch.setattr(realtime_v6, "opus_available", lambda: True)
    monkeypatch.setattr(
        realtime_v6,
        "encode_pcm_stream_to_framed_opus",
        lambda chunks, **_kwargs: iter([b"\x00\x01x"]),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v6/realtime/conversations/{session.conversation_id}/turns/turn-0/audio",
            params={"token": token},
            headers={
                "x-device-id": "board-1",
                "x-accept-audio-format": "opus,pcm",
            },
        )

    assert response.status_code == 200
    assert response.content == b"\x00\x00\x00\x00\x00\x00\x00\x03\x00\x01x"
    assert response.headers["x-audio-format"] == "opus"
    assert response.headers["x-audio-packetization"] == "framed-v1"
    assert response.headers["x-opus-sample-rate"] == "16000"
    assert response.headers["x-opus-channels"] == "1"
    assert response.headers["x-opus-frame-duration-ms"] == "60"


def test_two_missing_pong_intervals_close_with_keepalive_timeout() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []
            self.closed: tuple[int, str] | None = None

        async def receive(self) -> dict:
            await asyncio.sleep(60)
            return {}

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

        async def close(self, code: int, reason: str = "") -> None:
            self.closed = (code, reason)

    websocket = FakeWebSocket()
    with pytest.raises(realtime_v6.KeepaliveTimeout):
        asyncio.run(
            realtime_v6.receive_with_keepalive(
                websocket,
                conversation_id="conversation-1",
                interval_seconds=0.01,
                max_missed_intervals=2,
            )
        )

    assert [item["type"] for item in websocket.sent] == ["ping"]
    assert websocket.closed is not None
    assert websocket.closed[1] == "keepalive_timeout"


def test_turn_result_is_sent_before_first_audio_and_tts_worker_finishes(monkeypatch) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    session = realtime_v6.conversation_registry.create(device_id="board-1")
    turn = session.start_turn("turn-0", 0)
    turn.state_machine.on_turn_end()
    websocket = FakeWebSocket()
    socket = realtime_v6.ConversationSocket(websocket, session, device_id="board-1")
    worker: Future = Future()
    monkeypatch.setattr(socket, "_transcribe_turn", lambda _turn_id: "question")
    monkeypatch.setattr(session, "process_turn", lambda _turn_id, _question: worker)

    async def run_until_result() -> None:
        task = asyncio.create_task(socket._finish_turn("turn-0"))
        await asyncio.sleep(0.02)
        assert any(event["type"] == "turn_result" for event in websocket.sent)
        assert not worker.done()
        turn.audio.put(b"first-audio")
        worker.set_result(TurnRunResult(answer="answer"))
        await task

    asyncio.run(run_until_result())


def test_playback_complete_publishes_game_mode_limit_and_mood() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    session = realtime_v6.conversation_registry.create(device_id="board-1")
    turn = session.start_turn("turn-0", 0)
    turn.state_machine.on_turn_end()
    turn.state_machine.on_asr_final("陪我玩")
    turn.state_machine.on_turn_result(
        session_id="session-1",
        audio_stream_url="/audio",
    )
    turn.interaction_mode = "game"
    turn.max_turns = 10
    turn.pet_mood = "happy"
    websocket = FakeWebSocket()
    socket = realtime_v6.ConversationSocket(websocket, session, device_id="board-1")
    socket.started = True

    asyncio.run(
        socket._handle_text(
            json.dumps(
                {
                    "type": "turn_playback_complete",
                    "conversation_id": session.conversation_id,
                    "turn_id": turn.turn_id,
                    "turn_index": turn.turn_index,
                }
            )
        )
    )

    complete = websocket.sent[-1]
    assert complete["type"] == "turn_complete"
    assert complete["interaction_mode"] == "game"
    assert complete["max_turns"] == 10
    assert complete["pet_mood"] == "happy"


def test_first_audio_deadline_closes_early_url_as_technical_error(monkeypatch) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    session = realtime_v6.conversation_registry.create(device_id="board-1")
    turn = session.start_turn("turn-0", 0)
    turn.state_machine.on_turn_end()
    websocket = FakeWebSocket()
    socket = realtime_v6.ConversationSocket(websocket, session, device_id="board-1")
    worker: Future = Future()
    monkeypatch.setattr(socket, "_transcribe_turn", lambda _turn_id: "question")
    monkeypatch.setattr(session, "process_turn", lambda _turn_id, _question: worker)
    monkeypatch.setattr(
        realtime_v6.settings,
        "conversation_v6_first_audio_timeout_seconds",
        0.01,
    )

    asyncio.run(socket._finish_turn("turn-0"))

    assert [event["type"] for event in websocket.sent][-2:] == [
        "turn_result",
        "turn_complete",
    ]
    assert websocket.sent[-1]["outcome"] == "technical_error"
    assert turn.status == "technical_error"
    assert turn.audio.revoked


def test_asr_empty_text_completes_turn_as_asr_empty(monkeypatch) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    session = realtime_v6.conversation_registry.create(device_id="board-1")
    turn = session.start_turn("turn-0", 0)
    turn.state_machine.on_turn_end()
    websocket = FakeWebSocket()
    socket = realtime_v6.ConversationSocket(websocket, session, device_id="board-1")
    socket._frames[turn.turn_id] = {0: b"opus"}
    monkeypatch.setattr(realtime_v6, "decode_framed_opus_to_pcm", lambda *_args, **_kwargs: (b"\0\0", {}))
    monkeypatch.setattr(realtime_v6, "save_pcm_as_wav", lambda *_args, **_kwargs: "audio.wav")
    monkeypatch.setattr(
        realtime_v6,
        "transcribe_wav_result",
        lambda _path: ASRResult(None, "asr_empty_text", "empty"),
    )

    asyncio.run(socket._finish_turn(turn.turn_id))

    assert websocket.sent[-1]["type"] == "turn_complete"
    assert websocket.sent[-1]["outcome"] == "asr_empty"
    assert turn.status == "asr_empty"


def test_asr_timeout_requests_a_retry_instead_of_hanging(monkeypatch) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    session = realtime_v6.conversation_registry.create(device_id="board-1")
    turn = session.start_turn("turn-0", 0)
    turn.state_machine.on_turn_end()
    websocket = FakeWebSocket()
    socket = realtime_v6.ConversationSocket(websocket, session, device_id="board-1")
    socket._frames[turn.turn_id] = {0: b"opus"}
    monkeypatch.setattr(realtime_v6, "decode_framed_opus_to_pcm", lambda *_args, **_kwargs: (b"\0\0", {}))
    monkeypatch.setattr(realtime_v6, "save_pcm_as_wav", lambda *_args, **_kwargs: "audio.wav")
    monkeypatch.setattr(
        realtime_v6,
        "transcribe_wav_result",
        lambda _path: ASRResult(None, "asr_timeout", "timeout"),
    )

    asyncio.run(socket._finish_turn(turn.turn_id))

    assert websocket.sent[-1]["type"] == "turn_complete"
    assert websocket.sent[-1]["outcome"] == "asr_empty"
    assert turn.status == "asr_empty"
