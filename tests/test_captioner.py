import pytest
from src.captioner import group_into_phrases, detect_keywords_heuristic, _ass_timestamp


def _make_transcript(words, gap=0.3):
    transcript = []
    t = 0.0
    for w in words:
        transcript.append({"word": w, "start": round(t, 3), "end": round(t + 0.25, 3), "confidence": 1.0})
        t += 0.25 + gap
    return transcript


class TestGroupIntoPhrases:
    def test_empty_transcript(self):
        assert group_into_phrases([]) == []

    def test_single_word(self):
        t = _make_transcript(["hello"])
        phrases = group_into_phrases(t)
        assert len(phrases) >= 1

    def test_basic_grouping(self):
        t = _make_transcript(["this", "is", "a", "test"])
        phrases = group_into_phrases(t)
        assert len(phrases) >= 1
        # All indices should be accounted for
        all_indices = [i for p in phrases for i in p]
        assert sorted(all_indices) == list(range(len(t)))

    def test_no_single_word_orphans(self):
        t = _make_transcript(["word"] * 10)
        phrases = group_into_phrases(t)
        for p in phrases:
            assert len(p) >= 2 or len(phrases) == 1


class TestDetectKeywordsHeuristic:
    def test_long_words_detected(self):
        t = _make_transcript(["a", "big", "enormous", "cat"])
        indices = detect_keywords_heuristic(t)
        assert 2 in indices  # "enormous" is 8 chars

    def test_uppercase_detected(self):
        t = [{"word": "WOW", "start": 0, "end": 0.5, "confidence": 1.0}]
        indices = detect_keywords_heuristic(t)
        assert 0 in indices


class TestAssTimestamp:
    def test_zero(self):
        assert _ass_timestamp(0) == "0:00:00.00"

    def test_seconds(self):
        assert _ass_timestamp(5.5) == "0:00:05.50"

    def test_minutes(self):
        assert _ass_timestamp(65.0) == "0:01:05.00"

    def test_hours(self):
        assert _ass_timestamp(3661.5) == "1:01:01.50"
