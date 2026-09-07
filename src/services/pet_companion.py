from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.services.pet_games import (
    GAME_MAX_TURNS,
    GameDecision,
    get_game_snapshot,
    process_game_turn,
)
from src.storage.db import connect


PET_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
DEFAULT_AFFECTION = 10
DEFAULT_ENERGY = 80
DEFAULT_MOOD = "curious"
DEFAULT_CONVERSATION_TURNS = 4

MOOD_LABELS = {
    "curious": "好奇",
    "happy": "开心",
    "excited": "兴奋",
    "sleepy": "有点困",
}

_PUNCTUATION = " ，。！？,.!?；;：:、\t\r\n"
_NAME_QUERY = re.compile(r"(?:我叫(?:什么|啥)|你(?:还)?记得我(?:的名字|叫什么)|我的名字是什么)")
_FAVORITE_QUERY = re.compile(r"(?:我(?:最)?喜欢(?:谁|什么)|你(?:还)?记得我喜欢(?:谁|什么)|我喜欢的是什么)")
_MEMORY_SUMMARY_QUERY = re.compile(r"(?:你还记得我吗|你记得我吗|你记得关于我的什么|你了解我吗)")
_NAME_CAPTURE = re.compile(
    r"(?:我叫|请叫我|以后叫我|叫我)([\u4e00-\u9fffA-Za-z0-9_-]{1,12}?)(?=$|[，。！？,.!?]|就好|吧)"
)
_FAVORITE_CAPTURE = re.compile(
    r"我(?:最)?喜欢(?:的(?:迪士尼)?角色是|的是|的东西是|是)?(.{1,20}?)(?=$|[，。！？,.!?])"
)


@dataclass(frozen=True, slots=True)
class PetProfile:
    device_id: str
    affection: int
    mood: str
    energy: int
    streak_days: int
    last_interaction_date: str | None
    last_interaction_at: str | None

    @property
    def mood_label(self) -> str:
        return MOOD_LABELS.get(self.mood, "好奇")

    @property
    def bond_stage(self) -> str:
        if self.affection >= 90:
            return "非常默契的朋友"
        if self.affection >= 70:
            return "默契伙伴"
        if self.affection >= 40:
            return "好伙伴"
        if self.affection >= 20:
            return "熟悉的朋友"
        return "刚认识的朋友"

    def public_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "affection": self.affection,
            "bond_stage": self.bond_stage,
            "mood": self.mood,
            "mood_label": self.mood_label,
            "energy": self.energy,
            "streak_days": self.streak_days,
            "last_interaction_at": self.last_interaction_at,
        }


@dataclass(frozen=True, slots=True)
class PetTurnResult:
    handled: bool
    answer: str | None
    action: str
    profile: PetProfile | None
    memories: dict[str, str]
    prompt_context: str
    duplicate_event: bool = False
    game_active: bool = False
    max_turns: int = DEFAULT_CONVERSATION_TURNS
    game: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _Intent:
    action: str
    value: str = ""


