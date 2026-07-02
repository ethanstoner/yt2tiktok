import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FFMPEG_CMD = shutil.which("ffmpeg")

_WHISPER_MODELS = ["large-v3-turbo", "medium", "base"]
_WHISPER_TIMEOUT = 600
# Seconds of audio to grab on each side of a censored word so whisper
# hears the surrounding sentence for context.
SNIPPET_PAD = 4.0


class TranscriptionError(Exception):
    pass


class TranscriptionCancelled(TranscriptionError):
    pass


def _check_cancel(cancel_check):
    if cancel_check and cancel_check():
        raise TranscriptionCancelled("Cancelled by user.")


def _extract_audio(video_path: str, log_fn=None) -> str:
    if FFMPEG_CMD is None:
        raise TranscriptionError("ffmpeg not found in PATH. Install FFmpeg.")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        FFMPEG_CMD, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        tmp.name,
    ]
    if log_fn:
        log_fn("Extracting audio...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        os.unlink(tmp.name)
        raise TranscriptionError(f"Audio extraction failed: {result.stderr[:200]}")
    return tmp.name


def _extract_audio_snippet(video_path: str, start: float, duration: float,
                           log_fn=None) -> str:
    """Extract a small span of audio instead of the whole track."""
    if FFMPEG_CMD is None:
        raise TranscriptionError("ffmpeg not found in PATH. Install FFmpeg.")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        FFMPEG_CMD, "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        tmp.name,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        os.unlink(tmp.name)
        raise TranscriptionError(f"Audio snippet extraction failed: {result.stderr[:200]}")
    return tmp.name


def _merge_windows(starts: list[float], pad: float = SNIPPET_PAD) -> list[tuple[float, float]]:
    """Turn censored-word timestamps into merged (start, end) audio windows."""
    windows = []
    for s in sorted(starts):
        lo, hi = max(0.0, s - pad), s + pad
        if windows and lo <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], hi))
        else:
            windows.append((lo, hi))
    return windows


def _offset_words(word_lists: list[list[dict]], offsets: list[float]) -> list[dict]:
    """Shift per-snippet whisper timestamps back into video time."""
    words = []
    for snippet_words, offset in zip(word_lists, offsets):
        for w in snippet_words:
            words.append({
                "word": w["word"],
                "start": round(w["start"] + offset, 3),
                "end": round(w["end"] + offset, 3),
                "confidence": w["confidence"],
            })
    return words


# The worker takes a JSON manifest of audio paths so one subprocess (one
# model load) can transcribe every snippet. It emits a list-of-lists in
# manifest order; the parent shifts timestamps back to video time.
_WORKER_SCRIPT = '''
import json, sys
from faster_whisper import WhisperModel
model_name, manifest_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(manifest_path, "r", encoding="utf-8") as f:
    audio_paths = json.load(f)
model = WhisperModel(model_name, device="auto", compute_type="auto")
results = []
for audio_path in audio_paths:
    segments, _ = model.transcribe(audio_path, word_timestamps=True)
    words = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                words.append({"word": w.word.strip(), "start": round(w.start, 3),
                              "end": round(w.end, 3), "confidence": round(w.probability, 3)})
    results.append(words)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f)
'''


def _run_whisper_worker(cmd: list[str], cancel_check=None):
    """Run a whisper subprocess, killing it if the user cancels.

    Returns (returncode, stderr). Raises TranscriptionCancelled on cancel
    and subprocess.TimeoutExpired past _WHISPER_TIMEOUT.
    """
    _check_cancel(cancel_check)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + _WHISPER_TIMEOUT
    while True:
        if cancel_check and cancel_check():
            proc.kill()
            proc.wait()
            raise TranscriptionCancelled("Cancelled by user.")
        try:
            _, stderr = proc.communicate(timeout=0.5)
            return proc.returncode, stderr
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                proc.kill()
                proc.wait()
                raise


