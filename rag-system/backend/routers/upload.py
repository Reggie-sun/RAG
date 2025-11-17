import asyncio
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from ..services.hybrid_retriever import HybridRetriever
from ..services.ingest_service import IngestService
from ..services.providers import get_hybrid_retriever, get_ingest_service
from ..utils.logger import get_logger

router = APIRouter(prefix="/api", tags=["upload"])

logger = get_logger(__name__)


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".docx",
    ".odt",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.oasis.opendocument.text",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

MAX_BYTES = 50 * 1024 * 1024


class UploadSummary(BaseModel):
    filename: str
    chunks: int


class UploadResponse(BaseModel):
    processed: List[UploadSummary]


MAX_FILES_PER_REQUEST = 3


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    ingest_service: IngestService = Depends(get_ingest_service),
    retriever: HybridRetriever = Depends(get_hybrid_retriever),
) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"You can upload at most {MAX_FILES_PER_REQUEST} files per request.")

    async def process_file(file: UploadFile) -> UploadSummary:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")

        suffix = Path(file.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

        content_type = file.content_type.split(';')[0].strip().lower() if file.content_type else None
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            logger.warning(
                'upload.unsupported_content_type',
                extra={'filename': file.filename, 'content_type': content_type},
            )

        tmp_path: Path | None = None
        bytes_copied = 0
        logger.info('upload.received', extra={'filename': file.filename, 'content_type': file.content_type})

        try:
            with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = Path(tmp.name)
                chunk_size = 4 * 1024 * 1024
                await file.seek(0)
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    bytes_copied += len(chunk)
                    if bytes_copied > MAX_BYTES:
                        raise HTTPException(status_code=413, detail='File too large')
                    tmp.write(chunk)
        except HTTPException:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            raise
        except Exception as exc:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            raise HTTPException(status_code=400, detail='Failed to read or store uploaded file') from exc
        finally:
            await file.close()

        if bytes_copied == 0:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            raise HTTPException(status_code=400, detail='Uploaded file is empty')

        try:
            logger.info('upload.ingest_start', extra={'filename': file.filename, 'size': bytes_copied})
            ingest_result = await ingest_service.ingest_file_async(tmp_path, file.filename)
            logger.info('upload.ingest_done', extra={'filename': file.filename, 'chunks': ingest_result.get('chunks')})
            return UploadSummary(
                filename=file.filename,
                chunks=int(ingest_result.get('chunks', 0) or 0),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.exception('upload.runtime_error', extra={'filename': file.filename})
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception('upload.failure', extra={'filename': file.filename})
            raise HTTPException(status_code=500, detail='Failed to ingest document') from exc
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    results = await asyncio.gather(*(process_file(file) for file in files))

    # 立刻刷新一次索引，确保上传完成后就能检索到
    try:
        retriever.refresh_indexes()
    except Exception:
        logger.exception("upload.refresh_failed")
    finally:
        background_tasks.add_task(retriever.refresh_indexes)

    return UploadResponse(processed=list(results))
