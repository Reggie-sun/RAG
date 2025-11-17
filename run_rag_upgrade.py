import asyncio
from backend.services.providers import get_rag_service

async def main():
    rag = get_rag_service()
    resp = await rag.answer(
        query="解释一下cpps",
        top_k=6,
        allow_web=True,
        doc_only=False,
        web_mode=None,
    )
    print(resp["answer"])

if __name__ == "__main__":
    asyncio.run(main())
