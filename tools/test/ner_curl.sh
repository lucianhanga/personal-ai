#!/usr/bin/env bash
# Test the raw NER call against Ollama via curl -- the exact request one NER window makes (#464).
#
#   bash tools/test/ner_curl.sh "your text to extract from"
#
# Env knobs (the ones that decide success on the Qwen3 35B MoE):
#   MODEL    default qwen3.6:35b-a3b
#   NUM_CTX  default 4096   (32K OOM-crashes Ollama on this model)
#   THINK    default no_think | low | off   (how reasoning is requested)
#
# Lesson: keep the text SMALL (<= ~1500 chars). Large windows make this MoE return EMPTY content.
set -euo pipefail
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
MODEL="${MODEL:-qwen3.6:35b-a3b}"
NUM_CTX="${NUM_CTX:-4096}"
THINK="${THINK:-no_think}"
TEXT="${1:-Rechnung von M-Net Telekommunikations GmbH an Lucian Hanga, Betrag 39,99 EUR, Rechnungsnummer R-2026-0042, Datum 2026-01-15.}"

PAYLOAD=$(MODEL="$MODEL" NUM_CTX="$NUM_CTX" THINK="$THINK" python3 - "$TEXT" <<'PY'
import json, os, sys

text = sys.argv[1]
prompt = (
    "You are a thorough named-entity extractor. Extract EVERY named entity actually present in the "
    "text -- be exhaustive. Capture people; organizations and companies (vendors, senders, issuers "
    "-- e.g. the company on an invoice, wherever it appears); locations; dates; products and line "
    "items; events; and identifiers/amounts (invoice/order/reference numbers, totals) as type "
    "'other'. Do NOT invent entities. Use a type from this EXACT set: person, org, location, date, "
    "product, event, other. Return ONLY the structured result."
)
schema = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["person", "org", "location", "date", "product", "event", "other"],
                    },
                    "name": {"type": "string"},
                },
                "required": ["type", "name"],
            },
        }
    },
    "required": ["entities"],
}

messages = []
think = os.environ["THINK"]
if think == "no_think":
    messages.append({"role": "system", "content": "/no_think"})
messages.append({"role": "system", "content": prompt})
messages.append({"role": "user", "content": text})

payload = {
    "model": os.environ["MODEL"],
    "messages": messages,
    "format": schema,
    "stream": False,
    "keep_alive": "30m",
    "options": {"num_ctx": int(os.environ["NUM_CTX"])},
}
# THINK=low|off requests reasoning explicitly (some Ollama builds accept a level string).
if think == "low":
    payload["think"] = "low"
elif think == "off":
    payload["think"] = False
print(json.dumps(payload))
PY
)

echo ">>> POST $HOST/api/chat  model=$MODEL num_ctx=$NUM_CTX think=$THINK chars=${#TEXT}" >&2
curl -s "$HOST/api/chat" -d "$PAYLOAD" \
  | python3 -c "import sys,json;r=json.load(sys.stdin);print(r.get('message',{}).get('content') or '(EMPTY content) '+json.dumps(r)[:300])"
