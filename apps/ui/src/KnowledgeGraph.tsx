import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type LinkObject, type NodeObject } from "react-force-graph-2d";

import { EntityBrowser } from "./EntityBrowser";
import {
  fetchDocumentEntities,
  fetchEntityNeighborhood,
  type Entity,
  type EntityNeighborhood,
  type EntityType,
} from "./api";
import { MUTED, RED } from "./folderUi";
import { DOC_HUE, GraphLegend, TYPE_META, TypeBadge, entityNodeVal } from "./knowledgeUi";

// Hard cap on rendered nodes so the canvas never becomes an unreadable hairball (research: node-link
// graphs read only up to a few hundred nodes). The server caps too; this is the client backstop.
const MAX_NODES = 200;

const NER = "#a21caf"; // entity-category hue, shared with EntityBrowser so the feature reads as one.

// A renderable graph node — an entity CIRCLE (colored by type) or a document SQUARE (slate). Shape,
// not color, distinguishes the two classes, so the graph is readable without color.
interface GraphNode {
  id: string;
  kind: "entity" | "document";
  etype?: EntityType;
  label: string;
  val: number;
  color: string;
  focus?: boolean;
}

interface GraphLink {
  source: string;
  target: string;
  weight?: number;
}

interface BuiltGraph {
  nodes: GraphNode[];
  links: GraphLink[];
  total: number; // nodes BEFORE the cap, so we can say "showing N of M"
}

// Two ego-graph projections (ui-ux-designer spec). Bipartite is the literal model (focus ->
// documents -> co-occurring entities). Co-occurrence COLLAPSES the documents away and draws the
// focus straight to each co-occurring entity, with edge weight = shared_documents — the meaningful
// entity-cluster view given that direct entity<->entity edges are sparse/empty.
export type GraphLayout = "bipartite" | "cooccurrence";

function buildGraph(nb: EntityNeighborhood | null, layout: GraphLayout): BuiltGraph {
  if (!nb) return { nodes: [], links: [], total: 0 };
  const f = nb.focus;
  const includeDocs = layout === "bipartite";
  const nodes: GraphNode[] = [
    {
      id: f.id,
      kind: "entity",
      etype: f.type,
      label: f.name,
      val: entityNodeVal(f.mention_count) + 2,
      color: TYPE_META[f.type].hue,
      focus: true,
    },
  ];
  const links: GraphLink[] = [];
  // Co-occurrence hides the document nodes, so they don't count toward the rendered total/cap.
  const total = 1 + (includeDocs ? nb.documents.length : 0) + nb.neighbors.length;

  // Capping priority: documents first (the bipartite backbone), then the strongest co-occurrences.
  let budget = MAX_NODES - 1;
  const docs = includeDocs ? nb.documents.slice(0, Math.max(0, budget)) : [];
  budget -= docs.length;
  const neighbors = [...nb.neighbors]
    .sort((a, b) => b.shared_documents - a.shared_documents)
    .slice(0, Math.max(0, budget));

  for (const d of docs) {
    const did = `doc:${d.id}`;
    nodes.push({ id: did, kind: "document", label: d.name, val: 5, color: DOC_HUE });
    links.push({ source: f.id, target: did });
  }
  for (const n of neighbors) {
    nodes.push({
      id: n.entity.id,
      kind: "entity",
      etype: n.entity.type,
      label: n.entity.name,
      val: entityNodeVal(n.entity.mention_count),
      color: TYPE_META[n.entity.type].hue,
    });
    // The focus -> neighbor edge carries the co-occurrence weight (shared_documents) in BOTH
    // layouts; in co-occurrence it is the only edge class, so it reads as the entity cluster.
    links.push({ source: f.id, target: n.entity.id, weight: n.shared_documents });
  }
  return { nodes, links, total };
}

function prefersReducedMotion(): boolean {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
}

