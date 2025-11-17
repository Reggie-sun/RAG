from __future__ import annotations

from threading import Lock
from typing import Dict, List, Optional


class DocContextStore:
    """Stores the latest document chunks used per session for follow-up questions."""

    def __init__(self) -> None:
        self._store: Dict[str, List[dict]] = {}
        self._lock = Lock()

    def set(self, session_id: str, docs: List[dict]) -> None:
        if not session_id or not docs:
            return
        snapshot = [dict(doc) for doc in docs]
        with self._lock:
            self._store[session_id] = snapshot

    def get(self, session_id: Optional[str]) -> List[dict]:
        if not session_id:
            return []
        with self._lock:
            docs = self._store.get(session_id, [])
            return [dict(doc) for doc in docs]

    def clear(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        with self._lock:
            self._store.pop(session_id, None)


doc_context_store = DocContextStore()
