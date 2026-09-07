from __future__ import annotations

import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


GAME_MAX_TURNS = 10
GAME_TTL_SECONDS = 5 * 60
GAME_MIN_ENERGY = 10

GAME_CHOOSE = "choose"
GAME_USER_CLUES = "user_clues"
GAME_JUDY_CLUES = "judy_clues"

_QUIT_PATTERN = re.compile(r"(?:不玩了|别玩了|结束游戏|退出游戏|停止游戏)")
_USER_CLUES_CHOICE = re.compile(r"(?:朱迪猜|你来猜|你猜|我说.{0,3}线索|我出线索)")
_JUDY_CLUES_CHOICE = re.compile(r"(?:我来猜|我猜|你说.{0,3}线索|你出线索|你出题|猜你的)")
_PLAY_REQUEST = re.compile(r"(?:陪我玩|和我玩|一起玩|玩个游戏|来玩游戏)")
_YES_PATTERN = re.compile(r"^(?:对|对的|是|是的|没错|猜对了|就是|正确)[呀啊啦吧。！!]*$")
_NO_PATTERN = re.compile(r"^(?:不对|不是|错了|猜错了|不正确)[呀啊啦吧。！!]*$")


@dataclass(frozen=True, slots=True)
class GameQuestion:
    key: str
    label: str
    aliases: tuple[str, ...]
    clues: tuple[str, str, str]


QUESTION_BANK = (
    GameQuestion(
        "judy",
        "兔朱迪",
        ("朱迪", "兔朱迪", "朱迪霍普斯", "朱迪·霍普斯"),
        ("她是一只兔子。", "她从兔窝镇来到大城市。", "她实现梦想，成为了一名警察。"),
    ),
    GameQuestion(
        "nick",
        "尼克",
        ("尼克", "狐尼克", "尼克王尔德", "尼克·王尔德"),
        ("他是一只狐狸。", "他曾经很会做冰棍生意。", "后来他成为朱迪的警察搭档。"),
    ),
    GameQuestion(
        "flash",
        "闪电",
        ("闪电", "树懒闪电"),
        ("他是一只树懒。", "他说话和动作都特别慢。", "他在动物城车辆管理局工作。"),
    ),
    GameQuestion(
        "elsa",
        "艾莎",
        ("艾莎", "冰雪女王"),
        ("她是一位女王。", "她有一位名叫安娜的妹妹。", "她拥有制造冰雪的魔法。"),
    ),
    GameQuestion(
        "stitch",
        "史迪奇",
        ("史迪奇", "实验品626", "实验品六二六"),
        ("他来自外太空。", "他的编号是六二六。", "他在夏威夷懂得了欧哈纳的意义。"),
    ),
    GameQuestion(
        "mickey",
        "米奇",
        ("米奇", "米奇老鼠"),
        ("他有一双圆圆的大耳朵。", "米妮是他非常重要的伙伴。", "他是最经典的迪士尼角色之一。"),
    ),
    GameQuestion(
        "baymax",
        "大白",
        ("大白", "Baymax", "baymax"),
        ("他看起来白白软软的。", "他是一台私人医疗机器人。", "他出现在《超能陆战队》的故事里。"),
    ),
    GameQuestion(
        "lightning_mcqueen",
        "闪电麦坤",
        ("闪电麦坤", "麦坤"),
        ("他不是动物，也不是人类。", "他热爱速度和比赛。", "他的车身上有醒目的九十五号。"),
    ),
)


