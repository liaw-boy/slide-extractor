# Implementation Plan: 001-extract-slides

**Status**: Already shipped — this document captures the as-built architecture.

## Architecture (3-tier)

```
┌─────────────────────────────────────────────────────────────────┐
│  Entry points (3, share core pipeline)                          │
├─────────────────────────────────────────────────────────────────┤
│  slide_extractor.py   CLI, batch-friendly                       │
│  slide_review.py      CLI + HTTP review UI (one video at a time)│
│  slide_web.py         Single-server web GUI (multi-job)         │
└─────────────────────────────────────────────────────────────────┘
              ↓ all import from
┌─────────────────────────────────────────────────────────────────┐
│  Core pipeline (slide_extractor.py)                             │
├─────────────────────────────────────────────────────────────────┤
│  resolve_source()          ── input dispatch (URL vs file)      │
│  download_video()          ── yt-dlp wrapper                    │
│  extract_slides()          ── orchestrator                      │
│     ↓ sample frames                                             │
│     ↓ EasyOCR (GPU)        ── disk-backed JSON cache            │
│     ↓ pHash                                                     │
│     ↓ online cluster (token bigram + jaccard)                   │
│     ↓ pick representative per cluster (most tokens)             │
│  export_pptx()             ── aspect-preserving                 │
└─────────────────────────────────────────────────────────────────┘
              ↓ shared by slide_review + slide_web
┌─────────────────────────────────────────────────────────────────┐
│  Review UI helpers (slide_review.py)                            │
├─────────────────────────────────────────────────────────────────┤
│  build_contact_sheet()     ── dark-theme HTML with checkboxes   │
│  export_filtered_pptx()    ── subset → PPTX                     │
└─────────────────────────────────────────────────────────────────┘
              ↓ only used by slide_web
┌─────────────────────────────────────────────────────────────────┐
│  Web GUI extras (slide_web.py)                                  │
├─────────────────────────────────────────────────────────────────┤
│  Job dataclass + JOBS dict (in-memory, thread-safe)             │
│  JobProgressHandler        ── logging.Handler → progress fields │
│  stream_download_video()   ── yt-dlp Popen + live %             │
│  ThreadingTCPServer        ── one thread per HTTP request       │
└─────────────────────────────────────────────────────────────────┘
```

## Algorithm derivation (why this beats simpler approaches)

| Approach we tried | Why it failed |
|---|---|
| HSV histogram (PySceneDetect default) | All slides share template → histogram barely shifts |
| pHash alone | Same template fools the visual hash |
| SSIM alone | Same problem |
| OCR Jaccard alone | Slides on related topics share vocabulary |
| pHash + classify_transition rules | Borderline on animation reveals → split/merge |
| **Online content clustering** (current) | Every frame joins best-matching cluster, opens new one if no match ≥ jaccard threshold. **Structurally cannot miss** any frame the algorithm has seen. |

Combined with disk-backed OCR cache so re-tuning takes seconds, not 10 minutes.

## Data flow per request (web GUI)

```
POST /api/start
  └→ create Job(uuid, source, mode, output_dir)
  └→ spawn thread → run_job(job)
       └→ JobProgressHandler attached to LOG
       └→ resolve_with_progress(source) — Popen yt-dlp, parse [download] %
       └→ extract_slides() — LOG records parsed into progress_current/total
       └→ export_filtered_pptx() → auto PPTX
       └→ build_contact_sheet() → _sheet_<id>.html
       └→ status = "done"

GET /api/job/<id>
  └→ return {status, log, slide_count, progress_*, has_pptx, has_reviewed}
GET /job/<id>
  └→ render progress_html with polling JS

POST /api/job/<id>/finalize
  └→ export_filtered_pptx(slides_dir, kept_list, reviewed_pptx_path)
  └→ return {ok, download: "/job/<id>/pptx_reviewed"}

GET /job/<id>/pptx_reviewed
  └→ _send_file with RFC 5987 Content-Disposition for non-ASCII names
```

## Constraints & non-functional

- **Latency**: Auto mode for 35-min video ≈ 7 min OCR + 5s cluster + 5s PPTX on RTX 2080 Ti.
- **Memory**: Each job keeps full Sample frames in RAM during pipeline. ~720 samples × ~50MB peak per pipeline run.
- **Disk**: OCR cache `_ocr_cache_<title>.json` ~500KB-2MB; slides PNGs 300-700KB each; PPTX 5-10MB.
- **Concurrency**: ThreadingTCPServer + per-job worker thread. EasyOCR initialization holds a global lock (one OCR instance at a time per Python process).
- **Network**: yt-dlp only. No telemetry, no cloud OCR, no analytics.

## Technology choices (and what was rejected)

| Concern | Chosen | Rejected | Why |
|---|---|---|---|
| OCR | EasyOCR (GPU) | Tesseract, PaddleOCR | EasyOCR ch_tra+en single-call, GPU 18x speedup |
| Visual hash | imagehash phash | dHash, aHash, SSIM | pHash 64-bit, robust to compression artifacts |
| HTTP server | stdlib http.server + threading | Flask, FastAPI | No new dep, < 100 lines for full routing |
| Job state | In-memory dict | SQLite, Redis | Single-user tool; restart = restart |
| Frontend | Vanilla HTML/JS | React, Vue | Single-file delivery, no build step |
| Packaging | Plain .py | PyInstaller, Docker | User runs `python3 slide_web.py`, zero ceremony |

## Testing strategy

Unit tests (`tests/test_extractor.py`, pytest, 14 tests, 2.4s):
- `text_to_tokens` — bigram boundary, punctuation, English casing
- `classify_transition` — 4 paths: visually stable, text shrink, hard-OCR, growth-subset, content change
- `is_url` / `resolve_source` — URL detection, missing-file error, existing-file passthrough

Integration tests: **NOT WRITTEN** (gap). Acceptance is currently visual via review UI.

E2E tests: **NOT WRITTEN** (gap). Smoke test driven manually with `curl` against running server.

## Deployment

```bash
git clone https://github.com/liaw-boy/slide-extractor.git
cd slide-extractor && ./install.sh
python3 slide_web.py  # serves on 0.0.0.0:8903
```

No container. No systemd unit. User starts and stops manually. Tailscale provides the only "remote" access.
