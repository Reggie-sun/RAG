import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Literal

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator

from ..config import settings
from ..services.providers import get_rag_service
from ..services.rag_service import RAGService
from ..services.memory_store import memory_store, render_history
from ..services.intent_classifier import build_intent_response, detect_intent
from ..services.feedback_store import feedback_store, compose_feedback_text
from ..utils.logger import get_logger

router = APIRouter(prefix="/api", tags=["search"])
logger = get_logger(__name__)


class SearchFilters(BaseModel):
    source: Optional[list[str]] = Field(default=None)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=settings.retrieval_default_top_k, ge=1, le=settings.retrieval_max_top_k)
    alpha: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    use_rerank: Optional[bool] = None
    filters: Optional[SearchFilters] = None
    session_id: Optional[str] = None
    doc_only: Optional[bool] = None
    allow_web: Optional[bool] = None
    web_mode: Optional[str] = None
    feedback: Optional[str] = None
    feedback_tags: Optional[List[str]] = None

    @validator("filters", pre=True)
    def empty_filters_to_none(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value:
            return None
        return value


class Citation(BaseModel):
    source: Optional[str] = None
    page: Optional[int] = None
    snippet: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    answer: str
    mode: Literal["doc", "general", "chitchat", "guidance"]
    citations: List[Citation] = Field(default_factory=list)
    session_id: str
    suggestions: List[str] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    multi_topics: List[str] = Field(default_factory=list)


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    payload: SearchRequest,
    rag_service: RAGService = Depends(get_rag_service),
) -> SearchResponse:
    session_id = (payload.session_id or "").strip() or str(uuid.uuid4())
    history_pairs = memory_store.history(session_id)
    history_block = render_history(history_pairs)
    merged_feedback = compose_feedback_text(payload.feedback, payload.feedback_tags)
    feedback_text = feedback_store.sync(session_id, payload.query, merged_feedback)
    aggregated_feedback = feedback_text or None

    intent = detect_intent(payload.query)
    logger.info("search.request", extra={"query": payload.query, "session_id": session_id, "intent": intent})
    if intent in {"greeting", "thanks", "short"}:
        answer, mode, suggestions = build_intent_response(intent)
        memory_store.append(session_id, payload.query, answer)
        return SearchResponse(
            answer=answer,
            mode=mode,
            citations=[],
            session_id=session_id,
            suggestions=suggestions,
        )
    if intent == "general_qa":
        try:
            response = await rag_service.answer_general(
                payload.query,
                history_block,
                feedback=aggregated_feedback,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        memory_store.append(session_id, payload.query, response.get("answer", ""))
        return SearchResponse(
            answer=response.get("answer", ""),
            mode=response.get("mode", "general"),
            citations=response.get("citations", []),
            session_id=session_id,
            suggestions=response.get("suggestions", []),
            sources=response.get("sources", []),
            meta=response.get("meta", {}),
            diagnostics=response.get("diagnostics", {}),
            multi_topics=response.get("multi_topics", []),
        )

    try:
        response = await rag_service.answer(
            query=payload.query,
            top_k=payload.top_k,
            alpha=payload.alpha,
            use_rerank=payload.use_rerank,
            filters=payload.filters.dict(exclude_none=True) if payload.filters else None,
            history=history_block,
            allow_web=payload.allow_web,
            doc_only=payload.doc_only,
            web_mode=payload.web_mode,
            session_id=session_id,
            feedback=aggregated_feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    _append_retrieval_log(
        {
            "query": payload.query,
            "top_k": payload.top_k,
            "alpha": payload.alpha,
            "use_rerank": payload.use_rerank,
            "filters": payload.filters.dict(exclude_none=True) if payload.filters else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "diagnostics": response.get("diagnostics", {}),
            "answer_preview": response.get("answer", "")[:400],
            "session_id": session_id,
        }
    )

    memory_store.append(session_id, payload.query, response.get("answer", ""))

    return SearchResponse(
        answer=response.get("answer", ""),
        mode=response.get("mode", "doc"),
        citations=response.get("citations", []),
        session_id=session_id,
        suggestions=response.get("suggestions", []),
        sources=response.get("sources", []),
        meta=response.get("meta", {}),
        diagnostics=response.get("diagnostics", {}),
        multi_topics=response.get("multi_topics", []),
    )


@router.get("/stream")
async def stream_answer(
    query: str = Query(..., min_length=1),
    top_k: int = Query(settings.retrieval_default_top_k, ge=1, le=settings.retrieval_max_top_k),
    alpha: Optional[float] = Query(None, ge=0.0, le=1.0),
    use_rerank: Optional[bool] = Query(None),
    source: Optional[str] = Query(None, description="Comma separated source filters"),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    rag_service: RAGService = Depends(get_rag_service),
) -> StreamingResponse:
    filters = {}
    if source:
        filters["source"] = [item.strip() for item in source.split(",") if item.strip()]
    if min_score is not None:
        filters["min_score"] = min_score

    try:
        sources, generator, diagnostics = await rag_service.stream(
            query=query,
            top_k=top_k,
            alpha=alpha,
            use_rerank=use_rerank,
            filters=filters or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def event_stream() -> AsyncGenerator[str, None]:
        answer_chunks: List[str] = []
        yield f"event: sources\ndata: {json.dumps(sources)}\n\n"
        try:
            async for chunk in generator:
                answer_chunks.append(chunk)
                payload = json.dumps({"type": "token", "data": chunk})
                yield f"data: {payload}\n\n"
        except RuntimeError as exc:
            error_payload = json.dumps({"type": "error", "message": str(exc)})
            yield f"event: error\ndata: {error_payload}\n\n"
        else:
            yield "event: end\ndata: [DONE]\n\n"
        finally:
            _append_retrieval_log(
                {
                    "query": query,
                    "top_k": top_k,
                    "alpha": alpha,
                    "use_rerank": use_rerank,
                    "filters": filters or None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "diagnostics": diagnostics,
                    "answer_preview": "".join(answer_chunks)[:400],
                }
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _append_retrieval_log(entry: Dict[str, Any]) -> None:
    path = settings.retrieval_log_path
    serialized = orjson.dumps(entry) + b"\n"
    with path.open("ab") as fh:
        fh.write(serialized)

    lines = path.read_bytes().splitlines()
    if len(lines) > settings.max_retrieval_logs:
        trimmed = lines[-settings.max_retrieval_logs :]
        path.write_bytes(b"\n".join(trimmed) + b"\n")
