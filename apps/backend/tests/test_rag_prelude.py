"""RAG-pipeline "context prelude" trace items (#437) — the pure builders, no DB, no live model.

These cover the taxonomy + field shape + caps + anti-noise rules of the indexing/retrieval/ner
items that the chat handler collects during the pre-agent context-assembly phase, replays live as
trace frames, and PREPENDS to the assistant turn's ``meta["trace"]``. The end-to-end emit/persist/
order through the real ``/api/v1/chat`` call (which needs Postgres for the vector store) lives in
``test_conversations.py`` behind the ``_db_available`` skip; these run everywhere.
"""

from __future__ import annotations

from personalai_backend.app import (
    _PRELUDE_MAX_CITATIONS,
    _PRELUDE_QUERY_CAP,
    _PRELUDE_REF_CAP,
    _PRELUDE_TEXT_CAP,
    _emit_ner,
    _indexing_item,
    _retrieval_item,
)


def test_indexing_item_shape_and_label() -> None:
    item = _indexing_item("report.pdf", chunks=48, ms=1400)
    assert item["kind"] == "indexing"
    assert (
        item["text"] == "Indexed report.pdf"
    )  # short label; UI composes "{ref} - {chunks} chunks"
    assert item["ref"] == "report.pdf"
    assert item["chunks"] == 48
    assert item["ms"] == 1400
    assert "status" not in item and "error" not in item  # success has no error fields
    assert isinstance(item["ts"], str) and item["ts"].endswith("+00:00")  # UTC ISO, _TurnSse format


def test_indexing_item_error_carries_status_and_message() -> None:
    item = _indexing_item("big.pdf", chunks=0, ms=20, error="embed failed")
    assert item["status"] == "error"
    assert item["error"] == "embed failed"
    assert item["chunks"] == 0


def test_indexing_item_caps_ref_and_clamps_numbers() -> None:
    item = _indexing_item("x" * (_PRELUDE_REF_CAP + 50), chunks=-5, ms=-10)
    assert len(item["ref"]) == _PRELUDE_REF_CAP
    assert item["chunks"] == 0  # negative clamps to 0
    assert item["ms"] == 0
    assert len(item["text"]) <= _PRELUDE_TEXT_CAP


def test_retrieval_item_projects_compact_citations() -> None:
    citations = [
        {"n": 1, "name": "Q3-board.pdf", "source_id": "s1", "score": 0.82, "locator": "p1"},
        {"n": 2, "name": "notes.md", "source_id": "s2", "score": 0.61, "locator": "p2"},
    ]
    item = _retrieval_item(
        query="Q3 runway guidance", top_k=8, hits=2, scope="union", citations=citations, ms=320
    )
    assert item["kind"] == "retrieval"
    assert item["text"] == "Retrieved 2 passages"
    assert item["top_k"] == 8
    assert item["hits"] == 2
    assert item["scope"] == "union"
    assert item["ms"] == 320
    # Compact {source, score} only — no n/locator/source_id leak into the trace disclosure.
    assert item["citations"] == [
        {"source": "Q3-board.pdf", "score": 0.82},
        {"source": "notes.md", "score": 0.61},
    ]


def test_retrieval_item_zero_hits_is_signal_not_suppressed() -> None:
    item = _retrieval_item(query="q", top_k=8, hits=0, scope="global", citations=[], ms=12)
    assert item["hits"] == 0
    assert item["citations"] == []
    assert item["text"] == "Retrieved 0 passages"  # honest "searched, found nothing"


def test_retrieval_item_caps_citation_count_and_query() -> None:
    many = [{"name": f"d{i}.pdf", "source_id": str(i), "score": 0.5} for i in range(20)]
    item = _retrieval_item(
        query="z" * (_PRELUDE_QUERY_CAP + 100),
        top_k=20,
        hits=20,
        scope="union",
        citations=many,
        ms=1,
    )
    assert len(item["citations"]) == _PRELUDE_MAX_CITATIONS  # winners-only cap
    assert len(item["query"]) == _PRELUDE_QUERY_CAP


