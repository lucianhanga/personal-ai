# agents/ (extension seam)

Agent roles and LangGraph nodes (e.g. planner, researcher, critic).

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

## Current adapters
None yet. Agent roles live in the core orchestrator for now; add packaged roles here as they are extracted.