interface KnowledgeGraphTabProps {
  token: string;
  // Graph -> Corpus deep link (lifted into KnowledgePanel): switch to the Corpus tab and open the
  // given document's chunk inspector. Omitted in standalone/tests that don't need the cross-tab jump.
  onOpenInCorpus?: (docId: string) => void;
}

/** Knowledge > Graph: the entity list/picker (EntityBrowser, also the accessible alternative) on the
 * left, the focus+context ego-graph on the right. Focus is lifted here so both the list and the
 * graph's own neighbor affordances can drive it. */
export function KnowledgeGraphTab({ token, onOpenInCorpus }: KnowledgeGraphTabProps): React.ReactElement {
  const [focusId, setFocusId] = useState<string | null>(null);

  return (
    <div
      data-testid="knowledge-graph-tab"
      style={{ display: "flex", gap: "1rem", alignItems: "flex-start", flexWrap: "wrap" }}
    >
      <div style={{ flex: "1 1 260px", minWidth: 240 }}>
        <EntityBrowser token={token} onFocusEntity={setFocusId} focusedId={focusId} />
      </div>
      <div style={{ flex: "2 1 360px", minWidth: 300 }}>
        <EgoGraph
          token={token}
          focusId={focusId}
          onFocusEntity={setFocusId}
          onOpenInCorpus={onOpenInCorpus}
        />
      </div>
    </div>
  );
}

interface EgoGraphProps {
  token: string;
  focusId: string | null;
  onFocusEntity: (id: string) => void;
  onOpenInCorpus?: (docId: string) => void;
}

/** The ego-graph canvas + legend + accessible detail rail for the focused entity. The canvas is
 * `aria-hidden`; the rail (documents + co-occurring entities, both keyboard-focusable buttons) is the
 * accessible path, and selection is announced via an aria-live region. */