def _transcribe_faster_whisper(snippets: list[tuple[str, float]], log_fn=None,
                               cancel_check=None) -> list[dict]:
    """Transcribe audio snippets, trying whisper models largest-first in
    isolated subprocesses.

    `snippets` is a list of (audio_path, video_time_offset) pairs — pass
    [(full_audio, 0.0)] to transcribe a whole video. If a model OOMs, the
    subprocess dies but the parent survives and tries the next smaller
    model. cancel_check kills the running subprocess when it returns True.
    """
    python = sys.executable
    offsets = [off for _, off in snippets]

    out_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_file.close()
    manifest_file = tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8")
    json.dump([path for path, _ in snippets], manifest_file)
    manifest_file.close()

    try:
        for model_name in _WHISPER_MODELS:
            _check_cancel(cancel_check)
            if log_fn:
                log_fn(f"Trying faster-whisper ({model_name})...")

            # Write the worker script to a temp file
            script_file = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8")
            script_file.write(_WORKER_SCRIPT)
            script_file.close()

            try:
                returncode, stderr = _run_whisper_worker(
                    [python, script_file.name, model_name,
                     manifest_file.name, out_file.name],
                    cancel_check=cancel_check,
                )

                if returncode == 0 and os.path.exists(out_file.name):
                    results = None
                    try:
                        with open(out_file.name, "r", encoding="utf-8") as f:
                            results = json.load(f)
                    except ValueError:
                        pass  # corrupt output: treat as model failure below
                    if isinstance(results, list):
                        # Worker succeeded — return even if it heard no
                        # words (bleeped/silent audio): a smaller model
                        # won't hear more, so retrying just wastes two
                        # model loads.
                        words = _offset_words(results, offsets)
                        if log_fn:
                            log_fn(f"Transcribed {len(words)} words using {model_name}")
                        return words

                if log_fn:
                    reason = stderr.strip()[-200:] if stderr else f"exit code {returncode}"
                    log_fn(f"{model_name} failed ({reason}), trying smaller model...")

            except subprocess.TimeoutExpired:
                if log_fn:
                    log_fn(f"{model_name} timed out, trying smaller model...")
            finally:
                try:
                    os.unlink(script_file.name)
                except OSError:
                    pass

        raise TranscriptionError("All whisper models failed")
    finally:
        for p in (out_file.name, manifest_file.name):
            try:
                os.unlink(p)
            except OSError:
                pass


def _transcribe_parakeet(audio_path: str, log_fn=None) -> list[dict]:
    import nemo.collections.asr as nemo_asr

    if log_fn:
        log_fn("Loading Parakeet TDT 1.1B...")
    model = nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-1.1b")

    if log_fn:
        log_fn("Transcribing with Parakeet...")
    output = model.transcribe([audio_path], return_hypotheses=True)

    words = []
    if output and len(output) > 0:
        hyp = output[0][0] if isinstance(output[0], list) else output[0]
        if hasattr(hyp, "timestep") and hyp.timestep:
            for ts in hyp.timestep.get("word", []):
                words.append({
                    "word": ts.get("word", "").strip(),
                    "start": round(ts.get("start_offset", 0), 3),
                    "end": round(ts.get("end_offset", 0), 3),
                    "confidence": round(ts.get("confidence", 0.0), 3),
                })
    if not words:
        raise TranscriptionError("Parakeet returned no word timestamps")
    return words


