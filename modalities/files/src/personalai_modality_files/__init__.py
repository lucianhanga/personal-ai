"""File parsers + chunking for PersonalAI ingestion."""

from personalai_modality_files.parser import (
    ParsedDocument,
    UnsupportedFileTypeError,
    chunk_text,
    parse_document,
)

__all__ = ["ParsedDocument", "UnsupportedFileTypeError", "chunk_text", "parse_document"]
