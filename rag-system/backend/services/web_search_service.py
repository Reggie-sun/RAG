from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import httpx
from tavily import TavilyClient

try:
    from ..config import settings
    from ..utils.logger import get_logger
except ImportError:  # pragma: no cover - allow `services.*` imports
    try:
        from backend.config import settings  # type: ignore
        from backend.utils.logger import get_logger  # type: ignore
    except ImportError:
        from rag_system.backend.config import settings  # type: ignore
        from rag_system.backend.utils.logger import get_logger  # type: ignore


class WebSearchQuotaExceededError(RuntimeError):
    """Raised when Tavily reports that the usage/quota limit has been reached."""
    pass


class WebSearchService:
    PROVIDER_TAVILY = "tavily"
    PROVIDER_WEBSEARCHAPI = "websearchapi"
    PROVIDER_EXA = "exa"
    PROVIDER_FIRECRAWL = "firecrawl"
    KNOWN_PROVIDERS = {
        PROVIDER_TAVILY,
        PROVIDER_WEBSEARCHAPI,
        PROVIDER_EXA,
        PROVIDER_FIRECRAWL,
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        max_results: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.logger = get_logger(__name__)
        self.api_key = api_key or settings.tavily_api_key
        self.max_results = max_results or settings.web_search_max_results
        self.timeout = timeout or settings.web_search_timeout
        self.websearch_api_key = getattr(settings, "websearch_api_key", "")
        self.exa_api_key = getattr(settings, "exa_api_key", "")
        self.firecrawl_api_key = getattr(settings, "firecrawl_api_key", "")
        self.explicit_order: Sequence[str] = getattr(settings, "web_search_providers", ())
        self._client = TavilyClient(api_key=self.api_key) if self.api_key else None
        self.provider_order = self._resolve_provider_order()
        providers_configured = list(self.explicit_order) or ["default"]
        has_keys = {
            "tavily": bool(self.api_key),
            "websearchapi": bool(self.websearch_api_key),
            "exa": bool(self.exa_api_key),
            "firecrawl": bool(self.firecrawl_api_key),
        }
        self.logger.info(
            "web_search.init providers=%s order=%s available=%s keys=%s",
            providers_configured,
            list(self.provider_order),
            self.available,
            has_keys,
        )

    @property
    def available(self) -> bool:
        force = str(getattr(settings, "web_search_force_available", "")).lower()
        if force in {"1", "true", "yes"}:
            return True
        return any(self._provider_available(provider) for provider in self.provider_order)

    async def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        if not query.strip():
            return []

        limit = self._resolve_limit(max_results)
        quota_hit = False
        last_error: Optional[Exception] = None

        for provider in self.provider_order:
            if not self._provider_available(provider):
                continue

            self.logger.info(
                "web_search.provider_start provider=%s query=%s limit=%s",
                provider,
                query.strip().replace("\n", " ")[:120],
                limit,
            )
            try:
                hits = await self._dispatch_provider(provider, query, limit)
            except WebSearchQuotaExceededError:
                quota_hit = True
                self.logger.warning(
                    "web_search.provider_quota",
                    extra={"provider": provider},
                )
                continue
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                self.logger.warning(
                    "web_search.provider_timeout",
                    extra={"provider": provider, "query": query[:120]},
                )
                last_error = exc
                continue
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning(
                    "web_search.provider_failed",
                    extra={"provider": provider, "error": str(exc)},
                )
                last_error = exc
                continue

            if hits:
                self.logger.info(
                    "web_search.provider_success provider=%s hits=%s",
                    provider,
                    len(hits),
                )
                return hits[:limit]

        if quota_hit:
            raise WebSearchQuotaExceededError("All configured web search providers exhausted quota.")
        if last_error:
            raise last_error
        return []

    async def _dispatch_provider(self, provider: str, query: str, limit: int) -> List[Dict[str, Any]]:
        if provider == self.PROVIDER_TAVILY:
            return await self._search_tavily(query, limit)
        if provider == self.PROVIDER_WEBSEARCHAPI:
            return await self._search_websearchapi(query, limit)
        if provider == self.PROVIDER_EXA:
            return await self._search_exa(query, limit)
        if provider == self.PROVIDER_FIRECRAWL:
            return await self._search_firecrawl(query, limit)
        return []

    async def _search_tavily(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not self._client:
            return []
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.search,
                    query,
                    max_results=limit,
                    include_images=False,
                    include_answer=False,
                    search_depth="advanced",
                ),
                timeout=self.timeout,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            self.logger.warning("web_search.timeout", extra={"query": query[:120]})
            raise exc
        except Exception as exc:  # pragma: no cover - network issues
            message = str(exc)
            lower = message.lower()
            if any(keyword in lower for keyword in ("quota", "limit", "usage", "429", "rate limit")):
                self.logger.warning("web_search.quota_exceeded", extra={"error": message})
                raise WebSearchQuotaExceededError(message) from exc
            self.logger.warning("web_search.error", extra={"error": message})
            raise

        hits = response.get("results", [])[:limit]
        now = datetime.now(timezone.utc).isoformat()
        return [
            self._normalize_hit(hit, idx, now, provider=self.PROVIDER_TAVILY)
            for idx, hit in enumerate(hits, start=1)
        ]

    async def _search_websearchapi(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not self.websearch_api_key:
            return []
        payload = {
            "query": query,
            "maxResults": limit,
            "includeContent": True,
            "contentLength": "medium",
            "includeAnswer": False,
            "safeSearch": True,
        }
        headers = {
            "Authorization": f"Bearer {self.websearch_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.websearchapi.ai/ai-search",
                json=payload,
                headers=headers,
            )
        response.raise_for_status()
        data = response.json()
        organic = data.get("organic") or []
        now = datetime.now(timezone.utc).isoformat()
        normalized: List[Dict[str, Any]] = []
        answer = (data.get("answer") or "").strip()
        if answer:
            normalized.append(self._build_answer_doc("WebSearchAPI.ai", answer, now))
        for idx, hit in enumerate(organic[:limit], start=1):
            mapped = {
                "title": hit.get("title"),
                "url": hit.get("url"),
                "content": hit.get("content") or hit.get("description"),
                "score": hit.get("score"),
                "published_date": hit.get("date") or hit.get("publishedDate"),
            }
            normalized.append(
                self._normalize_hit(
                    mapped,
                    idx,
                    now,
                    provider=self.PROVIDER_WEBSEARCHAPI,
                )
            )
        return normalized[:limit]

    async def _search_exa(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not self.exa_api_key:
            return []
        payload = {
            "query": query,
            "numResults": limit,
            "useAutoprompt": True,
            "type": "neural",
        }
        headers = {
            "x-api-key": self.exa_api_key,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post("https://api.exa.ai/search", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        now = datetime.now(timezone.utc).isoformat()
        normalized: List[Dict[str, Any]] = []
        for idx, hit in enumerate(results[:limit], start=1):
            mapped = {
                "title": hit.get("title"),
                "url": hit.get("url"),
                "content": hit.get("summary") or hit.get("highlights") or "",
                "score": hit.get("score"),
                "published_date": hit.get("publishedDate"),
            }
            normalized.append(
                self._normalize_hit(
                    mapped,
                    idx,
                    now,
                    provider=self.PROVIDER_EXA,
                )
            )
        return normalized

    async def _search_firecrawl(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not self.firecrawl_api_key:
            return []
        payload = {
            "query": query,
            "limit": limit,
            "pageOptions": {
                "limit": limit,
                "includeMarkdown": True,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.firecrawl_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post("https://api.firecrawl.dev/v0/search", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        entries = data.get("data") or []
        now = datetime.now(timezone.utc).isoformat()
        normalized: List[Dict[str, Any]] = []
        if isinstance(entries, dict):
            buckets = []
            for bucket in entries.values():
                if isinstance(bucket, list):
                    buckets.extend(bucket)
            entries = buckets
        for idx, hit in enumerate(entries[:limit], start=1):
            metadata = hit.get("metadata") or {}
            mapped = {
                "title": metadata.get("title") or metadata.get("og:title"),
                "url": metadata.get("url") or metadata.get("sourceURL"),
                "content": hit.get("markdown") or hit.get("content") or metadata.get("description"),
                "score": metadata.get("score"),
                "published_date": metadata.get("published_time"),
            }
            normalized.append(
                self._normalize_hit(
                    mapped,
                    idx,
                    now,
                    provider=self.PROVIDER_FIRECRAWL,
                )
            )
        return normalized

    def _freshness_bonus(self, published: Optional[str]) -> float:
        if not published:
            return 0.0
        try:
            year = int(published[:4])
        except (ValueError, TypeError):
            return 0.0
        current_year = datetime.utcnow().year
        delta = current_year - year
        if delta < 0:
            return 0.0
        if delta == 0:
            return 0.15
        if delta == 1:
            return 0.08
        if delta == 2:
            return 0.04
        return 0.0

    def _resolve_provider_order(self) -> List[str]:
        base_order: List[str] = []
        for provider in self.explicit_order:
            name = provider.strip().lower()
            if name in self.KNOWN_PROVIDERS and name not in base_order:
                base_order.append(name)
        if not base_order:
            base_order = [
                self.PROVIDER_TAVILY,
                self.PROVIDER_WEBSEARCHAPI,
                self.PROVIDER_EXA,
                self.PROVIDER_FIRECRAWL,
            ]
        return [provider for provider in base_order if self._provider_available(provider)]

    def _provider_available(self, provider: str) -> bool:
        if provider == self.PROVIDER_TAVILY:
            return self._client is not None
        if provider == self.PROVIDER_WEBSEARCHAPI:
            return bool(self.websearch_api_key)
        if provider == self.PROVIDER_EXA:
            return bool(self.exa_api_key)
        if provider == self.PROVIDER_FIRECRAWL:
            return bool(self.firecrawl_api_key)
        return False

    def _resolve_limit(self, value: Optional[int]) -> int:
        if not value:
            return self.max_results
        return max(1, min(value, self.max_results))

    def _normalize_hit(
        self,
        hit: Dict[str, Any],
        position: int,
        retrieved_at: str,
        *,
        provider: str = "tavily",
    ) -> Dict[str, Any]:
        snippet = (hit.get("content") or hit.get("text") or hit.get("description") or "").strip()
        url = (hit.get("url") or "").strip()
        title = (hit.get("title") or url or "WebResult").strip()
        published = (hit.get("published_date") or "").strip() or None

        freshness_bonus = self._freshness_bonus(published)
        coverage_bonus = 0.1 if len(snippet) >= 180 else 0.0
        base_score = 0.75 - (position - 1) * 0.06
        confidence_floor = getattr(settings, "web_search_confidence_floor", 0.05)
        score = max(confidence_floor, min(0.99, base_score + freshness_bonus + coverage_bonus))
        if score >= 0.75:
            confidence = "high"
        elif score >= 0.55:
            confidence = "medium"
        else:
            confidence = "low"

        metadata = {
            "source": title,
            "title": title,
            "page": None,
            "source_type": "web",
            "url": url or None,
            "score": round(score, 4),
            "provider": provider,
            "published_at": published,
            "tavily_score": hit.get("score"),
            "retrieved_at": retrieved_at,
            "position": position,
            "confidence": confidence,
        }

        if snippet:
            metadata["text"] = snippet

        return {
            "text": snippet or title,
            "title": title,
            "url": url or None,
            "source": title,
            "score": score,
            "snippet": snippet or title,
            "published_date": published,
            "retrieved_at": retrieved_at,
            "source_type": "web",
            "confidence": confidence,
            "metadata": metadata,
        }

    def _build_answer_doc(self, provider_name: str, answer: str, retrieved_at: str) -> Dict[str, Any]:
        answer = answer.strip()
        metadata = {
            "source": f"{provider_name} Answer",
            "title": f"{provider_name} Answer",
            "page": None,
            "source_type": "web",
            "url": None,
            "score": 0.95,
            "provider": provider_name.lower(),
            "published_at": None,
            "tavily_score": None,
            "retrieved_at": retrieved_at,
            "position": 0,
            "confidence": "high",
        }
        return {
            "text": answer,
            "title": metadata["title"],
            "url": None,
            "source": metadata["title"],
            "score": 0.95,
            "snippet": answer,
            "published_date": None,
            "retrieved_at": retrieved_at,
            "source_type": "web",
            "confidence": "high",
            "metadata": metadata,
        }
