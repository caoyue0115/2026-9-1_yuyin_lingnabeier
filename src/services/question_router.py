from __future__ import annotations

import re
from enum import Enum


class QuestionRoute(str, Enum):
    DISNEY_KNOWLEDGE = "disney_knowledge"
    GENERAL = "general"
    DYNAMIC_CURRENT = "dynamic_current"


DISNEY_KEYWORDS = (
    "迪士尼",
    "Disney",
    "disney",
    "玲娜贝儿",
    "玲娜贝尔",
    "达菲",
    "雪莉玫",
    "杰拉多尼",
    "星黛露",
    "可琦安",
    "奥乐米拉",
    "朱迪",
    "兔朱迪",
    "尼克",
    "疯狂动物城",
    "Zootopia",
    "zootopia",
    "米奇",
    "米妮",
    "唐老鸭",
    "黛丝",
    "高飞",
    "布鲁托",
    "奇奇",
    "蒂蒂",
    "冰雪奇缘",
    "艾莎",
    "安娜",
    "雪宝",
    "玩具总动员",
    "胡迪",
    "巴斯光年",
    "海洋奇缘",
    "莫阿娜",
    "魔法满屋",
    "米拉贝尔",
    "狮子王",
    "辛巴",
    "木法沙",
    "星际宝贝",
    "史迪奇",
    "寻梦环游记",
    "米格",
    "皮克斯",
)

_DYNAMIC_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"天气|气温|温度|降雨|下雨|空气质量|台风|天气预报",
        r"(?:今天|今日|明天|后天|现在|当前|实时|最新).{0,16}(?:票价|门票|营业|开放|开园|闭园|关门|排队|等候|客流|烟花)",
        r"(?:票价|门票|营业|开放|开园|闭园|关门|排队|等候|客流|烟花).{0,16}(?:今天|今日|明天|后天|现在|当前|实时|最新)",
        r"(?:票价|门票).{0,8}(?:多少|多少钱|价格)",
        r"(?:营业|开放|开园|闭园|关门|烟花).{0,8}(?:时间|几点)",
        r"(?:排队|等候).{0,8}(?:多久|时间|多少)",
        r"(?:人多|拥挤).{0,4}(?:吗|么|不)",
    )
)

DYNAMIC_REFUSAL = (
    "我的警务终端暂时不能查询实时天气、票价、营业时间或排队情况。"
    "请查看迪士尼官方 App 或官网获取最新信息。"
)
DISNEY_KNOWLEDGE_MISS = (
    "这件事我还没有找到可靠线索，不能乱下结论。"
    "你可以问我动物城、尼克、牛局长，或已经收录的其他迪士尼故事。"
)


def route_question(question: str) -> QuestionRoute:
    normalized = str(question or "").strip()
    if any(pattern.search(normalized) for pattern in _DYNAMIC_PATTERNS):
        return QuestionRoute.DYNAMIC_CURRENT
    if any(keyword in normalized for keyword in DISNEY_KEYWORDS):
        return QuestionRoute.DISNEY_KNOWLEDGE
    return QuestionRoute.GENERAL

