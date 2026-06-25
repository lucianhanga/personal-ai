"""Unit tests for ``union_scope_predicate`` (#420 PR4) -- pure SQL-fragment builder, no DB.

The DB-level behaviour is covered by test_union_retrieval.py; this proves the fragment shape, the
parameter binding (the value is bound, never interpolated), and the anti-bleed structure: the only
non-global rows the union can match are those whose ``conversation_id`` equals the bound id.
"""

from __future__ import annotations

from personalai_contracts.ports.storage import Scope
from personalai_storage_postgres.db import scope_predicate, union_scope_predicate


def test_union_predicate_matches_global_or_this_conversation() -> None:
    fragment, params = union_scope_predicate("conv-123", next_param=5)
    # Global arm (NULL/NULL) OR this conversation; project rows excluded by the global arm's
    # `project_id IS NULL` and never matched by the conversation arm.
    assert fragment == (
        "((conversation_id IS NULL AND project_id IS NULL) "
        "OR (conversation_id = $5 AND project_id IS NULL))"
    )
    # The conversation id is BOUND ($5), never interpolated into the SQL string.
    assert params == ["conv-123"]
    assert "conv-123" not in fragment


def test_union_predicate_honors_next_param_offset() -> None:
    fragment, params = union_scope_predicate("c", next_param=2)
    assert "$2" in fragment
    assert params == ["c"]


def test_union_differs_from_single_conversation_scope() -> None:
    """The union includes the global arm; the single-scope predicate does not -- that extra arm is
    exactly what lets the global corpus stay searchable alongside the attachment."""
    union_sql, _ = union_scope_predicate("c", next_param=2)
    single_sql, _ = scope_predicate(Scope(conversation_id="c"), next_param=2)
    assert "conversation_id IS NULL" in union_sql
    assert "conversation_id IS NULL" not in single_sql
