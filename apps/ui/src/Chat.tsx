import { useEffect, useRef, useState } from "react";

import {
  fetchModels,
  fetchProviders,
  streamChat,
  type ChatMessage,
  type ModelInfo,
} from "./api";
import { Markdown } from "./Markdown";

export function Chat({ token }: { token: string }): React.ReactElement {
  const [providers, setProviders] = useState<string[]>([]);
  const [provider, setProvider] = useState<string>("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
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
    listRef.current?.scrollTo(0, listRef.current.scrollHeight);
  }, [messages]);

  async function send(): Promise<void> {
    const content = input.trim();
    if (!content || busy) return;
    setError(null);
    setInput("");
    const history: ChatMessage[] = [...messages, { role: "user", content }];
    // Add the user turn and an empty assistant turn we will stream into.
    setMessages([...history, { role: "assistant", content: "" }]);
    setBusy(true);
    try {
      let acc = "";
      await streamChat({ messages: history, model, provider, token }, (delta) => {
        acc += delta;
        setMessages([...history, { role: "assistant", content: acc }]);
      });
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
