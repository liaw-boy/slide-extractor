#!/usr/bin/env python3
"""Slide Extractor — single-server web GUI.

One process, one port. Open the page, paste a YouTube URL or a local video
path, pick a mode, watch the progress, then prune candidates on the same
dark contact-sheet UI that `slide_review.py` already ships. Final PPTX
downloads from the same page.

Routes (all served by the one Handler):
    GET  /                       submission form
    POST /api/start              kick off background extraction
    GET  /job/<id>               progress page (polls /api/job/<id>)
    GET  /api/job/<id>           JSON status (status, log, slide_count, …)
    GET  /job/<id>/sheet         contact sheet (after status == done)
    GET  /job/<id>/slides/<file> serve a slide PNG
    POST /api/job/<id>/finalize  build REVIEWED PPTX from chosen kept-list
    GET  /job/<id>/pptx          download AUTO PPTX
    GET  /job/<id>/pptx_reviewed download REVIEWED PPTX
"""
from __future__ import annotations

import argparse
import http.server
import json
import logging
import shutil
import socketserver
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from slide_extractor import (  # noqa: E402
    LOG,
    ExtractorConfig,
    extract_slides,
    resolve_source,
)
from slide_review import build_contact_sheet, export_filtered_pptx  # noqa: E402


# ────────────────────────── job model ──────────────────────────
@dataclass
class Job:
    """In-memory state for a single extraction request."""

    id: str
    source: str
    mode: str  # "auto" | "review"
    output_dir: Path
    status: str = "queued"
    log: list[str] = field(default_factory=list)
    slides_dir: Optional[Path] = None
    pptx_path: Optional[Path] = None
    reviewed_pptx_path: Optional[Path] = None
    slide_count: int = 0
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def _log(job: Job, msg: str) -> None:
    job.log.append(msg)
    LOG.info("[job %s] %s", job.id[:8], msg)


def run_job(job: Job) -> None:
    """Worker: download (if URL) → extract → contact sheet → auto PPTX."""
    try:
        job.status = "resolving"
        _log(job, f"resolving: {job.source}")
        video_path = resolve_source(job.source, job.output_dir / "_video")
        _log(job, f"video file: {video_path}")

        title = video_path.stem
        job.slides_dir = job.output_dir / title
        job.pptx_path = job.output_dir / f"{title}.pptx"
        job.reviewed_pptx_path = job.output_dir / f"{title}_REVIEWED.pptx"

        if job.slides_dir.exists():
            shutil.rmtree(job.slides_dir)

        cfg = ExtractorConfig(
            sample_sec=2.0 if job.mode == "review" else 3.0,
            cluster_jaccard=0.30 if job.mode == "review" else 0.45,
            min_duration_sec=3.0 if job.mode == "review" else 9.0,
        )

        job.status = "extracting"
        _log(job, f"extracting (mode={job.mode}, sample={cfg.sample_sec}s)")
        paths = extract_slides(video_path, job.slides_dir, cfg)
        job.slide_count = len(paths)
        _log(job, f"extracted {len(paths)} candidates")

        if paths:
            export_filtered_pptx(
                job.slides_dir, [p.name for p in paths], job.pptx_path
            )
            _log(job, f"auto PPTX → {job.pptx_path.name}")

            sheet_path = job.output_dir / f"_sheet_{job.id}.html"
            build_contact_sheet(job.slides_dir, sheet_path)
            _log(job, "contact sheet ready")

        job.status = "done"
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)
        _log(job, f"ERROR: {e}")


