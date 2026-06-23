"""A tiny local launcher UI for the benchmark (#332, streamlined in #351).

`python -m personalai_benchmarks ui` serves a localhost page to configure a `compare` run with
grouped, expandable checkbox trees (task categories -> tasks, providers -> models), review the
command, run it, and stream stdout/stderr live. The judge is always on (shown read-only). Each run
writes a timestamped report; past runs are listed.

Dev-only: binds 127.0.0.1, no auth. The run subprocess is built from a **validated** arg list
(models in the registry, modes in ALL_MODES, repeats int) with no shell, so the form can't inject
commands. Run it with `uv run --env-file .env …` so the spawned `compare` inherits your API keys.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from personalai_benchmarks import frontier
from personalai_benchmarks.judge import strongest_judge
from personalai_benchmarks.modes import ALL_MODES
from personalai_benchmarks.tasks import load_tasks

_OUT_DIR = "benchmark-results"
_DEFAULT_TASKS = Path(__file__).resolve().parents[2] / "tasks"


def _valid_models() -> set[str]:
    """Every selectable ``provider:model`` from the registry (the form's allow-list)."""
    return {f"{name}:{m.id}" for name, p in frontier.PROVIDERS.items() for m in p.models}


def build_compare_args(
    *,
    models: list[str],
    modes: list[str],
    task_ids: list[str],
    repeats: int,
    no_personalia: bool,
    base_url: str,
    out: str = _OUT_DIR,
) -> list[str]:
    """Validate the form selections and build the `compare` CLI args (raises ValueError if bad)."""
    bad_models = [m for m in models if m not in _valid_models()]
    if bad_models:
        raise ValueError(f"unknown models: {', '.join(bad_models)}")
    bad_modes = [m for m in modes if m not in ALL_MODES]
    if bad_modes:
        raise ValueError(f"unknown modes: {', '.join(bad_modes)}")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    args = ["compare", "--out", out, "--base-url", base_url, "--repeats", str(repeats)]
    if models:
        args += ["--models", ",".join(models)]
    if modes:
        args += ["--modes", ",".join(modes)]
    if task_ids:
        args += ["--task-ids", ",".join(task_ids)]
    if no_personalia:
        args += ["--no-personalia"]
    return args


def _list_runs() -> list[str]:
    """Past report directories (timestamp names), newest first."""
    base = Path(_OUT_DIR)
    if not base.is_dir():
        return []
    runs = [p.name for p in base.iterdir() if p.is_dir() and (p / "leaderboard.html").exists()]
    return sorted(runs, reverse=True)


def _render_page(base_url: str) -> str:
    providers = {name: [m.id for m in p.models] for name, p in frontier.PROVIDERS.items()}
    modes = [(name, m.capability_tier) for name, m in ALL_MODES.items()]
    tasks: dict[str, list[str]] = defaultdict(list)
    try:
        for t in load_tasks(_DEFAULT_TASKS):
            tasks[t.category].append(t.id)
    except (FileNotFoundError, ValueError):
        pass
    _, judge_label = strongest_judge()
    data = {
        "providers": providers,
        "modes": modes,
        "tasks": dict(sorted(tasks.items())),
        "judge": judge_label,
        "baseUrl": base_url,
    }
    return _PAGE.replace("/*DATA*/", json.dumps(data))


class _Handler(BaseHTTPRequestHandler):
    base_url = "http://127.0.0.1:8765"
    current_proc: subprocess.Popen[str] | None = None  # the in-flight benchmark, for /stop

    def log_message(self, *args: object) -> None:  # quiet
        pass

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(_render_page(self.base_url))
        elif parsed.path == "/run":
            self._stream_run(parse_qs(parsed.query))
        elif parsed.path == "/stop":
            self._stop()
        elif parsed.path == "/runs":
            self._send_json({"runs": _list_runs()})
        elif parsed.path == "/report":
            self._serve_report(parse_qs(parsed.query))
        else:
            self.send_error(404)

    def _stop(self) -> None:
        # SIGINT (not kill) so the CLI catches KeyboardInterrupt and still writes a partial report.
        proc = type(self).current_proc
        stopping = proc is not None and proc.poll() is None
        if stopping and proc is not None:
            proc.send_signal(signal.SIGINT)
        self._send_json({"stopping": stopping})

    def _send_json(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, body: str) -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_report(self, params: dict[str, list[str]]) -> None:
        runs = _list_runs()
        run = params.get("run", [""])[0]
        chosen = (
            run if run in runs else (runs[0] if runs else None)
        )  # validated against the listing
        if chosen is None:
            self.send_error(404, "no report yet — run a benchmark first")
            return
        self._send_html((Path(_OUT_DIR) / chosen / "leaderboard.html").read_text())

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
                models=many("models"),
                modes=many("modes"),
                task_ids=many("task_ids"),
                repeats=int(one("repeats", "1") or "1"),
                no_personalia=one("no_personalia") == "1",
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
        type(self).current_proc = proc  # let /stop signal this run
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._sse(None, line.rstrip("\n"))
        except (BrokenPipeError, ConnectionResetError):
            proc.terminate()
            return
        finally:
            if type(self).current_proc is proc:
                type(self).current_proc = None
        code = proc.wait()
        self._sse("done", json.dumps({"code": code}))


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
fieldset{border:1px solid #ddd;border-radius:6px;margin:0 0 .8rem;padding:.3rem .8rem}
legend{color:#555;font-size:.85rem}
.mono{background:#0d1117;color:#c9d1d9;border-radius:6px;
  font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap}
.cmd{padding:.5rem .7rem;word-break:break-all}
#log{padding:.6rem;height:300px;overflow:auto;line-height:1.45}
button{font-size:1rem;padding:.35rem 1rem;border-radius:6px;
  border:1px solid #1a7f37;background:#1a7f37;color:#fff;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
input[type=number]{width:4rem}
a{color:#1a7f37}
.opts label{display:inline-block;margin:.15rem .8rem .15rem 0}
.judge{color:#555;font-size:.9rem;margin:.2rem 0 .6rem}
.cbtree .group{position:relative;border-bottom:1px solid #eee}
.cbtree .group>.parent{position:absolute;left:6px;top:9px;z-index:1}
summary.grouprow{list-style:none;cursor:pointer;display:flex;align-items:center;gap:8px;
  padding:6px 6px 6px 30px}
summary.grouprow::-webkit-details-marker{display:none}
.chev{width:7px;height:7px;border-right:2px solid #888;border-bottom:2px solid #888;
  transform:rotate(-45deg);transition:transform .15s}
.cbtree details[open] .chev{transform:rotate(45deg)}
.count{margin-left:auto;font-variant-numeric:tabular-nums;color:#888;font-size:.85em}
.children{padding:2px 8px 8px 30px;display:grid;gap:2px}
.children label{display:flex;align-items:center;gap:6px;margin:0;font-size:.92em}
.toolbar{font-size:.82rem;color:#888;padding:.1rem 0 .3rem 4px}
.linkbtn{background:none;border:none;color:#1a7f37;cursor:pointer;padding:0 6px;font-size:.85rem}
#runs{font-size:.85rem}#runs a{display:inline-block;margin:.1rem .6rem .1rem 0}
@media (prefers-reduced-motion: reduce){.chev{transition:none}}
</style></head><body>
<h1>PersonalAI benchmark launcher</h1>
<p style="color:#666">Pick categories and models, review the command, Run, and watch it stream.
Run the server with <code>uv run --env-file .env …</code> so the benchmark gets your API keys.</p>
<fieldset><legend>Frontier providers / models (vs the app)</legend>
  <div class=toolbar><button type=button class=linkbtn data-all=providers,1>select all</button>
    <button type=button class=linkbtn data-all=providers,0>clear</button></div>
  <div class=cbtree id=providers></div></fieldset>
<fieldset><legend>Tasks (by category; none = all)</legend>
  <div class=toolbar><button type=button class=linkbtn data-all=tasks,1>select all</button>
    <button type=button class=linkbtn data-all=tasks,0>clear</button></div>
  <div class=cbtree id=tasks></div></fieldset>
<fieldset><legend>PersonalAI modes</legend><div class=opts id=modes></div></fieldset>
<fieldset><legend>Options</legend><div class=opts>
<label>repeats <input id=repeats type=number min=1 value=1></label>
<label><input id=no_personalia type=checkbox> skip PersonalAI (frontier only)</label>
</div></fieldset>
<div class=judge id=judge></div>
<div class="cmd mono" id=cmd></div>
<p><button id=run>Run benchmark</button>
<button id=stop disabled style="background:#b00020;border-color:#b00020">Stop</button>
<span id=status style="color:#666"></span></p>
<div id=log class=mono></div>
<fieldset><legend>Report history</legend><div id=runs>none yet</div></fieldset>
<script>
const D = /*DATA*/;
document.getElementById('judge').textContent = 'Judge (always on, fixed): ' + D.judge;
function buildTree(root, groups){
  root.innerHTML = groups.map((g,gi)=>{
    const kids = g.children.map(c=>
      `<label><input type=checkbox class=child value="${c.value}"> ${c.label}</label>`).join('');
    const lid = root.id+'-g'+gi;
    // The parent checkbox is a sibling of <details> (in the .group wrapper), NOT a child of
    // <details> before <summary> — otherwise the browser hides it while collapsed.
    return `<div class=group><input type=checkbox class=parent aria-labelledby="${lid}">`
      +`<details><summary class=grouprow><span class=chev aria-hidden=true></span>`
      +`<span class=grouplabel id="${lid}">${g.label}</span>`
      +`<span class=count data-count>0 / ${g.children.length}</span></summary>`
      +`<div class=children role=group aria-labelledby="${lid}">${kids}</div></details></div>`;
    }).join('');
  function syncGroup(g){
    const parent=g.querySelector('.parent'), kids=[...g.querySelectorAll('.child')];
    const n=kids.filter(k=>k.checked).length;
    parent.checked = n===kids.length && kids.length>0;
    parent.indeterminate = n>0 && n<kids.length;  // visual tri-state, recomputed from children
    g.querySelector('[data-count]').textContent = `${n} / ${kids.length}`;}
  root.addEventListener('change', e=>{
    const g=e.target.closest('.group'); if(!g) return;
    if(e.target.classList.contains('parent'))
      g.querySelectorAll('.child').forEach(k=>k.checked=e.target.checked);
    syncGroup(g); preview();});
  root.querySelectorAll('.group').forEach(syncGroup);
}
function checked(rootId){
  return [...document.querySelectorAll('#'+rootId+' .child:checked')].map(e=>e.value);}
buildTree(document.getElementById('providers'),
  Object.entries(D.providers).map(([p,ids])=>({label:p,
    children:ids.map(id=>({value:p+':'+id, label:id}))})));
buildTree(document.getElementById('tasks'),
  Object.entries(D.tasks).map(([c,ids])=>({label:c,
    children:ids.map(id=>({value:id, label:id}))})));
document.getElementById('modes').innerHTML = D.modes.map(m=>
  `<label><input type=checkbox class=mode value="${m[0]}"> ${m[0]} `
  +`<small style=color:#888>(${m[1]})</small></label>`).join('');
function params(){return {
  models:checked('providers').join(','), task_ids:checked('tasks').join(','),
  modes:[...document.querySelectorAll('.mode:checked')].map(e=>e.value).join(','),
  repeats:document.getElementById('repeats').value,
  no_personalia:document.getElementById('no_personalia').checked?'1':'0'};}
function preview(){const p=params(); let a=['compare','--repeats',p.repeats];
  if(p.models)a.push('--models',p.models);
  if(p.modes)a.push('--modes',p.modes);
  if(p.task_ids)a.push('--task-ids','('+p.task_ids.split(',').length+' tasks)');
  if(p.no_personalia==='1')a.push('--no-personalia');
  document.getElementById('cmd').textContent='$ python -m personalai_benchmarks '+a.join(' ');}
document.querySelectorAll('.linkbtn[data-all]').forEach(b=>b.onclick=()=>{
  const [root,on]=b.dataset.all.split(',');
  document.querySelectorAll('#'+root+' .child').forEach(k=>k.checked=on==='1');
  document.querySelectorAll('#'+root+' .group').forEach(g=>
    g.dispatchEvent(new Event('change',{bubbles:true})));});
document.getElementById('modes').addEventListener('change', preview);
document.getElementById('no_personalia').addEventListener('change', preview);
document.getElementById('repeats').addEventListener('input', preview);
function loadRuns(){fetch('/runs').then(r=>r.json()).then(d=>{
  const el=document.getElementById('runs');
  el.innerHTML = d.runs.length ? d.runs.map(r=>
    `<a href="/report?run=${encodeURIComponent(r)}" target=_blank>${r}</a>`).join('')
    : 'none yet';});}
preview(); loadRuns();
const runBtn=document.getElementById('run'), stopBtn=document.getElementById('stop');
runBtn.onclick=function(){
  const log=document.getElementById('log'), st=document.getElementById('status');
  log.textContent=''; st.textContent='running…'; runBtn.disabled=true; stopBtn.disabled=false;
  const es=new EventSource('/run?'+new URLSearchParams(params()).toString());
  es.onmessage=e=>{log.textContent+=e.data+'\\n'; log.scrollTop=log.scrollHeight;};
  es.addEventListener('error',e=>{log.textContent+='[error] '+(e.data||'')+'\\n';});
  es.addEventListener('done',e=>{es.close(); runBtn.disabled=false; stopBtn.disabled=true;
    const d=JSON.parse(e.data); loadRuns();
    st.innerHTML=`done (exit ${d.code}) — `
      +`<a href="/report" target=_blank>open latest leaderboard</a>`;});
};
stopBtn.onclick=function(){
  stopBtn.disabled=true;
  document.getElementById('status').textContent='stopping — writing partial report…';
  fetch('/stop');};
</script></body></html>"""
