import pytest

from src.moments import Moment, MomentsError, chunk_transcript


def make_transcript(total_seconds: int, words_per_sec: float = 1.0):
    """One word every 1/words_per_sec seconds, each 0.4s long."""
    tr, t, i = [], 0.0, 0
    step = 1.0 / words_per_sec
    while t < total_seconds:
        tr.append({"word": f"w{i}", "start": round(t, 3),
                   "end": round(t + 0.4, 3), "confidence": 1.0})
        t += step
        i += 1
    return tr


class TestChunkTranscript:
    def test_short_transcript_single_window(self):
        tr = make_transcript(300)  # 5 min < 10 min window
        windows = chunk_transcript(tr)
        assert len(windows) == 1
        assert windows[0] == tr

    def test_long_transcript_multiple_windows_with_overlap(self):
        tr = make_transcript(1500)  # 25 min
        windows = chunk_transcript(tr, window_seconds=600, overlap_seconds=60)
        assert len(windows) == 3
        # Window 2 must start 60s before window 1 ends (overlap)
        w1_end = windows[0][-1]["end"]
        w2_start = windows[1][0]["start"]
        assert w2_start <= w1_end - 55  # ~60s overlap, tolerance for word boundaries
        # Every word appears in at least one window
        covered = {w["start"] for win in windows for w in win}
        assert covered == {w["start"] for w in tr}

    def test_empty_transcript_raises(self):
        with pytest.raises(MomentsError):
            chunk_transcript([])


class TestMomentDataclass:
    def test_fields(self):
        m = Moment(start=1.0, end=31.0, score=80, hook_title="T", reason="R")
        assert m.end - m.start == 30.0
        assert m.caption == ""


from src.moments import _extract_json


class TestExtractJson:
    def test_plain_array(self):
        assert _extract_json('[{"a": 1}]', list) == [{"a": 1}]

    def test_code_fenced(self):
        text = '```json\n[{"a": 1}]\n```'
        assert _extract_json(text, list) == [{"a": 1}]

    def test_surrounding_prose(self):
        text = 'Here are the moments:\n[{"a": 1}]\nHope that helps!'
        assert _extract_json(text, list) == [{"a": 1}]

    def test_dict_kind_ignores_inner_array(self):
        text = 'Result: {"top": [2, 0, 1]}'
        assert _extract_json(text, dict) == {"top": [2, 0, 1]}

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            _extract_json("no json here", list)


from src.moments import _candidates_for_window


