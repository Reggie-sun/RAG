#!/usr/bin/env bash
set -euo pipefail
cd /home/reggie/vscode_folder/RAG/rag-system
source ~/miniconda3/bin/activate RAG
export PYTHONPATH=/home/reggie/vscode_folder/RAG/rag-system
export ALL_PROXY=
export all_proxy=
export HTTP_PROXY=
export http_proxy=
export HTTPS_PROXY=
export https_proxy=
python - <<'PY'
import asyncio
from backend.services.providers import get_rag_service

async def main():
    rag = get_rag_service()
    resp = await rag.answer(
        query="解释一下cpps",
        top_k=6,
        allow_web=True,
        doc_only=False,
        web_mode="only",
    )
    print(resp["answer"])

asyncio.run(main())
PY
