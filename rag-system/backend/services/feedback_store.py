from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Deque, Dict, List, Optional, Sequence


class FeedbackStore:
    """
    Store per-session feedback for the latest query so repeated回答可以记住用户的不满。
    每个 session 仅保留一组与当前查询绑定的反馈，用户更换问题时自动清空。
    """

    def __init__(self, max_items: int = 6) -> None:
        self.max_items = max(1, max_items)
        self._store: Dict[str, Dict[str, object]] = {}
        self._lock = Lock()

    def sync(
        self,
        session_id: Optional[str],
        query: Optional[str],
        feedback: Optional[str] = None,
    ) -> str:
        """
        更新指定 session 的反馈并返回当前累计的反馈文本。
        - session 或 query 为空时直接返回空字符串。
        - 新问题会重置历史反馈。
        - feedback 为空表示仅同步，不追加。
        """
        if not session_id:
            return ""
        normalized_query = (query or "").strip()
        if not normalized_query:
            return ""
        cleaned_feedback = (feedback or "").strip()

        with self._lock:
            entry = self._store.get(session_id)
            if not entry or entry.get("query") != normalized_query:
                entry = {
                    "query": normalized_query,
                    "items": deque(maxlen=self.max_items),
                }
                self._store[session_id] = entry
            items: Deque[str] = entry["items"]  # type: ignore[assignment]
            if cleaned_feedback:
                if not items or items[-1] != cleaned_feedback:
                    items.append(cleaned_feedback)
            return self._render(items)

    def current(self, session_id: Optional[str], query: Optional[str]) -> str:
        """获取当前累计的反馈文本，不会修改状态。"""
        if not session_id:
            return ""
        normalized_query = (query or "").strip()
        if not normalized_query:
            return ""
        with self._lock:
            entry = self._store.get(session_id)
            if not entry or entry.get("query") != normalized_query:
                return ""
            return self._render(entry["items"])  # type: ignore[arg-type]

    def clear(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        with self._lock:
            self._store.pop(session_id, None)

    def _render(self, items: Deque[str]) -> str:
        if not items:
            return ""
        formatted: List[str] = []
        for idx, value in enumerate(items, start=1):
            formatted.append(f"{idx}. {value}")
        return "\n".join(formatted)


feedback_store = FeedbackStore(max_items=6)

FEEDBACK_TAG_TEMPLATES: Dict[str, str] = {
    "missing_citation": "引用不完整：请补充足够的引用并标注具体页码/章节，至少提供两条来源。",
    "need_detail": "内容太概括：需要列出明确的步骤、数量或案例，不要只给结论。",
    "missing_risk": "缺少风险与限制：请补充潜在风险、前置条件或适用范围。",
    "format_issue": "排版不规范：请遵循模板层级，加粗标题，分段清晰。",
}


def compose_feedback_text(
    feedback: Optional[str],
    tags: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """
    将文本反馈与结构化标签合并成统一字符串，保持换行分隔。
    """
    base = (feedback or "").strip()
    tag_lines: List[str] = []
    if tags:
        seen = set()
        for tag in tags:
            tag_id = str(tag or "").strip().lower()
            if not tag_id or tag_id in seen:
                continue
            seen.add(tag_id)
            template = FEEDBACK_TAG_TEMPLATES.get(tag_id)
            if template:
                tag_lines.append(template)
    if not base and not tag_lines:
        return None
    sections = [section for section in [base, "\n".join(tag_lines)] if section]
    return "\n".join(sections)
