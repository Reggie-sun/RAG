from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path
from typing import Iterable, List, Optional

os.environ.setdefault("TRANSFORMERS_NO_TORCHVISION", "1")
os.environ.setdefault("HF_SKIP_TORCH_TRITON", "1")
os.environ.setdefault("TORCHINDUCTOR_SKIP", "1")

try:
    import triton as _triton  # type: ignore
except ModuleNotFoundError:
    _triton = types.ModuleType("triton")
    sys.modules["triton"] = _triton
else:
    _triton = sys.modules["triton"]

if not hasattr(_triton, "backends"):
    backends_stub = types.ModuleType("triton.backends")
    sys.modules["triton.backends"] = backends_stub
    setattr(_triton, "backends", backends_stub)
else:
    backends_stub = getattr(_triton, "backends")

compiler_module = sys.modules.get("triton.backends.compiler")
if compiler_module is None:
    compiler_module = types.ModuleType("triton.backends.compiler")
    sys.modules["triton.backends.compiler"] = compiler_module


def _unavailable(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("Triton compiler is unavailable in this environment")


if not hasattr(compiler_module, "compile"):
    compiler_module.compile = _unavailable  # type: ignore[attr-defined]
compiler_module.__all__ = ["compile"]  # type: ignore[attr-defined]
backends_stub.compiler = compiler_module  # type: ignore[attr-defined]

try:
    language_module = importlib.import_module("triton.language")
except ModuleNotFoundError:
    language_module = types.ModuleType("triton.language")
    language_module.__all__ = []  # type: ignore[attr-defined]
    sys.modules["triton.language"] = language_module
else:
    if not hasattr(language_module, "__all__"):
        language_module.__all__ = []  # type: ignore[attr-defined]
setattr(_triton, "language", language_module)

import torch
from transformers import AutoModel, AutoTokenizer


class LocalBgeEmbeddings:
    _DEFAULT_GPU_BATCH = 6

    def __init__(
        self,
        model_path: Path,
        device: str = "cpu",
        normalize: bool = True,
        batch_size: int = 16,
        max_length: int = 512,
    ) -> None:
        self._torch_dtype: Optional[torch.dtype] = None
        resolved_device = device
        if device.startswith("cuda") and not torch.cuda.is_available():
            resolved_device = "cpu"
        self.device = torch.device(resolved_device)
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"Embedding model not found at {self.model_path}")

        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))
        self.model = AutoModel.from_pretrained(str(self.model_path), trust_remote_code=False)
        if self.device.type == "cuda":
            dtype_name = os.getenv("EMBEDDING_TORCH_DTYPE", "float16").lower()
            if dtype_name == "float16":
                self.model = self.model.half()
                self._torch_dtype = torch.float16
            elif dtype_name == "bfloat16":
                self.model = self.model.to(dtype=torch.bfloat16)
                self._torch_dtype = torch.bfloat16
            else:
                self._torch_dtype = torch.float32
        self.model.to(self.device)
        self.model.eval()

        self.normalize = normalize
        if self.device.type == "cuda":
            tuned_batch = min(batch_size, self._DEFAULT_GPU_BATCH)
            self.batch_size = max(1, tuned_batch)
        else:
            self.batch_size = max(1, batch_size)
        self.max_length = max_length
        self._clear_cuda_cache()

    def embed_documents(self, texts: Iterable[str]) -> List[List[float]]:
        return self._encode(list(texts))

    def embed_query(self, text: str) -> List[float]:
        return self._encode([text])[0]

    def _encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        embeddings: List[List[float]] = []
        current_batch = self.batch_size
        index = 0
        with torch.no_grad():
            while index < len(texts):
                batch = texts[index : index + current_batch]
                try:
                    inputs = self.tokenizer(
                        batch,
                        padding=True,
                        truncation=True,
                        max_length=self.max_length,
                        return_tensors="pt",
                        return_attention_mask=True,
                    )
                    inputs = {key: value.to(self.device) for key, value in inputs.items()}
                    outputs = self.model(**inputs)
                    cls_embeddings = outputs.last_hidden_state[:, 0]
                    if self.normalize:
                        cls_embeddings = torch.nn.functional.normalize(cls_embeddings, p=2, dim=1)
                    embeddings.extend(cls_embeddings.cpu().tolist())
                    index += current_batch
                except RuntimeError as exc:
                    message = str(exc).lower()
                    if "out of memory" in message and self.device.type == "cuda" and current_batch > 1:
                        self._clear_cuda_cache()
                        current_batch = max(1, current_batch // 2)
                        continue
                    self._clear_cuda_cache()
                    raise
                finally:
                    self._clear_cuda_cache()
        self._clear_cuda_cache()
        return embeddings

    def _clear_cuda_cache(self) -> None:
        if torch.cuda.is_available() and self.device.type == "cuda":
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except RuntimeError:
                pass
