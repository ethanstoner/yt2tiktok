import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG_CMD = shutil.which("ffmpeg")

_WHISPER_MODELS = ["large-v3-turbo", "medium", "base"]


class TranscriptionError(Exception):
    pass


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


_WORKER_SCRIPT = '''
import json, sys
from faster_whisper import WhisperModel
model_name, audio_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
model = WhisperModel(model_name, device="auto", compute_type="auto")
segments, _ = model.transcribe(audio_path, word_timestamps=True)
words = []
for seg in segments:
    if seg.words:
        for w in seg.words:
            words.append({"word": w.word.strip(), "start": round(w.start, 3),
                          "end": round(w.end, 3), "confidence": round(w.probability, 3)})
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(words, f)
'''


def _transcribe_faster_whisper(audio_path: str, log_fn=None) -> list[dict]:
    """Try whisper models largest-first in isolated subprocesses.

    If a model OOMs, the subprocess dies but the parent survives
    and tries the next smaller model.
    """
    python = sys.executable
    out_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_file.close()

    try:
        for model_name in _WHISPER_MODELS:
            if log_fn:
                log_fn(f"Trying faster-whisper ({model_name})...")

            # Write the worker script to a temp file
            script_file = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8")
            script_file.write(_WORKER_SCRIPT)
            script_file.close()

            try:
                result = subprocess.run(
                    [python, script_file.name, model_name, audio_path, out_file.name],
                    capture_output=True, text=True, timeout=600,
                )

                if result.returncode == 0 and os.path.exists(out_file.name):
                    with open(out_file.name, "r", encoding="utf-8") as f:
                        words = json.load(f)
                    if words:
                        if log_fn:
                            log_fn(f"Transcribed {len(words)} words using {model_name}")
                        return words

                if log_fn:
                    reason = result.stderr.strip()[-200:] if result.stderr else f"exit code {result.returncode}"
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
        try:
            os.unlink(out_file.name)
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


def _fill_censored_words(yt_words: list[dict], video_path: str, log_fn=None) -> list[dict]:
    """Replace censored placeholders in YouTube captions with whisper transcriptions."""
    censored = [w for w in yt_words if w["word"] == "__CENSORED__"]
    if not censored:
        return yt_words

    if log_fn:
        log_fn(f"Filling {len(censored)} censored word(s) with local transcription...")

    # Run whisper to get uncensored words
    audio_path = _extract_audio(video_path, log_fn)
    try:
        whisper_words = _transcribe_faster_whisper(audio_path, log_fn)
    finally:
        try:
            os.unlink(audio_path)
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


def transcribe(video_path: str, url: str = None, log_fn=None) -> list[dict]:
    # Try YouTube captions first (most accurate, no local compute)
    if url:
        try:
            words, censored_count = _fetch_youtube_captions(url, log_fn)
            if censored_count > 0:
                words = _fill_censored_words(words, video_path, log_fn)
            if log_fn:
                log_fn(f"Transcription complete: {len(words)} words (YouTube captions" +
                       (" + whisper fill-in)" if censored_count else ")"))
            return words
        except Exception as e:
            if log_fn:
                log_fn(f"YouTube captions unavailable ({e}), using local transcription...")

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

        words = _transcribe_faster_whisper(audio_path, log_fn)
        return words

    finally:
        try:
            os.unlink(audio_path)
        except OSError:
            pass
