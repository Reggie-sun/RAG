from __future__ import annotations

import json
from typing import Any, Dict, List

from openai import AsyncOpenAI

from ..config import settings


class RerankService:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.rerank_model
        self._client: AsyncOpenAI | None = None
        if settings.openai_api_key:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def rerank(self, query: str, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not docs or self._client is None:
            return docs

        prompt = self._build_prompt(query, docs)
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
        except Exception:
            return docs

        content = response.choices[0].message.content if response.choices else None
        if not content:
            return docs

        try:
            payload = json.loads(content)
            ranking = payload.get("ranking", [])
        except json.JSONDecodeError:
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
