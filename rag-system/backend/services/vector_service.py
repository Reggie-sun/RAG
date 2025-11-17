from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple
import shutil

import numpy as np
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

from ..config import settings
from ..utils.gpu import detect_gpu, parse_cuda_device
from ..utils.logger import get_logger
from .cache import batch_hash, get_cache
from .local_embeddings import LocalBgeEmbeddings

try:
    import faiss  # type: ignore
except ImportError:  # pragma: no cover - faiss may be CPU-only
    faiss = None  # type: ignore


class VectorService:
    def __init__(self, index_dir: Path | None = None) -> None:
        self.index_dir = index_dir or settings.faiss_index_path
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(__name__)
        self._gpu_enabled = bool(settings.enable_gpu and faiss is not None)
        self._gpu_device_id = parse_cuda_device(settings.preferred_cuda_device)
        self._gpu_resources = None
        self._gpu_index = None
        self._cache = get_cache()
        self._embedding = self._build_embedding()
        self._index_state = None
        self._vector_store: FAISS | None = self._load_vector_store()
        if self._gpu_enabled:
            info = detect_gpu(settings.preferred_cuda_device)
            if info.available:
                self.logger.info(
                    "gpu.embedding.enabled",
                    extra={
                        "device": info.device,
                        "name": info.name,
                        "memory_gb": info.total_memory_gb,
                    },
                )
            else:
                self._gpu_enabled = False

    def add_documents(self, documents: List[Document]) -> None:
        if not documents:
            return

        texts = [doc.page_content for doc in documents]
        embeddings = self._embed_documents(documents)
        metadatas = [doc.metadata for doc in documents]
        pairs = list(zip(texts, embeddings))

        if self._vector_store is None:
            self._vector_store = FAISS.from_embeddings(pairs, self._embedding, metadatas=metadatas)
        else:
            self._vector_store.add_embeddings(pairs, metadatas=metadatas)
        self._save_vector_store()

    def search(self, query: str, top_k: int) -> List[dict]:
        if not query.strip():
            return []

        self._ensure_fresh_vector_store()

        if self._vector_store is None:
            return []

        vector = self._embed_query(query)
        results = self._similarity_search(vector, top_k)
        payload: List[dict] = []
        for doc, score in results:
            metadata = dict(doc.metadata)
            payload.append(
                {
                    "chunk_id": metadata.get("chunk_id"),
                    "text": doc.page_content,
                    "score": float(score),
                    "source": metadata.get("source", metadata.get("filename", "unknown")),
                    "metadata": metadata,
                }
            )
        return payload

    def _embed_documents(self, documents: Iterable[Document]) -> List[List[float]]:
        texts = [doc.page_content for doc in documents]
        hashes = batch_hash(texts)
        embeddings: List[List[float] | None] = [None] * len(texts)
        missing_indices: List[int] = []
        missing_texts: List[str] = []

        for idx, key in enumerate(hashes):
            cached = self._cache.get(key)
            if cached is not None:
                embeddings[idx] = cached
            else:
                missing_indices.append(idx)
                missing_texts.append(texts[idx])

        if missing_texts:
            computed = self._embedding.embed_documents(missing_texts)
            for idx, vec in zip(missing_indices, computed):
                embeddings[idx] = vec
                self._cache.set(hashes[idx], vec)

        return [vec for vec in embeddings if vec is not None]

    def _embed_query(self, query: str) -> List[float]:
        key = batch_hash([f"query::{query}"])[0]
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        vector = self._embedding.embed_query(query)
        self._cache.set(key, vector)
        return vector

    def _load_vector_store(self) -> FAISS | None:
        index_file = self.index_dir / "index.faiss"
        if not index_file.exists():
            self._index_state = self._snapshot_index_state()
            return None
        store = FAISS.load_local(
            str(self.index_dir),
            self._embedding,
            allow_dangerous_deserialization=True,
        )
        self._invalidate_gpu_index()
        self._index_state = self._snapshot_index_state()
        return store

    def _save_vector_store(self) -> None:
        if self._vector_store is None:
            return
        self._vector_store.save_local(str(self.index_dir))
        self._invalidate_gpu_index()
        self._index_state = self._snapshot_index_state()

    def clear_storage(self) -> None:
        """Clear in-memory and on-disk vector indexes."""
        try:
            if self.index_dir.exists():
                shutil.rmtree(self.index_dir)
            self.index_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.logger.warning("vector.clear_storage.disk_failed", extra={"error": str(exc)})
        self._vector_store = None
        self._invalidate_gpu_index()
        self._index_state = self._snapshot_index_state()
        self.logger.info("vector.clear_storage.completed")

    @property
    def vector_store(self) -> FAISS | None:
        return self._vector_store

    def _build_embedding(self) -> LocalBgeEmbeddings:
        model_path = settings.embedding_model_path
        if not model_path.exists():
            raise RuntimeError(f"Embedding model not found at {model_path}")
        return LocalBgeEmbeddings(model_path=model_path, device=settings.embedding_device)

    def _similarity_search(self, vector: List[float], top_k: int) -> List[Tuple[Document, float]]:
        if self._vector_store is None:
            return []

        search_with_scores = getattr(self._vector_store, "similarity_search_by_vector_with_relevance_scores", None)
        if callable(search_with_scores):
            return search_with_scores(vector, k=top_k)

        legacy_with_scores = getattr(self._vector_store, "similarity_search_by_vector_with_score", None)
        if callable(legacy_with_scores):
            return legacy_with_scores(vector, k=top_k)

        if hasattr(self._vector_store, "index"):
            return self._manual_index_search(vector, top_k)

        docs_only = getattr(self._vector_store, "similarity_search_by_vector", None)
        if callable(docs_only):
            docs = docs_only(vector, k=top_k)
            return [(doc, 0.0) for doc in docs]

        return []

    def _manual_index_search(self, vector: List[float], top_k: int) -> List[Tuple[Document, float]]:
        index = self._get_search_index()
        if index is None:
            return []

        query = np.asarray([vector], dtype=np.float32)
        distances, indices = index.search(query, top_k)
        ids_map = self._vector_store.index_to_docstore_id
        docstore = self._vector_store.docstore

        pairs: List[Tuple[Document, float]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            doc_id = ids_map.get(idx) if isinstance(ids_map, dict) else ids_map[idx]
            if doc_id is None:
                continue
            if hasattr(docstore, "search"):
                document = docstore.search(doc_id)
            elif hasattr(docstore, "get"):
                document = docstore.get(doc_id)
            else:
                document = None
            if document is None:
                continue
            score = self._convert_distance_to_score(float(dist))
            pairs.append((document, score))

        return pairs

    def _get_search_index(self):
        if self._vector_store is None:
            return None
        base_index = getattr(self._vector_store, "index", None)
        if base_index is None:
            return None
        if not self._gpu_enabled or faiss is None:
            return base_index
        if self._gpu_index is not None:
            return self._gpu_index
        try:
            self._gpu_resources = faiss.StandardGpuResources()  # type: ignore[attr-defined]
            self._gpu_index = faiss.index_cpu_to_gpu(  # type: ignore[attr-defined]
                self._gpu_resources,
                self._gpu_device_id,
                base_index,
            )
            self.logger.info(
                "gpu.faiss.index_ready",
                extra={
                    "device_id": self._gpu_device_id,
                    "vectors": getattr(base_index, "ntotal", 0),
                },
            )
            return self._gpu_index
        except Exception as exc:
            self.logger.warning("gpu.faiss.disabled", extra={"reason": str(exc)})
            self._gpu_enabled = False
            self._gpu_index = None
            self._gpu_resources = None
            return base_index

    def _invalidate_gpu_index(self) -> None:
        if self._gpu_index is not None:
            try:
                del self._gpu_index
            except Exception:
                pass
        self._gpu_index = None
        self._gpu_resources = None

    def _convert_distance_to_score(self, distance: float) -> float:
        try:
            import faiss  # type: ignore

            metric_type = getattr(self._vector_store.index, "metric_type", None)
            if metric_type == faiss.METRIC_INNER_PRODUCT:
                return distance
        except Exception:
            pass
        return float(1.0 / (1.0 + max(distance, 0.0)))

    def _snapshot_index_state(self):
        faiss_file = self.index_dir / "index.faiss"
        docstore_file = self.index_dir / "index.pkl"

        def info(path: Path):
            if not path.exists():
                return (False, None, None)
            stat = path.stat()
            return (True, stat.st_mtime_ns, stat.st_size)

        return (info(faiss_file), info(docstore_file))

    def _ensure_fresh_vector_store(self) -> None:
        current_state = self._snapshot_index_state()
        if self._index_state == current_state:
            return
        self._vector_store = self._load_vector_store()
        if self._vector_store is None:
            self.logger.info("vector.reload.empty")
        else:
            self.logger.info(
                "vector.reload.loaded",
                extra={"vectors": getattr(self._vector_store.index, "ntotal", 0)},
            )
