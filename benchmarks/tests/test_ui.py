"""Launcher UI: validated arg-builder + page render (#332). No live server/subprocess here."""

from __future__ import annotations

import pytest
from personalai_benchmarks import ui


def test_build_args_happy_path() -> None:
    args = ui.build_compare_args(
        providers=["openai"],
        modes=["single_no_tools"],
        task_ids=["reasoning_arithmetic_order"],
        repeats=3,
        judge=True,
        frontier_tools=True,
        no_personalia=True,
        base_url="http://127.0.0.1:8765",
    )
    assert args[0] == "compare"
    assert "--providers" in args and "openai" in args
    assert "--modes" in args and "single_no_tools" in args
    assert "--task-ids" in args and "reasoning_arithmetic_order" in args
    assert args[args.index("--repeats") + 1] == "3"
    assert "--frontier-tools" in args and "--no-personalia" in args
    # judge on -> no --no-judge flag
    assert "--no-judge" not in args


def test_model_tier_is_passed_through_and_validated() -> None:
    args = ui.build_compare_args(
        providers=["openai"],
        modes=[],
        task_ids=[],
        repeats=1,
        judge=True,
        frontier_tools=False,
        no_personalia=False,
        base_url="http://x",
        model_tier="best",
    )
    assert args[args.index("--model-tier") + 1] == "best"


def test_unknown_model_tier_rejected() -> None:
    with pytest.raises(ValueError, match="unknown model tier"):
        ui.build_compare_args(
            providers=[],
            modes=[],
            task_ids=[],
            repeats=1,
            judge=True,
            frontier_tools=False,
            no_personalia=False,
            base_url="http://x",
            model_tier="ultra",
        )


def test_no_judge_flag_when_judge_off() -> None:
    args = ui.build_compare_args(
        providers=[],
        modes=[],
        task_ids=[],
        repeats=1,
        judge=False,
        frontier_tools=False,
        no_personalia=False,
        base_url="http://x",
    )
    assert "--no-judge" in args
    assert "--frontier-tools" not in args and "--no-personalia" not in args


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ValueError, match="unknown providers"):
        ui.build_compare_args(
            providers=["evilcorp"],
            modes=[],
            task_ids=[],
            repeats=1,
            judge=True,
            frontier_tools=False,
            no_personalia=False,
            base_url="http://x",
        )


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="unknown modes"):
        ui.build_compare_args(
            providers=[],
            modes=["definitely_not_a_mode"],
            task_ids=[],
            repeats=1,
            judge=True,
            frontier_tools=False,
            no_personalia=False,
            base_url="http://x",
        )


def test_repeats_must_be_positive() -> None:
    with pytest.raises(ValueError, match="repeats"):
        ui.build_compare_args(
            providers=[],
            modes=[],
            task_ids=[],
            repeats=0,
            judge=True,
            frontier_tools=False,
            no_personalia=False,
            base_url="http://x",
        )


def test_page_renders_known_providers_and_modes() -> None:
    from personalai_benchmarks import frontier
    from personalai_benchmarks.modes import ALL_MODES

    page = ui._render_page("http://127.0.0.1:8765")
    assert "<!doctype html>" in page
    # the data blob feeding the checkboxes mentions real providers and modes
    for provider in frontier.PROVIDERS:
        assert provider in page
    for mode in ALL_MODES:
        assert mode in page


def test_page_has_a_stop_control() -> None:
    page = ui._render_page("http://127.0.0.1:8765")
    assert "id=stop" in page  # the Stop button
    assert "/stop" in page  # wired to the SIGINT endpoint
