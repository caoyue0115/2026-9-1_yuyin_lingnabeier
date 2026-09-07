from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.providers.llm import _build_messages
from src.services import conversation_v6 as conversation_service
from src.services.pet_companion import get_pet_snapshot, process_pet_turn
from src.settings import settings
from src.storage.conversation_v6_store import BoundedAudioQueue
from src.storage.db import connect, init_db


@pytest.fixture()
def pet_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "pet.db"))
    init_db()
    return tmp_path / "pet.db"


def _at(day: int, hour: int = 2) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


def test_profile_is_persistent_and_scoped_by_device(pet_db) -> None:
    saved = process_pet_turn("我叫小悦。", "board-1", "turn-1", now=_at(7))
    recalled = process_pet_turn("你记得我叫什么吗？", "board-1", "turn-2", now=_at(7, 3))
    other = process_pet_turn("你记得我叫什么吗？", "board-2", "turn-3", now=_at(7, 3))

    assert saved.handled is True
    assert saved.memories == {"name": "小悦"}
    assert "小悦" in recalled.answer
    assert "还没有" in other.answer
    assert get_pet_snapshot("board-1")["memories"] == {"name": "小悦"}
    assert get_pet_snapshot("board-2")["memories"] == {}


def test_pet_action_is_idempotent_for_same_turn(pet_db) -> None:
    first = process_pet_turn("摸摸你", "board-1", "turn-1", now=_at(7))
    repeated = process_pet_turn("摸摸你", "board-1", "turn-1", now=_at(7))
    second = process_pet_turn("再摸摸你", "board-1", "turn-2", now=_at(7, 3))

    assert first.profile.affection == 13  # first daily visit +1, pat +2
    assert repeated.profile.affection == 13
    assert repeated.duplicate_event is True
    assert second.profile.affection == 15
    conn = connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM pet_events WHERE device_id = 'board-1'").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_daily_streak_uses_china_standard_date_and_resets_after_gap(pet_db) -> None:
    day_one = process_pet_turn("你好", "board-1", "turn-1", now=_at(7, 2))
    next_day = process_pet_turn("你好", "board-1", "turn-2", now=_at(8, 2))
    after_gap = process_pet_turn("你好", "board-1", "turn-3", now=_at(10, 2))

    assert day_one.profile.streak_days == 1
    assert next_day.profile.streak_days == 2
    assert after_gap.profile.streak_days == 1
    assert after_gap.profile.affection == 13


def test_favorite_can_be_remembered_recalled_and_forgotten(pet_db) -> None:
    saved = process_pet_turn("我最喜欢艾莎。", "board-1", "turn-1", now=_at(7))
    recalled = process_pet_turn("我最喜欢谁？", "board-1", "turn-2", now=_at(7, 3))
    forgotten = process_pet_turn("忘掉我喜欢的东西", "board-1", "turn-3", now=_at(7, 4))
    missing = process_pet_turn("你还记得我喜欢什么吗？", "board-1", "turn-4", now=_at(7, 5))

    assert saved.memories["favorite"] == "艾莎"
    assert "艾莎" in recalled.answer
    assert "清掉" in forgotten.answer
    assert "还没告诉" in missing.answer


def test_status_and_play_actions_update_deterministic_state(pet_db) -> None:
    played = process_pet_turn("陪我玩", "board-1", "turn-1", now=_at(7))
    snapshot = get_pet_snapshot("board-1", now=_at(7) + timedelta(seconds=3))

    assert played.profile.mood == "happy"
    assert played.profile.energy == 89
    assert played.profile.affection == 12
    assert played.game_active is True
    assert "你想说三条线索" in played.answer
    assert snapshot["affection"] == 12
    assert snapshot["game"]["active"] is True


def test_companion_context_is_added_to_system_prompt() -> None:
    messages = _build_messages(
        "讲一个勇气的小故事",
        [],
        companion_context="设备长期陪伴档案：用户明确说自己叫小悦。",
    )

    assert "用户明确说自己叫小悦" in messages[0]["content"]
    assert "用户明确说自己叫小悦" not in messages[1]["content"]


def test_v6_pet_action_uses_existing_tts_path_without_llm(pet_db, monkeypatch) -> None:
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=32, cancel_event=cancel_event)
    monkeypatch.setattr(
        conversation_service,
        "_stream_answer_audio",
        lambda segments, answer: iter([b"pet-audio"]),
    )
    monkeypatch.setattr(
        conversation_service,
        "stream_answer_text",
        lambda *args, **kwargs: pytest.fail("pet action should not call LLM"),
    )

    result = conversation_service.run_turn(
        "摸摸你",
        [],
        cancel_event,
        audio,
        device_id="board-1",
        event_id="turn-1",
    )

    assert "耳朵" in result.answer
    assert audio.get() == b"pet-audio"


def test_general_v6_turn_passes_compact_device_memory_to_llm(pet_db, monkeypatch) -> None:
    process_pet_turn("我叫小悦。", "board-1", "memory-turn", now=_at(7))
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=32, cancel_event=cancel_event)
    captured: dict[str, str] = {}

    def answer(question, references, **kwargs):
        captured.update(kwargs)
        return iter(["当然可以。"])

    monkeypatch.setattr(conversation_service, "stream_answer_text", answer)
    monkeypatch.setattr(conversation_service, "realtime_tts_health", lambda: False)
    monkeypatch.setattr(
        conversation_service,
        "_stream_answer_audio",
        lambda segments, answer: iter([b"audio"]),
    )

    result = conversation_service.run_turn(
        "给我讲一个勇气的小故事",
        [],
        cancel_event,
        audio,
        device_id="board-1",
        event_id="turn-2",
    )

    assert result.answer == "当然可以。"
    assert "用户明确说自己叫小悦" in captured["companion_context"]
    assert len(captured["companion_context"]) < 160


def test_third_player_clue_uses_llm_guess_without_rag(pet_db, monkeypatch) -> None:
    process_pet_turn("你来猜，我说线索", "board-1", "game-1")
    process_pet_turn("她是一位女王", "board-1", "game-2")
    process_pet_turn("她有一个妹妹", "board-1", "game-3")
    captured: dict[str, object] = {}

    def answer(question, references, **kwargs):
        captured["question"] = question
        captured["references"] = references
        captured.update(kwargs)
        return iter(["我猜是艾莎，对吗？"])

    monkeypatch.setattr(conversation_service, "stream_answer_text", answer)
    monkeypatch.setattr(
        conversation_service,
        "retrieve_references",
        lambda *args, **kwargs: pytest.fail("game clue turn must not query RAG"),
    )
    monkeypatch.setattr(conversation_service, "realtime_tts_health", lambda: False)
    monkeypatch.setattr(
        conversation_service,
        "_stream_answer_audio",
        lambda segments, answer: iter([b"audio"]),
    )
    audio = BoundedAudioQueue(max_bytes=32, cancel_event=threading.Event())

    result = conversation_service.run_turn(
        "她会冰雪魔法",
        [],
        threading.Event(),
        audio,
        device_id="board-1",
        event_id="game-4",
    )

    assert result.answer == "我猜是艾莎，对吗？"
    assert result.interaction_mode == "game"
    assert result.max_turns == 10
    assert captured["references"] == []
    assert "她会冰雪魔法" in str(captured["companion_context"])
