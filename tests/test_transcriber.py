import subprocess

import pytest

from src import transcriber
from src.transcriber import (
    TranscriptionCancelled,
    TranscriptionError,
    _fill_censored_words,
    _merge_windows,
    _offset_words,
    _transcribe_faster_whisper,
)


class TestMergeWindows:
    def test_single_start_gets_padded_window(self):
        assert _merge_windows([10.0], pad=4.0) == [(6.0, 14.0)]

    def test_window_start_clamped_at_zero(self):
        assert _merge_windows([1.0], pad=4.0) == [(0.0, 5.0)]

    def test_overlapping_windows_merge(self):
        # 10s and 15s with ±4s pad overlap (6-14 and 11-19) -> one window
        assert _merge_windows([10.0, 15.0], pad=4.0) == [(6.0, 19.0)]

    def test_distant_windows_stay_separate(self):
        assert _merge_windows([10.0, 100.0], pad=4.0) == [
            (6.0, 14.0),
            (96.0, 104.0),
        ]

    def test_unsorted_input_is_sorted(self):
        assert _merge_windows([100.0, 10.0], pad=4.0) == [
            (6.0, 14.0),
            (96.0, 104.0),
        ]

    def test_empty_input(self):
        assert _merge_windows([], pad=4.0) == []


class TestOffsetWords:
    def test_offsets_applied_per_snippet(self):
        word_lists = [
            [{"word": "hello", "start": 1.0, "end": 1.4, "confidence": 0.9}],
            [{"word": "world", "start": 0.5, "end": 0.8, "confidence": 0.8}],
        ]
        words = _offset_words(word_lists, [6.0, 96.0])
        assert words == [
            {"word": "hello", "start": 7.0, "end": 7.4, "confidence": 0.9},
            {"word": "world", "start": 96.5, "end": 96.8, "confidence": 0.8},
        ]

    def test_empty_lists(self):
        assert _offset_words([[], []], [0.0, 5.0]) == []


class TestSnippetFill:
    def _yt_words(self):
        return [
            {"word": "he", "start": 9.0, "end": 9.3, "confidence": 1.0},
            {"word": "said", "start": 9.4, "end": 9.7, "confidence": 1.0},
            {"word": "__CENSORED__", "start": 10.0, "end": 10.0, "confidence": 0.0},
            {"word": "loudly", "start": 10.5, "end": 10.9, "confidence": 1.0},
        ]

    def test_only_snippet_windows_are_extracted(self, monkeypatch):
        extracted = []

        def fake_extract(video_path, start, duration, log_fn=None):
            extracted.append((start, duration))
            return f"snippet_{start}.wav"

        def fake_whisper(snippets, log_fn=None, cancel_check=None):
            # one snippet covering the censored word, already offset to video time
            return [{"word": "damn", "start": 10.1, "end": 10.4, "confidence": 0.95}]

        monkeypatch.setattr(transcriber, "_extract_audio_snippet", fake_extract)
        monkeypatch.setattr(transcriber, "_transcribe_faster_whisper", fake_whisper)
        monkeypatch.setattr(transcriber.os, "unlink", lambda p: None)

        words = _fill_censored_words(self._yt_words(), "video.mp4")

        # only ONE small window around 10.0s, not the whole video
        assert extracted == [(6.0, 8.0)]
        filled = [w["word"] for w in words]
        assert filled == ["he", "said", "damn", "loudly"]

    def test_whisper_failure_keeps_captions_and_drops_placeholders(self, monkeypatch):
        def fake_extract(video_path, start, duration, log_fn=None):
            return "snippet.wav"

        def fake_whisper(snippets, log_fn=None, cancel_check=None):
            raise TranscriptionError("All whisper models failed")

        monkeypatch.setattr(transcriber, "_extract_audio_snippet", fake_extract)
        monkeypatch.setattr(transcriber, "_transcribe_faster_whisper", fake_whisper)
        monkeypatch.setattr(transcriber.os, "unlink", lambda p: None)

        words = _fill_censored_words(self._yt_words(), "video.mp4")

        # captions survive, placeholder silently dropped — no exception
        assert [w["word"] for w in words] == ["he", "said", "loudly"]

    def test_cancel_raises_before_any_extraction(self, monkeypatch):
        def fail_extract(*a, **kw):
            raise AssertionError("should not extract when cancelled")

        monkeypatch.setattr(transcriber, "_extract_audio_snippet", fail_extract)

        with pytest.raises(TranscriptionCancelled):
            _fill_censored_words(
                self._yt_words(), "video.mp4", cancel_check=lambda: True
            )


