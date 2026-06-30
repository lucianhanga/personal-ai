# modalities/files (`personalai_modality_files`)

Lightweight, pure file parsers + chunking for ingestion. Depends inward on
`personalai_contracts` only (ADR-0001).

- `parse_document(content, filename)` -> `ParsedDocument(text, mime)` for **txt / markdown**
  (direct), **pdf** (pypdf), **docx** (python-docx). Text extraction only; no active content run.
- `chunk_text(text, size=1000, overlap=150)` -> overlapping character chunks.

Richer parsing (Apache Tika / IBM Docling, OCR) can be added later behind the `ModalityHandler`
seam without touching callers.
