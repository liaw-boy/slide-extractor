# slide-extractor

> Automatically extract complete slides from lecture videos into PNG snapshots and a 16:9 PPTX deck.
> 從演講 / 教學影片自動擷取完整投影片並輸出 PNG 與 PPTX 簡報檔。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

## Why this exists

Most video → slides tools fail on lecture videos because:

- **HSV histogram / PySceneDetect** — slides usually share a template (same background, fonts, footer). The histogram barely changes between consecutive slides.
- **pHash alone** — also fooled by shared templates.
- **SSIM** — same problem: structural similarity stays high between same-template slides.
- **OCR text Jaccard** — different slides on the same topic share a lot of vocabulary, so naive text comparison merges them.

`slide-extractor` combines pHash and OCR token analysis with an explicit
**animation-vs-transition** decision rule that handles the cases where each
single signal fails. See [docs/algorithm.md](docs/algorithm.md) for the full
write-up and the empirical data the thresholds were tuned against.

## Features

- GPU-accelerated OCR via [EasyOCR](https://github.com/JaidedAI/EasyOCR) — full lecture (~2 hr) finishes in a few minutes on a single GPU.
- Disk-backed OCR cache — re-running the algorithm with different thresholds is instant.
- Picks the **animation-complete frame** of each slide (the moment right before the next transition), not a half-rendered bullet list.
- One-shot export to a 16:9 PPTX deck for downstream editing.
- Works on local video files OR YouTube URLs (via `yt-dlp`).

## Install

```bash
git clone <this repo>
cd slide-extractor
pip install -r requirements.txt
# optional, for YouTube downloading:
pip install yt-dlp
```

Tested on Python 3.10+ with NVIDIA GPU (CUDA). CPU-only is supported via `--cpu`
but expect ~20× slower OCR.

## Quickstart

```bash
# from a local file
python slide_extractor.py /path/to/lecture.mp4

# from YouTube
python slide_extractor.py "https://www.youtube.com/watch?v=XXXXXXXXXXX"

# custom output directory
python slide_extractor.py lecture.mp4 -o ./my-output

# tune the sampling interval (smaller = more precise, slower)
python slide_extractor.py lecture.mp4 --sample-sec 2

# CPU-only
python slide_extractor.py lecture.mp4 --cpu

# Other languages (e.g. simplified Chinese + English)
python slide_extractor.py lecture.mp4 --lang ch_sim --lang en
```

Output layout:

```
<output>/
├── <video-title>/
│   ├── slide_001_00h02m21s.png
│   ├── slide_002_00h09m24s.png
│   └── ...
├── <video-title>.pptx
└── _ocr_cache_<video-title>.json   # speeds up re-runs
```

## CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `source` | — | Local video path or YouTube URL (required) |
| `-o`, `--output` | `~/slides_output` | Output base directory |
| `--sample-sec` | `3.0` | Sampling interval in seconds |
| `--phash-thr` | `6` | pHash distance threshold for a transition |
| `--min-duration` | `9` | Minimum slide on-screen duration in seconds |
| `--cpu` | off | Force CPU-only OCR |
| `--lang LANG` | `ch_tra en` | EasyOCR language code; repeat for multiple |
| `-v`, `-vv` | off | Increase log verbosity |

## Validation

The algorithm is validated against two real lectures:

| Video | Length | Expected | Detected | Notes |
|-------|--------|----------|----------|-------|
| OWASP Mobile M1 (Mandarin) | 55 min | 13 | **13** | All ground-truth timestamps matched within ~10 s |
| Cryptography Module 2 (Mandarin) | 2 hr 4 min | (unknown) | **40** | 0 visual-duplicate flags, 0 short-duration flags |

## Algorithm in one paragraph

For each pair of consecutive sampled frames, compute the **pHash distance**
and the **token-level subset relationship**:

- pHash distance below threshold → same visual state, skip.
- Text shrank sharply → real transition (animations only add content).
- Text grew and the old token set is mostly contained in the new → animation
  step within the same slide.
- Otherwise (visual change + content really differs) → real transition.

Within each slide segment, pick the frame with the most OCR tokens, breaking
ties by choosing the **latest** such frame (closest to the next transition,
i.e. the animation-complete state).

Full derivation and tuning notes: [docs/algorithm.md](docs/algorithm.md).

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [EasyOCR](https://github.com/JaidedAI/EasyOCR) for the GPU OCR backend
- [imagehash](https://github.com/JohannesBuchner/imagehash) for pHash
- [python-pptx](https://github.com/scanny/python-pptx) for PPTX export
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for YouTube downloading

## Contributing

PRs welcome. Please run `ruff` + `black` before submitting:

```bash
pip install black ruff
black slide_extractor.py
ruff check slide_extractor.py
```
