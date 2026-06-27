import { useEffect, useState } from "react";

import {
  fetchEntities,
  fetchEntityDetail,
  type Entity,
  type EntityDetail,
  type EntityType,
} from "./api";
import { MUTED, RED } from "./folderUi";

// Entity category hue: fuchsia-plum, reused from NerIO (#437/#451) so the entity feature reads as one
// category across the activity timeline + this browser. AA ~5.2:1; distinct from tool violet.
const NER = "#a21caf";

// Fixed display order for the type groups + filter chips. "All" is prepended for the filter.
const TYPE_ORDER: EntityType[] = ["person", "org", "location", "date", "product", "event", "other"];
const TYPE_LABEL: Record<EntityType, string> = {
  person: "People",
  org: "Organizations",
  location: "Locations",
  date: "Dates",
  product: "Products",
  event: "Events",
  other: "Other",
};

interface EntityBrowserProps {
  token: string;
  // When provided (Knowledge > Graph tab), each entity gains an "Open in graph" affordance that
  // drives the ego-graph canvas. `focusedId` highlights the entity currently shown on the canvas so
  // the list (the accessible alternative) and the canvas stay in sync. Omitted everywhere else, so
  // the existing inline-expand behavior (Documents > Entities) is unchanged.
  onFocusEntity?: (id: string) => void;
  focusedId?: string | null;
}

function copyId(id: string): void {
  void navigator.clipboard?.writeText(id).catch(() => undefined);
}

/** The corpus-global entity browser (#451), a top-level Documents region. Lists entities grouped by
 * type with a type filter + debounced fuzzy name search (both server-driven via the entities API).
 * Clicking an entity inline-expands its detail: the documents it appears in (copy-id affordances) and
 * its knowledge-graph edges (relation -> other entity, navigable). No emoji; word+color; aria-live. */