def get_pet_snapshot(device_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    normalized_device = _normalize_device_id(device_id)
    current_time = _as_utc(now or datetime.now(timezone.utc))
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        profile = _get_or_create_profile(conn, normalized_device, current_time)
        memories = _load_memories(conn, normalized_device)
        game = get_game_snapshot(conn, normalized_device, now=current_time)
        conn.commit()
    finally:
        conn.close()
    payload = profile.public_dict()
    payload["memories"] = memories
    payload["game"] = game
    return payload


def process_pet_turn(
    question: str,
    device_id: str,
    event_id: str,
    *,
    now: datetime | None = None,
) -> PetTurnResult:
    """Persist one device-scoped interaction and handle explicit pet/memory intents."""
    normalized_device = _normalize_device_id(device_id)
    normalized_event = str(event_id or "").strip()
    if not normalized_event:
        raise ValueError("missing_pet_event_id")
    normalized_question = _normalize_question(question)
    intent = _parse_intent(normalized_question)
    current_time = _as_utc(now or datetime.now(timezone.utc))
    local_date = current_time.astimezone(PET_TIMEZONE).date()

    conn = connect()
    game_decision = GameDecision()
    try:
        conn.execute("BEGIN IMMEDIATE")
        profile = _get_or_create_profile(conn, normalized_device, current_time)
        duplicate = conn.execute(
            "SELECT 1 FROM pet_events WHERE event_id = ?",
            (normalized_event,),
        ).fetchone() is not None
        first_today = False
        memory_changed = False
        affection_delta = 0
        energy_delta = 0
        mood_before = profile.mood
        mood_after = profile.mood

        if not duplicate:
            previous_local_date = _parse_local_date(profile.last_interaction_date)
            streak_days = profile.streak_days
            affection = profile.affection
            energy = profile.energy
            if previous_local_date != local_date:
                first_today = True
                streak_days = (
                    profile.streak_days + 1
                    if previous_local_date == local_date - timedelta(days=1)
                    else 1
                )
                affection_delta += 1
                energy_delta += min(10, 100 - energy)
                mood_after = DEFAULT_MOOD

            game_decision = process_game_turn(
                conn,
                normalized_device,
                normalized_question,
                energy=_clamp(energy + energy_delta),
                mood=mood_after,
                now=current_time,
            )
            if game_decision.handled or game_decision.llm_instruction:
                intent = _Intent(game_decision.action or "game")
                affection_delta += game_decision.affection_delta
                energy_delta += game_decision.energy_delta
                if game_decision.mood:
                    mood_after = game_decision.mood
            elif intent.action == "remember_name":
                _upsert_memory(conn, normalized_device, "name", intent.value, normalized_event, current_time)
                memory_changed = True
                mood_after = "happy"
                affection_delta += 1
            elif intent.action == "remember_favorite":
                _upsert_memory(conn, normalized_device, "favorite", intent.value, normalized_event, current_time)
                memory_changed = True
                mood_after = "happy"
                affection_delta += 1
            elif intent.action == "forget_name":
                memory_changed = _delete_memory(conn, normalized_device, "name")
            elif intent.action == "forget_favorite":
                memory_changed = _delete_memory(conn, normalized_device, "favorite")
            elif intent.action == "forget_all":
                memory_changed = _delete_all_memories(conn, normalized_device)
            elif intent.action == "pat":
                affection_delta += 2
                mood_after = "happy"
            elif intent.action == "feed":
                affection_delta += 1
                energy_delta += min(12, 100 - (energy + energy_delta))
                mood_after = "happy"
            elif intent.action == "like_judy":
                affection_delta += 2
                mood_after = "happy"
            elif intent.action == "play":
                if energy + energy_delta >= 10:
                    affection_delta += 3
                    energy_delta -= 8
                    mood_after = "excited"
                else:
                    mood_after = "sleepy"

            affection = _clamp(affection + affection_delta)
            energy = _clamp(energy + energy_delta)
            conn.execute(
                """
                UPDATE pet_profiles
                SET affection = ?, mood = ?, energy = ?, streak_days = ?,
                    last_interaction_date = ?, last_interaction_at = ?, updated_at = ?
                WHERE device_id = ?
                """,
                (
                    affection,
                    mood_after,
                    energy,
                    streak_days,
                    local_date.isoformat(),
                    current_time.isoformat(),
                    current_time.isoformat(),
                    normalized_device,
                ),
            )
            conn.execute(
                """
                INSERT INTO pet_events(
                    event_id, device_id, action, affection_delta, energy_delta,
                    mood_before, mood_after, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_event,
                    normalized_device,
                    intent.action,
                    affection_delta,
                    energy_delta,
                    mood_before,
                    mood_after,
                    json.dumps(
                        {"intent": intent.action, "memory_changed": memory_changed},
                        ensure_ascii=False,
                    ),
                    current_time.isoformat(),
                ),
            )

        row = conn.execute(
            "SELECT * FROM pet_profiles WHERE device_id = ?",
            (normalized_device,),
        ).fetchone()
        memories = _load_memories(conn, normalized_device)
        game = get_game_snapshot(conn, normalized_device, now=current_time)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    profile = _profile_from_row(row)
    answer = game_decision.answer or _render_answer(
        intent,
        profile,
        memories,
        first_today,
        memory_changed,
    )
    prompt_context = _build_prompt_context(profile, memories)
    if game_decision.llm_instruction:
        prompt_context += game_decision.llm_instruction
    game_active = bool(game and game.get("active"))
    return PetTurnResult(
        handled=answer is not None,
        answer=answer,
        action=intent.action,
        profile=profile,
        memories=memories,
        prompt_context=prompt_context,
        duplicate_event=duplicate,
        game_active=game_active,
        max_turns=GAME_MAX_TURNS if game_active else DEFAULT_CONVERSATION_TURNS,
        game=game,
    )


def _parse_intent(question: str) -> _Intent:
    if re.search(r"(?:清除|删除|忘掉|忘记).{0,6}(?:关于我的|我的).{0,4}(?:全部|所有)?(?:记忆|事情|资料)", question):
        return _Intent("forget_all")
    if re.search(r"(?:忘掉|忘记|删除).{0,5}(?:我的名字|我叫什么|称呼)", question):
        return _Intent("forget_name")
    if re.search(r"(?:忘掉|忘记|删除).{0,5}(?:我喜欢的|我的喜好)", question):
        return _Intent("forget_favorite")
    if _NAME_QUERY.search(question):
        return _Intent("recall_name")
    if _FAVORITE_QUERY.search(question):
        return _Intent("recall_favorite")
    if _MEMORY_SUMMARY_QUERY.search(question):
        return _Intent("recall_summary")
    if re.search(r"(?:我喜欢你|我最喜欢你|喜欢朱迪|最喜欢朱迪)", question):
        return _Intent("like_judy")

    name_match = _NAME_CAPTURE.search(question)
    if name_match:
        value = _clean_memory_value(name_match.group(1), max_chars=12)
        if value:
            return _Intent("remember_name", value)
    favorite_match = _FAVORITE_CAPTURE.search(question)
    if favorite_match:
        value = _clean_memory_value(favorite_match.group(1), max_chars=20)
        if value and value not in {"什么", "谁", "你", "朱迪"}:
            return _Intent("remember_favorite", value)

    if re.search(r"(?:摸摸你|摸摸头|摸你的头|拍拍你|抱抱你|抱一下)", question):
        return _Intent("pat")
    if re.search(r"(?:给你|喂你|请你吃|吃一根).{0,5}(?:胡萝卜|零食)|(?:胡萝卜|零食).{0,4}(?:给你|吃吧)", question):
        return _Intent("feed")
    if re.search(r"(?:陪我玩|和我玩|一起玩|玩个游戏|来玩游戏)", question):
        return _Intent("play")
    if re.search(r"(?:亲密度|我们.{0,3}(?:熟|关系)|你和我.{0,3}(?:熟|关系))", question):
        return _Intent("status_bond")
    if re.search(r"(?:精力|累不累|你累吗|困不困|你困吗)", question):
        return _Intent("status_energy")
    if re.search(r"(?:心情|开心吗|你今天怎么样|你现在怎么样)", question):
        return _Intent("status_mood")
    return _Intent("conversation")


def _render_answer(
    intent: _Intent,
    profile: PetProfile,
    memories: dict[str, str],
    first_today: bool,
    memory_changed: bool,
) -> str | None:
    if intent.action == "remember_name":
        return f"记住啦，我以后叫你{intent.value}。下次见面可别装作不认识我哦。"
    if intent.action == "remember_favorite":
        return f"记住啦，你喜欢{intent.value}。下次聊到它，我会想到你的。"
    if intent.action == "forget_name":
        return "好，我已经忘掉之前的称呼了。你想换个名字时再告诉我吧。" if memory_changed else "我这里本来就没有保存你的称呼。"
    if intent.action == "forget_favorite":
        return "好，我已经清掉那条喜好记录了。" if memory_changed else "我这里还没有保存你的喜好。"
    if intent.action == "forget_all":
        return "好，关于你的称呼和喜好线索都已经清掉了。" if memory_changed else "我这里还没有保存你的个人线索。"
    if intent.action == "recall_name":
        return f"当然记得，你叫{memories['name']}。" if memories.get("name") else "这条线索我还没有呢。你可以告诉我“我叫……”"
    if intent.action == "recall_favorite":
        return f"我记得，你喜欢{memories['favorite']}。" if memories.get("favorite") else "你还没告诉我最喜欢什么呢。"
    if intent.action == "recall_summary":
        known = []
        if memories.get("name"):
            known.append(f"你叫{memories['name']}")
        if memories.get("favorite"):
            known.append(f"你喜欢{memories['favorite']}")
        if known:
            return f"当然记得，{'，'.join(known)}。我们已经连续见面{profile.streak_days}天啦。"
        return f"我记得我们已经连续见面{profile.streak_days}天，不过你的名字和喜好还没告诉我。"
    if intent.action == "pat":
        return "嘿嘿，谢谢你！我的耳朵都精神起来啦。"
    if intent.action == "feed":
        return "胡萝卜收到！脆脆的，感觉一下子又有精神了。"
    if intent.action == "like_judy":
        return "真的？那我可要把这句话好好记在心里啦。我也很高兴见到你。"
    if intent.action == "play":
        if profile.mood == "sleepy":
            return "我现在有点没电啦，让我歇一会儿，我们晚点再玩。"
        return "好呀！我们来玩一个动物城线索问答，你先想一个角色让我猜。"
    if intent.action == "status_bond":
        return f"我们的亲密度是{profile.affection}，已经是{profile.bond_stage}啦。"
    if intent.action == "status_energy":
        return f"我的精力还有{profile.energy}，现在{profile.mood_label}。"
    if intent.action == "status_mood":
        prefix = "今天又见到你，我很开心。" if first_today else ""
        return f"{prefix}我现在{profile.mood_label}，我们的亲密度是{profile.affection}。"
    return None


def _build_prompt_context(profile: PetProfile, memories: dict[str, str]) -> str:
    parts = [
        f"当前心情是{profile.mood_label}",
        f"与这台设备的用户处于{profile.bond_stage}阶段",
    ]
    if memories.get("name"):
        parts.append(f"用户明确说自己叫{memories['name']}")
    if memories.get("favorite"):
        parts.append(f"用户明确说喜欢{memories['favorite']}")
    return (
        "设备长期陪伴档案："
        + "；".join(parts)
        + "。心情会影响表达：好奇时自然追问，开心时温暖鼓励，兴奋时更活泼但仍简短，"
        "困倦时语气轻缓且不主动提议玩游戏。只在相关时自然使用，不主动朗读亲密度或档案，"
        "不声称通过声纹识别了具体的人。"
    )


def _get_or_create_profile(conn: Any, device_id: str, now: datetime) -> PetProfile:
    row = conn.execute(
        "SELECT * FROM pet_profiles WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    if row is None:
        timestamp = now.isoformat()
        conn.execute(
            """
            INSERT INTO pet_profiles(
                device_id, affection, mood, energy, streak_days,
                last_interaction_date, last_interaction_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 0, NULL, NULL, ?, ?)
            """,
            (device_id, DEFAULT_AFFECTION, DEFAULT_MOOD, DEFAULT_ENERGY, timestamp, timestamp),
        )
        row = conn.execute(
            "SELECT * FROM pet_profiles WHERE device_id = ?",
            (device_id,),
        ).fetchone()
    return _profile_from_row(row)


def _profile_from_row(row: Any) -> PetProfile:
    if row is None:
        raise RuntimeError("pet_profile_missing")
    return PetProfile(
        device_id=str(row["device_id"]),
        affection=int(row["affection"]),
        mood=str(row["mood"]),
        energy=int(row["energy"]),
        streak_days=int(row["streak_days"]),
        last_interaction_date=row["last_interaction_date"],
        last_interaction_at=row["last_interaction_at"],
    )


def _load_memories(conn: Any, device_id: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT memory_key, memory_value FROM device_memories WHERE device_id = ? ORDER BY memory_key",
        (device_id,),
    ).fetchall()
    return {str(row["memory_key"]): str(row["memory_value"]) for row in rows}


def _upsert_memory(
    conn: Any,
    device_id: str,
    memory_key: str,
    memory_value: str,
    source_turn_id: str,
    now: datetime,
) -> None:
    timestamp = now.isoformat()
    conn.execute(
        """
        INSERT INTO device_memories(
            device_id, memory_key, memory_value, source_turn_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id, memory_key) DO UPDATE SET
            memory_value = excluded.memory_value,
            source_turn_id = excluded.source_turn_id,
            updated_at = excluded.updated_at
        """,
        (device_id, memory_key, memory_value, source_turn_id, timestamp, timestamp),
    )


def _delete_memory(conn: Any, device_id: str, memory_key: str) -> bool:
    cursor = conn.execute(
        "DELETE FROM device_memories WHERE device_id = ? AND memory_key = ?",
        (device_id, memory_key),
    )
    return cursor.rowcount > 0


def _delete_all_memories(conn: Any, device_id: str) -> bool:
    cursor = conn.execute("DELETE FROM device_memories WHERE device_id = ?", (device_id,))
    return cursor.rowcount > 0


def _normalize_device_id(device_id: str) -> str:
    normalized = str(device_id or "").strip()
    if not normalized:
        raise ValueError("missing_device_id")
    if len(normalized) > 80:
        raise ValueError("device_id_too_long")
    return normalized


def _normalize_question(question: str) -> str:
    return " ".join(str(question or "").strip().split())


def _clean_memory_value(value: str, *, max_chars: int) -> str:
    normalized = str(value or "").strip(_PUNCTUATION)
    normalized = re.sub(r"(?:就好|吧)$", "", normalized).strip(_PUNCTUATION)
    return normalized[:max_chars]


def _parse_local_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clamp(value: int) -> int:
    return min(max(int(value), 0), 100)
