from __future__ import annotations


ZOOTOPIA_CORE = "zootopia_core"
DISNEY_HEARSAY = "disney_hearsay"

IDENTITY_TERMS = (
    "你是谁",
    "你的名字",
    "你叫什么",
    "你是做什么的",
    "你是干什么的",
)

ZOOTOPIA_TERMS = (
    "朱迪",
    "Judy",
    "judy",
    "霍普斯",
    "尼克",
    "Nick",
    "nick",
    "王尔德",
    "疯狂动物城",
    "Zootopia",
    "zootopia",
    "动物城",
    "动物城警察局",
    "牛局长",
    "豹警官",
    "羊副市长",
    "狮市长",
    "奥獭顿",
    "芬尼克",
    "闪电",
    "大先生",
    "夏奇羊",
    "盖瑞",
    "爪爪冰棍",
    "午夜嚎叫",
    "兔窝镇",
    "冰川镇",
    "撒哈拉广场",
    "雨林区",
    "湿地市场",
    "热力追踪",
    *IDENTITY_TERMS,
)


def classify_knowledge_scope(question_text: str) -> str:
    question = str(question_text or "")
    if any(term in question for term in ZOOTOPIA_TERMS):
        return ZOOTOPIA_CORE
    return DISNEY_HEARSAY


def expand_retrieval_query(question_text: str) -> str:
    question = str(question_text or "")
    if any(term in question for term in IDENTITY_TERMS):
        return f"{question} 兔朱迪 朱迪·霍普斯 身份 兔子警官 务农家庭 梦想"
    return question