class _FakeProc:
    """A subprocess that never finishes until killed."""

    def __init__(self, *args, **kwargs):
        self.killed = False
        self.returncode = None

    def communicate(self, timeout=None):
        if self.killed:
            return ("", "")
        raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class TestWhisperCancel:
    def test_cancel_kills_subprocess(self, monkeypatch, tmp_path):
        procs = []

        def fake_popen(*args, **kwargs):
            proc = _FakeProc()
            procs.append(proc)
            return proc

        monkeypatch.setattr(transcriber.subprocess, "Popen", fake_popen)

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"")

        # cancel arrives only after the subprocess has launched
        cancelled = {"value": False}

        def cancel_check():
            if procs:  # subprocess is running -> user clicks cancel
                cancelled["value"] = True
            return cancelled["value"]

        with pytest.raises(TranscriptionCancelled):
            _transcribe_faster_whisper([(str(audio), 0.0)],
                                       cancel_check=cancel_check)

        assert len(procs) == 1
        assert procs[0].killed

    def test_cancel_checked_before_launch(self, monkeypatch, tmp_path):
        def fail_popen(*args, **kwargs):
            raise AssertionError("should not launch when already cancelled")

        monkeypatch.setattr(transcriber.subprocess, "Popen", fail_popen)

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"")

        with pytest.raises(TranscriptionCancelled):
            _transcribe_faster_whisper(
                [(str(audio), 0.0)], cancel_check=lambda: True
            )


class TestEmptyTranscription:
    def test_successful_worker_with_no_words_returns_empty_without_retry(
            self, monkeypatch, tmp_path):
        """A worker that exits 0 but hears no speech (bleeped/silent audio)
        must not waste minutes loading two more models — smaller models
        won't hear more."""
        attempts = []

        def fake_worker(cmd, cancel_check=None):
            attempts.append(cmd[2])  # model name argv
            out_path = cmd[-1]
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("[[]]")
            return 0, ""

        monkeypatch.setattr(transcriber, "_run_whisper_worker", fake_worker)

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"")

        words = _transcribe_faster_whisper([(str(audio), 0.0)])

        assert words == []
        assert len(attempts) == 1

    def test_unparseable_worker_output_tries_next_model(self, monkeypatch, tmp_path):
        attempts = []

        def fake_worker(cmd, cancel_check=None):
            attempts.append(cmd[2])
            with open(cmd[-1], "w", encoding="utf-8") as f:
                f.write("not json")
            return 0, ""

        monkeypatch.setattr(transcriber, "_run_whisper_worker", fake_worker)

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"")

        with pytest.raises(TranscriptionError):
            _transcribe_faster_whisper([(str(audio), 0.0)])
        assert len(attempts) == len(transcriber._WHISPER_MODELS)


    def test_full_video_empty_transcription_raises(self, monkeypatch):
        monkeypatch.setattr(transcriber, "_extract_audio", lambda *a, **kw: "a.wav")
        monkeypatch.setattr(transcriber, "_transcribe_parakeet",
                            lambda *a, **kw: (_ for _ in ()).throw(Exception("skip")))
        monkeypatch.setattr(transcriber, "_transcribe_faster_whisper",
                            lambda *a, **kw: [])
        monkeypatch.setattr(transcriber.os, "unlink", lambda p: None)

        with pytest.raises(TranscriptionError):
            transcriber.transcribe("video.mp4")


class TestTranscribeCancelPropagation:
    def test_cancel_does_not_fall_back_to_full_transcription(self, monkeypatch):
        def fake_fetch(url, log_fn=None):
            return (
                [{"word": "__CENSORED__", "start": 1.0, "end": 1.0,
                  "confidence": 0.0}],
                1,
            )

        def fake_fill(words, video_path, log_fn=None, cancel_check=None):
            raise TranscriptionCancelled("Cancelled by user.")

        def fail_extract(*a, **kw):
            raise AssertionError(
                "cancel must not fall back to full local transcription"
            )

        monkeypatch.setattr(transcriber, "_fetch_youtube_captions", fake_fetch)
        monkeypatch.setattr(transcriber, "_fill_censored_words", fake_fill)
        monkeypatch.setattr(transcriber, "_extract_audio", fail_extract)

        with pytest.raises(TranscriptionCancelled):
            transcriber.transcribe(
                "video.mp4", url="https://youtube.com/watch?v=x",
                cancel_check=lambda: True,
            )