@dataclass(frozen=True, slots=True)
class GameState:
    device_id: str
    game_id: str
    game_type: str
    status: str
    stage: str
    turn_count: int
    clue_count: int
    guess_count: int
    answer_key: str
    answer_label: str
    clues: tuple[str, ...]
    started_at: datetime
    expires_at: datetime

    def public_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(timezone.utc))
        active = self.status == "active" and current < self.expires_at
        return {
            "active": active,
            "game_type": self.game_type,
            "stage": self.stage,
            "turn_count": self.turn_count,
            "max_turns": GAME_MAX_TURNS,
            "clue_count": self.clue_count,
            "guess_count": self.guess_count,
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class GameDecision:
    handled: bool = False
    answer: str | None = None
    llm_instruction: str = ""
    action: str = ""
    active: bool = False
    energy_delta: int = 0
    affection_delta: int = 0
    mood: str | None = None
    state: GameState | None = None


def get_game_snapshot(conn: Any, device_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    state = _load_game(conn, device_id)
    return state.public_dict(now=now) if state is not None else None


def process_game_turn(
    conn: Any,
    device_id: str,
    question: str,
    *,
    energy: int,
    mood: str,
    now: datetime,
) -> GameDecision:
    current = _as_utc(now)
    normalized = _normalize(question)
    state = _load_game(conn, device_id)

    if state is not None and state.status == "active" and current >= state.expires_at:
        _finish_game(conn, state, stage="expired", now=current)
        if _looks_like_game_input(normalized):
            return GameDecision(
                handled=True,
                answer="刚才那局已经超过五分钟啦。重新说“陪我玩”，我们马上开新一局。",
                action="game_expired",
                mood="curious",
            )
        state = None

    if state is not None and state.status == "active" and _QUIT_PATTERN.search(normalized):
        finished = _finish_game(conn, state, stage="quit", now=current)
        return GameDecision(
            handled=True,
            answer="好，这局先停在这里。想再玩时叫我一声就行。",
            action="game_quit",
            active=False,
            mood="curious",
            state=finished,
        )

    if state is None or state.status != "active":
        game_type = _direct_game_type(normalized)
        if game_type is None and not _PLAY_REQUEST.search(normalized):
            return GameDecision()
        if energy < GAME_MIN_ENERGY:
            return GameDecision(
                handled=True,
                answer="我现在有点没电啦。给我一根胡萝卜，或者等我恢复些精力再玩吧。",
                action="game_low_energy",
                mood="sleepy",
            )
        if game_type == GAME_USER_CLUES:
            state = _create_game(conn, device_id, GAME_USER_CLUES, current)
            return GameDecision(
                handled=True,
                answer=(
                    f"{_game_start_lead(mood)}你每次说一条线索，一共三条，"
                    "我最后来猜。先给我第一条吧。"
                ),
                action="game_start_user_clues",
                active=True,
                energy_delta=-2,
                affection_delta=1,
                mood="curious",
                state=state,
            )
        if game_type == GAME_JUDY_CLUES:
            state = _create_game(conn, device_id, GAME_JUDY_CLUES, current)
            question_item = _question_for_state(state)
            return GameDecision(
                handled=True,
                answer=(
                    f"{_game_start_lead(mood)}我想好啦。第一条线索："
                    f"{question_item.clues[0]}你猜是谁？"
                ),
                action="game_start_judy_clues",
                active=True,
                energy_delta=-2,
                affection_delta=1,
                mood="curious",
                state=state,
            )
        state = _create_game(conn, device_id, GAME_CHOOSE, current)
        return GameDecision(
            handled=True,
            answer=(
                f"{_game_start_lead(mood)}你想说三条线索让我猜，"
                "还是让我说线索、你来猜？"
            ),
            action="game_choose",
            active=True,
            energy_delta=-1,
            affection_delta=1,
            mood="happy",
            state=state,
        )

    if state.turn_count >= GAME_MAX_TURNS - 1:
        finished = _finish_game(
            conn,
            state,
            stage="turn_limit",
            now=current,
            turn_count=GAME_MAX_TURNS,
        )
        return GameDecision(
            handled=True,
            answer="这一局已经玩到十轮啦，今天先记作一次开心的搭档训练。想玩还能再开一局。",
            action="game_turn_limit",
            active=False,
            energy_delta=2,
            mood="happy",
            state=finished,
        )

    if state.game_type == GAME_CHOOSE:
        return _choose_game(conn, state, normalized, current)
    if state.game_type == GAME_USER_CLUES:
        return _play_user_clues(conn, state, normalized, current)
    if state.game_type == GAME_JUDY_CLUES:
        return _play_judy_clues(conn, state, normalized, current)
    finished = _finish_game(conn, state, stage="invalid", now=current)
    return GameDecision(
        handled=True,
        answer="这局的线索出了点问题，我们重新开一局吧。",
        action="game_invalid",
        active=False,
        mood="curious",
        state=finished,
    )


def _choose_game(conn: Any, state: GameState, question: str, now: datetime) -> GameDecision:
    selected = _direct_game_type(question)
    turn_count = state.turn_count + 1
    if selected is None:
        updated = _update_game(conn, state, turn_count=turn_count, now=now)
        return GameDecision(
            handled=True,
            answer="告诉我“你来猜”，或者“我来猜”，我们就开始。",
            action="game_choose_retry",
            active=True,
            energy_delta=-1,
            mood="curious",
            state=updated,
        )
    if selected == GAME_USER_CLUES:
        updated = _update_game(
            conn,
            state,
            game_type=GAME_USER_CLUES,
            stage="collecting_clues",
            turn_count=turn_count,
            clues=(),
            now=now,
        )
        return GameDecision(
            handled=True,
            answer="收到，你每次说一条线索，一共三条。先给我第一条吧。",
            action="game_select_user_clues",
            active=True,
            energy_delta=-1,
            mood="curious",
            state=updated,
        )
    item = _choose_question(state.answer_key)
    updated = _update_game(
        conn,
        state,
        game_type=GAME_JUDY_CLUES,
        stage="guessing",
        turn_count=turn_count,
        clue_count=1,
        answer_key=item.key,
        answer_label=item.label,
        clues=(),
        now=now,
    )
    return GameDecision(
        handled=True,
        answer=f"我想好啦。第一条线索：{item.clues[0]}你猜是谁？",
        action="game_select_judy_clues",
        active=True,
        energy_delta=-1,
        mood="curious",
        state=updated,
    )


def _play_user_clues(conn: Any, state: GameState, question: str, now: datetime) -> GameDecision:
    next_turn = state.turn_count + 1
    if state.stage == "collecting_clues":
        clues = (*state.clues, question[:80])
        clue_count = len(clues)
        if clue_count < 3:
            updated = _update_game(
                conn,
                state,
                turn_count=next_turn,
                clue_count=clue_count,
                clues=clues,
                now=now,
            )
            ordinal = "第二条" if clue_count == 1 else "最后一条"
            return GameDecision(
                handled=True,
                answer=f"第{clue_count}条记下了，再给我{ordinal}线索。",
                action="game_user_clue",
                active=True,
                energy_delta=-1,
                mood="curious",
                state=updated,
            )
        updated = _update_game(
            conn,
            state,
            stage="awaiting_verdict",
            turn_count=next_turn,
            clue_count=3,
            clues=clues,
            now=now,
        )
        clue_text = "；".join(clues)
        instruction = (
            f"正在玩角色猜谜。玩家给出的三条线索是：{clue_text}。"
            "只猜一个最可能的迪士尼角色，严格用“我猜是……，对吗？”回答；"
            "不要列出多个候选，不解释推理，也不要添加别的内容。"
        )
        return GameDecision(
            handled=False,
            llm_instruction=instruction,
            action="game_judy_guess",
            active=True,
            energy_delta=-1,
            mood="curious",
            state=updated,
        )
    if state.stage == "awaiting_verdict":
        if _NO_PATTERN.match(question):
            updated = _update_game(
                conn,
                state,
                stage="awaiting_reveal",
                turn_count=next_turn,
                now=now,
            )
            return GameDecision(
                handled=True,
                answer="哎呀，被你难住了！正确答案是谁？",
                action="game_judy_wrong",
                active=True,
                energy_delta=-1,
                mood="curious",
                state=updated,
            )
        if _YES_PATTERN.match(question):
            finished = _finish_game(conn, state, stage="judy_correct", now=now, turn_count=next_turn)
            return GameDecision(
                handled=True,
                answer="耶，我猜对啦！这次线索训练让我一下子精神起来了。",
                action="game_judy_correct",
                active=False,
                energy_delta=7,
                mood="excited",
                state=finished,
            )
        updated = _update_game(conn, state, turn_count=next_turn, now=now)
        return GameDecision(
            handled=True,
            answer="告诉我“猜对了”或者“不对”，我才能结算这局哦。",
            action="game_verdict_retry",
            active=True,
            energy_delta=-1,
            mood="curious",
            state=updated,
        )
    if state.stage == "awaiting_reveal":
        answer = question.strip(" ，。！？,.!?")[:20] or "这个角色"
        finished = _finish_game(conn, state, stage="revealed", now=now, turn_count=next_turn)
        return GameDecision(
            handled=True,
            answer=f"原来是{answer}！这条线索我记住玩法了，这局也很有意思。",
            action="game_revealed",
            active=False,
            energy_delta=3,
            mood="happy",
            state=finished,
        )
    return GameDecision()


def _play_judy_clues(conn: Any, state: GameState, question: str, now: datetime) -> GameDecision:
    item = _question_for_state(state)
    next_turn = state.turn_count + 1
    next_guess = state.guess_count + 1
    if _guess_matches(question, item):
        finished = _finish_game(
            conn,
            state,
            stage="player_correct",
            now=now,
            turn_count=next_turn,
            guess_count=next_guess,
        )
        return GameDecision(
            handled=True,
            answer=f"猜对啦，就是{item.label}！漂亮，这局让我的心情变得超好。",
            action="game_player_correct",
            active=False,
            energy_delta=7,
            mood="excited",
            state=finished,
        )
    if next_guess >= 3:
        finished = _finish_game(
            conn,
            state,
            stage="player_out_of_guesses",
            now=now,
            turn_count=next_turn,
            guess_count=next_guess,
        )
        return GameDecision(
            handled=True,
            answer=f"三次机会用完啦，答案是{item.label}。别灰心，陪我玩完这局我还是很开心。",
            action="game_player_out_of_guesses",
            active=False,
            energy_delta=3,
            mood="happy",
            state=finished,
        )
    next_clue_count = min(state.clue_count + 1, 3)
    updated = _update_game(
        conn,
        state,
        turn_count=next_turn,
        clue_count=next_clue_count,
        guess_count=next_guess,
        now=now,
    )
    ordinal = "第二" if next_clue_count == 2 else "第三"
    return GameDecision(
        handled=True,
        answer=f"还不对。{ordinal}条线索：{item.clues[next_clue_count - 1]}再猜一次。",
        action="game_player_wrong",
        active=True,
        energy_delta=-1,
        mood="curious",
        state=updated,
    )


def _create_game(conn: Any, device_id: str, game_type: str, now: datetime) -> GameState:
    item = _choose_question("") if game_type == GAME_JUDY_CLUES else None
    state = GameState(
        device_id=device_id,
        game_id=str(uuid.uuid4()),
        game_type=game_type,
        status="active",
        stage=(
            "choosing"
            if game_type == GAME_CHOOSE
            else "collecting_clues"
            if game_type == GAME_USER_CLUES
            else "guessing"
        ),
        turn_count=1,
        clue_count=1 if item else 0,
        guess_count=0,
        answer_key=item.key if item else "",
        answer_label=item.label if item else "",
        clues=(),
        started_at=now,
        expires_at=now + timedelta(seconds=GAME_TTL_SECONDS),
    )
    _write_game(conn, state, now)
    return state


def _update_game(
    conn: Any,
    state: GameState,
    *,
    game_type: str | None = None,
    status: str | None = None,
    stage: str | None = None,
    turn_count: int | None = None,
    clue_count: int | None = None,
    guess_count: int | None = None,
    answer_key: str | None = None,
    answer_label: str | None = None,
    clues: tuple[str, ...] | None = None,
    now: datetime,
) -> GameState:
    updated = GameState(
        device_id=state.device_id,
        game_id=state.game_id,
        game_type=state.game_type if game_type is None else game_type,
        status=state.status if status is None else status,
        stage=state.stage if stage is None else stage,
        turn_count=state.turn_count if turn_count is None else turn_count,
        clue_count=state.clue_count if clue_count is None else clue_count,
        guess_count=state.guess_count if guess_count is None else guess_count,
        answer_key=state.answer_key if answer_key is None else answer_key,
        answer_label=state.answer_label if answer_label is None else answer_label,
        clues=state.clues if clues is None else clues,
        started_at=state.started_at,
        expires_at=state.expires_at,
    )
    _write_game(conn, updated, now)
    return updated


def _finish_game(
    conn: Any,
    state: GameState,
    *,
    stage: str,
    now: datetime,
    turn_count: int | None = None,
    guess_count: int | None = None,
) -> GameState:
    return _update_game(
        conn,
        state,
        status="completed",
        stage=stage,
        turn_count=turn_count,
        guess_count=guess_count,
        now=now,
    )


def _write_game(conn: Any, state: GameState, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO pet_games(
            device_id, game_id, game_type, status, stage, turn_count,
            clue_count, guess_count, answer_key, answer_label, clues_json,
            started_at, expires_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            game_id = excluded.game_id,
            game_type = excluded.game_type,
            status = excluded.status,
            stage = excluded.stage,
            turn_count = excluded.turn_count,
            clue_count = excluded.clue_count,
            guess_count = excluded.guess_count,
            answer_key = excluded.answer_key,
            answer_label = excluded.answer_label,
            clues_json = excluded.clues_json,
            started_at = excluded.started_at,
            expires_at = excluded.expires_at,
            updated_at = excluded.updated_at
        """,
        (
            state.device_id,
            state.game_id,
            state.game_type,
            state.status,
            state.stage,
            state.turn_count,
            state.clue_count,
            state.guess_count,
            state.answer_key,
            state.answer_label,
            json.dumps(list(state.clues), ensure_ascii=False),
            state.started_at.isoformat(),
            state.expires_at.isoformat(),
            now.isoformat(),
        ),
    )


def _load_game(conn: Any, device_id: str) -> GameState | None:
    row = conn.execute("SELECT * FROM pet_games WHERE device_id = ?", (device_id,)).fetchone()
    if row is None:
        return None
    try:
        clues = tuple(str(item) for item in json.loads(row["clues_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        clues = ()
    return GameState(
        device_id=str(row["device_id"]),
        game_id=str(row["game_id"]),
        game_type=str(row["game_type"]),
        status=str(row["status"]),
        stage=str(row["stage"]),
        turn_count=int(row["turn_count"]),
        clue_count=int(row["clue_count"]),
        guess_count=int(row["guess_count"]),
        answer_key=str(row["answer_key"] or ""),
        answer_label=str(row["answer_label"] or ""),
        clues=clues,
        started_at=_parse_datetime(row["started_at"]),
        expires_at=_parse_datetime(row["expires_at"]),
    )


def _question_for_state(state: GameState) -> GameQuestion:
    for item in QUESTION_BANK:
        if item.key == state.answer_key:
            return item
    return QUESTION_BANK[0]


def _choose_question(previous_key: str) -> GameQuestion:
    candidates = [item for item in QUESTION_BANK if item.key != previous_key] or list(QUESTION_BANK)
    return secrets.choice(candidates)


def _guess_matches(guess: str, item: GameQuestion) -> bool:
    normalized = _compact(guess)
    return any(_compact(alias).lower() in normalized.lower() for alias in item.aliases)


def _direct_game_type(question: str) -> str | None:
    if _USER_CLUES_CHOICE.search(question):
        return GAME_USER_CLUES
    if _JUDY_CLUES_CHOICE.search(question):
        return GAME_JUDY_CLUES
    return None


def _looks_like_game_input(question: str) -> bool:
    return bool(
        _PLAY_REQUEST.search(question)
        or _QUIT_PATTERN.search(question)
        or _direct_game_type(question)
        or _YES_PATTERN.match(question)
        or _NO_PATTERN.match(question)
    )


def _game_start_lead(mood: str) -> str:
    if mood == "excited":
        return "我正有冲劲呢！"
    if mood == "happy":
        return "好呀，我正想和你玩！"
    if mood == "sleepy":
        return "我还有一点困，不过玩一小局也许就精神啦。"
    return "好呀！"


def _normalize(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _compact(value: str) -> str:
    return re.sub(r"[\s，。！？,.!?；;：:、]", "", str(value or ""))


def _parse_datetime(value: Any) -> datetime:
    try:
        return _as_utc(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
