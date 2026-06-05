# modalities/ (extension seam)

Modality handlers implementing `ModalityHandler` (parse/ocr/transcribe/synthesize/render) - e.g. files-tika, files-docling, stt-whisper, tts-piper, vision. Added from M3/M8.

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

> Empty at M0-1 by design. Concrete adapters arrive in their milestones.
