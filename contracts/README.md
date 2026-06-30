# contracts (`personalai_contracts`)

The **stable core API** of PersonalAI: ports (interfaces), schemas, and message/tool contracts.

- This package has **no dependencies** on any other PersonalAI package.
- Everything else depends **inward** on this package (see ADR-0001).
- Ports and base schemas are defined here.

Do **not** import `personalai_core` or `personalai_backend` from here.
