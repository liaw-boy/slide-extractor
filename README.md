# slide-extractor

> Extract slides from lecture videos into PNG snapshots and an aspect-preserving PPTX deck. Auto mode is ~95% accurate; an optional browser review UI lets you visually confirm and reach full completeness.
> 從演講影片擷取投影片，輸出 PNG + PPTX。自動模式約 95% 準確；可選的瀏覽器審核 UI 讓你目視確認、達到完整覆蓋。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Personal Use Only](https://img.shields.io/badge/use-personal%20study%20only-orange.svg)](#-copyright--著作權)

> [!IMPORTANT]
> **Personal-study tool only. You must own legitimate access to the source video and comply with the original copyright and the source platform's Terms of Service.** See [Copyright / 著作權](#-copyright--著作權) and [NOTICE](NOTICE).
>
> **僅供個人學習用途。使用者必須擁有影片的合法存取權，並遵守原內容著作權與平台服務條款。**

---

## ⚡ Quick start

```bash
git clone https://github.com/liaw-boy/slide-extractor.git
cd slide-extractor
./install.sh
python3 slide_web.py
```

Then open **`http://localhost:8903/`** in your browser (or `http://<your-host>:8903/` over Tailscale / LAN).

That's the whole flow:

1. Paste a **YouTube URL** or a **local video path** into the form.
2. Pick **Auto** (fastest) or **Review** (over-extracts so you can prune visually).
3. Watch the live progress bar + ETA.
4. Click **下載 PPTX** when it finishes, or **看候選** to prune in the contact sheet.

The home page also shows a live **job dashboard** so you can submit multiple videos in parallel and jump between them.

### Output layout

```
~/slides_output/
├── <video-title>/
│   ├── slide_001_00h02m17s.png
│   └── ...
├── <video-title>.pptx                    # auto mode output
└── <video-title>_REVIEWED.pptx           # review-mode output
```

---

## 🖥 Web GUI walkthrough

### Step 1 — Start the server

```bash
python3 slide_web.py
```

You'll see:
```
▶ Slide Extractor Web GUI: http://<your-host>:8903/
  Local:     http://localhost:8903/
  Ctrl+C 結束。
```

Keep this terminal running. Stop with `Ctrl+C` when done. The server is local-only by default but binds to `0.0.0.0`, so anyone on your LAN / Tailscale who can reach the host IP can use it. To restrict to your own machine: `python3 slide_web.py --bind 127.0.0.1`.

### Step 2 — Open the page

Open one of:
- **Same machine**: `http://localhost:8903/`
- **Another device on LAN**: `http://<host-IP>:8903/`
- **Tailscale**: `http://<tailscale-IP>:8903/`

You'll see the submission form, the **Scope** card, the **Copyright** notice, and (after you've run anything) a **📋 你的工作列表 (Job dashboard)** that lists every recent job with its status + a mini progress bar.

### Step 3 — Submit a video

Paste **either** a YouTube URL **or** an absolute local file path:

```
https://www.youtube.com/watch?v=…
/home/you/lectures/week3.mp4
```

Pick a mode:
- **Auto** — fastest. Algorithm picks slides; you get the PPTX directly.
- **Review** — over-extracts. You'll prune duplicates on a contact sheet before the final PPTX.

Click **開始抓 slide**. The page redirects to a progress view.

### Step 4 — Watch the progress

Three things on the progress page:
- Big progress bar with **phase label** (`下載影片 → OCR 採樣 → 聚類分析中 → 生成 PPTX`).
- **ETA** estimated from the polling rate ("預估剩 4 分鐘").
- A collapsed `<details>` block with raw technical log (for debugging).

You can leave the tab open OR navigate away — the job keeps running on the server. Come back via the **Job dashboard** on the home page; click any card to return to that job.

### Step 5 — Download or review

When status flips to **完成 ✓**, two buttons appear:

- **⬇ 直接下載 Auto PPTX** — grab the algorithm's best guess immediately.
- **👀 看 N 張候選** — open the dark contact sheet to visually confirm.

In the contact sheet:
1. Glance through the thumbnails (sorted by time).
2. Uncheck any duplicates / partial-animation versions.
3. Click **儲存選擇 → 生成 PPTX** at the bottom.
4. Browser downloads `<video-title>_REVIEWED.pptx`.

