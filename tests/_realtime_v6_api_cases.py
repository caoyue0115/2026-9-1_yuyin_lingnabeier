from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import Future

import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.api import realtime_v6


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


def test_turn_result_is_sent_before_streaming_tts_worker_finishes(monkeypatch) -> None:
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
        worker.set_result(None)
        await task

    asyncio.run(run_until_result())
