from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ollama import AsyncClient

try:
    from ..config import settings
    from ..utils.logger import get_logger
except ImportError:  # pragma: no cover - allow `services.*` imports
    from backend.config import settings  # type: ignore
    from backend.utils.logger import get_logger  # type: ignore

DOC_HINT_PATTERN = re.compile(
    r"(这[篇份个]?)(文档|材料|报告|记录|ppt|pdf)|附录|章节|表\s*\d+|第\s*\d+\s*(章|节|页)",
    re.IGNORECASE,
)
TIME_SENSITIVE_PATTERN = re.compile(
    r"(最新|实时|当前|今年|本周|今日|刚刚|price|行情|news|update|现在|near-term|当月)",
    re.IGNORECASE,
)
COMPARISON_PATTERN = re.compile(r"(对比|相比|区别|差异|优缺点|vs\.?|versus)", re.IGNORECASE)
HOWTO_PATTERN = re.compile(r"(如何|怎么|怎样|步骤|流程|操作|guide|教程)", re.IGNORECASE)
DECISION_PATTERN = re.compile(r"(是否|要不要|值得|建议|方案|策略)", re.IGNORECASE)
MULTI_TOPIC_SPLIT = re.compile(r"[\n。；;！？?!、]|(?:\s+and\s+)|(?:\s+or\s+)")

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


class QuestionType(Enum):
    FACT = "fact"
    HOW_TO = "how_to"
    COMPARISON = "comparison"
    DECISION = "decision"
    GENERAL = "general"


class AnsweringMode(Enum):
    DOCUMENT_FIRST = "document_first"
    HYBRID = "hybrid"
    GENERAL_ONLY = "general_only"


@dataclass
class IntentAnalysisResult:
    query: str
    question_type: QuestionType
    answering_mode: AnsweringMode
    requires_web_search: bool
    confidence: float
    time_sensitivity: float
    complexity_score: float
    rationale: str = ""
    tokens: List[str] = field(default_factory=list)
    raw_topics: List[str] = field(default_factory=list)


