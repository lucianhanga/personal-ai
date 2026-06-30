# storage/ (extension seam)

Repository adapters for the storage ports (relational, vector, object, graph).

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

## Current adapters
`postgres`.
