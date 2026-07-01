import random

import pytest
from src.clipper import calculate_cut_points, sanitize_title, CLIP_MIN, CLIP_MAX


class TestCalculateCutPoints:
    def test_short_video_single_clip(self):
        cuts = calculate_cut_points(30.0, "random")
        assert len(cuts) == 1
        assert cuts[0][0] == 0.0

    def test_exact_clip_length(self):
        cuts = calculate_cut_points(65.0, "random")
        assert len(cuts) == 1

    def test_multiple_clips(self):
        cuts = calculate_cut_points(200.0, "random")
        assert len(cuts) >= 2
        # Clips should cover full duration
        total = sum(dur for _, dur in cuts)
        assert abs(total - 200.0) < 1.0

    def test_last_clip_merged_if_short(self):
        # Seed RNG so this doesn't intermittently fail on an unmergeable tail.
        random.seed(1234)
        cuts = calculate_cut_points(130.0, "random")
        for _, dur in cuts:
            assert dur >= CLIP_MIN - 1  # Allow small float imprecision


def _synthetic_transcript(gap_after=63):
    """~200s transcript, one word/sec, with an extra-long silence right
    after `gap_after` (inside clip 1's 55-75s window)."""
    tr, t = [], 0.0
    for i in range(200):
        d = 0.4
        tr.append({"word": f"w{i}", "start": round(t, 3),
                   "end": round(t + d, 3), "confidence": 1.0})
        t = round(t + d + (1.6 if i == gap_after else 0.6), 3)
    return tr, t


class TestSmartCutModes:
    def test_natural_pause_cuts_at_silence_gap(self):
        tr, dur = _synthetic_transcript(gap_after=63)
        cuts = calculate_cut_points(dur, "natural_pause", tr, None)
        assert len(cuts) >= 2
        gap_mid = (tr[63]["end"] + tr[64]["start"]) / 2
        # First cut must land at the deliberate silence gap, not a random point.
        assert abs(cuts[0][1] - gap_mid) < 0.01

    def test_cliffhanger_invokes_llm_and_uses_its_choice(self):
        tr, dur = _synthetic_transcript(gap_after=63)

        class StubLLM:
            def __init__(self):
                self.calls = 0

            def is_available(self):
                return True

            def complete(self, prompt):
                self.calls += 1
                return "index 5"

        llm = StubLLM()
        cuts = calculate_cut_points(dur, "cliffhanger", tr, llm)
        assert llm.calls > 0, "cliffhanger never called the LLM"
        window = [w for w in tr if w["start"] >= 55.0 and w["end"] <= min(75.0, dur)]
        assert abs(cuts[0][1] - window[5]["end"]) < 0.01

    def test_cliffhanger_without_llm_falls_back(self):
        tr, dur = _synthetic_transcript(gap_after=63)
        # llm=None must not crash and must still produce valid clips.
        cuts = calculate_cut_points(dur, "cliffhanger", tr, None)
        assert len(cuts) >= 2
        assert abs(sum(d for _, d in cuts) - dur) < 1.0


class TestSanitizeTitle:
    def test_removes_special_chars(self):
        assert sanitize_title('Test: "Video" | Cool') == 'Test Video  Cool'

    def test_strips_trailing_dots(self):
        assert sanitize_title("test...") == "test"

    def test_preserves_normal_chars(self):
        assert sanitize_title("Normal Title 123") == "Normal Title 123"

    def test_empty_after_sanitize_falls_back(self):
        # Punctuation-only titles must not collapse to an empty dir name.
        assert sanitize_title("???") == "video"
        assert sanitize_title("...") == "video"
        assert sanitize_title("") == "video"


from src.clipper import build_overlay_filters, FONT_PATH, FFMPEG_CMD


class TestBuildOverlayFilters:
    @pytest.mark.skipif(not FONT_PATH, reason="no caption font available")
    def test_default_has_title_and_part(self, tmp_path):
        tf = str(tmp_path / "title.txt")
        f = build_overlay_filters("My Title", 1, top_text=None, show_part_label=True,
                                  textfile_path=tf)
        # Top text travels via a UTF-8 textfile, never inline in the filter.
        assert (tmp_path / "title.txt").read_text(encoding="utf-8") == "My Title"
        assert "textfile=" in f
        assert "expansion=none" in f
        assert "My Title" not in f
        assert "Part 1" in f

    @pytest.mark.skipif(not FONT_PATH, reason="no caption font available")
    def test_custom_top_text_replaces_title(self, tmp_path):
        tf = str(tmp_path / "title.txt")
        f = build_overlay_filters("My Title", 1, top_text="INSANE story",
                                  show_part_label=False, textfile_path=tf)
        content = (tmp_path / "title.txt").read_text(encoding="utf-8")
        assert "INSANE story" in content
        assert "My Title" not in content
        assert "My Title" not in f
        assert "Part" not in f

    def test_no_font_returns_empty(self, monkeypatch):
        import src.clipper as clipper_mod
        monkeypatch.setattr(clipper_mod, "FONT_PATH", "")
        assert build_overlay_filters("T", 1, None, True) == ""

    @pytest.mark.skipif(not FONT_PATH, reason="no caption font available")
    def test_missing_textfile_path_raises(self):
        with pytest.raises(ValueError):
            build_overlay_filters("T", 1, None, True)

    @pytest.mark.skipif(not FONT_PATH, reason="no caption font available")
    def test_special_chars_go_to_textfile_not_filter(self, tmp_path):
        raw = "Plot twist: it's over, really 100%"
        tf = str(tmp_path / "title.txt")
        f = build_overlay_filters(raw, 1, None, True, textfile_path=tf)
        # No raw user text may appear in the filter string — ffmpeg 7.1's
        # filtergraph parser silently corrupts inline quotes/percent.
        assert "Plot" not in f
        assert "twist" not in f
        assert "it's" not in f
        # The text lands verbatim in the file (modulo line wrapping).
        content = (tmp_path / "title.txt").read_text(encoding="utf-8")
        assert content.replace("\n", " ") == raw
        # textfile path escaped like fontfile: forward slashes, colon -> \:
        safe_tf = tf.replace("\\", "/").replace(":", "\\:")
        assert f"textfile='{safe_tf}':expansion=none" in f
        # Both drawtext calls disable expansion; option separators intact.
        assert f.count("expansion=none") == 2
        assert ":fontcolor=white:" in f

    @pytest.mark.skipif(FFMPEG_CMD is None, reason="ffmpeg not available")
    @pytest.mark.skipif(not FONT_PATH, reason="no caption font available")
    def test_ffmpeg_accepts_special_chars_in_overlay(self, tmp_path):
        import subprocess
        # Apostrophe, unicode apostrophe, colon, comma, percent — every one
        # of these has a known silent-corruption mode with inline text=.
        text = "Plot twist: it’s 100% wild, isn't it"
        tf = str(tmp_path / "title.txt")
        f = build_overlay_filters(text, 1, None, True, textfile_path=tf)
        cmd = [
            FFMPEG_CMD, "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1",
            "-vf", f, "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        # Return code alone is NOT enough: several corruption modes exit 0
        # while burning filter options into the frame or dropping glyphs.
        assert result.returncode == 0, f"ffmpeg rejected filter: {result.stderr[:500]}"
        assert result.stderr.strip() == "", f"ffmpeg emitted errors: {result.stderr[:500]}"
