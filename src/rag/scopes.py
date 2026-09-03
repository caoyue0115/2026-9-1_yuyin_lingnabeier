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

FAMILY_TERMS = (
    "你爸爸",
    "你妈妈",
    "你的爸爸",
    "你的妈妈",
    "你的父母",
    "你父母",
    "你的家人",
    "你家人",
    "你的家乡",
    "你从哪里来",
    "你从哪来",
)

PERSONAL_STORY_TERMS = (
    "你的梦想",
    "你为什么当警察",
    "你为什么要当警察",
    "你怎么当上警察",
)

NICK_IDENTITY_TERMS = (
    "尼克是谁",
    "尼克叫什么",
    "介绍尼克",
)

NICK_RELATION_TERMS = (
    "尼克和你",
    "你和尼克",
    "尼克是你的",
    "尼克是不是你的",
    "你们是什么关系",
    "你们啥关系",
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
    "蛇盖瑞",
    "尼布尔斯",
    "弗兹比",
    "林克斯利",
    "宝伯特",
    "风舞马",
    "爪爪冰棍",
    "午夜嚎叫",
    "兔窝镇",
    "冰川镇",
    "撒哈拉广场",
    "雨林区",
    "湿地市场",
    "热力追踪",
    *IDENTITY_TERMS,
    *FAMILY_TERMS,
    *PERSONAL_STORY_TERMS,
)


def classify_knowledge_scope(question_text: str) -> str:
    question = str(question_text or "")
    if any(term in question for term in ZOOTOPIA_TERMS):
        return ZOOTOPIA_CORE
    return DISNEY_HEARSAY


def expand_retrieval_query(question_text: str) -> str:
    question = str(question_text or "")
    if any(term in question for term in NICK_IDENTITY_TERMS):
        return f"{question} 尼克·王尔德 身份 狐狸 街头骗子 第一位狐狸警官"
    if any(term in question for term in NICK_RELATION_TERMS):
        return f"{question} 朱迪 尼克 关系 警察搭档 重要朋友 互相信任"
    if any(term in question for term in FAMILY_TERMS):
        return f"{question} 兔朱迪 朱迪·霍普斯 父母 爸爸斯图 妈妈邦妮 兔窝镇 胡萝卜农场 家庭"
    if any(term in question for term in IDENTITY_TERMS):
        return f"{question} 兔朱迪 朱迪·霍普斯 身份 兔子警官 务农家庭 梦想"
    if any(term in question for term in PERSONAL_STORY_TERMS):
        return f"{question} 兔朱迪 朱迪·霍普斯 梦想 第一位兔子警官 努力"
    return question
