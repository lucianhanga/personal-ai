-- Security settings (Settings -> Security panel): two per-tenant flags joining tenant_settings (0015).
-- agent_egress_gate decouples the network-egress approval pause (#377) from the answer gate
-- (agent_human_gate); tool_approval_required is the persisted "require approval for high-risk tools"
-- policy the chat composer's approve-tools default follows. NULL on either inherits the deployment
-- default (PERSONALAI_AGENT_EGRESS_GATE / PERSONALAI_TOOL_APPROVAL_REQUIRED).
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS agent_egress_gate boolean;
ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS tool_approval_required boolean;
