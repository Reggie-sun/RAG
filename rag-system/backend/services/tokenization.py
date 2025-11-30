from __future__ import annotations

import re
from typing import List

import jieba


def tokenize(text: str) -> List[str]:
    """
    统一的终极 tokenizer（中文/英文混合）：
    1) jieba 分词（中文友好）
    2) 英文/数字下划线 token（regex）
    3) 字符 2-gram，增强召回
    保证构建索引与检索使用同一逻辑。
    """
    if text is None:
        return []
    text = text.lower()
    tokens: List[str] = []

    # 1) 中文分词（jieba）
    tokens += list(jieba.cut(text))

    # 2) 英文/数字 token
    tokens += re.findall(r"[a-z0-9_]+", text)

    # 3) 2-gram 字符粒度
    for i in range(len(text) - 1):
        tokens.append(text[i : i + 2])

    return [tok for tok in tokens if tok and tok.strip()]

