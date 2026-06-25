import { useEffect, useRef, useState } from "react";

// Color code (project convention): green ok, amber warn/in-progress, red error, accent, muted.
const GREEN = "#1a7f37";
const AMBER = "#b06f00";
const RED = "#b00020";
const ACCENT = "#4a90d9";
const MUTED = "#6b7280";

export type ImageStatus = "describing" | "done" | "error";

export interface ImageAttachment {
  id: string;
  src: string; // data-URL of the (downsized) image
  description: string;
  status: ImageStatus;
  error?: string;
}

/** Classical "two overlapping rounded rectangles" copy glyph (monochrome SVG, not emoji). */
function CopyIcon(): React.ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

/** Check-mark glyph shown briefly after a successful copy (monochrome SVG, not emoji). */
function CheckIcon(): React.ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

/** Floating panel: the image's vision description (scrollable, bounded) + a Copy button. Dismissed
 * by the parent on Escape/click-away; this owns only the Copy state. */
function DescriptionPanel({ id, text }: { id: string; text: string }): React.ReactElement {
  const [copied, setCopied] = useState(false);
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard blocked (no permission / insecure context) — silently no-op.
    }
  }
  return (
    <div
      data-testid="image-panel"
      role="dialog"
      aria-label="Image description"
      onMouseDown={(e) => e.stopPropagation()}
      style={{
        position: "absolute",
        bottom: "calc(100% + 4px)",
        left: 0,
        zIndex: 20,
        minWidth: "18em",
        maxWidth: "min(28em, 80vw)",
        background: "#fff",
        border: "1px solid #e2e2e2",
        borderRadius: 8,
        boxShadow: "0 8px 24px rgba(0,0,0,0.14)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.45rem 0.6rem",
          borderBottom: "1px solid #eee",
          background: "rgba(127,127,127,0.04)",
        }}
      >
        <span style={{ color: "#333", fontWeight: 600, fontSize: "0.78rem", flex: 1 }}>
          Description
        </span>
        <button
          data-testid={`copy-image-${id}`}
          onClick={() => void copy()}
          aria-label="Copy description"
          title={copied ? "Copied" : "Copy"}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "1.7em",
            height: "1.7em",
            background: "none",
            border: "1px solid rgba(127,127,127,0.3)",
            borderRadius: 5,
            color: copied ? GREEN : MUTED,
            cursor: "pointer",
            padding: 0,
            flexShrink: 0,
            transition: "color 0.15s",
          }}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
        </button>
      </div>
      <div
        data-testid="image-desc"
        style={{
          maxHeight: "14em",
          overflow: "auto",
          fontSize: "0.82rem",
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          color: "#222",
          padding: "0.55rem 0.6rem",
        }}
      >
        {text}
      </div>
    </div>
  );
}

interface Thumb {
  id: string;
  src: string;
  description?: string;
  status?: ImageStatus;
  error?: string;
  onRemove?: () => void;
}

/** Shared image-thumbnail grid with a sticky description panel (opens on hover/focus/click; stays
 * open until Escape/click-away/re-click so the pointer can reach Copy). Used by the composer
 * (`ImageChips`, with status + remove) and the transcript (`TranscriptImages`, read-only). */
