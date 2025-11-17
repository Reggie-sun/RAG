from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple
from enum import Enum
from contextlib import asynccontextmanager, suppress

import asyncio
import os
import random
import re
from difflib import SequenceMatcher

import httpx

from ollama import AsyncClient

try:
    from ..config import settings
    from ..utils.logger import get_logger
except ImportError:  # pragma: no cover - support direct `services.*` imports
    from backend.config import settings  # type: ignore
    from backend.utils.logger import get_logger  # type: ignore
from .prompt_utils import (
    build_doc_prompt,
    build_general_prompt,
    is_doc_mode,
    select_top_documents,
)
from .intent_classifier import has_doc_hint
from .enhanced_intent_classifier import (
    enhanced_classifier,
    IntentAnalysisResult,
    QuestionType,
    AnsweringMode,
    EnhancedIntentClassifier,
)
from .hybrid_retriever import HybridRetriever
from .web_search_service import WebSearchService, WebSearchQuotaExceededError
from .doc_context_store import doc_context_store


class WebMode(str, Enum):
    OFF = "off"
    UPGRADE = "upgrade"
    ONLY = "only"


STOPWORDS_EN: Set[str] = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "be",
    "as",
    "by",
    "from",
    "at",
    "that",
    "this",
    "these",
    "those",
}
STOPWORDS_ZH: Set[str] = {"的", "了", "和", "及", "与", "或", "以及"}