def test_retrieval_item_falls_back_to_source_id_when_name_missing() -> None:
    item = _retrieval_item(
        query="q",
        top_k=4,
        hits=1,
        scope="conversation",
        citations=[{"source_id": "doc-123", "score": 0.4}],
        ms=5,
    )
    assert item["citations"] == [{"source": "doc-123", "score": 0.4}]


def test_retrieval_item_unknown_scope_normalizes_to_global() -> None:
    item = _retrieval_item(query="q", top_k=4, hits=0, scope="weird", citations=[], ms=1)
    assert item["scope"] == "global"


def test_emit_ner_is_dormant_no_op() -> None:
    prelude: list[dict[str, object]] = []
    _emit_ner(prelude, entities=None)
    assert prelude == []  # Phase 6 hook: emits nothing until entities are supplied


def test_emit_ner_phase6_shape_when_entities_supplied() -> None:
    # Forward-compat: when Phase 6 fills `entities`, the item carries the documented ner shape.
    prelude: list[dict[str, object]] = []
    _emit_ner(prelude, entities={"count": 7, "types": [{"type": "PERSON", "count": 3}]})
    assert len(prelude) == 1
    ner = prelude[0]
    assert ner["kind"] == "ner"
    assert ner["text"] == "Extracted 7 entities"
    assert ner["count"] == 7
    assert ner["types"] == [{"type": "PERSON", "count": 3}]


def test_turnsse_map_retrieval_is_live_progress_and_not_persisted() -> None:
    # Live retrieval progress (#462): the gather node's running/done frames map to a transient
    # `event: retrieval` SSE frame (status running -> ok, marked `live`) for the chat + Activity
    # pane, and are INTENTIONALLY never folded into the persisted trace -- the durable per-source
    # retrieval items are derived post-merge from the unified citations.
    import json

    from personalai_backend.app import _TurnSse
    from personalai_backend.turn import TurnEvent

    sse = _TurnSse(run_id=None)
    running = sse.map(
        TurnEvent(
            "retrieval",
            output={"status": "running", "query": "q", "sources": ["vector", "memory"]},
        )
    )
    assert running is not None
    head, _, data = running.decode().partition("data: ")
    assert head.strip() == "event: retrieval"
    payload = json.loads(data)
    assert payload["kind"] == "retrieval"
    assert payload["status"] == "running" and payload["live"] is True
    assert payload["sources"] == ["vector", "memory"]
    assert sse.trace == []  # progress-only: nothing persisted

    done = sse.map(
        TurnEvent(
            "retrieval",
            output={
                "status": "done",
                "query": "q",
                "counts": {"vector": 3, "memory": 1},
                "hits": 4,
            },
        )
    )
    assert done is not None
    dp = json.loads(done.decode().partition("data: ")[2])
    assert dp["status"] == "ok"  # terminal frame normalizes to the "ok" convention
    assert dp["hits"] == 4 and dp["counts"] == {"vector": 3, "memory": 1}
    assert sse.trace == []  # still nothing persisted


def test_turnsse_map_stage_is_live_progress_and_not_persisted() -> None:
    # Generic stage heartbeat (#465): a node-entry "working" frame maps to a transient
    # `event: stage` SSE frame (marked `live`) for the chat + Activity pane, and is INTENTIONALLY
    # never folded into the persisted trace -- it is pure progress chrome.
    import json

    from personalai_backend.app import _TurnSse
    from personalai_backend.turn import TurnEvent

    sse = _TurnSse(run_id=None)
    frame = sse.map(
        TurnEvent(
            "stage", output={"name": "researcher", "label": "Researching", "status": "running"}
        )
    )
    assert frame is not None
    head, _, data = frame.decode().partition("data: ")
    assert head.strip() == "event: stage"
    payload = json.loads(data)
    assert payload["kind"] == "stage"
    assert payload["name"] == "researcher" and payload["label"] == "Researching"
    assert payload["status"] == "running" and payload["live"] is True
    assert sse.trace == []  # progress-only: nothing persisted
