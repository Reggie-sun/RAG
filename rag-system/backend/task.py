# backend/tasks.py
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from celery import Celery

from backend.agent_init import build_agent
from backend.config import settings
from backend.services.providers import get_rag_service

# ===== Celery 基础配置 =====
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
BACKEND_URL = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(__name__, broker=BROKER_URL, backend=BACKEND_URL)
celery_app.conf.broker_connection_retry_on_startup = True

# ===== LangChain Agent（兼容历史逻辑）=====
_AGENT: Optional[Any] = None


def get_agent() -> Any:
    global _AGENT
    if _AGENT is None:
        _AGENT = build_agent()
    return _AGENT


@celery_app.task(name="qa.answer_sync")
def answer_sync(question: str) -> str:
    agent = get_agent()
    return agent.run(question)


@celery_app.task(name="qa.answer_async")
def answer_async(question: str) -> str:
    agent = get_agent()
    return asyncio.run(agent.invoke(question))


# ===== RAG 队列任务 =====
@celery_app.task(name="qa.rag_answer")
def rag_answer_task(
    question: str,
    session_id: str,
    history: str | None = None,
    top_k: int | None = None,
    alpha: float | None = None,
    use_rerank: bool | None = None,
    filters: dict | None = None,
    allow_web: bool | None = None,
    doc_only: bool | None = None,
    web_mode: str | None = None,
    feedback: str | None = None,
) -> dict:
    rag_service = get_rag_service()
    effective_top_k = top_k or settings.retrieval_default_top_k
    response = asyncio.run(
        rag_service.answer(
            query=question,
            top_k=effective_top_k,
            alpha=alpha,
            use_rerank=use_rerank,
            filters=filters,
            history=history,
            allow_web=allow_web,
            doc_only=doc_only,
            web_mode=web_mode,
            session_id=session_id,
            feedback=feedback,
        )
    )

    result_payload: dict[str, Any] = dict(response or {})
    result_payload.setdefault("answer", "")
    result_payload.setdefault("mode", "doc")
    result_payload.setdefault("citations", [])
    result_payload.setdefault("suggestions", [])
    result_payload["session_id"] = session_id
    result_payload["question"] = question

    return result_payload
