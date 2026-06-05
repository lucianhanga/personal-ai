# tools/ (extension seam)

Internal tools and MCP adapters. Each is self-contained (manifest + sandboxed handler) and is loaded by the Tool/MCP gateway. Added from M4.

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

> Empty at M0-1 by design. Concrete adapters arrive in their milestones.
