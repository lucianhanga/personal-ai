"""Tool-equipped frontier "chat" adapter (#328): a frontier model + PersonalAI's own tools.

This is the assistant/ChatGPT-style variant (vs the `raw` tier): the frontier model is given
PersonalAI's tools via OpenAI function-calling, and each tool call is executed through the backend's
gateway (`/api/v1/tools/invoke`) — so frontier models use the *same* tools as PersonalAI
(calculator, web_search, …), reusing the app's real implementations (no extra search key). Needs
the backend running, like the rest of `compare`. The model + tool HTTP calls are injectable, so
this tests with no network.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from personalai_benchmarks.adapters import RunResult
from personalai_benchmarks.frontier import PROVIDERS, Provider

# Loaded tools: (function specs, permissions-by-real-name, versions-by-real-name, safe→real names).
_Tools = tuple[
    list[dict[str, Any]], dict[str, list[dict[str, str]]], dict[str, str], dict[str, str]
]


class ToolEquippedFrontierAdapter:
    """A frontier :class:`SystemUnderTest` that calls PersonalAI's tools via function-calling."""

    def __init__(
        self,
        provider: Provider,
        api_key: str,
        model: str,
        *,
        backend_url: str = "http://127.0.0.1:8765",
        backend_token: str | None = None,
        client: httpx.Client | None = None,
        max_steps: int = 5,
        temperature: float = 0.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.name = f"{provider.name}+tools:{model}"
        self._key = api_key
        self._backend = backend_url.rstrip("/")
        self._backend_token = backend_token
        self._client = client or httpx.Client(timeout=120.0)
        self._max_steps = max_steps
        self._temperature = temperature
        self._tools: _Tools | None = None

    def _backend_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._backend_token}"} if self._backend_token else {}

    def _load_tools(self) -> _Tools:
        """Fetch the backend's tool manifests once → specs (with model-safe names), permissions,
        versions, and a safe→real name map (MCP tools have dotted names OpenAI rejects)."""
        if self._tools is not None:
            return self._tools
        resp = self._client.get(f"{self._backend}/api/v1/tools", headers=self._backend_headers())
        resp.raise_for_status()
        tools = resp.json().get("data", {}).get("tools", [])
        specs: list[dict[str, Any]] = []
        perms: dict[str, list[dict[str, str]]] = {}
        versions: dict[str, str] = {}
        name_map: dict[str, str] = {}
        for t in tools:
            real = t["name"]
            # OpenAI function names must match ^[a-zA-Z0-9_-]+$; dotted MCP names don't.
            safe = re.sub(r"[^a-zA-Z0-9_-]", "_", real)
            name_map[safe] = real
            perms[real] = t.get("permissions", [])
            versions[real] = t.get("version", "1.0.0")
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": safe,
                        "description": f"PersonalAI {real} tool",
                        "parameters": t.get("inputs") or {"type": "object", "properties": {}},
                    },
                }
            )
        self._tools = (specs, perms, versions, name_map)
        return self._tools

    def _invoke_tool(self, name: str, args: Mapping[str, Any]) -> str:
        _, perms, versions, _ = self._load_tools()
        body = {
            "tool": name,
            "version": versions.get(name, "1.0.0"),
            "args": dict(args),
            "grants": perms.get(name, []),
            "approved": True,  # benchmark runs auto-approve; tools stay behind the egress guard
        }
        try:
            resp = self._client.post(
                f"{self._backend}/api/v1/tools/invoke", headers=self._backend_headers(), json=body
            )
        except httpx.HTTPError as exc:
            return f"tool transport error: {exc}"
        data = resp.json()
        if data.get("ok"):
            return json.dumps(data.get("data", {}))
        return f"tool error: {(data.get('error') or {}).get('message', 'failed')}"

    def _chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self._temperature,
        }
        if tools:
            body["tools"] = tools
        url = f"{self.provider.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._key}"}
        resp = self._client.post(url, headers=headers, json=body)
        if resp.status_code == 400 and "temperature" in resp.text.lower():
            body.pop("temperature", None)
            resp = self._client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        message: dict[str, Any] = resp.json()["choices"][0]["message"]
        return message

    def run(self, messages: Sequence[Mapping[str, str]], overrides: Mapping[str, Any]) -> RunResult:
        started = time.perf_counter()
        try:
            specs, _, _, name_map = self._load_tools()
            convo: list[dict[str, Any]] = [dict(m) for m in messages]
            tool_calls_made: list[dict[str, Any]] = []
            for step in range(self._max_steps):
                # On the last allowed step, drop tools so the model must produce a final answer.
                message = self._chat(convo, specs if step < self._max_steps - 1 else None)
                convo.append(message)
                calls = message.get("tool_calls") or []
                if not calls:
                    latency = (time.perf_counter() - started) * 1000.0
                    return RunResult(
                        answer=str(message.get("content") or ""),
                        trace=[{"kind": "tool_call", **tc} for tc in tool_calls_made],
                        tool_calls=tool_calls_made,
                        latency_ms=round(latency, 1),
                        config_used={
                            "provider": self.provider.name,
                            "model": self.model,
                            "tier": "frontier_tools",
                        },
                    )
                for call in calls:
                    fn = call.get("function", {})
                    real = name_map.get(fn.get("name", ""), fn.get("name", ""))  # safe → real name
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except (ValueError, TypeError):
                        args = {}
                    tool_calls_made.append({"tool": real, "args": args})
                    output = self._invoke_tool(real, args)
                    convo.append(
                        {"role": "tool", "tool_call_id": call.get("id", ""), "content": output}
                    )
        except httpx.HTTPError as exc:
            return RunResult(error=f"{self.provider.name}+tools request failed: {exc}")
        except (KeyError, IndexError, TypeError) as exc:
            return RunResult(error=f"{self.provider.name}+tools unexpected response: {exc}")
        # Reached the step limit without a tool-free answer (rare given the forced last step).
        return RunResult(
            error=f"{self.provider.name}+tools: no final answer within {self._max_steps} steps"
        )


def build(
    provider_name: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    backend_url: str = "http://127.0.0.1:8765",
    backend_token: str | None = None,
    client: httpx.Client | None = None,
) -> ToolEquippedFrontierAdapter | None:
    """A tool-equipped adapter for ``provider_name``, or None if its API key is absent."""
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise KeyError(f"unknown provider {provider_name!r}; known: {', '.join(PROVIDERS)}")
    key = api_key if api_key is not None else os.environ.get(provider.env_var)
    if not key:
        return None
    return ToolEquippedFrontierAdapter(
        provider,
        key,
        model or provider.default_model,
        backend_url=backend_url,
        backend_token=backend_token,
        client=client,
    )
