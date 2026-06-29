import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { AgentCollaborationGraph } from "./AgentGraph";

test("single mode shows the assistant tool loop and no pipeline agents", () => {
  render(
    <AgentCollaborationGraph
      mode="single"
      accuracyMode="standard"
      humanGate={false}
      verifierCheck={false}
    />,
  );
  expect(screen.getByTestId("agent-collab-graph")).toBeInTheDocument();
  expect(screen.getByTestId("agent-node-assistant")).toBeInTheDocument();
  expect(screen.getByTestId("agent-node-user")).toBeInTheDocument();
  expect(screen.getByTestId("agent-node-answer")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-assistant-assistant")).toBeInTheDocument(); // tool loop
  expect(screen.queryByTestId("agent-node-planner")).not.toBeInTheDocument();
  expect(screen.queryByTestId("agent-node-critic")).not.toBeInTheDocument();
});

test("multi + standard shows planner/researcher/critic with the critic's fact-check, no verifier", () => {
  render(
    <AgentCollaborationGraph
      mode="multi"
      accuracyMode="standard"
      humanGate={false}
      verifierCheck={true}
    />,
  );
  expect(screen.getByTestId("agent-node-planner")).toBeInTheDocument();
  expect(screen.getByTestId("agent-node-researcher")).toBeInTheDocument();
  expect(screen.getByTestId("agent-node-critic")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-user-planner")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-critic-researcher")).toBeInTheDocument(); // revise loop
  expect(screen.queryByTestId("agent-node-verifier")).not.toBeInTheDocument();
  // Standard mode: the critic is the last judge, so the fact-check lookup attaches to IT.
  expect(screen.getByTestId("agent-node-sources")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-critic-sources")).toBeInTheDocument();
  expect(screen.queryByTestId("agent-edge-verifier-sources")).not.toBeInTheDocument();
});

test("multi + standard with judge fact-check off draws no fact-check edge", () => {
  render(
    <AgentCollaborationGraph
      mode="multi"
      accuracyMode="standard"
      humanGate={false}
      verifierCheck={false}
    />,
  );
  expect(screen.queryByTestId("agent-node-sources")).not.toBeInTheDocument();
  expect(screen.queryByTestId("agent-edge-critic-sources")).not.toBeInTheDocument();
});

test("multi + accurate inserts the verifier (with its own revise loop)", () => {
  render(
    <AgentCollaborationGraph
      mode="multi"
      accuracyMode="accurate"
      humanGate={false}
      verifierCheck={false}
    />,
  );
  expect(screen.getByTestId("agent-node-verifier")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-critic-verifier")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-verifier-researcher")).toBeInTheDocument();
  // verifierCheck is off, so no independent fact-check lookup.
  expect(screen.queryByTestId("agent-node-sources")).not.toBeInTheDocument();
  expect(screen.queryByTestId("agent-edge-verifier-sources")).not.toBeInTheDocument();
});

test("accurate + verifier_check draws the fact-check edge to a sources node", () => {
  render(
    <AgentCollaborationGraph
      mode="multi"
      accuracyMode="accurate"
      humanGate={false}
      verifierCheck={true}
    />,
  );
  expect(screen.getByTestId("agent-node-sources")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-verifier-sources")).toBeInTheDocument();
});

test("human gate inserts a gate node before the answer", () => {
  render(
    <AgentCollaborationGraph
      mode="multi"
      accuracyMode="standard"
      humanGate={true}
      verifierCheck={false}
    />,
  );
  expect(screen.getByTestId("agent-node-gate")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-critic-gate")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-gate-answer")).toBeInTheDocument();
});

test("accurate + gate orders critic -> verifier -> gate -> answer", () => {
  render(
    <AgentCollaborationGraph
      mode="multi"
      accuracyMode="accurate"
      humanGate={true}
      verifierCheck={false}
    />,
  );
  expect(screen.getByTestId("agent-edge-critic-verifier")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-verifier-gate")).toBeInTheDocument();
  expect(screen.getByTestId("agent-edge-gate-answer")).toBeInTheDocument();
});

test("custom mode renders the placeholder at a stable height", () => {
  render(
    <AgentCollaborationGraph
      mode="custom"
      accuracyMode="standard"
      humanGate={false}
      verifierCheck={false}
    />,
  );
  expect(screen.getByTestId("agent-collab-graph")).toBeInTheDocument();
  expect(screen.getByTestId("agent-graph-placeholder")).toHaveTextContent(/coming soon/i);
  expect(screen.queryByTestId("agent-node-planner")).not.toBeInTheDocument();
});
