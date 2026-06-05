/** Minimal client for the local PersonalAI backend. */

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8765";

export interface VersionInfo {
  name: string;
  version: string;
}

/** Returns true if the backend /health endpoint reports ok. Never throws. */
export async function fetchHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) return false;
    const body = (await res.json()) as { status?: string };
    return body.status === "ok";
  } catch {
    return false;
  }
}
