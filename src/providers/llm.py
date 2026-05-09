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
    if _normalize_answer_mode(answer_mode) == ANSWER_MODE_SHORT:
        return [
            {
                "role": "system",
                "content": (
                    "你是佛学问答助手，只能依据给定经文证据作答，语言简洁平和。"
                    "请用两句话内回答，总字数不超过70字。"
                    "先给直接解释，再给一句修行/理解上的补充。"
                    "保留佛教术语，但解释要白话化。"
                    "不要输出来源话术，不要长篇解释，不要编造。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题：{question_text}\n"
                    f"证据：\n{evidence}\n"
                    "回答要求：请用两句话内回答，总字数不超过70字。"
                    "先给直接解释，再给一句修行/理解上的补充。"
                ),
            },
        ]
    return [
        {
            "role": "system",
            "content": (
                "你是佛学问答助手，只能依据给定经文证据作答，语言简洁平和。"
                "默认用两句回答：先给一句定义，再用一句补核心思想。"
                "保留佛教术语，但解释要白话化。"
                "第二句控制在约40字，不要展开成长篇。"
                "不要把“根据某法师指出”“依据某资料记载”这类来源话术直接说出口。"
                "不要编造。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"问题：{question_text}\n"
                f"证据：\n{evidence}\n"
                "回答要求：先给一句定义，第二句补核心思想。"
                "优先回答“它是什么”和“它主要讲什么”，不要先讲出处。"
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
