#!/usr/bin/env bash
# slide-extractor one-shot installer.
# Idempotent — safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── helpers ───────────────────────────────────────────────────────
log()  { printf "\033[36m▶\033[0m %s\n" "$*"; }
warn() { printf "\033[33m⚠\033[0m %s\n" "$*"; }
err()  { printf "\033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }

# ── check Python ──────────────────────────────────────────────────
if ! command -v python3 >/dev/null; then
    err "python3 not found — install Python 3.10+ first"
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
log "Python $PY_VER detected"

# ── pip install ───────────────────────────────────────────────────
log "Installing Python dependencies (this can take ~5 min on first run)"
PIP_FLAGS="--user --break-system-packages"
if [[ "${VIRTUAL_ENV:-}" != "" ]]; then
    PIP_FLAGS=""
    log "Active venv detected: $VIRTUAL_ENV (installing into it)"
fi
# shellcheck disable=SC2086
python3 -m pip install $PIP_FLAGS -r requirements.txt
# shellcheck disable=SC2086
python3 -m pip install $PIP_FLAGS yt-dlp  # for YouTube support

# ── GPU sanity check (informational only) ─────────────────────────
if python3 -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
    GPU=$(python3 -c "import torch; print(torch.cuda.get_device_name(0))")
    log "GPU OK: $GPU (OCR will run ~20x faster than CPU)"
else
    warn "No CUDA GPU detected — extractor will still work but OCR will be slow."
    warn "Pass --cpu to suppress the GPU init warning."
fi

# ── system tools ──────────────────────────────────────────────────
for bin in ffmpeg; do
    if ! command -v $bin >/dev/null; then
        warn "$bin not on PATH (recommended for video probing — sudo apt install $bin)"
    fi
done

# ── prime OCR model cache (download once) ─────────────────────────
log "Pre-downloading EasyOCR Chinese + English models (~120MB, one-time)…"
python3 -c "
import easyocr, sys
try:
    r = easyocr.Reader(['ch_tra','en'], gpu=False, verbose=False)
    print('models ready')
except Exception as e:
    print(f'model download failed: {e}', file=sys.stderr); sys.exit(1)
"

cat <<EOF

✓ Installation complete.

Quick start:
  $ python3 slide_extractor.py /path/to/lecture.mp4         # auto mode
  $ python3 slide_review.py    /path/to/lecture.mp4         # review-with-UI mode

  $ python3 slide_extractor.py "https://www.youtube.com/watch?v=..."  # YouTube

After review-UI mode, open the printed URL in a browser, tick the slides to
keep, click "Save selection → generate PPTX". Final PPTX lands in:
  ~/slides_output/<video-title>_REVIEWED.pptx

Run "python3 slide_extractor.py --help" for full CLI reference.
EOF
