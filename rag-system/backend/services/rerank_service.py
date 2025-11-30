from __future__ import annotations

import json
from typing import Any, Dict, List

from openai import AsyncOpenAI
import httpx

from ..config import settings
from ..utils.logger import get_logger


class RerankService:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.rerank_model
        self._client: AsyncOpenAI | None = None
        self._provider: str | None = None
        self.logger = get_logger(__name__)

        # 优先使用 OpenAI，其次专用 RERANK API，再到质谱原生、DeepSeek
        if settings.openai_api_key:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
            self._provider = "openai"
            # 如果当前模型显然不是 OpenAI 侧可用的（例如 glm*），自动回退到 chat 模型
            if model is None and (self.model.startswith("glm") or not self.model):
                self.model = settings.openai_chat_model
        elif settings.rerank_api_key:
            self._client = AsyncOpenAI(
                api_key=settings.rerank_api_key,
                base_url=settings.rerank_api_base_url or None,
            )
            self._provider = "custom"
        elif settings.zhipu_api_key:
            # 质谱原生接口（非 OpenAI 兼容）
            self._provider = "zhipu"
            if model is None and self.model == settings.rerank_model:
                self.model = settings.zhipu_chat_model
        elif settings.deepseek_api_key:
            self._client = AsyncOpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )
            self._provider = "deepseek"
            # 如果还在用 OpenAI 的默认模型名，切换到 DeepSeek 的默认模型
            if model is None and self.model == settings.rerank_model:
                self.model = settings.deepseek_chat_model

    async def rerank(self, query: str, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not docs:
            return docs
        if self._client is None and self._provider != "zhipu":
            return docs

        prompt = self._build_prompt(query, docs)
        content: str | None = None

        # OpenAI / DeepSeek / 自定义兼容接口
        if self._client is not None:
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a retriever reranker. Return a JSON object with a single key 'ranking' \n"
                                "that maps to an array of objects with 'chunk_id' and 'score' (0-1)."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                )
                content = response.choices[0].message.content if response.choices else None
            except Exception as exc:
                # 详细记录异常，便于定位 rerank 失败
                extra = {
                    "provider": self._provider or "unknown",
                    "model": self.model,
                    "error": str(exc),
                }
                # 尝试从异常中提取 HTTP 细节
                resp = getattr(exc, "response", None) or getattr(exc, "http_response", None)
                if resp is not None:
                    extra["status_code"] = getattr(resp, "status_code", None)
                    try:
                        extra["body"] = resp.text  # type: ignore[attr-defined]
                    except Exception:
                        pass
                self.logger.warning("rerank.request_failed", extra=extra)
                return docs

        # 质谱原生接口
        elif self._provider == "zhipu":
            url = settings.zhipu_api_base_url.rstrip("/") + "/chat/completions"
            headers = {"Authorization": f"Bearer {settings.zhipu_api_key}"}
            payload = {
                "model": self.model or settings.zhipu_chat_model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a retriever reranker. Return a JSON object with a single key 'ranking' \n"
                            "that maps to an array of objects with 'chunk_id' and 'score' (0-1)."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            }
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices")
                if choices:
                    content = choices[0].get("message", {}).get("content")
            except Exception as exc:
                self.logger.warning(
                    "rerank.request_failed",
                    extra={
                        "provider": "zhipu",
                        "model": self.model,
                        "status_code": getattr(resp, "status_code", None) if "resp" in locals() else None,
                        "body": getattr(resp, "text", None) if "resp" in locals() else None,
                        "error": str(exc),
                    },
                )
                return docs

        if not content:
            return docs

        try:
            payload = json.loads(content)
            ranking = payload.get("ranking", [])
        except json.JSONDecodeError:
            # 兼容非 JSON 输出：尝试从文本中解析 chunk_id 和 score
            ranking = []
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                if ":" in line:
                    parts = line.split(":", 1)
                else:
                    parts = line.split()
                if len(parts) < 2:
                    continue
                cid = parts[0].strip().strip(",")
                try:
                    val = float(parts[1].strip().strip(","))
                except ValueError:
                    continue
                ranking.append({"chunk_id": cid, "score": val})
            if not ranking:
                return docs

        score_map = {str(item.get("chunk_id")): float(item.get("score", 0.0)) for item in ranking}
        if not score_map:
            return docs

        def key_fn(doc: Dict[str, Any]) -> float:
            chunk_id = str(doc.get("chunk_id"))
            return score_map.get(chunk_id, doc.get("score", 0.0))

        reranked = sorted(docs, key=key_fn, reverse=True)
        updated: List[Dict[str, Any]] = []
        for doc in reranked:
            chunk_id = str(doc.get("chunk_id"))
            if chunk_id in score_map:
                new_score = score_map[chunk_id]
                metadata = {**(doc.get("metadata") or {})}
                metadata["score"] = new_score
                doc = {**doc, "score": new_score, "metadata": metadata}
            updated.append(doc)
        return updated

    def _build_prompt(self, query: str, docs: List[Dict[str, Any]]) -> str:
        lines = [
            f"Query: {query}",
            "\nDocuments:",
        ]
        for idx, doc in enumerate(docs, start=1):
            snippet = doc.get("text", "")[:1000]
            lines.append(
                json.dumps(
                    {
                        "index": idx,
                        "chunk_id": doc.get("chunk_id"),
                        "score": doc.get("score", 0.0),
                        "text": snippet,
                    },
                    ensure_ascii=False,
                )
            )
        lines.append(
            "Return a JSON object: {\"ranking\": [{\"chunk_id\": <id>, \"score\": <0-1 float>}, ...]} "
            "ordered from most to least relevant."
        )
        return "\n".join(lines)