class RAGService:
    OFF_TOPIC_SCORE_THRESHOLD = 0.60
    OFF_TOPIC_OVERLAP_THRESHOLD = 0.40

    MULTI_TOPIC_MAX_SNIPPETS = 3
    MULTI_TOPIC_MAX_TOPICS = 3
    MULTI_TOPIC_MAX_CITATIONS = 3

    FOLLOWUP_PRONOUN_PATTERN = re.compile(
        r"^(这[本文篇份个]|该[文件文档材料篇]?|上述|前述|文中|本篇|本文件)$",
        re.IGNORECASE,
    )
    FOLLOWUP_GENERIC_PATTERN = re.compile(
        r"(总结|概括|要点|概览|概述|提炼|整理)$",
        re.IGNORECASE,
    )
    LEADING_SYMBOL_PATTERN = re.compile(r"^[`'\"“”‘’、，,。．·…:：;；•○●◦◯▪▫☆★◇◆¤※\-\s]+")
    CONTROL_CHAR_PREFIX = re.compile(r"^[\ufeff\u200b\u200c\u200d\u202a-\u202e]+")
    ISOLATED_CJK_PREFIX = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff](?=[\s\u3000]+)")

    OLLAMA_CHAT_MAX_ATTEMPTS = 3
    OLLAMA_CONNECT_TIMEOUT_SECONDS = 8.0
    OLLAMA_RETRY_BACKOFF_SECONDS = 0.5
    OLLAMA_MAX_CONNECTIONS = 10
    OLLAMA_MAX_KEEPALIVE_CONNECTIONS = 5

    def __init__(
        self,
        retriever: HybridRetriever,
        web_search: Optional[WebSearchService] = None,
        intent_classifier: Optional[EnhancedIntentClassifier] = None,
    ) -> None:
        self.retriever = retriever
        self.debug_router = os.getenv("DEBUG_ROUTER", "false").lower() in {"1", "true", "yes"}
        self.logger = get_logger(__name__)
        self.web_search = web_search or WebSearchService()
        self.intent_classifier = intent_classifier or enhanced_classifier

    @asynccontextmanager
    async def _ollama_client(self) -> AsyncGenerator[AsyncClient, None]:
        timeout = httpx.Timeout(
            timeout=settings.ollama_timeout,
            connect=min(self.OLLAMA_CONNECT_TIMEOUT_SECONDS, settings.ollama_timeout),
        )
        limits = httpx.Limits(
            max_connections=self.OLLAMA_MAX_CONNECTIONS,
            max_keepalive_connections=self.OLLAMA_MAX_KEEPALIVE_CONNECTIONS,
            keepalive_expiry=30.0,
        )
        client = AsyncClient(
            host=settings.ollama_base_url,
            proxy=None,
            timeout=timeout,
            limits=limits,
        )
        try:
            yield client
        finally:
            with suppress(Exception):
                await self._close_async_client(client)

    async def _close_async_client(self, client: AsyncClient) -> None:
        close = getattr(client, "aclose", None)
        if callable(close):
            await close()
            return
        inner = getattr(client, "_client", None)
        if inner is not None:
            await inner.aclose()

    def _parse_web_mode(self, web_mode: Optional[str]) -> Optional[WebMode]:
        if not web_mode:
            return None
        try:
            return WebMode(web_mode.lower())
        except ValueError:
            self.logger.info(
                "web_search.mode_invalid",
                extra={"requested": web_mode},
            )
            return None

    def _resolve_web_mode(
        self,
        requested_mode: Optional[WebMode],
        allow_web: Optional[bool],
        doc_only_mode: bool,
    ) -> WebMode:
        if requested_mode:
            return requested_mode
        if not allow_web:
            return WebMode.OFF
        # 默认采用升级模式：先文档，必要时联网补充
        return WebMode.UPGRADE

    async def answer(
        self,
        query: str,
        top_k: int,
        alpha: Optional[float] = None,
        use_rerank: Optional[bool] = None,
        filters: Optional[Dict[str, Any]] = None,
        history: Optional[str] = None,
        allow_web: Optional[bool] = None,
        web_mode: Optional[str] = None,
        doc_only: Optional[bool] = None,
        session_id: Optional[str] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 增强意图分析
        intent_result = await self.intent_classifier.analyze_intent(query)
        has_feedback = bool(feedback and feedback.strip())

        doc_only_mode = bool(doc_only)
        cached_docs = doc_context_store.get(session_id)
        use_cached_docs = self._should_use_cached_doc_query(query, cached_docs)
        module_config = self._module_config(doc_only_mode, allow_web)
        stacked_mode = module_config.get("stacked", False)

        web_client_ready = bool(self.web_search and self.web_search.available)
        force_web_answer = bool(allow_web and not doc_only_mode)

        # 根据意图分析结果调整参数
        if (
            intent_result.answering_mode == AnsweringMode.GENERAL_ONLY
            and not doc_only_mode
            and not force_web_answer
        ):
            # 常识问题，直接返回常识回答
            return await self._answer_general_knowledge(
                query,
                history,
                intent_result,
                feedback=feedback,
            )

        requested_mode = self._parse_web_mode(web_mode)

        resolved_mode = self._resolve_web_mode(requested_mode, allow_web, doc_only_mode)
        diagnostics_base = {
            "allow_web": bool(allow_web),
            "requested_mode": web_mode,
            "resolved_mode": resolved_mode.value if resolved_mode else None,
            "web_available": web_client_ready,
            "providers": getattr(self.web_search, "provider_order", []) if self.web_search else [],
            "module_config": module_config,
        }

        # 确定是否需要联网搜索
        needs_web_search = bool(
            intent_result.requires_web_search
            or resolved_mode == WebMode.ONLY
            or bool(allow_web)
        )
        diagnostics_base["needs_web_search"] = needs_web_search
        diagnostics_base["stacked_mode_active"] = module_config.get("stacked", False)

        sub_queries, truncated, original_topic_count = await self._intelligent_decompose_query(query)
        multi_topic = len(sub_queries) > 1
        active_topics = sub_queries if multi_topic else []

        retrieval = None
        retrievals: List[Tuple[str, Any]] = []
        diagnostics: Dict[str, Any] = {}
        web_docs_single: List[Dict[str, Any]] = []
        topic_web_docs: Dict[str, List[Dict[str, Any]]] = {}
        web_available = web_client_ready
        use_web = resolved_mode != WebMode.OFF and web_available
        web_only = resolved_mode == WebMode.ONLY
        should_attempt_web = use_web and (web_only or needs_web_search)
        quota_state = {"web_quota_hit": False}
        if resolved_mode != WebMode.OFF and not web_available:
            self.logger.info(
                "web_search.disabled",
                extra={"reason": "client_unavailable", "requested_mode": resolved_mode.value},
            )

        if multi_topic:
            # 动态TopK：多主题时每个子查询使用较小的top_k
            adaptive_top_k = max(3, min(top_k // len(sub_queries), 8))

            # 并行执行多主题检索
            retrievals, topic_web_docs = await self._parallel_multi_topic_retrieval(
                sub_queries,
                adaptive_top_k,
                alpha,
                use_rerank,
                filters,
                use_web,
                should_attempt_web,
                quota_state,
            )

            diagnostics = {
                "topics": {sub_query: sub_ret.diagnostics for sub_query, sub_ret in retrievals}
            }
            diagnostics["intent_analysis"] = self._intent_payload(intent_result)
            diagnostics["doc_only_mode"] = doc_only_mode
            web_hits_total = sum(len(topic_web_docs.get(sub_query, [])) for sub_query in sub_queries)
            diagnostics["web_search_used"] = web_hits_total > 0
            diagnostics["web_hits"] = web_hits_total
            topic_docs = self._prepare_multi_topic_docs(retrievals)
            diagnostics.update(diagnostics_base)

            if web_only and use_web and web_hits_total == 0:
                diagnostics["web_only_no_hits"] = True
                meta = self._build_response_meta(
                    intent=intent_result,
                    strategy="web_only",
                    multi_topic=True,
                    topics=sub_queries,
                    web_used=False,
                    doc_sources=0,
                    web_sources=0,
                    truncated=truncated,
                    modules=module_config,
                    feedback=feedback,
                )
                return {
                    "answer": "未检索到可靠的联网来源。",
                    "mode": "general",
                    "citations": [],
                    "suggestions": self._general_suggestions(),
                    "sources": [],
                    "diagnostics": diagnostics,
                    "meta": meta,
                    "multi_topics": active_topics,
                }

            if web_only and use_web and web_hits_total:
                web_topics = {sub_query: topic_web_docs.get(sub_query, []) for sub_query in sub_queries}
                answer, citations = await self._compose_multi_topic_answer(
                    sub_queries,
                    original_topic_count,
                    web_topics,
                    history,
                    truncated,
                    feedback=feedback,
                )
                meta = self._build_response_meta(
                    intent=intent_result,
                    strategy="web_only",
                    multi_topic=True,
                    topics=sub_queries,
                    web_used=True,
                    doc_sources=0,
                    web_sources=web_hits_total,
                    truncated=truncated,
                    modules=module_config,
                    feedback=feedback,
                )
                suggestions = self._general_suggestions()
                return {
                    "answer": answer,
                    "mode": "doc" if citations else "general",
                    "citations": citations,
                    "suggestions": suggestions,
                    "sources": citations,
                    "diagnostics": diagnostics,
                    "meta": meta,
                    "multi_topics": active_topics,
                }

            if topic_docs:
                answer, citations = await self._compose_multi_topic_answer(
                    sub_queries,
                    original_topic_count,
                    topic_docs,
                    history,
                    truncated,
                    feedback=feedback,
                    topic_web_docs=topic_web_docs if use_web else None,
                )
                if not citations:
                    citations = self._build_citations([doc for docs in topic_docs.values() for doc in docs])

                if self.debug_router:
                    self.logger.info(
                        "route.debug",
                        extra={
                            "intent": "question",
                            "topics": sub_queries,
                            "doc_hits": sum(len(docs) for docs in topic_docs.values()),
                            "diagnostics": diagnostics,
                        },
                    )
                doc_payload = [doc for docs in topic_docs.values() for doc in docs]
                self._update_doc_context(session_id, doc_payload)
                suggestions = self._general_suggestions()
                meta = self._build_response_meta(
                    intent=intent_result,
                    strategy="multi_topic",
                    multi_topic=True,
                    topics=sub_queries,
                    web_used=web_hits_total > 0,
                    doc_sources=len(doc_payload),
                    web_sources=web_hits_total,
                    truncated=truncated,
                    modules=module_config,
                    feedback=feedback,
                )
                return {
                    "answer": answer,
                    "mode": "doc" if citations else "general",
                    "citations": citations,
                    "suggestions": suggestions,
                    "sources": citations,
                    "diagnostics": diagnostics,
                    "meta": meta,
                    "multi_topics": active_topics,
                }
        else:
            retrieval = await self.retriever.retrieve(
                query,
                top_k,
                alpha=alpha,
                use_rerank=use_rerank,
                filters=filters,
            )
            trigger_web = (
                use_web
                and retrieval is not None
                and (web_only or needs_web_search or not retrieval.results)
            )
            if trigger_web:
                web_context = cached_docs if cached_docs else retrieval.results
                try:
                    web_docs_single = await self._web_search(
                        query,
                        settings.doc_answer_max_snippets,
                        context_docs=web_context,
                    ) or []
                except WebSearchQuotaExceededError:
                    quota_state["web_quota_hit"] = True
                    diagnostics["web_error"] = "quota_exceeded"
                    web_docs_single = []
                if web_docs_single:
                    retrieval.diagnostics["web_hits"] = len(web_docs_single)
                else:
                    retrieval.diagnostics["web_error"] = "no_results"
            retrievals.append((query, retrieval))
        diagnostics = dict(retrieval.diagnostics or {})
        diagnostics.update(diagnostics_base)
        diagnostics["intent_analysis"] = self._intent_payload(intent_result)
        diagnostics["web_search_used"] = bool(web_docs_single)
        diagnostics["web_hits"] = len(web_docs_single)
        diagnostics["doc_only_mode"] = doc_only_mode
        if use_cached_docs and cached_docs:
            diagnostics["doc_context_cached"] = True

        if web_only and use_web:
            if not web_docs_single:
                web_context = cached_docs if cached_docs else retrieval.results
                try:
                    web_docs_single = await self._web_search(
                        query,
                        settings.doc_answer_max_snippets,
                        context_docs=web_context,
                    ) or []
                except WebSearchQuotaExceededError:
                    quota_state["web_quota_hit"] = True
                    diagnostics["web_error"] = "quota_exceeded"
                    web_docs_single = []
                if not web_docs_single and "web_error" not in diagnostics:
                    diagnostics["web_error"] = "no_results"
                diagnostics["web_search_used"] = bool(web_docs_single)
                diagnostics["web_hits"] = len(web_docs_single)
            if web_docs_single:
                prepared = self._prepare_web_docs_for_structured_answer(web_docs_single)
                topic_heading = self._topic_with_web_suffix(self._extract_main_topic(query))
                structured_answer, web_citations = await self._generate_structured_answer(
                    query,
                    prepared,
                    topic_name=topic_heading,
                )
                meta = self._build_response_meta(
                    intent=intent_result,
                    strategy="web_only",
                    multi_topic=False,
                    topics=None,
                    web_used=True,
                    doc_sources=0,
                    web_sources=len(web_docs_single),
                    modules=module_config,
                    feedback=feedback,
                )
                return {
                    "answer": structured_answer,
                    "mode": "doc" if web_citations else "general",
                    "citations": web_citations,
                    "suggestions": self._general_suggestions(),
                    "sources": web_citations,
                    "diagnostics": diagnostics,
                    "meta": meta,
                    "multi_topics": active_topics,
                }

        # fallback to单主题路径 - 使用结构化答案
        retrieval = retrieval or retrievals[0][1]
        candidate_pool_k = max(settings.doc_answer_max_snippets * 6, settings.doc_answer_max_snippets + 4)
        candidates, top_score = select_top_documents(
            retrieval.results,
            k=candidate_pool_k,
        )
        top_docs = self._diversify_by_source(
            candidates,
            k=settings.doc_answer_max_snippets,
            max_per_source=2,
            min_unique_sources=2,
        )
        top_docs = self._ensure_multi_source_minimum(candidates, top_docs, need_sources=2)
        if top_docs:
            top_primary_score = self._document_score(top_docs[0])
            score_floor = max(settings.doc_answer_threshold - 0.05, top_primary_score * 0.6)
            filtered_docs: List[Dict[str, Any]] = []
            for idx, item in enumerate(top_docs):
                if idx == 0:
                    filtered_docs.append(item)
                    continue
                if self._document_score(item) >= score_floor:
                    filtered_docs.append(item)
            top_docs = filtered_docs
        top_docs = top_docs[: settings.doc_answer_max_snippets]
        if not top_docs and use_cached_docs and cached_docs:
            top_docs = cached_docs[: settings.doc_answer_max_snippets]
            diagnostics["doc_context_hit"] = True
        if web_only and not top_docs and web_docs_single:
            prepared = self._prepare_web_docs_for_structured_answer(web_docs_single)
            topic_heading = self._topic_with_web_suffix(self._extract_main_topic(query))
            structured_answer, web_citations = await self._generate_structured_answer(
                query,
                prepared,
                topic_name=topic_heading,
            )
            meta = self._build_response_meta(
                intent=intent_result,
                strategy="web_only",
                multi_topic=False,
                topics=None,
                web_used=bool(web_docs_single),
                doc_sources=0,
                web_sources=len(web_docs_single),
                modules=module_config,
                feedback=feedback,
            )
            return {
                "answer": structured_answer,
                "mode": "doc" if web_citations else "general",
                "citations": web_citations,
                "suggestions": self._general_suggestions(),
                "sources": web_citations,
                "diagnostics": diagnostics,
                "meta": meta,
                "multi_topics": active_topics,
            }
        if not top_docs:
            if doc_only_mode and not quota_state["web_quota_hit"]:
                return self._doc_only_no_hits_response(
                    query,
                    retrieval,
                    diagnostics,
                    web_docs=web_docs_single if stacked_mode else None,
                    allow_web=stacked_mode,
                )
            return await self.answer_general(
                query,
                history,
                sources=retrieval.results,
                diagnostics=retrieval.diagnostics,
                intent_result=intent_result,
                feedback=feedback,
            )

        doc_docs = []
        for item in top_docs:
            metadata = item.get("metadata", {}) or {}
            if str(metadata.get("source_type", "")).lower() != "web":
                doc_docs.append(item)

        web_docs: List[Dict[str, Any]] = web_docs_single if use_web else []
        if doc_only_mode and not stacked_mode:
            web_docs = []

        primary_docs = doc_docs if doc_docs else top_docs
        combined_docs = primary_docs + (web_docs if use_web else [])
        topic_override = None
        if use_web and web_docs and not doc_docs:
            topic_override = f"{self._extract_main_topic(query)}（联网）"
        structured_answer, structured_citations = await self._generate_structured_answer(
            query,
            combined_docs,
            topic_name=topic_override,
        )

        if doc_docs and structured_answer and not has_feedback:
            combined_citations = list(structured_citations) or self._build_citations(combined_docs)
            if combined_citations:
                suggestions = self._general_suggestions()
                meta = self._build_response_meta(
                    intent=intent_result,
                    strategy="document",
                    multi_topic=False,
                    topics=None,
                    web_used=bool(web_docs),
                    doc_sources=len(doc_docs),
                    web_sources=len(web_docs),
                    modules=module_config,
                    feedback=feedback,
                )
                self._update_doc_context(session_id, doc_docs)
                return {
                    "answer": structured_answer,
                    "mode": "doc",
                    "citations": combined_citations,
                    "suggestions": suggestions,
                    "sources": combined_citations,
                    "diagnostics": diagnostics,
                    "meta": meta,
                    "multi_topics": active_topics,
                }

        doc_hint = has_doc_hint(query)
        overlap = self._token_overlap_ratio(query, top_docs)
        score_threshold = max(self.OFF_TOPIC_SCORE_THRESHOLD, settings.doc_answer_threshold)
        if not doc_hint and (
            top_score < score_threshold or overlap < self.OFF_TOPIC_OVERLAP_THRESHOLD
        ):
            if doc_only_mode and not quota_state["web_quota_hit"]:
                return self._doc_only_no_hits_response(
                    query,
                    retrieval,
                    diagnostics,
                    web_docs=web_docs_single if stacked_mode else None,
                    allow_web=stacked_mode,
                )
            return await self.answer_general(
                query,
                history,
                sources=retrieval.results,
                diagnostics=retrieval.diagnostics,
                intent_result=intent_result,
                feedback=feedback,
            )

        mode = "doc" if top_docs and (doc_hint or is_doc_mode(top_score)) else "general"
        prompt_core = self._build_single_topic_prompt(query, top_docs, mode, feedback=feedback)
        prompt = self._compose_prompt(history, prompt_core, mode)
        messages = self._build_messages_for_mode(prompt, mode)
        answer = await self._chat(messages, query=query, mode=mode)
        if self.debug_router:
            self.logger.info(
                "route.debug",
                extra={
                    "intent": "question",
                    "doc_hits": len(top_docs),
                    "top_score": float(top_score or 0.0),
                    "overlap": float(overlap or 0.0),
                    "thresholds": {
                        "doc": settings.doc_answer_threshold,
                        "overlap": self.OFF_TOPIC_OVERLAP_THRESHOLD,
                    },
                },
            )
        if mode == "general" and "[非文档知识]" not in answer:
            answer = "[非文档知识]\n" + answer
        citations = self._build_citations(top_docs) if mode == "doc" else []
        suggestions = self._general_suggestions() if mode != "doc" else []
        meta = self._build_response_meta(
            intent=intent_result,
            strategy="document" if mode == "doc" else "general",
            multi_topic=False,
            topics=None,
            web_used=bool(web_docs),
            doc_sources=len(top_docs) if mode == "doc" else 0,
            web_sources=len(web_docs),
            modules=module_config,
            feedback=feedback,
        )
        if mode == "doc":
            self._update_doc_context(session_id, top_docs)
        return {
            "answer": answer,
            "mode": mode,
            "citations": citations,
            "suggestions": suggestions,
            "sources": citations,
            "diagnostics": diagnostics,
            "meta": meta,
            "multi_topics": active_topics,
        }

    async def answer_general(
        self,
        query: str,
        history: Optional[str] = None,
        *,
        sources: Optional[List[Dict[str, Any]]] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
        intent_result: Optional[IntentAnalysisResult] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        intent = intent_result or await self.intent_classifier.analyze_intent(query)
        prompt_core = build_general_prompt(query, feedback=feedback)
        prompt = self._compose_prompt(history, prompt_core, "general")
        messages = self._build_messages_for_mode(prompt, "general")
        answer = await self._chat(messages, query=query, mode="general")
        if "[非文档知识]" not in answer:
            answer = "[非文档知识]\n" + answer
        source_payload = self._build_citations(sources or []) if sources else []
        meta = self._build_response_meta(
            intent=intent,
            strategy="general",
            multi_topic=False,
            topics=intent.raw_topics,
            web_used=False,
            doc_sources=0,
            web_sources=0,
            feedback=feedback,
        )
        diag_payload = dict(diagnostics or {})
        diag_payload["intent_analysis"] = self._intent_payload(intent)
        return {
            "answer": answer,
            "mode": "general",
            "citations": [],
            "suggestions": self._general_suggestions(),
            "sources": source_payload,
            "diagnostics": diag_payload,
            "meta": meta,
            "multi_topics": intent.raw_topics,
        }

    async def stream(
        self,
        query: str,
        top_k: int,
        alpha: Optional[float] = None,
        use_rerank: Optional[bool] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], AsyncGenerator[str, None], Dict[str, Any]]:
        retrieval = await self.retriever.retrieve(
            query, top_k, alpha=alpha, use_rerank=use_rerank, filters=filters
        )
        context = self._build_context(retrieval.results)

        async def generator() -> AsyncGenerator[str, None]:
            logger = self.logger
            async with self._ollama_client() as client:
                start_task = asyncio.create_task(
                    client.chat(
                        model=settings.ollama_model,
                        messages=self._build_stream_messages(query, context),
                        options=self._ollama_options(),
                        stream=True,
                    )
                )
                try:
                    stream = await asyncio.wait_for(
                        start_task, timeout=settings.ollama_timeout
                    )
                except asyncio.TimeoutError:
                    start_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await start_task
                    logger.warning(
                        "ollama.stream.timeout",
                        extra={"stage": "startup", "query": query},
                    )
                    return
                except asyncio.CancelledError:
                    start_task.cancel()
                    with suppress(Exception):
                        await start_task
                    raise
                except Exception as exc:
                    start_task.cancel()
                    with suppress(Exception):
                        await start_task
                    logger.warning(
                        "ollama.stream.error",
                        extra={"stage": "startup", "query": query, "exc": type(exc).__name__},
                    )
                    return

                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            stream.__anext__(), timeout=settings.ollama_timeout
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "ollama.stream.timeout",
                            extra={"stage": "chunk", "query": query},
                        )
                        break
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "ollama.stream.error",
                            extra={"stage": "chunk", "query": query, "exc": type(exc).__name__},
                        )
                        break

                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content

        return retrieval.results, generator(), retrieval.diagnostics

    def _diversify_by_source(
        self,
        results: List[Dict[str, Any]],
        k: int,
        *,
        max_per_source: int = 2,
        min_unique_sources: int = 2,
    ) -> List[Dict[str, Any]]:
        if not results:
            return []

        def _src(item: Dict[str, Any]) -> str:
            metadata = item.get("metadata", {}) or {}
            return metadata.get("source") or item.get("source") or "unknown"

        picked: List[Dict[str, Any]] = []
        per_source: Dict[str, int] = {}
        seen_sources = set()

        for item in results:
            source = _src(item)
            count = per_source.get(source, 0)
            if count >= max_per_source:
                continue
            picked.append(item)
            per_source[source] = count + 1
            seen_sources.add(source)
            if len(picked) >= k and len(seen_sources) >= min_unique_sources:
                break

        if len(picked) < k or len(seen_sources) < min_unique_sources:
            used = {id(x) for x in picked}
            for item in results:
                if id(item) in used:
                    continue
                source = _src(item)
                count = per_source.get(source, 0)
                if count >= max_per_source:
                    continue
                picked.append(item)
                per_source[source] = count + 1
                seen_sources.add(source)
                if len(picked) >= k:
                    break

        if len(picked) < k and len(seen_sources) >= min_unique_sources:
            used = {id(x) for x in picked}
            for item in results:
                if id(item) in used:
                    continue
                source = _src(item)
                count = per_source.get(source, 0)
                if count >= max_per_source + 1:
                    continue
                picked.append(item)
                per_source[source] = count + 1
                seen_sources.add(source)
                if len(picked) >= k:
                    break

        return picked[:k]

    def _ensure_multi_source_minimum(
        self,
        results: List[Dict[str, Any]],
        picked: List[Dict[str, Any]],
        *,
        need_sources: int = 2,
    ) -> List[Dict[str, Any]]:
        if not picked:
            return picked

        picked_sources = {self._doc_source(item) for item in picked}
        if len(picked_sources) >= need_sources:
            return picked

        if not results:
            return picked

        top_score = self._document_score(picked[0])
        score_floor = max(settings.doc_answer_threshold - 0.05, top_score * 0.6)

        used = {id(x) for x in picked}
        for item in results:
            if id(item) in used:
                continue
            if self._document_score(item) < score_floor:
                continue
            source = self._doc_source(item)
            if source in picked_sources:
                continue
            picked.append(item)
            picked_sources.add(source)
            if len(picked_sources) >= need_sources:
                break

        return picked

    def _doc_source(self, item: Dict[str, Any]) -> str:
        metadata = item.get("metadata", {}) or {}
        return metadata.get("source") or item.get("source") or "unknown"

    def _document_score(self, item: Dict[str, Any]) -> float:
        metadata = item.get("metadata", {}) or {}
        raw = item.get("score", metadata.get("score", 0.0))
        try:
            return float(raw or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _build_single_topic_prompt(
        self,
        query: str,
        docs: List[Dict[str, Any]],
        mode: str,
        *,
        feedback: Optional[str] = None,
    ) -> str:
        if mode != "doc" or not docs:
            return build_general_prompt(query, feedback=feedback)

        return build_doc_prompt(query, docs, feedback=feedback)

    def _format_doc_chunk(self, idx: int, doc: Dict[str, Any]) -> str:
        metadata = doc.get("metadata", {}) or {}
        title = metadata.get("source") or doc.get("source") or "Unknown"
        page = metadata.get("page")
        header = f"[{idx}] 《{title}》"
        if page not in (None, ""):
            header += f" P.{page}"
        text = str(doc.get("text") or metadata.get("text") or "")[:800]
        return f"{header}\n{text}"

    def _build_context(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return ""
        parts = []
        for item in results:
            metadata = item.get("metadata", {})
            parts.append(
                "\n".join(
                    [
                        f"Chunk ID: {metadata.get('chunk_id', item.get('chunk_id'))}",
                        f"Source: {metadata.get('source', item.get('source', 'unknown'))}",
                        f"Page: {metadata.get('page', 0)}",
                        f"Score: {item.get('score', 0.0):.4f}",
                        "Text:",
                        item.get("text", ""),
                    ]
                )
            )
        return "\n\n---\n\n".join(parts)

    async def _web_search(
        self,
        query: str,
        max_results: int,
        *,
        context_docs: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.web_search or not self.web_search.available:
            return []
        keywords = self._extract_doc_keywords(context_docs or [])
        search_query = self._build_contextual_web_query(query, keywords)
        try:
            raw_results = await self.web_search.search(search_query, max_results=max_results) or []
            if not raw_results:
                self.logger.info("web_search.no_results", extra={"query": search_query[:120]})
        except WebSearchQuotaExceededError:
            raise
        except Exception as exc:  # pragma: no cover - network errors
            self.logger.warning(
                "web_search.failed",
                extra={"error": str(exc)},
            )
            return []
        filtered_hits = self._filter_web_hits(raw_results, keywords, query)
        if not filtered_hits and raw_results:
            self.logger.info(
                "web_search.filtered_all",
                extra={"query": search_query[:120], "keywords": keywords, "raw_hits": len(raw_results)},
            )
        normalized: List[Dict[str, Any]] = []
        for hit in filtered_hits:
            metadata = dict(hit.get("metadata") or {})
            metadata.setdefault("source_type", "web")
            metadata.setdefault(
                "source",
                metadata.get("source") or hit.get("source") or hit.get("title") or "WebResult",
            )
            metadata.setdefault("title", hit.get("title") or metadata.get("source"))
            url = hit.get("url") or metadata.get("url")
            if url:
                metadata["url"] = url
            published = metadata.get("published_date") or metadata.get("published_at")
            if published:
                metadata["published_at"] = published
            text = hit.get("text") or hit.get("content") or metadata.get("text") or ""
            doc = {
                "title": hit.get("title") or metadata.get("title"),
                "url": metadata.get("url"),
                "text": text,
                "content": text,
                "source": metadata.get("source"),
                "score": float(hit.get("score") or metadata.get("score") or 0.0),
                "metadata": metadata,
            }
            normalized.append(doc)
            if max_results and len(normalized) >= max_results:
                break
        return normalized

    def _build_web_highlights(
        self,
        docs: List[Dict[str, Any]],
        heading: str = "附加联网资讯",
    ) -> Tuple[str, List[Dict[str, Any]]]:
        if not docs:
            return "", []

        lines: List[str] = []
        seen_keys = set()
        for doc in docs:
            source, page, text, _ = self._doc_fields(doc)
            metadata = (doc.get("metadata") or {}) if isinstance(doc, dict) else {}
            snippet = (text or metadata.get("description") or "").strip()
            snippet = self._clean_leading_symbols(snippet)
            snippet = self._normalize_whitespace(snippet)
            if not snippet and metadata.get("title"):
                snippet = f"{metadata['title']}（暂无摘要，点击链接查看详情）"
            if not snippet and metadata.get("url"):
                snippet = "该来源未提供摘要，请访问链接查看原文。"
            if not snippet:
                continue

            title = metadata.get("title") or source or "外部来源"
            url = metadata.get("url")
            link = f"[{title}]({url})" if url else title

            dedup_key = (url or title, snippet[:120])
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            digest = snippet if len(snippet) <= 220 else snippet[:220].rstrip() + "..."
            lines.append(f"- {link}：{digest}{self._format_citation(doc)}")
            if len(lines) >= 3:
                break

        section = ""
        if lines:
            section = f"#### {heading}\n" + "\n".join(lines)
        citations = self._build_citations(docs)
        return section, citations

    def _doc_only_no_hits_response(
        self,
        query: str,
        retrieval: Any,
        diagnostics: Dict[str, Any],
        web_docs: Optional[List[Dict[str, Any]]] = None,
        quota_hit: bool = False,
        allow_web: bool = False,
    ) -> Dict[str, Any]:
        """在仅文档模式下未检索到结果时的提示回复。"""
        base = (
            "**未检索到相关文档内容**\n"
            f"在当前知识库中没有找到与“{query}”匹配的段落。"
            "\n- 请确认相关材料已经上传并完成索引\n- 尝试使用更具体的关键词或缩小问题范围"
        )
        sections = [base]
        citations: List[Dict[str, Any]] = []
        if allow_web and web_docs:
            web_section, web_citations = self._build_web_highlights(web_docs, "联网检索补充")
            if web_section:
                sections.append(web_section)
            if web_citations:
                citations.extend(web_citations)
        if quota_hit:
            sections.append("> 联网搜索配额已用尽，暂时无法获取最新的公开信息。")
        payload = dict(diagnostics or {})
        payload["doc_only_no_hits"] = True
        suggestions = self._general_suggestions()
        sources = getattr(retrieval, "results", None) or []
        if citations and not sources:
            sources = citations
        return {
            "answer": "\n\n".join(section for section in sections if section).strip(),
            "mode": "guidance",
            "citations": citations,
            "suggestions": suggestions,
            "sources": sources,
            "diagnostics": payload,
        }

    def _update_doc_context(self, session_id: Optional[str], docs: List[Dict[str, Any]]) -> None:
        if not session_id or not docs:
            return
        doc_context_store.set(session_id, docs[: settings.doc_answer_max_snippets])

    def _should_use_cached_doc_query(self, query: str, cached_docs: List[Dict[str, Any]]) -> bool:
        if not cached_docs:
            return False
        text = (query or "").strip()
        if not text:
            return False
        lowered = text.lower()
        if not self.FOLLOWUP_PRONOUN_PATTERN.search(lowered):
            return False
        stripped = self.FOLLOWUP_GENERIC_PATTERN.sub("", lowered)
        stripped = re.sub(r"[\s，。,。!！?？：:；;（）()\-_\/]+", "", stripped)
        return len(stripped) < 4

    def _build_contextual_web_query(
        self,
        query: str,
        keywords: List[str],
    ) -> str:
        if not keywords:
            return query

        quoted = []
        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue
            if " " in keyword and not keyword.startswith("\""):
                quoted.append(f"\"{keyword}\"")
            else:
                quoted.append(keyword)
        context = " ".join(quoted[:4])
        combined = f"{context} {query}".strip()
        return combined[-512:] if len(combined) > 512 else combined

    def _extract_doc_keywords(self, docs: List[Dict[str, Any]]) -> List[str]:
        keywords: List[str] = []
        seen: set[str] = set()
        doc_entries: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        # 先尝试使用结构化元数据（标题、文档名等）提取关键词
        for doc in docs:
            metadata = (doc.get("metadata") or {}) if isinstance(doc, dict) else {}
            doc_entries.append((doc, metadata))
            candidates = [
                metadata.get("title"),
                metadata.get("source"),
                metadata.get("file_name"),
                metadata.get("document"),
                doc.get("title") if isinstance(doc, dict) else None,
                doc.get("source") if isinstance(doc, dict) else None,
            ]
            for candidate in candidates:
                if not candidate:
                    continue
                clean = self._clean_leading_symbols(str(candidate).strip())
                if not clean or len(clean) < 3:
                    continue
                lowered = clean.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                keywords.append(clean)
                break
            if len(keywords) >= 4:
                break

        if len(keywords) >= 4:
            return keywords[:6]

        # 元数据不足时退回到文档片段内容，抽取关键句作为联网检索上下文
        for doc, metadata in doc_entries:
            text = ""
            if isinstance(doc, dict):
                text = str(doc.get("text") or doc.get("content") or "")
            if not text:
                text = str(metadata.get("text") or metadata.get("snippet") or "")
            snippet = self._clean_leading_symbols(text.strip())
            if not snippet:
                continue
            segments = re.split(r"[。！？!?\n]+", snippet)
            for segment in segments:
                candidate = segment.strip()
                if len(candidate) < 4:
                    continue
                trimmed = candidate[:80]
                lowered = trimmed.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                keywords.append(trimmed)
                break
            if len(keywords) >= 6:
                break

        return keywords[:6]

    def _filter_web_hits(
        self,
        hits: List[Dict[str, Any]],
        keywords: List[str],
        query: str,
    ) -> List[Dict[str, Any]]:
        if not hits:
            return hits

        lowered_keywords = [kw.lower() for kw in keywords if len(kw) >= 3]

        def _haystack(hit: Dict[str, Any]) -> str:
            metadata = hit.get("metadata") or {}
            return " ".join(
                [
                    str(hit.get("title") or ""),
                    str(hit.get("content") or ""),
                    str(hit.get("snippet") or ""),
                    str(metadata.get("description") or ""),
                ]
            ).lower()

        filtered: List[Dict[str, Any]] = []
        if lowered_keywords:
            for hit in hits:
                hay = _haystack(hit)
                if any(kw in hay for kw in lowered_keywords):
                    filtered.append(hit)

        if filtered:
            result = filtered
        else:
            result = hits[:5]

        normalized_query = re.sub(r"\s+", "", (query or "").lower())
        if normalized_query:
            need_relax = len(normalized_query) >= 12 or len(result) < 3
            if need_relax:
                grams: set[str] = set()
                if len(normalized_query) >= 3:
                    for idx in range(len(normalized_query) - 2):
                        grams.add(normalized_query[idx : idx + 3])
                else:
                    grams.add(normalized_query)
                relaxed: List[Dict[str, Any]] = []
                for hit in hits:
                    hay = _haystack(hit)
                    if any(g in hay for g in grams):
                        relaxed.append(hit)
                if relaxed:
                    seen_ids = set()
                    merged: List[Dict[str, Any]] = []
                    for bucket in (filtered, relaxed) if filtered else (relaxed,):
                        for hit in bucket:
                            oid = id(hit)
                            if oid in seen_ids:
                                continue
                            seen_ids.add(oid)
                            merged.append(hit)
                    if merged:
                        result = merged

        return result

    def _normalize_whitespace(self, text: str) -> str:
        if not text:
            return ""
        normalized = (
            text.replace("\r", " ")
            .replace("\n", " ")
            .replace("\xa0", " ")
            .replace("\u3000", " ")
        )
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _clean_leading_symbols(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.lstrip()
        cleaned = self.CONTROL_CHAR_PREFIX.sub("", cleaned)
        cleaned = self.LEADING_SYMBOL_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"^[^\w\u4e00-\u9fff]+", "", cleaned)
        cleaned = self.ISOLATED_CJK_PREFIX.sub("", cleaned)
        cleaned = cleaned.strip()
        normalized = self._normalize_whitespace(cleaned)
        return normalized or text.strip()

    def _segment_sentences(self, text: str) -> List[str]:
        """
        按照段落/句子组合切分原文，确保每段信息量足够大。
        """
        normalized = text.replace("\r", "\n")
        raw_segments = re.split(r"(?<=[。！？!?])", normalized)
        segments: List[str] = []
        buffer = ""
        for piece in raw_segments:
            chunk = piece.strip()
            if not chunk:
                continue
            if len(buffer) + len(chunk) < 320:
                buffer += chunk
            else:
                if buffer.strip():
                    segments.append(buffer.strip())
                buffer = chunk
        if buffer.strip():
            segments.append(buffer.strip())
        usable = [seg for seg in segments if len(seg) >= 60]
        return usable or [text.strip()]

    def _ensure_sentence(self, text: str) -> str:
        cleaned = self._normalize_whitespace(text)
        if not cleaned:
            return ""
        if cleaned.endswith(("。", "！", "?", "？", "…", "……")):
            return cleaned
        return cleaned + "。"


    def _filter_segments_by_keywords(
        self,
        segments: List[Dict[str, Any]],
        keywords: List[str],
    ) -> List[Dict[str, Any]]:
        lowered = [kw.lower() for kw in keywords]
        filtered: List[Dict[str, Any]] = []
        for entry in segments:
            candidate = entry["text"].lower()
            if any(keyword in candidate for keyword in lowered):
                filtered.append(entry)
        return filtered

    def _normalize_answer_output(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.lstrip("\ufeff\u200b\u200c\u200d")
        heading_idx = cleaned.find("###")
        if heading_idx > 0 and heading_idx < 8:
            prefix = cleaned[:heading_idx].strip()
            if len(prefix) <= 2:
                cleaned = cleaned[heading_idx:]
        return cleaned

    def _strip_quotes_and_noise(self, text: str) -> str:
        if not text:
            return text
        s = text.strip()
        quote_pairs = [
            ("'", "'"),
            ('"', '"'),
            ("“", "”"),
            ("‘", "’"),
            ("«", "»"),
            ("＂", "＂"),
            ("＇", "＇"),
            ("「", "」"),
            ("『", "』"),
        ]
        for left, right in quote_pairs:
            if s.startswith(left) and s.endswith(right) and len(s) >= 2:
                s = s[1:-1].strip()
        s = re.sub(r'^[\uFEFF\u200B\u200C\u200D\s`\'"“”‘’＂＇、，,。．·…:：;；\-—–（）()\[\]【】「」『』]+', '', s)
        s = re.sub(r'[\s\u200B\u200C\u200D\uFEFF]+$', '', s)
        return s.strip()

    def _build_citations(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        citations: List[Dict[str, Any]] = []
        seen = set()
        for doc in docs:
            metadata = (doc.get("metadata") or {}) if isinstance(doc, dict) else {}
            source, page, text, score = self._doc_fields(doc)
            clean_text = self._clean_leading_symbols(text)
            key = (source, page, clean_text[:120])
            if key in seen:
                continue
            seen.add(key)
            source_type = str(metadata.get("source_type", "")).lower()
            confidence = "high" if score >= 0.65 else ("medium" if score >= 0.35 else "low")
            citations.append(
                {
                    "source": source,
                    "page": page,
                    "snippet": (clean_text[:240] + "...") if len(clean_text) > 240 else clean_text,
                    "score": score,
                    "source_type": "web" if source_type == "web" else "document",
                    "url": metadata.get("url"),
                    "title": metadata.get("title"),
                    "published_date": metadata.get("published_at"),
                    "confidence": confidence,
                }
            )
        return citations

    async def _intelligent_decompose_query(self, query: str) -> Tuple[List[str], bool, int]:
        basic_queries, basic_truncated, basic_original_count = self._basic_decompose_query(query)
        if len(basic_queries) <= 1 or len(query.strip()) < 20:
            return basic_queries, basic_truncated, basic_original_count

        max_topics = self.MULTI_TOPIC_MAX_TOPICS
        prompt = f"""分析以下用户查询，识别是否包含多个不同的主题领域。如果包含多个主题，请按领域进行分解。

原始查询: "{query}"

分解原则：
1. 识别查询中涉及的不同语义领域（如：医学、技术、管理等）
2. 同一领域的内容保持在一个子查询中
3. 避免跨领域的混合查询
4. 每个子查询应该专注一个明确的主题领域

请按以下格式回答：
单一主题: [主题明确的查询]

或

多主题分解：
子查询1: [第一个主题领域的问题]
子查询2: [第二个主题领域的问题]
子查询3: [第三个主题领域的问题]

示例：
- "CPPS治疗方法，Linux常用命令" → 子查询1: CPPS的治疗方法是什么，子查询2: Linux常用命令有哪些
- "如何安装conda，以及git基本操作" → 子查询1: 如何安装conda环境，子查询2: git的基本操作命令

注意：最多分解为{max_topics}个子查询，确保每个子查询主题单一明确。"""

        try:
            async with self._ollama_client() as client:
                task = asyncio.create_task(
                    client.chat(
                        model=settings.ollama_model,
                        messages=[{"role": "user", "content": prompt}],
                        options={"temperature": 0.1, "num_predict": 200},
                        stream=False,
                    )
                )
                try:
                    timeout = min(8.0, settings.ollama_timeout)
                    response = await asyncio.wait_for(task, timeout=timeout)
                except asyncio.TimeoutError:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise
                except asyncio.CancelledError:
                    task.cancel()
                    with suppress(Exception):
                        await task
                    raise
                except Exception:
                    task.cancel()
                    with suppress(Exception):
                        await task
                    raise
        except asyncio.TimeoutError:
            self.logger.warning("LLM decomposition timeout, fallback to basic.")
            return basic_queries, basic_truncated, basic_original_count
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.warning(f"LLM decomposition error: {exc}")
            return basic_queries, basic_truncated, basic_original_count

        llm_response = response.get("message", {}).get("content", "").strip()
        if llm_response.startswith("单一主题:"):
            single_query = llm_response.replace("单一主题:", "").strip()
            return [single_query], False, 1

        sub_queries_raw: List[str] = []
        for line in llm_response.split("\n"):
            line = line.strip()
            if line.startswith("子查询") and ":" in line:
                query_part = line.split(":", 1)[1].strip()
                if query_part:
                    sub_queries_raw.append(query_part)

        if len(sub_queries_raw) > 1:
            truncated = len(sub_queries_raw) > max_topics
            limited = sub_queries_raw[:max_topics]
            return limited, truncated, len(sub_queries_raw)

        return basic_queries, basic_truncated, basic_original_count

    def _basic_decompose_query(self, query: str) -> Tuple[List[str], bool, int]:
        text = (query or "").strip()
        if not text:
            return [query], False, 1

        parts = re.split(r"[\n。；;？！?!,，、]+", text)
        cleaned: List[str] = []
        for part in parts:
            fragment = part.strip()
            if not fragment:
                continue
            fragment = re.sub(r"^(\d+\s*[\.、]\s*)", "", fragment)
            fragment = re.sub(r"^第\s*\d+\s*(题|问)\s*", "", fragment)
            fragment = fragment.strip()
            if fragment:
                cleaned.append(fragment)

        if not cleaned:
            return [text], False, 1

        truncated = len(cleaned) > self.MULTI_TOPIC_MAX_TOPICS
        limited = cleaned[: self.MULTI_TOPIC_MAX_TOPICS]
        return limited, truncated, len(cleaned)

    def _prepare_multi_topic_docs(self, retrievals: List[Tuple[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        fused: Dict[str, Dict[str, Any]] = {}
        for sub_query, retrieval in retrievals:
            results = retrieval.results or []
            for rank, item in enumerate(results[: settings.doc_answer_max_snippets * 4], start=1):
                metadata = item.get("metadata", {}) or {}
                if str(metadata.get("source_type", "")).lower() == "web":
                    continue
                chunk_id = metadata.get("chunk_id") or item.get("chunk_id")
                if chunk_id is None:
                    chunk_id = f"{metadata.get('source')}#{rank}#{hash(item.get('text', ''))}"
                chunk_id = str(chunk_id)
                entry = fused.setdefault(
                    chunk_id,
                    {
                        "doc": item,
                        "topics": set(),
                        "score": 0.0,
                    },
                )
                entry["topics"].add(sub_query)
                entry["score"] += 1.0 / (rank + 1.0)

        if not fused:
            return {}

        sorted_docs = sorted(fused.values(), key=lambda x: x["score"], reverse=True)
        topic_docs: Dict[str, List[Dict[str, Any]]] = {sub: [] for sub, _ in retrievals}

        for entry in sorted_docs:
            doc = entry["doc"]
            for sub_query in entry["topics"]:
                if len(topic_docs[sub_query]) >= self.MULTI_TOPIC_MAX_SNIPPETS:
                    continue
                topic_docs[sub_query].append(doc)

        return topic_docs

    def _build_multi_topic_prompt(
        self,
        topics: List[str],
        topic_docs: Dict[str, List[Dict[str, Any]]],
        *,
        feedback: Optional[str] = None,
    ) -> str:
        if not topic_docs:
            return build_general_prompt("\n".join(topics), feedback=feedback)

        question_lines = [f"{idx}. {topic}" for idx, topic in enumerate(topics, start=1)]
        sections: List[str] = []
        for idx, topic in enumerate(topics, start=1):
            docs = topic_docs.get(topic, [])
            if not docs:
                continue
            chunk_lines: List[str] = []
            for doc_idx, doc in enumerate(docs, start=1):
                metadata = doc.get("metadata", {}) or {}
                title = metadata.get("source") or doc.get("source") or "Unknown"
                page = metadata.get("page")
                identifier = f"[{idx}.{doc_idx}]"
                header = f"{identifier} 《{title}》"
                if page not in (None, ""):
                    header += f" P.{page}"
                text = str(doc.get("text") or metadata.get("text") or "")[:800]
                chunk_lines.append(f"{header}\n{text}")
            sections.append(f"主题{idx}: {topic}\n" + "\n\n".join(chunk_lines))

        context = "\n\n".join(sections)
        return (
            "你是一名检索增强问答助手。下面包含多个主题的问题及对应的参考文档片段。"
            "请针对每个主题分别回答，并在要点后使用方括号标注引用编号（如 [1.2] 表示主题1的第2个片段）。\n\n"
            "问题列表：\n"
            + "\n".join(question_lines)
            + "\n\n文档片段：\n"
            + context
            + "\n\n回答格式（每个主题都需遵循）：\n"
            "### 主题N：问题内容\n"
            "#### 结论\n"
            "- 至少 3 句话，总结该主题的结论及其背景影响。\n"
            "#### 详细解析\n"
            "1. 针对关键事实或步骤展开说明，每条不少于 2 句话，并附上引用编号（如 [1.2]）。\n"
            "2. 至少列出 3 条要点；如证据更丰富可继续编号。\n"
            "#### 建议\n"
            "- 提供 1-2 条可执行建议；若无可靠依据，请标注“暂无可靠建议”。\n"
            "若没有检索到可信证据，请直接写“未检索到可靠来源”并提示用户可能的补救措施。\n"
        )

    async def _compose_multi_topic_answer(
        self,
        topics: List[str],
        original_topic_count: int,
        topic_docs: Dict[str, List[Dict[str, Any]]],
        history: Optional[str],
        truncated: bool,
        feedback: Optional[str] = None,
        topic_web_docs: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        sections: List[str] = []
        combined_citations: List[Dict[str, Any]] = []

        if truncated:
            limit = min(original_topic_count, self.MULTI_TOPIC_MAX_TOPICS)
            sections.append(f"> 提示：输入包含 {original_topic_count} 个主题，已精简至 {limit} 个。")

        if feedback:
            feedback_lines = [line.strip() for line in feedback.strip().splitlines() if line.strip()]
            if feedback_lines:
                formatted = "\n".join(f"> {line}" for line in feedback_lines)
                sections.append(
                    "\n".join(
                        [
                            "> 用户反馈：",
                            formatted,
                            "> 请逐条修正上述问题，确保新的回答明显改进。",
                        ]
                    )
                )

        for idx, topic in enumerate(topics, start=1):
            docs = list(topic_docs.get(topic, []) or [])
            web_docs = list(topic_web_docs.get(topic, []) if topic_web_docs else [])
            combined_docs = docs + web_docs
            if not combined_docs:
                sections.append("\n\n".join([
                    f"### 主题{idx}：{topic}",
                    "未检索到可靠来源。",
                    "",
                    "来源:",
                    "- 未检索到可靠来源",
                ]))
                continue

            topic_heading = f"主题{idx}：{topic}"
            if web_docs:
                topic_heading += "（联网）"
            try:
                structured, topic_citations = await self._generate_structured_answer(
                    topic,
                    combined_docs,
                    topic_name=topic_heading,
                )
            except Exception as exc:
                self.logger.warning(
                    "multi_topic.summary_failed",
                    extra={"topic": topic, "error": str(exc)},
                )
                structured = self._fallback_topic_summary(f"{topic_heading}", combined_docs, idx)
                topic_citations = self._build_citations(combined_docs)
            sections.append(structured.strip())
            combined_citations.extend(topic_citations)

        if not sections:
            return "未检索到可靠来源。", []

        answer = "\n\n".join(sections)
        unique: List[Dict[str, Any]] = []
        seen = set()
        for item in combined_citations:
            key = (item.get("source"), item.get("page"), item.get("snippet"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return answer, unique

    def _fallback_topic_summary(self, topic_title: str, docs: List[Dict[str, Any]], topic_index: int) -> str:
        title_line = topic_title if topic_title.startswith("###") else f"### {topic_title}"
        lines: List[str] = [title_line]
        if not docs:
            lines.append("未检索到可靠来源。")
            lines.append("")
            lines.append("来源:")
            lines.append("- 未检索到可靠来源")
            return "\n".join(lines)
        for doc in docs[: self.MULTI_TOPIC_MAX_SNIPPETS]:
            metadata = doc.get("metadata", {}) or {}
            text = (doc.get("text") or metadata.get("text") or doc.get("content") or "").strip()
            if not text:
                continue
            snippet = self._ensure_sentence(text[:400])
            lines.append(f"- {snippet}{self._format_citation(doc)}")
        lines.append("")
        lines.append("来源:")
        for doc_idx, doc in enumerate(docs[: self.MULTI_TOPIC_MAX_CITATIONS], start=1):
            metadata = doc.get("metadata", {}) or {}
            title = metadata.get("source") or doc.get("source") or "Unknown"
            page = metadata.get("page")
            label = f"[{topic_index}.{doc_idx}] {title}"
            source_type = str(metadata.get("source_type") or metadata.get("type") or "").lower()
            if source_type == "web" or metadata.get("url"):
                label = f"(联网) {label}"
            if page not in (None, ""):
                label += f" (P.{page})"
            lines.append(f"- {label}")
        return "\n".join(lines)

    def _build_multi_topic_citations(
        self,
        topic_docs: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        citations: List[Dict[str, Any]] = []
        for docs in topic_docs.values():
            for doc in docs:
                metadata = doc.get("metadata", {}) or {}
                page = metadata.get("page")
                try:
                    page_value = int(page)
                except (TypeError, ValueError):
                    page_value = None
                snippet = (doc.get("text") or metadata.get("text") or "")[:240]
                citations.append(
                    {
                        "source": metadata.get("source") or doc.get("source"),
                        "page": page_value,
                        "snippet": snippet,
                        "score": float(metadata.get("score", doc.get("score", 0.0)) or 0.0),
                    }
                )
        # 去重
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for citation in citations:
            key = (citation.get("source"), citation.get("page"), citation.get("snippet"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(citation)
        return deduped

    async def _chat(
        self,
        messages: List[Dict[str, str]],
        *,
        query: str,
        mode: str,
        fallback: Optional[str] = None,
    ) -> str:
        attempts = max(1, self.OLLAMA_CHAT_MAX_ATTEMPTS)
        last_error: Optional[BaseException] = None
        logger = self.logger
        log_query = (query or "")[:120]

        for attempt in range(1, attempts + 1):
            async with self._ollama_client() as client:
                task = asyncio.create_task(
                    client.chat(
                        model=settings.ollama_model,
                        messages=messages,
                        options=self._ollama_options(),
                    )
                )
                try:
                    response = await asyncio.wait_for(task, timeout=settings.ollama_timeout)
                except asyncio.TimeoutError as exc:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    logger.warning(
                        "ollama.chat.timeout",
                        extra={
                            "query": log_query,
                            "mode": mode,
                            "attempt": attempt,
                            "timeout": settings.ollama_timeout,
                        },
                    )
                    last_error = exc
                except asyncio.CancelledError:
                    task.cancel()
                    with suppress(Exception):
                        await task
                    raise
                except Exception as exc:
                    task.cancel()
                    with suppress(Exception):
                        await task
                    logger.warning(
                        "ollama.chat.error",
                        extra={
                            "query": log_query,
                            "mode": mode,
                            "attempt": attempt,
                            "exc": type(exc).__name__,
                        },
                    )
                    last_error = exc
                else:
                    if attempt > 1:
                        logger.info(
                            "ollama.chat.retry_success",
                            extra={
                                "query": log_query,
                                "mode": mode,
                                "attempt": attempt,
                            },
                        )
                    content = response.get("message", {}).get("content", "").strip()
                    if content:
                        content = self._strip_quotes_and_noise(content)
                    return content

            if attempt < attempts:
                base = self.OLLAMA_RETRY_BACKOFF_SECONDS
                jitter = random.uniform(0, base * (2 ** attempt))
                backoff = min(4.0, jitter)
                await asyncio.sleep(backoff)

        if last_error and not isinstance(last_error, asyncio.TimeoutError):
            logger.exception(
                "llm.failure",
                extra={
                    "query": log_query,
                    "mode": mode,
                    "exc": type(last_error).__name__,
                },
            )

        if fallback:
            return fallback

        if isinstance(last_error, asyncio.TimeoutError):
            if mode == "doc":
                return (
                    "[非文档知识]\n"
                    "生成基于文档的回答超时，暂无法引用具体来源。\n"
                    f"问题：{query}\n"
                    "建议稍后重试，或让我以常识模式回答该问题。"
                )
            return (
                "[非文档知识]\n"
                "回答生成超时，我根据常识给出简要建议：\n"
                "- 请稍后重试或让我联网检索权威信息。\n"
                "- 也可以补充更多上下文，以便提供更精准的建议。"
            )

        return (
            "[非文档知识]\n"
            "调用本地模型时发生错误，暂无法生成引用答案。\n"
            "建议稍后重试或检查 Ollama 服务状况。"
        )

    def _general_suggestions(self) -> List[str]:
        return [
            "限定问题范围，例如：请只依据上传文档回答",
            "如果需要最新数据，可以让我联网检索权威来源",
            "补充时间、对象、指标等背景信息，以便精确检索",
        ]

    def _module_config(self, doc_only: bool, allow_web: Optional[bool]) -> Dict[str, Any]:
        allow_web_flag = bool(allow_web)
        return {
            "doc_only": doc_only,
            "allow_web": allow_web_flag,
            "stacked": bool(doc_only and allow_web_flag),
        }

    def _build_response_meta(
        self,
        *,
        intent: IntentAnalysisResult,
        strategy: str,
        multi_topic: bool,
        topics: Optional[List[str]],
        web_used: bool,
        doc_sources: int,
        web_sources: int,
        truncated: bool = False,
        modules: Optional[Dict[str, Any]] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "strategy": strategy,
            "answering_mode": intent.answering_mode.value,
            "question_type": intent.question_type.value,
            "time_sensitivity": intent.time_sensitivity,
            "confidence": intent.confidence,
            "multi_topic": multi_topic,
            "topics": topics or intent.raw_topics,
            "truncated_topics": truncated,
            "web_search_used": web_used,
            "source_counts": {
                "documents": doc_sources,
                "web": web_sources,
            },
            "modules": modules or {},
        }
        if feedback:
            payload["feedback_history"] = feedback
        return payload

    def _intent_payload(self, intent: IntentAnalysisResult) -> Dict[str, Any]:
        return {
            "question_type": intent.question_type.value,
            "answering_mode": intent.answering_mode.value,
            "confidence": intent.confidence,
            "requires_web_search": intent.requires_web_search,
            "time_sensitivity": intent.time_sensitivity,
            "complexity_score": intent.complexity_score,
            "reasoning": intent.rationale,
        }

    def _token_overlap_ratio(self, query: str, docs: List[Dict[str, Any]]) -> float:
        q_tokens = self._normalized_tokens(query)
        if not q_tokens:
            return 0.0

        snippet_parts: List[str] = []
        for doc in docs:
            text = doc.get("text")
            if not text:
                metadata = (doc.get("metadata") or {}) if isinstance(doc, dict) else {}
                text = metadata.get("text") or ""
            snippet_parts.append(str(text)[:600])
        snippet_text = " ".join(snippet_parts)
        doc_tokens = self._normalized_tokens(snippet_text)
        if not doc_tokens:
            return 0.0

        token_overlap = len(q_tokens & doc_tokens) / max(len(q_tokens), 1)

        query_ngrams = self._char_ngrams(query)
        doc_ngrams = self._char_ngrams(snippet_text)
        ngram_overlap = len(query_ngrams & doc_ngrams) / max(len(query_ngrams), 1) if query_ngrams else 0.0

        compact_query = self._compact_text(query)
        compact_doc = self._compact_text(snippet_text[:800])
        sequence_score = (
            SequenceMatcher(None, compact_query, compact_doc).ratio()
            if compact_query and compact_doc
            else 0.0
        )

        return round(token_overlap * 0.5 + ngram_overlap * 0.3 + sequence_score * 0.2, 4)

    def _normalized_tokens(self, text: Optional[str]) -> Set[str]:
        if not text:
            return set()
        raw_tokens = re.findall(r"[\u4e00-\u9fa5]|[A-Za-z0-9_]+", text)
        normalized: Set[str] = set()
        for raw in raw_tokens:
            token = raw.lower()
            if token in STOPWORDS_EN or token in STOPWORDS_ZH:
                continue
            if token.isascii() and token.isalpha() and len(token) == 1:
                continue
            normalized.add(token)
        return normalized

    def _char_ngrams(self, text: Optional[str], n: int = 3) -> Set[str]:
        compact = self._compact_text(text)
        if not compact:
            return set()
        if len(compact) <= n:
            return {compact}
        return {compact[i : i + n] for i in range(len(compact) - n + 1)}

    def _compact_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", "", text.lower())

    def _build_messages_for_mode(self, prompt: str, mode: str) -> List[Dict[str, str]]:
        if mode == "doc":
            system_prompt = (
                "你是企业知识库助手，只能基于提供的历史与文档片段回答，并给出清晰引用。"
                "回答需结构化，涵盖必要背景，若信息缺失请说明。"
            )
        else:
            system_prompt = (
                "你是业务顾问，当文档不足时结合历史对话使用常识回答。"
                "不要伪造文档引用，需标注为[非文档知识]并提醒用户进一步核实。"
            )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

    def _compose_prompt(self, history: Optional[str], prompt_core: str, mode: str) -> str:
        history_text = (history or "").strip()
        if not history_text:
            return prompt_core
        if mode == "doc":
            preface = (
                "以下为本会话的历史问答，请结合这些上下文保持语义连贯并回答当前问题。\n"
            )
        else:
            preface = (
                "以下为本会话的历史问答，请在理解上下文的基础上补充非文档知识回应。\n"
            )
        return f"{preface}{history_text}\n\n{prompt_core}"

    def _build_stream_messages(self, query: str, context: str) -> List[Dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that answers user questions using only the provided context. "
                    "Produce structured answers with sufficient detail and cite supporting chunks using the format [[chunk_id]]. "
                    "If the answer cannot be determined from the context, respond with 'I do not know.'"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Context:\n{context}\n\nQuestion:\n{query}\n\n"
                    "Provide a concise answer in markdown. Always include citations."
                ),
            },
        ]

    def _ollama_options(self) -> Dict[str, Any]:
        return {
            "temperature": settings.ollama_temperature,
            "num_ctx": settings.ollama_num_ctx,
            "num_predict": settings.ollama_num_predict,
        }

    def _doc_fields(self, doc: Dict[str, Any]) -> Tuple[str, Optional[int], str, float]:
        """
        统一获取 (source, page, text, score)
        - 优先从 metadata 取，回退 doc 顶层
        - page 解析失败返回 None
        - text 截断交给调用方决定
        """
        md = (doc.get("metadata") or {}) if isinstance(doc, dict) else {}
        source = (
            md.get("source")
            or doc.get("source")
            or md.get("title")
            or doc.get("title")
            or md.get("url")
            or doc.get("url")
            or "unknown"
        )
        page_raw = md.get("page", doc.get("page"))
        try:
            page = int(page_raw) if page_raw not in (None, "") else None
        except (ValueError, TypeError):
            page = None
        text_candidates = [
            doc.get("text"),
            md.get("text"),
            doc.get("content"),
            md.get("content"),
            doc.get("snippet"),
            md.get("snippet"),
            doc.get("description"),
            md.get("description"),
        ]
        text = ""
        for candidate in text_candidates:
            if candidate is None:
                continue
            candidate_str = str(candidate).strip()
            if candidate_str:
                text = candidate_str
                break
        score = float(md.get("score", doc.get("score", 0.0)) or 0.0)
        return source, page, text, score

    async def _generate_structured_answer(
        self,
        query: str,
        docs: List[Dict[str, Any]],
        topic_name: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        if not docs:
            topic = topic_name or self._extract_main_topic(query)
            message = f"### 主题：{topic}\n\n未检索到可引用的文档内容。"
            return message, []

        topic = topic_name or self._extract_main_topic(query)
        doc_segments: List[Dict[str, Any]] = []
        doc_labels: Dict[int, Dict[str, Any]] = {}
        seen_segments: Set[Tuple[int, str]] = set()
        for idx, doc in enumerate(docs, start=1):
            source, page, text, _ = self._doc_fields(doc)
            clean_text = self._clean_leading_symbols(text)
            if not clean_text:
                continue
            label = source or "未知来源"
            if page not in (None, ""):
                label = f"{label} · P{page}"
            metadata = (doc.get("metadata") or {}) if isinstance(doc, dict) else {}
            source_type = str(metadata.get("source_type") or metadata.get("type") or "").lower()
            is_web_doc = bool(source_type == "web" or metadata.get("url"))
            if is_web_doc:
                label = f"(联网) {label}"
            doc_labels[idx] = {"label": label, "source": source, "page": page, "is_web": is_web_doc}
            for sentence in self._segment_sentences(clean_text):
                key = (idx, sentence[:80])
                if key in seen_segments:
                    continue
                seen_segments.add(key)
                doc_segments.append(
                    {
                        "doc_idx": idx,
                        "text": self._ensure_sentence(sentence),
                        "id": len(doc_segments),
                        "is_web": is_web_doc,
                    }
                )
        if not doc_segments:
            topic = topic_name or self._extract_main_topic(query)
            message = f"### 主题：{topic}\n\n文档内容无法解析。"
            return message, []

        def _entry_line(entry: Dict[str, Any]) -> str:
            return self._normalize_whitespace(entry["text"])

        doc_entries = [entry for entry in doc_segments if not entry.get("is_web")]
        primary_entries = doc_entries if doc_entries else doc_segments
        summary_entry = primary_entries[0]
        answer_parts: List[str] = [f"### 主题：{topic}", "#### 摘要速览"]
        answer_parts.append(f"- {_entry_line(summary_entry)}")

        answer_parts.append("#### 一、关键结论（证据驱动）")
        key_entries = primary_entries[:6]
        used_entry_ids = {entry["id"] for entry in key_entries}
        for entry in key_entries:
            answer_parts.append(f"- {_entry_line(entry)}")

        method_entries = [
            entry
            for entry in self._filter_segments_by_keywords(
                primary_entries,
                ["方法", "步骤", "练习", "操作", "实施", "训练", "采用", "策略", "疗法"],
            )
            if entry["id"] not in used_entry_ids
        ]
        used_entry_ids.update(entry["id"] for entry in method_entries)
        answer_parts.append("#### 二、方法 / 步骤（可执行）")
        if method_entries:
            for entry in method_entries[:4]:
                answer_parts.append(f"- {_entry_line(entry)}")
        else:
            answer_parts.append("未在文档中找到")

        risk_entries = [
            entry
            for entry in self._filter_segments_by_keywords(
                primary_entries,
                ["风险", "注意", "限制", "避免", "警告", "不足", "不建议"],
            )
            if entry["id"] not in used_entry_ids
        ]
        answer_parts.append("#### 三、风险与限制 / 注意事项")
        if risk_entries:
            for entry in risk_entries[:4]:
                answer_parts.append(f"- {_entry_line(entry)}")
        else:
            answer_parts.append("未在文档中找到")
        used_entry_ids.update(entry["id"] for entry in risk_entries)

        web_entries = [entry for entry in doc_segments if entry.get("is_web")]
        web_unused = [entry for entry in web_entries if entry["id"] not in used_entry_ids]
        if web_unused:
            answer_parts.append("#### **联网补充**")
            for entry in web_unused[:4]:
                answer_parts.append(f"- {_entry_line(entry)}")

        answer_parts.append("来源:")
        for idx in sorted(doc_labels.keys()):
            info = doc_labels[idx]
            label = info["label"]
            answer_parts.append(f"- {label}")
        return "\n".join(answer_parts), self._build_citations(docs)

    def _extract_main_topic(self, query: str) -> str:
        """从查询中提取主要主题"""
        # 简单的主题提取逻辑
        if 'cpps' in query.lower() or '盆腔' in query:
            return "CPPS相关"
        elif 'linux' in query.lower() or '命令' in query:
            return "Linux命令"
        elif 'conda' in query.lower():
            return "Conda环境管理"
        elif 'git' in query.lower():
            return "Git版本控制"
        else:
            # 取查询的前20个字符作为主题
            return query[:20] + "..." if len(query) > 20 else query

    def _topic_with_web_suffix(self, topic: Optional[str]) -> str:
        base = (topic or "").strip() or "联网补充"
        if "联网" in base:
            return base
        return f"{base}（联网）"

    def _prepare_web_docs_for_structured_answer(
        self,
        docs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        prepared: List[Dict[str, Any]] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            metadata = doc.setdefault("metadata", {}) or {}
            if doc.get("title") and not metadata.get("title"):
                metadata["title"] = doc["title"]
            if doc.get("url") and not metadata.get("url"):
                metadata["url"] = doc["url"]
            metadata.setdefault("source_type", "web")
            if not metadata.get("source"):
                metadata["source"] = (
                    doc.get("source")
                    or metadata.get("title")
                    or (metadata.get("url") or doc.get("url") or "外部来源")
                )
            text_candidates = [
                doc.get("text"),
                metadata.get("text"),
                doc.get("content"),
                metadata.get("content"),
                doc.get("snippet"),
                metadata.get("snippet"),
                doc.get("description"),
                metadata.get("description"),
            ]
            chosen = ""
            for candidate in text_candidates:
                if candidate is None:
                    continue
                candidate_str = str(candidate).strip()
                if candidate_str:
                    chosen = candidate_str
                    break
            if chosen:
                doc["text"] = chosen
                metadata.setdefault("text", chosen)
            prepared.append(doc)
        return prepared

    def _format_citation(self, doc: Dict[str, Any]) -> str:
        source, page, _, _ = self._doc_fields(doc)
        metadata = (doc.get("metadata") or {}) if isinstance(doc, dict) else {}
        url = metadata.get("url") or doc.get("url")
        suffixes = (".docx", ".pdf", ".odt", ".txt", ".md", ".pptx", ".ppt", ".xlsx")
        lower_source = source.lower()
        for suf in suffixes:
            if lower_source.endswith(suf):
                source = source[: -len(suf)]
                break
        label = source or "外部来源"
        if url:
            label = f"[{label}]({url})"
        if page is None:
            return f"【{label}】"
        return f"【{label}†P{page}】"

    def _format_reference_label(self, index: int, citation: Dict[str, Any]) -> str:
        source = citation.get("source") or "未知来源"
        page = citation.get("page")
        snippet = (citation.get("snippet") or "").strip().replace("\n", " ")
        if len(snippet) > 80:
            snippet = snippet[:77].rstrip() + "..."
        page_text = f" P{page}" if isinstance(page, int) else ""
        return f"- [{index}] {source}{page_text} — {snippet}"

    async def _answer_general_knowledge(
        self,
        query: str,
        history: Optional[str],
        intent_result: IntentAnalysisResult,
        *,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        常识知识回答模式 - 针对常识问题提供直接回答
        """
        # 如果有时效性需求，尝试联网搜索增强
        web_docs = []
        if intent_result.requires_web_search and self.web_search and self.web_search.available:
            try:
                web_docs = await self._web_search(query, 3) or []
            except WebSearchQuotaExceededError as exc:
                self.logger.warning("Web search quota exceeded during general knowledge flow", extra={"error": str(exc)})
            except Exception as exc:
                self.logger.warning(f"Web search failed for general knowledge: {exc}")

        # 构建提示词
        prompt_core = self._build_general_knowledge_prompt(
            query,
            web_docs,
            intent_result,
            feedback=feedback,
        )
        prompt = self._compose_prompt(history, prompt_core, "general")
        messages = self._build_messages_for_mode(prompt, "general")
        answer = await self._chat(messages, query=query, mode="general")

        # 确保有常识回答标识
        if "[常识知识]" not in answer:
            answer = "[常识知识]\n" + answer

        # 如果有联网搜索结果，添加相关信息
        citations = []
        if web_docs:
            web_section, web_citations = self._build_web_highlights(web_docs, "联网参考信息")
            if web_section:
                answer = answer.rstrip() + "\n\n" + web_section
            citations.extend(web_citations)

        # 构建诊断信息
        diagnostics = {
            "intent_analysis": {
                "question_type": intent_result.question_type.value,
                "answering_mode": intent_result.answering_mode.value,
                "confidence": intent_result.confidence,
                "time_sensitivity": intent_result.time_sensitivity,
                "complexity_score": intent_result.complexity_score,
            },
            "web_search_used": len(web_docs) > 0,
            "web_hits": len(web_docs),
        }

        meta = self._build_response_meta(
            intent=intent_result,
            strategy="general_common",
            multi_topic=False,
            topics=intent_result.raw_topics,
            web_used=bool(web_docs),
            doc_sources=0,
            web_sources=len(web_docs),
            feedback=feedback,
        )
        return {
            "answer": answer,
            "mode": "general",
            "citations": citations,
            "suggestions": self._get_general_knowledge_suggestions(intent_result),
            "sources": citations,
            "diagnostics": diagnostics,
            "meta": meta,
            "multi_topics": intent_result.raw_topics,
        }

    def _build_general_knowledge_prompt(
        self,
        query: str,
        web_docs: List[Dict[str, Any]],
        intent_result: IntentAnalysisResult,
        *,
        feedback: Optional[str] = None,
    ) -> str:
        """
        构建常识知识回答的提示词
        """
        feedback_block = ""
        if feedback:
            cleaned = feedback.strip()
            if cleaned:
                feedback_block = (
                    "\n用户对上一轮回答的反馈如下，请针对性改进：\n"
                    f"{cleaned}\n"
                    "务必避免重复上述问题。\n"
                )
        base_prompt = f"""请基于你的通用知识回答以下问题。{f"如果提供了联网搜索结果，请结合最新信息进行回答。" if web_docs else ""}

问题：{query}

回答要求：
1. 提供准确、清晰的答案
2. 如果问题涉及多个方面，请分点说明
3. 保持客观中立的立场
4. 如果信息不确定，请明确说明"""

        if feedback_block:
            base_prompt = f"{base_prompt}{feedback_block}"

        if web_docs:
            web_info = "\n\n联网参考信息：\n"
            for i, doc in enumerate(web_docs[:3], 1):
                title = doc.get("title", "来源")
                content = doc.get("content", doc.get("text", ""))
                web_info += f"{i}. {title}: {content[:200]}...\n"
            base_prompt += web_info

        # 根据问题类型调整提示词
        if intent_result.question_type == QuestionType.HOW_TO:
            base_prompt += "\n\n请提供详细的步骤说明，确保可操作性。"
        elif intent_result.question_type == QuestionType.COMPARISON:
            base_prompt += "\n\n请提供客观的对比分析，突出各自的优缺点。"
        elif intent_result.time_sensitivity > 0.6:
            base_prompt += "\n\n请特别关注信息的时效性，优先提供最新的信息。"

        return base_prompt

    def _get_general_knowledge_suggestions(self, intent_result: IntentAnalysisResult) -> List[str]:
        """
        为常识知识回答提供建议
        """
        suggestions = [
            "如需更具体的指导，请提供更多背景信息",
            "如果这是关于特定领域的问题，可以让我基于上传文档回答"
        ]

        if intent_result.time_sensitivity > 0.5:
            suggestions.append("如需最新数据，建议明确时间范围")

        if intent_result.complexity_score > 0.7:
            suggestions.append("复杂问题可以分解为多个子问题分别提问")

        if intent_result.question_type == QuestionType.HOW_TO:
            suggestions.append("可以询问具体的操作步骤和注意事项")

        return suggestions

    async def _parallel_multi_topic_retrieval(
        self,
        sub_queries: List[str],
        adaptive_top_k: int,
        alpha: Optional[float],
        use_rerank: Optional[bool],
        filters: Optional[Dict[str, Any]],
        use_web: bool,
        enable_web_search: bool,
        quota_state: Dict[str, bool],
    ) -> Tuple[List[Tuple[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        并行执行多主题检索

        Args:
            sub_queries: 子查询列表
            adaptive_top_k: 适应性的top_k值
            alpha: 混合权重
            use_rerank: 是否使用重排序
            filters: 过滤器
            use_web: 是否允许使用网络搜索
            enable_web_search: 是否需要发起网络搜索（受模式和意图影响）

        Returns:
            List[Tuple[str, Any]]: 检索结果列表 (查询, 检索结果)
        """
        async def retrieve_single_topic(sub_query: str) -> Tuple[str, Any, List[Dict[str, Any]]]:
            """检索单个主题"""
            # 并行执行文档检索和网络搜索
            retrieval_task = asyncio.create_task(
                self.retriever.retrieve(
                    sub_query,
                    adaptive_top_k,
                    alpha=alpha,
                    use_rerank=use_rerank,
                    filters=filters,
                )
            )

            web_search_task = None
            if use_web and enable_web_search:
                web_search_task = asyncio.create_task(
                    self._web_search(sub_query, self.MULTI_TOPIC_MAX_SNIPPETS)
                )

            # 等待检索完成
            sub_retrieval = await retrieval_task

            # 等待网络搜索完成（如果启用）
            web_docs = []
            if web_search_task:
                try:
                    web_docs = await web_search_task
                except WebSearchQuotaExceededError:
                    quota_state["web_quota_hit"] = True
                    self.logger.warning(f"Web search quota exceeded for topic '{sub_query}'")
                except Exception as exc:
                    self.logger.warning(f"Web search failed for topic '{sub_query}': {exc}")

            # 添加网络搜索结果到诊断信息
            if web_docs:
                sub_retrieval.diagnostics["web_hits"] = len(web_docs)

            return sub_query, sub_retrieval, web_docs

        # 并行执行所有主题的检索
        retrieval_tasks = [
            retrieve_single_topic(sub_query) for sub_query in sub_queries
        ]

        try:
            # 使用asyncio.gather并行执行
            retrievals = await asyncio.gather(*retrieval_tasks, return_exceptions=True)

            # 处理异常结果
            valid_retrievals = []
            topic_web_docs: Dict[str, List[Dict[str, Any]]] = {}
            for i, result in enumerate(retrievals):
                if isinstance(result, Exception):
                    self.logger.error(f"Topic retrieval {i} failed: {result}")
                    # 创建一个空的检索结果
                    from types import SimpleNamespace
                    empty_retrieval = SimpleNamespace(
                        results=[],
                        diagnostics={"error": str(result), "stage": "retrieval"}
                    )
                    topic_web_docs[sub_queries[i]] = []
                    valid_retrievals.append((sub_queries[i], empty_retrieval))
                else:
                    sub_query, retrieval_result, web_docs = result
                    topic_web_docs[sub_query] = web_docs or []
                    valid_retrievals.append((sub_query, retrieval_result))

            return valid_retrievals, topic_web_docs

        except Exception as exc:
            self.logger.error(f"Parallel multi-topic retrieval failed: {exc}")
            # 降级到串行执行
            return await self._fallback_serial_retrieval(
                sub_queries, adaptive_top_k, alpha, use_rerank, filters, use_web, enable_web_search, quota_state
            )

    async def _fallback_serial_retrieval(
        self,
        sub_queries: List[str],
        adaptive_top_k: int,
        alpha: Optional[float],
        use_rerank: Optional[bool],
        filters: Optional[Dict[str, Any]],
        use_web: bool,
        enable_web_search: bool,
        quota_state: Dict[str, bool],
    ) -> Tuple[List[Tuple[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        串行检索的后备方案

        Args:
            sub_queries: 子查询列表
            adaptive_top_k: 适应性的top_k值
            alpha: 混合权重
            use_rerank: 是否使用重排序
            filters: 过滤器
            use_web: 是否使用网络搜索
            needs_web_search: 是否需要网络搜索

        Returns:
            List[Tuple[str, Any]]: 检索结果列表
        """
        retrievals: List[Tuple[str, Any]] = []
        topic_web_docs: Dict[str, List[Dict[str, Any]]] = {}

        for sub_query in sub_queries:
            try:
                sub_retrieval = await self.retriever.retrieve(
                    sub_query,
                    adaptive_top_k,
                    alpha=alpha,
                    use_rerank=use_rerank,
                    filters=filters,
                )

                web_docs = []
                if use_web and enable_web_search:
                    try:
                        web_docs = await self._web_search(sub_query, self.MULTI_TOPIC_MAX_SNIPPETS) or []
                    except WebSearchQuotaExceededError:
                        quota_state["web_quota_hit"] = True
                        self.logger.warning(f"Web search quota exceeded for topic '{sub_query}'")
                        web_docs = []
                    except Exception as exc:
                        self.logger.warning(f"Web search failed for topic '{sub_query}': {exc}")

                if web_docs:
                    sub_retrieval.diagnostics["web_hits"] = len(web_docs)

                topic_web_docs[sub_query] = web_docs
                retrievals.append((sub_query, sub_retrieval))

            except Exception as exc:
                self.logger.error(f"Serial retrieval failed for '{sub_query}': {exc}")
                from types import SimpleNamespace
                empty_retrieval = SimpleNamespace(
                    results=[],
                    diagnostics={"error": str(exc), "stage": "retrieval"}
                )
                topic_web_docs[sub_query] = []
                retrievals.append((sub_query, empty_retrieval))

        return retrievals, topic_web_docs

    def _enhanced_multi_topic_deduplication(
        self,
        topic_docs: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        增强的多主题去重逻辑

        Args:
            topic_docs: 主题文档字典

        Returns:
            Dict[str, List[Dict[str, Any]]]: 去重后的主题文档
        """
        seen_docs = set()
        enhanced_topic_docs = {}

        for topic, docs in topic_docs.items():
            enhanced_docs = []
            for doc in docs:
                # 创建文档的唯一标识
                content = (doc.get("text") or doc.get("content", "")).strip()
                source = doc.get("source", doc.get("metadata", {}).get("source", ""))

                # 使用内容的前100字符 + 来源作为唯一标识
                doc_id = f"{content[:100]}_{source}"

                if doc_id not in seen_docs:
                    seen_docs.add(doc_id)
                    enhanced_docs.append(doc)

            enhanced_topic_docs[topic] = enhanced_docs

        return enhanced_topic_docs

    async def _smart_answer_fusion(
        self,
        topic_results: List[Tuple[str, Any, List[Dict[str, Any]]]],
        query: str,
        history: Optional[str]
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        智能答案融合

        Args:
            topic_results: 主题结果列表 (主题, 检索结果, 网络搜索结果)
            query: 原始查询
            history: 历史对话

        Returns:
            Tuple[str, List[Dict[str, Any]]]: (融合的答案, 引用列表)
        """
        if not topic_results:
            return "未找到相关内容。", []

        # 如果只有一个主题，使用标准的答案生成
        if len(topic_results) == 1:
            topic, retrieval, web_docs = topic_results[0]
            if retrieval.results:
                # 使用现有的结构化答案生成逻辑
                structured_answer, structured_citations = await self._generate_structured_answer(
                    query, retrieval.results
                )

                # 添加网络搜索结果
                if web_docs:
                    web_section, web_citations = self._build_web_highlights(web_docs)
                    if web_section:
                        structured_answer = structured_answer.rstrip() + "\n\n" + web_section
                    structured_citations.extend(web_citations)

                return structured_answer, structured_citations
            else:
                # 纯网络搜索结果
                if web_docs:
                    prepared = self._prepare_web_docs_for_structured_answer(web_docs)
                    topic_title = self._topic_with_web_suffix(topic or self._extract_main_topic(query))
                    structured_answer, web_citations = await self._generate_structured_answer(
                        query,
                        prepared,
                        topic_name=topic_title,
                    )
                    return structured_answer, web_citations
                else:
                    return "未找到相关信息。", []

        # 多主题智能融合
        fusion_prompt = self._build_fusion_prompt(topic_results, query)
        messages = self._build_messages_for_mode(fusion_prompt, "doc")
        fused_answer = await self._chat(messages, query=query, mode="doc")

        # 收集所有引用
        all_citations = []
        for _, retrieval, web_docs in topic_results:
            if retrieval.results:
                all_citations.extend(self._build_citations(retrieval.results))
            if web_docs:
                all_citations.extend(self._build_citations(web_docs))

        # 去重引用
        unique_citations = []
        seen = set()
        for citation in all_citations:
            key = (citation.get("source"), citation.get("page"), citation.get("snippet"))
            if key not in seen:
                seen.add(key)
                unique_citations.append(citation)

        return fused_answer, unique_citations

    def _build_fusion_prompt(
        self,
        topic_results: List[Tuple[str, Any, List[Dict[str, Any]]]],
        original_query: str
    ) -> str:
        """
        构建答案融合提示词

        Args:
            topic_results: 主题结果列表
            original_query: 原始查询

        Returns:
            str: 融合提示词
        """
        prompt_parts = [
            f"用户提出了一个复杂的多主题问题：{original_query}",
            "",
            "以下是为不同主题检索到的信息，请将其融合成一个连贯、完整的答案。",
            ""
        ]

        for i, (topic, retrieval, web_docs) in enumerate(topic_results, 1):
            prompt_parts.append(f"## 主题 {i}: {topic}")

            # 添加文档检索结果
            if retrieval.results:
                prompt_parts.append("### 文档信息:")
                for j, doc in enumerate(retrieval.results[:3], 1):
                    content = (doc.get("text") or doc.get("content", "")).strip()
                    source = doc.get("source", doc.get("metadata", {}).get("source", "未知"))
                    if content:
                        prompt_parts.append(f"{j}. [{source}] {content[:200]}...")

            # 添加网络搜索结果
            if web_docs:
                prompt_parts.append("### 网络信息:")
                for j, doc in enumerate(web_docs[:2], 1):
                    content = (doc.get("content") or doc.get("text", "")).strip()
                    title = doc.get("title", "来源")
                    if content:
                        prompt_parts.append(f"{j}. [{title}] {content[:150]}...")

            prompt_parts.append("")

        prompt_parts.extend([
            "## 融合要求:",
            "1. 将多个主题的信息有机整合，避免简单拼接",
            "2. 突出主题之间的关联性和逻辑性",
            "3. 提供结构化的答案，包含清晰的层次",
            "4. 如果存在矛盾信息，请指出并分析",
            "5. 确保回答的完整性和可读性",
            "",
            "请生成融合后的答案："
        ])

        return "\n".join(prompt_parts)
