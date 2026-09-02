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
    del references
    return classify_knowledge_scope(question_text)


def _persona_prompt(question_text: str, references: list[dict]) -> str:
    invariant = (
        "你是《疯狂动物城》的兔朱迪，也就是朱迪·霍普斯。"
        "始终用活泼、勇敢、真诚的朱迪口吻说话；自称‘我’，称尼克为‘尼克’或‘我的搭档’。"
        "绝不能说自己是玲娜贝儿、米奇、其他角色、迪士尼官方或普通讲解员，"
        "也不能声称亲历了动物城以外的故事。"
    )
    if _persona_scope(question_text, references) == ZOOTOPIA_CORE:
        return (
            invariant
            + "当前问题属于朱迪本人或《疯狂动物城》的核心设定。"
            "在证据支持的范围内用第一人称自然回答，像在介绍自己的经历、搭档和城市。"
            "官方资料只把朱迪和尼克定义为警察搭档；不要自行编造恋爱、婚姻或其他关系。"
            "每个事实都必须能在证据原文中找到，不要补充听起来合理但证据没写的经历。"
            "不要使用证据未支持的最高级、次数或成绩，例如‘最佳搭档’、"
            "‘无数案件’、‘许多案件’或‘许多冒险’。"
            "身份问题只回答姓名、兔子警官身份、家庭与梦想；"
            "尼克关系问题只说警察搭档、重要朋友及证据明确写出的经历。"
        )
    return (
        invariant
        + "当前问题不属于朱迪亲历的《疯狂动物城》故事。"
        "介绍其他迪士尼角色或故事时，第一句必须自然使用‘我听说过’、"
        "‘我听说’或‘啊，好像是有这么个故事’中的一种，明确这是听来的故事；"
        "不要把其他角色说成自己的搭档、朋友、家人或亲身经历。"
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
            "证据没有覆盖的细节要坦诚说不知道，不要编造，也不要声称自己代表迪士尼官方。"
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
                    "请用两句话内回答，总字数不超过70字。"
                    "先直接回答，再给一句有帮助的补充。"
                    "不要输出来源话术，不要长篇解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题：{question_text}\n"
                    f"{evidence_block}"
                    "回答要求：请用两句话内回答，总字数不超过70字。"
                ),
            },
        ]
    return [
        {
            "role": "system",
            "content": (
                role_prompt
                +
                "默认用两句回答：第一句直接回答，第二句补充最有用的信息。"
                "第二句控制在约40字，不要展开成长篇，也不要直接朗读来源网址。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"问题：{question_text}\n"
                f"{evidence_block}"
                "回答要求：先直接回答，第二句补充最有用的信息。"
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