The top nav bar lets you jump back to the progress page or the home dashboard at any time.

### Job persistence

Jobs survive `Ctrl+C` and restart. The server writes `_jobs.json` to your output directory; on next start it reloads completed jobs (so they re-appear on the dashboard with download buttons intact). Jobs that were mid-extraction at the time of restart show as **中斷 (interrupted)** — re-submit the URL to retry.

---

## ✅ Scope / 適用範圍

**Designed for** screen recordings of typed slide decks — lecture videos, conference talks, tutorial walk-throughs, online courses. Default OCR languages are Traditional Chinese + English.

| Verdict | Cases |
|---------|-------|
| ✅ **Works well** | PowerPoint / Keynote / Google Slides screen recordings · slide-driven lectures · conference talks with screen capture · 中文/English content |
| 🟡 **Borderline (use review mode)** | Slides with small speaker-camera overlay · slides containing embedded short video clips · code-heavy slides with sparse text (lower `--min-text-len`) · non-CJK/English languages (use `--lang`) |
| ❌ **Not designed for** | Whiteboard / handwriting videos (no OCR signal) · software demo screencasts (no slide structure) · pure talking-head with no slides · Prezi-style smooth-zoom transitions · videos shorter than ~30 s |

If your video is in the "❌" column, the right tool is `ffmpeg` keyframe extraction or manual screenshotting — not this.

---

## ⚠ Copyright / 著作權
<a name="-copyright--著作權"></a>

This tool is intended **strictly for personal study and research**. By using it you confirm that you have legitimate access to the source video and that your downstream use complies with the original content's copyright terms and the hosting platform's Terms of Service.

**Do not use this tool to:**
- Reproduce or redistribute copyrighted content you do not own or license
- Build commercial / for-profit derivative products
- Circumvent platform restrictions in violation of their ToS

The tool runs **entirely on your local machine** and uploads nothing to external servers. Responsibility for downstream use of the extracted slides rests with the user.

---

## 🎯 Pick the right mode

| Need | Mode | What you do | Realistic accuracy |
|------|------|-------------|--------------------|
| Quick draft, OK with ~5% noise | **Auto** | Submit → wait → download PPTX | ~95% (algorithm alone) |
| Final output, want to verify | **Review** | Submit → wait → eyeball contact sheet → uncheck duplicates → download | as good as your eyes — no algorithm threshold can promise 100% by itself |

Review mode runs in PARANOID settings (denser sampling, lower thresholds) so it always outputs MORE candidates than real slides. You glance through, uncheck the duplicates, click save. Time spent reviewing depends on lecture length — typically tens of seconds for a 30-minute lecture, longer for slide-heavy material.

---

## 🧠 Why this beats other approaches

Naive video → slides tools fail on lecture videos because:

| Approach | Fails when… |
|----------|-------------|
| HSV histogram (PySceneDetect default) | All slides share a template — histogram barely shifts |
| pHash alone | Same template fools the visual hash |
| SSIM alone | Same problem |
| OCR Jaccard | Slides on related topics share vocabulary |

slide-extractor's two-tier strategy:

1. **Online content clustering** — every sampled frame is OCR'd and clustered by token Jaccard. Any frame whose content does not overlap enough with prior slides *necessarily* opens a new slide. **Structurally cannot miss slides** the algorithm has seen.
2. **Human review UI** — for the residual 5% (OCR misreads, animation/transition ambiguity), a contact-sheet HTML lets you visually confirm and prune duplicates.

Full algorithm derivation with empirical tuning data: [docs/algorithm.md](docs/algorithm.md).

---

## 🧑‍💻 Advanced: CLI usage

The web GUI (`slide_web.py`) is the recommended entry point. The CLI scripts below are useful for scripting / batch jobs / debugging.

### `slide_extractor.py` — auto extraction

