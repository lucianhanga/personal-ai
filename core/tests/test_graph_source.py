"""KAG aggregation source (#465): count-intent detection + counting retrieve. No LLM/DB -- the
counter is a fake and entity extraction uses the no-provider heuristic path."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from personalai_core.sources.graph import GraphSource, _is_count_query


async def _counter(name: str) -> Sequence[tuple[str, str, int]]:
    # Strongest match first (the source takes [0]).
    return [("M-Net Telekom", "org", 14), ("Other Co", "org", 2)]


def test_is_count_query() -> None:
    assert _is_count_query("how many M-Net invoices are there?")
    assert _is_count_query("number of invoices from Acme")
    assert _is_count_query("list all documents about taxes")
    assert _is_count_query("which documents mention M-Net?")
    assert not _is_count_query("what is the M-Net invoice total?")
    assert not _is_count_query("tell me about M-Net")


def test_select_only_on_count_query_with_counter() -> None:
    src = GraphSource(counter=_counter)
    assert asyncio.run(src.select("how many M-Net invoices?", None)) == 0.9  # self-elects
    assert asyncio.run(src.select("tell me about M-Net", None)) == 0.0  # not a count question
    # No counter wired -> never applicable (the old no-op stub behaviour).
    assert asyncio.run(GraphSource().select("how many M-Net invoices?", None)) == 0.0


def test_retrieve_counts_top_match() -> None:
    src = GraphSource(counter=_counter)  # no provider -> heuristic entity extraction
    evidence = asyncio.run(src.retrieve("how many M-Net invoices?", 1000, None))
    assert len(evidence) == 1
    assert evidence[0].metadata["count"] == 14
    assert "14" in evidence[0].text
    assert evidence[0].source_kind == "graph"


def test_retrieve_empty_when_no_entity_match() -> None:
    async def _none(name: str) -> Sequence[tuple[str, str, int]]:
        return []

    assert asyncio.run(GraphSource(counter=_none).retrieve("how many X?", 1000, None)) == []


def test_retrieve_noop_on_non_count_query() -> None:
    src = GraphSource(counter=_counter)
    assert asyncio.run(src.retrieve("tell me about M-Net", 1000, None)) == []


def test_retrieve_noop_without_counter() -> None:
    assert asyncio.run(GraphSource().retrieve("how many M-Net invoices?", 1000, None)) == []
