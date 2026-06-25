import { useEffect, useRef, useState } from "react";

import {
  createConversation,
  deleteConversation,
  deleteFile,
  fetchConversation,
  fetchConversations,
  fetchFiles,
  fetchMemories,
  allowEgressHost,
  fetchModels,
  fetchProviders,
  fetchSettings,
  fetchTranscribeEnabled,
  fetchTtsEnabled,
  renameConversation,
  resumeChat,
  saveSettings,
  streamChat,
  describeImage,
  extractDocument,
  transcribeAudio,
  uploadFile,
  type ApprovalRequest,
  type ChatMessage,
  type Citation,
  type ContextBreakdown,
  type ConversationSummary,
  type DocumentInfo,
  type ModelInfo,
  type ResourceAction,
  type ResourceActivity,
  type TenantSettings,
  type TraceItem,
  type TurnUsage,
  type UsageInfo,
} from "./api";
import { type LiveActivity } from "./ActivityTimeline";
import { AudioChips, type AudioAttachment } from "./AudioChips";
import { ChatsPanel } from "./ChatsPanel";
import { DocumentChips, type DocumentAttachment } from "./DocumentChips";
import { ImageChips, type ImageAttachment } from "./ImageChips";
import { EgressApproval, type EgressDecision } from "./EgressApproval";
import { MessageList } from "./MessageList";
import { SettingsView } from "./SettingsView";
import { SidePanel } from "./SidePanel";

// Key for the not-yet-persisted "new" chat (before its conversation id exists).
const NEW_CHAT = "__new__";

// The unsent composer draft (typed text + attached images + done audio transcripts) is kept in
// sessionStorage so it survives a remount or reload. Without this, any session re-validation
// unmounts <Chat> (App shows the loading view) and the in-memory draft is silently lost (#369).
const DRAFT_KEY = "personalai_composer_draft";

// A persisted audio chip: only `done` chips (with a transcript) are saved — never the File,
// in-flight chips, error chips, or any AbortController (#406).
interface DraftAudio {
  id: string;
  name: string;
  transcript: string;
}

// A persisted image chip: only `done` chips (downsized src + description) are saved — never
// in-flight/error chips or any AbortController (#419).
interface DraftImage {
  id: string;
  src: string;
  description: string;
}

// A persisted document chip: extracted text + name (the small/large status is recomputed from the
// text on load, so it isn't stored). In-flight/error chips are never saved (#416).
interface DraftDocument {
  id: string;
  name: string;
  text: string;
}

interface ComposerDraft {
  input: string;
  images: DraftImage[];
  audio: DraftAudio[];
  documents: DraftDocument[];
}

function loadDraft(): ComposerDraft {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return { input: "", images: [], audio: [], documents: [] };
    const d = JSON.parse(raw) as Partial<ComposerDraft>;
    const documents = Array.isArray(d.documents)
      ? d.documents.filter(
          (doc): doc is DraftDocument =>
            !!doc &&
            typeof doc.id === "string" &&
            typeof doc.name === "string" &&
            typeof doc.text === "string",
        )
      : [];
    const audio = Array.isArray(d.audio)
      ? d.audio.filter(
          (a): a is DraftAudio =>
            !!a &&
            typeof a.id === "string" &&
            typeof a.name === "string" &&
            typeof a.transcript === "string",
        )
      : [];
    const images = Array.isArray(d.images)
      ? d.images.filter(
          (im): im is DraftImage =>
            !!im &&
            typeof im.id === "string" &&
            typeof im.src === "string" &&
            typeof im.description === "string",
        )
      : [];
    return {
      input: typeof d.input === "string" ? d.input : "",
      images,
      audio,
      documents,
    };
  } catch {
    return { input: "", images: [], audio: [], documents: [] };
  }
}

function saveDraft(draft: ComposerDraft): void {
  try {
    if (
      !draft.input &&
      draft.images.length === 0 &&
      draft.audio.length === 0 &&
      draft.documents.length === 0
    ) {
      sessionStorage.removeItem(DRAFT_KEY); // keep storage clean once the draft is empty/sent
      return;
    }
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch {
    // Quota exceeded (large base64 images) or storage disabled: degrade to the old in-memory-only
    // behaviour rather than throwing — the draft simply won't survive a remount in that case.
  }
}

// Turn a getUserMedia failure into a plain-language hint instead of a raw DOMException string.
export function micErrorMessage(e: unknown): string {
  const name = (e as { name?: string } | null)?.name;
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Microphone access was blocked. Allow microphone access in your browser, then try again.";
  if (name === "NotFoundError" || name === "DevicesNotFoundError")
    return "No microphone was found. Connect one and try again.";
  return `Microphone unavailable: ${String(e)}`;
}

// Friendlier message for a failed transcription (the upload cap returns HTTP 413).
export function transcribeErrorMessage(e: unknown): string {
  const msg = String(e);
  if (msg.includes("413")) return "That recording is too long. Try a shorter one.";
  return `Transcription failed: ${msg}`;
}

// Friendlier message for a failed image description (#419).
export function describeImageError(e: unknown): string {
  const msg = String(e);
  if (msg.includes("413")) return "That image is too large.";
  if (msg.includes("vision")) return "The default model isn't a vision model.";
  return "Couldn't describe the image.";
}

// Resource-activity helpers (#424): a stable per-chip UTC-seconds `ts` derived from the chip id (its
// `*_<base36 Date.now()>_*` prefix), so the SAME ts is used live (pre-turn cluster) and on submit
// (persisted) — keeping the timeline positionally stable across the live->persisted transition.
export function activityTsFromId(id: string): number {
  const parts = id.split("_");
  const ms = parts.length > 1 ? parseInt(parts[1], 36) : NaN;
  return Number.isFinite(ms) ? Math.round(ms / 1000) : Math.round(Date.now() / 1000);
}

// action -> the human label verb (mirrors ResourceIO.resourceLabel; kept local to avoid importing a
// presentation helper into the composer). The activity `text` is "{verb} — {ref}".
const ACTIVITY_VERB: Record<ResourceAction, string> = {
  image_described: "Described image",
  document_extracted: "Extracted document",
  audio_transcribed: "Transcribed audio",
};

function makeActivity(
  id: string,
  action: ResourceAction,
  ref: string,
  model: string | null | undefined,
  ms: number | null | undefined,
  error?: string,
): ResourceActivity {
  return {
    kind: "resource",
    action,
    text: `${ACTIVITY_VERB[action]} — ${ref}`,
    ref,
    ts: activityTsFromId(id),
    model: model ?? null,
    ms: ms ?? null,
    ...(error ? { status: "error", error } : {}),
  };
}

// Cap on attached images per turn, and the longest-edge a kept image is downscaled to (#419) — large
// enough to stay understandable, small enough to bound vision tokens, payload, and DB storage.
const MAX_IMAGES = 6;
// A document whose extracted text is at/under this token estimate folds inline; over it, the chip is
// gated `large` and NOT folded (Tier-2 ephemeral RAG is a later phase, #420). ~6k tokens ≈ 4-5 pages.
const DOC_INLINE_TOKEN_GATE = 6000;
const DOC_MIMES = new Set(["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain", "text/markdown"]);
const DOC_EXTS = /\.(pdf|docx|txt|md|markdown)$/i;
function isDocumentFile(f: File): boolean {
  return DOC_MIMES.has(f.type) || DOC_EXTS.test(f.name);
}
// Estimate tokens from chars (~4 chars/token) to decide the inline gate.
function docTokenEstimate(text: string): number {
  return Math.ceil(text.length / 4);
}
const IMAGE_MAX_EDGE = 1024;

/** Downscale an image file to a data-URL ONLY if its longest edge exceeds IMAGE_MAX_EDGE; otherwise
 * keep it as-is. Re-encodes a downscaled image as JPEG (~0.82) to shrink payload + stored size. The
 * downsized result is what's attached, described, sent, and persisted (#419). */
export async function downscaleImage(file: File): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as string);
    r.onerror = () => reject(new Error("read failed"));
    r.readAsDataURL(file);
  });
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => reject(new Error("decode failed"));
    el.src = dataUrl;
  });
  const longest = Math.max(img.naturalWidth, img.naturalHeight);
  if (!longest || longest <= IMAGE_MAX_EDGE) return dataUrl; // small enough — keep original bytes
  const scale = IMAGE_MAX_EDGE / longest;
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.naturalWidth * scale);
  canvas.height = Math.round(img.naturalHeight * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) return dataUrl; // no canvas support — fall back to the original
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.82);
}

