from __future__ import annotations

from contextlib import asynccontextmanager
import uuid
from typing import Any, Optional, List

from celery.result import AsyncResult
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator

from .agent_init import build_agent
from .config import settings
from .routers.search import router as search_router
from .routers.status import index_status_router, router as status_router
from .routers.upload import router as upload_router
from .routers.feishu import router as feishu_router
from .routers.customer_service import router as customer_service_router
from .routers.wechat import router as wechat_router
from .services.memory_store import memory_store, render_history
from .services.providers import get_rag_service
from .services.intent_classifier import build_intent_response, detect_intent
from .services.feedback_store import feedback_store, compose_feedback_text
from .task import answer_sync, celery_app, rag_answer_task
from .utils.logger import get_logger

_agent: Any | None = None
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent
    settings.ensure_directories()
    _agent = build_agent()
    try:
        yield
    finally:
        _agent = None


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_agent() -> Any:
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return _agent


app.include_router(search_router)
app.include_router(index_status_router)
app.include_router(status_router)
app.include_router(upload_router)
app.include_router(feishu_router)
app.include_router(customer_service_router)
app.include_router(wechat_router)


class AsyncFilters(BaseModel):
    source: Optional[list[str]] = Field(default=None)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @validator("source", pre=True)
    def clean_source(cls, value: Any) -> Any:
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned or None
        return value


class AsyncAskPayload(BaseModel):
    query: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    top_k: Optional[int] = Field(
        default=None, ge=1, le=settings.retrieval_max_top_k
    )
    alpha: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    use_rerank: Optional[bool] = None
    filters: Optional[AsyncFilters] = None
    doc_only: Optional[bool] = None
    allow_web: Optional[bool] = None
    web_mode: Optional[str] = None
    feedback: Optional[str] = None
    feedback_tags: Optional[List[str]] = None

    @validator("filters", pre=True)
    def empty_filters(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value:
            return None
        return value


def _resolve_top_k(value: Optional[int]) -> int:
    if value is None:
        return settings.retrieval_default_top_k
    return max(1, min(value, settings.retrieval_max_top_k))


def _format_filters(filters: Optional[AsyncFilters]) -> Optional[dict]:
    if filters is None:
        return None
    data = filters.dict(exclude_none=True)
    return data or None


@app.post("/api/chat")
async def chat(q: str, agent: Any = Depends(get_agent)) -> dict[str, Any]:
    answer = agent.run(q)
    return {"answer": answer}


@app.post("/api/ask")
async def enqueue_rag(payload: AsyncAskPayload, _request: Request) -> dict[str, Any]:
    logger.info(
        "ask.enqueue",
        extra={
            "session_id": payload.session_id,
            "top_k": payload.top_k,
            "alpha": payload.alpha,
            "use_rerank": payload.use_rerank,
        },
    )
    question = payload.query.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Field 'query' is required")

    session_id = (payload.session_id or "").strip() or str(uuid.uuid4())
    history_block = render_history(memory_store.history(session_id))
    merged_feedback = compose_feedback_text(payload.feedback, payload.feedback_tags)
    feedback_text = feedback_store.sync(session_id, question, merged_feedback)
    aggregated_feedback = feedback_text or None
    intent = detect_intent(question)
    if intent in {"greeting", "thanks", "short"}:
        answer, mode, suggestions = build_intent_response(intent)
        result_payload = {
            "answer": answer,
            "mode": mode,
            "citations": [],
            "session_id": session_id,
            "suggestions": suggestions,
        }
        memory_store.append(session_id, question, answer)
        return {"task_id": None, "session_id": session_id, "result": result_payload}
    if intent == "general_qa" and not payload.doc_only:
        rag_service = get_rag_service()
        response = await rag_service.answer_general(
            question,
            history_block,
            feedback=aggregated_feedback,
        )
        response["session_id"] = session_id
        memory_store.append(session_id, question, response.get("answer", ""))
        return {"task_id": None, "session_id": session_id, "result": response}

    top_k = _resolve_top_k(payload.top_k)
    filters = _format_filters(payload.filters)

    task = rag_answer_task.delay(
        question,
        session_id,
        history_block,
        top_k,
        payload.alpha,
        payload.use_rerank,
        filters,
        payload.allow_web,
        payload.doc_only,
        payload.web_mode,
        aggregated_feedback,
    )
    return {"task_id": task.id, "session_id": session_id}


@app.get("/api/result/{task_id}")
def fetch_rag_result(task_id: str) -> dict[str, Any]:
    async_result = AsyncResult(task_id, app=celery_app)
    status = async_result.status
    if async_result.successful():
        data = async_result.result or {}
        session_id = data.get("session_id")
        question = data.get("question")
        answer = data.get("answer")
        if session_id and question and answer:
            memory_store.append(session_id, question, answer)
        return {"status": status, "result": data}
    if async_result.failed():
        return {"status": status, "error": str(async_result.result)}
    return {"status": status}


@app.post("/api/tasks/ask")
def enqueue_task(payload: dict[str, str] = Body(...)) -> dict[str, str]:
    question = (payload.get("q") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Field 'q' is required")
    task = answer_sync.delay(question)
    return {"task_id": task.id}


@app.get("/api/tasks/result/{task_id}")
def fetch_result(task_id: str) -> dict[str, Any]:
    result = AsyncResult(task_id, app=celery_app)
    if result.successful():
        return {"status": result.status, "result": result.result}
    if result.failed():
        return {"status": result.status, "error": str(result.result)}
    return {"status": result.status}


static_dir = (settings.base_dir / "../frontend/dist").resolve()
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
