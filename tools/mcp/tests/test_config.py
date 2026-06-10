"""Loading MCP server configs from an mcp.json."""

from __future__ import annotations

from pathlib import Path

from personalai_tool_mcp import load_server_configs


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_server_configs(tmp_path / "nope.json") == []


def test_parses_mcp_servers_map(tmp_path: Path) -> None:
    p = tmp_path / "mcp.json"
    p.write_text(
        '{"mcpServers": {"playwright": {"command": "npx", "args": ["-y", "@playwright/mcp"],'
        ' "env": {"K": "v"}}}}',
        encoding="utf-8",
    )
    configs = load_server_configs(p)
    assert len(configs) == 1
    c = configs[0]
    assert c.name == "playwright"
    assert c.command == "npx"
    assert c.args == ("-y", "@playwright/mcp")
    assert c.env == {"K": "v"}


def test_skips_disabled_and_commandless(tmp_path: Path) -> None:
    p = tmp_path / "mcp.json"
    p.write_text(
        '{"mcpServers": {"off": {"command": "x", "enabled": false},'
        ' "nocmd": {"args": ["y"]}, "ok": {"command": "z"}}}',
        encoding="utf-8",
    )
    assert [c.name for c in load_server_configs(p)] == ["ok"]


def test_parses_remote_http_server(tmp_path: Path) -> None:
    p = tmp_path / "mcp.json"
    p.write_text(
        '{"mcpServers": {"remote": {"url": "https://host/mcp",'
        ' "headers": {"Authorization": "x"}}}}',
        encoding="utf-8",
    )
    configs = load_server_configs(p)
    assert len(configs) == 1
    c = configs[0]
    assert c.name == "remote" and c.url == "https://host/mcp" and c.command == ""
    assert c.headers == {"Authorization": "x"}
