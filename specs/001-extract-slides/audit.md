# Spec-Kit Audit: slide-extractor

> Cross-check `constitution.md` ⇄ `spec.md` ⇄ `plan.md` ⇄ codebase.
> Surfaces alignment gaps, unstated assumptions, and concrete recommendations.

## Verdict — overall

🟢 **Healthy**, with 6 actionable gaps. No CRITICAL inconsistencies. The codebase delivers what the spec promises; gaps are mostly missing test coverage and undocumented preconditions.

| Health dimension | Score | Note |
|---|---|---|
| Constitution adherence | 8/10 | Principle VIII (test boundaries) is partially violated — 0 integration tests. |
| Spec ↔ Code coverage | 9/10 | All 5 user stories implemented; FR-006 dashboard just landed this session. |
| Plan ↔ Reality drift | 9/10 | Architecture diagram matches actual file layout. |
| Tasks ↔ Backlog truth | 10/10 | New `tasks.md` is the first time backlog is written down. |

---

## Gap 1: Test coverage violates Principle VIII

**Constitution**: "測試 = 演算法核心 + I/O 邊界". Spec FR-006 / FR-007 / FR-004 are HTTP behaviors with **0 tests**.

**Reality**:
```
tests/test_extractor.py  → 14 unit tests, all on slide_extractor.py
tests/                   → NO test for slide_review.py
tests/                   → NO test for slide_web.py
```

**Risk**: Refactoring web GUI (Phase D) cannot be safely automated. Today we caught the RFC 5987 bug by smoke-testing with `curl`; next regression we'll catch the same way (manually).

**Recommendation**: T-G02 + T-G03 in tasks.md. Estimate: 2 hours for both.

---

## Gap 2: Cluster threshold default is too tight for animation reveals

**Constitution Principle II**: "過收優於漏頁". 
**Spec FR-002**: cluster threshold 0.45 default.
**Reality**: slide 11/12 in M2 video got split (jaccard 0.39 < 0.45). User had to manually drop slide 11. *Tool over-extracted, which is correct per Principle II* — but the default is *near* the danger zone.

**Two competing readings**:
- (a) Default is fine because Principle II says over-extract is OK.
- (b) Default should be 0.35 because that specific failure mode (intro → full animation) is so common in real lectures.

**Recommendation**: T-G01 — add subset-merge rule, keep 0.45 default. This handles (a) and (b) without flipping the default. Build regression test suite first.

---

## Gap 3: Adversarial inputs not specified

**Spec is silent on**:
- What happens when yt-dlp downloads a 4GB 4K video? (OOM risk during sampling.)
- What happens when influence is private / age-restricted on YouTube? (yt-dlp 403)
- What happens with vertical-only videos (1080×1920)? (PPTX page will be tall — does python-pptx handle 1920px wide images?)
- What happens with subtitle burn-in (字幕烤進影像)? (Subtitles change every line → false "new slide".)

**Recommendation**: Add adversarial-inputs section to spec.md OR add per-failure error messages.

---

## Gap 4: Multi-user / multi-tenant assumption is implicit

**Constitution Principle VI**: "Local-only by default".
**Spec FR-008**: bind `0.0.0.0`, Tailscale OK.
**Reality**: JOBS dict is **global**, no auth, no user separation. Two people on Tailscale will see each other's jobs.

**Two options**:
- (a) Spec says "single-user tool" explicitly → accept this.
- (b) Add minimal token-based separation if multi-user is expected.

**Recommendation**: Add explicit "Single-user tool" line to spec.md → out of scope: multi-tenancy. If you want multi-tenancy, that's a different product.

---

## Gap 5: Constitution version not tracked

**Reality**: Constitution doesn't have explicit "this principle was added because of incident X on date Y" log entries for each principle. Spec-kit recommends a CHANGELOG-style governance trail.

**Recommendation**: Add `## Principle history` section to constitution.md when next principle is added. Format:
```
v1.1.0 (YYYY-MM-DD): added Principle XI — "..." (driven by incident: ...)
```

---

## Gap 6: Spec doesn't bind algorithm tunables to constitution

`cluster_jaccard 0.45` lives only in code (`DEFAULT_CLUSTER_JACCARD`) and in spec FR-002.
If someone changes it from 0.45 to 0.30, they break Principle I (algorithm reliability) without realizing they need to update spec.

**Recommendation**: Add `## Algorithm parameter contract` section to spec.md that lists each tunable + which principle it implements + what test validates the choice.

---

## What spec-kit gave us that we didn't have before

| Before spec-kit | After |
|---|---|
| Implicit principles in chat | 10 written principles with incident provenance |
| Features documented only in README | 5 user stories with acceptance criteria |
| Architecture in my head | Diagram + technology rejection log |
| Backlog scattered across chat | One ordered `tasks.md` with priority + gates |
| "Are we sure this is done?" | Each shipped task has ✓ checkpoint |

## What spec-kit did NOT give us

- Doesn't auto-generate tests for the gaps it identifies.
- Doesn't enforce the constitution at PR time (need a linter / CI check for that).
- Doesn't track which constitution principles each PR touches.

These are real follow-ups: CI hook that parses commit messages for principle references, lint rule that blocks PRs that change `DEFAULT_*` constants without spec.md update.

---

## Next actions (prioritized)

1. **Now**: User reads this audit, decides which of Gap 1-6 to action.
2. **Next session**: Pick top gap → write checklist → fix → re-audit.
3. **Recurring**: Re-run audit after every feature merge.

## How to re-run

Open the project in your spec-kit-aware agent, then run the equivalent of:
```
/speckit-analyze
```
This will diff spec.md / plan.md / code and produce a fresh audit.
