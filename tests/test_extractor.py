"""Unit tests for slide_extractor's pure logic.

We do NOT run the full pipeline here (that requires GPU + a real video).
The pipeline is covered by the validation runs documented in the README.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the script importable as a module:
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import slide_extractor as sx  # noqa: E402


@pytest.mark.unit
class TestTokenize:
    def test_english_words_lowercased(self) -> None:
        toks = sx.text_to_tokens("Hello WORLD foo")
        assert "hello" in toks
        assert "world" in toks
        assert "foo" in toks

    def test_chinese_uses_bigrams(self) -> None:
        toks = sx.text_to_tokens("加密演算法")
        assert "加密" in toks
        assert "密演" in toks
        assert "演算" in toks
        assert "算法" in toks

    def test_single_char_chinese_kept(self) -> None:
        toks = sx.text_to_tokens("好")
        assert "好" in toks

    def test_punctuation_stripped(self) -> None:
        toks = sx.text_to_tokens("Module 2-3-1: 公開金鑰加密法")
        # punctuation must not appear in any token
        assert all(":" not in t and "-" not in t for t in toks)

    def test_short_english_dropped(self) -> None:
        # Single ASCII letters are noise (e.g. "a", "i") — must not appear
        toks = sx.text_to_tokens("a b c hi yes")
        assert "a" not in toks and "b" not in toks
        assert "hi" in toks
        assert "yes" in toks


@pytest.mark.unit
class TestClassifyTransition:
    def _make_sample(self, *, tokens: set[str], phash_val: int) -> sx.Sample:
        import imagehash
        import numpy as np

        # Forge an ImageHash from a 64-bit int for deterministic distances.
        bits = format(phash_val, "064b")
        arr = [[bool(int(b)) for b in bits[i : i + 8]] for i in range(0, 64, 8)]
        return sx.Sample(
            frame_idx=0,
            frame=np.zeros((1, 1, 3), dtype=np.uint8),
            text="",
            tokens=frozenset(tokens),
            phash=imagehash.ImageHash(np.array(arr, dtype=bool)),
        )

    def test_visually_stable_is_same(self) -> None:
        cfg = sx.ExtractorConfig()
        a = self._make_sample(tokens={"x", "y", "z"}, phash_val=0)
        b = self._make_sample(tokens={"x", "y", "z"}, phash_val=0)
        is_trans, _ = sx.classify_transition(a, b, cfg)
        assert is_trans is False

    def test_text_shrink_is_transition(self) -> None:
        cfg = sx.ExtractorConfig()
        # Shrink with token overlap that survives the hard-OCR cutoff,
        # so the "text shrank" path actually fires (not hard-OCR).
        common = {f"t{i}" for i in range(20)}
        a = self._make_sample(tokens=common, phash_val=0)
        b = self._make_sample(
            tokens={f"t{i}" for i in range(8)},  # subset of A, but small
            phash_val=int("1" * 64, 2),
        )
        is_trans, reason = sx.classify_transition(a, b, cfg)
        assert is_trans is True
        assert "shrank" in reason

    def test_hard_jaccard_transition_even_with_low_phash(self) -> None:
        cfg = sx.ExtractorConfig()
        # Real-world failure mode: same-template slides → pHash distance is
        # below threshold, but OCR content is completely different.
        a = self._make_sample(tokens={f"t{i}" for i in range(20)}, phash_val=0)
        b = self._make_sample(tokens={f"u{i}" for i in range(20)}, phash_val=4)
        is_trans, reason = sx.classify_transition(a, b, cfg)
        assert is_trans is True
        assert "hard-OCR" in reason

    def test_growth_with_subset_is_animation(self) -> None:
        cfg = sx.ExtractorConfig()
        a = self._make_sample(tokens={f"t{i}" for i in range(10)}, phash_val=0)
        # New tokens include all of A + more (animation step)
        new_tokens = {f"t{i}" for i in range(10)} | {f"u{i}" for i in range(20)}
        b = self._make_sample(tokens=new_tokens, phash_val=int("1" * 32, 2))
        is_trans, reason = sx.classify_transition(a, b, cfg)
        assert is_trans is False
        assert "animation" in reason or "subset" in reason

    def test_content_change_is_transition(self) -> None:
        cfg = sx.ExtractorConfig()
        # Different content but with enough overlap to stay above hard-jaccard
        # cutoff, so the "content change" (mid-level) path actually fires.
        shared = {f"t{i}" for i in range(5)}
        a = self._make_sample(tokens=shared | {f"a{i}" for i in range(10)}, phash_val=0)
        b = self._make_sample(
            tokens=shared | {f"b{i}" for i in range(10)},
            phash_val=int("1" * 32, 2),
        )
        is_trans, reason = sx.classify_transition(a, b, cfg)
        assert is_trans is True
        assert "content change" in reason


@pytest.mark.unit
class TestResolveSource:
    def test_http_url_detected(self) -> None:
        assert sx.is_url("https://www.youtube.com/watch?v=abc") is True
        assert sx.is_url("http://example.com/video.mp4") is True
        assert sx.is_url("www.youtube.com/watch?v=abc") is True

    def test_local_paths_not_detected(self) -> None:
        assert sx.is_url("/tmp/lecture.mp4") is False
        assert sx.is_url("lecture.mp4") is False
        assert sx.is_url("./videos/foo.mkv") is False

    def test_existing_local_file_passes(self, tmp_path: Path) -> None:
        video = tmp_path / "fake.mp4"
        video.write_bytes(b"\x00")
        out = sx.resolve_source(str(video), tmp_path / "_dl")
        assert out == video

    def test_missing_local_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError) as exc:
            sx.resolve_source("not_a_real_file.mp4", tmp_path / "_dl")
        assert "not found" in str(exc.value)
