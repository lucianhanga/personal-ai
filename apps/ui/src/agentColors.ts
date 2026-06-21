// Canonical per-agent color code, shared by the reasoning trace (MessageDetails) and the
// multi-agent graph config (Agents). No emoji; foreground accent + a very faded background per
// agent so each contributor is easy to delimit wherever it appears.
export const AGENT_FG: Record<string, string> = {
  planner: "#2563eb", // blue
  researcher: "#6b7280", // gray
  critic: "#b8860b", // amber
};

export const AGENT_BG: Record<string, string> = {
  planner: "#eef4ff",
  researcher: "#f3f4f6",
  critic: "#fcf7ea",
};
