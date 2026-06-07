import { useEffect, useRef, useState } from "react";

import {
  deleteFile,
  fetchFiles,
  fetchModels,
  fetchProviders,
  streamChat,
  uploadFile,
  type ChatMessage,
  type Citation,
  type DocumentInfo,
  type ModelInfo,
} from "./api";
import { Markdown } from "./Markdown";

export function Chat({ token }: { token: string }): React.ReactElement {
  const [providers, setProviders] = useState<string[]>([]);
  const [provider, setProvider] = useState<string>("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string>("");
  const [files, setFiles] = useState<DocumentInfo[]>([]);
  const [useRag, setUseRag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [citations, setCitations] = useState<Record<number, Citation[]>>({});
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    fetchProviders(token)
      .then(({ default: def, providers }) => {
        if (!active) return;
        setProviders(providers);
        setProvider(def || providers[0] || "");
      })
      .catch((e: unknown) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    if (!provider) return;
    let active = true;
    setError(null);
    fetchModels(token, provider)
      .then(({ defaultModel, models }) => {
        if (!active) return;
        setModels(models);
        setModel(models.some((m) => m.name === defaultModel) ? defaultModel : models[0]?.name || "");
      })
      .catch((e: unknown) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [token, provider]);

  useEffect(() => {
    let active = true;
    // Files require storage; if unavailable the list just stays empty (no hard error).
    fetchFiles(token)
      .then((f) => active && setFiles(f))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    listRef.current?.scrollTo(0, listRef.current.scrollHeight);
  }, [messages]);

  async function onUpload(file: File | undefined): Promise<void> {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await uploadFile(token, file);
      setFiles(await fetchFiles(token));
      setUseRag(true);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(id: string): Promise<void> {
    try {
      await deleteFile(token, id);
      setFiles(files.filter((f) => f.id !== id));
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function send(): Promise<void> {
    const content = input.trim();
    if (!content || busy) return;
    setError(null);
    setInput("");
    const history: ChatMessage[] = [...messages, { role: "user", content }];
    const assistantIndex = history.length;
    setMessages([...history, { role: "assistant", content: "" }]);
    setBusy(true);
    try {
      let acc = "";
      await streamChat(
        { messages: history, model, provider, useRag, token },
        (delta) => {
          acc += delta;
          setMessages([...history, { role: "assistant", content: acc }]);
        },
        (cites) => setCitations((prev) => ({ ...prev, [assistantIndex]: cites })),
      );
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const selected = models.find((m) => m.name === model);

  return (
    <section aria-label="chat" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <label htmlFor="provider">Provider:</label>
        <select
          id="provider"
          data-testid="provider-select"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        >
          {providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <label htmlFor="model">Model:</label>
        <select
          id="model"
          data-testid="model-select"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        >
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
        {selected && (
          <span data-testid="model-caps" style={{ fontSize: "0.8rem", color: "#555" }}>
            {[
              selected.local ? "local" : "remote",
              selected.capabilities.vision && "vision",
              selected.capabilities.tool_calling && "tools",
              selected.capabilities.thinking && "thinking",
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        )}
      </div>

      <div
        data-testid="documents"
        style={{
          display: "flex",
          gap: "0.5rem",
          alignItems: "center",
          flexWrap: "wrap",
          fontSize: "0.85rem",
        }}
      >
        <label>
          Documents:{" "}
          <input
            data-testid="file-input"
            type="file"
            accept=".txt,.md,.markdown,.pdf,.docx"
            disabled={uploading}
            onChange={(e) => void onUpload(e.target.files?.[0])}
          />
        </label>
        {uploading && <span data-testid="upload-status">uploading…</span>}
        <label style={{ marginLeft: "auto" }}>
          <input
            data-testid="rag-toggle"
            type="checkbox"
            checked={useRag}
            onChange={(e) => setUseRag(e.target.checked)}
          />{" "}
          Use my documents
        </label>
      </div>

      {files.length > 0 && (
        <ul data-testid="file-list" style={{ margin: 0, paddingLeft: "1rem", fontSize: "0.8rem" }}>
          {files.map((f) => (
            <li key={f.id} data-testid="file-item">
              {f.name} <span style={{ color: "#888" }}>({f.chunk_count} chunks)</span>{" "}
              <button
                data-testid={`delete-${f.id}`}
                onClick={() => void onDelete(f.id)}
                style={{ fontSize: "0.75rem" }}
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div
        ref={listRef}
        data-testid="messages"
        style={{
          border: "1px solid #ddd",
          borderRadius: 8,
          padding: "0.75rem",
          height: 320,
          overflowY: "auto",
        }}
      >
        {messages.length === 0 && <p style={{ color: "#888" }}>Ask your local model anything.</p>}
        {messages.map((m, i) =>
          m.role === "assistant" ? (
            // Assistant replies render as Markdown (block elements, so not inside a <p>).
            <div key={i} data-testid="msg-assistant" style={{ margin: "0.4rem 0" }}>
              <strong>AI:</strong>
              <Markdown content={m.content} />
              {citations[i]?.length ? (
                <div data-testid="citations" style={{ fontSize: "0.75rem", color: "#555" }}>
                  Sources:{" "}
                  {citations[i]
                    .map(
                      (c) =>
                        `[${c.n}] ${c.name ?? c.source_id.slice(0, 8)}` +
                        (c.locator ? ` (${c.locator})` : ""),
                    )
                    .join("   ")}
                </div>
              ) : null}
            </div>
          ) : (
            // User input stays literal text.
            <p key={i} data-testid="msg-user" style={{ margin: "0.4rem 0" }}>
              <strong>You:</strong> {m.content}
            </p>
          ),
        )}
      </div>

      {error && (
        <p data-testid="chat-error" style={{ color: "#b00" }}>
          {error}
        </p>
      )}

      <div style={{ display: "flex", gap: "0.5rem" }}>
        <input
          data-testid="composer"
          style={{ flex: 1 }}
          value={input}
          placeholder="Type a message..."
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void send();
          }}
        />
        <button data-testid="send" onClick={() => void send()} disabled={busy || !model}>
          {busy ? "..." : "Send"}
        </button>
      </div>
    </section>
  );
}
