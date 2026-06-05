# retrieval/ (extension seam)

Retrieval strategy adapters implementing the `Retriever` port (e.g. vector-pgvector, keyword, graph-age). Added from M3.

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

> Empty at M0-1 by design. Concrete adapters arrive in their milestones.