/** A data-URL -> Blob (so the downsized image can be POSTed as multipart for description). */
function dataUrlToBlob(dataUrl: string): Blob {
  const [head, body] = dataUrl.split(",", 2);
  const mime = /data:([^;]+)/.exec(head)?.[1] ?? "image/jpeg";
  const bytes = atob(body ?? "");
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: mime });
}

// Seconds -> "m:ss" for the recording timer.
export function formatDuration(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** All per-conversation state, so chats stream independently and survive switching. */
interface ChatState {
  messages: ChatMessage[];
  citations: Record<number, Citation[]>;
  // Ordered reasoning + tool-step timeline per assistant message index.
  trace: Record<number, TraceItem[]>;
  usage: UsageInfo | null;
  // Running totals across every turn in this chat (tokens, wall-clock ms, turn count).
  totals: { tokens: number; ms: number; turns: number };
  // The context composition assembled for the latest turn (what went into the prompt).
  context: ContextBreakdown | null;
  // Per-turn context composition, keyed by assistant message index, so EVERY turn (not just the
  // latest) can show its "Context assembled" node in the activity timeline.
  contexts: Record<number, ContextBreakdown>;
  busy: boolean;
  // Set when a turn is suspended at the durable human gate (M8.1c), awaiting approve/reject.
  pending: ApprovalRequest | null;
}

const EMPTY_CHAT: ChatState = {
  messages: [],
  citations: {},
  trace: {},
  usage: null,
  totals: { tokens: 0, ms: 0, turns: 0 },
  context: null,
  contexts: {},
  busy: false,
  pending: null,
};

/** Set the latest turn's usage, attach it to its assistant message (for the per-message footer),
 * and fold it into the per-chat running totals. */
function withUsage(s: ChatState, u: UsageInfo): ChatState {
  const turn: TurnUsage = {
    prompt_tokens: u.prompt_tokens,
    completion_tokens: u.completion_tokens,
    total_tokens: u.total_tokens,
    elapsed_ms: u.elapsed_ms,
  };
  const messages = s.messages.slice();
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") {
      messages[i] = { ...messages[i], meta: { ...messages[i].meta, usage: turn } };
      break;
    }
  }
  return {
    ...s,
    messages,
    usage: u,
    totals: {
      tokens: s.totals.tokens + (u.total_tokens ?? 0),
      ms: s.totals.ms + (u.elapsed_ms ?? 0),
      turns: s.totals.turns + 1,
    },
  };
}

// These kinds stream as deltas; consecutive same-kind items are merged into one.
const STREAMING_KINDS = new Set(["reasoning", "plan", "critique"]);

/** Append a trace item in order, merging consecutive streamed deltas (reasoning/plan/critique). */
function appendTrace(list: TraceItem[] | undefined, item: TraceItem): TraceItem[] {
  const next = [...(list ?? [])];
  const last = next[next.length - 1];
  if (STREAMING_KINDS.has(item.kind) && last?.kind === item.kind) {
    next[next.length - 1] = { ...last, text: (last.text ?? "") + (item.text ?? "") };
  } else {
    next.push(item);
  }
  return next;
}

