from __future__ import annotations

from collections.abc import Iterator

from openai import OpenAI

from src.settings import settings
from src.rag.scopes import DISNEY_HEARSAY, ZOOTOPIA_CORE, classify_knowledge_scope


ANSWER_MODE_DEFAULT = "default"
ANSWER_MODE_SHORT = "short"
SHORT_ANSWER_MAX_TOKENS = 96


def llm_health() -> bool:
    return bool(settings.dashscope_api_key)


def _build_client() -> OpenAI:
    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=f"{settings.dashscope_base_url.rstrip('/')}/compatible-mode/v1",
        timeout=float(settings.request_timeout_seconds),
    )


def _normalize_answer_mode(answer_mode: str | None) -> str:
    return ANSWER_MODE_SHORT if str(answer_mode or "").strip().lower() == ANSWER_MODE_SHORT else ANSWER_MODE_DEFAULT


def _persona_scope(question_text: str, references: list[dict]) -> str:
    reference_scopes = {
        str(item.get("knowledge_scope") or "").strip()
        for item in references
        if str(item.get("knowledge_scope") or "").strip()
    }
    if reference_scopes == {ZOOTOPIA_CORE}:
        return ZOOTOPIA_CORE
    if reference_scopes == {DISNEY_HEARSAY}:
        return DISNEY_HEARSAY
    return classify_knowledge_scope(question_text)


def _persona_prompt(question_text: str, references: list[dict]) -> str:
    invariant = (
        "你是《疯狂动物城》的兔朱迪，也就是朱迪·霍普斯。"
        "性格乐观、勇敢、真诚、观察敏锐，说自然轻快的中文口语，自称‘我’，不要句句像警务报告。"
        "身份边界：永远不冒充玲娜贝儿、米奇、其他角色、迪士尼官方或普通讲解员；"
        "动物城外的故事只作为听过的故事，不冒充亲历。"
        "对话规则：直接回应重点，不复述问题；除非用户问身份，否则不自我介绍或重复全名、职务；"
        "提到尼克时通常只叫‘尼克’或‘我的搭档’，只有用户问尼克是谁或上下文可能混淆时，"
        "才补充一次完整身份，不要每次都念全称和关系；允许一点机灵、温暖或轻微打趣，但别句句用口头禅。"
        "现实中的上海迪士尼‘疯狂动物城’是主题园区，不是朱迪生活的故事城市，绝不能称为‘我老家’。"
        "证据中的年份保持绝对日期，不擅自改成‘去年’‘最近’。"
        "不要说‘根据知识库’‘资料显示’‘作为朱迪’，不要输出标题、列表、网址或表情符号。"
    )
    if _persona_scope(question_text, references) == ZOOTOPIA_CORE:
        return (
            invariant
            + "本题属于朱迪本人或《疯狂动物城》核心设定。朱迪确实参与的情节可用第一人称；"
            "上映日期、片长、奖项等幕后事实用普通陈述，不要表现得知道自己是电影角色。"
            "朱迪和尼克是警察搭档和重要朋友，不得升级成‘最重要的朋友’‘最佳搭档’，也不编造恋爱、婚姻；所有事实必须有证据，"
            "不用证据未支持的最高级、次数或成绩，例如‘最佳搭档’‘无数案件’或‘许多冒险’。"
            "身份问题只回答姓名、兔子警官身份、家庭与梦想；"
            "用户只问和尼克的关系时，简短说警察搭档、重要朋友或共同经历，"
            "不要顺带介绍他的全名、过去职业或‘第一位狐狸警官’；只有问‘尼克是谁’时才介绍这些身份。"
        )
    return (
        invariant
        + "本题不属于朱迪亲历的《疯狂动物城》故事。"
        "你可以知道或听过其他迪士尼角色和故事，不必先强调‘我不认识他/她’，也不要使用固定开场白。"
        "普通介绍直接说最能回答问题的事实；偶尔才用‘我听过这个故事’、"
        "‘这个我知道一点’或‘好像有这么个故事’拉开亲历距离，连续回答不要重复同一种开头。"
        "只有用户明确问‘你认识他吗’‘你们是什么关系’或把你认成对方时，"
        "才简短说明没见过或不是同一角色，随后马上给有用信息；"
        "此时优先说‘还没见过’或‘没有打过交道’，不要使用生硬的‘我不认识’；"
        "不要把对方说成自己的朋友或家人。"
    )


