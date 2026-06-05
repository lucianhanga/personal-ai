/**
 * PersonalAI structured-output contracts - TS/Zod bindings (ADR-0003).
 *
 * These mirror the Python Pydantic models in `personalai_contracts.schemas` and are aligned
 * against the canonical JSON Schema in `schemas/json/`. The shared fixtures in
 * `schemas/fixtures/` are exercised by both the Python and the TS test suites so the two
 * bindings cannot drift apart. All objects are `.strict()` (fail-closed: unknown keys rejected).
 */
import { z } from "zod";

/** Agent message envelope: `{from, to, type, payload, schema_version}`. */
export const AgentMessageSchema = z
  .object({
    id: z.string().optional(),
    from: z.string(),
    to: z.string(),
    type: z.string(),
    payload: z.record(z.unknown()).optional().default({}),
    schema_version: z.string().optional(),
  })
  .strict();
export type AgentMessage = z.infer<typeof AgentMessageSchema>;

/** A least-privilege permission grant. */
export const PermissionSchema = z
  .object({
    type: z.enum(["filesystem", "network", "exec", "env", "clipboard"]),
    scope: z.string(),
  })
  .strict();
export type Permission = z.infer<typeof PermissionSchema>;

/** Tool invocation contract: `{tool, version, args, required_permissions}`. */
export const ToolInvocationSchema = z
  .object({
    tool: z.string(),
    version: z.string(),
    args: z.record(z.unknown()).optional().default({}),
    required_permissions: z.array(PermissionSchema).optional().default([]),
    schema_version: z.string().optional(),
  })
  .strict();
export type ToolInvocation = z.infer<typeof ToolInvocationSchema>;

/** Structured error. */
export const ErrorInfoSchema = z
  .object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.unknown()).optional().default({}),
  })
  .strict();
export type ErrorInfo = z.infer<typeof ErrorInfoSchema>;

/** Normalized result envelope: exactly one of `data` (ok) or `error` (not ok). */
export const StructuredResultSchema = z
  .object({
    ok: z.boolean(),
    data: z.record(z.unknown()).nullable().optional(),
    error: ErrorInfoSchema.nullable().optional(),
    schema_version: z.string().optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.ok && value.error != null) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "ok result must not carry an error" });
    }
    if (!value.ok && value.error == null) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "failed result must carry an error" });
    }
  });
export type StructuredResult = z.infer<typeof StructuredResultSchema>;
