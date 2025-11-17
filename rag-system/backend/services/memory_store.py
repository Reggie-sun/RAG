from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict, List, Tuple


class MemoryStore:
    def __init__(self, max_turns: int = 8) -> None:
        self.max_turns = max(1, max_turns)
        self._store: Dict[str, Deque[Tuple[str, str]]] = defaultdict(
            lambda: deque(maxlen=self.max_turns)
        )
        self._lock = Lock()

    def append(self, session_id: str, question: str, answer: str) -> None:
        if not session_id:
            return
        with self._lock:
            buffer = self._store[session_id]
            if buffer and buffer[-1] == (question, answer):
                return
            buffer.append((question, answer))

    def history(self, session_id: str) -> List[Tuple[str, str]]:
        if not session_id:
            return []
        with self._lock:
            return list(self._store.get(session_id, ()))

    def reset(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            self._store.pop(session_id, None)


memory_store = MemoryStore(max_turns=30)


def render_history(pairs: List[Tuple[str, str]], limit: int = 6) -> str:
    if not pairs or limit <= 0:
        return ""
    segments: List[str] = []
    for idx, (question, answer) in enumerate(pairs[-limit:], start=1):
        segments.append(f"[历史{idx}] 问：{question}\n答：{answer}\n")
    return "\n".join(segments)
