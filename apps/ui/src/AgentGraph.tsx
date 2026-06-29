import { AGENT_BG, AGENT_FG } from "./agentColors";

// Deterministic, hand-drawn SVG of how the agent team is wired. It is a pure render off props
// (no physics layout, no async state) so it redraws instantly when a setting is toggled and never
// jiggles or reflows. The topology mirrors core/graph.py:
//   single : User -> Assistant (tool loop) -> Answer
//   multi  : User -> Planner -> Researcher -> Critic -> [Verifier] -> [Gate] -> Answer,
//            with a bounded "revise" return loop to the researcher, and (when verifier_check is on)
//            an independent "fact-check" lookup off the LAST judge (verifier in accurate mode, else
//            the critic in standard mode — mirrors core/graph.py).
//   custom : placeholder (no defined topology yet).

type Mode = "single" | "multi" | "custom";
type AccuracyMode = "standard" | "accurate";

export interface AgentCollaborationGraphProps {
  mode: Mode;
  accuracyMode: AccuracyMode;
  humanGate: boolean;
  verifierCheck: boolean;
}

// --- geometry (viewBox units; the svg itself is width:100% so this just sets the aspect ratio) ---
const NODE_W = 86;
const NODE_H = 30;
const SPACING = 110; // x-distance between node centers along the main row
const LEFT_PAD = 55; // x of the first node center
const ROW_Y = 70; // y of the main left-to-right chain
const SOURCES_Y = 130; // y of the verifier's independent-lookup node (below the row)
const VB_HEIGHT = 160;

// --- color code (reuse agentColors; never hardcode the agent hues) ---
const NEUTRAL = { fill: "#f8fafc", stroke: "#94a3b8", text: "#475569" } as const;
const EDGE = "#475569"; // forward edges + their labels
const REVISE = "#9ca3af"; // dashed reflection loop, visually distinct from forward flow
const ROSE = AGENT_FG.verifier; // the verifier's independent fact-check lookup

const LABELS: Record<string, string> = {
  user: "User",
  planner: "Planner",
  researcher: "Researcher",
  critic: "Critic",
  verifier: "Verifier",
  gate: "Gate",
  answer: "Answer",
  assistant: "Assistant",
  sources: "Sources",
};

interface NodeSpec {
  key: string;
  cx: number;
  cy: number;
}

function colorFor(key: string): { fill: string; stroke: string; text: string } {
  if (key in AGENT_FG) return { fill: AGENT_BG[key], stroke: AGENT_FG[key], text: AGENT_FG[key] };
  // The single-agent worker reuses researcher gray; the independent-lookup node reuses verifier rose.
  if (key === "assistant")
    return { fill: AGENT_BG.researcher, stroke: AGENT_FG.researcher, text: AGENT_FG.researcher };
  if (key === "sources")
    return { fill: AGENT_BG.verifier, stroke: AGENT_FG.verifier, text: AGENT_FG.verifier };
  return { ...NEUTRAL };
}

function Node({ node }: { node: NodeSpec }): React.ReactElement {
  const c = colorFor(node.key);
  return (
    <g data-testid={`agent-node-${node.key}`}>
      <rect
        x={node.cx - NODE_W / 2}
        y={node.cy - NODE_H / 2}
        width={NODE_W}
        height={NODE_H}
        rx={6}
        fill={c.fill}
        stroke={c.stroke}
        strokeWidth={1.5}
      />
      <text
        x={node.cx}
        y={node.cy}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={11}
        fontWeight={600}
        fill={c.text}
      >
        {LABELS[node.key] ?? node.key}
      </text>
    </g>
  );
}

function ForwardEdge({
  from,
  to,
  label,
}: {
  from: NodeSpec;
  to: NodeSpec;
  label?: string;
}): React.ReactElement {
  const x1 = from.cx + NODE_W / 2;
  const x2 = to.cx - NODE_W / 2;
  const y = ROW_Y;
  return (
    <g data-testid={`agent-edge-${from.key}-${to.key}`}>
      <line
        x1={x1}
        y1={y}
        x2={x2}
        y2={y}
        stroke={EDGE}
        strokeWidth={1.5}
        markerEnd="url(#agc-arrow)"
      />
      {label && (
        <text x={(x1 + x2) / 2} y={y - 6} textAnchor="middle" fontSize={9} fill={EDGE}>
          {label}
        </text>
      )}
    </g>
  );
}