# ────────────────────────── HTML ──────────────────────────
THEME_CSS = """
  :root {
    --bg: #0f0f12; --card: #1c1c22; --text: #f5f5f5;
    --accent: #4ade80; --muted: #888; --danger: #f87171;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    min-height: 100vh;
  }
  header {
    padding: 32px 24px 16px;
    border-bottom: 1px solid #2a2a30;
  }
  h1 { margin: 0; font-size: 22px; font-weight: 600; }
  .hint { color: var(--muted); font-size: 13px; margin-top: 6px; }
  main { padding: 24px; max-width: 720px; margin: 0 auto; }
  form { display: flex; flex-direction: column; gap: 18px; }
  label.field { display: flex; flex-direction: column; gap: 6px; }
  label.field span { font-size: 13px; color: var(--muted); }
  input[type=text] {
    background: var(--card); color: var(--text);
    border: 1px solid #333; border-radius: 8px;
    padding: 12px 14px; font-size: 15px; font-family: inherit;
  }
  input[type=text]:focus { outline: none; border-color: var(--accent); }
  .modes { display: flex; gap: 16px; flex-wrap: wrap; }
  .modes label {
    background: var(--card); border: 1px solid #333; border-radius: 8px;
    padding: 10px 14px; cursor: pointer; flex: 1;
    display: flex; flex-direction: column; gap: 4px;
  }
  .modes label:has(input:checked) { border-color: var(--accent); }
  .modes label small { color: var(--muted); font-size: 12px; }
  button {
    background: var(--accent); color: #000; border: none;
    padding: 12px 20px; border-radius: 8px; cursor: pointer;
    font-size: 15px; font-weight: 600;
  }
  button:disabled { opacity: 0.5; cursor: wait; }
  button.ghost { background: var(--card); color: var(--text); border: 1px solid #333; }
  pre.log {
    background: #000; color: #9ca3af;
    padding: 14px; border-radius: 8px;
    font-size: 12px; max-height: 320px; overflow-y: auto;
    white-space: pre-wrap; word-break: break-all;
  }
  .status-pill {
    display: inline-block; padding: 4px 10px; border-radius: 999px;
    background: var(--card); font-size: 12px; margin-left: 8px;
  }
  .status-pill.done { background: var(--accent); color: #000; }
  .status-pill.error { background: var(--danger); color: #000; }
  a.button-link { display: inline-block; text-decoration: none; }
"""

