import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import orjson
from fastapi import APIRouter, HTTPException

from ..config import settings
from ..utils.gpu import detect_gpu
from ..utils.logger import get_logger
from ..services.providers import get_vector_service, get_hybrid_retriever

router = APIRouter(prefix="/api", tags=["status"])
index_status_router = APIRouter(prefix="/api", tags=["status"])

__all__ = ["router", "index_status_router"]


def _empty_meta() -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "documents": 0,
        "chunks": 0,
        "updated_at": now,
    }


def _load_status() -> Dict[str, Any]:
    try:
        raw = settings.meta_file_path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw else {}
    except FileNotFoundError:
        return _empty_meta()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Metadata file is corrupted") from exc

    documents = int(data.get("total_docs", data.get("documents", 0)))
    chunks = int(data.get("total_chunks", data.get("chunks", 0)))
    updated_at = (
        data.get("updated_at")
        or data.get("last_updated")
        or datetime.now(timezone.utc).isoformat()
    )

    return {
        "documents": documents,
        "chunks": chunks,
        "updated_at": updated_at,
    }


@router.get("/status")
async def get_status() -> dict[str, object]:
    status = _load_status()

    return {
        "total_docs": status["documents"],
        "total_chunks": status["chunks"],
        "updated_at": status["updated_at"],
    }


@index_status_router.get("/index/status")
async def get_index_status() -> Dict[str, Any]:
    return _load_status()


@router.get("/gpu/status")
async def gpu_status() -> Dict[str, Any]:
    preferred = settings.preferred_cuda_device if settings.enable_gpu else "cuda:0"
    info = detect_gpu(preferred)
    payload = info.as_dict()
    payload.update(
        {
            "configured_device": settings.embedding_device,
            "enable_gpu": settings.enable_gpu,
        }
    )
    return payload


@router.get("/retrieval/logs")
async def retrieval_logs(limit: int = 50) -> List[Dict[str, Any]]:
    if not settings.retrieval_log_path.exists():
        return []

    lines = settings.retrieval_log_path.read_bytes().splitlines()
    limit = max(1, min(limit, 200))
    selected = lines[-limit:]
    logs: List[Dict[str, Any]] = []
    for line in reversed(selected):
        try:
            logs.append(orjson.loads(line))
        except orjson.JSONDecodeError:
            continue
    return logs


@router.get("/retrieval/stats")
async def retrieval_stats() -> Dict[str, Any]:
    if not settings.retrieval_log_path.exists():
        return {
            "total": 0,
            "avg_final_top_k": 0.0,
            "avg_confidence": 0.0,
            "avg_rerank_gain": 0.0,
        }

    lines = settings.retrieval_log_path.read_bytes().splitlines()
    samples = [orjson.loads(line) for line in lines[-settings.max_retrieval_logs :] if line.strip()]
    if not samples:
        return {
            "total": 0,
            "avg_final_top_k": 0.0,
            "avg_confidence": 0.0,
            "avg_rerank_gain": 0.0,
        }

    total = len(samples)
    top_k_sum = 0
    confidence_sum = 0.0
    gains: List[float] = []

    for entry in samples:
        diagnostics = entry.get("diagnostics", {})
        final_results = diagnostics.get("final_results", [])
        top_k_sum += len(final_results)
        confidence_sum += float(diagnostics.get("confidence", 0.0))

        pre = diagnostics.get("pre_rerank")
        post = diagnostics.get("final_results")
        if pre and post:
            pre_score = float(pre[0].get("score", 0.0)) if pre else 0.0
            post_score = float(post[0].get("score", 0.0)) if post else 0.0
            gains.append(post_score - pre_score)

    return {
        "total": total,
        "avg_final_top_k": round(top_k_sum / total, 3) if total else 0.0,
        "avg_confidence": round(confidence_sum / total, 3) if total else 0.0,
        "avg_rerank_gain": round(sum(gains) / len(gains), 3) if gains else 0.0,
    }


@router.delete("/index/clear")
async def clear_index() -> dict[str, str]:
    """清空所有索引数据，包括向量索引、BM25索引和元数据"""

    logger = get_logger(__name__)

    try:
        # 清空向量索引（内存+磁盘）
        vector_service = get_vector_service()
        vector_service.clear_storage()

        # 清空BM25索引
        if settings.bm25_index_path.exists():
            import shutil
            shutil.rmtree(settings.bm25_index_path)
            settings.bm25_index_path.mkdir(parents=True, exist_ok=True)
            logger.info("BM25 index cleared")

        # 刷新检索器内缓存的 BM25 结构
        get_hybrid_retriever().refresh_indexes()

        # 清空元数据
        if settings.meta_file_path.exists():
            settings.meta_file_path.unlink()
            logger.info("Metadata cleared")

        # 清空检索日志
        if settings.retrieval_log_path.exists():
            settings.retrieval_log_path.unlink()
            logger.info("Retrieval logs cleared")

        return {"status": "ok", "message": "All indexes cleared successfully"}

    except Exception as e:
        logger.error("Failed to clear indexes", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to clear indexes: {str(e)}")


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
