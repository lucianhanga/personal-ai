#!/usr/bin/env python3
"""Experiment with the local NER / KAG entity extractor (#464) -- and compare models.

Runs the SAME windowed extraction (same prompt, same merge) through either the local Ollama model
or an OpenAI model, so you can compare what each one finds, how long it takes, and how many tokens
it costs.

Providers:
  --provider ollama   the local model via the real core ``extract_entities`` (default)
  --provider openai   an OpenAI model (default gpt-5-nano)
  --provider both     run both and print them side by side

OpenAI knobs:
  --openai-model      default gpt-5-nano. For NER, gpt-4o-mini / gpt-4.1-nano are fast non-reasoning
                      options; gpt-5-mini is more capable.
  --openai-reasoning  minimal | low | medium | high (default minimal). Applies ONLY to reasoning
                      models (gpt-5-*, o-series). 'minimal' is fastest + cheapest -- best for NER.
                      Non-reasoning models (gpt-4o-mini, gpt-4.1-*) ignore it.

Ollama knobs:
  --num-ctx (default 32768; drop to 4096 if the 35B OOM-crashes Ollama), --window (1200; the local
  MoE returns EMPTY on large windows, OpenAI handles big windows fine), --overlap, --max-windows,
  --timeout, --ollama-model (alias --model).

OpenAI needs a key: export OPENAI_API_KEY=sk-... (or PERSONALAI_OPENAI_API_KEY).

Examples:
  uv run python tools/test/ner_extract.py --provider openai --file tools/test/sample_invoice.txt
  uv run python tools/test/ner_extract.py --provider openai --openai-model gpt-4o-mini --window 6000
  uv run python tools/test/ner_extract.py --provider both --first-doc
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from personalai_core.config import CoreConfig
from personalai_core.entity_extraction import (
    _NER_PROMPT,
    ExtractedEntities,
    ExtractedEntity,
    ExtractedRelation,
    _windows,
    extract_entities,
)
from personalai_provider_ollama import OllamaProvider

_SAMPLE = (
    "Rechnung von M-Net Telekommunikations GmbH an Lucian Hanga, Betrag 39,99 EUR, "
    "Rechnungsnummer R-2026-0042, Datum 2026-01-15."
)

_ENTITY_TYPES = ["person", "org", "location", "date", "product", "event", "other"]
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")

# OpenAI structured outputs are STRICT: every object needs additionalProperties:false and all its
# properties listed in `required`.
_STRICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "enum": _ENTITY_TYPES},
                    "name": {"type": "string"},
                },
                "required": ["type", "name"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "src": {"type": "string"},
                    "relation": {"type": "string"},
                    "dst": {"type": "string"},
                },
                "required": ["src", "relation", "dst"],
            },
        },
    },
    "required": ["entities", "relations"],
}


async def _text_from_first_doc(database_url: str) -> str:
    """Reconstruct the first global document's text from its stored chunks (no OCR / disk read)."""
    from personalai_storage_postgres import create_pool

    pool = await create_pool(database_url)
    try:
        rows = await pool.fetch(
            "SELECT metadata->>'text' AS t FROM vectors "
            "WHERE metadata->>'document_id' = ("
            "  SELECT metadata->>'document_id' FROM vectors "
            "  WHERE metadata->>'document_id' LIKE 'global-%' ORDER BY 1 LIMIT 1) "
            "ORDER BY (metadata->>'chunk_index')::int"
        )
        return "\n".join(r["t"] or "" for r in rows)
    finally:
        await pool.close()


def _merge_payload(
    payload: dict[str, Any],
    entities: dict[tuple[str, str], ExtractedEntity],
    relations: dict[tuple[str, str, str], ExtractedRelation],
) -> None:
    for ent in payload.get("entities", []):
        etype, name = ent.get("type"), str(ent.get("name", "")).strip()
        norm = " ".join(name.lower().split())
        if norm and etype in _ENTITY_TYPES:
            entities.setdefault((etype, norm), ExtractedEntity(type=etype, name=name))
    for rel in payload.get("relations", []):
        key = (
            str(rel.get("src", "")).strip().lower(),
            str(rel.get("relation", "")).strip().lower(),
            str(rel.get("dst", "")).strip().lower(),
        )
        if all(key):
            relations.setdefault(
                key, ExtractedRelation(src=rel["src"], relation=rel["relation"], dst=rel["dst"])
            )


