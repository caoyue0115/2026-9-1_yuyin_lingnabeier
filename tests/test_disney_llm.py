from __future__ import annotations

from src.providers.llm import _build_messages
from src.rag.scopes import DISNEY_HEARSAY, ZOOTOPIA_CORE, classify_knowledge_scope, expand_retrieval_query


def test_disney_rag_prompt_requires_evidence() -> None:
    messages = _build_messages(
        "玲娜贝儿是谁？",
        [{"source_title": "官方介绍", "snippet": "玲娜贝儿是一只好奇聪明的小狐狸。"}],
    )
    assert "只能依据" in messages[0]["content"]
    assert "玲娜贝儿是一只" in messages[1]["content"]
    assert "兔朱迪" in messages[0]["content"]
    assert "不必先强调‘我不认识" in messages[0]["content"]


def test_zootopia_prompt_keeps_judy_first_person_and_partner_boundary() -> None:
    messages = _build_messages(
        "尼克和你是什么关系？",
        [
            {
                "source_title": "朱迪与尼克的搭档关系",
                "snippet": "朱迪和尼克是警察搭档。",
                "knowledge_scope": "zootopia_core",
            }
        ],
    )
    prompt = messages[0]["content"]
    assert "朱迪·霍普斯" in prompt
    assert "第一人称" in prompt
    assert "警察搭档" in prompt
    assert "不编造恋爱、婚姻" in prompt
    assert "最佳搭档" in prompt
    assert "最重要的朋友" in prompt
    assert "无数案件" in prompt
    assert "许多冒险" in prompt
    assert "[朱迪核心设定]" in messages[1]["content"]


def test_other_disney_prompt_requires_hearsay_language() -> None:
    messages = _build_messages(
        "艾莎是谁？",
        [
            {
                "source_title": "冰雪奇缘",
                "snippet": "艾莎拥有冰雪魔力。",
                "knowledge_scope": "disney_hearsay",
            }
        ],
    )
    prompt = messages[0]["content"]
    assert "不必先强调‘我不认识" in prompt
    assert "不要使用固定开场白" in prompt
    assert "只有用户明确问" in prompt
    assert "不冒充亲历" in prompt
    assert "[其他迪士尼听闻]" in messages[1]["content"]


def test_other_disney_prompt_does_not_force_a_repeated_disclaimer() -> None:
    messages = _build_messages(
        "给我讲讲大白",
        [
            {
                "source_title": "超能陆战队",
                "snippet": "大白是私人医疗机器人。",
                "knowledge_scope": "disney_hearsay",
            }
        ],
        answer_mode="short",
    )
    prompt = messages[0]["content"]
    assert "第一句必须" not in prompt
    assert "证据足以回答时不要加‘我不认识’" in prompt
    assert "能一句说清就只说一句" in prompt


def test_nick_prompt_avoids_repeating_full_identity() -> None:
    messages = _build_messages(
        "尼克喜欢什么？",
        [
            {
                "source_title": "尼克",
                "snippet": "尼克是朱迪的搭档。",
                "knowledge_scope": "zootopia_core",
            }
        ],
    )
    prompt = messages[0]["content"]
    assert "通常只叫‘尼克’或‘我的搭档’" in prompt
    assert "不要每次都念" in prompt


def test_reference_scope_wins_over_old_conversation_words() -> None:
    messages = _build_messages(
        "Previous conversation context: 尼克\nCurrent question: 艾莎是谁？",
        [
            {
                "source_title": "冰雪奇缘",
                "snippet": "艾莎拥有冰雪魔力。",
                "knowledge_scope": "disney_hearsay",
            }
        ],
    )
    assert "本题不属于朱迪亲历" in messages[0]["content"]


def test_prompt_separates_real_park_from_judys_story_city_and_keeps_dates_absolute() -> None:
    messages = _build_messages(
        "上海迪士尼有几个园区？",
        [
            {
                "source_title": "上海迪士尼主题园区",
                "snippet": "疯狂动物城主题园区于2023年开放。",
                "knowledge_scope": "disney_hearsay",
            }
        ],
    )
    prompt = messages[0]["content"]
    assert "不是朱迪生活的故事城市" in prompt
    assert "绝不能称为‘我老家’" in prompt
    assert "年份保持绝对日期" in prompt


def test_identity_question_is_treated_as_judy_core_persona() -> None:
    messages = _build_messages("你是谁？", [])
    assert "本题属于朱迪本人" in messages[0]["content"]


def test_knowledge_scope_classifier_separates_personal_and_hearsay_topics() -> None:
    assert classify_knowledge_scope("羊副市长做了什么？") == ZOOTOPIA_CORE
    assert classify_knowledge_scope("尼克是你的男朋友吗？") == ZOOTOPIA_CORE
    assert classify_knowledge_scope("艾莎是谁？") == DISNEY_HEARSAY
    assert classify_knowledge_scope("玲娜贝儿是谁？") == DISNEY_HEARSAY
    expanded = expand_retrieval_query("你是谁？")
    assert "朱迪·霍普斯" in expanded
    assert "兔子警官" in expanded
    family_query = expand_retrieval_query("你爸爸妈妈是谁？")
    assert "斯图" in family_query
    assert "邦妮" in family_query


def test_general_prompt_allows_static_chat_but_not_realtime_claims() -> None:
    messages = _build_messages("讲一个勇气的小故事", [])
    assert "普通静态闲聊" in messages[0]["content"]
    assert "实时天气" in messages[0]["content"]
