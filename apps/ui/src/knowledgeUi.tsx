import type { EntityType } from "./api";

// Knowledge (KAG/RAG) palette + type metadata. Every entity type carries a hue AND a one-letter
// badge AND a full label so the graph/legend/corpus never encode meaning with color alone (color is
// only reinforcement; the word + badge carry it — color-blind safe). Hues are the ui-ux-designer's
// spec palette (AA on white). Document nodes are slate (a distinct SHAPE + neutral hue, not a type).
export const TYPE_META: Record<EntityType, { hue: string; badge: string; label: string }> = {
  person: { hue: "#1a6fb0", badge: "P", label: "Person" },
  org: { hue: "#6d28d9", badge: "O", label: "Organization" },
  location: { hue: "#0d7d7d", badge: "L", label: "Location" },
  date: { hue: "#8a6d00", badge: "D", label: "Date" },
  product: { hue: "#b3431a", badge: "R", label: "Product" },
  event: { hue: "#a21caf", badge: "E", label: "Event" },
  other: { hue: "#555555", badge: "?", label: "Other" },
};

// The document (RAG chunk source) node — a SQUARE in slate, distinguishing it from the entity
// circles by shape (not color), per the bipartite entity<->document model.
export const DOC_HUE = "#334155";

// Status hues for the corpus table / stat chips. Reuses the folder-source vocabulary: green = indexed
// (ok), amber = not indexed (warn). Never color-only — paired with the status word.
export const STATUS_OK = "#1a7f37";
export const STATUS_WARN = "#8a6d00";

// Fixed legend / grouping order (matches EntityBrowser's TYPE_ORDER). "other" trails.
export const TYPE_ORDER: EntityType[] = [
  "person",
  "org",
  "location",
  "date",
  "product",
  "event",
  "other",
];

/** Bucket an entity's mention_count into a node radius so heavily-mentioned entities read as larger
 * without letting one outlier dominate. Documents use a fixed mid size (see the graph builder). */
export function entityNodeVal(mentionCount: number): number {
  if (mentionCount <= 2) return 4;
  if (mentionCount <= 5) return 6;
  if (mentionCount <= 10) return 8;
  return 10;
}

/** A small word+color badge ("P" person, "O" org, ...) for legends and node labels. The single
 * letter is decorative reinforcement; callers always render the full label alongside it. */
export function TypeBadge({ type }: { type: EntityType }): React.ReactElement {
  const meta = TYPE_META[type];
  return (
    <span
      data-testid={`type-badge-${type}`}
      aria-hidden
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 16,
        height: 16,
        borderRadius: 4,
        background: meta.hue,
        color: "#fff",
        fontSize: "0.62rem",
        fontWeight: 700,
        flex: "0 0 auto",
      }}
    >
      {meta.badge}
    </span>
  );
}

/** The type legend: hue + one-letter badge + full label for each entity type, plus the document
 * (square/slate) node. Shared by the graph; never color-only (badge + word carry the meaning). */
export function GraphLegend(): React.ReactElement {
  return (
    <div
      data-testid="graph-legend"
      role="group"
      aria-label="Graph legend"
      style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", fontSize: "0.72rem", color: "#444" }}
    >
      {TYPE_ORDER.map((t) => (
        <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
          <TypeBadge type={t} />
          {TYPE_META[t].label}
        </span>
      ))}
      <span style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
        <span
          aria-hidden
          style={{ width: 14, height: 14, background: DOC_HUE, borderRadius: 2, flex: "0 0 auto" }}
        />
        Document
      </span>
    </div>
  );
}