def _fetch_youtube_captions(url: str, log_fn=None) -> list[dict]:
    """Download word-level timestamps from YouTube's auto-captions (JSON3 format)."""
    import yt_dlp
    import urllib.request

    if log_fn:
        log_fn("Fetching YouTube captions...")

    ydl_opts = {"quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Prefer manual subs, fall back to auto
    subs = info.get("subtitles", {})
    auto_subs = info.get("automatic_captions", {})
    en_subs = subs.get("en", []) or auto_subs.get("en", [])

    json3_url = None
    for s in en_subs:
        if s.get("ext") == "json3":
            json3_url = s["url"]
            break

    if not json3_url:
        raise TranscriptionError("No English captions available")

    with urllib.request.urlopen(json3_url, timeout=30) as resp:
        data = json.loads(resp.read())
    events = data.get("events", [])

    import re
    _CENSORED_PLACEHOLDER = "__CENSORED__"
    words = []
    for ev in events:
        segs = ev.get("segs")
        if not segs:
            continue
        base_ms = ev.get("tStartMs", 0)
        dur_ms = ev.get("dDurationMs", 0)
        for seg in segs:
            text = seg.get("utf8", "").strip()
            if not text or text == "\n":
                continue
            offset_ms = seg.get("tOffsetMs", 0)
            start_ms = base_ms + offset_ms
            start_s = round(start_ms / 1000, 3)
            # Detect YouTube censorship (e.g. [__]) — mark for whisper fill-in
            if re.search(r"\[[\W_]+\]", text):
                words.append({
                    "word": _CENSORED_PLACEHOLDER,
                    "start": start_s,
                    "end": start_s,
                    "confidence": 0.0,
                })
                continue
            # Clean up YouTube caption artifacts
            text = re.sub(r"^>>+\s*", "", text).strip()
            text = re.sub(r"\[.*?\]", "", text).strip()  # [music] [applause] etc
            if not text:
                continue
            words.append({
                "word": text,
                "start": start_s,
                "end": start_s,  # placeholder, will fix below
                "confidence": 1.0,
            })

    # Fix end times: each word ends when the next one starts, capped at 1.5s
    for i in range(len(words) - 1):
        next_start = words[i + 1]["start"]
        words[i]["end"] = round(min(next_start, words[i]["start"] + 1.5), 3)
    if words:
        words[-1]["end"] = round(words[-1]["start"] + 0.3, 3)

    # Filter out empty words (but keep censored placeholders)
    words = [w for w in words if w["word"]]

    if not words:
        raise TranscriptionError("YouTube captions had no usable words")

    censored_count = sum(1 for w in words if w["word"] == _CENSORED_PLACEHOLDER)
    if log_fn:
        log_fn(f"Got {len(words)} words from YouTube captions" +
               (f" ({censored_count} censored)" if censored_count else ""))

    return words, censored_count


def _fill_censored_words(yt_words: list[dict], video_path: str, log_fn=None,
                         cancel_check=None) -> list[dict]:
    """Replace censored placeholders in YouTube captions with whisper transcriptions.

    Only the few seconds of audio around each censored word are extracted
    and transcribed — not the whole video."""
    censored = [w for w in yt_words if w["word"] == "__CENSORED__"]
    if not censored:
        return yt_words

    _check_cancel(cancel_check)

    windows = _merge_windows([w["start"] for w in censored])
    total_audio = sum(end - start for start, end in windows)
    if log_fn:
        log_fn(f"Filling {len(censored)} censored word(s): transcribing "
               f"{len(windows)} snippet(s) (~{total_audio:.0f}s of audio)...")

    snippet_paths = []
    try:
        snippets = []
        for start, end in windows:
            _check_cancel(cancel_check)
            path = _extract_audio_snippet(video_path, start, end - start, log_fn)
            snippet_paths.append(path)
            snippets.append((path, start))
        whisper_words = _transcribe_faster_whisper(
            snippets, log_fn, cancel_check=cancel_check)
    except TranscriptionCancelled:
        raise
    except TranscriptionError as e:
        # Whisper fill-in is best-effort: keep the captions and drop the
        # placeholders rather than failing over to a full local transcription.
        if log_fn:
            log_fn(f"Whisper fill-in failed ({e}); leaving censored words out.")
        whisper_words = []
    finally:
        for p in snippet_paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    # For each censored slot, find the closest whisper word by timestamp
    for cw in censored:
        best_match = None
        best_dist = float("inf")
        for ww in whisper_words:
            dist = abs(ww["start"] - cw["start"])
            if dist < best_dist:
                best_dist = dist
                best_match = ww
        if best_match and best_dist < 2.0:
            cw["word"] = best_match["word"]
            cw["confidence"] = best_match["confidence"]
            if log_fn:
                log_fn(f"  Filled censored word at {cw['start']:.1f}s -> \"{best_match['word']}\"")
        else:
            # No match found, remove the placeholder
            cw["word"] = ""

    # Filter out any remaining empty entries
    return [w for w in yt_words if w["word"] and w["word"] != "__CENSORED__"]


def transcribe(video_path: str, url: str = None, log_fn=None,
               cancel_check=None) -> list[dict]:
    # Try YouTube captions first (most accurate, no local compute)
    if url:
        try:
            words, censored_count = _fetch_youtube_captions(url, log_fn)
            if censored_count > 0:
                words = _fill_censored_words(words, video_path, log_fn,
                                             cancel_check=cancel_check)
            if log_fn:
                log_fn(f"Transcription complete: {len(words)} words (YouTube captions" +
                       (" + whisper fill-in)" if censored_count else ")"))
            return words
        except TranscriptionCancelled:
            raise
        except Exception as e:
            if log_fn:
                log_fn(f"YouTube captions unavailable ({e}), using local transcription...")

    _check_cancel(cancel_check)
    audio_path = _extract_audio(video_path, log_fn)

    try:
        try:
            import torch
            if torch.cuda.is_available():
                import nemo.collections.asr  # noqa: F401
                words = _transcribe_parakeet(audio_path, log_fn)
                if log_fn:
                    log_fn(f"Transcription complete: {len(words)} words (Parakeet)")
                return words
        except ImportError:
            pass
        except Exception as e:
            if log_fn:
                log_fn(f"Parakeet failed, falling back to faster-whisper: {e}")

        words = _transcribe_faster_whisper([(audio_path, 0.0)], log_fn,
                                           cancel_check=cancel_check)
        if not words:
            raise TranscriptionError("Transcription produced no words")
        return words

    finally:
        try:
            os.unlink(audio_path)
        except OSError:
            pass
