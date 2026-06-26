"""File parsers + chunking for PersonalAI ingestion."""

from personalai_modality_files.ocr import OcrUnavailableError, ocr_available, ocr_pdf
from personalai_modality_files.parser import (
    ParsedDocument,
    UnsupportedFileTypeError,
    chunk_text,
    parse_document,
)

__all__ = [
    "OcrUnavailableError",
    "ParsedDocument",
    "UnsupportedFileTypeError",
    "chunk_text",
    "ocr_available",
    "ocr_pdf",
    "parse_document",
]
