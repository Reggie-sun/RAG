from pathlib import Path
from typing import Dict

from ..services.ingest_service import IngestService
from ..services.vector_service import VectorService

_ingest_service = IngestService(VectorService())


def ingest_document(file_path: Path, filename: str) -> Dict[str, int]:
    """
    Convenience wrapper for CLI ingestion utilities.
    """
    return _ingest_service.ingest_file(file_path, filename)
