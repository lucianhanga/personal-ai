import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";

import { EntityBrowser } from "./EntityBrowser";
import {
  fetchDocumentEntities,
  fetchEntities,
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

// Shared visual tokens so the canvas frame, toolbar, legend, chips, and detail rail read as one
// cohesive panel. Neutral greys only; per-entity-type hues still come exclusively from TYPE_META.
const BORDER = "#e2e8f0"; // slate-200 hairline — every frame/divider in this view uses it
const PANEL_BG = "#fafbfc"; // very light panel fill
const INK = "#334155"; // slate-700 body text on chips/buttons
const CANVAS_H = 360; // canvas height, kept in sync between the frame and the ForceGraph2D prop

// Hover affordance for the chips + toolbar buttons. Inline styles can't express :hover, so a single
// scoped stylesheet carries only the hover transition; all base styles stay inline as before.
const GRAPH_CSS = `
.kg-chip{transition:background-color 120ms ease,border-color 120ms ease}
.kg-chip:hover{background-color:#f1f5f9;border-color:#cbd5e1}
.kg-btn{transition:background-color 120ms ease,border-color 120ms ease}
.kg-btn:hover{background-color:#f1f5f9;border-color:#cbd5e1}
`;

function GraphStyles(): React.ReactElement {
  return <style>{GRAPH_CSS}</style>;
}

// A cohesive small toolbar button (Fit/Reset), consistent with the rest of the app: neutral grey,
// white fill, text label, no icon/emoji. Hover comes from the `kg-btn` class.
const toolbarBtnStyle: React.CSSProperties = {
  border: `1px solid ${BORDER}`,
  borderRadius: 6,
  background: "#fff",
  color: INK,
  fontSize: "0.74rem",
  fontWeight: 500,
  padding: "0.2rem 0.65rem",
  cursor: "pointer",
  lineHeight: 1.4,
};

// A consistent section label for the detail rail (Documents / Co-occurring entities / ...).
const railHeadingStyle: React.CSSProperties = {
  fontSize: "0.68rem",
  fontWeight: 700,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: MUTED,
  margin: "0 0 0.3rem",
};

/** Translucent fill from a TYPE_META hex hue (for the focus halo) — keeps node color = type hue. */
function hexAlpha(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

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

// Minimal shapes for the pure label-selection helper, so it can be unit-tested without a canvas or a
// force-graph instance. A link's source/target may be a raw id (as we build it) or, once the engine
// has run, a node object — handle both.
interface LabelableNode {
  id: string;
  label: string;
  focus?: boolean;
}
interface LabelableLink {
  source: string | { id: string };
  target: string | { id: string };
}

/** Which node ids get a painted on-canvas label (G-A): always the focus node, plus the top `n` other
 * nodes by degree (incident-link count), ties broken by name. Everything else stays a bare dot with
 * the existing hover tooltip. Pure so the selection rule is unit-testable without rendering. */
export function pickLabeledNodeIds(
  nodes: LabelableNode[],
  links: LabelableLink[],
  n = 6,
): Set<string> {
  const ids = new Set<string>();
  const focus = nodes.find((node) => node.focus);
  if (focus) ids.add(focus.id);

  const endId = (e: string | { id: string }): string => (typeof e === "object" ? e.id : e);
  const degree = new Map<string, number>();
  for (const l of links) {
    const s = endId(l.source);
    const t = endId(l.target);
    degree.set(s, (degree.get(s) ?? 0) + 1);
    degree.set(t, (degree.get(t) ?? 0) + 1);
  }

  const others = nodes
    .filter((node) => !node.focus)
    .sort((a, b) => {
      const da = degree.get(a.id) ?? 0;
      const db = degree.get(b.id) ?? 0;
      if (db !== da) return db - da;
      return a.label.localeCompare(b.label);
    });
  for (const node of others.slice(0, Math.max(0, n))) ids.add(node.id);
  return ids;
}

function prefersReducedMotion(): boolean {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
}

/** Text-first legend rows for the size + edge-weight encodings (G-C). Word-only — no color or shape
 * carries meaning here, so it reads identically without color. A hairline separates it from the type
 * key above so the two read as one compact legend. */
function ScaleLegend(): React.ReactElement {
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: "0.3rem 1.25rem",
        paddingTop: "0.45rem",
        borderTop: `1px solid ${BORDER}`,
        fontSize: "0.7rem",
        color: MUTED,
      }}
    >
      <span data-testid="graph-legend-size">Dot size: fewer → more mentions</span>
      <span data-testid="graph-legend-edge">Line weight: 1 → more shared documents</span>
    </div>
  );
}

