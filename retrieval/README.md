# retrieval/ (extension seam)

Retrieval strategy adapters implementing the `Retriever` port (e.g. vector, keyword, graph).

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

## Current adapters
None yet. Add one as a self-contained subpackage when retrieval lands.
