from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services import pet_games
from src.services.pet_companion import get_pet_snapshot, process_pet_turn
from src.settings import settings
from src.storage.db import connect, init_db


@pytest.fixture()
def game_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "games.db"))
    init_db()
    return tmp_path / "games.db"


def _at(second: int = 0) -> datetime:
    return datetime(2026, 9, 7, 2, 0, second, tzinfo=timezone.utc)


def test_user_gives_three_clues_then_judy_guesses_and_receives_verdict(game_db) -> None:
    start = process_pet_turn("陪我玩", "board-1", "t1", now=_at())
    selected = process_pet_turn("你来猜，我说线索", "board-1", "t2", now=_at(1))
    clue_one = process_pet_turn("她是一位女王", "board-1", "t3", now=_at(2))
    clue_two = process_pet_turn("她有一个妹妹", "board-1", "t4", now=_at(3))
    clue_three = process_pet_turn("她会冰雪魔法", "board-1", "t5", now=_at(4))
    verdict = process_pet_turn("猜对了", "board-1", "t6", now=_at(5))

    assert start.game_active is True
    assert start.max_turns == 10
    assert selected.game["game_type"] == "user_clues"
    assert "第二条" in clue_one.answer
    assert "最后一条" in clue_two.answer
    assert clue_three.answer is None
    assert clue_three.action == "game_judy_guess"
    assert "她是一位女王" in clue_three.prompt_context
    assert "她会冰雪魔法" in clue_three.prompt_context
    assert verdict.game_active is False
    assert verdict.max_turns == 4
    assert verdict.profile.mood == "excited"
    assert verdict.profile.energy == 92


def test_player_gets_up_to_three_guesses_from_fixed_clues(game_db, monkeypatch) -> None:
    monkeypatch.setattr(
        pet_games.secrets,
        "choice",
        lambda candidates: next(item for item in pet_games.QUESTION_BANK if item.key == "judy"),
    )
    start = process_pet_turn("我来猜，你出题", "board-1", "t1", now=_at())
    wrong_one = process_pet_turn("尼克", "board-1", "t2", now=_at(1))
    wrong_two = process_pet_turn("艾莎", "board-1", "t3", now=_at(2))
    correct = process_pet_turn("是朱迪", "board-1", "t4", now=_at(3))

    assert "第一条线索" in start.answer
    assert "兔子" in start.answer
    assert "第二条线索" in wrong_one.answer
    assert "第三条线索" in wrong_two.answer
    assert "猜对啦" in correct.answer
    assert correct.game_active is False
    assert correct.profile.mood == "excited"
    assert correct.game["guess_count"] == 3


def test_three_wrong_guesses_reveal_answer_and_finish(game_db, monkeypatch) -> None:
    monkeypatch.setattr(
        pet_games.secrets,
        "choice",
        lambda candidates: next(item for item in pet_games.QUESTION_BANK if item.key == "judy"),
    )
    process_pet_turn("我来猜，你出题", "board-1", "t1", now=_at())
    process_pet_turn("尼克", "board-1", "t2", now=_at(1))
    process_pet_turn("艾莎", "board-1", "t3", now=_at(2))
    finished = process_pet_turn("米奇", "board-1", "t4", now=_at(3))

    assert "答案是兔朱迪" in finished.answer
    assert finished.game_active is False
    assert finished.profile.mood == "happy"
    assert finished.profile.energy == 89


def test_game_expires_after_five_minutes(game_db) -> None:
    start_time = _at()
    process_pet_turn("陪我玩", "board-1", "t1", now=start_time)
    expired = process_pet_turn(
        "我来猜",
        "board-1",
        "t2",
        now=start_time + timedelta(seconds=301),
    )

    assert "超过五分钟" in expired.answer
    assert expired.game_active is False
    assert expired.game["stage"] == "expired"


def test_game_stops_on_tenth_total_interaction(game_db) -> None:
    current = process_pet_turn("陪我玩", "board-1", "t1", now=_at())
    for index in range(2, 10):
        current = process_pet_turn("我还没选好", "board-1", f"t{index}", now=_at(index))
        assert current.game_active is True
    limited = process_pet_turn("我还没选好", "board-1", "t10", now=_at(10))

    assert "十轮" in limited.answer
    assert limited.game_active is False
    assert limited.game["turn_count"] == 10


def test_exit_command_finishes_active_game_immediately(game_db) -> None:
    process_pet_turn("陪我玩", "board-1", "t1", now=_at())
    stopped = process_pet_turn("不玩了", "board-1", "t2", now=_at(1))

    assert "先停在这里" in stopped.answer
    assert stopped.game_active is False
    assert stopped.game["stage"] == "quit"


def test_low_energy_changes_mood_and_blocks_new_game(game_db) -> None:
    process_pet_turn("你好", "board-1", "t1", now=_at())
    conn = connect()
    try:
        conn.execute("UPDATE pet_profiles SET energy = 5 WHERE device_id = 'board-1'")
        conn.commit()
    finally:
        conn.close()

    blocked = process_pet_turn("陪我玩", "board-1", "t2", now=_at(1))

    assert "没电" in blocked.answer
    assert blocked.profile.energy == 5
    assert blocked.profile.mood == "sleepy"
    assert blocked.game_active is False


def test_persisted_mood_changes_the_next_game_opening(game_db) -> None:
    process_pet_turn("我喜欢你", "board-1", "t1", now=_at())

    started = process_pet_turn("陪我玩", "board-1", "t2", now=_at(1))

    assert "我正想和你玩" in started.answer
    assert "开心时温暖鼓励" in started.prompt_context


def test_public_snapshot_hides_random_answer(game_db, monkeypatch) -> None:
    monkeypatch.setattr(
        pet_games.secrets,
        "choice",
        lambda candidates: next(item for item in pet_games.QUESTION_BANK if item.key == "judy"),
    )
    process_pet_turn("我来猜，你出题", "board-1", "t1", now=_at())

    game = get_pet_snapshot("board-1", now=_at(1))["game"]

    assert game["active"] is True
    assert "answer_key" not in game
    assert "answer_label" not in game
