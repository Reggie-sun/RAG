from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections import defaultdict, deque
from threading import Lock
from typing import Any, Deque, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, validator

from ..config import settings
from ..services.feedback_store import compose_feedback_text, feedback_store
from ..services.memory_store import memory_store, render_history
from ..services.providers import get_rag_service
from ..utils.logger import get_logger

router = APIRouter(prefix="/integrations/customer-service", tags=["Customer Service"])
logger = get_logger(__name__)

_RATE_LIMIT_WINDOW_SECONDS = 60.0
_RATE_LIMIT_LOCK = Lock()
_rate_limit_cache: Dict[str, Deque[float]] = defaultdict(deque)


class CustomerServiceFilters(BaseModel):
    source: Optional[list[str]] = Field(default=None)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @validator("source", pre=True)
    def clean_source(cls, value: Any) -> Any:
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned or None
        return value


class CustomerServiceAskPayload(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=settings.retrieval_max_top_k,
    )
    allow_web: Optional[bool] = None
    doc_only: Optional[bool] = None
    filters: Optional[CustomerServiceFilters] = None
    metadata: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None
    feedback_tags: Optional[list[str]] = None

    @validator("metadata", pre=True)
    def clean_metadata(cls, value: Any) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("metadata must be an object")
        return value or None

    @validator("filters", pre=True)
    def normalize_filters(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value:
            return None
        return value


def _resolve_top_k(value: Optional[int]) -> int:
    if value is None:
        return settings.retrieval_default_top_k
    return max(1, min(value, settings.retrieval_max_top_k))


def _format_filters(filters: Optional[CustomerServiceFilters]) -> Optional[Dict[str, Any]]:
    if filters is None:
        return None
    data = filters.dict(exclude_none=True)
    return data or None


def _hash_token(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return digest[:12]


def _partner_identity(partner_name: Optional[str], token: Optional[str]) -> str:
    if partner_name:
        name = partner_name.strip()
        if name:
            return name
    if token:
        return f"token:{_hash_token(token)}"
    return "anonymous"


def _enforce_rate_limit(identity: str) -> None:
    limit = max(1, settings.customer_service_rate_limit_per_minute)
    now = time.monotonic()
    with _RATE_LIMIT_LOCK:
        bucket = _rate_limit_cache[identity]
        while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = _RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0]) if bucket else _RATE_LIMIT_WINDOW_SECONDS
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": f"{int(retry_after)}"},
            )
        bucket.append(now)


def require_token(
    token: Optional[str] = Header(default=None, alias="X-Customer-Service-Token"),
) -> Optional[str]:
    expected = (settings.customer_service_api_key or "").strip()
    if not expected:
        return None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )
    if not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication token",
        )
    return token


@router.post("/ask")
async def ask_via_customer_service(
    payload: CustomerServiceAskPayload,
    token_value: Optional[str] = Depends(require_token),
    partner_name: Optional[str] = Header(default=None, alias="X-Customer-Service-Partner"),
) -> Dict[str, Any]:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Field 'question' is required")

    session_id = (payload.session_id or "").strip() or str(uuid.uuid4())
    filters = _format_filters(payload.filters)
    top_k = _resolve_top_k(payload.top_k)
    history_block = render_history(memory_store.history(session_id))
    merged_feedback = compose_feedback_text(payload.feedback, payload.feedback_tags)
    feedback_text = feedback_store.sync(session_id, question, merged_feedback)

    identity = _partner_identity(partner_name, token_value)
    _enforce_rate_limit(identity)
    logger.info(
        "customer_service.request",
        extra={
            "session_id": session_id,
            "identity": identity,
            "allow_web": payload.allow_web,
            "doc_only": payload.doc_only,
            "top_k": top_k,
            "metadata": payload.metadata or {},
        },
    )

    rag_service = get_rag_service()

    try:
        response = await rag_service.answer(
            query=question,
            top_k=top_k,
            filters=filters,
            history=history_block,
            allow_web=payload.allow_web,
            doc_only=payload.doc_only,
            session_id=session_id,
            feedback=feedback_text or None,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "customer_service.answer_failed",
            extra={"session_id": session_id, "identity": identity},
        )
        raise HTTPException(
            status_code=503,
            detail="Unable to generate an answer at this time",
        )

    answer_text = (response.get("answer") or "").strip()
    if answer_text:
        memory_store.append(session_id, question, answer_text)

    logger.info(
        "customer_service.response",
        extra={
            "session_id": session_id,
            "identity": identity,
            "has_answer": bool(answer_text),
            "citations": len(response.get("citations") or []),
        },
    )

    return {
        "session_id": session_id,
        "question": question,
        "answer": answer_text,
        "mode": response.get("mode", "general"),
        "citations": response.get("citations") or [],
        "suggestions": response.get("suggestions") or [],
        "sources": response.get("sources") or [],
        "diagnostics": response.get("diagnostics") or {},
        "metadata": payload.metadata or {},
    }
