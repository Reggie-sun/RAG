from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers.status import index_status_router, router as status_router
from .routers.upload import router as upload_router


def create_app() -> FastAPI:
    app = FastAPI(title="RAG CPU Tasks API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def on_startup() -> None:  # pragma: no cover
        settings.ensure_directories()

    app.include_router(upload_router)
    app.include_router(index_status_router)
    app.include_router(status_router)

    return app


app = create_app()
