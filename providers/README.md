# providers/ (extension seam)

Model runtime adapters implementing the `ModelProvider` port. One subpackage per adapter. Adapters MUST NOT import each other.

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

## Current adapters
`ollama`, `openai_compat`, `whisper_local`.