INDEX_HTML = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head>
<meta charset="utf-8">
<title>Slide Extractor</title>
<style>{THEME_CSS}
  .scope, .notice {{
    background: var(--card); border: 1px solid #2a2a30;
    border-radius: 8px; padding: 14px 16px; font-size: 13px;
    line-height: 1.6; color: #cbd5e1;
  }}
  .scope h3, .notice h3 {{
    margin: 0 0 8px; font-size: 13px; color: var(--accent);
    text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .scope ul {{ margin: 4px 0; padding-left: 20px; }}
  .scope li {{ margin: 2px 0; }}
  .notice {{ border-left: 3px solid #facc15; }}
  .notice h3 {{ color: #facc15; }}
  footer {{
    padding: 24px; text-align: center; color: var(--muted);
    font-size: 11px; border-top: 1px solid #2a2a30; margin-top: 40px;
  }}
</style>
</head><body>
<header>
  <h1>Slide Extractor</h1>
  <p class="hint">YouTube 連結 或 本機影片路徑都可以。最終輸出：PNG + PPTX。</p>
</header>
<main>
  <form id="start" onsubmit="return submitForm(event)">
    <label class="field">
      <span>Source（YouTube URL 或本機影片絕對路徑）</span>
      <input type="text" id="source" required
        placeholder="https://www.youtube.com/watch?v=…   或   /home/you/lecture.mp4" />
    </label>
    <div class="modes">
      <label>
        <input type="radio" name="mode" value="auto" checked />
        <strong>Auto</strong>
        <small>最快，95%+ 準確，會直接生成 PPTX</small>
      </label>
      <label>
        <input type="radio" name="mode" value="review" />
        <strong>Review</strong>
        <small>過收所有候選，你勾完再生成 PPTX，100% 不漏頁</small>
      </label>
    </div>
    <button type="submit" id="go">開始抓 slide</button>
  </form>

  <div style="margin-top: 28px; display: flex; flex-direction: column; gap: 14px;">
    <div class="scope">
      <h3>適用範圍</h3>
      <div><strong style="color: var(--accent)">✓ 設計給</strong>：螢幕錄製的 PowerPoint/Keynote/Google Slides 講演、技術分享、線上課程等「以靜態投影片為主」的影片（中文 + 英文）。</div>
      <ul>
        <li>🟡 邊緣案例（會出但可能要 review 模式）：簡報帶講者小視窗、頁面有嵌入短片、code-heavy 文字稀疏、非中英文（用 <code>--lang</code> 切換 OCR）。</li>
        <li>✗ 不適用：白板/手寫教學、軟體 demo 螢幕錄製、純講者頭像無投影片、Prezi 平滑縮放、影片少於 30 秒。</li>
      </ul>
    </div>

    <div class="notice">
      <h3>⚠ 著作權聲明 · Copyright</h3>
      本工具僅供<strong>個人學習用途</strong>。使用者必須擁有影片內容的合法存取權限，並遵守原內容的著作權條款與平台服務條款。<br>
      請<strong>勿</strong>用於：(1) 重製、傳播他人受著作權保護的內容；(2) 商業性質的二次利用；(3) 違反平台 ToS 的行為。<br>
      <span style="color: var(--muted)">本工具完全在本機運作，不上傳任何影片或截圖到外部伺服器。</span>
    </div>
  </div>
</main>
<footer>
  Slide Extractor · 個人學習工具 · 請尊重原作者著作權
</footer>
<script>
async function submitForm(e) {{
  e.preventDefault();
  const source = document.getElementById('source').value.trim();
  const mode = document.querySelector('input[name=mode]:checked').value;
  const btn = document.getElementById('go');
  btn.disabled = true; btn.textContent = '建立 job…';
  const r = await fetch('/api/start', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ source, mode }})
  }});
  const data = await r.json();
  if (!data.ok) {{
    btn.disabled = false; btn.textContent = '開始抓 slide';
    alert('失敗：' + data.error); return;
  }}
  location.href = '/job/' + data.job_id;
}}
</script>
</body></html>"""


def progress_html(job_id: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head>
<meta charset="utf-8">
<title>Job {job_id[:8]} — Slide Extractor</title>
<style>{THEME_CSS}</style>
</head><body>
<header>
  <h1>進度 <span id="pill" class="status-pill">queued</span></h1>
  <p class="hint">Job <code>{job_id[:8]}</code> · 自動更新；完成後會出現操作按鈕。</p>
</header>
<main>
  <pre class="log" id="log">等待…</pre>
  <div id="actions" style="margin-top:18px; display:flex; gap:12px; flex-wrap:wrap;"></div>
  <p style="margin-top:24px"><a href="/" style="color: var(--muted)">← 抓另一個影片</a></p>
</main>
<script>
const jobId = "{job_id}";
const pill = document.getElementById('pill');
const logEl = document.getElementById('log');
const actions = document.getElementById('actions');

async function poll() {{
  const r = await fetch('/api/job/' + jobId);
  const j = await r.json();
  pill.textContent = j.status;
  pill.className = 'status-pill ' + (j.status === 'done' ? 'done' : j.status === 'error' ? 'error' : '');
  logEl.textContent = j.log.join('\\n');
  logEl.scrollTop = logEl.scrollHeight;
  if (j.status === 'done') {{
    renderActions(j);
    return;
  }}
  if (j.status === 'error') return;
  setTimeout(poll, 1500);
}}
function renderActions(j) {{
  const parts = [];
  if (j.slide_count > 0) {{
    parts.push(`<a class="button-link" href="/job/${{jobId}}/sheet"><button>看 ${{j.slide_count}} 張候選 / 勾選後生成 PPTX</button></a>`);
    parts.push(`<a class="button-link" href="/job/${{jobId}}/pptx" download><button class="ghost">下載 Auto PPTX</button></a>`);
  }} else {{
    parts.push(`<span style="color: var(--muted)">沒抓到 slide — 試試 review 模式或檢查影片來源</span>`);
  }}
  actions.innerHTML = parts.join('');
}}
poll();
</script>
</body></html>"""


# ────────────────────────── HTTP handler ──────────────────────────
def make_handler(output_dir: Path) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: N802
            print(f"[{self.address_string()}] {fmt % args}")

        # ── helpers ──
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, payload: dict) -> None:
            self._send(code, json.dumps(payload).encode(), "application/json")

        def _send_file(self, path: Path, ctype: str) -> None:
            if not path.exists():
                self.send_error(404, f"not found: {path.name}")
                return
            data = path.read_bytes()
            # HTTP headers must be latin-1; non-ASCII filenames require RFC 5987.
            ascii_fallback = path.name.encode("ascii", "replace").decode("ascii").replace("?", "_")
            utf8_encoded = quote(path.name, safe="")
            disposition = (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{utf8_encoded}"
            )
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", disposition)
            self.end_headers()
            self.wfile.write(data)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(length) if length > 0 else b""

        def _get_job(self, jid: str) -> Optional[Job]:
            with JOBS_LOCK:
                return JOBS.get(jid)

        # ── GET ──
        def do_GET(self):  # noqa: N802
            path = unquote(self.path.split("?", 1)[0])
            if path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
                return
            if path.startswith("/job/"):
                parts = path[len("/job/"):].split("/", 1)
                jid = parts[0]
                sub = parts[1] if len(parts) > 1 else ""
                job = self._get_job(jid)
                if not job:
                    self.send_error(404, "no such job")
                    return
                if sub == "":
                    self._send(200, progress_html(jid).encode(), "text/html; charset=utf-8")
                    return
                if sub == "sheet":
                    sheet = output_dir / f"_sheet_{jid}.html"
                    self._send(200, sheet.read_bytes(), "text/html; charset=utf-8")
                    return
                if sub == "pptx" and job.pptx_path:
                    self._send_file(job.pptx_path,
                                    "application/vnd.openxmlformats-officedocument.presentationml.presentation")
                    return
                if sub == "pptx_reviewed" and job.reviewed_pptx_path:
                    self._send_file(job.reviewed_pptx_path,
                                    "application/vnd.openxmlformats-officedocument.presentationml.presentation")
                    return
                if sub.startswith("slides/") and job.slides_dir:
                    name = sub[len("slides/"):]
                    self._send_file(job.slides_dir / name, "image/png")
                    return
                self.send_error(404)
                return
            if path.startswith("/api/job/"):
                jid = path[len("/api/job/"):]
                job = self._get_job(jid)
                if not job:
                    self._send_json(404, {"ok": False, "error": "no such job"})
                    return
                self._send_json(200, {
                    "ok": True, "status": job.status, "log": job.log,
                    "slide_count": job.slide_count, "error": job.error,
                    "has_pptx": bool(job.pptx_path and job.pptx_path.exists()),
                    "has_reviewed": bool(job.reviewed_pptx_path and job.reviewed_pptx_path.exists()),
                })
                return
            self.send_error(404)

        # ── POST ──
        def do_POST(self):  # noqa: N802
            path = unquote(self.path.split("?", 1)[0])
            if path == "/api/start":
                try:
                    body = json.loads(self._read_body() or b"{}")
                    source = (body.get("source") or "").strip()
                    mode = body.get("mode", "auto")
                    if not source:
                        self._send_json(400, {"ok": False, "error": "source required"})
                        return
                    if mode not in ("auto", "review"):
                        self._send_json(400, {"ok": False, "error": "mode must be auto|review"})
                        return
                    job = Job(id=uuid.uuid4().hex, source=source, mode=mode, output_dir=output_dir)
                    with JOBS_LOCK:
                        JOBS[job.id] = job
                    t = threading.Thread(target=run_job, args=(job,), daemon=True)
                    t.start()
                    self._send_json(200, {"ok": True, "job_id": job.id})
                except Exception as e:  # noqa: BLE001
                    self._send_json(500, {"ok": False, "error": str(e)})
                return
            if path.startswith("/api/job/") and path.endswith("/finalize"):
                jid = path[len("/api/job/"):-len("/finalize")]
                job = self._get_job(jid)
                if not job or not job.slides_dir or not job.reviewed_pptx_path:
                    self._send_json(404, {"ok": False, "error": "no such job"})
                    return
                try:
                    body = json.loads(self._read_body())
                    kept = body.get("kept", [])
                    export_filtered_pptx(job.slides_dir, kept, job.reviewed_pptx_path)
                    self._send_json(200, {
                        "ok": True, "n": len(kept),
                        "download": f"/job/{jid}/pptx_reviewed",
                    })
                except Exception as e:  # noqa: BLE001
                    self._send_json(500, {"ok": False, "error": str(e)})
                return
            self.send_error(404)

    # Patch the contact-sheet template so it POSTs to the per-job finalize URL.
    # The shipped slide_review.build_contact_sheet writes a fetch('/finalize')
    # call; rewrite when we serve the sheet.
    return Handler


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ────────────────────────── contact-sheet rewrite ──────────────────────────
# The existing sheet posts to /finalize. We serve sheets per job, so we need
# the JS to post to /api/job/<id>/finalize and then redirect to the download.
# Patch the HTML once we read it from disk.
def _rewrite_sheet(html: bytes, job_id: str) -> bytes:
    html_str = html.decode("utf-8")
    html_str = html_str.replace(
        "fetch('/finalize'",
        f"fetch('/api/job/{job_id}/finalize'",
    )
    # Replace the alert with a redirect to download
    old_alert = "alert('✓ PPTX 已生成：' + result.pptx);"
    new_action = (
        "window.location.href = result.download;"
    )
    html_str = html_str.replace(old_alert, new_action)
    # Also rewrite image src `slides/...` → `/job/<id>/slides/...`
    html_str = html_str.replace(
        'src="slides/', f'src="/job/{job_id}/slides/'
    )
    return html_str.encode("utf-8")


