import { useCallback, useEffect, useState } from "react";

import {
  deleteFolder,
  fetchFolders,
  registerFolder,
  type FolderError,
  type FolderSource,
} from "./api";

// Result of an add attempt, shaped for the form's inline-error rendering: success clears + refreshes;
// failure carries the structured backend message (bad path / duplicate) to show in place.
export type AddFolderResult = { ok: true } | { ok: false; error: FolderError };

export interface UseFolderSources {
  folders: FolderSource[];
  loading: boolean;
  // Backend unreachable (the list fetch threw). Mutating actions are disabled while offline.
  offline: boolean;
  refresh: () => Promise<void>;
  addFolder: (path: string, label: string) => Promise<AddFolderResult>;
  removeFolder: (id: string) => Promise<void>;
}

/** Owns the folder-source list + its mutations (#458), keeping FolderSourcesPanel/SettingsView thin.
 * Mirrors the self-fetching panels (Memory/Tools/McpPanel) that take a `token` and manage their own
 * state, rather than lifting folder state into Chat.tsx (no cross-cutting consumer needs it). */
export function useFolderSources(token: string): UseFolderSources {
  const [folders, setFolders] = useState<FolderSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  const refresh = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const list = await fetchFolders(token);
      setFolders(list);
      setOffline(false);
    } catch {
      // Storage/backend unavailable: surface an offline state (disables mutating actions) rather
      // than a hard error, mirroring how the file list degrades gracefully.
      setOffline(true);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const list = await fetchFolders(token);
        if (!active) return;
        setFolders(list);
        setOffline(false);
      } catch {
        if (active) setOffline(true);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [token]);

  const addFolder = useCallback(
    async (path: string, label: string): Promise<AddFolderResult> => {
      const result = await registerFolder(token, path, label || undefined);
      if (result.ok) {
        // Prepend optimistically so the new card appears immediately, then reconcile from the server
        // so SSE-driven counts/status start from the authoritative shape.
        setFolders((prev) => [result.folder, ...prev]);
        void refresh();
        return { ok: true };
      }
      return { ok: false, error: result.error };
    },
    [token, refresh],
  );

  const removeFolder = useCallback(
    async (id: string): Promise<void> => {
      await deleteFolder(token, id);
      setFolders((prev) => prev.filter((f) => f.id !== id));
    },
    [token],
  );

  return { folders, loading, offline, refresh, addFolder, removeFolder };
}