class FakeLLM:
    """Returns queued responses in order; records prompts."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def is_available(self):
        return True

    def complete(self, prompt, max_tokens=256, timeout=30):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeLLM ran out of responses")
        return self.responses.pop(0)


class TestCandidatePass:
    def test_valid_candidates_parsed(self):
        window = make_transcript(120)  # 120 words, 1/sec
        llm = FakeLLM(['[{"start_idx": 10, "end_idx": 40, "score": 85, '
                       '"hook_title": "Big reveal", "reason": "Strong hook"}]'])
        cands = _candidates_for_window(window, llm, min_dur=20.0, max_dur=90.0)
        assert len(cands) == 1
        m = cands[0]
        assert m.start == window[10]["start"]
        assert m.end == window[40]["end"]
        assert m.score == 85
        assert m.hook_title == "Big reveal"

    def test_out_of_bounds_and_too_short_dropped(self):
        window = make_transcript(120)
        llm = FakeLLM(['['
                       '{"start_idx": 10, "end_idx": 15, "score": 90, "hook_title": "x", "reason": "too short"},'
                       '{"start_idx": 100, "end_idx": 999, "score": 90, "hook_title": "x", "reason": "oob"},'
                       '{"start_idx": 50, "end_idx": 20, "score": 90, "hook_title": "x", "reason": "reversed"},'
                       '{"start_idx": 10, "end_idx": 40, "score": 80, "hook_title": "ok", "reason": "good"}'
                       ']'])
        cands = _candidates_for_window(window, llm, min_dur=20.0, max_dur=90.0)
        assert len(cands) == 1
        assert cands[0].hook_title == "ok"

    def test_malformed_json_retries_once_then_gives_up(self):
        window = make_transcript(120)
        llm = FakeLLM(["not json at all", "still not json"])
        cands = _candidates_for_window(window, llm, min_dur=20.0, max_dur=90.0)
        assert cands == []
        assert len(llm.prompts) == 2
        assert "ONLY" in llm.prompts[1]  # stricter retry prompt

    def test_retry_succeeds_second_time(self):
        window = make_transcript(120)
        llm = FakeLLM(["garbage",
                       '[{"start_idx": 10, "end_idx": 40, "score": 70, '
                       '"hook_title": "t", "reason": "r"}]'])
        cands = _candidates_for_window(window, llm, min_dur=20.0, max_dur=90.0)
        assert len(cands) == 1


from src.moments import dedupe_candidates


class TestDedupe:
    def test_heavy_overlap_keeps_higher_score(self):
        a = Moment(start=10.0, end=40.0, score=90, hook_title="A", reason="")
        b = Moment(start=12.0, end=42.0, score=60, hook_title="B", reason="")
        result = dedupe_candidates([b, a])
        assert result == [a]

    def test_light_overlap_keeps_both(self):
        a = Moment(start=10.0, end=40.0, score=90, hook_title="A", reason="")
        b = Moment(start=35.0, end=70.0, score=60, hook_title="B", reason="")
        # overlap 5s / min(30,35)=30 → 17% < 50%
        result = dedupe_candidates([a, b])
        assert len(result) == 2

    def test_disjoint_keeps_both(self):
        a = Moment(start=10.0, end=40.0, score=90, hook_title="A", reason="")
        b = Moment(start=100.0, end=130.0, score=60, hook_title="B", reason="")
        assert len(dedupe_candidates([a, b])) == 2


from src.moments import _rank_and_caption


def _three_candidates():
    return [
        Moment(start=10.0, end=40.0, score=70, hook_title="A", reason="ra"),
        Moment(start=100.0, end=140.0, score=90, hook_title="B", reason="rb"),
        Moment(start=200.0, end=230.0, score=50, hook_title="C", reason="rc"),
    ]


class TestRankAndCaption:
    def test_top_n_selected_in_rank_order(self):
        llm = FakeLLM([
            '{"top": [1, 0]}',
            '[{"index": 0, "caption": "cap B #x"}, {"index": 1, "caption": "cap A #y"}]',
        ])
        winners = _rank_and_caption(_three_candidates(), llm, count=2)
        assert [m.hook_title for m in winners] == ["B", "A"]
        assert winners[0].caption == "cap B #x"
        assert winners[1].caption == "cap A #y"

    def test_ranking_failure_falls_back_to_score_order(self):
        llm = FakeLLM(["garbage", "still garbage",
                       '[{"index": 0, "caption": "c1"}, {"index": 1, "caption": "c2"}]'])
        winners = _rank_and_caption(_three_candidates(), llm, count=2)
        # Fallback: sort by score desc → B(90), A(70)
        assert [m.hook_title for m in winners] == ["B", "A"]

    def test_caption_failure_leaves_captions_empty(self):
        llm = FakeLLM(['{"top": [1, 0]}', "garbage", "still garbage"])
        winners = _rank_and_caption(_three_candidates(), llm, count=2)
        assert [m.hook_title for m in winners] == ["B", "A"]
        assert all(m.caption == "" for m in winners)

    def test_fewer_candidates_than_count(self):
        llm = FakeLLM(['{"top": [0]}', '[{"index": 0, "caption": "c"}]'])
        cands = [Moment(start=1.0, end=31.0, score=60, hook_title="only", reason="r")]
        winners = _rank_and_caption(cands, llm, count=5)
        assert len(winners) == 1

    def test_invalid_indices_ignored(self):
        llm = FakeLLM(['{"top": [99, 1, 1, 0]}',
                       '[{"index": 0, "caption": "c1"}, {"index": 1, "caption": "c2"}]'])
        winners = _rank_and_caption(_three_candidates(), llm, count=2)
        assert [m.hook_title for m in winners] == ["B", "A"]