# Monkey-patch the GET handler for /job/<id>/sheet through the make_handler
# closure (cleanest: hook into _send_file path read). We do it by overriding
# the sheet branch in do_GET above. To keep do_GET tidy, replace its sheet
# branch using a small wrapper.
def make_handler_v2(output_dir: Path) -> type[http.server.BaseHTTPRequestHandler]:
    base = make_handler(output_dir)

    class Handler(base):  # type: ignore[misc, valid-type]
        def do_GET(self):  # noqa: N802
            path = unquote(self.path.split("?", 1)[0])
            if path.startswith("/job/") and path.endswith("/sheet"):
                jid = path[len("/job/"):-len("/sheet")]
                job = self._get_job(jid)
                if not job:
                    self.send_error(404)
                    return
                sheet = output_dir / f"_sheet_{jid}.html"
                if not sheet.exists():
                    self.send_error(404, "sheet not built")
                    return
                patched = _rewrite_sheet(sheet.read_bytes(), jid)
                self._send(200, patched, "text/html; charset=utf-8")
                return
            super().do_GET()

    return Handler


# ────────────────────────── main ──────────────────────────
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="slide-web",
        description="Web GUI for slide-extractor (single port, dark theme, drop-in).",
    )
    p.add_argument("-o", "--output", type=Path, default=Path.home() / "slides_output",
                   help="Output base directory (default: ~/slides_output)")
    p.add_argument("--port", type=int, default=8903)
    p.add_argument("--bind", default="0.0.0.0")
    args = p.parse_args(argv)

    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    handler = make_handler_v2(args.output)
    with ReusableTCPServer((args.bind, args.port), handler) as srv:
        host = "<your-host>" if args.bind == "0.0.0.0" else args.bind
        print(f"\n▶ Slide Extractor Web GUI: http://{host}:{args.port}/")
        print(f"  Tailscale: http://100.94.113.75:{args.port}/")
        print(f"  Local:     http://localhost:{args.port}/")
        print("  Ctrl+C 結束。\n")
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
