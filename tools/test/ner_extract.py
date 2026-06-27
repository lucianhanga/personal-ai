#!/usr/bin/env python3
"""Experiment with the local NER / KAG entity extractor (#464).

Runs the REAL core extractor (``personalai_core.entity_extraction.extract_entities``) against text
you provide -- a literal string, a file, or a document reconstructed from the live vector store --
so you can see exactly what the model produces and sweep the knobs that actually matter on the
Qwen3 35B MoE:

  --num-ctx     Ollama context window (default 32768). If Ollama OOM-crashes loading the 35B at 32K
                on your box, drop to 4096 -- a small NER window needs little context anyway.
  --window      NER window size in chars. Keep SMALL (1200): the MoE returns EMPTY structured output
                on large windows -- a ~4000-char window comes back with zero tokens.
  --overlap     window overlap (default 150).
  --max-windows cap on windows per document.
  --timeout     Ollama HTTP timeout seconds (default 600; a cold 35B load is slow).
  --model       Ollama model (default: the configured default_model).

Examples:
  uv run python tools/test/ner_extract.py --text "Rechnung von M-Net GmbH, 39,99 EUR, 2026-01-15"
  uv run python tools/test/ner_extract.py --file tools/test/sample_invoice.txt --window 1200
  uv run python tools/test/ner_extract.py --first-doc --num-ctx 4096
  # find the size where the MoE starts returning nothing:
  uv run python tools/test/ner_extract.py --first-doc --sweep 800,1200,2000,4000
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

from personalai_core.config import CoreConfig
from personalai_core.entity_extraction import ExtractedEntities, extract_entities
from personalai_provider_ollama import OllamaProvider

_SAMPLE = (
    "Rechnung von M-Net Telekommunikations GmbH an Lucian Hanga, Betrag 39,99 EUR, "
    "Rechnungsnummer R-2026-0042, Datum 2026-01-15."
)


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


async def _run(
    text: str, *, provider: OllamaProvider, model: str, window: int, overlap: int, max_windows: int
) -> tuple[ExtractedEntities, float]:
    started = time.perf_counter()
    res = await extract_entities(
        text,
        provider=provider,
        model=model,
        window=window,
        overlap=overlap,
        max_windows=max_windows,
    )
    return res, time.perf_counter() - started


async def main() -> None:
    ap = argparse.ArgumentParser(description="Experiment with the local NER extractor.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--text", help="literal text to extract from")
    src.add_argument("--file", help="path to a text file to extract from")
    src.add_argument(
        "--first-doc", action="store_true", help="reconstruct the first global doc from the index"
    )
    ap.add_argument("--model", default=None)
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--window", type=int, default=1200)
    ap.add_argument("--overlap", type=int, default=150)
    ap.add_argument("--max-windows", type=int, default=30)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--sweep", default=None, help="comma-separated window sizes to compare")
    args = ap.parse_args()

    config = CoreConfig.from_env(os.environ)
    model = args.model or config.default_model

    if args.text:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.first_doc:
        text = await _text_from_first_doc(config.database_url)
    else:
        text = _SAMPLE

    provider = OllamaProvider(
        base_url=config.ollama_host,
        keep_alive=config.ollama_keep_alive,
        timeout=args.timeout,
        num_ctx=args.num_ctx,
    )
    print(f"model={model} num_ctx={args.num_ctx} input_chars={len(text)}")

    sizes = [int(s) for s in args.sweep.split(",")] if args.sweep else [args.window]
    for window in sizes:
        res, elapsed = await _run(
            text,
            provider=provider,
            model=model,
            window=window,
            overlap=args.overlap,
            max_windows=args.max_windows,
        )
        print(
            f"\n--- window={window} -> {len(res.entities)} entities, "
            f"{len(res.relations)} relations in {elapsed:.1f}s ---"
        )
        for e in res.entities:
            print(f"  {e.type:9} {e.name}")
        for r in res.relations:
            print(f"  REL  {r.src} -[{r.relation}]-> {r.dst}")


if __name__ == "__main__":
    asyncio.run(main())
