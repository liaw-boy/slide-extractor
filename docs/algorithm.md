# Algorithm

A detailed walk-through of how `slide-extractor` reliably separates real slide
transitions from in-slide animation steps in lecture videos.

## Problem statement

Given a lecture video where the speaker advances through a set of slides
(possibly with bullets/text appearing one at a time inside each slide), output
**one image per real slide**, captured at the moment animations finish (so the
slide is at its most complete state).

The naive approaches all fail in well-known ways:

| Approach | Fails because |
|----------|---------------|
| HSV colour histogram (PySceneDetect's default) | Same template → same histogram. Cuts not detected. |
| pHash, raw distance threshold | Same template fools pHash too. |
| SSIM | Same problem — structural similarity stays high. |
| OCR text Jaccard | Slides on related topics share too many words. |
| pHash with low threshold | Now catches **every animation step** as well. |

## The combined rule

For every pair of consecutive sampled frames `(A, B)`:

1. Compute `pHash_dist(A, B)`.
2. Tokenise OCR text into **Chinese bigrams + English words**.
3. Compute `size_ratio = |B_tokens| / |A_tokens|` and `old_in_new = |A ∩ B| / |A|`.

Decision rule:

```
if pHash_dist < PHASH_THR:           return SAME       # visually unchanged
if size_ratio < SIZE_RATIO_DROP:     return TRANSITION # text shrank → must be a new slide
if size_ratio >= SIZE_RATIO_GROW
   and old_in_new >= SUBSET_THR:     return SAME       # animation step
if old_in_new >= SUBSET_THR:         return SAME       # ambiguous subset, treat conservatively
return TRANSITION                                       # visual change + content really differs
```

The two **subset** checks plus the **shrink** check are the key:

- A within-slide animation only **adds** content, so `B_tokens ⊃ A_tokens`
  approximately. We detect that by `old_in_new ≥ 0.85`.
- A real slide transition either **changes** the content (low subset) or
  **drops** content (`size_ratio < 0.6` — animations never remove text).

## Empirical tuning data

The thresholds in `slide_extractor.py` are not guessed. They are picked from
real OCR + pHash data on a Mandarin cryptography lecture, where the ground
truth was known. Here is a snippet of the per-frame analysis around
`01:52–01:55` (a region with three real transitions tightly packed):

| Time | pHash dist | jaccard | old_in_new | What is it? |
|------|-----------:|--------:|-----------:|-------------|
| 01:53:03 | 10 | 0.29 | 0.77 | **Real transition** ("內容" → "其他公開金鑰演算法") |
| 01:53:06 → 01:53:48 | 0–2 | 0.93–1.00 | ≥ 0.96 | Same slide, OCR jitter |
| 01:53:51 | 10 | 0.28 | 1.00 | **Real transition** (next slide's title only) |
| 01:53:54 | 10 | 0.30 | 0.87 | **Animation** — title → title + body |
| 01:54:06 / 01:54:21 | 6 | 0.57 / 0.71 | 0.91 / 0.94 | OCR jitter (Chinese OCR confidence wobble) |

Notice that the first and third rows have nearly identical pHash distance
*and* near-identical jaccard, yet one is a transition and one is animation.
The discriminator is the `size_ratio + old_in_new` pair.

## Why not just use PySceneDetect's `AdaptiveDetector`?

We tried. On the OWASP M1 lecture (55 min, known to have 13 slides), every
PySceneDetect detector returned 10–12 scenes because some real slide
transitions had HSV-histogram distances *below* the noise floor of changes
within other slides. The combined OCR + pHash rule gets all 13.

## Per-segment representative frame

Once segments are identified, we pick one frame per segment to save. The
chosen frame is the one with the **most OCR tokens** in that segment;
ties are broken by picking the **latest** frame (closest to the next
transition).

Rationale:

- "Most tokens" = animation has played the longest, so the most content is on
  screen.
- "Latest" tie-breaker = if the slide reached its final state early and stayed
  there, picking the frame closest to the transition makes the output
  consistent with how a human would screenshot a slide.

## Edge cases handled

- **Title-only intermediate frames** (e.g. `01:53:51` above): caught by the
  `size_ratio < 0.6` shrink rule on the *next* transition.
- **Same-template adjacent slides**: caught by combining low `old_in_new`
  with the pHash signal; neither alone is enough.
- **OCR jitter on the same slide** (`pHash_dist = 6`, `jaccard = 0.57`):
  rejected because `old_in_new ≥ 0.85`.
- **Animation noise that yields a fake one-sample slide**: filtered out by
  `MIN_SLIDE_DURATION` (default 9 s).

## Limitations

- Requires **OCR-friendly text**; slides that are pure images / diagrams with
  little text will be treated as one slide regardless of visual changes
  because the tokens cannot drive the decision rule.
- The current build is tuned for **traditional Chinese + English** lectures.
  Other scripts (e.g. simplified Chinese, Japanese) should still work — pass
  `--lang` flags accordingly — but thresholds may need adjustment.
- 720p+ source video is recommended; very low-resolution OCR (480p or below)
  drops accuracy, especially for small footer text.