async def _extract_openai(
    text: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    reasoning: str,
    window: int,
    overlap: int,
    max_windows: int,
    timeout: float,
) -> ExtractedEntities:
    """Windowed extraction via a DIRECT OpenAI /chat/completions call (strict structured output).
    Direct, not via the app provider, so we can set ``reasoning_effort`` (the provider can't). For
    reasoning models that param decides speed/cost: 'minimal' barely thinks -- ideal for NER."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    use_reasoning = model.startswith(_REASONING_PREFIXES)
    merged_e: dict[tuple[str, str], ExtractedEntity] = {}
    merged_r: dict[tuple[str, str, str], ExtractedRelation] = {}
    in_tok = out_tok = reason_tok = 0
    wins = _windows(text.strip(), window, overlap, max_windows)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        for i, win in enumerate(wins, 1):
            body: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _NER_PROMPT},
                    {"role": "user", "content": win},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "entities", "schema": _STRICT_SCHEMA, "strict": True},
                },
            }
            if use_reasoning:
                body["reasoning_effort"] = reasoning
            tag = f"reasoning={reasoning}" if use_reasoning else "no-reasoning"
            print(f"  [{i}/{len(wins)}] {model} ({tag}) on {len(win)} chars ...", flush=True)
            t0 = time.perf_counter()
            resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
            dt = time.perf_counter() - t0
            if resp.status_code != 200:
                print(
                    f"      <- HTTP {resp.status_code}: {resp.text[:200]} ({dt:.1f}s)", flush=True
                )
                continue
            data = resp.json()
            content = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage", {})
            p_in = usage.get("prompt_tokens", 0)
            p_out = usage.get("completion_tokens", 0)
            p_reason = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
            in_tok, out_tok, reason_tok = in_tok + p_in, out_tok + p_out, reason_tok + p_reason
            print(
                f"      <- {len(content)} chars in {dt:.1f}s "
                f"(in={p_in} out={p_out} reasoning={p_reason})",
                flush=True,
            )
            start, end = content.find("{"), content.rfind("}")
            if start < 0 or end < 0:
                continue
            try:
                _merge_payload(json.loads(content[start : end + 1]), merged_e, merged_r)
            except json.JSONDecodeError:
                continue
    print(f"  [tokens] input={in_tok} output={out_tok} (of which reasoning={reason_tok})")
    return ExtractedEntities(entities=list(merged_e.values()), relations=list(merged_r.values()))


def _print_result(label: str, model: str, res: ExtractedEntities, elapsed: float) -> None:
    print(
        f"\n==== {label} ({model}) -> {len(res.entities)} entities, "
        f"{len(res.relations)} relations in {elapsed:.1f}s ===="
    )
    for e in res.entities:
        print(f"  {e.type:9} {e.name}")
    for r in res.relations:
        print(f"  REL  {r.src} -[{r.relation}]-> {r.dst}")


def _openai_key(config: CoreConfig) -> str:
    key = os.environ.get("OPENAI_API_KEY") or config.openai_api_key
    if not key:
        raise SystemExit(
            "set OPENAI_API_KEY (or PERSONALAI_OPENAI_API_KEY) to use --provider openai"
        )
    return key


async def main() -> None:
    ap = argparse.ArgumentParser(description="Experiment with / compare NER extractors.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--text", help="literal text to extract from")
    src.add_argument("--file", help="path to a text file to extract from")
    src.add_argument("--first-doc", action="store_true", help="first global doc from the index")
    ap.add_argument("--provider", choices=["ollama", "openai", "both"], default="ollama")
    ap.add_argument(
        "--ollama-model",
        "--model",
        dest="ollama_model",
        default=None,
        help="Ollama model (default: configured default_model)",
    )
    ap.add_argument("--openai-model", default="gpt-5-nano")
    ap.add_argument(
        "--openai-reasoning",
        choices=["minimal", "low", "medium", "high"],
        default="minimal",
        help="reasoning effort for gpt-5-*/o-series (ignored by non-reasoning models)",
    )
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--window", type=int, default=1200)
    ap.add_argument("--overlap", type=int, default=150)
    ap.add_argument("--max-windows", type=int, default=30)
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args()

    config = CoreConfig.from_env(os.environ)

    if args.text:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.first_doc:
        text = await _text_from_first_doc(config.database_url)
    else:
        text = _SAMPLE
    print(f"input_chars={len(text)} window={args.window} provider={args.provider}")

    if args.provider in ("ollama", "both"):
        ollama = OllamaProvider(
            base_url=config.ollama_host,
            keep_alive=config.ollama_keep_alive,
            timeout=args.timeout,
            num_ctx=args.num_ctx,
        )
        model = args.ollama_model or config.default_model
        started = time.perf_counter()
        res = await extract_entities(
            text,
            provider=ollama,
            model=model,
            window=args.window,
            overlap=args.overlap,
            max_windows=args.max_windows,
        )
        _print_result("OLLAMA", model, res, time.perf_counter() - started)

    if args.provider in ("openai", "both"):
        started = time.perf_counter()
        res = await _extract_openai(
            text,
            base_url=config.openai_base_url,
            api_key=_openai_key(config),
            model=args.openai_model,
            reasoning=args.openai_reasoning,
            window=args.window,
            overlap=args.overlap,
            max_windows=args.max_windows,
            timeout=args.timeout,
        )
        _print_result("OPENAI", args.openai_model, res, time.perf_counter() - started)


if __name__ == "__main__":
    asyncio.run(main())
