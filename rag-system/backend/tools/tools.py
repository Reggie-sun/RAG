from __future__ import annotations

import asyncio
from typing import ClassVar, List, Optional

from langchain_core.documents import Document
from langchain_core.tools import BaseTool
from pydantic import ConfigDict
from tavily import TavilyClient

from ..services.hybrid_retriever import HybridRetriever


class TavilyTool(BaseTool):
    name: ClassVar[str] = "WebSearch"
    description: ClassVar[str] = "联网搜索新闻/官网并返回简要摘要列表（用于强时效问题）"
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: TavilyClient
    max_results: int = 5

    def __init__(
        self,
        client: Optional[TavilyClient] = None,
        max_results: int = 5,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> None:
        if client is None:
            if not api_key:
                raise ValueError("TavilyTool requires a TavilyClient instance or an api_key.")
            client = TavilyClient(api_key=api_key)
        super().__init__(client=client, max_results=max_results, **kwargs)

    def _run(self, query: str) -> str:
        response = self.client.search(query=query, max_results=self.max_results)
        hits = response.get("results", [])[: self.max_results]
        if not hits:
            return "No web results."
        lines = []
        for hit in hits:
            title = hit.get("title", "").strip()
            url = hit.get("url", "").strip()
            snippet = hit.get("content", "").strip()
            entry = f"- {title} | {url}"
            if snippet:
                entry += f"\n  {snippet[:200]}"
            lines.append(entry)
        return "Web results:\n" + "\n".join(lines)

    async def _arun(self, query: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run, query)


class DocSearchTool(BaseTool):
    name: ClassVar[str] = "DocSearch"
    description: ClassVar[str] = "在上传的文档库中进行混合检索（向量+BM25），返回相关片段"
    model_config = ConfigDict(arbitrary_types_allowed=True)

    retriever: HybridRetriever
    k: int = 5

    def __init__(self, retriever: HybridRetriever, k: int = 5, **kwargs) -> None:
        super().__init__(retriever=retriever, k=k, **kwargs)

    def _run(self, query: str) -> str:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.retriever.retrieve(query=query, top_k=self.k))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        docs: List[Document] = [
            Document(page_content=item.get("text", ""), metadata=item.get("metadata", {}))
            for item in result.results
        ]
        if not docs:
            return "No doc hits."

        lines = []
        for idx, doc in enumerate(docs[: self.k], start=1):
            metadata = doc.metadata or {}
            src = metadata.get("source", metadata.get("filename", "unknown"))
            page = metadata.get("page")
            prefix = f"[{idx}] 《{src}》" + (f" P.{page}" if page is not None else "")
            lines.append(f"{prefix}\n{doc.page_content[:500]}")
        return "\n\n".join(lines)

    async def _arun(self, query: str) -> str:
        result = await self.retriever.retrieve(query=query, top_k=self.k)
        docs: List[Document] = [
            Document(page_content=item.get("text", ""), metadata=item.get("metadata", {}))
            for item in result.results
        ]
        if not docs:
            return "No doc hits."

        lines = []
        for idx, doc in enumerate(docs[: self.k], start=1):
            metadata = doc.metadata or {}
            src = metadata.get("source", metadata.get("filename", "unknown"))
            page = metadata.get("page")
            prefix = f"[{idx}] 《{src}》" + (f" P.{page}" if page is not None else "")
            lines.append(f"{prefix}\n{doc.page_content[:500]}")
        return "\n\n".join(lines)
