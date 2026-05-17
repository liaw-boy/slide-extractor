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
import re
import shutil
import socketserver
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from slide_extractor import (  # noqa: E402
    LOG,
    CancelledError,
    ExtractorConfig,
    extract_slides,
    is_url,
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
    # Live progress (-1 = indeterminate / no bar shown)
    progress_current: int = 0
    progress_total: int = 0
    progress_label: str = ""
    # T-G04 — cancellation. Not persisted (each server start gets fresh events).
    cancel_event: threading.Event = field(default_factory=threading.Event)


# ────────────────────────── progress wiring ──────────────────────────
RE_TOTAL_FRAMES = re.compile(r"frames=(\d+) sample-interval=(\d+)")
RE_SAMPLED = re.compile(r"sampled (\d+) valid frames")
RE_SAMPLING_DONE = re.compile(r"sampling done: (\d+) valid frames")
RE_SLIDE_OUT = re.compile(r"\[\+\] slide (\d+) @")
RE_YTDLP_PCT = re.compile(r"\[download\]\s+([\d.]+)%")


class JobProgressHandler(logging.Handler):
    """Translate slide_extractor LOG records into per-job progress fields."""

    def __init__(self, job: Job):
        super().__init__(level=logging.INFO)
        self.job = job
        self._total_samples = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if m := RE_TOTAL_FRAMES.search(msg):
            frames = int(m.group(1))
            interval = int(m.group(2))
            self._total_samples = max(1, frames // interval)
            self.job.progress_total = self._total_samples
            self.job.progress_current = 0
            self.job.progress_label = "OCR 採樣"
            return
        if "initializing EasyOCR" in msg:
            self.job.progress_label = "啟動 OCR (GPU)"
            return
        if m := RE_SAMPLED.search(msg):
            self.job.progress_current = int(m.group(1))
            self.job.progress_label = "OCR 採樣"
            return
        if m := RE_SAMPLING_DONE.search(msg):
            self.job.progress_current = int(m.group(1))
            self.job.progress_label = "聚類分析中"
            return
        if "content-clustered" in msg or "dropped" in msg:
            self.job.progress_label = "聚類分析中"
            return
        if RE_SLIDE_OUT.search(msg):
            self.job.progress_label = "寫入 slide PNG"
            return
        if msg.startswith("PPTX"):
            self.job.progress_label = "生成 PPTX"
            return


def stream_download_video(url: str, out_dir: Path, job: Job, height_cap: int = 1080) -> Path:
    """yt-dlp download with live percentage piped into the job's progress fields."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = (
        f"bestvideo[height<={height_cap}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height_cap}]+bestaudio/best"
    )
    job.progress_label = "下載影片"
    job.progress_total = 100
    job.progress_current = 0

    proc = subprocess.Popen(
        [
            "yt-dlp", "-f", fmt, "--merge-output-format", "mp4",
            "-o", str(out_dir / "%(title).80s.%(ext)s"),
            "--print", "after_move:filepath",
            "--newline",
            url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    filepath: Optional[str] = None
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        if m := RE_YTDLP_PCT.search(line):
            job.progress_current = int(float(m.group(1)))
        elif line.startswith("/"):
            filepath = line
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed (exit {proc.returncode})")
    if not filepath:
        raise RuntimeError("yt-dlp did not print filepath")
    return Path(filepath)


def resolve_with_progress(src: str, download_dir: Path, job: Job) -> Path:
    """Like slide_extractor.resolve_source, but pipes yt-dlp % into the job."""
    if is_url(src):
        return stream_download_video(src, download_dir, job)
    local = Path(src).expanduser()
    if not local.exists():
        raise FileNotFoundError(
            f"input not found: {src!r}\n"
            "  Pass either an existing local video file or a URL starting with http(s)://"
        )
    if not local.is_file():
        raise FileNotFoundError(f"input is not a file: {local}")
    return local


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
PERSIST_PATH: Optional[Path] = None  # set by main(); enables T-G05 persistence


def _log(job: Job, msg: str) -> None:
    job.log.append(msg)
    LOG.info("[job %s] %s", job.id[:8], msg)
    persist_jobs()


def _job_to_dict(j: Job) -> dict:
    return {
        "id": j.id, "source": j.source, "mode": j.mode,
        "output_dir": str(j.output_dir), "status": j.status,
        "log": list(j.log),
        "slides_dir": str(j.slides_dir) if j.slides_dir else None,
        "pptx_path": str(j.pptx_path) if j.pptx_path else None,
        "reviewed_pptx_path": str(j.reviewed_pptx_path) if j.reviewed_pptx_path else None,
        "slide_count": j.slide_count, "error": j.error,
        "created_at": j.created_at,
        "progress_current": j.progress_current,
        "progress_total": j.progress_total,
        "progress_label": j.progress_label,
    }


def _job_from_dict(d: dict) -> Job:
    # cancel_event is NOT persisted — each server start hands out fresh events.
    return Job(
        id=d["id"], source=d["source"], mode=d["mode"],
        output_dir=Path(d["output_dir"]), status=d["status"],
        log=list(d.get("log") or []),
        slides_dir=Path(d["slides_dir"]) if d.get("slides_dir") else None,
        pptx_path=Path(d["pptx_path"]) if d.get("pptx_path") else None,
        reviewed_pptx_path=Path(d["reviewed_pptx_path"]) if d.get("reviewed_pptx_path") else None,
        slide_count=d.get("slide_count", 0),
        error=d.get("error"),
        created_at=d.get("created_at", time.time()),
        progress_current=d.get("progress_current", 0),
        progress_total=d.get("progress_total", 0),
        progress_label=d.get("progress_label", ""),
    )


def persist_jobs() -> None:
    """Atomic write of JOBS to disk; no-op if PERSIST_PATH not configured."""
    if PERSIST_PATH is None:
        return
    try:
        with JOBS_LOCK:
            data = [_job_to_dict(j) for j in JOBS.values()]
        tmp = PERSIST_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        tmp.replace(PERSIST_PATH)
    except Exception as e:  # noqa: BLE001
        LOG.warning("persist_jobs failed: %s", e)


def _parse_multipart_upload(body: bytes, content_type: str) -> tuple[str, bytes, dict[str, str]]:
    """Extract first file (filename, data) and any form fields from multipart body.

    Returns (filename, file_bytes, form_fields_dict). Minimal parser tuned for
    one file + a handful of text fields — no streaming, no nested parts.
    """
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        raise ValueError("no boundary in Content-Type")
    boundary = b"--" + m.group(1).encode()
    fields: dict[str, str] = {}
    filename: Optional[str] = None
    file_data: bytes = b""
    for part in body.split(boundary):
        if not part or part in (b"--", b"--\r\n"):
            continue
        header_end = part.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        headers_blob = part[:header_end].lstrip(b"\r\n").decode("utf-8", "replace")
        data = part[header_end + 4:]
        if data.endswith(b"\r\n"):
            data = data[:-2]
        # parse Content-Disposition: form-data; name="…"; filename="…"
        name_match = re.search(r'name="([^"]+)"', headers_blob)
        if not name_match:
            continue
        field_name = name_match.group(1)
        file_match = re.search(r'filename="([^"]*)"', headers_blob)
        if file_match and file_match.group(1):
            filename = file_match.group(1)
            file_data = data
        else:
            try:
                fields[field_name] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
    if not filename:
        raise ValueError("no file part in upload")
    return filename, file_data, fields


def purge_job(job: Job, *, also_uploaded: bool = True) -> dict[str, list[str]]:
    """Remove a job's outputs from disk + drop it from JOBS dict.

    Always preserves OCR cache (`_ocr_cache_*.json`) and downloaded videos
    (`_video/`) so re-processing the same source is still fast. If the source
    was an upload (`_uploads/`), it's deleted by default — that data came from
    the user just for this job, so deleting the job implies deleting it.

    Returns {"removed": [...paths...], "kept": [...paths...]}.
    """
    removed: list[str] = []
    kept: list[str] = []

    def _rm_dir(p: Optional[Path]) -> None:
        if p and p.exists() and p.is_dir():
            shutil.rmtree(p)
            removed.append(str(p))

    def _rm_file(p: Optional[Path]) -> None:
        if p and p.exists() and p.is_file():
            p.unlink()
            removed.append(str(p))

    _rm_dir(job.slides_dir)
    _rm_file(job.pptx_path)
    _rm_file(job.reviewed_pptx_path)
    _rm_file(job.output_dir / f"_sheet_{job.id}.html")

    # Source file: only delete if it lives under _uploads/ for this job
    try:
        src = Path(job.source)
        if also_uploaded and src.is_file() and "_uploads" in src.parts:
            src.unlink()
            removed.append(str(src))
        elif src.exists():
            kept.append(str(src))
    except (OSError, ValueError):
        pass

    # OCR cache is intentionally preserved.
    if job.slides_dir is not None:
        title = job.slides_dir.name
        cache = job.output_dir / f"_ocr_cache_{title}.json"
        if cache.exists():
            kept.append(str(cache))

    with JOBS_LOCK:
        JOBS.pop(job.id, None)
    persist_jobs()
    return {"removed": removed, "kept": kept}


def load_jobs(output_dir: Path) -> int:
    """Read _jobs.json into JOBS; flip in-flight jobs to 'interrupted'. Returns count."""
    global PERSIST_PATH
    PERSIST_PATH = output_dir / "_jobs.json"
    if not PERSIST_PATH.exists():
        return 0
    try:
        records = json.loads(PERSIST_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        LOG.warning("could not load %s: %s", PERSIST_PATH, e)
        return 0
    n = 0
    with JOBS_LOCK:
        for d in records:
            job = _job_from_dict(d)
            if job.status in ("queued", "resolving", "extracting"):
                job.status = "interrupted"
                job.error = "server restart — re-submit to retry"
            JOBS[job.id] = job
            n += 1
    return n


def run_job(job: Job) -> None:
    """Worker: download (if URL) → extract → contact sheet → auto PPTX."""
    handler = JobProgressHandler(job)
    LOG.addHandler(handler)
    try:
        job.status = "resolving"
        _log(job, f"resolving: {job.source}")
        video_path = resolve_with_progress(job.source, job.output_dir / "_video", job)
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
        # Reset progress for the new phase; handler will populate from log lines
        job.progress_total = 0
        job.progress_current = 0
        job.progress_label = "準備擷取"
        _log(job, f"extracting (mode={job.mode}, sample={cfg.sample_sec}s)")
        paths = extract_slides(
            video_path, job.slides_dir, cfg,
            should_cancel=job.cancel_event.is_set,
        )
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

        job.progress_label = "完成"
        job.progress_current = job.progress_total or 1
        job.status = "done"
        persist_jobs()  # final snapshot — _log won't fire after this point
    except CancelledError:
        job.status = "cancelled"
        job.progress_label = "已取消"
        _log(job, "cancelled by user")
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)
        _log(job, f"ERROR: {e}")
    finally:
        LOG.removeHandler(handler)


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
  .job-card {{
    background: var(--card); border: 1px solid #2a2a30; border-radius: 10px;
    padding: 14px 16px; text-decoration: none; color: inherit;
    display: block; transition: border-color .15s ease;
  }}
  .job-card:hover {{ border-color: var(--accent); }}
  .job-card .top {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
  .job-card .src {{
    flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; font-size: 13px; color: #cbd5e1;
  }}
  .job-card .pill-sm {{
    flex-shrink: 0; padding: 3px 9px; border-radius: 999px;
    background: #0a0a0e; font-size: 11px; color: var(--muted);
  }}
  .job-card .pill-sm.done {{ background: var(--accent); color: #000; }}
  .job-card .pill-sm.error {{ background: var(--danger); color: #000; }}
  .job-card .pill-sm.running {{ background: #2563eb; color: #fff; }}
  .job-card .bar-mini-outer {{
    margin-top: 8px; background: #0a0a0e; border-radius: 999px;
    height: 4px; overflow: hidden;
  }}
  .job-card .bar-mini {{
    background: var(--accent); height: 100%; width: 0%;
    transition: width 300ms ease; border-radius: 999px;
  }}
  .job-card .meta {{
    margin-top: 6px; font-size: 11px; color: var(--muted);
    display: flex; gap: 10px; flex-wrap: wrap;
  }}
  .job-card .trash {{
    flex-shrink: 0; background: transparent; border: 1px solid #333;
    color: var(--muted); padding: 4px 10px; border-radius: 6px;
    cursor: pointer; font-size: 12px; line-height: 1;
  }}
  .job-card .trash:hover {{ border-color: var(--danger); color: var(--danger); }}
</style>
</head><body>
<header>
  <h1>Slide Extractor</h1>
  <p class="hint">YouTube 連結 或 本機影片路徑都可以。最終輸出：PNG + PPTX。</p>
</header>
<main>
  <form id="start" onsubmit="return submitForm(event)">
    <label class="field">
      <span>Source — 貼 YouTube URL 或本機檔案絕對路徑</span>
      <input type="text" id="source"
        placeholder="https://www.youtube.com/watch?v=…   或   /home/you/lecture.mp4" />
    </label>

    <div id="drop-zone" style="
      border: 2px dashed #333; border-radius: 10px;
      padding: 24px; text-align: center; cursor: pointer;
      background: rgba(255,255,255,0.02); color: var(--muted);
      transition: border-color .15s, background .15s; font-size: 13px;
    ">
      <strong style="display:block;color:var(--text);margin-bottom:4px;">或 — 把影片檔拖到這裡</strong>
      <span>（也可以點這裡選檔，影片只會傳到本機 server，不會上雲）</span>
      <input type="file" id="file-input" accept="video/*" style="display:none" />
    </div>

    <div class="modes">
      <label>
        <input type="radio" name="mode" value="auto" checked />
        <strong>Auto</strong>
        <small>最快，演算法直接出 PPTX（約 95% 準確）</small>
      </label>
      <label>
        <input type="radio" name="mode" value="review" />
        <strong>Review</strong>
        <small>過收所有候選，你目視勾完再生成 PPTX</small>
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

  <section id="jobs-section" style="margin-top: 32px; display: none;">
    <h2 style="font-size: 16px; margin: 0 0 12px;">📋 你的工作列表</h2>
    <p class="hint" style="margin-top:-4px;">最近抓過的影片；點任何一張卡片回到該 job 的進度頁。本頁自動更新。</p>
    <div id="jobs-list" style="display: flex; flex-direction: column; gap: 10px; margin-top: 12px;"></div>
  </section>
</main>
<footer>
  Slide Extractor · 個人學習工具 · 請尊重原作者著作權
</footer>
<script>
async function submitForm(e) {{
  e.preventDefault();
  const source = document.getElementById('source').value.trim();
  const mode = document.querySelector('input[name=mode]:checked').value;
  if (!source) {{
    alert('請貼 URL/路徑，或把檔案拖到下面的方框（或點方框選檔）');
    return;
  }}
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

async function uploadFile(file) {{
  const mode = document.querySelector('input[name=mode]:checked').value;
  const dz = document.getElementById('drop-zone');
  const sizeMB = (file.size / 1024 / 1024).toFixed(1);
  dz.innerHTML = `<strong style="color:var(--text)">上傳中…</strong><br><span>${{file.name}} (${{sizeMB}} MB)</span>`;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('mode', mode);
  const r = await fetch('/api/start', {{ method: 'POST', body: fd }});
  const data = await r.json();
  if (!data.ok) {{
    alert('上傳失敗：' + data.error);
    location.reload();
    return;
  }}
  location.href = '/job/' + data.job_id;
}}

(function setupDropZone() {{
  const dz = document.getElementById('drop-zone');
  const fi = document.getElementById('file-input');
  dz.addEventListener('click', () => fi.click());
  fi.addEventListener('change', () => {{
    if (fi.files.length > 0) uploadFile(fi.files[0]);
  }});
  ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => {{
    e.preventDefault(); e.stopPropagation();
    dz.style.borderColor = 'var(--accent)';
    dz.style.background = 'rgba(74,222,128,0.08)';
  }}));
  ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => {{
    e.preventDefault(); e.stopPropagation();
    dz.style.borderColor = '#333';
    dz.style.background = 'rgba(255,255,255,0.02)';
  }}));
  dz.addEventListener('drop', e => {{
    if (e.dataTransfer.files.length > 0) uploadFile(e.dataTransfer.files[0]);
  }});
}})();

const STATUS_LABEL = {{
  queued: "排隊中", resolving: "下載中",
  extracting: "分析中", done: "完成", error: "失敗",
  interrupted: "中斷", cancelled: "已取消"
}};
function timeAgo(ts) {{
  const sec = Math.floor(Date.now()/1000 - ts);
  if (sec < 60) return sec + ' 秒前';
  if (sec < 3600) return Math.floor(sec/60) + ' 分鐘前';
  if (sec < 86400) return Math.floor(sec/3600) + ' 小時前';
  return Math.floor(sec/86400) + ' 天前';
}}
function shortenSource(s) {{
  if (s.startsWith('http')) {{
    try {{ const u = new URL(s); return u.hostname + u.pathname + u.search; }}
    catch (e) {{ return s; }}
  }}
  // local path → last segment
  const parts = s.split('/');
  return parts[parts.length - 1] || s;
}}
function statusClass(status) {{
  if (status === 'done') return 'done';
  if (status === 'error' || status === 'interrupted' || status === 'cancelled') return 'error';
  if (status === 'queued') return '';
  return 'running';
}}
async function renderJobs() {{
  let r;
  try {{ r = await fetch('/api/jobs'); }} catch (e) {{ return; }}
  const data = await r.json();
  const list = data.jobs || [];
  const sec = document.getElementById('jobs-section');
  const container = document.getElementById('jobs-list');
  if (!list.length) {{ sec.style.display = 'none'; return; }}
  sec.style.display = 'block';
  const TERMINAL = ['done','error','cancelled','interrupted'];
  container.innerHTML = list.map(j => {{
    const pct = j.progress_total > 0
      ? Math.min(100, Math.round(100 * j.progress_current / j.progress_total))
      : (j.status === 'done' ? 100 : 0);
    const meta = j.status === 'done' && j.slide_count > 0
      ? `🖼 ${{j.slide_count}} 張 · ${{timeAgo(j.created_at)}}`
      : (j.error ? '❌ ' + j.error : `${{j.progress_label || ''}} · ${{timeAgo(j.created_at)}}`);
    const canDelete = TERMINAL.includes(j.status);
    const trashBtn = canDelete
      ? `<button class="trash" onclick="event.preventDefault(); event.stopPropagation(); deleteJob('${{j.id}}', '${{shortenSource(j.source).replace(/'/g, "\\\\'")}}')" title="刪除這個 job（保留 OCR cache）">🗑</button>`
      : '';
    return `
      <a class="job-card" href="/job/${{j.id}}">
        <div class="top">
          <span class="src" title="${{j.source.replace(/"/g,'&quot;')}}">${{shortenSource(j.source)}}</span>
          <span class="pill-sm ${{statusClass(j.status)}}">${{STATUS_LABEL[j.status] || j.status}} ${{j.status !== 'queued' && j.status !== 'done' && j.status !== 'error' ? pct + '%' : ''}}</span>
          ${{trashBtn}}
        </div>
        <div class="bar-mini-outer"><div class="bar-mini" style="width:${{pct}}%;"></div></div>
        <div class="meta">${{meta}}</div>
      </a>
    `;
  }}).join('');
}}
async function deleteJob(id, label) {{
  if (!confirm(`確定刪除「${{label}}」？\\n\\n會刪除：投影片 PNG + PPTX + 審核 sheet\\n保留：OCR cache（重跑很快）+ 下載/上傳的原始影片`)) return;
  const r = await fetch('/api/job/' + id + '/delete', {{ method: 'POST' }});
  const data = await r.json();
  if (!data.ok) {{ alert('刪除失敗：' + data.error); return; }}
  renderJobs();
}}
renderJobs();
setInterval(renderJobs, 2000);
</script>
</body></html>"""


STATUS_LABEL = {
    "queued": "排隊中",
    "resolving": "下載影片中",
    "extracting": "分析投影片中",
    "done": "完成",
    "error": "失敗",
    "interrupted": "中斷（server 重啟）",
    "cancelled": "已取消",
}


def progress_html(job_id: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head>
<meta charset="utf-8">
<title>Job {job_id[:8]} — Slide Extractor</title>
<style>{THEME_CSS}
  .stage {{
    background: var(--card); border-radius: 10px; padding: 18px 20px;
    margin-bottom: 16px;
  }}
  .stage-row {{ display: flex; align-items: center; gap: 12px; }}
  .stage h2 {{ margin: 0; font-size: 16px; font-weight: 600; flex: 1; }}
  .stage .eta {{ font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .bar-outer {{
    margin-top: 12px; background: #0a0a0e; border-radius: 999px;
    height: 10px; overflow: hidden; position: relative;
  }}
  .bar-inner {{
    background: linear-gradient(90deg, #22c55e, #4ade80);
    height: 100%; width: 0%; transition: width 400ms ease;
    border-radius: 999px;
  }}
  .bar-indeterminate {{
    background: linear-gradient(90deg, transparent 0%, #4ade80 50%, transparent 100%);
    background-size: 50% 100%; animation: stripe 1.4s linear infinite;
    width: 100%;
  }}
  @keyframes stripe {{ from {{ background-position: -50% 0; }} to {{ background-position: 150% 0; }} }}
  .stage-label {{ margin-top: 8px; font-size: 13px; color: #cbd5e1; }}
  .stage-label .pct {{ color: var(--accent); font-weight: 600; }}
  details.tech {{ margin-top: 10px; font-size: 12px; color: var(--muted); }}
  details.tech summary {{ cursor: pointer; }}
  details.tech pre {{
    margin-top: 8px; background: #000; padding: 12px; border-radius: 6px;
    font-size: 11px; max-height: 240px; overflow-y: auto;
    white-space: pre-wrap; word-break: break-all; color: #6b7280;
  }}
</style>
</head><body>
<header>
  <h1>進度 <span id="pill" class="status-pill">排隊中</span></h1>
  <p class="hint">Job <code>{job_id[:8]}</code> · 頁面自動更新，沒有東西要按。完成後會出現「下載 PPTX」「看候選」按鈕。</p>
</header>
<main>
  <div class="stage">
    <div class="stage-row">
      <h2 id="phase">準備中…</h2>
      <span class="eta" id="eta">—</span>
    </div>
    <div class="bar-outer"><div class="bar-inner" id="bar"></div></div>
    <div class="stage-label"><span id="phase_detail">啟動中</span> <span class="pct" id="pct"></span></div>
  </div>

  <div id="actions" style="display:flex; gap:12px; flex-wrap:wrap;"></div>
  <div id="cancel-row" style="margin-top:12px;">
    <button id="cancel-btn" class="ghost" onclick="cancelJob()" style="display:none;">取消這個 job</button>
  </div>

  <details class="tech">
    <summary>顯示技術細節 / log（給工程師看的）</summary>
    <pre id="log">等待…</pre>
  </details>

  <p style="margin-top:24px"><a href="/" style="color: var(--muted)">← 回主頁</a></p>
</main>
<script>
const jobId = "{job_id}";
const pill = document.getElementById('pill');
const logEl = document.getElementById('log');
const actions = document.getElementById('actions');
const bar = document.getElementById('bar');
const phase = document.getElementById('phase');
const phaseDetail = document.getElementById('phase_detail');
const pct = document.getElementById('pct');
const etaEl = document.getElementById('eta');
const STATUS = {{
  queued: "排隊中", resolving: "下載影片中",
  extracting: "分析投影片中", done: "完成", error: "失敗"
}};
const PHASE = {{
  queued: "排隊", resolving: "下載影片",
  extracting: "分析投影片", done: "全部完成 ✓", error: "失敗 ✗"
}};
let lastPct = -1, lastTime = Date.now();

async function poll() {{
  let r;
  try {{ r = await fetch('/api/job/' + jobId); }}
  catch (e) {{ setTimeout(poll, 2000); return; }}
  const j = await r.json();
  pill.textContent = STATUS[j.status] || j.status;
  pill.className = 'status-pill ' + (j.status === 'done' ? 'done' : j.status === 'error' ? 'error' : '');
  phase.textContent = PHASE[j.status] || j.status;
  phaseDetail.textContent = j.progress_label || '處理中';
  logEl.textContent = j.log.join('\\n');
  logEl.scrollTop = logEl.scrollHeight;

  if (j.progress_total > 0) {{
    const p = Math.min(100, Math.round(100 * j.progress_current / j.progress_total));
    bar.style.width = p + '%';
    bar.className = 'bar-inner';
    pct.textContent = `· ${{j.progress_current}}/${{j.progress_total}} (${{p}}%)`;
    // crude ETA: extrapolate from rate since last poll
    const now = Date.now();
    if (lastPct >= 0 && p > lastPct) {{
      const ratePerMs = (p - lastPct) / (now - lastTime);
      if (ratePerMs > 0) {{
        const remainMs = (100 - p) / ratePerMs;
        const remainSec = Math.round(remainMs / 1000);
        etaEl.textContent = remainSec > 60
          ? `預估剩 ${{Math.round(remainSec/60)}} 分鐘`
          : `預估剩 ${{remainSec}} 秒`;
      }}
    }}
    lastPct = p; lastTime = now;
  }} else {{
    // indeterminate phase
    bar.className = 'bar-inner bar-indeterminate';
    bar.style.width = '100%';
    pct.textContent = '';
    etaEl.textContent = '';
  }}

  // Cancel button visibility — only while truly in-flight
  const cancelBtn = document.getElementById('cancel-btn');
  cancelBtn.style.display =
    (j.status === 'queued' || j.status === 'resolving' || j.status === 'extracting')
    ? 'inline-block' : 'none';

  if (j.status === 'done') {{
    bar.style.width = '100%';
    bar.className = 'bar-inner';
    etaEl.textContent = '';
    renderActions(j);
    return;
  }}
  if (j.status === 'error' || j.status === 'cancelled' || j.status === 'interrupted') {{
    etaEl.textContent = '';
    return;
  }}
  setTimeout(poll, 1500);
}}
async function cancelJob() {{
  if (!confirm('確定要取消這個 job？已經 OCR 的內容會保留在 cache。')) return;
  const btn = document.getElementById('cancel-btn');
  btn.disabled = true; btn.textContent = '取消中…';
  await fetch('/api/job/' + jobId + '/cancel', {{ method: 'POST' }});
  // poll will update UI; button hides itself when status flips
}}
function renderActions(j) {{
  const parts = [];
  if (j.slide_count > 0) {{
    parts.push(`<a class="button-link" href="/job/${{jobId}}/sheet"><button>👀 看 ${{j.slide_count}} 張候選 / 勾選後產 PPTX</button></a>`);
    parts.push(`<a class="button-link" href="/job/${{jobId}}/pptx" download><button class="ghost">⬇ 直接下載 Auto PPTX</button></a>`);
  }} else {{
    parts.push(`<span style="color: var(--muted)">沒抓到 slide — 試試 Review 模式，或確認影片是「投影片型」的講演</span>`);
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
            if path == "/api/jobs":
                with JOBS_LOCK:
                    summaries = [
                        {
                            "id": j.id,
                            "source": j.source,
                            "mode": j.mode,
                            "status": j.status,
                            "slide_count": j.slide_count,
                            "progress_current": j.progress_current,
                            "progress_total": j.progress_total,
                            "progress_label": j.progress_label,
                            "created_at": j.created_at,
                            "error": j.error,
                        }
                        for j in JOBS.values()
                    ]
                summaries.sort(key=lambda x: x["created_at"], reverse=True)
                self._send_json(200, {"ok": True, "jobs": summaries})
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
                    "progress_current": job.progress_current,
                    "progress_total": job.progress_total,
                    "progress_label": job.progress_label,
                })
                return
            self.send_error(404)

        # ── POST ──
        def do_POST(self):  # noqa: N802
            path = unquote(self.path.split("?", 1)[0])
            if path == "/api/start":
                try:
                    content_type = self.headers.get("Content-Type", "")
                    body = self._read_body()
                    if content_type.startswith("multipart/form-data"):
                        try:
                            filename, file_bytes, form = _parse_multipart_upload(
                                body, content_type
                            )
                        except ValueError as e:
                            self._send_json(400, {"ok": False, "error": str(e)})
                            return
                        uploads_dir = output_dir / "_uploads"
                        uploads_dir.mkdir(parents=True, exist_ok=True)
                        # Sanitize filename — keep extension, prefix with uuid to avoid clash
                        safe_name = Path(filename).name or "upload.mp4"
                        upload_path = uploads_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
                        upload_path.write_bytes(file_bytes)
                        source = str(upload_path)
                        mode = form.get("mode", "auto")
                    else:
                        data = json.loads(body or b"{}")
                        source = (data.get("source") or "").strip()
                        mode = data.get("mode", "auto")
                    if not source:
                        self._send_json(400, {"ok": False, "error": "source required"})
                        return
                    if mode not in ("auto", "review"):
                        self._send_json(400, {"ok": False, "error": "mode must be auto|review"})
                        return
                    job = Job(id=uuid.uuid4().hex, source=source, mode=mode, output_dir=output_dir)
                    with JOBS_LOCK:
                        JOBS[job.id] = job
                    persist_jobs()
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
            if path.startswith("/api/job/") and path.endswith("/cancel"):
                jid = path[len("/api/job/"):-len("/cancel")]
                job = self._get_job(jid)
                if not job:
                    self._send_json(404, {"ok": False, "error": "no such job"})
                    return
                if job.status in ("done", "error", "cancelled", "interrupted"):
                    self._send_json(409, {"ok": False, "error": f"job already {job.status}"})
                    return
                job.cancel_event.set()
                self._send_json(200, {"ok": True, "status": "cancelling"})
                return
            if path.startswith("/api/job/") and path.endswith("/delete"):
                jid = path[len("/api/job/"):-len("/delete")]
                job = self._get_job(jid)
                if not job:
                    self._send_json(404, {"ok": False, "error": "no such job"})
                    return
                if job.status not in ("done", "error", "cancelled", "interrupted"):
                    self._send_json(409, {
                        "ok": False,
                        "error": f"cancel first — job is {job.status}",
                    })
                    return
                result = purge_job(job)
                self._send_json(200, {"ok": True, **result})
                return
            self.send_error(404)

        def do_DELETE(self):  # noqa: N802 — alias for /cancel
            path = unquote(self.path.split("?", 1)[0])
            if path.startswith("/api/job/"):
                jid = path[len("/api/job/"):]
                job = self._get_job(jid)
                if not job:
                    self._send_json(404, {"ok": False, "error": "no such job"})
                    return
                if job.status in ("done", "error", "cancelled", "interrupted"):
                    self._send_json(409, {"ok": False, "error": f"job already {job.status}"})
                    return
                job.cancel_event.set()
                self._send_json(200, {"ok": True, "status": "cancelling"})
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
    # Inject a sticky top navbar with back links + style tweak so it doesn't
    # overlap the existing sticky header in the sheet template.
    nav = f"""<nav style="
        position: sticky; top: 0; z-index: 20;
        background: #0a0a0e; border-bottom: 1px solid #2a2a30;
        padding: 10px 24px; display: flex; gap: 16px; align-items: center;
        font-size: 13px;
    ">
      <a href="/job/{job_id}" style="
        color: #4ade80; text-decoration: none;
        padding: 5px 10px; border: 1px solid #4ade80; border-radius: 6px;
      ">← 回到此 job 進度頁</a>
      <a href="/" style="color: #888; text-decoration: none;">← 回到首頁 / 工作列表</a>
      <span style="margin-left: auto; color: #555; font-size: 11px;">
        Job <code style="color: #888;">{job_id[:8]}</code>
      </span>
    </nav>"""
    # Make the sheet's own sticky header not stick to top:0 so our nav sits above it.
    html_str = html_str.replace(
        "header {\n    position: sticky; top: 0;",
        "header {\n    position: sticky; top: 44px;",
    )
    html_str = html_str.replace("<body>", "<body>" + nav, 1)
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
    restored = load_jobs(args.output)
    if restored:
        LOG.info("restored %d jobs from %s", restored, PERSIST_PATH)

    handler = make_handler_v2(args.output)
    with ReusableTCPServer((args.bind, args.port), handler) as srv:
        _print_startup_banner(args.bind, args.port)
        srv.serve_forever()
    return 0


def _detect_lan_ips() -> list[str]:
    """Best-effort: return non-loopback IPv4 addresses we're bound to."""
    import socket as _s
    ips: list[str] = []
    try:
        hostname = _s.gethostname()
        for info in _s.getaddrinfo(hostname, None, _s.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    # Fallback: ask the kernel which address it would use for outbound traffic.
    try:
        sock = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        if ip and ip not in ips:
            ips.append(ip)
        sock.close()
    except OSError:
        pass
    return ips


def _print_startup_banner(bind: str, port: int) -> None:
    """Tell users exactly where to point their browser."""
    print("\n" + "═" * 56)
    print("  Slide Extractor — Web GUI")
    print("═" * 56)
    print(f"\n  ▸ Open this URL in your browser on THIS computer:")
    print(f"      http://localhost:{port}/")
    if bind in ("0.0.0.0", "::"):
        lan_ips = _detect_lan_ips()
        if lan_ips:
            print(f"\n  ▸ From another device on the same network:")
            for ip in lan_ips:
                print(f"      http://{ip}:{port}/")
        print(f"\n  (Listening on all interfaces. To restrict to this")
        print(f"   computer only: re-run with --bind 127.0.0.1)")
    else:
        print(f"\n  (Listening on {bind} only)")
    print(f"\n  Press Ctrl+C in this terminal to stop the server.")
    print("═" * 56 + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
