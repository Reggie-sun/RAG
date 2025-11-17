from __future__ import annotations

from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Any, Dict, Optional

try:
    import torch
except Exception:  # pragma: no cover - torch may be missing in CPU-only envs
    torch = None  # type: ignore[assignment]


@dataclass(frozen=True)
class GPUStatus:
    available: bool
    device: str
    name: Optional[str] = None
    total_memory_gb: Optional[float] = None
    capability: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        return payload


def _torch_available() -> bool:
    return bool(torch and torch.cuda.is_available())


def parse_cuda_device(value: str) -> int:
    try:
        if ":" in value:
            _, idx = value.split(":", 1)
        else:
            idx = value
        return max(0, int(idx))
    except Exception:
        return 0


@lru_cache(maxsize=4)
def detect_gpu(preferred: str = "cuda:0") -> GPUStatus:
    if not _torch_available():
        return GPUStatus(False, "cpu")
    device_index = parse_cuda_device(preferred)
    try:
        properties = torch.cuda.get_device_properties(device_index)
        name = properties.name
        capability = f"{properties.major}.{properties.minor}"
        total_memory_gb = round(properties.total_memory / (1024 ** 3), 2)
    except Exception:
        name = None
        capability = None
        total_memory_gb = None
    device = f"cuda:{device_index}"
    return GPUStatus(True, device, name, total_memory_gb, capability)


def resolve_device(preferred: str, fallback: str = "cpu") -> str:
    status = detect_gpu(preferred)
    return status.device if status.available else fallback
