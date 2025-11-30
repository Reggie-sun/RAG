from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import re

import orjson
from rank_bm25 import BM25Okapi

from ..config import settings
from .rerank_service import RerankService
from .vector_service import VectorService


@dataclass
class HybridRetrievalResult:
    results: List[Dict[str, Any]]
    diagnostics: Dict[str, Any]


class HybridRetriever:
    def __init__(
        self,
        vector_service: VectorService,
        reranker: Optional[RerankService] = None,
        alpha: float | None = None,
    ) -> None:
        self.vector_service = vector_service
        self.reranker = reranker if settings.use_rerank else None
        self.alpha = alpha or settings.vector_weight
        self.index_file = settings.bm25_index_path / "index.jsonl"
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_entries: List[Dict[str, Any]] = []
        self._load_bm25_index()

    async def retrieve(
        self,
        query: str,
        top_k: int,
        alpha: Optional[float] = None,
        use_rerank: Optional[bool] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> HybridRetrievalResult:
        alpha = alpha if alpha is not None else self.alpha
        use_rerank = use_rerank if use_rerank is not None else settings.use_rerank
        filters = filters or {}

        diagnostics: Dict[str, Any] = {
            "query": query,
            "alpha": alpha,
            "requested_top_k": top_k,
            "filters": filters,
            "confidence_threshold": settings.retrieval_confidence_threshold,
        }

        adaptive_k = max(top_k, settings.retrieval_default_top_k)
        adaptive_k = min(adaptive_k, settings.retrieval_max_top_k)

        fused_results: List[Dict[str, Any]] = []
        confidence = 0.0

        while True:
            vector_hits = self.vector_service.search(query, adaptive_k)
            bm25_hits = self._search_bm25(query, adaptive_k)

            fused_results = self._fuse_results(vector_hits, bm25_hits, alpha)
            fused_results = self._dedup_by_source_page(fused_results)
            fused_results = self._apply_filters(fused_results, filters)
            fused_results = self._filter_gibberish(fused_results, diagnostics)
            confidence = fused_results[0]["score"] if fused_results else 0.0

            diagnostics.update(
                {
                    "vector_hits": vector_hits,
                    "bm25_hits": bm25_hits,
                    "fused_top_k": adaptive_k,
                    "confidence": confidence,
                }
            )

            if confidence >= settings.retrieval_confidence_threshold or adaptive_k >= settings.retrieval_max_top_k:
                break
            adaptive_k = min(adaptive_k * 2, settings.retrieval_max_top_k)

        capped_results = fused_results[: adaptive_k]

        diagnostics["pre_rerank"] = capped_results

        if use_rerank and self.reranker is not None:
            reranked = await self.reranker.rerank(query, capped_results)
            diagnostics["reranked"] = reranked
            capped_results = reranked

        final_results = capped_results[:top_k]
        diagnostics["final_results"] = final_results
        diagnostics["final_top_k"] = len(final_results)

        return HybridRetrievalResult(results=final_results, diagnostics=diagnostics)

    def refresh_indexes(self) -> None:
        self._load_bm25_index()

    def _load_bm25_index(self) -> None:
        if not self.index_file.exists():
            self._bm25 = None
            self._bm25_entries = []
            return

        entries: List[Dict[str, Any]] = []
        with self.index_file.open("rb") as fh:
            for line in fh:
                if not line.strip():
                    continue
                entries.append(orjson.loads(line))

        self._bm25_entries = entries
        if entries:
            token_lists = [entry.get("tokens", []) for entry in entries]
            self._bm25 = BM25Okapi(token_lists)
        else:
            self._bm25 = None

    def _search_bm25(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if self._bm25 is None or not query.strip():
            return []

        tokens = self._tokenize(query)
        scores = self._bm25.get_scores(tokens)
        paired = list(zip(self._bm25_entries, scores))
        paired.sort(key=lambda item: item[1], reverse=True)
        results: List[Dict[str, Any]] = []
        for entry, score in paired[:top_k]:
            results.append(
                {
                    "chunk_id": entry["chunk_id"],
                    "text": entry["text"],
                    "score": float(score),
                    "source": entry.get("source"),
                    "metadata": entry.get("metadata", {}),
                    "bm25_only": True,
                }
            )
        return results

    def _fuse_results(
        self,
        vector_hits: List[Dict[str, Any]],
        bm25_hits: List[Dict[str, Any]],
        alpha: float,
    ) -> List[Dict[str, Any]]:
        alpha = min(max(alpha, 0.0), 1.0)
        combined: Dict[str, Dict[str, Any]] = {}

        vec_norm = self._normalize_scores(vector_hits)
        bm25_norm = self._normalize_scores(bm25_hits)

        for item in vector_hits:
            chunk_id = str(item.get("chunk_id"))
            combined[chunk_id] = {
                **item,
                "vector_score": vec_norm.get(chunk_id, item.get("score", 0.0)),
                "bm25_score": bm25_norm.get(chunk_id, 0.0),
            }

        for item in bm25_hits:
            chunk_id = str(item.get("chunk_id"))
            current = combined.get(chunk_id)
            if current is None:
                combined[chunk_id] = {
                    **item,
                    "vector_score": vec_norm.get(chunk_id, 0.0),
                    "bm25_score": bm25_norm.get(chunk_id, item.get("score", 0.0)),
                }
            else:
                current["bm25_score"] = bm25_norm.get(chunk_id, item.get("score", 0.0))

        fused: List[Dict[str, Any]] = []
        for chunk_id, item in combined.items():
            vector_score = item.get("vector_score", 0.0)
            bm25_score = item.get("bm25_score", 0.0)
            # 如果只有一条路径有分数，就直接用该路径的分数，避免被 alpha 稀释成恒 0.6
            if bm25_score == 0.0 and vector_score != 0.0:
                fused_score = vector_score
            elif vector_score == 0.0 and bm25_score != 0.0:
                fused_score = bm25_score
            else:
                fused_score = alpha * vector_score + (1 - alpha) * bm25_score
            metadata = {**item.get("metadata", {})}
            metadata.setdefault("chunk_id", item.get("chunk_id"))
            metadata.setdefault("source", item.get("source"))
            metadata.setdefault("page", item.get("metadata", {}).get("page"))
            metadata["vector_score"] = vector_score
            metadata["bm25_score"] = bm25_score
            metadata["score"] = fused_score
            fused.append({**item, "score": fused_score, "metadata": metadata})

        fused.sort(key=lambda item: item["score"], reverse=True)
        return fused

    def _normalize_scores(self, hits: List[Dict[str, Any]]) -> Dict[str, float]:
        if not hits:
            return {}
        scores = [float(item.get("score", 0.0)) for item in hits]
        max_score = max(scores)
        min_score = min(scores)
        # 如果所有分数相同，按排名做轻微衰减，避免全部落在同一个分数档
        if max_score == min_score:
            normalized: Dict[str, float] = {}
            for idx, item in enumerate(hits):
                base = float(item.get("score", 0.0)) or 1.0
                decay = max(0.5, 1.0 - 0.05 * idx)  # 至少保留 0.5
                normalized[str(item.get("chunk_id"))] = base * decay
            return normalized
        return {
            str(item.get("chunk_id")): (float(item.get("score", 0.0)) - min_score) / (max_score - min_score)
            for item in hits
        }

    def _apply_filters(self, hits: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not filters:
            return hits
        allowed_sources = {value.lower() for value in (filters.get("source") or [])}
        min_score = float(filters.get("min_score", 0.0))

        filtered: List[Dict[str, Any]] = []
        for item in hits:
            metadata = item.get("metadata", {})
            if allowed_sources:
                source_type = (metadata.get("source_type") or metadata.get("extension") or "").lower()
                if source_type not in allowed_sources:
                    continue
            if item.get("score", 0.0) < min_score:
                continue
            filtered.append(item)
        return filtered or hits

    def _filter_gibberish(self, hits: List[Dict[str, Any]], diagnostics: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not hits:
            return hits

        def _looks_like_mojibake(text: str) -> bool:
            cleaned = (text or "").strip()
            if len(cleaned) < 8:
                return False
            cjk = sum(1 for ch in cleaned if "\u4e00" <= ch <= "\u9fff")
            latin_supp = sum(1 for ch in cleaned if "\u00c0" <= ch <= "\u017f")
            basic_latin = sum(1 for ch in cleaned if "a" <= ch.lower() <= "z")
            total = len(cleaned)
            if cleaned.count("�") / max(total, 1) > 0.02:
                return True
            if cjk == 0 and ("Ã" in cleaned or "Â" in cleaned or latin_supp > 0):
                ratio = (basic_latin + latin_supp) / max(total, 1)
                if ratio > 0.7:
                    return True
            if cjk == 0:
                extended = sum(1 for ch in cleaned if ch in {"ä", "å", "æ", "ç", "è", "é", "ê", "ë", "ö", "ø", "ï", "î", "ñ"})
                ratio = (basic_latin + latin_supp) / max(total, 1)
                if extended and ratio > 0.6:
                    return True
                if ratio > 0.85:
                    return True
            if re.fullmatch(r"[-=+/\\_|~!@#$%^&*()<>\"'`:;.,，。；、…·\\s]{8,}", cleaned):
                return True
            return False

        filtered: List[Dict[str, Any]] = []
        for item in hits:
            text = (
                item.get("text")
                or item.get("metadata", {}).get("text")
                or item.get("content")
                or ""
            )
            if _looks_like_mojibake(str(text)):
                continue
            filtered.append(item)

        removed = len(hits) - len(filtered)
        if filtered:
            if removed > 0:
                diagnostics["gibberish_filtered"] = removed
            return filtered
        return hits

    def _dedup_by_source_page(
        self,
        hits: List[Dict[str, Any]],
        *,
        max_per_source: int | None = None,
        max_per_page: int | None = None,
    ) -> List[Dict[str, Any]]:
        """
        简单多样性约束：可选限制同一来源/页码的返回数量，减少重复片段。
        若参数为空则不做限制。
        """
        if not hits or (max_per_source is None and max_per_page is None):
            return hits

        per_source: Dict[str, int] = {}
        per_page: Dict[tuple[str, str], int] = {}
        diversified: List[Dict[str, Any]] = []

        for item in hits:
            md = item.get("metadata", {}) or {}
            source = md.get("source") or item.get("source") or "unknown"
            page = str(md.get("page", ""))

            if max_per_source is not None:
                src_count = per_source.get(source, 0)
                if src_count >= max_per_source:
                    continue
            else:
                src_count = per_source.get(source, 0)

            if max_per_page is not None and page:
                page_key = (source, page)
                page_count = per_page.get(page_key, 0)
                if page_count >= max_per_page:
                    continue
            else:
                page_key = (source, page)
                page_count = per_page.get(page_key, 0)

            diversified.append(item)
            per_source[source] = src_count + 1
            per_page[page_key] = page_count + 1

        return diversified or hits

    def _tokenize(self, text: str) -> List[str]:
        return [token.lower() for token in text.split() if token.strip()]
