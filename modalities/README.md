# modalities/ (extension seam)

Modality handlers implementing `ModalityHandler` (parse/ocr/transcribe/synthesize/render).

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

## Current adapters
`files` (file parsing/extraction).