/** The type key + the size/edge scale rows, framed as one compact, aligned legend panel rather than
 * two stacked lines. Shared by both the cold-start and focused views. */
function LegendPanel(): React.ReactElement {
  return (
    <div
      style={{
        border: `1px solid ${BORDER}`,
        borderRadius: 8,
        background: PANEL_BG,
        padding: "0.5rem 0.6rem",
        display: "flex",
        flexDirection: "column",
        gap: "0.45rem",
      }}
    >
      <GraphLegend />
      <ScaleLegend />
    </div>
  );
}

/** Cold-start launcher (G-D): the corpus's most-mentioned entities as clickable chips, so a fresh
 * graph has an obvious first move instead of a single sentence. Clicking one focuses the graph. */
function TopEntities({
  entities,
  onFocusEntity,
}: {
  entities: Entity[];
  onFocusEntity: (id: string) => void;
}): React.ReactElement {
  const top = [...entities].sort((a, b) => b.mention_count - a.mention_count).slice(0, 12);
  return (
    <div data-testid="graph-top-entities">
      <p style={{ color: INK, fontSize: "0.82rem", fontWeight: 600, margin: "0 0 0.15rem" }}>
        Start the graph
      </p>
      <p style={{ color: MUTED, fontSize: "0.78rem", margin: "0 0 0.55rem" }}>
        Pick one of your most-mentioned entities to see how it connects.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
        {top.map((e) => (
          <button
            key={e.id}
            className="kg-chip"
            data-testid="graph-top-entity"
            data-entity-id={e.id}
            type="button"
            onClick={() => onFocusEntity(e.id)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.35rem",
              border: `1px solid ${BORDER}`,
              borderRadius: 999,
              background: "#fff",
              padding: "0.2rem 0.55rem",
              fontSize: "0.78rem",
              color: INK,
              cursor: "pointer",
            }}
          >
            <TypeBadge type={e.type} />
            <span>{e.name}</span>
            <span style={{ color: MUTED, fontSize: "0.72rem" }}>{e.mention_count}</span>
          </button>
        ))}
      </div>
    </div>
  );
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

  // Cold-start launcher (G-D): the most-mentioned entities to start the graph from when nothing is
  // focused. null = still loading; [] = a genuinely empty corpus (the graph-empty prompt).
  const [topEntities, setTopEntities] = useState<Entity[] | null>(null);
  const [topError, setTopError] = useState<string | null>(null);

  // ForceGraph2D imperative handle for the camera controls (G-B).
  const graphRef = useRef<ForceGraphMethods | undefined>(undefined);

  const reqRef = useRef(0);

  useEffect(() => {
    let active = true;
    setTopEntities(null);
    setTopError(null);
    fetchEntities(token, { limit: 50 })
      .then((es) => active && setTopEntities(es))
      .catch(() => active && setTopError("Could not load entities."));
    return () => {
      active = false;
    };
  }, [token]);

  function fitView(): void {
    graphRef.current?.zoomToFit(400, 40);
  }

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
  const labeledIds = useMemo(() => pickLabeledNodeIds(graph.nodes, graph.links, 6), [graph]);

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
        <GraphStyles />
        <LegendPanel />
        <div aria-live="polite" aria-busy={topEntities === null} style={{ marginTop: "0.75rem" }}>
          {topError ? (
            <p data-testid="graph-top-error" role="alert" style={{ color: RED, fontSize: "0.85rem" }}>
              {topError}
            </p>
          ) : topEntities === null ? (
            <p data-testid="graph-top-loading" role="status" style={{ color: MUTED, fontSize: "0.85rem" }}>
              Loading entities…
            </p>
          ) : topEntities.length === 0 ? (
            <div
              data-testid="graph-empty"
              style={{
                border: `1px solid ${BORDER}`,
                borderRadius: 8,
                background: PANEL_BG,
                padding: "1.1rem 0.9rem",
                textAlign: "center",
                color: MUTED,
                fontSize: "0.82rem",
                lineHeight: 1.5,
              }}
            >
              No entities yet — add documents to your corpus and they’ll appear here as they’re indexed.
            </div>
          ) : (
            <TopEntities entities={topEntities} onFocusEntity={onFocusEntity} />
          )}
        </div>
      </section>
    );
  }

  return (
    <section data-testid="ego-graph" aria-label="Entity graph">
      <GraphStyles />
      <LegendPanel />

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

            {/* Camera controls (G-B). Real buttons (keyboard-reachable, visible focus ring); the
                canvas itself stays aria-hidden, with the detail rail as the accessible equivalent. */}
            <div
              data-testid="graph-controls"
              style={{ display: "flex", gap: "0.4rem", margin: "0.4rem 0 0.5rem" }}
            >
              <button
                className="kg-btn"
                data-testid="graph-zoom-fit"
                type="button"
                onClick={fitView}
                aria-label="Fit the graph to the view"
                style={toolbarBtnStyle}
              >
                Fit
              </button>
              <button
                className="kg-btn"
                data-testid="graph-zoom-reset"
                type="button"
                onClick={fitView}
                aria-label="Reset the graph view"
                style={toolbarBtnStyle}
              >
                Reset
              </button>
            </div>

            {/* The visual graph. Decorative + redundant with the rail below -> aria-hidden. */}
            <div
              data-testid="graph-canvas"
              aria-hidden="true"
              style={{
                border: `1px solid ${BORDER}`,
                borderRadius: 10,
                background: PANEL_BG,
                height: CANVAS_H,
                overflow: "hidden",
              }}
            >
              <ForceGraph2D
                ref={graphRef}
                graphData={{ nodes: graph.nodes, links: graph.links }}
                height={CANVAS_H}
                nodeId="id"
                nodeVal="val"
                nodeLabel="label"
                nodeColor="color"
                linkColor={() => "#cbd5e1"}
                linkWidth={(l: LinkObject) => 1 + Math.min(4, ((l.weight as number) ?? 1) - 1)}
                cooldownTicks={reduced ? 0 : undefined}
                warmupTicks={reduced ? 0 : undefined}
                enableNodeDrag={!reduced}
                onEngineStop={fitView}
                onNodeClick={(n: NodeObject) => handleNodeClick(n as unknown as GraphNode)}
                nodeCanvasObjectMode={() => "replace"}
                nodeCanvasObject={(
                  node: NodeObject,
                  ctx: CanvasRenderingContext2D,
                  globalScale: number,
                ) => {
                  const n = node as unknown as GraphNode & { x?: number; y?: number };
                  const r = Math.max(3, n.val);
                  const x = n.x ?? 0;
                  const y = n.y ?? 0;
                  // Keep separators/rings a constant ~px regardless of the current zoom.
                  const hairline = 1.5 / globalScale;

                  // Focus halo: a soft category-hue glow so the focused node reads instantly,
                  // without overriding its type color.
                  if (n.focus) {
                    ctx.beginPath();
                    ctx.arc(x, y, r + 4, 0, 2 * Math.PI);
                    ctx.fillStyle = hexAlpha(NER, 0.15);
                    ctx.fill();
                  }

                  ctx.fillStyle = n.color;
                  if (n.kind === "document") {
                    ctx.fillRect(x - r, y - r, r * 2, r * 2);
                    // Thin white edge so overlapping squares separate cleanly.
                    ctx.lineWidth = hairline;
                    ctx.strokeStyle = "#ffffff";
                    ctx.strokeRect(x - r, y - r, r * 2, r * 2);
                  } else {
                    ctx.beginPath();
                    ctx.arc(x, y, r, 0, 2 * Math.PI);
                    ctx.fill();
                    // Thin white stroke so overlapping dots stay visually distinct.
                    ctx.lineWidth = hairline;
                    ctx.strokeStyle = "#ffffff";
                    ctx.stroke();
                    if (n.focus) {
                      ctx.beginPath();
                      ctx.arc(x, y, r + 2, 0, 2 * Math.PI);
                      ctx.lineWidth = 2 / globalScale;
                      ctx.strokeStyle = NER;
                      ctx.stroke();
                    }
                  }
                  // G-A: paint a name label only for the focus node + the top-degree neighbors
                  // (pickLabeledNodeIds); the long tail stays bare dots with the hover tooltip. A
                  // white text-halo keeps the label legible over edges and other nodes.
                  if (labeledIds.has(n.id)) {
                    const fontPx = Math.max(9, 11 / globalScale);
                    ctx.font = `${n.focus ? "600 " : ""}${fontPx}px sans-serif`;
                    ctx.textAlign = "center";
                    ctx.textBaseline = "top";
                    const ty = y + r + 2 / globalScale + 1;
                    ctx.lineJoin = "round";
                    ctx.lineWidth = 3 / globalScale;
                    ctx.strokeStyle = "rgba(255, 255, 255, 0.92)";
                    ctx.strokeText(n.label, x, ty);
                    ctx.fillStyle = "#1e293b";
                    ctx.fillText(n.label, x, ty);
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
      <div style={{ display: "inline-flex", border: `1px solid ${BORDER}`, borderRadius: 6, overflow: "hidden" }}>
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
  // One pill style shared by the co-occurring + document-entity chips so the rail reads consistently.
  const entityChipStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: "0.35rem",
    border: `1px solid ${BORDER}`,
    borderRadius: 999,
    background: "#fff",
    fontSize: "0.76rem",
    padding: "0.16rem 0.5rem",
    cursor: "pointer",
    color: INK,
  };
  // Each rail section after the header gets a hairline divider above it, so the hierarchy
  // (focus -> documents -> co-occurring entities) reads as distinct, scannable blocks.
  const sectionStyle: React.CSSProperties = {
    borderTop: `1px solid ${BORDER}`,
    paddingTop: "0.55rem",
    marginTop: "0.55rem",
  };
  return (
    <div
      data-testid="graph-detail"
      role="region"
      aria-label="Graph detail"
      style={{
        marginTop: "0.6rem",
        border: `1px solid ${BORDER}`,
        borderLeft: `3px solid ${TYPE_META[f.type].hue}`,
        borderRadius: 8,
        background: "#fff",
        padding: "0.65rem 0.75rem",
      }}
    >
      <div
        data-testid="graph-focus"
        aria-live="polite"
        style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "0.4rem 0.5rem" }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
          <TypeBadge type={f.type} />
          <strong style={{ fontSize: "0.95rem", color: INK }}>{f.name}</strong>
        </span>
        <span style={{ color: MUTED, fontSize: "0.74rem" }}>
          {TYPE_META[f.type].label} · {f.mention_count} {f.mention_count === 1 ? "mention" : "mentions"}
        </span>
      </div>

      {/* Documents the focus appears in. */}
      <div style={sectionStyle}>
        <div style={railHeadingStyle}>Documents ({nb.documents.length})</div>
        {nb.documents.length === 0 ? (
          <span data-testid="graph-docs-empty" style={{ color: MUTED, fontSize: "0.78rem" }}>
            No source documents.
          </span>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
            {nb.documents.map((d) => {
              const active = selDoc?.id === d.id;
              return (
                <button
                  key={d.id}
                  className="kg-chip"
                  data-testid="graph-doc"
                  data-doc-id={d.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelectDocument(d.id, d.name)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.35rem",
                    border: `1px solid ${active ? DOC_HUE : BORDER}`,
                    borderRadius: 6,
                    background: active ? "rgba(51,65,85,0.08)" : "#fff",
                    color: INK,
                    fontSize: "0.74rem",
                    fontWeight: active ? 600 : 400,
                    padding: "0.16rem 0.45rem",
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
      <div style={sectionStyle}>
        <div style={railHeadingStyle}>Co-occurring entities ({nb.neighbors.length})</div>
        {nb.neighbors.length === 0 ? (
          <span data-testid="graph-neighbors-empty" style={{ color: MUTED, fontSize: "0.78rem" }}>
            No co-occurring entities yet.
          </span>
        ) : (
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
            {nb.neighbors.map((n) => (
              <li key={n.entity.id}>
                <button
                  className="kg-chip"
                  data-testid="graph-neighbor"
                  data-entity-id={n.entity.id}
                  type="button"
                  onClick={() => onFocusEntity(n.entity.id)}
                  title={`Focus ${n.entity.name}`}
                  style={entityChipStyle}
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
        <div data-testid="graph-doc-detail" aria-live="polite" style={sectionStyle}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "0.4rem",
              marginBottom: "0.3rem",
            }}
          >
            <span style={railHeadingStyle}>Entities in “{selDoc.name}”</span>
            {onOpenInCorpus && (
              <button
                className="kg-btn"
                data-testid="graph-open-in-corpus"
                data-doc-id={selDoc.id}
                type="button"
                onClick={() => onOpenInCorpus(selDoc.id)}
                title={`Open “${selDoc.name}” in the Corpus chunk inspector`}
                style={{
                  border: `1px solid ${DOC_HUE}`,
                  borderRadius: 6,
                  background: "#fff",
                  color: INK,
                  fontSize: "0.72rem",
                  fontWeight: 600,
                  padding: "0.16rem 0.5rem",
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
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
              {docEntities.map((e) => (
                <button
                  key={e.id}
                  className="kg-chip"
                  data-testid="graph-doc-entity"
                  data-entity-id={e.id}
                  type="button"
                  onClick={() => onFocusEntity(e.id)}
                  style={entityChipStyle}
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
