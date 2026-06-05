/**
 * The TS/Zod bindings accept/reject the SAME shared fixtures as the Python tests, proving the
 * two bindings agree (ADR-0003). Fixtures live in `schemas/fixtures/` at the repo root.
 */
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { ZodTypeAny } from "zod";

import {
  AgentMessageSchema,
  StructuredResultSchema,
  ToolInvocationSchema,
} from "../src/index";

const FIXTURES = fileURLToPath(new URL("../../../schemas/fixtures", import.meta.url));

const SCHEMAS: Record<string, ZodTypeAny> = {
  "agent-message": AgentMessageSchema,
  "tool-invocation": ToolInvocationSchema,
  "structured-result": StructuredResultSchema,
};

function load(dir: string, validity: "valid" | "invalid"): Array<[string, unknown]> {
  const base = `${FIXTURES}/${dir}/${validity}`;
  return readdirSync(base)
    .filter((f) => f.endsWith(".json"))
    .map((f) => [f, JSON.parse(readFileSync(`${base}/${f}`, "utf-8"))]);
}

describe("Zod bindings agree with shared fixtures", () => {
  for (const [dir, schema] of Object.entries(SCHEMAS)) {
    for (const [name, payload] of load(dir, "valid")) {
      it(`${dir}: accepts ${name}`, () => {
        expect(schema.safeParse(payload).success).toBe(true);
      });
    }
    for (const [name, payload] of load(dir, "invalid")) {
      it(`${dir}: rejects ${name}`, () => {
        expect(schema.safeParse(payload).success).toBe(false);
      });
    }
  }
});
