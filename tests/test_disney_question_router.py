from __future__ import annotations

from src.services.question_router import QuestionRoute, route_question


def test_routes_disney_questions_to_rag() -> None:
    assert route_question("玲娜贝儿是怎样认识达菲的？") == QuestionRoute.DISNEY_KNOWLEDGE
    assert route_question("朱迪在疯狂动物城里做什么？") == QuestionRoute.DISNEY_KNOWLEDGE
    assert route_question("给我讲讲冰雪奇缘") == QuestionRoute.DISNEY_KNOWLEDGE
    assert route_question("史迪奇是谁？") == QuestionRoute.DISNEY_KNOWLEDGE
    assert route_question("你是谁？") == QuestionRoute.DISNEY_KNOWLEDGE


def test_routes_general_static_chat_to_llm() -> None:
    assert route_question("给我讲一个关于勇气的小故事") == QuestionRoute.GENERAL


def test_routes_dynamic_questions_to_friendly_refusal() -> None:
    assert route_question("上海迪士尼明天天气怎么样？") == QuestionRoute.DYNAMIC_CURRENT
    assert route_question("疯狂动物城现在要排队多久？") == QuestionRoute.DYNAMIC_CURRENT
    assert route_question("今天门票多少钱？") == QuestionRoute.DYNAMIC_CURRENT
