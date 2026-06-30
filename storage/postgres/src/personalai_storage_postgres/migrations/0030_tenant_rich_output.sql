-- #517: per-tenant rich-output (Mermaid diagrams / rich markdown) toggle. opt-in; when on, a
-- _RICH_OUTPUT system message is injected telling the model it may emit Mermaid diagrams. Joins the
-- per-tenant settings (tenant_settings, 0015). NULL inherits PERSONALAI_RICH_OUTPUT_ENABLED.

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS rich_output_enabled boolean;