function EgoGraph({ token, focusId, onFocusEntity, onOpenInCorpus }: EgoGraphProps): React.ReactElement {
  const [nb, setNb] = useState<EntityNeighborhood | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Projection toggle (ui-ux-designer spec). Default Bipartite (the literal model); Co-occurrence
  // collapses the document nodes to show the focus's entity cluster directly. Sticky across re-focus.
  const [layout, setLayout] = useState<GraphLayout>("bipartite");

  // Selected document within the focus's graph -> its entities (the "document's entities" rail view).
  const [selDoc, setSelDoc] = useState<{ id: string; name: string } | null>(null);
  const [docEntities, setDocEntities] = useState<Entity[] | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [docError, setDocError] = useState<string | null>(null);

  const reqRef = useRef(0);

  useEffect(() => {
    setSelDoc(null);
    setDocEntities(null);
    if (!focusId) {
      setNb(null);
      setError(null);
      setLoading(false);
      return;
    }
    const req = ++reqRef.current;
    setLoading(true);
    setError(null);
    setNb(null);
    fetchEntityNeighborhood(token, focusId)
      .then((data) => {
        if (reqRef.current === req) setNb(data);
      })
      .catch(() => {
        if (reqRef.current === req) setError("Could not load the graph.");
      })
      .finally(() => {
        if (reqRef.current === req) setLoading(false);
      });
  }, [token, focusId]);

  const graph = useMemo(() => buildGraph(nb, layout), [nb, layout]);

  function selectDocument(id: string, name: string): void {
    setSelDoc({ id, name });
    setDocEntities(null);
    setDocError(null);
    setDocLoading(true);
    fetchDocumentEntities(token, id)
      .then((es) => setDocEntities(es))
      .catch(() => setDocError("Could not load document entities."))
      .finally(() => setDocLoading(false));
  }

  // Canvas click -> shared selection: a document node opens its entities; another entity re-focuses.
  function handleNodeClick(node: GraphNode | undefined): void {
    if (!node) return;
    if (node.kind === "document") selectDocument(node.id.replace(/^doc:/, ""), node.label);
    else if (!node.focus) onFocusEntity(node.id);
  }

  const reduced = prefersReducedMotion();

  if (!focusId) {
    return (
      <section data-testid="ego-graph" aria-label="Entity graph">
        <GraphLegend />
        <p data-testid="graph-empty" style={{ color: MUTED, fontSize: "0.85rem", marginTop: "0.75rem" }}>
          Select an entity (or use “Graph” on a chip) to see how it connects to your documents and
          other entities.
        </p>
      </section>
    );
  }

  return (
    <section data-testid="ego-graph" aria-label="Entity graph">
      <GraphLegend />

      <div aria-live="polite" aria-busy={loading} style={{ marginTop: "0.5rem" }}>
        {loading ? (
          <p data-testid="graph-loading" role="status" style={{ color: MUTED, fontSize: "0.85rem" }}>
            Loading graph…
          </p>
        ) : error ? (
          <p data-testid="graph-error" role="alert" style={{ color: RED, fontSize: "0.85rem" }}>
            {error}
          </p>
        ) : nb ? (
          <>
            <LayoutToggle layout={layout} onChange={setLayout} />

            {graph.total > graph.nodes.length && (
              <p data-testid="graph-cap" style={{ color: MUTED, fontSize: "0.74rem", margin: "0 0 0.3rem" }}>
                Showing {graph.nodes.length} of {graph.total} nodes (largest connections first).
              </p>
            )}

            {/* The visual graph. Decorative + redundant with the rail below -> aria-hidden. */}
            <div
              data-testid="graph-canvas"
              aria-hidden="true"
              style={{
                border: "1px solid #eee",
                borderRadius: 8,
                background: "#fbfbfc",
                height: 340,
                overflow: "hidden",
              }}
            >
              <ForceGraph2D
                graphData={{ nodes: graph.nodes, links: graph.links }}
                height={340}
                nodeId="id"
                nodeVal="val"
                nodeLabel="label"
                nodeColor="color"
                linkColor={() => "#cbd5e1"}
                linkWidth={(l: LinkObject) => 1 + Math.min(4, ((l.weight as number) ?? 1) - 1)}
                cooldownTicks={reduced ? 0 : undefined}
                warmupTicks={reduced ? 0 : undefined}
                enableNodeDrag={!reduced}
                onNodeClick={(n: NodeObject) => handleNodeClick(n as unknown as GraphNode)}
                nodeCanvasObjectMode={() => "replace"}
                nodeCanvasObject={(node: NodeObject, ctx: CanvasRenderingContext2D) => {
                  const n = node as unknown as GraphNode & { x?: number; y?: number };
                  const r = Math.max(3, n.val);
                  const x = n.x ?? 0;
                  const y = n.y ?? 0;
                  ctx.fillStyle = n.color;
                  if (n.kind === "document") {
                    ctx.fillRect(x - r, y - r, r * 2, r * 2);
                  } else {
                    ctx.beginPath();
                    ctx.arc(x, y, r, 0, 2 * Math.PI);
                    ctx.fill();
                    if (n.focus) {
                      ctx.lineWidth = 2;
                      ctx.strokeStyle = NER;
                      ctx.stroke();
                    }
                  }
                }}
              />
            </div>

            <GraphDetailRail
              nb={nb}
              onSelectDocument={selectDocument}
              onFocusEntity={onFocusEntity}
              onOpenInCorpus={onOpenInCorpus}
              selDoc={selDoc}
              docEntities={docEntities}
              docLoading={docLoading}
              docError={docError}
            />
          </>
        ) : null}
      </div>
    </section>
  );
}

interface LayoutToggleProps {
  layout: GraphLayout;
  onChange: (layout: GraphLayout) => void;
}

/** The projection toggle: Bipartite (focus -> documents -> entities) vs Co-occurrence (documents
 * collapsed; focus -> entities weighted by shared documents). A 2-button segmented control; the
 * active option is `aria-pressed`. Color is reinforcement only — the labels carry the meaning. */
