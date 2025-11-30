from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import asyncio
import os
import re

for _var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_var, None)

from ollama import AsyncClient, Client

from ..config import settings
from .prompt_utils import (
    build_doc_prompt,
    build_general_prompt,
    is_doc_mode,
    select_top_documents,
)
from .intent_classifier import has_doc_hint
from .hybrid_retriever import HybridRetriever
from ..utils.logger import get_logger


class RAGService:
    OFF_TOPIC_SCORE_THRESHOLD = 0.60
    OFF_TOPIC_OVERLAP_THRESHOLD = 0.40

    MULTI_TOPIC_MAX_SNIPPETS = 3
    MULTI_TOPIC_MAX_TOPICS = 6
    MULTI_TOPIC_MAX_CITATIONS = 3

    def __init__(self, retriever: HybridRetriever) -> None:
        self.retriever = retriever
        Client(proxy=None)
        self.debug_router = os.getenv("DEBUG_ROUTER", "false").lower() in {"1", "true", "yes"}
        self.logger = get_logger(__name__)

    async def answer(
        self,
        query: str,
        top_k: int,
        alpha: Optional[float] = None,
        use_rerank: Optional[bool] = None,
        filters: Optional[Dict[str, Any]] = None,
        history: Optional[str] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        sub_queries, truncated, original_topic_count = await self._intelligent_decompose_query(query)
        multi_topic = len(sub_queries) > 1
        has_feedback = bool(feedback and feedback.strip())

        retrieval = None
        retrievals: List[Tuple[str, Any]] = []
        diagnostics: Dict[str, Any] = {}

        if multi_topic:
            # 动态TopK：多主题时每个子查询使用较小的top_k
            adaptive_top_k = max(3, min(top_k // len(sub_queries), 8))

            for sub_query in sub_queries:
                sub_retrieval = await self.retriever.retrieve(
                    sub_query,
                    adaptive_top_k,
                    alpha=alpha,
                    use_rerank=use_rerank,
                    filters=filters,
                )
                retrievals.append((sub_query, sub_retrieval))
            diagnostics = {
                sub_query: sub_ret.diagnostics for sub_query, sub_ret in retrievals
            }
        else:
            retrieval = await self.retriever.retrieve(
                query,
                top_k,
                alpha=alpha,
                use_rerank=use_rerank,
                filters=filters,
            )
            retrievals.append((query, retrieval))
            diagnostics = retrieval.diagnostics

        if multi_topic:
            topic_docs = self._prepare_multi_topic_docs(retrievals)
            if topic_docs:
                answer, citations = await self._compose_multi_topic_answer(
                    sub_queries,
                    original_topic_count,
                    topic_docs,
                    history,
                    truncated,
                    feedback=feedback,
                )
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
                suggestions = self._general_suggestions()
                return {
                    "answer": answer,
                    "mode": "doc" if citations else "general",
                    "citations": citations,
                    "suggestions": suggestions,
                    "sources": [doc for docs in topic_docs.values() for doc in docs],
                    "diagnostics": diagnostics,
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
        top_docs = top_docs[: settings.doc_answer_max_snippets]
        if not top_docs:
            return await self.answer_general(
                query,
                history,
                sources=retrieval.results,
                diagnostics=retrieval.diagnostics,
                feedback=feedback,
            )

        # 使用新的结构化答案生成方法
        structured_answer, structured_citations = await self._generate_structured_answer(query, top_docs)

        # 如果生成了结构化答案，使用它；否则回退到原有逻辑
        if structured_answer and structured_citations and not has_feedback:
            suggestions = self._general_suggestions()
            return {
                "answer": structured_answer,
                "mode": "doc",
                "citations": structured_citations,
                "suggestions": suggestions,
                "sources": top_docs,
                "diagnostics": retrieval.diagnostics,
            }

        doc_hint = has_doc_hint(query)
        overlap = self._token_overlap_ratio(query, top_docs)
        score_threshold = max(self.OFF_TOPIC_SCORE_THRESHOLD, settings.doc_answer_threshold)
        if not doc_hint and (
            top_score < score_threshold or overlap < self.OFF_TOPIC_OVERLAP_THRESHOLD
        ):
            return await self.answer_general(
                query,
                history,
                sources=retrieval.results,
                diagnostics=retrieval.diagnostics,
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
        return {
            "answer": answer,
            "mode": mode,
            "citations": citations,
            "suggestions": suggestions,
            "sources": retrieval.results,
            "diagnostics": diagnostics,
        }

    async def answer_general(
        self,
        query: str,
        history: Optional[str] = None,
        *,
        sources: Optional[List[Dict[str, Any]]] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt_core = build_general_prompt(query, feedback=feedback)
        prompt = self._compose_prompt(history, prompt_core, "general")
        messages = self._build_messages_for_mode(prompt, "general")
        answer = await self._chat(messages, query=query, mode="general")
        if "[非文档知识]" not in answer:
            answer = "[非文档知识]\n" + answer
        return {
            "answer": answer,
            "mode": "general",
            "citations": [],
            "suggestions": self._general_suggestions(),
            "sources": sources or [],
            "diagnostics": diagnostics or {},
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
            client = AsyncClient(host=settings.ollama_base_url, proxy=None)
            try:
                # Ensure starting the stream does not hang indefinitely
                try:
                    stream = await asyncio.wait_for(
                        client.chat(
                            model=settings.ollama_model,
                            messages=self._build_stream_messages(query, context),
                            options=self._ollama_options(),
                            stream=True,
                        ),
                        timeout=settings.ollama_timeout,
                    )
                except asyncio.TimeoutError:
                    return  # abort streaming silently on startup timeout

                # Read chunks with an idle timeout to prevent hangs mid-stream
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            stream.__anext__(), timeout=settings.ollama_timeout
                        )
                    except asyncio.TimeoutError:
                        break  # stop on idle timeout
                    except StopAsyncIteration:
                        break  # normal end of stream
                    except Exception:
                        break  # defensive: terminate on unexpected failure

                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
            finally:
                await client._client.aclose()

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

        def _src(item: Dict[str, Any]) -> str:
            metadata = item.get("metadata", {}) or {}
            return metadata.get("source") or item.get("source") or "unknown"

        def _score(item: Dict[str, Any]) -> float:
            metadata = item.get("metadata", {}) or {}
            raw = item.get("score", metadata.get("score", 0.0))
            try:
                return float(raw or 0.0)
            except (TypeError, ValueError):
                return 0.0

        picked_sources = {_src(item) for item in picked}
        if len(picked_sources) >= need_sources:
            return picked

        if not results:
            return picked

        top_score = _score(picked[0])
        score_floor = max(settings.doc_answer_threshold * 0.8, (top_score or 0.0) * 0.6)

        used = {id(x) for x in picked}
        for item in results:
            if id(item) in used:
                continue
            if _score(item) < score_floor:
                continue
            source = _src(item)
            if source in picked_sources:
                continue
            picked.append(item)
            picked_sources.add(source)
            if len(picked_sources) >= need_sources:
                break

        return picked

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

    def _build_citations(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        citations: List[Dict[str, Any]] = []
        for doc in docs:
            metadata = doc.get("metadata", {}) or {}
            page = metadata.get("page")
            try:
                page_value = int(page)
            except (TypeError, ValueError):
                page_value = None
            snippet = self._clean_snippet(doc.get("text") or metadata.get("text") or "")
            citation = {
                "source": metadata.get("source") or doc.get("source"),
                "page": page_value,
                "snippet": snippet[:240],
                "score": float(metadata.get("score", doc.get("score", 0.0)) or 0.0),
            }
            citations.append(citation)
        return citations

    async def _intelligent_decompose_query(self, query: str) -> Tuple[List[str], bool, int]:
        """使用LLM智能分解查询，如果LLM不可用则回退到基础分解"""
        # 首先尝试基础分解
        basic_queries, truncated, original_topic_count = self._basic_decompose_query(query)

        # 如果只有一个查询或查询太短，直接返回
        if len(basic_queries) <= 1 or len(query.strip()) < 20:
            return basic_queries, truncated, original_topic_count

        try:
            # 使用LLM判断是否需要进一步分解
            client = AsyncClient(host=settings.ollama_base_url, proxy=None)
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

注意：最多分解为3个子查询，确保每个子查询主题单一明确。"""

            try:
                response = await asyncio.wait_for(
                    client.chat(
                        model=settings.ollama_model,
                        messages=[{"role": "user", "content": prompt}],
                        options={"temperature": 0.1, "num_predict": 200},
                        stream=False,
                    ),
                    timeout=5.0
                )

                llm_response = response.get("message", {}).get("content", "").strip()
                await client._client.aclose()

                # 解析LLM响应
                if llm_response.startswith("单一主题:"):
                    # LLM认为只有一个主题
                    single_query = llm_response.replace("单一主题:", "").strip()
                    return [single_query], False, 1
                else:
                    # 解析多个子查询
                    sub_queries = []
                    for line in llm_response.split('\n'):
                        line = line.strip()
                        if line.startswith('子查询') and ':' in line:
                            query_part = line.split(':', 1)[1].strip()
                            if query_part:
                                sub_queries.append(query_part)

                    if len(sub_queries) > 1:
                        # 限制子查询数量
                        sub_queries = sub_queries[:3]
                        return sub_queries, len(sub_queries) > self.MULTI_TOPIC_MAX_TOPICS, len(sub_queries)

            except (asyncio.TimeoutError, Exception) as e:
                self.logger.warning(f"LLM query decomposition failed: {e}")
                await client._client.aclose()

        except Exception as e:
            self.logger.warning(f"LLM decomposition error: {e}")

        # 回退到基础分解
        return basic_queries, truncated, original_topic_count

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
    ) -> str:
        if not topic_docs:
            return build_general_prompt("\n".join(topics))

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
    ) -> Tuple[str, List[Dict[str, Any]]]:
        sections: List[str] = []
        combined_citations: List[Dict[str, Any]] = []

        if truncated:
            limit = min(original_topic_count, self.MULTI_TOPIC_MAX_TOPICS)
            sections.append(f"> 提示：输入包含 {original_topic_count} 个主题，已精简至 {limit} 个。")

        if feedback:
            cleaned = [line.strip() for line in feedback.strip().splitlines() if line.strip()]
            if cleaned:
                formatted = "\n".join(f"> {line}" for line in cleaned)
                sections.append(
                    "\n".join(
                        [
                            "> 用户反馈：",
                            formatted,
                            "> 请针对上述问题改进以下各主题的回答。",
                        ]
                    )
                )

        for idx, topic in enumerate(topics, start=1):
            docs = topic_docs.get(topic, [])
            if not docs:
                sections.append("\n\n".join([
                    f"### 主题{idx}：{topic}",
                    "未检索到可靠来源。",
                    "",
                    "来源:",
                    "- 未检索到可靠来源",
                ]))
                continue

            summary = await self._summarize_topic(
                topic,
                docs,
                history,
                idx,
                feedback=feedback,
            )
            sources_md, citations = self._format_sources(idx, docs)
            combined_citations.extend(citations)
            section = "\n".join([
                f"### 主题{idx}：{topic}",
                summary.strip(),
                "",
                "来源:",
                sources_md,
            ])
            sections.append(section)

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

    async def _summarize_topic(
        self,
        topic: str,
        docs: List[Dict[str, Any]],
        history: Optional[str],
        topic_index: int,
        *,
        feedback: Optional[str] = None,
    ) -> str:
        prompt_lines: List[str] = []
        for doc_idx, doc in enumerate(docs[: self.MULTI_TOPIC_MAX_SNIPPETS * 2], start=1):
            metadata = doc.get("metadata", {}) or {}
            title = metadata.get("source") or doc.get("source") or "Unknown"
            page = metadata.get("page")
            header = f"[{topic_index}.{doc_idx}] {title}"
            if page not in (None, ""):
                header += f" (P.{page})"
            text_segment = str(doc.get("text") or metadata.get("text") or "")[:800]
            prompt_lines.append(f"{header}\n{text_segment}")

        context = "\n\n".join(prompt_lines)
        feedback_block = ""
        if feedback:
            cleaned = "\n".join(line.strip() for line in feedback.strip().splitlines() if line.strip())
            if cleaned:
                feedback_block = (
                    "用户反馈上一轮回答存在以下不足，请在本主题回答中重点改进：\n"
                    f"{cleaned}\n"
                    "务必补充缺失信息并避免重复错误。\n\n"
                )

        prompt = (
            "请根据以下文档片段撰写详尽总结。使用 Markdown 编号列表输出 4-6 条要点，"
            "每条至少 2 句话，阐述背景、结论与可能的影响或注意事项；务必引用相关编号并避免臆造或引用文档以外的内容。\n"
            f"{feedback_block}"
            f"主题：{topic}\n\n文档片段：\n{context}"
        )
        messages = self._build_messages_for_mode(prompt, "doc")
        summary = await self._chat(messages, query=topic, mode="doc")
        return summary

    def _format_sources(
        self,
        topic_index: int,
        docs: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        lines: List[str] = []
        citations: List[Dict[str, Any]] = []
        for doc_idx, doc in enumerate(docs[: self.MULTI_TOPIC_MAX_CITATIONS], start=1):
            metadata = doc.get("metadata", {}) or {}
            title = metadata.get("source") or doc.get("source") or "Unknown"
            page = metadata.get("page")
            ref = f"[{topic_index}.{doc_idx}] {title}"
            if page not in (None, ""):
                ref += f" (P.{page})"
            lines.append(f"- {ref}")

            snippet = self._clean_snippet(doc.get("text") or metadata.get("text") or "")[:240]
            try:
                page_value = int(page)
            except (TypeError, ValueError):
                page_value = None
            citations.append(
                {
                    "source": title,
                    "page": page_value,
                    "snippet": snippet,
                    "score": float(metadata.get("score", doc.get("score", 0.0)) or 0.0),
                }
            )
        if not lines:
            lines.append("- 未检索到可靠来源")
        return "\n".join(lines), citations

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
                snippet = self._clean_snippet(doc.get("text") or metadata.get("text") or "")[:240]
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
        client = AsyncClient(host=settings.ollama_base_url, proxy=None)
        try:
            response = await asyncio.wait_for(
                client.chat(
                    model=settings.ollama_model,
                    messages=messages,
                    options=self._ollama_options(),
                ),
                timeout=settings.ollama_timeout,
            )
        except asyncio.TimeoutError:
            if fallback:
                return fallback
            if mode == "doc":
                message = (
                    "[非文档知识]\n"
                    "生成基于文档的回答超时，暂无法引用具体来源。\n"
                    f"问题：{query}\n"
                    "建议稍后重试，或让我以常识模式回答该问题。"
                )
            else:
                message = (
                    "[非文档知识]\n"
                    "回答生成超时，我根据常识给出简要建议：\n"
                    "- 请稍后重试或让我联网检索权威信息。\n"
                    "- 也可以补充更多上下文，以便提供更精准的建议。"
                )
            return message
        except Exception as exc:
            logger = get_logger(__name__)
            logger.exception(
                "llm.failure",
                extra={
                    "query": query,
                    "mode": mode,
                    "exc": type(exc).__name__,
                },
            )
            if fallback:
                return fallback
            return (
                "[非文档知识]\n"
                "调用本地模型时发生错误，暂无法生成引用答案。\n"
                "建议稍后重试或检查 Ollama 服务状况。"
            )
        finally:
            await client._client.aclose()
        return response.get("message", {}).get("content", "").strip()

    def _general_suggestions(self) -> List[str]:
        return [
            "限定问题范围，例如：请只依据上传文档回答",
            "如果需要最新数据，可以让我联网检索权威来源",
            "补充时间、对象、指标等背景信息，以便精确检索",
        ]

    def _token_overlap_ratio(self, query: str, docs: List[Dict[str, Any]]) -> float:
        q_tokens = set(re.findall(r"[\u4e00-\u9fa5]|[A-Za-z0-9_]+", query or ""))
        if not q_tokens:
            return 0.0
        snippet_text = " ".join(
            (doc.get("text") or (doc.get("metadata", {}) or {}).get("text") or "")[:600]
            for doc in docs
        )
        d_tokens = set(re.findall(r"[\u4e00-\u9fa5]|[A-Za-z0-9_]+", snippet_text))
        if not d_tokens:
            return 0.0
        inter = len(q_tokens & d_tokens)
        return inter / max(len(q_tokens), 1)

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

    async def _generate_structured_answer(
        self,
        query: str,
        docs: List[Dict[str, Any]],
        topic_name: Optional[str] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        使用 LLM 生成结构化答案，避免直接拼接原文导致的乱码或断句问题。
        """
        if not docs:
            topic = topic_name or self._extract_main_topic(query)
            return f"### 主题：{topic}\n\n未检索到可引用的文档内容。", []

        topic = topic_name or self._extract_main_topic(query)
        context_blocks: List[str] = []
        for idx, doc in enumerate(docs, start=1):
            metadata = doc.get("metadata", {}) or {}
            source = metadata.get("source") or doc.get("source") or f"Doc-{idx}"
            page = metadata.get("page")
            snippet = self._clean_snippet(doc.get("text") or metadata.get("text") or "")
            if not snippet:
                continue
            header = f"[{idx}] {source}"
            if page not in (None, ""):
                header += f" (P.{page})"
            context_blocks.append(f"{header}\n{snippet[:800]}")

        if not context_blocks:
            topic = topic_name or self._extract_main_topic(query)
            return f"### 主题：{topic}\n\n未检索到可引用的文档内容。", []

        context = "\n\n".join(context_blocks)
        template = (
            "请严格根据下方文档片段回答，并使用以下结构输出：\n"
            "### 主题：{topic}\n"
            "#### 一、定义 / 背景说明\n"
            "- …\n"
            "#### 二、关键内容 / 原理 / 步骤\n"
            "- …（引用 [编号]）\n"
            "#### 三、典型示例 / 适用场景（没有可写“未在文档中找到”）\n"
            "#### 四、注意事项 / 建议\n"
            "- …\n"
            "来源:\n"
            "- 列出使用到的文档标题与页码\n\n"
            "要求：\n"
            "1. 只能使用提供的文档信息，禁止扩写常识。\n"
            "2. 每条事实句在末尾标注引用编号（如 [1]、[2]），编号与文档片段顺序一致。\n"
            "3. 若某部分没有对应内容，请明确说明“未在文档中找到”。\n"
        ).format(topic=topic)

        prompt = (
            f"{template}\n"
            f"用户问题：{query}\n\n"
            f"文档片段：\n{context}\n"
        )

        messages = [
            {
                "role": "system",
                "content": "你是企业知识库助手，只能根据提供的文档片段回答，需输出结构化 Markdown 并给出明确引用。",
            },
            {"role": "user", "content": prompt},
        ]

        answer = await self._chat(messages, query=query, mode="doc")
        citations = self._build_citations(docs)
        return answer, citations

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

    def _format_citation(self, doc: Dict[str, Any]) -> str:
        """格式化引用标注"""
        metadata = doc.get("metadata", {}) or {}
        source = metadata.get('source') or doc.get('source', 'unknown')
        page = metadata.get('page', doc.get('page', 1))

        # 简化文件名
        if source.endswith('.docx'):
            source = source.replace('.docx', '')
        elif source.endswith('.pdf'):
            source = source.replace('.pdf', '')
        elif source.endswith('.odt'):
            source = source.replace('.odt', '')

        return f"【{source}†P{page}】"

    def _clean_snippet(self, text: str) -> str:
        """移除控制字符与异常前缀，避免展示乱码。"""
        cleaned = text.replace("\u200b", " ").replace("\ufeff", " ").replace("\u00a0", " ")
        cleaned = re.sub(r"[\r\n]+", " ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"^[`'\"＂＇、，,。．·…:：;；\\s]+", "", cleaned)
        cleaned = re.sub(r"^[^\w\u4e00-\u9fff]+", "", cleaned)
        return cleaned.strip()
