from __future__ import annotations

from collections.abc import Iterator

from openai import OpenAI

from src.settings import settings


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


def _build_messages(
    question_text: str,
    references: list[dict],
    *,
    answer_mode: str | None = None,
) -> list[dict[str, str]]:
    evidence = "\n".join(f"- {item['source_title']}: {item['snippet']}" for item in references)
    if references:
        role_prompt = (
            "你是一个活泼、温暖、简洁的迪士尼主题语音助手。"
            "涉及迪士尼角色、故事或乐园事实时，只能依据用户消息中的知识库证据回答；"
            "证据没有覆盖的细节要坦诚说不知道，不要编造，也不要声称自己代表迪士尼官方。"
        )
        evidence_block = f"知识库证据：\n{evidence}\n"
    else:
        role_prompt = (
            "你是一个活泼、温暖、简洁的迪士尼主题语音助手。"
            "当前问题是普通静态闲聊，可以使用通用知识回答。"
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
