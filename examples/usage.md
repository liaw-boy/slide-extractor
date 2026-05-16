# Examples

## Basic: extract from a local file

```bash
python slide_extractor.py ~/Videos/intro-cryptography.mp4
```

Output goes to `~/slides_output/intro-cryptography/` (PNG snapshots)
and `~/slides_output/intro-cryptography.pptx`.

## YouTube URL

```bash
python slide_extractor.py "https://www.youtube.com/watch?v=N_Dl7j8qWew"
```

The video is downloaded first via `yt-dlp` into `~/slides_output/_video/`.

## Faster sampling for short videos

For a 5-minute video, the default 3-second interval (~100 samples) is fine.
For very long videos, raise the interval to keep OCR time bounded:

```bash
python slide_extractor.py long-lecture.mp4 --sample-sec 5
```

## More precise transitions

If the algorithm misses a fast transition or a slide that only stays on
screen for ~10 s, sample more densely:

```bash
python slide_extractor.py lecture.mp4 --sample-sec 1
```

(Trade-off: 3× more OCR work.)

## CPU-only

```bash
python slide_extractor.py lecture.mp4 --cpu
```

Plan on ~20× slower OCR. The disk cache mitigates this on the second run.

## Simplified Chinese + English

```bash
python slide_extractor.py lecture.mp4 --lang ch_sim --lang en
```

## Re-running with tuned parameters

The OCR cache (`_ocr_cache_<title>.json`) makes parameter sweeps cheap.
First full run does the heavy OCR; subsequent runs touching only the
threshold logic finish in seconds.

```bash
# First run: full OCR (slow)
python slide_extractor.py lecture.mp4

# Tune the pHash threshold (cache reused, ~1s)
python slide_extractor.py lecture.mp4 --phash-thr 8

# Tune the minimum slide duration
python slide_extractor.py lecture.mp4 --min-duration 12
```