export function Chat({
  token,
  status = "connected",
  statusLabel = "",
  onToken,
}: {
  token: string;
  status?: string;
  statusLabel?: string;
  onToken?: (value: string) => void;
}): React.ReactElement {
  const [providers, setProviders] = useState<string[]>([]);
  const [provider, setProvider] = useState<string>("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string>("");
  // The tenant's saved settings, loaded once. The top-bar model selector is the single source of
  // truth and writes the chosen model back here as the persisted default, so it survives reloads.
  const settingsRef = useRef<TenantSettings | null>(null);
  const [files, setFiles] = useState<DocumentInfo[]>([]);
  const [useRag, setUseRag] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [useMemory, setUseMemory] = useState(true);
  const [useTools, setUseTools] = useState(true);
  const [approveTools, setApproveTools] = useState(true);
  // Default to "brief": reasoning on but bounded, so large reasoning models (e.g. 35B) don't
  // over-deliberate and appear to hang. "Off"/"Full" remain selectable.
  const [reasoning, setReasoning] = useState<"off" | "brief" | "full">("brief");
  const [incognito, setIncognito] = useState(false);
  // Two-view navigation: the chat workspace vs the full-width Settings view (#290 redesign).
  const [tab, setTab] = useState<"chat" | "settings">("chat");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [chatsCollapsed, setChatsCollapsed] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  // Per-conversation state, keyed by conversation id (NEW_CHAT for the unsaved one). Streams run
  // independently against their key, so switching chats never interrupts a generating answer.
  const [chats, setChats] = useState<Record<string, ChatState>>({});
  const [persistence, setPersistence] = useState(false);
  // The composer draft is restored from sessionStorage so a remount/reload (e.g. a session
  // re-validation that unmounts Chat) doesn't discard typed text or a staged attachment (#369).
  const [input, setInput] = useState(() => loadDraft().input);
  // Image attachment chips (#419): each attached image is downsized (if large) and described by the
  // vision model in the background. Only `done` chips (downsized src + description) restore from the
  // draft; in-flight/error are not. The downsized image + description are what get sent/persisted.
  const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>(() =>
    loadDraft().images.map((im) => ({
      id: im.id,
      src: im.src,
      description: im.description,
      status: "done" as const,
    })),
  );
  // One AbortController per in-flight description, keyed by chip id (removing a chip cancels it).
  const imageAbortRef = useRef<Map<string, AbortController>>(new Map());
  // Audio attachment chips (#406): each dropped audio file is transcribed in the background. Only
  // `done` chips are restored from the draft (as completed transcripts); in-flight/error are not.
  const [audioAttachments, setAudioAttachments] = useState<AudioAttachment[]>(() =>
    loadDraft().audio.map((a) => ({ id: a.id, name: a.name, status: "done" as const, transcript: a.transcript })),
  );
  // One AbortController per in-flight transcription, keyed by chip id, so removing a chip mid-flight
  // cancels its fetch. Never persisted.
  const audioAbortRef = useRef<Map<string, AbortController>>(new Map());
  // Document attachment chips (#416, tier-1 of #420): a dropped doc's text is extracted in the
  // background and gated small (folds inline) vs large (shown for read/copy, not folded). Restored
  // from the draft with the status recomputed from the text.
  const [documentAttachments, setDocumentAttachments] = useState<DocumentAttachment[]>(() =>
    loadDraft().documents.map((doc) => ({
      id: doc.id,
      name: doc.name,
      text: doc.text,
      status: docTokenEstimate(doc.text) <= DOC_INLINE_TOKEN_GATE ? "small" : "large",
    })),
  );
  const docAbortRef = useRef<Map<string, AbortController>>(new Map());
  // True while an image is being dragged over the composer (drop-to-attach affordance, #324).
  const [dragOver, setDragOver] = useState(false);
  // Voice input (M9.2): whether STT is configured, and the live recording state.
  const [transcribeEnabled, setTranscribeEnabled] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  // Soft, non-error STT feedback (amber): no-speech, or the one-time model-download hint.
  const [micNotice, setMicNotice] = useState<string | null>(null);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const recordTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const modelHintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // After a transcription, auto-send unless the user edits within a short grace period (M9.2c).
  const [autoSendIn, setAutoSendIn] = useState<number | null>(null);
  const autoSendTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sendRef = useRef<() => void>(() => {});
  const [error, setError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const activeKey = activeId ?? NEW_CHAT;
  const view = chats[activeKey] ?? EMPTY_CHAT;
  const { messages, citations, trace, usage, totals, contexts, busy, pending } = view;

  const patchChat = (key: string, fn: (s: ChatState) => ChatState): void => {
    setChats((prev) => ({ ...prev, [key]: fn(prev[key] ?? EMPTY_CHAT) }));
  };

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

  // Load the saved settings once so the model selector can persist the chosen default. If storage
  // is unavailable (no DB), persistence is silently skipped and selection stays session-only.
  useEffect(() => {
    fetchSettings(token)
      .then(({ settings }) => {
        settingsRef.current = settings;
      })
      .catch(() => {
        settingsRef.current = null;
      });
  }, [token]);

  // Persist the chosen model as the tenant default (best-effort; the selection still applies this
  // session even if the write fails). Merges into the loaded settings so other fields are preserved.
  function persistDefaultModel(name: string): void {
    const base = settingsRef.current;
    if (base === null || name === "") return;
    const next: TenantSettings = { ...base, default_model: name };
    settingsRef.current = next;
    void saveSettings(token, next).catch(() => undefined);
  }

  function onModelChange(name: string): void {
    setModel(name);
    persistDefaultModel(name);
  }

  useEffect(() => {
    let active = true;
    // Files require storage; if unavailable the list just stays empty (no hard error).
    fetchFiles(token)
      .then((f) => {
        if (!active) return;
        setFiles(f);
        // If documents are already present, default to using them (avoids silently
        // ungrounded answers after a reload).
        if (f.length > 0) setUseRag(true);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    let active = true;
    // Default "use my memory" on when there is anything remembered (mirrors the RAG default).
    fetchMemories(token)
      .then((m) => active && m.length > 0 && setUseMemory(true))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    let active = true;
    // Conversation history requires storage; if unavailable, persistence stays off.
    fetchConversations(token)
      .then((c) => {
        if (!active) return;
        setConversations(c);
        setPersistence(true);
      })
      .catch(() => active && setPersistence(false));
    return () => {
      active = false;
    };
  }, [token]);

  // Sticky-bottom auto-scroll: follow new content while the user is at the bottom; if they scroll
  // up, pause until they return to the bottom (then resume). `atBottom` also drives a jump button.
  const stickToBottom = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  function onMessagesScroll(): void {
    const el = listRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    stickToBottom.current = bottom;
    setAtBottom(bottom);
  }

  function scrollToBottom(): void {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    stickToBottom.current = true;
    setAtBottom(true);
  }

  useEffect(() => {
    if (stickToBottom.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, trace]);

  // Mirror the composer draft into sessionStorage so it survives a remount/reload (#369, #406).
  // send() clears the state, which writes an empty draft here and removes the stored key. Only the
  // `done` audio chips' transcripts are persisted (never the File / in-flight / error chips).
  useEffect(() => {
    const audio = audioAttachments
      .filter((a) => a.status === "done")
      .map((a) => ({ id: a.id, name: a.name, transcript: a.transcript }));
    const images = imageAttachments
      .filter((im) => im.status === "done")
      .map((im) => ({ id: im.id, src: im.src, description: im.description }));
    const documents = documentAttachments
      .filter((d) => d.status === "small" || d.status === "large")
      .map((d) => ({ id: d.id, name: d.name, text: d.text }));
    saveDraft({ input, images, audio, documents });
  }, [input, imageAttachments, audioAttachments, documentAttachments]);

  function newChat(): void {
    setChats((prev) => ({ ...prev, [NEW_CHAT]: EMPTY_CHAT }));
    setActiveId(null);
    setError(null);
  }

  async function openConversation(id: string): Promise<void> {
    setError(null);
    setActiveId(id);
    // If this chat is mid-stream, keep its live state; otherwise load from the server.
    if (chats[id]?.busy) return;
    try {
      const conv = await fetchConversation(token, id);
      // Rebuild the per-chat token/time totals from each persisted turn's usage, so they survive a
      // reload (and show the last turn in the meter).
      const totals = { tokens: 0, ms: 0, turns: 0 };
      let lastUsage: UsageInfo | null = null;
      for (const m of conv.messages) {
        const u = m.role === "assistant" ? m.meta?.usage : undefined;
        if (!u) continue;
        totals.tokens += u.total_tokens ?? 0;
        totals.ms += u.elapsed_ms ?? 0;
        totals.turns += 1;
        lastUsage = { ...u, context_limit: null }; // window % is only known live, not on reload
      }
      // If the chat started streaming while we were loading, keep its live state (don't clobber).
      setChats((prev) =>
        prev[id]?.busy
          ? prev
          : { ...prev, [id]: { ...EMPTY_CHAT, messages: conv.messages, totals, usage: lastUsage } },
      );
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function commitRename(id: string): Promise<void> {
    const title = renameDraft.trim();
    setRenamingId(null);
    if (!title) return;
    try {
      await renameConversation(token, id, title);
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function removeConversation(id: string): Promise<void> {
    try {
      await deleteConversation(token, id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      setChats((prev) => {
        const { [id]: _omit, ...rest } = prev;
        return rest;
      });
      if (id === activeId) newChat();
    } catch (e: unknown) {
      setError(String(e));
    }
  }

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

  async function onAllowHost(host: string): Promise<void> {
    // Allow-on-deny: add the host to the allowlist (the reasoning-pane prompt shows the outcome).
    try {
      await allowEgressHost(token, host);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  // Discover whether voice input (M9.2) and read-aloud (M9.3) are available.
  useEffect(() => {
    fetchTranscribeEnabled(token).then(setTranscribeEnabled, () => setTranscribeEnabled(false));
    fetchTtsEnabled(token).then(setTtsEnabled, () => setTtsEnabled(false));
  }, [token]);

  function cancelAutoSend(): void {
    if (autoSendTimerRef.current) {
      clearInterval(autoSendTimerRef.current);
      autoSendTimerRef.current = null;
    }
    setAutoSendIn(null);
  }

  // Grace period after a transcription: count down, then auto-send unless the user edited the text.
  // The remaining count lives in a closure ref, NOT in the setState updater: a state updater must be
  // pure, and React Strict Mode double-invokes it — which would fire the send (and create the
  // conversation) twice, leaving a duplicate empty chat. The timer callback runs once per tick, so
  // the side effects (send/cancel) belong here.
  function startAutoSend(seconds = 3): void {
    cancelAutoSend();
    let remaining = seconds;
    setAutoSendIn(remaining);
    autoSendTimerRef.current = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        cancelAutoSend();
        sendRef.current(); // reads the latest input via the ref (avoids a stale closure)
      } else {
        setAutoSendIn(remaining);
      }
    }, 1000);
  }

  useEffect(() => {
    // Clear every STT timer and abort any in-flight transcription / extraction on unmount.
    const aborts = audioAbortRef.current;
    const docAborts = docAbortRef.current;
    return () => {
      cancelAutoSend();
      stopRecordTimer();
      clearModelHint();
      aborts.forEach((c) => c.abort());
      aborts.clear();
      docAborts.forEach((c) => c.abort());
      docAborts.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function stopRecordTimer(): void {
    if (recordTimerRef.current) {
      clearInterval(recordTimerRef.current);
      recordTimerRef.current = null;
    }
  }

  function clearModelHint(): void {
    if (modelHintTimerRef.current) {
      clearTimeout(modelHintTimerRef.current);
      modelHintTimerRef.current = null;
    }
  }

  async function toggleRecording(): Promise<void> {
    if (recording) {
      recorderRef.current?.stop(); // the onstop handler transcribes
      return;
    }
    cancelAutoSend(); // a new recording supersedes a pending auto-send
    setMicNotice(null);
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        stopRecordTimer();
        setRecording(false);
        setTranscribing(true);
        // A slow transcription is almost always the one-time local-model download — surface that
        // after a few seconds so the wait doesn't look like a hang (the user hit this before).
        modelHintTimerRef.current = setTimeout(
          () =>
            setMicNotice(
              "Working… the first transcription downloads the speech model, which can take a minute.",
            ),
          4000,
        );
        try {
          const { text } = await transcribeAudio(token, new Blob(chunks, { type: "audio/webm" }));
          if (text) {
            setMicNotice(null);
            setInput((cur) => (cur ? `${cur} ${text}` : text));
            startAutoSend(); // auto-send after a grace period unless the user edits
          } else {
            setMicNotice("No speech detected — try again, a bit closer to the mic.");
          }
        } catch (e: unknown) {
          setError(transcribeErrorMessage(e));
        } finally {
          clearModelHint();
          setTranscribing(false);
        }
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
      setRecordSeconds(0);
      recordTimerRef.current = setInterval(() => setRecordSeconds((s) => s + 1), 1000);
    } catch (e: unknown) {
      setError(micErrorMessage(e));
    }
  }

  function onAttachImages(files: FileList | null): void {
    // Each image is downsized (if large) then described by the vision model in the BACKGROUND, so
    // the description shows on hover and (for non-vision models) augments the message (#419). Cap the
    // total count; ignore extras past the cap.
    const list = Array.from(files ?? []).filter((f) => f.type.startsWith("image/"));
    const room = Math.max(0, MAX_IMAGES - imageAttachments.length);
    for (const f of list.slice(0, room)) {
      const id = `img_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
      const controller = new AbortController();
      imageAbortRef.current.set(id, controller);
      void (async () => {
        let src: string;
        try {
          src = await downscaleImage(f);
        } catch {
          src = await new Promise<string>((resolve) => {
            const r = new FileReader();
            r.onload = () => resolve(r.result as string);
            r.readAsDataURL(f);
          });
        }
        setImageAttachments((cur) => [
          ...cur,
          { id, src, description: "", status: "describing", name: f.name },
        ]);
        try {
          const result = await describeImage(token, dataUrlToBlob(src), controller.signal);
          imageAbortRef.current.delete(id);
          setImageAttachments((cur) =>
            cur.map((c) =>
              c.id === id
                ? {
                    ...c,
                    status: "done",
                    description: result.description,
                    model: result.model,
                    ms: result.ms,
                  }
                : c,
            ),
          );
        } catch (e: unknown) {
          imageAbortRef.current.delete(id);
          if ((e as { name?: string } | null)?.name === "AbortError") return; // chip removed
          setImageAttachments((cur) =>
            cur.map((c) =>
              c.id === id ? { ...c, status: "error", error: describeImageError(e) } : c,
            ),
          );
        }
      })();
    }
  }

  // Remove an image chip: abort its in-flight description (if any) and drop it.
  function removeImage(id: string): void {
    const controller = imageAbortRef.current.get(id);
    if (controller) {
      controller.abort();
      imageAbortRef.current.delete(id);
    }
    setImageAttachments((cur) => cur.filter((c) => c.id !== id));
  }

  const doneImages = imageAttachments.filter((im) => im.status === "done");
  const imageDescribing = imageAttachments.some((im) => im.status === "describing");

  // Drag-drop audio (#406): each dropped audio file becomes a `transcribing` chip whose transcription
  // runs in the BACKGROUND (no composer hijack, no auto-send). On resolve the chip becomes `done`
  // (or `empty` when blank); on error it becomes `error`. An abort (chip removed mid-flight) silently
  // drops the chip. The transcript is folded into the message on send() and is copyable from the chip.
  function onAudioFiles(files: File[]): void {
    for (const file of files) {
      const id = `aud_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
      const controller = new AbortController();
      audioAbortRef.current.set(id, controller);
      setAudioAttachments((cur) => [
        ...cur,
        { id, name: file.name, status: "transcribing", transcript: "" },
      ]);
      void transcribeAudio(token, file, file.name, controller.signal)
        .then(({ text, model, ms }) => {
          audioAbortRef.current.delete(id);
          setAudioAttachments((cur) =>
            cur.map((c) =>
              c.id === id
                ? text
                  ? { ...c, status: "done", transcript: text, model, ms }
                  : { ...c, status: "empty", transcript: "", model, ms }
                : c,
            ),
          );
        })
        .catch((e: unknown) => {
          audioAbortRef.current.delete(id);
          // Abort -> the chip was already removed; do not resurrect it as an error.
          if ((e as { name?: string } | null)?.name === "AbortError") return;
          setAudioAttachments((cur) =>
            cur.map((c) =>
              c.id === id ? { ...c, status: "error", error: transcribeErrorMessage(e) } : c,
            ),
          );
        });
    }
  }

  // Remove a chip: abort its in-flight transcription (if any) and drop it from the row.
  function removeAudio(id: string): void {
    const controller = audioAbortRef.current.get(id);
    if (controller) {
      controller.abort();
      audioAbortRef.current.delete(id);
    }
    setAudioAttachments((cur) => cur.filter((c) => c.id !== id));
  }

  const doneAudio = audioAttachments.filter((a) => a.status === "done");
  const audioTranscribing = audioAttachments.some((a) => a.status === "transcribing");

  // Extract text from each dropped document; gate small (folds) vs large (shown, not folded) (#416).
  function onDocumentFiles(files: File[]): void {
    for (const file of files) {
      const id = `doc_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
      const controller = new AbortController();
      docAbortRef.current.set(id, controller);
      setDocumentAttachments((cur) => [
        ...cur,
        { id, name: file.name, status: "extracting", text: "" },
      ]);
      void extractDocument(token, file, controller.signal)
        .then((doc) => {
          docAbortRef.current.delete(id);
          const status = docTokenEstimate(doc.text) <= DOC_INLINE_TOKEN_GATE ? "small" : "large";
          setDocumentAttachments((cur) =>
            cur.map((c) => (c.id === id ? { ...c, status, text: doc.text, ms: doc.ms } : c)),
          );
        })
        .catch((e: unknown) => {
          docAbortRef.current.delete(id);
          if ((e as { name?: string } | null)?.name === "AbortError") return;
          setDocumentAttachments((cur) =>
            cur.map((c) => (c.id === id ? { ...c, status: "error", error: String(e) } : c)),
          );
        });
    }
  }

  function removeDocument(id: string): void {
    const controller = docAbortRef.current.get(id);
    if (controller) {
      controller.abort();
      docAbortRef.current.delete(id);
    }
    setDocumentAttachments((cur) => cur.filter((c) => c.id !== id));
  }

  // Only SMALL docs fold into the message; large ones are ingested at send (Tier-2 RAG, #436/#420).
  const smallDocs = documentAttachments.filter((d) => d.status === "small");
  // LARGE docs (over the inline gate) are sent as `documents_full` for conversation-scoped RAG
  // ingest-at-send: the backend chunks+embeds them before retrieval and answers with citations (#436).
  const largeDocs = documentAttachments.filter((d) => d.status === "large");
  // Both small AND large docs have extracted text -> both get a transcript chip (#426); only the
  // model-facing fold differs (small folds inline, large doesn't). Errors/extracting are excluded.
  const doneDocs = documentAttachments.filter((d) => d.status === "small" || d.status === "large");
  const docExtracting = documentAttachments.some((d) => d.status === "extracting");

  // Live pre-turn resource activities (#424): mirror each chip's state machine into the Activity
  // panel's "Preparing your message" cluster. A removed chip drops out automatically (it's gone from
  // the source array). The SAME items (minus the live `state`) are submitted on send below.
  const liveActivities: LiveActivity[] = [
    ...imageAttachments.map((im): LiveActivity => ({
      ...makeActivity(im.id, "image_described", im.name ?? "image", im.model, im.ms, im.error),
      state: im.status === "describing" ? "in-progress" : im.status === "error" ? "error" : "done",
    })),
    ...audioAttachments.map((a): LiveActivity => ({
      ...makeActivity(a.id, "audio_transcribed", a.name, a.model, a.ms, a.error),
      state: a.status === "transcribing" ? "in-progress" : a.status === "error" ? "error" : "done",
    })),
    ...documentAttachments.map((d): LiveActivity => ({
      ...makeActivity(d.id, "document_extracted", d.name, null, d.ms, d.error),
      state: d.status === "extracting" ? "in-progress" : d.status === "error" ? "error" : "done",
    })),
  ];

  async function send(): Promise<void> {
    cancelAutoSend();
    const typed = input.trim();
    // Only `done` images go out (downsized src + description); in-flight/error are excluded.
    const imgs = doneImages;
    const images = imgs.map((im) => im.src);
    const descriptions = imgs.map((im) => im.description);
    const isVision = models.find((m) => m.name === model)?.capabilities.vision ?? false;
    // Fold each `done` audio chip's transcript into the outgoing content (Option (b), #406).
    const audioBlocks = doneAudio.map((a) => `[Audio: ${a.name}]\n${a.transcript}`).join("\n\n");
    // Augment-not-replace (#419): a vision model receives the image itself, so don't fold its
    // description; a NON-vision model can't see the image, so fold the descriptions as a fallback.
    const imageBlocks =
      !isVision && descriptions.some(Boolean)
        ? descriptions.filter(Boolean).map((d) => `[Image: ${d}]`).join("\n\n")
        : "";
    // Fold each SMALL document's text inline (#416); large docs are not folded (Tier-2 RAG, #420).
    const docBlocks = smallDocs.map((d) => `[Document: ${d.name}]\n${d.text}`).join("\n\n");
    const content = [typed, audioBlocks, imageBlocks, docBlocks].filter(Boolean).join("\n\n");
    // Display-vs-model split (#426): the bubble renders the original typed prompt + attachment chips,
    // NOT the folded `content` (which still goes to the model above). Build the structured display
    // arrays from THIS turn's done attachments. Documents include both small (folded) AND large
    // (not folded) — the chip lets the user read/copy either; only the fold differs.
    const documents = doneDocs.map((d) => ({ name: d.name, text: d.text }));
    // Tier-2 ingest-at-send (#436): large docs carry their FULL text in `documents_full` so the
    // backend ingests them into the conversation RAG index before retrieval. The `documents` chip
    // entry above still keeps the large doc's text for the transcript display chip on reload.
    const documentsFull = largeDocs.map((d) => ({ name: d.name, text: d.text }));
    const audio = doneAudio.map((a) => ({ name: a.name, transcript: a.transcript }));
    // Allow sending with only an image or only a transcript (no typed text). Block while a chip is
    // still transcribing/describing (the Send button is also disabled).
    if (
      (!content && images.length === 0) ||
      !model ||
      view.busy ||
      audioTranscribing ||
      imageDescribing ||
      docExtracting
    )
      return;
    setError(null);
    setInput("");
    setImageAttachments([]);
    setAudioAttachments([]);
    setDocumentAttachments([]);

    // Snapshot the buffered resource activities for THIS turn (#424): every terminal live activity
    // becomes a persisted activity (strip the live-only `state`; the backend sanitizes them). The
    // pre-turn cluster is fed from the chip arrays, which we clear above, so it vanishes on submit and
    // the same items re-render under the committed turn from the persisted `meta["activities"]`.
    const turnActivities: ResourceActivity[] = liveActivities
      .filter((a) => a.state !== "in-progress")
      .map(({ state: _state, ...activity }) => activity);

    const startKey = activeId ?? NEW_CHAT;
    const userMsg: ChatMessage = {
      role: "user",
      content,
      // Display-vs-model split (#426): always carry the original typed prompt so the bubble renders
      // it (not the folded `content`) and the transcript takes the structural path. Empty for an
      // attachments-only turn -> the bubble shows just the chip strip, no empty line.
      displayContent: typed,
      ...(images.length ? { images, image_descriptions: descriptions } : {}),
      ...(documents.length ? { documents } : {}),
      ...(documentsFull.length ? { documents_full: documentsFull } : {}),
      ...(audio.length ? { audio } : {}),
      ...(turnActivities.length ? { activities: turnActivities } : {}),
    };
    const history: ChatMessage[] = [...(chats[startKey]?.messages ?? []), userMsg];
    const assistantIndex = history.length;
    // Optimistically show the user turn + an empty assistant bubble and mark this chat busy.
    patchChat(startKey, (s) => ({
      ...s,
      messages: [...history, { role: "assistant", content: "" }],
      busy: true,
      usage: null,
    }));

    let targetId = activeId;
    let key = startKey;
    try {
      // Persist into a conversation (create lazily on the first message); migrate the optimistic
      // state from NEW_CHAT to the real id so streaming continues there.
      if (persistence && targetId === null) {
        const conv = await createConversation(token, (content || "Image").slice(0, 60), incognito);
        targetId = conv.id;
        key = conv.id;
        setChats((prev) => {
          const cur = prev[NEW_CHAT] ?? EMPTY_CHAT;
          const { [NEW_CHAT]: _omit, ...rest } = prev;
          return { ...rest, [conv.id]: cur };
        });
        setActiveId((cur) => (cur === null ? conv.id : cur)); // don't yank focus if user switched
        setConversations(await fetchConversations(token)); // show the new chat (with its marker)
      }

      let acc = "";
      await streamChat(
        {
          messages: history,
          model,
          provider,
          useRag,
          useMemory,
          useTools,
          approveTools,
          think: reasoning !== "off",
          reasoning,
          conversationId: targetId ?? undefined,
          token,
        },
        (delta) => {
          acc += delta;
          patchChat(key, (s) => ({ ...s, messages: [...history, { role: "assistant", content: acc }] }));
        },
        (cites) => patchChat(key, (s) => ({ ...s, citations: { ...s.citations, [assistantIndex]: cites } })),
        (step) => {
          // A tool call means the answer text streamed so far this turn was tool-use narration
          // (it's kept in the trace as reasoning); drop it from the answer bubble. The final turn
          // has no tool call, so its streamed answer stays.
          if (step.phase === "call") {
            acc = "";
            patchChat(key, (s) => ({
              ...s,
              messages: [...history, { role: "assistant", content: "" }],
            }));
          }
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], {
                kind: step.phase === "call" ? "tool_call" : "tool_result",
                tool: step.tool,
                args: step.args,
                ok: step.ok,
                output: step.output,
                error: step.error,
                ts: step.ts,
              }),
            },
          }));
        },
        (u) => patchChat(key, (s) => withUsage(s, u)),
        (delta, ts) =>
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], {
                kind: "reasoning",
                text: delta,
                ts,
              }),
            },
          })),
        (message) => {
          // Surface backend errors in the assistant bubble instead of silently ending the turn.
          acc = (acc ? acc + "\n\n" : "") + `**Error:** ${message}`;
          patchChat(key, (s) => ({
            ...s,
            messages: [...history, { role: "assistant", content: acc }],
          }));
        },
        (req) => {
          // Durable human gate (M8.1c): the turn is suspended; the proposed answer is already in the
          // bubble (acc). Stash the run so Approve/Reject can resume it.
          patchChat(key, (s) => ({ ...s, pending: req }));
        },
        (step) =>
          // M8 multi-agent flow: stream planner/critic steps into the live trace so the user can
          // follow which agent did what, in order with the researcher's tool/reasoning steps.
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], {
                kind: step.kind,
                text: step.text,
                ts: step.ts,
              }),
            },
          })),
        // The context composition for this turn, shown in the side panel as the question is asked.
        // Stored per assistant-message index (so EVERY turn keeps its own composition, not just the
        // latest), plus `context` for the live meter / back-compat.
        (ctx) =>
          patchChat(key, (s) => ({
            ...s,
            contexts: { ...s.contexts, [assistantIndex]: ctx },
            context: ctx,
          })),
        // M8.2 verifier (accurate mode): a verification step into the reasoning trace.
        (step) =>
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], {
                kind: "verification",
                text: step.text,
                verdict: step.verdict ?? null,
                ts: step.ts,
              }),
            },
          })),
        // The researcher's draft answer -> reasoning pane (#393), NOT the output bubble. Only
        // finalize's accepted answer fills the bubble (via onDelta), so a rejected draft never
        // appears in the output and the revision loop stays in the reasoning trace.
        (step) =>
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], {
                kind: "draft",
                text: step.text,
                attempt: step.attempt,
                ts: step.ts,
              }),
            },
          })),
        // RAG-pipeline prelude (#437): the backend replays indexing/retrieval/ner items as trace
        // frames BEFORE the agent loop, so appending them in arrival order lands them first in the
        // per-turn trace — matching the persisted, prepended meta["trace"] (live === reload).
        (item) =>
          patchChat(key, (s) => ({
            ...s,
            trace: {
              ...s.trace,
              [assistantIndex]: appendTrace(s.trace[assistantIndex], item),
            },
          })),
      );
      if (persistence) setConversations(await fetchConversations(token));
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      patchChat(key, (s) => ({ ...s, busy: false }));
    }
  }

  // The auto-send timer fires a stable ref so it always calls the latest send (current input).
  sendRef.current = () => void send();

  // Resolve a turn suspended at the durable human gate (M8.1c): resume with the decision, stream the
  // finalized answer into the same assistant bubble, and clear the pending state.
  async function resolveApproval(decision: "approve" | "reject"): Promise<void> {
    const key = activeKey;
    const cur = chats[key];
    if (!cur?.pending) return;
    const runId = cur.pending.run_id;
    const idx = cur.messages.length - 1; // the suspended assistant message
    setError(null);
    patchChat(key, (s) => ({ ...s, busy: true, pending: null }));
    try {
      await resumeChat(
        { runId, decision, conversationId: activeId ?? undefined, provider, token },
        (delta) => {
          // Resume re-delivers the full answer as one delta -> set the bubble content.
          patchChat(key, (s) => {
            const msgs = [...s.messages];
            msgs[idx] = { role: "assistant", content: delta };
            return { ...s, messages: msgs };
          });
        },
        (u) => patchChat(key, (s) => withUsage(s, u)),
        (message) => setError(message),
      );
      if (persistence) setConversations(await fetchConversations(token));
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      patchChat(key, (s) => ({ ...s, busy: false }));
    }
  }

  // Resolve a turn suspended at the durable egress gate (#377): a tool wanted to reach a
  // non-allowlisted host. Resume with the egress verb (the backend reads the host from the
  // checkpoint and re-runs the model on the chosen provider), stream the continuation into the same
  // assistant bubble, and clear the pending state. Mirrors resolveApproval (answer gate).
  async function resolveEgress(decision: EgressDecision): Promise<void> {
    const key = activeKey;
    const cur = chats[key];
    if (!cur?.pending) return;
    const runId = cur.pending.run_id;
    const idx = cur.messages.length - 1; // the suspended assistant message
    setError(null);
    patchChat(key, (s) => ({ ...s, busy: true, pending: null }));
    try {
      await resumeChat(
        { runId, decision, conversationId: activeId ?? undefined, provider, token },
        (delta) => {
          // Resume re-delivers the finalized answer as one delta -> set the bubble content.
          patchChat(key, (s) => {
            const msgs = [...s.messages];
            msgs[idx] = { role: "assistant", content: delta };
            return { ...s, messages: msgs };
          });
        },
        (u) => patchChat(key, (s) => withUsage(s, u)),
        (message) => setError(message),
      );
      if (persistence) setConversations(await fetchConversations(token));
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      patchChat(key, (s) => ({ ...s, busy: false }));
    }
  }

  const selected = models.find((m) => m.name === model);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", height: "100%" }}>
      {/* Row 1: top bar (non-collapsable) — identity, status, token, provider/model. */}
      <header
        data-testid="top-bar"
        style={{
          display: "flex",
          gap: "0.75rem",
          alignItems: "center",
          flexWrap: "wrap",
          borderBottom: "1px solid #ddd",
          paddingBottom: "0.5rem",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.3rem" }}>Personal AI</h1>
        {/* Chat | Settings view switch (two-tab navigation). */}
        <div role="tablist" aria-label="view" style={{ display: "flex", gap: "0.25rem" }}>
          {(["chat", "settings"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={tab === v}
              aria-current={tab === v ? "page" : undefined}
              data-testid={`nav-${v}`}
              onClick={() => setTab(v)}
              style={{
                padding: "0.25rem 0.6rem",
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: "0.9rem",
                fontWeight: tab === v ? 600 : 400,
                borderBottom: tab === v ? "2px solid #1a7f37" : "2px solid transparent",
              }}
            >
              {v === "chat" ? "Chat" : "Settings"}
            </button>
          ))}
        </div>
        {/* Backend health as a color dot + label (green ok, red down, amber checking). */}
        <span
          data-testid="backend-status"
          data-status={status}
          title={statusLabel}
          style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", fontSize: "0.85rem", color: "#555" }}
        >
          <span
            aria-hidden
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background:
                status === "connected" ? "#1a7f37" : status === "loading" ? "#b06f00" : "#b00",
            }}
          />
          {statusLabel}
        </span>
        {/* Model selection is a Chat-view concern (per-turn); hidden on the Settings view. */}
        {tab === "chat" && (
          <>
            <label htmlFor="model" style={{ marginLeft: "auto", fontSize: "0.85rem", color: "#555" }}>
              Model
            </label>
            <select
              id="model"
              data-testid="model-select"
              value={model}
              onChange={(e) => onModelChange(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
            {/* The provider selector only appears when more than one is configured (local-first:
                usually just Ollama, so it stays out of the way). */}
            {providers.length > 1 && (
              <select
                data-testid="provider-select"
                aria-label="provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            )}
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
          </>
        )}
      </header>

      {tab === "settings" ? (
        <SettingsView
          token={token}
          onToken={onToken}
          files={files}
          uploading={uploading}
          onUpload={(f) => void onUpload(f)}
          onDelete={(id) => void onDelete(id)}
        />
      ) : (
        <div
          data-testid="workspace"
          style={{
            display: "flex",
            gap: "1rem",
            alignItems: "stretch",
            width: "100%",
            flex: 1,
            minHeight: 0,
          }}
        >
          {/* Column 1: chats (collapsible) */}
          <ChatsPanel
            collapsed={chatsCollapsed}
            setCollapsed={setChatsCollapsed}
            conversations={conversations}
            chats={chats}
            activeId={activeId}
            incognito={incognito}
            setIncognito={setIncognito}
            renamingId={renamingId}
            setRenamingId={setRenamingId}
            renameDraft={renameDraft}
            setRenameDraft={setRenameDraft}
            onNewChat={newChat}
            onOpen={(id) => void openConversation(id)}
            onCommitRename={(id) => void commitRename(id)}
            onRemove={(id) => void removeConversation(id)}
          />

          {/* Column 2: chat output + composer */}
          <section
            aria-label="chat"
            data-testid="chat-col"
            style={{ flex: 3, minWidth: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}
          >
            <MessageList
              messages={messages}
              trace={trace}
              citations={citations}
              busy={busy}
              ttsEnabled={ttsEnabled}
              listRef={listRef}
              onScroll={onMessagesScroll}
              onAllowHost={(host) => void onAllowHost(host)}
            />

            {!atBottom && (
              <button
                data-testid="scroll-bottom"
                onClick={scrollToBottom}
                style={{ alignSelf: "center", fontSize: "0.75rem", marginTop: "-0.25rem" }}
              >
                ↓ Jump to latest
              </button>
            )}

            {pending && pending.reason === "egress_approval" ? (
              <EgressApproval
                host={pending.blocked_host!}
                tool={pending.tool}
                args={pending.args}
                busy={busy}
                onResolve={(d) => void resolveEgress(d)}
              />
            ) : pending ? (
              <div
                data-testid="approval-request"
                style={{
                  border: "1px solid #c90",
                  background: "#fff8e1",
                  borderRadius: "0.4rem",
                  padding: "0.5rem 0.75rem",
                  fontSize: "0.85rem",
                }}
              >
                <strong>Approval needed</strong> — review the proposed answer before it is finalized.
                {/* The proposed (draft) answer lives in the reasoning trace, not the output bubble
                    (#393); show it here from the gate payload so the reviewer can see it. */}
                {pending.answer ? (
                  <div
                    data-testid="approval-answer"
                    style={{
                      margin: "0.35rem 0",
                      padding: "0.4rem 0.55rem",
                      background: "rgba(127,127,127,0.08)",
                      borderRadius: 4,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {pending.answer}
                  </div>
                ) : null}
                {pending.critique ? (
                  <p style={{ margin: "0.35rem 0", color: "#555" }}>Critique: {pending.critique}</p>
                ) : null}
                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.35rem" }}>
                  <button
                    data-testid="approve"
                    onClick={() => void resolveApproval("approve")}
                    disabled={busy}
                  >
                    Approve
                  </button>
                  <button
                    data-testid="reject"
                    onClick={() => void resolveApproval("reject")}
                    disabled={busy}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ) : null}

            {error && (
              <p data-testid="chat-error" style={{ color: "#b00" }}>
                {error}
              </p>
            )}

            {/* Live STT feedback (M9.2f): recording timer (red), transcribing state, and soft
                amber notices (model-download hint, no-speech). Keeps the user informed instead of
                a silent wait. */}
            {recording && (
              <p data-testid="recording-status" style={{ color: "#b00", fontSize: "0.82rem", margin: 0 }}>
                <span aria-hidden="true">● </span>
                Recording {formatDuration(recordSeconds)}
                {recordSeconds >= 60 && (
                  <span style={{ color: "#b06f00" }}>
                    {" "}
                    — long recordings take longer to transcribe.
                  </span>
                )}
              </p>
            )}
            {!recording && transcribing && (
              <p data-testid="transcribing-status" style={{ color: "#555", fontSize: "0.82rem", margin: 0 }}>
                Transcribing…
              </p>
            )}
            {micNotice && (
              <p data-testid="mic-notice" style={{ color: "#b06f00", fontSize: "0.82rem", margin: 0 }}>
                {micNotice}
              </p>
            )}

            {/* Grace period after a transcription (M9.2c): a visible 3-2-1 countdown auto-sends the
                transcript unless the user presses Stop (then they can edit) — editing also cancels. */}
            {autoSendIn !== null && (
              <div
                data-testid="autosend-banner"
                role="status"
                style={{
                  display: "flex",
                  gap: "0.6rem",
                  alignItems: "center",
                  fontSize: "0.85rem",
                  color: "#b06f00",
                  border: "1px solid #e6c200",
                  background: "#fff8e1",
                  borderRadius: 6,
                  padding: "0.35rem 0.6rem",
                }}
              >
                <span
                  data-testid="autosend-count"
                  aria-hidden="true"
                  style={{
                    fontSize: "1.2rem",
                    fontWeight: 700,
                    fontVariantNumeric: "tabular-nums",
                    minWidth: "1.2rem",
                    textAlign: "center",
                  }}
                >
                  {autoSendIn}
                </span>
                <span style={{ flex: 1 }}>Sending in {autoSendIn}… press Stop to edit.</span>
                <button
                  data-testid="autosend-cancel"
                  onClick={cancelAutoSend}
                  style={{ fontWeight: 600 }}
                >
                  Stop
                </button>
              </div>
            )}

            {/* Per-session controls strip: these are per-turn toggles, kept next to the composer. */}
            <div
              data-testid="session-controls"
              style={{
                display: "flex",
                gap: "0.75rem",
                alignItems: "center",
                flexWrap: "wrap",
                fontSize: "0.85rem",
                borderTop: "1px solid #eee",
                paddingTop: "0.4rem",
              }}
            >
              <label>
                <input
                  data-testid="rag-toggle"
                  type="checkbox"
                  checked={useRag}
                  onChange={(e) => setUseRag(e.target.checked)}
                />{" "}
                Use my documents
              </label>
              <label>
                <input
                  data-testid="tools-toggle"
                  type="checkbox"
                  checked={useTools}
                  onChange={(e) => setUseTools(e.target.checked)}
                />{" "}
                Use tools
              </label>
              {useTools && (
                <label title="Allow high-risk tools (e.g. http_fetch) to run this session">
                  <input
                    data-testid="approve-tools-toggle"
                    type="checkbox"
                    checked={approveTools}
                    onChange={(e) => setApproveTools(e.target.checked)}
                  />{" "}
                  approve high-risk
                </label>
              )}
              <label>
                <input
                  data-testid="memory-toggle"
                  type="checkbox"
                  checked={useMemory}
                  onChange={(e) => setUseMemory(e.target.checked)}
                />{" "}
                Use my memory
              </label>
              <label
                style={{ marginLeft: "auto" }}
                title="How much the model thinks before answering. Off = none; Brief = concise; Full = think freely (slower)."
              >
                Reasoning{" "}
                <select
                  data-testid="reasoning-select"
                  value={reasoning}
                  onChange={(e) => setReasoning(e.target.value as "off" | "brief" | "full")}
                >
                  <option value="off">Off</option>
                  <option value="brief">Brief</option>
                  <option value="full">Full</option>
                </select>
              </label>
            </div>
            {files.length > 0 && !useRag && (
              <span data-testid="rag-hint" style={{ color: "#b06f00", fontSize: "0.8rem" }}>
                Not using your documents — turn on “Use my documents” to ground answers.
              </span>
            )}

            {/* Audio attachment chips (#406): drag-drop audio is transcribed in the background; each
                done chip reveals its full transcript on hover/focus/click with a Copy button. */}
            <AudioChips chips={audioAttachments} onRemove={removeAudio} />

            {/* Attached image chips (#419): each is downsized + described by the vision model in the
                background; hover a done thumbnail for its description + a Copy button. Removable. */}
            <ImageChips chips={imageAttachments} onRemove={removeImage} />

            {/* Document attachment chips (#416): drag-drop a PDF/DOCX/txt/md; small docs fold into the
                message, large ones are gated (read/copy only) until Tier-2 retrieval (#420). */}
            <DocumentChips chips={documentAttachments} onRemove={removeDocument} />
            {imageAttachments.length > 0 && selected && !selected.capabilities.vision && (
              <span data-testid="vision-hint" style={{ color: "#b06f00", fontSize: "0.8rem" }}>
                The selected model isn’t a vision model — its description is sent as text instead.
              </span>
            )}

            <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
              {/* Drop images onto the composer to attach them (#324) — replaces the old button. */}
              <div
                data-testid="composer-dropzone"
                style={{ position: "relative", flex: 1 }}
                onDragOver={(e) => {
                  if (e.dataTransfer.types.includes("Files")) {
                    e.preventDefault();
                    setDragOver(true);
                  }
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  // Split the drop: images attach (as today); audio files each become a transcribing
                  // chip (#406). Anything else is ignored. Audio is drag-drop ONLY now.
                  onAttachImages(e.dataTransfer.files); // images only; non-images ignored here
                  const dropped = Array.from(e.dataTransfer.files);
                  if (transcribeEnabled) {
                    const audio = dropped.filter((f) => f.type.startsWith("audio/"));
                    if (audio.length) onAudioFiles(audio);
                  }
                  // Documents (PDF/DOCX/txt/md) → text extraction + the small/large inline gate (#416).
                  const docs = dropped.filter(isDocumentFile);
                  if (docs.length) onDocumentFiles(docs);
                }}
              >
                <textarea
                  data-testid="composer"
                  rows={4}
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    resize: "vertical",
                    font: "inherit",
                    padding: "0.4rem",
                    border: dragOver ? "2px dashed #1a7f37" : undefined,
                  }}
                  value={input}
                  placeholder="Type a message...  (Enter to send, Shift+Enter for a new line)"
                  onChange={(e) => {
                    cancelAutoSend(); // editing the transcript cancels the pending auto-send
                    setInput(e.target.value);
                  }}
                  onKeyDown={(e) => {
                    // Enter sends; Shift+Enter inserts a newline. Ignore Enter mid-IME composition
                    // (e.g. Japanese/Chinese input) so committing a candidate doesn't send.
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                />
                {/* Faint watermark hint that drag-and-drop is supported. */}
                <span
                  aria-hidden="true"
                  style={{
                    position: "absolute",
                    bottom: 6,
                    right: 10,
                    fontSize: "0.72rem",
                    color: "#aaa",
                    pointerEvents: "none",
                    userSelect: "none",
                  }}
                >
                  {transcribeEnabled ? "drag & drop images or audio here" : "drag & drop images here"}
                </span>
                {/* Drop-target overlay shown while dragging a file over the composer. */}
                {dragOver && (
                  <div
                    data-testid="drop-overlay"
                    style={{
                      position: "absolute",
                      inset: 0,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      background: "rgba(26,127,55,0.08)",
                      border: "2px dashed #1a7f37",
                      borderRadius: 4,
                      color: "#1a7f37",
                      fontSize: "0.85rem",
                      pointerEvents: "none",
                    }}
                  >
                    {transcribeEnabled
                      ? "Drop images, audio, or documents to attach"
                      : "Drop images or documents to attach"}
                  </div>
                )}
              </div>
              {/* Mic + Send stacked; symbol buttons with the description in the tooltip (monochrome
                  geometric glyphs, not emoji — record dot / stop / send). Audio FILES are added by
                  drag-drop only now (#406), so there is no file-picker button. */}
              <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                {transcribeEnabled && (
                  <button
                    data-testid="mic"
                    onClick={() => void toggleRecording()}
                    disabled={busy || transcribing}
                    aria-label={recording ? "Stop recording" : "Record voice (speech-to-text)"}
                    title={
                      transcribing
                        ? "Transcribing…"
                        : recording
                          ? "Stop recording"
                          : "Record voice (speech-to-text)"
                    }
                    style={{
                      fontSize: "1.1rem",
                      lineHeight: 1,
                      padding: "0.25rem 0.6rem",
                      // Record convention: red dot = record, red square = stop, muted while processing.
                      color: transcribing ? "#888" : "#b00",
                    }}
                  >
                    <span aria-hidden="true">{transcribing ? "…" : recording ? "■" : "●"}</span>
                  </button>
                )}
                <button
                  data-testid="send"
                  onClick={() => void send()}
                  disabled={
                    busy ||
                    transcribing ||
                    audioTranscribing ||
                    imageDescribing ||
                    docExtracting ||
                    !model ||
                    (input.trim() === "" &&
                      doneImages.length === 0 &&
                      doneAudio.length === 0 &&
                      smallDocs.length === 0)
                  }
                  aria-label="Send message"
                  title="Send message (Enter)"
                  style={{ fontSize: "1.1rem", lineHeight: 1, padding: "0.25rem 0.6rem" }}
                >
                  <span aria-hidden="true">{busy ? "…" : "↑"}</span>
                </button>
              </div>
              {/* Screen-reader-only live status: an aria-label swap on a button is not always
                  reannounced, so the recording/transcribing transition is voiced here. */}
              <span
                data-testid="mic-status"
                aria-live="polite"
                style={{
                  position: "absolute",
                  width: 1,
                  height: 1,
                  overflow: "hidden",
                  clip: "rect(0 0 0 0)",
                  whiteSpace: "nowrap",
                }}
              >
                {transcribing ? "Transcribing" : recording ? "Recording" : (micNotice ?? "")}
              </span>
            </div>
          </section>

          {/* Column 3: logs (collapsible) */}
          <SidePanel
            messages={messages}
            trace={trace}
            usage={usage}
            totals={totals}
            contexts={contexts}
            busy={busy}
            onAllowHost={(host) => void onAllowHost(host)}
            collapsed={sidebarCollapsed}
            setCollapsed={setSidebarCollapsed}
            liveActivities={liveActivities}
          />
        </div>
      )}

      <p data-testid="security-note" style={{ color: "#555", fontSize: "0.8rem" }}>
        Local-first: network egress is disabled by default; remote providers are opt-in.
      </p>
    </div>
  );
}
