# Tasks: 001-extract-slides

## Shipped (✓ Done)

### Phase A — Core pipeline
- [x] T-A01 GPU EasyOCR + disk-backed JSON cache
- [x] T-A02 pHash perceptual hashing per frame
- [x] T-A03 Token bigram tokenizer (CJK bigrams + English words)
- [x] T-A04 Online content clustering with jaccard threshold
- [x] T-A05 Pick representative frame (most tokens = animation-complete state)
- [x] T-A06 Aspect-preserving PPTX export

### Phase B — Inputs & dispatch
- [x] T-B01 `is_url()` URL detection
- [x] T-B02 `resolve_source()` URL-vs-file dispatch with FileNotFoundError
- [x] T-B03 yt-dlp wrapper with 1080p cap
- [x] T-B04 4 unit tests for input dispatch

### Phase C — Human-in-the-loop review
- [x] T-C01 Paranoid mode preset (denser sampling, lower threshold)
- [x] T-C02 Dark-theme contact sheet HTML with checkboxes
- [x] T-C03 `/finalize` POST → REVIEWED PPTX export
- [x] T-C04 HTTP server on port 8901 (slide_review.py)

### Phase D — Web GUI (slide_web.py)
- [x] T-D01 Submission form (URL or local path + mode toggle)
- [x] T-D02 Background worker thread per job
- [x] T-D03 In-memory JOBS dict with lock
- [x] T-D04 Progress page with auto-polling
- [x] T-D05 `/api/jobs` + dashboard on home page
- [x] T-D06 Live progress bar with ETA
- [x] T-D07 `JobProgressHandler` (logging.Handler → progress fields)
- [x] T-D08 `stream_download_video()` with yt-dlp `--newline` parsing
- [x] T-D09 RFC 5987 Content-Disposition for non-ASCII filenames
- [x] T-D10 Sheet HTML rewrite (per-job finalize URL, slide src patching)

### Phase E — Honesty layer
- [x] T-E01 Scope section in README (works well / borderline / not for)
- [x] T-E02 Copyright callout at README top (`> [!IMPORTANT]`)
- [x] T-E03 `NOTICE` file with Do/Don't list
- [x] T-E04 CLI `--help` description with Scope + Copyright
- [x] T-E05 Web UI yellow notice box on home page

### Phase F — Spec-kit retrospective (this PR)
- [x] T-F01 `specify init --here` scaffolding
- [x] T-F02 Reverse-engineered `constitution.md` (10 principles)
- [x] T-F03 Reverse-engineered `spec.md` (5 user stories + 8 FRs)
- [x] T-F04 Reverse-engineered `plan.md` (architecture + algorithm derivation)
- [x] T-F05 This `tasks.md`

---

## Backlog (□ Pending — priority ordered)

### P1 — Reliability gaps
- [ ] T-G01 **Fix animation-reveal cluster split**
  - Problem: slide 11 (36 tokens intro) and slide 12 (92 tokens full version) get split because jaccard 36/92 = 0.39 < 0.45.
  - Approach: add subset-merge rule after clustering — if cluster A's tokens are ≥ 0.85 contained in cluster B's, merge A→B.
  - Risk: regress on legitimately distinct slides that share vocabulary.
  - **Gate**: build regression test suite from OWASP M1/M2 + Crypto + t4hNkGJOWnk before changing default.

- [ ] T-G02 **Integration test for end-to-end pipeline**
  - Currently 0 integration tests. Smoke driven manually.
  - Approach: vendor a tiny synthetic test video (10 frames, 3 fake slides) into `tests/fixtures/`, run full pipeline, assert slide count.

- [ ] T-G03 **E2E test for web GUI**
  - Approach: pytest + httpx, spin up `slide_web` in subprocess, hit /api/start → poll → /api/finalize → download. Stub yt-dlp.

### P2 — UX polish
- [ ] T-G04 **Cancel a running job**
  - No way to stop a 10-min OCR job started by accident. Need DELETE /api/job/<id>.
  - Approach: pass `threading.Event` into worker; check between samples.

- [ ] T-G05 **Persist jobs across server restart**
  - Restart `slide_web.py` → lose dashboard. Approach: write `jobs.json` on each status change.

- [ ] T-G06 **Drag-and-drop file upload in browser**
  - Currently must paste local path. Some users want drag the video into the browser.
  - Tradeoff: multipart upload of 200MB video over Tailscale is slow vs pasting path.

- [ ] T-G07 **Mobile-responsive contact sheet**
  - Sheet grid is 280px min — on mobile two columns OK but checkboxes hard to tap.

### P3 — Distribution
- [ ] T-G08 **PyInstaller single-file binary**
  - User parked this. Reactivate once web GUI usage stabilizes.
  - Output: `dist/slide-extractor` (~400MB with EasyOCR models bundled).

- [ ] T-G09 **Docker image option**
  - For users who don't want to install GPU stack on host.

- [ ] T-G10 **GitHub release with prebuilt assets**
  - Tagged release + binary downloads in addition to source.

### P4 — Algorithm research
- [ ] T-G11 **Speaker-camera overlay detection**
  - Detect PiP overlay rectangle, mask it out of OCR/pHash → less false transitions.

- [ ] T-G12 **Whiteboard/handwriting mode**
  - Currently in "❌ not designed for" — could add separate pipeline that uses contour detection instead of OCR for those.
  - Decide if scope creep is worth it.

---

## Done (this session, 2026-05-17)
- T-D05, T-D06, T-D07, T-D08, T-D09, T-D10
- T-E01, T-E02, T-E03, T-E04, T-E05
- T-F01, T-F02, T-F03, T-F04, T-F05

## Done (previous sessions)
- All of Phase A, B, C
- T-D01, T-D02, T-D03, T-D04
