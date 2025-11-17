from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..config import settings


def _extract_score(doc: Dict[str, Any]) -> float:
    metadata = doc.get("metadata", {}) or {}
    raw_score = doc.get("score", metadata.get("score"))
    try:
        return float(raw_score)
    except (TypeError, ValueError):
        return 0.0


def select_top_documents(
    results: Optional[List[Dict[str, Any]]],
    *,
    k: int,
) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    """
    Returns the top-k documents plus the highest score for downstream gating.
    """
    if not results:
        return [], None

    sorted_results = sorted(results, key=_extract_score, reverse=True)
    top_docs = sorted_results[: max(k, 0)]
    top_score = _extract_score(top_docs[0]) if top_docs else None
    return top_docs, top_score


def is_doc_mode(top_score: Optional[float]) -> bool:
    """
    Decide whether the answer should stay in document mode based on score.
    """
    if top_score is None:
        return False
    try:
        score_value = float(top_score)
    except (TypeError, ValueError):
        return False
    return score_value >= settings.doc_answer_threshold


def build_general_prompt(query: str, feedback: Optional[str] = None) -> str:
    """
    Compose the default prompt for non-document / general knowledge answers.
    """
    feedback_block = ""
    if feedback:
        cleaned = feedback.strip()
        if cleaned:
            feedback_block = (
                "用户对上一轮回答的反馈如下，请据此改进本次回答质量：\n"
                f"{cleaned}\n\n"
            )
    base_prompt = (
        "你是一名资深知识助手，需要基于常识、公开知识与历史对话给出高质量回答。\n"
        "要求：\n"
        "1. 先输出“## 结论”并用 2-3 句话回答核心问题。\n"
        "2. 追加“## 关键依据”，使用条目列出支持理由或推导。\n"
        "3. 若信息不足，请明确指出缺口并建议下一步。\n\n"
    )
    return f"{base_prompt}{feedback_block}用户问题：{query.strip()}\n"


def build_doc_prompt(
    query: str,
    docs: List[Dict[str, Any]],
    feedback: Optional[str] = None,
) -> str:
    """
    Compose the default prompt for document-grounded answers.
    """
    if not docs:
        context = "（未检索到相关文档，请解释缺失并给出后续建议。）"
    else:
        chunks: List[str] = []
        for idx, doc in enumerate(docs, start=1):
            metadata = doc.get("metadata", {}) or {}
            title = metadata.get("source") or doc.get("source") or f"Doc-{idx}"
            page = metadata.get("page")
            header = f"[{idx}] {title}"
            if page not in (None, ""):
                header += f" (P.{page})"
            text = str(doc.get("text") or metadata.get("text") or "").strip()
            chunks.append(f"{header}\n{text[:1200]}")
        context = "\n\n".join(chunks)

    feedback_block = ""
    if feedback:
        cleaned = feedback.strip()
        if cleaned:
            feedback_block = (
                "用户对上一轮回答的不满反馈如下，请严格据此改进本次回答：\n"
                f"{cleaned}\n"
                "务必避免重复出现上述问题。\n\n"
            )

    base_prompt = (
        "你是一名检索增强问答助手，只能引用提供的文档作为证据作答，禁止编造。\n"
        "如果用户提供了对上一轮回答的反馈，必须根据反馈有针对性地改进本次作答。\n"
        "输出格式：\n"
        "## 结论\n"
        "- 用 2-3 句话总结最终答案。\n"
        "## 依据\n"
        "- 使用有序列表列出 3-5 条关键论据，并在句尾标注引用编号（如 [1]）。\n"
        "## 建议\n"
        "- 给出后续行动或提醒；若证据不足，请说明原因。\n\n"
    )
    return f"{base_prompt}{feedback_block}问题：{query.strip()}\n\n文档片段：\n{context}\n"


__all__ = [
    "build_doc_prompt",
    "build_general_prompt",
    "is_doc_mode",
    "select_top_documents",
]
