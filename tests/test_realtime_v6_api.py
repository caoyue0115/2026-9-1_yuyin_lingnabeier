from __future__ import annotations

import asyncio
import json
import time

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
