"""Launcher UI: validated arg-builder + page render (#332, streamlined #351). No live server."""

from __future__ import annotations

import pytest
from personalai_benchmarks import ui


def test_build_args_happy_path() -> None:
    args = ui.build_compare_args(
        models=["openai:gpt-4o"],
        modes=["single_no_tools"],
        task_ids=["reasoning_arithmetic_order"],
        repeats=3,
        no_personalia=True,
        base_url="http://127.0.0.1:8765",
    )
    assert args[0] == "compare"
    assert "--models" in args and "openai:gpt-4o" in args
    assert "--modes" in args and "single_no_tools" in args
    assert "--task-ids" in args and "reasoning_arithmetic_order" in args
    assert args[args.index("--repeats") + 1] == "3"
    assert "--no-personalia" in args
    # streamlined: these flags no longer exist
    assert "--no-judge" not in args and "--frontier-tools" not in args
    assert "--model-tier" not in args and "--providers" not in args


def test_empty_selection_builds_a_minimal_command() -> None:
    args = ui.build_compare_args(
        models=[], modes=[], task_ids=[], repeats=1, no_personalia=False, base_url="http://x"
    )
    assert args[0] == "compare"
    assert "--models" not in args and "--no-personalia" not in args


def test_unknown_model_rejected() -> None:
    with pytest.raises(ValueError, match="unknown models"):
        ui.build_compare_args(
            models=["openai:not-a-real-model"],
            modes=[],
            task_ids=[],
            repeats=1,
            no_personalia=False,
            base_url="http://x",
        )


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="unknown modes"):
        ui.build_compare_args(
            models=[],
            modes=["definitely_not_a_mode"],
            task_ids=[],
            repeats=1,
            no_personalia=False,
            base_url="http://x",
        )


def test_repeats_must_be_positive() -> None:
    with pytest.raises(ValueError, match="repeats"):
        ui.build_compare_args(
            models=[],
            modes=[],
            task_ids=[],
            repeats=0,
            no_personalia=False,
            base_url="http://x",
        )


def test_valid_models_covers_a_real_registry_entry() -> None:
    valid = ui._valid_models()
    assert "openai:gpt-5.5" in valid  # provider:model from the registry
    assert "openai" not in valid  # bare provider is not a model id


def test_page_renders_trees_judge_and_controls() -> None:
    from personalai_benchmarks import frontier
    from personalai_benchmarks.modes import ALL_MODES

    page = ui._render_page("http://127.0.0.1:8765")
    assert "<!doctype html>" in page
    assert "cbtree" in page  # the grouped checkbox tree control
    for provider in frontier.PROVIDERS:
        assert provider in page  # provider groups present
    for mode in ALL_MODES:
        assert mode in page
    assert "Judge (always on" in page  # fixed-judge display
    # removed controls are gone from the page
    assert "model_tier" not in page and "frontier with tools" not in page


def test_page_has_stop_and_history_controls() -> None:
    page = ui._render_page("http://127.0.0.1:8765")
    assert "id=stop" in page and "/stop" in page  # stop -> SIGINT endpoint
    assert "/runs" in page and "Report history" in page  # run-history listing