| Flag | Default | Description |
|------|---------|-------------|
| `source` | — | Local video path or YouTube URL (required) |
| `-o`, `--output` | `~/slides_output` | Output base directory |
| `--sample-sec` | `3.0` | Sampling interval in seconds (lower = denser) |
| `--phash-thr` | `6` | pHash distance threshold (legacy gate) |
| `--min-duration` | `9` | Discard slides shown < this many seconds |
| `--cluster-jaccard` | `0.45` | Lower = more clusters (more sensitive) |
| `--cpu` | off | Force CPU-only OCR (default: GPU if available) |
| `--lang LANG` | `ch_tra en` | EasyOCR language; repeat for multiple |
| `-v`, `-vv` | off | Increase log verbosity |

### `slide_review.py` — review-with-UI

Inherits all of the above plus:

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8901` | HTTP port for the review UI |
| `--bind` | `0.0.0.0` | Bind address (use `127.0.0.1` for local-only) |
| `--skip-extract` | off | Skip re-extraction (when iterating on review of an already-extracted dir) |

### `slide_web.py` flags (web GUI — already covered in Quick start above)

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `~/slides_output` | Output base directory |
| `--port` | `8903` | HTTP port |
| `--bind` | `0.0.0.0` | Bind address (use `127.0.0.1` for local-only) |

---

## 🔧 Troubleshooting

### "Missing slides" after auto mode

1. **First**: re-run with `slide_review.py` to over-extract and confirm visually.
2. **If still missing**: paranoid mode goes lower:
   ```bash
   python3 slide_extractor.py video.mp4 \
       --min-duration 3 --cluster-jaccard 0.30 --sample-sec 2
   ```
3. **Edge cases the algorithm cannot solve alone**:
   - Pure-image slides with little/no text → OCR has nothing to cluster on. Use review UI.
   - Slides shown < 3 seconds → may be filtered by `--min-duration`. Set to `1`.
   - Very-low-resolution video (< 480p) → text OCR accuracy drops sharply; consider upscaling the source.

### "Too many duplicate slides"

1. Raise `--cluster-jaccard` toward 0.6 to merge more aggressively, OR
2. Use review UI and uncheck the duplicates (preferred — guaranteed quality).

### "Slides look stretched / flat"

Fixed in commit `a28a9b4` — PPTX page now derives its aspect ratio from the first slide image. Re-pull the latest.

### "OCR too slow"

- Make sure GPU is being used: `nvidia-smi` should show python3 holding ~600MB.
- Without GPU, expect ~5s/frame on CPU. The OCR cache (`_ocr_cache_<title>.json`) makes re-runs instant.

### "Want to start fresh"

```bash
rm -rf ~/slides_output/<video-title>          # delete extracted PNGs
rm    ~/slides_output/_ocr_cache_<video-title>.json   # delete OCR cache
```

---

## 🧪 Validation

The algorithm is validated against three real lectures:

| Video | Length | Ground truth | Detected | Notes |
|-------|--------|--------------|----------|-------|
| OWASP Mobile M1 (Mandarin) | 55 min | 13 | **13** | All GT timestamps matched within ~10 s |
| Cryptography Module 2 (Mandarin) | 2 hr 4 min | (no manual GT) | 39 | 0 visual-duplicate flags |
| OWASP Mobile intro (Mandarin) | 30 min | (no manual GT) | 12 | Algorithm + manual cross-check |

---

## 📁 Repo layout

```
slide-extractor/
├── slide_extractor.py     # auto extraction (CLI: slide-extractor)
├── slide_review.py        # human-in-the-loop review UI
├── install.sh             # one-shot installer
├── requirements.txt       # pip deps
├── pyproject.toml         # modern Python packaging
├── docs/
│   └── algorithm.md       # algorithm derivation + tuning data
├── examples/
│   └── usage.md           # more CLI recipes
└── tests/
    └── test_extractor.py  # unit tests (10/10)
```

---

## 🛠️ Contributing

```bash
pip install black ruff pytest
black slide_extractor.py slide_review.py
ruff check .
pytest -v
```

---

## 📜 License

MIT — see [LICENSE](LICENSE).

Built with [EasyOCR](https://github.com/JaidedAI/EasyOCR),
[imagehash](https://github.com/JohannesBuchner/imagehash),
[python-pptx](https://github.com/scanny/python-pptx),
[yt-dlp](https://github.com/yt-dlp/yt-dlp).
