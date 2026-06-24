import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { EgressApproval } from "./EgressApproval";

test("shows the blocked host + tool and the four actions with tooltips", () => {
  render(<EgressApproval host="api.example.com" tool="http_fetch" onResolve={() => {}} />);

  expect(screen.getByTestId("egress-host")).toHaveTextContent("api.example.com");
  expect(screen.getByTestId("egress-approval")).toHaveTextContent("http_fetch");

  expect(screen.getByTestId("egress-allow-once")).toHaveAttribute(
    "title",
    "Allow this request for this run only; don't remember it.",
  );
  expect(screen.getByTestId("egress-allow-always")).toHaveAttribute(
    "title",
    "Allow and remember this host for next time (added to your allowlist).",
  );
  expect(screen.getByTestId("egress-deny")).toHaveAttribute(
    "title",
    "Block this request; the tool returns an error and the run continues.",
  );
  expect(screen.getByTestId("egress-more-info")).toHaveAttribute(
    "title",
    "See exactly what would be sent to this host before deciding.",
  );
});

test("each allow/deny button resolves with the matching verb", () => {
  const onResolve = vi.fn();
  render(<EgressApproval host="api.example.com" tool="http_fetch" onResolve={onResolve} />);

  fireEvent.click(screen.getByTestId("egress-allow-once"));
  expect(onResolve).toHaveBeenCalledWith("egress_allow_once");

  fireEvent.click(screen.getByTestId("egress-allow-always"));
  expect(onResolve).toHaveBeenCalledWith("egress_allow_always");

  fireEvent.click(screen.getByTestId("egress-deny"));
  expect(onResolve).toHaveBeenCalledWith("egress_deny");
});

test("'More info' toggles the details panel (no resolve)", () => {
  const onResolve = vi.fn();
  render(<EgressApproval host="api.example.com" onResolve={onResolve} />);

  expect(screen.queryByTestId("egress-details")).toBeNull();
  fireEvent.click(screen.getByTestId("egress-more-info"));
  expect(screen.getByTestId("egress-details")).toBeInTheDocument();
  expect(onResolve).not.toHaveBeenCalled();
});

test("details redact secret-looking arg keys while showing normal ones", () => {
  render(
    <EgressApproval
      host="api.example.com"
      tool="http_fetch"
      args={{
        url: "https://api.example.com/data",
        authorization: "Bearer sk-super-secret", // pragma: allowlist secret
        api_key: "abcd1234", // pragma: allowlist secret
        headers: { cookie: "session=topsecret" }, // pragma: allowlist secret
      }}
      onResolve={() => {}}
    />,
  );
  fireEvent.click(screen.getByTestId("egress-more-info"));
  const details = screen.getByTestId("egress-details");

  // Normal key + value shown verbatim.
  expect(details).toHaveTextContent("https://api.example.com/data");
  // Secret values redacted (top-level and nested), and the raw secrets never appear.
  expect(details).toHaveTextContent("<redacted>");
  expect(details).not.toHaveTextContent("sk-super-secret");
  expect(details).not.toHaveTextContent("abcd1234");
  expect(details).not.toHaveTextContent("topsecret");
});

test("the in-details buttons also resolve with the right verb", () => {
  const onResolve = vi.fn();
  render(<EgressApproval host="api.example.com" args={{ url: "x" }} onResolve={onResolve} />);
  fireEvent.click(screen.getByTestId("egress-more-info"));

  // Within the details panel, repeat the allow-once button (now there are two in the DOM).
  const onceButtons = screen.getAllByTestId("egress-allow-once");
  expect(onceButtons.length).toBe(2);
  fireEvent.click(onceButtons[1]);
  expect(onResolve).toHaveBeenCalledWith("egress_allow_once");
});

test("buttons are disabled while busy", () => {
  render(<EgressApproval host="api.example.com" busy onResolve={() => {}} />);
  expect(screen.getByTestId("egress-allow-once")).toBeDisabled();
  expect(screen.getByTestId("egress-allow-always")).toBeDisabled();
  expect(screen.getByTestId("egress-deny")).toBeDisabled();
});
