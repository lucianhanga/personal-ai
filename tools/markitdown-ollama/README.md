# MarkItDown-on-Ollama MCP server

A small, self-contained **MCP server** that converts documents to Markdown with **local** image
descriptions / OCR via an **Ollama** vision model — no remote services.

The official [`markitdown-mcp`](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp)
does plain conversion only: it instantiates `MarkItDown()` with no LLM client and reads no env to
configure one, so images get no captions. This server wraps `MarkItDown(llm_client=…, llm_model=…)`
pointed at Ollama's OpenAI-compatible endpoint to fill that gap.

## Tool

- `convert_to_markdown(uri)` — `uri` is a local path, `file://`, `http(s)://`, or `data:` URI.
  Supports PDF, DOCX, PPTX, XLSX, HTML, images, and more. Images are described by the local model.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (runs the script and resolves its deps from the inline metadata)
- A vision model in Ollama, e.g.: `ollama pull qwen2.5vl:7b` (~6 GB; `qwen2.5vl:32b` for higher quality)

## Run standalone

```bash
uv run --script tools/markitdown-ollama/server.py
```

## Use from PersonalAI

Add to your `mcp.json` (then point `PERSONALAI_MCP_CONFIG` at it and restart the backend):

```json
"markitdown": {
  "command": "uv",
  "args": ["run", "--script", "/ABSOLUTE/PATH/tools/markitdown-ollama/server.py"],
  "env": { "MARKITDOWN_OLLAMA_MODEL": "qwen2.5vl:7b" }
}
```

## Configuration (env)

| Variable | Default | Meaning |
|---|---|---|
| `MARKITDOWN_OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama OpenAI-compatible endpoint |
| `MARKITDOWN_OLLAMA_MODEL` | `qwen2.5vl:7b` | Vision model pulled in Ollama |
| `OPENAI_API_KEY` | `ollama` | Ignored by Ollama; any non-empty value |

In PersonalAI this server's tool is third-party → **HIGH risk**: enable **approve high-risk** in chat
to let the agent call it. It can read any file the process user can access (`file://`) — treat
accordingly.
