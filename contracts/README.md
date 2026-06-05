# contracts (`personalai_contracts`)

The **stable core API** of PersonalAI: ports (interfaces), schemas, and message/tool contracts.

- This package has **no dependencies** on any other PersonalAI package.
- Everything else depends **inward** on this package (see ADR-0001).
- Ports and base schemas are defined here in **M0-2** and **M0-3**; this milestone (M0-1)
  only establishes the package and its boundary.

Do **not** import `personalai_core` or `personalai_backend` from here.
