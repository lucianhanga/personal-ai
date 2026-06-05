# storage/ (extension seam)

Repository adapters for the storage ports (relational, vector, object, graph) - e.g. postgres, qdrant, object-store. Added from M3.

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

> Empty at M0-1 by design. Concrete adapters arrive in their milestones.
