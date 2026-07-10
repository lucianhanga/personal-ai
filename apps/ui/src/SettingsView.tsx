import { useState } from "react";

import { Agents } from "./Agents";
import { DocumentsPanel } from "./DocumentsPanel";
import { KnowledgePanel } from "./KnowledgePanel";
import { McpPanel } from "./McpPanel";
import { Memory } from "./Memory";
import { ModelStack } from "./ModelStack";
import { Preferences } from "./Preferences";
import { Security } from "./Security";
import { Tools } from "./Tools";
import type { DocumentInfo } from "./api";

type SectionId =
  | "documents"
  | "tools"
  | "mcp"
  | "agents"
  | "models"
  | "memory"
  | "knowledge"
  | "preferences"
  | "security";

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "models", label: "Model stack" },
  { id: "documents", label: "Documents" },
  { id: "mcp", label: "MCP servers" },
  { id: "tools", label: "Tools" },
  { id: "agents", label: "Agents" },
  { id: "memory", label: "Memory" },
  { id: "knowledge", label: "Knowledge" },
  { id: "preferences", label: "Preferences" },
  // Security sits last and is flagged red — egress + the human-in-the-loop approval gates.
  { id: "security", label: "Security" },
];

interface SettingsViewProps {
  token: string;
  onToken?: (value: string) => void;
  files: DocumentInfo[];
  uploading: boolean;
  onUpload: (file: File | undefined) => void;
  onDelete: (id: string) => void;
}

/** Settings as a dedicated full-width view with a section rail + detail pane (#290 redesign). */
export function SettingsView(props: SettingsViewProps): React.ReactElement {
  const { token, onToken } = props;
  const [section, setSection] = useState<SectionId>("documents");

  return (
    <div
      data-testid="settings-view"
      style={{ display: "flex", gap: "1rem", flex: 1, minHeight: 0, alignItems: "stretch", flexWrap: "wrap" }}
    >
      {/* Section rail */}
      <nav
        data-testid="settings-nav"
        role="tablist"
        aria-orientation="vertical"
        style={{ display: "flex", flexDirection: "column", gap: "0.15rem", minWidth: 140 }}
      >
        {SECTIONS.map((s) => {
          const active = section === s.id;
          // Security is flagged red so it reads as the "danger zone" of settings.
          const danger = s.id === "security";
          const accent = danger ? "#b00020" : "#1a7f37";
          return (
            <button
              key={s.id}
              role="tab"
              aria-selected={active}
              aria-current={active ? "page" : undefined}
              data-testid={`settings-nav-${s.id}`}
              onClick={() => setSection(s.id)}
              style={{
                textAlign: "left",
                padding: "0.4rem 0.6rem",
                border: "none",
                cursor: "pointer",
                borderLeft: active ? `3px solid ${accent}` : "3px solid transparent",
                background: active ? (danger ? "#fbeaec" : "#f0f6f1") : "none",
                color: danger ? "#b00020" : undefined,
                fontWeight: active || danger ? 600 : 400,
                fontSize: "0.88rem",
              }}
            >
              {s.label}
            </button>
          );
        })}
      </nav>

      {/* Detail pane */}
      <div data-testid="settings-pane" style={{ flex: 1, minWidth: 280, overflowY: "auto" }}>
        {section === "documents" && (
          <DocumentsPanel
            token={token}
            files={props.files}
            uploading={props.uploading}
            onUpload={props.onUpload}
            onDelete={props.onDelete}
          />
        )}
        {section === "tools" && <Tools token={token} />}
        {section === "mcp" && <McpPanel token={token} />}
        {section === "agents" && <Agents token={token} />}
        {section === "models" && <ModelStack token={token} />}
        {section === "memory" && <Memory token={token} />}
        {section === "knowledge" && <KnowledgePanel token={token} />}
        {section === "preferences" && <Preferences token={token} onToken={onToken} />}
        {section === "security" && <Security token={token} />}
      </div>
    </div>
  );
}
