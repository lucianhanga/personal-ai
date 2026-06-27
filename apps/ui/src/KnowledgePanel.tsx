import { useState } from "react";

import { KnowledgeCorpusTab } from "./KnowledgeCorpus";
import { KnowledgeGraphTab } from "./KnowledgeGraph";

type KnowledgeTab = "graph" | "corpus";

const TABS: { id: KnowledgeTab; label: string }[] = [
  { id: "graph", label: "Graph" },
  { id: "corpus", label: "Corpus" },
];

const NER = "#a21caf"; // entity-category hue, shared with EntityBrowser/the graph.

interface KnowledgePanelProps {
  token: string;
}

/** Settings > Knowledge (#KAG/#RAG): the entity/document graph (Graph) and the indexed-corpus
 * overview (Corpus). Two tabs; the graph is the focus+context ego-graph, the corpus is the P0
 * overview (stats + per-document indexed status + chunk inspector).
 *
 * The active tab and the Corpus chunk-inspector's selected document are lifted here so the Graph tab
 * can deep-link a document node into the Corpus tab ("Open in Corpus"): one click switches to Corpus
 * AND opens that document's chunks. The Corpus document table also drives the same selection. */
export function KnowledgePanel({ token }: KnowledgePanelProps): React.ReactElement {
  const [tab, setTab] = useState<KnowledgeTab>("graph");
  // The document whose chunks the Corpus inspector shows (null = closed). Single source of truth so
  // the graph deep-link and the corpus table both drive the same inspector.
  const [corpusDocId, setCorpusDocId] = useState<string | null>(null);

  // Graph -> Corpus deep link: switch to the Corpus tab and open the document's chunk inspector.
  function openInCorpus(docId: string): void {
    setCorpusDocId(docId);
    setTab("corpus");
  }

  return (
    <section
      data-testid="knowledge-panel"
      aria-label="Knowledge"
      style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem" }}
    >
      <div
        data-testid="knowledge-tabs"
        role="tablist"
        aria-label="Knowledge views"
        style={{ display: "flex", gap: "0.25rem", marginBottom: "0.75rem", borderBottom: "1px solid #eee" }}
      >
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              data-testid={`knowledge-tab-${t.id}`}
              type="button"
              onClick={() => setTab(t.id)}
              style={{
                border: "none",
                background: "none",
                cursor: "pointer",
                padding: "0.35rem 0.7rem",
                fontSize: "0.85rem",
                fontWeight: active ? 600 : 400,
                color: active ? NER : "#555",
                borderBottom: active ? `2px solid ${NER}` : "2px solid transparent",
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      <div role="tabpanel" data-testid={`knowledge-panel-${tab}`}>
        {tab === "graph" ? (
          <KnowledgeGraphTab token={token} onOpenInCorpus={openInCorpus} />
        ) : (
          <KnowledgeCorpusTab
            token={token}
            selectedDocId={corpusDocId}
            onSelectDocument={setCorpusDocId}
          />
        )}
      </div>
    </section>
  );
}