// Dashed return arrow arching above the row, from `from` back to the researcher. `peak` lets two
// loops (critic + verifier) sit at different heights so they don't overlap.
function ReviseEdge({
  from,
  to,
  peak,
}: {
  from: NodeSpec;
  to: NodeSpec;
  peak: number;
}): React.ReactElement {
  const sx = from.cx;
  const sy = from.cy - NODE_H / 2;
  const tx = to.cx;
  const ty = to.cy - NODE_H / 2;
  return (
    <g data-testid={`agent-edge-${from.key}-${to.key}`}>
      <path
        d={`M ${sx},${sy} C ${sx},${peak} ${tx},${peak} ${tx},${ty}`}
        fill="none"
        stroke={REVISE}
        strokeWidth={1.5}
        strokeDasharray="4 3"
        markerEnd="url(#agc-arrow-revise)"
      />
      <text x={(sx + tx) / 2} y={peak - 2} textAnchor="middle" fontSize={9} fill={REVISE}>
        revise
      </text>
    </g>
  );
}

function FactCheckEdge({ from, to }: { from: NodeSpec; to: NodeSpec }): React.ReactElement {
  const x = from.cx;
  return (
    <g data-testid={`agent-edge-${from.key}-${to.key}`}>
      <line
        x1={x}
        y1={from.cy + NODE_H / 2}
        x2={x}
        y2={to.cy - NODE_H / 2}
        stroke={ROSE}
        strokeWidth={1.5}
        markerEnd="url(#agc-arrow-rose)"
      />
      <text x={x + 6} y={(from.cy + to.cy) / 2} fontSize={9} fill={ROSE}>
        fact-check
      </text>
    </g>
  );
}

// Self-loop arcing above a node (the single-agent tool loop).
function ToolLoop({ node }: { node: NodeSpec }): React.ReactElement {
  const { cx } = node;
  const top = node.cy - NODE_H / 2;
  return (
    <g data-testid={`agent-edge-${node.key}-${node.key}`}>
      <path
        d={`M ${cx - 16},${top} C ${cx - 34},${top - 34} ${cx + 34},${top - 34} ${cx + 16},${top}`}
        fill="none"
        stroke={EDGE}
        strokeWidth={1.5}
        markerEnd="url(#agc-arrow)"
      />
      <text x={cx} y={top - 30} textAnchor="middle" fontSize={9} fill={EDGE}>
        tools
      </text>
    </g>
  );
}

function Defs(): React.ReactElement {
  const marker = (id: string, color: string): React.ReactElement => (
    <marker
      id={id}
      markerWidth={8}
      markerHeight={8}
      refX={7}
      refY={3}
      orient="auto"
      markerUnits="userSpaceOnUse"
    >
      <path d="M0,0 L7,3 L0,6 Z" fill={color} />
    </marker>
  );
  return (
    <defs>
      {marker("agc-arrow", EDGE)}
      {marker("agc-arrow-revise", REVISE)}
      {marker("agc-arrow-rose", ROSE)}
    </defs>
  );
}

function row(keys: string[]): NodeSpec[] {
  return keys.map((key, i) => ({ key, cx: LEFT_PAD + i * SPACING, cy: ROW_Y }));
}

