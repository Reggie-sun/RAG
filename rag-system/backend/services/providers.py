from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from ..config import settings

if TYPE_CHECKING:
    from .hybrid_retriever import HybridRetriever
    from .ingest_service import IngestService
    from .rag_service import RAGService
    from .rerank_service import RerankService
    from .vector_service import VectorService
    from .web_search_service import WebSearchService
    from .enhanced_intent_classifier import EnhancedIntentClassifier
    from .feishu_client import FeishuClient
    from .wechat_crypto import WeChatCrypto
    from .wechat_crypto import WeChatCrypto


@lru_cache(maxsize=1)
def get_vector_service() -> VectorService:
    from .vector_service import VectorService

    return VectorService()


@lru_cache(maxsize=1)
def get_rerank_service() -> RerankService:
    from .rerank_service import RerankService

    return RerankService()


@lru_cache(maxsize=1)
def get_hybrid_retriever() -> HybridRetriever:
    from .hybrid_retriever import HybridRetriever

    return HybridRetriever(get_vector_service(), get_rerank_service())


@lru_cache(maxsize=1)
def get_ingest_service() -> IngestService:
    from .ingest_service import IngestService

    return IngestService(get_vector_service())


@lru_cache(maxsize=1)
def get_rag_service() -> RAGService:
    from .rag_service import RAGService

    return RAGService(
        get_hybrid_retriever(),
        web_search=get_web_search_service(),
        intent_classifier=get_intent_classifier(),
    )


@lru_cache(maxsize=1)
def get_web_search_service() -> WebSearchService:
    from .web_search_service import WebSearchService

    return WebSearchService()


@lru_cache(maxsize=1)
def get_intent_classifier() -> EnhancedIntentClassifier:
    from .enhanced_intent_classifier import EnhancedIntentClassifier, enhanced_classifier
    if isinstance(enhanced_classifier, EnhancedIntentClassifier):
        return enhanced_classifier
    return EnhancedIntentClassifier()


@lru_cache(maxsize=1)
def get_feishu_client() -> "FeishuClient":
    from .feishu_client import FeishuClient, FeishuConfigError

    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise FeishuConfigError("Feishu credentials are not configured")
    return FeishuClient(settings.feishu_app_id, settings.feishu_app_secret)


@lru_cache(maxsize=1)
def get_wechat_official_crypto() -> "WeChatCrypto":
    from .wechat_crypto import WeChatCrypto, WeChatCredentials

    creds = WeChatCredentials(
        token=settings.wechat_token,
        encoding_aes_key=settings.wechat_encoding_aes_key,
        app_id=settings.wechat_app_id,
    )
    return WeChatCrypto(creds)


@lru_cache(maxsize=1)
def get_wecom_crypto() -> "WeChatCrypto":
    from .wechat_crypto import WeChatCrypto, WeChatCredentials

    creds = WeChatCredentials(
        token=settings.wecom_token,
        encoding_aes_key=settings.wecom_encoding_aes_key,
        app_id=settings.wecom_corp_id,
    )
    return WeChatCrypto(creds)
