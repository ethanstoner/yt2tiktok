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
        # A duration that would produce a very short last clip
        cuts = calculate_cut_points(130.0, "random")
        for _, dur in cuts:
            assert dur >= CLIP_MIN - 1  # Allow small float imprecision


class TestSanitizeTitle:
    def test_removes_special_chars(self):
        assert sanitize_title('Test: "Video" | Cool') == 'Test Video  Cool'

    def test_strips_trailing_dots(self):
        assert sanitize_title("test...") == "test"

    def test_preserves_normal_chars(self):
        assert sanitize_title("Normal Title 123") == "Normal Title 123"