/** A fixed, deterministic SVG of the current agent topology, driven purely by props (#290/#261). */
export function AgentCollaborationGraph({
  mode,
  accuracyMode,
  humanGate,
  verifierCheck,
}: AgentCollaborationGraphProps): React.ReactElement {
  if (mode === "custom") {
    return (
      <div
        data-testid="agent-collab-graph"
        role="img"
        aria-label="Custom agent graph — not configured yet"
        style={{
          height: VB_HEIGHT,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: "1px dashed #cbd5e1",
          borderRadius: 6,
          margin: "0 0 0.5rem",
          padding: "0.5rem",
          textAlign: "center",
          color: "#64748b",
          fontSize: "0.82rem",
        }}
      >
        <span data-testid="agent-graph-placeholder">
          Custom agent graph — configure agents and relations (coming soon)
        </span>
      </div>
    );
  }

  let nodes: NodeSpec[];
  const forwardEdges: { from: NodeSpec; to: NodeSpec; label?: string }[] = [];
  const reviseEdges: { from: NodeSpec; to: NodeSpec; peak: number }[] = [];
  let factCheck: { from: NodeSpec; to: NodeSpec } | null = null;
  let toolLoop: NodeSpec | null = null;
  let ariaLabel: string;

  if (mode === "single") {
    nodes = row(["user", "assistant", "answer"]);
    const [user, assistant, answer] = nodes;
    forwardEdges.push({ from: user, to: assistant }, { from: assistant, to: answer });
    toolLoop = assistant;
    ariaLabel = "Single-agent loop: user to a tool-using assistant to answer.";
  } else {
    // multi
    const accurate = accuracyMode === "accurate";
    const keys = ["user", "planner", "researcher", "critic"];
    if (accurate) keys.push("verifier");
    if (humanGate) keys.push("gate");
    keys.push("answer");
    nodes = row(keys);
    const byKey = (k: string): NodeSpec => nodes.find((n) => n.key === k)!;

    // Forward chain along the row; the hop into the gate is labeled "approval".
    for (let i = 0; i < nodes.length - 1; i += 1) {
      const from = nodes[i];
      const to = nodes[i + 1];
      forwardEdges.push({ from, to, label: to.key === "gate" ? "approval" : undefined });
    }

    // Bounded reflection loop: the critic (and verifier, in accurate mode) route back to research.
    const researcher = byKey("researcher");
    reviseEdges.push({ from: byKey("critic"), to: researcher, peak: 34 });
    if (accurate) reviseEdges.push({ from: byKey("verifier"), to: researcher, peak: 16 });

    // The final judge's independent lookup (when "Judge fact-check" is on): an extra rose
    // "fact-check" edge down to a Sources node. The verifier is the last judge in accurate mode;
    // the critic is the last judge in standard mode — mirrors core/graph.py (#465).
    const lastJudge = accurate ? "verifier" : "critic";
    if (verifierCheck) {
      const sources: NodeSpec = { key: "sources", cx: byKey(lastJudge).cx, cy: SOURCES_Y };
      nodes = [...nodes, sources];
      factCheck = { from: byKey(lastJudge), to: sources };
    }

    const stages = keys.filter((k) => k !== "user" && k !== "answer");
    ariaLabel =
      `Multi-agent pipeline: ${stages.join(", ")}` +
      (humanGate ? ", with a human approval gate" : "") +
      (verifierCheck ? `, and the ${lastJudge} runs an independent fact-check lookup` : "") +
      ". The critic feeds revisions back to the researcher.";
  }

  const lastCx = nodes.reduce((m, n) => Math.max(m, n.cx), 0);
  const vbWidth = lastCx + LEFT_PAD;

  return (
    <svg
      data-testid="agent-collab-graph"
      role="img"
      aria-label={ariaLabel}
      viewBox={`0 0 ${vbWidth} ${VB_HEIGHT}`}
      width="100%"
      height={VB_HEIGHT}
      preserveAspectRatio="xMidYMid meet"
      style={{
        display: "block",
        border: "1px solid #eee",
        borderRadius: 6,
        margin: "0 0 0.5rem",
        background: "#fff",
      }}
    >
      <Defs />
      {/* edges first so nodes paint on top */}
      {forwardEdges.map((e) => (
        <ForwardEdge key={`${e.from.key}-${e.to.key}`} from={e.from} to={e.to} label={e.label} />
      ))}
      {reviseEdges.map((e) => (
        <ReviseEdge key={`${e.from.key}-${e.to.key}`} from={e.from} to={e.to} peak={e.peak} />
      ))}
      {factCheck && <FactCheckEdge from={factCheck.from} to={factCheck.to} />}
      {toolLoop && <ToolLoop node={toolLoop} />}
      {nodes.map((n) => (
        <Node key={n.key} node={n} />
      ))}
    </svg>
  );
}
