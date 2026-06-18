import type { Dispatch, SetStateAction } from "react";

import type { DocumentInfo } from "./api";
import { Agents } from "./Agents";
import { McpPanel } from "./McpPanel";
import { Memory } from "./Memory";
import { Preferences } from "./Preferences";
import { Tools } from "./Tools";

interface SettingsAccordionProps {
  token: string;
  showSettings: boolean;
  setShowSettings: Dispatch<SetStateAction<boolean>>;
  files: DocumentInfo[];
  uploading: boolean;
  onUpload: (file: File | undefined) => void;
  useRag: boolean;
  setUseRag: Dispatch<SetStateAction<boolean>>;
  showTools: boolean;
  setShowTools: Dispatch<SetStateAction<boolean>>;
  useTools: boolean;
  setUseTools: Dispatch<SetStateAction<boolean>>;
  approveTools: boolean;
  setApproveTools: Dispatch<SetStateAction<boolean>>;
  showMemory: boolean;
  setShowMemory: Dispatch<SetStateAction<boolean>>;
  useMemory: boolean;
  setUseMemory: Dispatch<SetStateAction<boolean>>;
  reasoning: "off" | "brief" | "full";
  setReasoning: Dispatch<SetStateAction<"off" | "brief" | "full">>;
  showMcp: boolean;
  setShowMcp: Dispatch<SetStateAction<boolean>>;
  showPreferences: boolean;
  setShowPreferences: Dispatch<SetStateAction<boolean>>;
  showAgents: boolean;
  setShowAgents: Dispatch<SetStateAction<boolean>>;
}

const ROW: React.CSSProperties = {
  display: "flex",
  gap: "0.5rem",
  alignItems: "center",
  flexWrap: "wrap",
};

/** Row 2: the collapsible global-settings accordion (documents, tools, memory, reasoning, MCP). */
export function SettingsAccordion(props: SettingsAccordionProps): React.ReactElement {
  const { token, showSettings, setShowSettings, files, uploading, onUpload, useRag, setUseRag } =
    props;
  return (
    <div
      data-testid="settings-accordion"
      style={{ border: "1px solid #ddd", borderRadius: 8, fontSize: "0.85rem" }}
    >
      <button
        data-testid="settings-toggle"
        onClick={() => setShowSettings((v) => !v)}
        style={{
          width: "100%",
          textAlign: "left",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: "0.5rem 0.75rem",
          fontWeight: 600,
        }}
      >
        {showSettings ? "▾" : "▸"} Settings
      </button>
      {showSettings && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
            padding: "0 0.75rem 0.75rem",
          }}
        >
          {/* Line 1: Documents */}
          <div data-testid="settings-documents" style={ROW}>
            <label>
              Documents:{" "}
              <input
                data-testid="file-input"
                type="file"
                accept=".txt,.md,.markdown,.pdf,.docx"
                disabled={uploading}
                onChange={(e) => onUpload(e.target.files?.[0])}
              />
            </label>
            {uploading && <span data-testid="upload-status">uploading…</span>}
            {files.length > 0 && !useRag && (
              <span data-testid="rag-hint" style={{ marginLeft: "auto", color: "#b06f00" }}>
                Not using your documents — turn on to ground answers.
              </span>
            )}
            <label style={{ marginLeft: files.length > 0 && !useRag ? "0.5rem" : "auto" }}>
              <input
                data-testid="rag-toggle"
                type="checkbox"
                checked={useRag}
                onChange={(e) => setUseRag(e.target.checked)}
              />{" "}
              Use my documents
            </label>
          </div>

          {/* Line 2: Tools */}
          <div data-testid="settings-tools" style={ROW}>
            <button data-testid="tools-show" onClick={() => props.setShowTools((v) => !v)}>
              {props.showTools ? "Hide tools" : "Tools"}
            </button>
            <label style={{ marginLeft: "auto" }}>
              <input
                data-testid="tools-toggle"
                type="checkbox"
                checked={props.useTools}
                onChange={(e) => props.setUseTools(e.target.checked)}
              />{" "}
              Use tools
            </label>
            {props.useTools && (
              <label title="Allow high-risk tools (e.g. http_fetch) to run this session">
                <input
                  data-testid="approve-tools-toggle"
                  type="checkbox"
                  checked={props.approveTools}
                  onChange={(e) => props.setApproveTools(e.target.checked)}
                />{" "}
                approve high-risk
              </label>
            )}
          </div>
          {props.showTools && <Tools token={token} />}

          {/* Line 3: Memory */}
          <div data-testid="settings-memory" style={ROW}>
            <button data-testid="memory-show" onClick={() => props.setShowMemory((v) => !v)}>
              {props.showMemory ? "Hide memory" : "Memory"}
            </button>
            <label style={{ marginLeft: "auto" }}>
              <input
                data-testid="memory-toggle"
                type="checkbox"
                checked={props.useMemory}
                onChange={(e) => props.setUseMemory(e.target.checked)}
              />{" "}
              Use my memory
            </label>
          </div>
          {props.showMemory && <Memory token={token} />}

          {/* Line 4: Reasoning */}
          <div data-testid="settings-reasoning" style={ROW}>
            <span style={{ color: "#555" }}>Reasoning</span>
            <label
              style={{ marginLeft: "auto" }}
              title="How much the model thinks before answering. Off = no reasoning; Brief = think but stay concise; Full = think freely (slower). Shown under each message's Details."
            >
              <select
                data-testid="reasoning-select"
                value={props.reasoning}
                onChange={(e) => props.setReasoning(e.target.value as "off" | "brief" | "full")}
              >
                <option value="off">Off</option>
                <option value="brief">Brief</option>
                <option value="full">Full</option>
              </select>
            </label>
          </div>

          {/* Line 5: MCP servers */}
          <div data-testid="settings-mcp" style={ROW}>
            <button data-testid="mcp-show" onClick={() => props.setShowMcp((v) => !v)}>
              {props.showMcp ? "Hide MCP" : "Manage MCP"}
            </button>
            <span style={{ marginLeft: "auto", color: "#888" }}>MCP servers (tool sources)</span>
          </div>
          {props.showMcp && <McpPanel token={token} />}

          {/* Line 6: Preferences (per-tenant defaults: model, agent, behavior) */}
          <div data-testid="settings-preferences" style={ROW}>
            <button
              data-testid="preferences-show"
              onClick={() => props.setShowPreferences((v) => !v)}
            >
              {props.showPreferences ? "Hide preferences" : "Preferences"}
            </button>
            <span style={{ marginLeft: "auto", color: "#888" }}>
              Saved defaults (model, agent, behavior)
            </span>
          </div>
          {props.showPreferences && <Preferences token={token} />}

          {/* Line 7: Agents (agentic mode + per-agent prompts/tools) */}
          <div data-testid="settings-agents" style={ROW}>
            <button data-testid="agents-show" onClick={() => props.setShowAgents((v) => !v)}>
              {props.showAgents ? "Hide agents" : "Agents"}
            </button>
            <span style={{ marginLeft: "auto", color: "#888" }}>
              Agentic mode + per-agent prompts/tools
            </span>
          </div>
          {props.showAgents && <Agents token={token} />}
        </div>
      )}
    </div>
  );
}