function LayoutToggle({ layout, onChange }: LayoutToggleProps): React.ReactElement {
  const options: { id: GraphLayout; label: string }[] = [
    { id: "bipartite", label: "Bipartite" },
    { id: "cooccurrence", label: "Co-occurrence" },
  ];
  return (
    <div
      data-testid="graph-layout-toggle"
      role="group"
      aria-label="Graph layout"
      style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.5rem" }}
    >
      <span style={{ fontSize: "0.74rem", color: MUTED }}>Layout</span>
      <div style={{ display: "inline-flex", border: "1px solid #ddd", borderRadius: 6, overflow: "hidden" }}>
        {options.map((o) => {
          const active = layout === o.id;
          return (
            <button
              key={o.id}
              data-testid={`graph-layout-${o.id}`}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(o.id)}
              style={{
                border: "none",
                background: active ? NER : "transparent",
                color: active ? "#fff" : "#555",
                fontSize: "0.74rem",
                fontWeight: active ? 600 : 400,
                padding: "0.16rem 0.5rem",
                cursor: "pointer",
              }}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface GraphDetailRailProps {
  nb: EntityNeighborhood;
  onSelectDocument: (id: string, name: string) => void;
  onFocusEntity: (id: string) => void;
  onOpenInCorpus?: (docId: string) => void;
  selDoc: { id: string; name: string } | null;
  docEntities: Entity[] | null;
  docLoading: boolean;
  docError: string | null;
}

/** The accessible alternative to the canvas: the focus entity, the documents it appears in (each
 * opens that document's entities), and its co-occurring entities (each re-focuses the graph). */
function GraphDetailRail({
  nb,
  onSelectDocument,
  onFocusEntity,
  onOpenInCorpus,
  selDoc,
  docEntities,
  docLoading,
  docError,
}: GraphDetailRailProps): React.ReactElement {
  const f = nb.focus;
  return (
    <div
      data-testid="graph-detail"
      role="region"
      aria-label="Graph detail"
      style={{
        marginTop: "0.6rem",
        border: "1px solid #eee",
        borderLeft: `3px solid ${TYPE_META[f.type].hue}`,
        borderRadius: 6,
        padding: "0.5rem 0.6rem",
      }}
    >
      <div
        data-testid="graph-focus"
        aria-live="polite"
        style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.4rem" }}
      >
        <TypeBadge type={f.type} />
        <strong style={{ fontSize: "0.9rem" }}>{f.name}</strong>
        <span style={{ color: MUTED, fontSize: "0.74rem" }}>
          {TYPE_META[f.type].label} · {f.mention_count} {f.mention_count === 1 ? "mention" : "mentions"}
        </span>
      </div>

      {/* Documents the focus appears in. */}
      <div style={{ marginBottom: "0.5rem" }}>
        <div style={{ fontSize: "0.74rem", fontWeight: 600, color: MUTED, marginBottom: "0.2rem" }}>
          Documents ({nb.documents.length})
        </div>
        {nb.documents.length === 0 ? (
          <span data-testid="graph-docs-empty" style={{ color: MUTED, fontSize: "0.78rem" }}>
            No source documents.
          </span>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
            {nb.documents.map((d) => {
              const active = selDoc?.id === d.id;
              return (
                <button
                  key={d.id}
                  data-testid="graph-doc"
                  data-doc-id={d.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelectDocument(d.id, d.name)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.3rem",
                    border: `1px solid ${active ? DOC_HUE : "#ddd"}`,
                    borderRadius: 5,
                    background: active ? "rgba(51,65,85,0.08)" : "none",
                    color: "#334155",
                    fontSize: "0.74rem",
                    padding: "0.12rem 0.4rem",
                    cursor: "pointer",
                  }}
                >
                  <span
                    aria-hidden
                    style={{ width: 9, height: 9, background: DOC_HUE, borderRadius: 1, flex: "0 0 auto" }}
                  />
                  {d.name}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Co-occurring entities (shared-document weight). */}
      <div>
        <div style={{ fontSize: "0.74rem", fontWeight: 600, color: MUTED, marginBottom: "0.2rem" }}>
          Co-occurring entities ({nb.neighbors.length})
        </div>
        {nb.neighbors.length === 0 ? (
          <span data-testid="graph-neighbors-empty" style={{ color: MUTED, fontSize: "0.78rem" }}>
            No co-occurring entities yet.
          </span>
        ) : (
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
            {nb.neighbors.map((n) => (
              <li key={n.entity.id}>
                <button
                  data-testid="graph-neighbor"
                  data-entity-id={n.entity.id}
                  type="button"
                  onClick={() => onFocusEntity(n.entity.id)}
                  title={`Focus ${n.entity.name}`}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.3rem",
                    border: "1px solid #ddd",
                    borderRadius: 14,
                    background: "rgba(127,127,127,0.04)",
                    fontSize: "0.76rem",
                    padding: "0.14rem 0.45rem",
                    cursor: "pointer",
                    color: "#333",
                  }}
                >
                  <TypeBadge type={n.entity.type} />
                  {n.entity.name}
                  <span style={{ color: MUTED, fontSize: "0.7rem" }}>
                    {n.shared_documents} shared
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Selected document -> its entities (the "document's entities" rail view). */}
      {selDoc && (
        <div
          data-testid="graph-doc-detail"
          aria-live="polite"
          style={{ marginTop: "0.5rem", borderTop: "1px solid #eee", paddingTop: "0.4rem" }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "0.4rem",
              marginBottom: "0.2rem",
            }}
          >
            <span style={{ fontSize: "0.74rem", fontWeight: 600, color: MUTED }}>
              Entities in “{selDoc.name}”
            </span>
            {onOpenInCorpus && (
              <button
                data-testid="graph-open-in-corpus"
                data-doc-id={selDoc.id}
                type="button"
                onClick={() => onOpenInCorpus(selDoc.id)}
                title={`Open “${selDoc.name}” in the Corpus chunk inspector`}
                style={{
                  border: `1px solid ${DOC_HUE}`,
                  borderRadius: 5,
                  background: "none",
                  color: "#334155",
                  fontSize: "0.72rem",
                  fontWeight: 600,
                  padding: "0.12rem 0.45rem",
                  cursor: "pointer",
                  flex: "0 0 auto",
                }}
              >
                Open in Corpus
              </button>
            )}
          </div>
          {docLoading ? (
            <span data-testid="graph-doc-loading" role="status" style={{ color: MUTED, fontSize: "0.78rem" }}>
              Loading…
            </span>
          ) : docError ? (
            <span data-testid="graph-doc-error" role="alert" style={{ color: RED, fontSize: "0.78rem" }}>
              {docError}
            </span>
          ) : docEntities && docEntities.length > 0 ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
              {docEntities.map((e) => (
                <button
                  key={e.id}
                  data-testid="graph-doc-entity"
                  data-entity-id={e.id}
                  type="button"
                  onClick={() => onFocusEntity(e.id)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.3rem",
                    border: "1px solid #ddd",
                    borderRadius: 14,
                    background: "rgba(127,127,127,0.04)",
                    fontSize: "0.76rem",
                    padding: "0.14rem 0.45rem",
                    cursor: "pointer",
                    color: "#333",
                  }}
                >
                  <TypeBadge type={e.type} />
                  {e.name}
                </button>
              ))}
            </div>
          ) : (
            <span data-testid="graph-doc-empty" style={{ color: MUTED, fontSize: "0.78rem" }}>
              No entities extracted from this document.
            </span>
          )}
        </div>
      )}
    </div>
  );
}