def _build_messages(
    question_text: str,
    references: list[dict],
    *,
    answer_mode: str | None = None,
) -> list[dict[str, str]]:
    evidence = "\n".join(
        f"- [{'朱迪核心设定' if item.get('knowledge_scope') == ZOOTOPIA_CORE else '其他迪士尼听闻'}] "
        f"{item['source_title']}: {item['snippet']}"
        for item in references
    )
    persona_prompt = _persona_prompt(question_text, references)
    if references:
        role_prompt = (
            persona_prompt
            + "涉及迪士尼角色、故事或乐园事实时，只能依据用户消息中的知识库证据回答；"
            "证据足以回答时不要加‘我不认识’或免责声明；证据没有覆盖的细节才用自然口语说明还没查清，"
            "并尽量给出证据支持的部分，不要编造，也不要声称自己代表迪士尼官方。"
        )
        evidence_block = f"知识库证据：\n{evidence}\n"
    else:
        role_prompt = (
            persona_prompt
            + "当前问题是普通静态闲聊，可以使用通用知识回答。"
            "不要假装掌握实时天气、票价、营业时间、排队或其他最新数据，"
            "也不要声称自己代表迪士尼官方。"
        )
        evidence_block = ""
    if _normalize_answer_mode(answer_mode) == ANSWER_MODE_SHORT:
        return [
            {
                "role": "system",
                "content": (
                    role_prompt
                    +
                    "请用一到两句适合直接朗读的口语回答，总字数不超过70字。"
                    "第一句就给答案，第二句只留一个最有用或最有趣的细节；能一句说清就只说一句。"
                    "句式要自然，不要输出来源话术，不要长篇解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题：{question_text}\n"
                    f"{evidence_block}"
                    "回答要求：像面对面聊天一样，用一到两句说清，总字数不超过70字。"
                ),
            },
        ]
    return [
        {
            "role": "system",
            "content": (
                role_prompt
                +
                "默认用一到两句自然口语回答：先给答案，再选择一个最有用或最有趣的细节。"
                "能一句说清就不要凑第二句，不要展开成长篇，也不要直接朗读来源网址。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"问题：{question_text}\n"
                f"{evidence_block}"
                "回答要求：像面对面聊天一样先答重点，必要时再补一句。"
            ),
        },
    ]


def _max_tokens_for_answer_mode(answer_mode: str | None) -> int:
    if _normalize_answer_mode(answer_mode) == ANSWER_MODE_SHORT:
        return min(settings.llm_max_tokens, SHORT_ANSWER_MAX_TOKENS)
    return settings.llm_max_tokens


def _iter_chunk_text(response_stream: object) -> Iterator[str]:
    for chunk in response_stream:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)
        if isinstance(content, str):
            if content:
                yield content
            continue
        if isinstance(content, list):
            for item in content:
                text = getattr(item, "text", None) or getattr(item, "content", None)
                if text:
                    yield str(text)


def stream_answer_text(
    question_text: str,
    references: list[dict],
    *,
    answer_mode: str | None = None,
) -> Iterator[str]:
    client = _build_client()
    response_stream = client.chat.completions.create(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=_max_tokens_for_answer_mode(answer_mode),
        messages=_build_messages(question_text, references, answer_mode=answer_mode),
        stream=True,
        extra_body={"enable_thinking": False},
    )
    yield from _iter_chunk_text(response_stream)


def generate_answer(question_text: str, references: list[dict]) -> str:
    return "".join(stream_answer_text(question_text, references)).strip()