export function EntityBrowser({ token, onFocusEntity, focusedId }: EntityBrowserProps): React.ReactElement {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [typeFilter, setTypeFilter] = useState<EntityType | "all">("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Debounce the name search (250ms) so typing doesn't re-query on every keystroke.
  useEffect(() => {
    const t = window.setTimeout(() => setSearch(searchInput), 250);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  // Server-driven list: re-fetch whenever the type filter or debounced search changes.
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchEntities(token, {
      type: typeFilter === "all" ? undefined : typeFilter,
      q: search.trim() || undefined,
    })
      .then((list) => active && setEntities(list))
      .catch(() => active && setError("Could not load entities."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [token, typeFilter, search]);

  function selectEntity(id: string): void {
    if (selectedId === id) {
      // Re-clicking the open entity collapses it.
      setSelectedId(null);
      setDetail(null);
      return;
    }
    setSelectedId(id);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    fetchEntityDetail(token, id)
      .then((d) => {
        // Guard against a stale response if the user clicked another entity meanwhile.
        setSelectedId((cur) => {
          if (cur === id) setDetail(d);
          return cur;
        });
      })
      .catch(() => setDetailError("Could not load entity detail."))
      .finally(() => setDetailLoading(false));
  }

  // Group the loaded entities by type, preserving the fixed type order; drop empty groups.
  const groups = TYPE_ORDER.map((type) => ({
    type,
    items: entities.filter((e) => e.type === type),
  })).filter((g) => g.items.length > 0);

  const narrowing = typeFilter !== "all" || search.trim() !== "";

  return (
    <section data-testid="entity-browser" aria-label="Entities" style={{ marginTop: "1rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.4rem" }}>
        <strong style={{ flex: 1, fontSize: "0.9rem", color: NER }}>Entities</strong>
        <span style={{ color: MUTED, fontSize: "0.74rem" }}>Knowledge graph</span>
      </div>
      <p style={{ color: MUTED, fontSize: "0.78rem", margin: "0 0 0.5rem" }}>
        People, organizations, places and more, extracted across all your documents as they are
        indexed.
      </p>

      {/* Type filter chips. */}
      <div
        role="group"
        aria-label="Filter entities by type"
        style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", marginBottom: "0.4rem" }}
      >
        {(["all", ...TYPE_ORDER] as const).map((t) => {
          const active = typeFilter === t;
          return (
            <button
              key={t}
              data-testid={`entity-filter-${t}`}
              type="button"
              aria-pressed={active}
              onClick={() => setTypeFilter(t)}
              style={{
                padding: "0.2rem 0.55rem",
                borderRadius: 12,
                border: `1px solid ${active ? NER : "#ddd"}`,
                background: active ? "rgba(162,28,175,0.08)" : "none",
                color: active ? NER : "#444",
                fontSize: "0.76rem",
                fontWeight: active ? 600 : 400,
                cursor: "pointer",
              }}
            >
              {t === "all" ? "All" : TYPE_LABEL[t]}
            </button>
          );
        })}
      </div>

      {/* Debounced fuzzy name search. */}
      <input
        data-testid="entity-search"
        type="search"
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
        placeholder="Search entity name…"
        aria-label="Search entities by name"
        style={{
          width: "100%",
          boxSizing: "border-box",
          padding: "0.3rem 0.5rem",
          border: "1px solid #ddd",
          borderRadius: 6,
          fontSize: "0.82rem",
          marginBottom: "0.5rem",
        }}
      />

      <div aria-live="polite" aria-busy={loading}>
        {loading ? (
          <p data-testid="entity-loading" role="status" style={{ color: MUTED, fontSize: "0.82rem" }}>
            Loading entities…
          </p>
        ) : error ? (
          <p data-testid="entity-error" role="alert" style={{ color: RED, fontSize: "0.82rem" }}>
            {error}
          </p>
        ) : groups.length === 0 ? (
          <p data-testid="entities-empty" style={{ color: MUTED, fontSize: "0.82rem" }}>
            {narrowing
              ? "No entities match."
              : "No entities yet — they're extracted as documents are indexed."}
          </p>
        ) : (
          <div data-testid="entity-groups">
            {groups.map((g) => (
              <div key={g.type} data-testid={`entity-group-${g.type}`} style={{ marginBottom: "0.6rem" }}>
                <div
                  style={{
                    fontSize: "0.74rem",
                    fontWeight: 600,
                    color: MUTED,
                    textTransform: "uppercase",
                    letterSpacing: "0.03em",
                    marginBottom: "0.25rem",
                  }}
                >
                  {TYPE_LABEL[g.type]} <span style={{ color: "#b0b0b0" }}>({g.items.length})</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                  {g.items.map((e) => {
                    const open = selectedId === e.id;
                    const focused = focusedId === e.id;
                    return (
                      <span
                        key={e.id}
                        data-testid="entity-chip-wrap"
                        style={{ display: "inline-flex", alignItems: "center", gap: "0.2rem" }}
                      >
                        <button
                          data-testid="entity-chip"
                          data-entity-id={e.id}
                          type="button"
                          aria-expanded={open}
                          aria-current={focused ? "true" : undefined}
                          onClick={() => selectEntity(e.id)}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "0.4rem",
                            padding: "0.22rem 0.5rem",
                            borderRadius: 14,
                            border: `1px solid ${focused ? NER : open ? NER : "#ddd"}`,
                            background: focused
                              ? "rgba(162,28,175,0.14)"
                              : open
                                ? "rgba(162,28,175,0.08)"
                                : "rgba(127,127,127,0.04)",
                            fontSize: "0.8rem",
                            cursor: "pointer",
                            color: "#333",
                            fontWeight: focused ? 600 : 400,
                          }}
                        >
                          <span style={{ fontWeight: 500 }}>{e.name}</span>
                          <span style={{ color: MUTED, fontSize: "0.72rem" }}>
                            {e.mention_count} {e.mention_count === 1 ? "mention" : "mentions"}
                          </span>
                        </button>
                        {onFocusEntity && (
                          <button
                            data-testid="entity-open-in-graph"
                            data-entity-id={e.id}
                            type="button"
                            onClick={() => onFocusEntity(e.id)}
                            title={`Open ${e.name} in graph`}
                            aria-label={`Open ${e.name} in graph`}
                            style={{
                              border: `1px solid ${focused ? NER : "#ddd"}`,
                              borderRadius: 10,
                              background: "none",
                              color: NER,
                              fontSize: "0.68rem",
                              padding: "0.1rem 0.4rem",
                              cursor: "pointer",
                            }}
                          >
                            Graph
                          </button>
                        )}
                      </span>
                    );
                  })}
                </div>

                {/* Inline detail expander, rendered under the group of the selected entity. */}
                {g.items.some((e) => e.id === selectedId) && (
                  <EntityDetailPanel
                    loading={detailLoading}
                    error={detailError}
                    detail={detail}
                    onSelectEntity={selectEntity}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** The inline detail for a selected entity: its source documents (copy-id affordances) and its
 * knowledge-graph edges ("relation -> other entity", the destination navigable). */
function EntityDetailPanel({
  loading,
  error,
  detail,
  onSelectEntity,
}: {
  loading: boolean;
  error: string | null;
  detail: EntityDetail | null;
  onSelectEntity: (id: string) => void;
}): React.ReactElement {
  return (
    <div
      data-testid="entity-detail"
      role="region"
      aria-label="Entity detail"
      aria-live="polite"
      style={{
        marginTop: "0.4rem",
        border: "1px solid #eee",
        borderLeft: `3px solid ${NER}`,
        borderRadius: 6,
        padding: "0.5rem 0.6rem",
        background: "rgba(162,28,175,0.03)",
      }}
    >
      {loading ? (
        <p data-testid="entity-detail-loading" role="status" style={{ color: MUTED, fontSize: "0.78rem", margin: 0 }}>
          Loading detail…
        </p>
      ) : error ? (
        <p data-testid="entity-detail-error" role="alert" style={{ color: RED, fontSize: "0.78rem", margin: 0 }}>
          {error}
        </p>
      ) : detail ? (
        <>
          <div style={{ marginBottom: "0.4rem" }}>
            <div style={{ fontSize: "0.74rem", fontWeight: 600, color: MUTED, marginBottom: "0.2rem" }}>
              Documents ({detail.documents.length})
            </div>
            {detail.documents.length === 0 ? (
              <span style={{ color: MUTED, fontSize: "0.78rem" }}>No source documents.</span>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
                {detail.documents.map((docId) => (
                  <button
                    key={docId}
                    data-testid="entity-document"
                    type="button"
                    onClick={() => copyId(docId)}
                    title={`Document ${docId} (click to copy id)`}
                    aria-label={`Copy document id ${docId}`}
                    style={{
                      border: "1px solid #ddd",
                      borderRadius: 5,
                      background: "none",
                      color: "#4a90d9",
                      fontSize: "0.72rem",
                      padding: "0 0.35rem",
                      cursor: "pointer",
                    }}
                  >
                    {docId}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            <div style={{ fontSize: "0.74rem", fontWeight: 600, color: MUTED, marginBottom: "0.2rem" }}>
              Related ({detail.edges.length})
            </div>
            {detail.edges.length === 0 ? (
              <span style={{ color: MUTED, fontSize: "0.78rem" }}>No relationships yet.</span>
            ) : (
              <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                {detail.edges.map((edge, i) => (
                  <li
                    key={`${edge.relation}-${edge.dst_entity_id}-${i}`}
                    data-testid="entity-edge"
                    style={{ fontSize: "0.78rem", padding: "0.1rem 0", display: "flex", alignItems: "center", gap: "0.3rem" }}
                  >
                    <span style={{ color: MUTED }}>{edge.relation}</span>
                    <span aria-hidden style={{ color: NER }}>{"->"}</span>
                    <button
                      data-testid="entity-edge-target"
                      type="button"
                      onClick={() => onSelectEntity(edge.dst_entity_id)}
                      style={{
                        border: "none",
                        background: "none",
                        color: NER,
                        fontSize: "0.78rem",
                        padding: 0,
                        cursor: "pointer",
                        textDecoration: "underline",
                      }}
                    >
                      {edge.dst_entity_id}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