function ImageGrid({
  items,
  testid,
  thumbHeight = 56,
}: {
  items: Thumb[];
  testid: string;
  thumbHeight?: number;
}): React.ReactElement | null {
  const [openId, setOpenId] = useState<string | null>(null);
  const rowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (openId === null) return;
    function onDocMouseDown(e: MouseEvent): void {
      if (rowRef.current && !rowRef.current.contains(e.target as Node)) setOpenId(null);
    }
    function onKey(e: KeyboardEvent): void {
      if (e.key === "Escape") setOpenId(null);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [openId]);

  if (items.length === 0) return null;

  return (
    <div
      ref={rowRef}
      data-testid={testid}
      style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}
    >
      <style>{"@keyframes image-pulse{0%,100%{opacity:1}50%{opacity:0.3}}"}</style>
      {items.map((it) => {
        const canOpen = !!it.description && it.status !== "describing" && it.status !== "error";
        const open = canOpen && openId === it.id;
        const border =
          it.status === "error" ? RED : open ? ACCENT : "#ddd";
        return (
          <span
            key={it.id}
            data-testid="image-attachment"
            data-status={it.status ?? "static"}
            tabIndex={canOpen ? 0 : -1}
            onMouseEnter={() => canOpen && setOpenId(it.id)}
            onFocus={() => canOpen && setOpenId(it.id)}
            onClick={() => canOpen && setOpenId((cur) => (cur === it.id ? null : it.id))}
            style={{ position: "relative", display: "inline-block", cursor: canOpen ? "pointer" : "default" }}
          >
            <img
              src={it.src}
              alt={it.description ? "attachment (described)" : "attachment"}
              style={{
                height: thumbHeight,
                borderRadius: 4,
                border: `1px solid ${border}`,
                display: "block",
              }}
            />
            {/* Describing overlay (amber, pulsing). */}
            {it.status === "describing" && (
              <span
                role="status"
                aria-label="describing image"
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 4,
                  background: "rgba(0,0,0,0.35)",
                  color: "#fff",
                  fontSize: "0.7rem",
                }}
              >
                <span
                  aria-hidden="true"
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: AMBER,
                    animation: "image-pulse 1s ease-in-out infinite",
                  }}
                />
              </span>
            )}
            {/* Error badge. */}
            {it.status === "error" && (
              <span
                title={it.error ?? "description failed"}
                style={{
                  position: "absolute",
                  bottom: 2,
                  left: 2,
                  background: RED,
                  color: "#fff",
                  borderRadius: 3,
                  fontSize: "0.6rem",
                  padding: "0 3px",
                }}
              >
                !
              </span>
            )}
            {/* "described" affordance dot so users know there's something on hover. */}
            {canOpen && (
              <span
                aria-hidden="true"
                title="Hover for the description"
                style={{
                  position: "absolute",
                  bottom: 2,
                  left: 2,
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: GREEN,
                  boxShadow: "0 0 0 1.5px #fff",
                }}
              />
            )}
            {it.onRemove && (
              <button
                data-testid={`remove-image-${it.id}`}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  it.onRemove?.();
                }}
                title="Remove"
                aria-label="Remove image"
                style={{
                  position: "absolute",
                  top: -6,
                  right: -6,
                  borderRadius: "50%",
                  lineHeight: 1,
                  padding: "0 5px",
                }}
              >
                ×
              </button>
            )}
            {open && it.description && <DescriptionPanel id={it.id} text={it.description} />}
          </span>
        );
      })}
    </div>
  );
}

/** Composer image attachment chips (#419): downsized thumbnails, each described by the vision model
 * in the background. A `done` chip reveals its description on hover/focus/click with a Copy button;
 * a `describing` chip shows a pulsing overlay; an `error` chip a red badge. Removable. */
export function ImageChips({
  chips,
  onRemove,
}: {
  chips: ImageAttachment[];
  onRemove: (id: string) => void;
}): React.ReactElement | null {
  return (
    <ImageGrid
      testid="image-attachments"
      items={chips.map((c) => ({
        id: c.id,
        src: c.src,
        description: c.description,
        status: c.status,
        error: c.error,
        onRemove: () => onRemove(c.id),
      }))}
    />
  );
}

/** Read-only image grid for a sent message in the transcript (#419): the same hover-to-see-the-
 * description + copy, reconstructed from the persisted `images` + `image_descriptions`. */
export function TranscriptImages({
  images,
  descriptions,
}: {
  images: string[];
  descriptions?: string[];
}): React.ReactElement | null {
  return (
    <ImageGrid
      testid="msg-images"
      thumbHeight={160}
      items={images.map((src, i) => ({
        id: `ti-${i}`,
        src,
        description: descriptions?.[i] || undefined,
      }))}
    />
  );
}
