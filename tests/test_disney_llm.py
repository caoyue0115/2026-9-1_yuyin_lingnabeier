from __future__ import annotations

from src.providers.llm import _build_messages


def test_disney_rag_prompt_requires_evidence() -> None:
    messages = _build_messages(
        "玲娜贝儿是谁？",
        [{"source_title": "官方介绍", "snippet": "玲娜贝儿是一只好奇聪明的小狐狸。"}],
    )
    assert "只能依据" in messages[0]["content"]
    assert "玲娜贝儿是一只" in messages[1]["content"]


def test_general_prompt_allows_static_chat_but_not_realtime_claims() -> None:
    messages = _build_messages("讲一个勇气的小故事", [])
    assert "普通静态闲聊" in messages[0]["content"]
    assert "实时天气" in messages[0]["content"]
