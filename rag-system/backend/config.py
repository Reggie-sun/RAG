import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Tuple

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "https://srj666.com",
    "https://www.srj666.com",
    "https://api.srj666.com",
    "https://cpu.srj666.com",
    "https://test.srj666.com",
]


@dataclass
class Settings:
    base_dir: ClassVar[Path] = Path(__file__).resolve().parent
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    # DeepSeek 兼容 OpenAI 接口，用于本地模型不可用时回退
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    deepseek_chat_model: str = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat").strip()
    deepseek_temperature: float = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.2"))
    llm_provider_debug: bool = os.getenv("LLM_PROVIDER_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b")
    ollama_temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    ollama_num_predict: int = int(os.getenv("OLLAMA_NUM_PREDICT", "1024"))
    ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "25"))
    embedding_model_path: Path = Path(os.getenv("EMBEDDING_MODEL_PATH", "/home/reggie/bge-m3")).expanduser()
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "auto").strip()
    rerank_api_key: str = os.getenv("RERANK_API_KEY", "").strip()
    rerank_api_base_url: str = os.getenv("RERANK_API_BASE_URL", "").strip()
    zhipu_api_key: str = os.getenv("ZHIPU_API_KEY", "").strip()
    zhipu_api_base_url: str = os.getenv("ZHIPU_API_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").strip()
    zhipu_chat_model: str = os.getenv("ZHIPU_CHAT_MODEL", "glm-4.6").strip()
    data_dir: Path = (base_dir / "../data").resolve()
    faiss_index_path: Path = Path(
        os.getenv("FAISS_INDEX_PATH", base_dir / "../data/faiss_index")
    ).resolve()
    bm25_index_path: Path = Path(
        os.getenv("BM25_INDEX_PATH", base_dir / "../data/bm25_index")
    ).resolve()
    meta_file_path: Path = (base_dir / "db/meta.json").resolve()
    cache_dir: Path = (base_dir / "../data/emb_cache").resolve()
    retrieval_log_path: Path = Path(
        os.getenv("RETRIEVAL_LOG_PATH", base_dir / "../data/retrieval_logs.jsonl")
    ).resolve()
    log_dir: Path = (base_dir / "../data/logs").resolve()
    app_log_file: Path = (base_dir / "../data/logs/app.log").resolve()
    vector_weight: float = float(os.getenv("VECTOR_WEIGHT", "0.6"))
    use_rerank: bool = os.getenv("USE_RERANK", "true").lower() in {"1", "true", "yes"}
    rerank_model: str = os.getenv("RERANK_MODEL", "gpt-4o-mini")
    retrieval_default_top_k: int = int(os.getenv("RETRIEVAL_TOP_K", "6"))
    retrieval_max_top_k: int = int(os.getenv("RETRIEVAL_MAX_TOP_K", "10"))
    retrieval_confidence_threshold: float = float(os.getenv("RETRIEVAL_CONFIDENCE_THRESHOLD", "0.6"))
    # 原文摘录使用更宽松的阈值，尽量保留 top-k 片段
    retrieval_excerpt_confidence_threshold: float = float(
        os.getenv("RETRIEVAL_EXCERPT_CONFIDENCE_THRESHOLD", "0.4")
    )
    max_retrieval_logs: int = int(os.getenv("MAX_RETRIEVAL_LOGS", "500"))
    doc_answer_threshold: float = float(os.getenv("DOC_ANSWER_THRESHOLD", "0.6"))
    doc_answer_max_snippets: int = int(os.getenv("DOC_ANSWER_MAX_SNIPPETS", "3"))
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    web_search_max_results: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "6"))
    web_search_timeout: float = float(os.getenv("WEB_SEARCH_TIMEOUT", "8"))
    web_search_confidence_floor: float = float(os.getenv("WEB_SEARCH_CONFIDENCE_FLOOR", "0.55"))
    web_search_providers: Tuple[str, ...] = tuple(
        provider.strip().lower()
        for provider in os.getenv("WEB_SEARCH_PROVIDERS", "").split(",")
        if provider.strip()
    )
    websearch_api_key: str = os.getenv("WEBSEARCHAPI_KEY", "")
    exa_api_key: str = os.getenv("EXA_API_KEY", "")
    firecrawl_api_key: str = os.getenv("FIRECRAWL_API_KEY", "")
    intent_llm_timeout: float = float(os.getenv("INTENT_LLM_TIMEOUT", "4.5"))
    intent_low_confidence_gap: float = float(os.getenv("INTENT_LOW_CONFIDENCE_GAP", "0.18"))
    intent_multi_topic_length: int = int(os.getenv("INTENT_MULTI_TOPIC_LENGTH", "28"))
    enable_gpu: bool = os.getenv("ENABLE_GPU", "false").lower() in {"1", "true", "yes"}
    preferred_cuda_device: str = os.getenv("CUDA_DEVICE", "cuda:0").strip()
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "").strip()
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "").strip()
    feishu_verification_token: str = os.getenv("FEISHU_VERIFICATION_TOKEN", "").strip()
    feishu_encrypt_key: str = os.getenv("FEISHU_ENCRYPT_KEY", "").strip()
    wechat_token: str = os.getenv("WECHAT_TOKEN", "").strip()
    wechat_app_id: str = os.getenv("WECHAT_APP_ID", "").strip()
    wechat_encoding_aes_key: str = os.getenv("WECHAT_ENCODING_AES_KEY", "").strip()
    wechat_app_secret: str = os.getenv("WECHAT_APP_SECRET", "").strip()
    wecom_token: str = os.getenv("WECOM_TOKEN", "").strip()
    wecom_corp_id: str = os.getenv("WECOM_CORP_ID", "").strip()
    wecom_agent_id: str = os.getenv("WECOM_AGENT_ID", "").strip()
    wecom_corp_secret: str = os.getenv("WECOM_CORP_SECRET", "").strip()
    wecom_encoding_aes_key: str = os.getenv("WECOM_ENCODING_AES_KEY", "").strip()
    customer_service_api_key: str = os.getenv("CUSTOMER_SERVICE_API_KEY", "").strip()
    customer_service_rate_limit_per_minute: int = int(
        os.getenv("CUSTOMER_SERVICE_RATE_LIMIT_PER_MINUTE", "60")
    )
    cors_allowed_origins: Tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            ",".join(DEFAULT_CORS_ORIGINS),
        ).split(",")
        if origin.strip()
    )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.faiss_index_path.mkdir(parents=True, exist_ok=True)
        self.bm25_index_path.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.meta_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.meta_file_path.exists():
            default_meta = {
                "total_docs": 0,
                "total_chunks": 0,
                "documents": 0,
                "chunks": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "next_chunk_id": 0,
            }
            self.meta_file_path.write_text(json.dumps(default_meta, indent=2), encoding="utf-8")
        self.retrieval_log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.retrieval_log_path.exists():
            self.retrieval_log_path.write_text("", encoding="utf-8")
        if not self.app_log_file.exists():
            self.app_log_file.touch()


settings = Settings()
settings.ensure_directories()

try:
    from .utils.gpu import resolve_device
except Exception:
    resolve_device = None


def _configure_embedding_device() -> None:
    if resolve_device is None:
        if settings.embedding_device in {"", "auto"}:
            settings.embedding_device = "cpu"
        return

    if settings.embedding_device.lower() in {"", "auto"}:
        if settings.enable_gpu:
            settings.embedding_device = resolve_device(settings.preferred_cuda_device)
        else:
            settings.embedding_device = "cpu"

_configure_embedding_device()
