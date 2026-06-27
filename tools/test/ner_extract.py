#!/usr/bin/env python3
"""Experiment with the local NER / KAG entity extractor (#464) -- and compare models.

Runs the SAME windowed extraction (same prompt, same merge) through either the local Ollama model
or an OpenAI model, so you can compare what each one finds and how long it takes.

Providers:
  --provider ollama   the local model via the real core ``extract_entities`` (default)
  --provider openai   an OpenAI model (default gpt-5-nano -- cheapest GPT-5 tier)
  --provider both     run both and print them side by side

Knobs:
  --num-ctx     Ollama context (default 32768). Drop to 4096 if Ollama OOM-crashes the 35B at 32K.
  --window      NER window size in chars (default 1200). The local MoE returns EMPTY on large
                windows; OpenAI handles big windows fine, so pass a larger --window for it.
  --overlap / --max-windows / --timeout   window overlap, cap, and Ollama HTTP timeout.
  --model       Ollama model (default: configured default_model).
  --openai-model  OpenAI model (default gpt-5-nano; try gpt-5-mini / gpt-4o-mini for more capacity).

OpenAI needs a key: export OPENAI_API_KEY=sk-... (or PERSONALAI_OPENAI_API_KEY).

Examples:
  uv run python tools/test/ner_extract.py --file tools/test/sample_invoice.txt
  uv run python tools/test/ner_extract.py --provider openai --file tools/test/sample_invoice.txt
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

from personalai_contracts.ports import ChatMessage, GenerationRequest, Role
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
from personalai_provider_openai import OpenAICompatProvider

_SAMPLE = (
    "Rechnung von M-Net Telekommunikations GmbH an Lucian Hanga, Betrag 39,99 EUR, "
    "Rechnungsnummer R-2026-0042, Datum 2026-01-15."
)

_ENTITY_TYPES = ["person", "org", "location", "date", "product", "event", "other"]

# OpenAI structured outputs are STRICT: every object needs additionalProperties:false and all its
# properties listed in `required`. (Ollama tolerates this too.) Built by hand so it stays strict.
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


async def _extract_via_schema(
    text: str, *, provider: Any, model: str, window: int, overlap: int, max_windows: int
) -> ExtractedEntities:
    """Windowed extraction using the strict JSON schema -- the path for the OpenAI provider (its
    structured mode needs the strict schema). Same prompt + merge as core extract_entities."""
    merged_e: dict[tuple[str, str], ExtractedEntity] = {}
    merged_r: dict[tuple[str, str, str], ExtractedRelation] = {}
    for win in _windows(text.strip(), window, overlap, max_windows):
        raw = ""
        request = GenerationRequest(
            messages=[ChatMessage(Role.SYSTEM, _NER_PROMPT), ChatMessage(Role.USER, win)],
            model=model,
            json_schema=_STRICT_SCHEMA,
        )
        async for chunk in provider.stream(request):
            if chunk.delta:
                raw += chunk.delta
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < 0:
            continue
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            continue
        for ent in payload.get("entities", []):
            etype, name = ent.get("type"), str(ent.get("name", "")).strip()
            norm = " ".join(name.lower().split())
            if norm and etype in _ENTITY_TYPES:
                merged_e.setdefault((etype, norm), ExtractedEntity(type=etype, name=name))
        for rel in payload.get("relations", []):
            key = (
                str(rel.get("src", "")).strip().lower(),
                str(rel.get("relation", "")).strip().lower(),
                str(rel.get("dst", "")).strip().lower(),
            )
            if all(key):
                merged_r.setdefault(
                    key,
                    ExtractedRelation(src=rel["src"], relation=rel["relation"], dst=rel["dst"]),
                )
    return ExtractedEntities(entities=list(merged_e.values()), relations=list(merged_r.values()))


async def _run(
    label: str, text: str, *, provider: Any, model: str, core: bool, window: int, **kw: int
) -> None:
    started = time.perf_counter()
    if core:
        # Ollama path: the real extractor (handles the MoE /no_think workaround + repair).
        res = await extract_entities(text, provider=provider, model=model, window=window, **kw)
    else:
        res = await _extract_via_schema(text, provider=provider, model=model, window=window, **kw)
    elapsed = time.perf_counter() - started
    print(
        f"\n==== {label} ({model}) -> {len(res.entities)} entities, "
        f"{len(res.relations)} relations in {elapsed:.1f}s ===="
    )
    for e in res.entities:
        print(f"  {e.type:9} {e.name}")
    for r in res.relations:
        print(f"  REL  {r.src} -[{r.relation}]-> {r.dst}")


def _openai_provider(config: CoreConfig) -> OpenAICompatProvider:
    key = os.environ.get("OPENAI_API_KEY") or config.openai_api_key
    if not key:
        raise SystemExit(
            "set OPENAI_API_KEY (or PERSONALAI_OPENAI_API_KEY) to use --provider openai"
        )
    return OpenAICompatProvider(api_key=key, base_url=config.openai_base_url)


async def main() -> None:
    ap = argparse.ArgumentParser(description="Experiment with / compare NER extractors.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--text", help="literal text to extract from")
    src.add_argument("--file", help="path to a text file to extract from")
    src.add_argument("--first-doc", action="store_true", help="first global doc from the index")
    ap.add_argument("--provider", choices=["ollama", "openai", "both"], default="ollama")
    ap.add_argument(
        "--model", default=None, help="Ollama model (default: configured default_model)"
    )
    ap.add_argument("--openai-model", default="gpt-5-nano")
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

    win_kw = {"overlap": args.overlap, "max_windows": args.max_windows}

    if args.provider in ("ollama", "both"):
        ollama = OllamaProvider(
            base_url=config.ollama_host,
            keep_alive=config.ollama_keep_alive,
            timeout=args.timeout,
            num_ctx=args.num_ctx,
        )
        await _run(
            "OLLAMA",
            text,
            provider=ollama,
            model=args.model or config.default_model,
            core=True,
            window=args.window,
            **win_kw,
        )

    if args.provider in ("openai", "both"):
        await _run(
            "OPENAI",
            text,
            provider=_openai_provider(config),
            model=args.openai_model,
            core=False,
            window=args.window,
            **win_kw,
        )


if __name__ == "__main__":
    asyncio.run(main())
