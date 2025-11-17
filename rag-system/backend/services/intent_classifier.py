import re
from typing import List, Literal, Tuple

Intent = Literal["greeting", "thanks", "short", "general_qa", "question"]

GREETING_PAT = re.compile(
    r"^\s*(你好|您好|哈喽|嗨|在吗|晚上好|早上好|中午好|hello|hi|hey|yo|bye|再见|拜拜|👋|🙂|:\)|:-\))\s*[!！。,.…]*\s*$",
    re.IGNORECASE,
)
THANKS_PAT = re.compile(
    r"^\s*(谢谢|多谢|辛苦了|thx|thanks|thank\s+you)\s*[!！。,.…]*\s*$",
    re.IGNORECASE,
)
DOC_HINT_PAT = re.compile(
    r"(本文|这[份个]文档|这本书|这篇|该报告|该文档|该文件|第\s*\d+\s*(页|章|节|图)|附录|图表|table|figure)",
    re.IGNORECASE,
)
GENERAL_Q_PAT = re.compile(
    r"(几(个|时)|多少|为什么|为啥|是什么|是谁|哪[里国种些]|是否|多久|怎么|如何|when|what|why|who|which|how)",
    re.IGNORECASE,
)


def detect_intent(query: str) -> Intent:
    text = query or ""
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return "short"

    if GREETING_PAT.match(text):
        return "greeting"
    if THANKS_PAT.match(text):
        return "thanks"

    zh_chars = len(re.findall(r"[\u4e00-\u9fa5]", text))
    en_tokens = len(re.findall(r"[A-Za-z0-9_]+", text))
    if zh_chars <= 2 and en_tokens <= 2:
        return "short"

    if GENERAL_Q_PAT.search(text) and not DOC_HINT_PAT.search(text):
        return "general_qa"

    return "question"


def build_intent_response(intent: Intent) -> Tuple[str, Literal["chitchat", "guidance"], List[str]]:
    if intent == "greeting":
        return (
            "**嗨～我在这儿！**\n"
            "你可以让我：\n"
            "- 总结或解释上传的文档\n"
            "- 对比两份资料的不同观点\n"
            "- 提取要点并生成行动建议\n\n"
            "试着问我：`这份 PDF 的关键结论是什么？`",
            "chitchat",
            [
                "总结这篇PDF的核心发现（100字）",
                "提取报告里的行动项并分配负责人",
                "对比《A.pdf》和《B.pdf》的观点差异",
            ],
        )

    if intent == "thanks":
        return (
            "不客气～如需保存结果，我可以帮你把这次对话整理成要点。",
            "chitchat",
            [
                "把这次对话生成会议纪要",
                "继续分析《最新报告.pdf》的要点",
                "列出下一步需跟进的风险点",
            ],
        )

    return (
        "我需要更具体的问题才能检索文档。\n\n"
        "可以试试这些提问方式：\n"
        "- `总结这篇PDF的核心发现（100字）`\n"
        "- `提取报告里的行动项并说明责任人`\n"
        "- `对比A与B两个文档的观点`",
        "guidance",
        [
            "总结这篇PDF的核心发现（100字）",
            "提取报告里的行动项并说明责任人",
            "给出这份文档的风险点及缓解建议",
        ],
    )


def has_doc_hint(query: str) -> bool:
    return bool(DOC_HINT_PAT.search(query or ""))
