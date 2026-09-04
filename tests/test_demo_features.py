from __future__ import annotations

import time

from src.api import demo as demo_api
from src.services.demo_diagnostics import DemoDiagnostics, demo_diagnostics
from src.services import park_navigation as navigation


def setup_function() -> None:
    demo_diagnostics.reset()
    navigation.phone_locations.reset()


def test_diagnostics_keeps_bounded_events_and_copies_snapshot() -> None:
    diagnostics = DemoDiagnostics(max_events=2)
    diagnostics.set_connected("board-1", "conversation-1")
    diagnostics.record("asr_final", device_id="board-1", asr_text="你好")
    diagnostics.record("answer_ready", device_id="board-1", answer="你好呀")

    snapshot = diagnostics.snapshot()
    assert [event["event"] for event in snapshot["recent_events"]] == [
        "answer_ready",
        "asr_final",
    ]
    assert snapshot["devices"][0]["online"] is True
    snapshot["devices"][0]["answer"] = "changed"
    assert diagnostics.snapshot()["devices"][0]["answer"] == "你好呀"


def test_new_connection_clears_previous_conversation_summary() -> None:
    diagnostics = DemoDiagnostics()
    diagnostics.set_connected("board-1", "conversation-1")
    diagnostics.record(
        "answer_ready",
        device_id="board-1",
        conversation_id="conversation-1",
        turn_index=2,
        asr_text="旧问题",
        answer="旧答案",
        memory=[{"question": "旧问题"}],
    )

    diagnostics.set_connected("board-1", "conversation-2")

    device = diagnostics.snapshot()["devices"][0]
    assert device["conversation_id"] == "conversation-2"
    assert device["turn_index"] is None
    assert device["asr_text"] == ""
    assert device["answer"] == ""
    assert device["memory"] == []


def test_phone_location_and_navigation_api() -> None:
    update = demo_api.update_phone_location(
        demo_api.PhoneLocationUpdate(
            device_id="board-1",
            latitude=31.14574,
            longitude=121.65533,
            accuracy=8,
        )
    )
    route = demo_api.demo_navigation(
        device_id="board-1",
        destination="zootopia_hot_pursuit",
    )

    assert update["status"] == "ok"
    assert route["status"] == "ok"
    assert "疯狂动物城" in route["answer"]
    assert "方向" in route["answer"]


def test_voice_navigation_requests_phone_location_first() -> None:
    answer = navigation.answer_navigation_question("带我去创极速光轮", "board-1")

    assert answer is not None
    assert "手机位置" in answer


def test_stale_phone_location_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(navigation.settings, "phone_location_ttl_seconds", 10)
    current = time.time()
    monkeypatch.setattr(navigation.time, "time", lambda: current)
    navigation.phone_locations.update("board-1", 31.14574, 121.65533, 5)
    monkeypatch.setattr(navigation.time, "time", lambda: current + 11)

    assert navigation.phone_locations.get("board-1") is None
    assert navigation.phone_locations.get("board-1", include_stale=True) is not None


def test_demo_pages_are_available() -> None:
    assert demo_api.demo_console().status_code == 200
    assert demo_api.park_guide().status_code == 200
    payload = demo_api.demo_devices()
    assert "disney-vocat-demo-001" in payload["devices"]
    assert any(item["key"] == "zootopia_hot_pursuit" for item in payload["pois"])
