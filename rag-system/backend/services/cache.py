from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, List

from diskcache import Cache

from ..config import settings

_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache(str(settings.cache_dir))
    return _cache


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def batch_hash(texts: Iterable[str]) -> List[str]:
    return [hash_text(text) for text in texts]


def close_cache() -> None:
    global _cache
    if _cache is not None:
        _cache.close()
        _cache = None
