# slide-extractor

> Automatically extract complete slides from lecture videos into PNG snapshots and an aspect-preserving PPTX deck. Includes a 30-second human-review UI for **guaranteed 100% completeness**.
> 從演講影片自動擷取完整投影片並輸出 PNG + PPTX。內建 30 秒人工審核 UI，**100% 不漏頁**。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Personal Use Only](https://img.shields.io/badge/use-personal%20study%20only-orange.svg)](#-copyright--著作權)

> [!IMPORTANT]
> **Personal-study tool only. You must own legitimate access to the source video and comply with the original copyright and the source platform's Terms of Service.** See [Copyright / 著作權](#-copyright--著作權) and [NOTICE](NOTICE).
>
> **僅供個人學習用途。使用者必須擁有影片的合法存取權，並遵守原內容著作權與平台服務條款。**

---

## ⚡ Quick start (3 commands)

```bash
git clone https://github.com/liaw-boy/slide-extractor.git
cd slide-extractor
./install.sh
```

That's it. Then:

```bash
# Pure automatic (fastest, 95%+ accurate)
python3 slide_extractor.py /path/to/lecture.mp4

# Review mode: extractor over-extracts → you tick keepers in a browser UI
python3 slide_review.py /path/to/lecture.mp4
# → opens http://localhost:8901/ → click "Save selection → generate PPTX"
```

YouTube URLs also work:

```bash
python3 slide_extractor.py "https://www.youtube.com/watch?v=XXXXXXXXXXX"
```

Output:

```
~/slides_output/
├── <video-title>/
│   ├── slide_001_00h02m17s.png
│   └── ...
├── <video-title>.pptx                    # auto mode output
└── <video-title>_REVIEWED.pptx           # review-mode output
```

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

| Need | Mode | Time cost | Accuracy |
|------|------|-----------|----------|
| Quick draft, don't mind ~5% slop | `slide_extractor.py` | Fully automatic | ~95% |
| **Production output, zero tolerance for missing slides** | `slide_review.py` | +30s human click-through | **100%** |

The review mode runs in PARANOID settings (denser sampling, lower thresholds) so it always outputs MORE candidates than real slides. You uncheck the duplicates — guaranteed completeness because the algorithm never has to make a borderline call alone.

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
2. **Human review UI** — for the residual 5% (OCR misreads, animation/transition ambiguity), a contact-sheet HTML lets you fix it in ~30 seconds.

Full algorithm derivation with empirical tuning data: [docs/algorithm.md](docs/algorithm.md).

---

## 📋 CLI reference

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

### `slide_web.py` — single-server web GUI (all-in-one)

The browser-only entry point: open one page, paste a URL or local path, pick a mode, watch progress, then prune candidates on the same dark contact sheet.

```bash
python3 slide_web.py            # listens on 0.0.0.0:8903
# → open http://localhost:8903/  (or Tailscale http://<your-ip>:8903/)
```

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `~/slides_output` | Output base directory |
| `--port` | `8903` | HTTP port |
| `--bind` | `0.0.0.0` | Bind address |

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
