from __future__ import annotations

import orjson
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import zipfile
from xml.etree import ElementTree as ET

from fastapi.concurrency import run_in_threadpool
from langchain_core.documents import Document
from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from PIL import Image, ImageSequence, UnidentifiedImageError
import pytesseract

from ..config import settings
from .vector_service import VectorService
from ..utils.logger import get_logger


class IngestService:
    def __init__(self, vector_service: VectorService) -> None:
        self.vector_service = vector_service
        self.bm25_file = settings.bm25_index_path / "index.jsonl"
        self.logger = get_logger(__name__)

    def ingest_file(self, file_path: Path, filename: str) -> Dict[str, int]:
        self.logger.info("ingest.start", extra={"filename": filename, "path": str(file_path)})
        documents = self._load_documents(file_path, filename)
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(documents)
        if not chunks:
            raise ValueError("Document could not be parsed")

        chunk_id_start = self._reserve_chunk_ids(len(chunks))
        prepared_docs: List[Document] = []
        bm25_entries: List[bytes] = []
        source_type = self._detect_source_type(filename)

        for idx, chunk in enumerate(chunks):
            chunk_id = chunk_id_start + idx
            metadata = dict(chunk.metadata)
            metadata.update(
                {
                    "chunk_id": chunk_id,
                    "chunk_index": idx,
                    "source": filename,
                    "source_type": source_type,
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            document = Document(page_content=chunk.page_content, metadata=metadata)
            prepared_docs.append(document)
            bm25_entries.append(
                orjson.dumps(
                    {
                        "chunk_id": chunk_id,
                        "text": chunk.page_content,
                        "tokens": self._tokenize(chunk.page_content),
                        "source": filename,
                        "metadata": metadata,
                    }
                )
            )

        self.vector_service.add_documents(prepared_docs)
        self._append_bm25_entries(bm25_entries)
        self._update_meta(len(chunks))

        self.logger.info("ingest.done", extra={"filename": filename, "chunks": len(chunks)})
        return {"chunks": len(chunks)}

    async def ingest_file_async(self, file_path: Path, filename: str) -> Dict[str, int]:
        return await run_in_threadpool(self.ingest_file, file_path, filename)

    def _append_bm25_entries(self, rows: List[bytes]) -> None:
        if not rows:
            return
        with self.bm25_file.open("ab") as fh:
            for row in rows:
                fh.write(row + b"\n")

    def _load_documents(self, file_path: Path, filename: str) -> List[Document]:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            loader = PyPDFLoader(str(file_path))
            docs = loader.load()
        elif suffix == ".txt":
            loader = TextLoader(str(file_path), encoding="utf-8")
            docs = loader.load()
        elif suffix == ".docx":
            loader = Docx2txtLoader(str(file_path))
            docs = loader.load()
        elif suffix == ".odt":
            docs = self._load_odt_documents(file_path, filename)
        elif suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
            docs = self._load_image_documents(file_path, filename)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

        for doc in docs:
            doc.metadata.setdefault("source", filename)
            doc.metadata.setdefault("page", doc.metadata.get("page", 0))
        return docs

    def _load_odt_documents(self, file_path: Path, filename: str) -> List[Document]:
        try:
            with zipfile.ZipFile(file_path) as archive:
                with archive.open("content.xml") as handle:
                    xml_bytes = handle.read()
        except (zipfile.BadZipFile, KeyError, FileNotFoundError) as exc:
            raise ValueError(f"Failed to open ODT file: {filename}") from exc

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise ValueError(f"Failed to parse ODT file: {filename}") from exc

        ns = {
            "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        }
        paragraphs: List[str] = []
        for node in root.findall(".//text:p", ns):
            text = "".join(node.itertext()).strip()
            if text:
                paragraphs.append(text)

        if not paragraphs:
            raise ValueError("ODT file did not contain extractable text")

        docs: List[Document] = []
        for idx, paragraph in enumerate(paragraphs):
            docs.append(
                Document(
                    page_content=paragraph,
                    metadata={
                        "source": filename,
                        "page": idx,
                    },
                )
            )
        return docs

    def _load_image_documents(self, file_path: Path, filename: str) -> List[Document]:
        try:
            with Image.open(file_path) as image:
                frames = list(ImageSequence.Iterator(image))
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError(f"Failed to open image file: {filename}") from exc

        documents: List[Document] = []
        for idx, frame in enumerate(frames):
            try:
                # pytesseract requires RGB frames for best results
                converted = frame.convert("RGB")
                text = pytesseract.image_to_string(converted)
            except pytesseract.TesseractError as exc:
                raise RuntimeError("Tesseract OCR execution failed") from exc

            cleaned = text.strip()
            if not cleaned:
                continue

            documents.append(
                Document(
                    page_content=cleaned,
                    metadata={
                        "filename": filename,
                        "page": idx,
                        "source": filename,
                    },
                )
            )

        if not documents:
            raise ValueError("Image file did not contain extractable text")

        return documents

    def _detect_source_type(self, filename: str) -> str:
        suffix = Path(filename).suffix.lower().lstrip(".")
        return suffix or "unknown"

    def _reserve_chunk_ids(self, count: int) -> int:
        meta = self._read_meta()
        start = int(meta.get("next_chunk_id", 0))
        meta["next_chunk_id"] = start + count
        self._write_meta(meta)
        return start

    def _update_meta(self, new_chunks: int) -> None:
        meta = self._read_meta()
        total_docs = int(meta.get("total_docs", meta.get("documents", 0)) or 0) + 1
        total_chunks = int(meta.get("total_chunks", meta.get("chunks", 0)) or 0) + new_chunks
        meta["total_docs"] = total_docs
        meta["total_chunks"] = total_chunks
        meta["documents"] = total_docs
        meta["chunks"] = total_chunks
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_meta(meta)

    def _read_meta(self) -> Dict[str, int | str]:
        if not settings.meta_file_path.exists():
            return {
                "total_docs": 0,
                "total_chunks": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "next_chunk_id": 0,
            }
        data = orjson.loads(settings.meta_file_path.read_bytes() or b"{}")
        data.setdefault("next_chunk_id", 0)
        if "documents" not in data:
            data["documents"] = data.get("total_docs", 0)
        if "chunks" not in data:
            data["chunks"] = data.get("total_chunks", 0)
        return data

    def _write_meta(self, data: Dict[str, Any]) -> None:
        settings.meta_file_path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))

    def _tokenize(self, text: str) -> List[str]:
        return [token.lower() for token in text.split() if token.strip()]
