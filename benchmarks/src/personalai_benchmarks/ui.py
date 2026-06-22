"""A tiny local launcher UI for the benchmark (#332).

`python -m personalai_benchmarks ui` serves a localhost page to configure a `compare` run with
checkboxes, see the generated command, run it, and stream its stdout/stderr live into a log window.
Dev-only: binds 127.0.0.1, no auth. The run subprocess is built from a **validated** arg list
(providers ∈ registry, modes ∈ ALL_MODES, repeats int) with no shell, so the form can't inject
commands. Run it with `uv run --env-file .env …` so the spawned `compare` inherits your API keys.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from personalai_benchmarks import frontier
from personalai_benchmarks.modes import ALL_MODES
from personalai_benchmarks.tasks import load_tasks

_OUT_DIR = "benchmark-results"
_DEFAULT_TASKS = Path(__file__).resolve().parents[2] / "tasks"


_MODEL_TIERS = ("default", *frontier.MODEL_TIERS, "all")


def build_compare_args(
    *,
    providers: list[str],
    modes: list[str],
    task_ids: list[str],
    repeats: int,
    judge: bool,
    frontier_tools: bool,
    no_personalia: bool,
    base_url: str,
    model_tier: str = "default",
    out: str = _OUT_DIR,
) -> list[str]:
    """Validate the form selections and build the `compare` CLI args (raises ValueError if bad)."""
    bad_p = [p for p in providers if p not in frontier.PROVIDERS]
    if bad_p:
        raise ValueError(f"unknown providers: {', '.join(bad_p)}")
    bad_m = [m for m in modes if m not in ALL_MODES]
    if bad_m:
        raise ValueError(f"unknown modes: {', '.join(bad_m)}")
    if model_tier not in _MODEL_TIERS:
        raise ValueError(f"unknown model tier: {model_tier}")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    args = ["compare", "--out", out, "--base-url", base_url, "--repeats", str(repeats)]
    args += ["--model-tier", model_tier]
    if providers:
        args += ["--providers", ",".join(providers)]
    if modes:
        args += ["--modes", ",".join(modes)]
    if task_ids:
        args += ["--task-ids", ",".join(task_ids)]
    if no_personalia:
        args += ["--no-personalia"]
    if frontier_tools:
        args += ["--frontier-tools"]
    if not judge:
        args += ["--no-judge"]
    return args


def _render_page(base_url: str) -> str:
    providers = sorted(frontier.PROVIDERS)
    modes = [(name, m.capability_tier) for name, m in ALL_MODES.items()]
    try:
        task_ids = [(t.id, t.category) for t in load_tasks(_DEFAULT_TASKS)]
    except (FileNotFoundError, ValueError):
        task_ids = []
    data = {
        "providers": providers,
        "modes": modes,
        "tasks": task_ids,
        "modelTiers": list(_MODEL_TIERS),
        "baseUrl": base_url,
    }
    return _PAGE.replace("/*DATA*/", json.dumps(data)).replace("__BASE__", html.escape(base_url))


class _Handler(BaseHTTPRequestHandler):
    base_url = "http://127.0.0.1:8765"

    def log_message(self, *args: object) -> None:  # quiet
        pass

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(_render_page(self.base_url))
        elif parsed.path == "/run":
            self._stream_run(parse_qs(parsed.query))
        elif parsed.path == "/report":
            self._serve_report()
        else:
            self.send_error(404)

    def _send_html(self, body: str) -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_report(self) -> None:
        path = Path(_OUT_DIR) / "leaderboard.html"
        if not path.exists():
            self.send_error(404, "no report yet — run a benchmark first")
            return
        self._send_html(path.read_text())

    def _sse(self, event: str | None, payload: str) -> None:
        line = (f"event: {event}\n" if event else "") + f"data: {payload}\n\n"
        self.wfile.write(line.encode())
        self.wfile.flush()

    def _stream_run(self, params: dict[str, list[str]]) -> None:
        def one(key: str, default: str = "") -> str:
            return params.get(key, [default])[0]

        def many(key: str) -> list[str]:
            return [v for v in one(key).split(",") if v]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            args = build_compare_args(
                providers=many("providers"),
                modes=many("modes"),
                task_ids=many("task_ids"),
                repeats=int(one("repeats", "1") or "1"),
                judge=one("judge") == "1",
                frontier_tools=one("frontier_tools") == "1",
                no_personalia=one("no_personalia") == "1",
                model_tier=one("model_tier", "default") or "default",
                base_url=self.base_url,
            )
        except (ValueError, TypeError) as exc:
            self._sse("error", str(exc))
            return
        self._sse(None, "$ python -m personalai_benchmarks " + " ".join(args))
        proc = subprocess.Popen(  # noqa: S603 - args are a validated list, no shell
            [sys.executable, "-m", "personalai_benchmarks", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._sse(None, line.rstrip("\n"))
        except (BrokenPipeError, ConnectionResetError):
            proc.terminate()
            return
        code = proc.wait()
        self._sse("done", json.dumps({"code": code, "out": _OUT_DIR}))


def serve(*, port: int = 8900, base_url: str = "http://127.0.0.1:8765") -> int:
    """Run the launcher on ``port`` (blocks until Ctrl-C)."""
    _Handler.base_url = base_url
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"benchmark launcher: open {url}  (Ctrl-C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.", file=sys.stderr)
    finally:
        server.server_close()
    return 0


_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<title>PersonalAI benchmark launcher</title><style>
body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:1.5rem auto;
  max-width:900px;color:#1a1a1a;padding:0 1rem}
h1{font-size:1.3rem}
fieldset{border:1px solid #ddd;border-radius:6px;margin:0 0 .8rem;padding:.5rem .8rem}
legend{color:#555;font-size:.85rem}
label{display:inline-block;margin:.15rem .8rem .15rem 0}
.mono{background:#0d1117;color:#c9d1d9;border-radius:6px;
  font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap}
.cmd{padding:.5rem .7rem;word-break:break-all}
#log{padding:.6rem;height:340px;overflow:auto;line-height:1.45}
button{font-size:1rem;padding:.35rem 1rem;border-radius:6px;
  border:1px solid #1a7f37;background:#1a7f37;color:#fff;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
input[type=number]{width:4rem}
a{color:#1a7f37}
</style></head><body>
<h1>PersonalAI benchmark launcher</h1>
<p style="color:#666">Pick options, review the command, Run, and watch the output stream below.
Run the server with <code>uv run --env-file .env …</code> so the benchmark gets your API keys.</p>
<fieldset><legend>Frontier providers</legend><div id=providers></div></fieldset>
<fieldset><legend>PersonalAI modes</legend><div id=modes></div></fieldset>
<fieldset><legend>Tasks (none = all)</legend><div id=tasks></div></fieldset>
<fieldset><legend>Options</legend>
<label>model tier <select id=model_tier></select></label>
<label>repeats <input id=repeats type=number min=1 value=1></label>
<label><input id=judge type=checkbox checked> LLM judge</label>
<label><input id=frontier_tools type=checkbox> frontier with tools</label>
<label><input id=no_personalia type=checkbox> skip PersonalAI</label>
</fieldset>
<div class="cmd mono" id=cmd></div>
<p><button id=run>Run benchmark</button> <span id=status style="color:#666"></span></p>
<div id=log class=mono></div>
<script>
const D = /*DATA*/;
function chk(id, items, val, lbl){const el=document.getElementById(id);
  el.innerHTML = items.map(it=>{const v=val(it), l=lbl(it);
    return `<label><input type=checkbox value="${v}" data-g="${id}">${l}</label>`;}).join('');}
chk('providers', D.providers, x=>x, x=>x);
chk('modes', D.modes, x=>x[0], x=>`${x[0]} <small style=color:#888>(${x[1]})</small>`);
chk('tasks', D.tasks, x=>x[0], x=>`${x[0]} <small style=color:#888>(${x[1]})</small>`);
document.getElementById('model_tier').innerHTML =
  D.modelTiers.map(t=>`<option value="${t}">${t}</option>`).join('');
function picked(id){
  return [...document.querySelectorAll(`input[data-g=${id}]:checked`)].map(e=>e.value);}
function params(){return {
  providers:picked('providers'), modes:picked('modes'), task_ids:picked('tasks'),
  model_tier:document.getElementById('model_tier').value,
  repeats:document.getElementById('repeats').value,
  judge:document.getElementById('judge').checked?'1':'0',
  frontier_tools:document.getElementById('frontier_tools').checked?'1':'0',
  no_personalia:document.getElementById('no_personalia').checked?'1':'0'};}
function preview(){const p=params();
  let a=['compare','--repeats',p.repeats,'--model-tier',p.model_tier];
  if(p.providers.length)a.push('--providers',p.providers.join(','));
  if(p.modes.length)a.push('--modes',p.modes.join(','));
  if(p.task_ids.length)a.push('--task-ids',p.task_ids.join(','));
  if(p.no_personalia==='1')a.push('--no-personalia');
  if(p.frontier_tools==='1')a.push('--frontier-tools');
  if(p.judge==='0')a.push('--no-judge');
  document.getElementById('cmd').textContent='$ python -m personalai_benchmarks '+a.join(' ');}
document.body.addEventListener('change', preview); preview();
document.getElementById('run').onclick=function(){
  const log=document.getElementById('log'), st=document.getElementById('status');
  log.textContent=''; st.textContent='running…'; this.disabled=true;
  const qs=new URLSearchParams(params()).toString();
  const es=new EventSource('/run?'+qs);
  es.onmessage=e=>{log.textContent+=e.data+'\\n'; log.scrollTop=log.scrollHeight;};
  es.addEventListener('error',e=>{log.textContent+='[error] '+(e.data||'')+'\\n';});
  es.addEventListener('done',e=>{es.close(); document.getElementById('run').disabled=false;
    const d=JSON.parse(e.data);
    st.innerHTML=`done (exit ${d.code}) — `
      +`<a href="/report" target=_blank>open leaderboard</a>`;});
};
</script></body></html>"""