class EnhancedIntentClassifier:
    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self._timeout = min(settings.intent_llm_timeout, settings.ollama_timeout)
        self._model = settings.ollama_model
        self._max_prompt_chars = 640

    async def analyze_intent(self, query: str) -> IntentAnalysisResult:
        normalized_query = self._normalize_query(query)
        heuristic = self._heuristic_pass(normalized_query)
        if heuristic.confidence >= 0.82 or len(normalized_query) < settings.intent_multi_topic_length:
            return heuristic

        try:
            llm_result = await self._llm_refine(normalized_query)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            self.logger.warning("intent.llm.unexpected_error", extra={"error": str(exc)})
            return heuristic

        if not llm_result:
            return heuristic

        return self._merge_results(heuristic, llm_result)

    def _heuristic_pass(self, query: str) -> IntentAnalysisResult:
        text = (query or "").strip()
        lowered = text.lower()
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text)

        doc_bias = 0.0
        if DOC_HINT_PATTERN.search(text):
            doc_bias += 0.5
        if ".pdf" in lowered or ".ppt" in lowered or "附件" in text:
            doc_bias += 0.25
        if len(text) > 120:
            doc_bias += 0.1

        time_sensitivity = 0.0
        for match in TIME_SENSITIVE_PATTERN.finditer(text):
            time_sensitivity += 0.25
        time_sensitivity = min(1.0, time_sensitivity)

        question_type = QuestionType.GENERAL
        if HOWTO_PATTERN.search(text):
            question_type = QuestionType.HOW_TO
        elif COMPARISON_PATTERN.search(text):
            question_type = QuestionType.COMPARISON
        elif DECISION_PATTERN.search(text):
            question_type = QuestionType.DECISION
        elif tokens and tokens[0] in {"what", "why", "who", "when"}:
            question_type = QuestionType.FACT

        complexity_score = min(1.0, max(0.1, len(tokens) / 80.0))
        topics = self._split_topics(text)
        if len(topics) > 1:
            complexity_score = max(complexity_score, 0.7)

        requires_web = time_sensitivity >= 0.5
        answering_mode = AnsweringMode.DOCUMENT_FIRST if doc_bias >= 0.45 else AnsweringMode.GENERAL_ONLY
        if requires_web or (0.2 < doc_bias < 0.45):
            answering_mode = AnsweringMode.HYBRID

        confidence = min(0.95, 0.55 + max(doc_bias, time_sensitivity) + complexity_score * 0.2)

        return IntentAnalysisResult(
            query=text,
            question_type=question_type,
            answering_mode=answering_mode,
            requires_web_search=requires_web,
            confidence=confidence,
            time_sensitivity=time_sensitivity,
            complexity_score=complexity_score,
            rationale="heuristic",
            tokens=tokens[:32],
            raw_topics=topics,
        )

    async def _llm_refine(self, query: str) -> Optional[IntentAnalysisResult]:
        prompt = self._build_llm_prompt(query)

        try:
            async with self._ollama_client() as client:
                task = asyncio.create_task(
                    client.chat(
                        model=self._model,
                        messages=[{"role": "user", "content": prompt}],
                        options={"temperature": 0, "num_predict": 256},
                        stream=False,
                    )
                )
                response = await asyncio.wait_for(task, timeout=self._timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None
        except Exception as exc:  # pragma: no cover - network faults
            self.logger.debug("intent.llm.error", extra={"error": str(exc)})
            return None

        content = response.get("message", {}).get("content", "").strip()
        blob = self._extract_json(content)
        if not blob:
            return None
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            return None

        q_type = self._map_question_type(data.get("question_type"))
        mode = self._map_answering_mode(data.get("answering_mode"))
        requires_web = bool(data.get("requires_web_search"))
        time_sensitivity = self._clamp_float(data.get("time_sensitivity"))
        complexity = self._clamp_float(data.get("complexity"))
        topics = self._sanitize_topics(data.get("topics"))

        confidence = 0.78 if mode == AnsweringMode.DOCUMENT_FIRST else 0.74

        return IntentAnalysisResult(
            query=query,
            question_type=q_type,
            answering_mode=mode,
            requires_web_search=requires_web,
            confidence=confidence,
            time_sensitivity=max(0.0, min(1.0, time_sensitivity)),
            complexity_score=max(0.0, min(1.0, complexity)),
            rationale=data.get("reason", "llm"),
            raw_topics=topics[:3],
        )

    def _merge_results(
        self,
        heuristic: IntentAnalysisResult,
        refined: IntentAnalysisResult,
    ) -> IntentAnalysisResult:
        requires_web = heuristic.requires_web_search or refined.requires_web_search
        answering_mode = refined.answering_mode
        if answering_mode == AnsweringMode.GENERAL_ONLY and heuristic.answering_mode == AnsweringMode.DOCUMENT_FIRST:
            answering_mode = AnsweringMode.HYBRID

        return IntentAnalysisResult(
            query=heuristic.query,
            question_type=refined.question_type or heuristic.question_type,
            answering_mode=answering_mode,
            requires_web_search=requires_web,
            confidence=max(heuristic.confidence, refined.confidence),
            time_sensitivity=max(heuristic.time_sensitivity, refined.time_sensitivity),
            complexity_score=max(heuristic.complexity_score, refined.complexity_score),
            rationale=f"{heuristic.rationale}+{refined.rationale}",
            tokens=heuristic.tokens,
            raw_topics=refined.raw_topics or heuristic.raw_topics,
        )

    def _split_topics(self, text: str) -> List[str]:
        parts = [frag.strip() for frag in MULTI_TOPIC_SPLIT.split(text) if frag.strip()]
        return parts[:3]

    def _map_question_type(self, value: Optional[str]) -> QuestionType:
        mapping = {
            "how_to": QuestionType.HOW_TO,
            "comparison": QuestionType.COMPARISON,
            "decision": QuestionType.DECISION,
            "fact": QuestionType.FACT,
            "general": QuestionType.GENERAL,
        }
        if not value:
            return QuestionType.GENERAL
        return mapping.get(value.lower(), QuestionType.GENERAL)

    def _map_answering_mode(self, value: Optional[str]) -> AnsweringMode:
        mapping = {
            "document_first": AnsweringMode.DOCUMENT_FIRST,
            "hybrid": AnsweringMode.HYBRID,
            "general_only": AnsweringMode.GENERAL_ONLY,
        }
        if not value:
            return AnsweringMode.HYBRID
        return mapping.get(value.lower(), AnsweringMode.HYBRID)

    @asynccontextmanager
    async def _ollama_client(self) -> AsyncClient:
        client = AsyncClient(host=settings.ollama_base_url, proxy=None)
        try:
            yield client
        finally:
            with suppress(Exception):
                await self._close_client(client)

    def _extract_json(self, text: str) -> Optional[str]:
        if not text:
            return None
        candidate = text.strip()
        fence_match = JSON_FENCE_RE.search(candidate)
        if fence_match:
            candidate = fence_match.group(1).strip()
        start = candidate.find("{")
        if start == -1:
            return None
        depth = 0
        for idx in range(start, len(candidate)):
            char = candidate[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return candidate[start : idx + 1]
        return None

    def _normalize_query(self, query: Any) -> str:
        if isinstance(query, str):
            text = query
        else:
            text = str(query or "")
        compact = text.strip()
        if len(compact) > self._max_prompt_chars:
            compact = compact[: self._max_prompt_chars].rstrip()
        return compact

    def _build_llm_prompt(self, query: str) -> str:
        safe_query = json.dumps(query, ensure_ascii=False)
        sample = json.dumps(
            {
                "question_type": "fact",
                "answering_mode": "document_first",
                "requires_web_search": False,
                "time_sensitivity": 0.3,
                "complexity": 0.4,
                "reason": "简要说明推理",
                "topics": ["主题A", "主题B"],
            },
            ensure_ascii=False,
        )
        return (
            "请分析以下问题并以 JSON 返回，字段包括 question_type、answering_mode、requires_web_search、"
            "time_sensitivity、complexity、reason、topics。"
            "\n- question_type: fact/how_to/comparison/decision/general"
            "\n- answering_mode: document_first/hybrid/general_only"
            "\n- requires_web_search: true/false"
            "\n- time_sensitivity、complexity: 0到1之间的小数"
            f"\n问题：{safe_query}\n"
            f"仅输出一个 JSON 对象，例如：{sample}\n"
            "不要添加额外文字或解释。"
        )

    def _clamp_float(self, value: Any, minimum: float = 0.0, maximum: float = 1.0) -> float:
        try:
            numeric = float(value or 0.0)
        except (TypeError, ValueError):
            numeric = 0.0
        return max(minimum, min(maximum, numeric))

    def _sanitize_topics(self, payload: Any) -> List[str]:
        if not isinstance(payload, list):
            return []
        cleaned: List[str] = []
        for item in payload:
            if not isinstance(item, str):
                continue
            candidate = item.strip()
            if candidate:
                cleaned.append(candidate[:80])
            if len(cleaned) >= 3:
                break
        return cleaned

    async def _close_client(self, client: AsyncClient) -> None:
        close = getattr(client, "aclose", None)
        if callable(close):
            await close()
            return
        inner = getattr(client, "_client", None)
        if inner is not None:
            await inner.aclose()


enhanced_classifier = EnhancedIntentClassifier()
