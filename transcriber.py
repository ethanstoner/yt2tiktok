import os
import shutil
import subprocess
import tempfile
from pathlib import Path

FFMPEG_CMD = shutil.which("ffmpeg")


class TranscriptionError(Exception):
    pass


def _extract_audio(video_path: str, log_fn=None) -> str:
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


_WHISPER_MODELS = ["large-v3-turbo", "medium", "base"]


def _transcribe_faster_whisper(audio_path: str, log_fn=None) -> list[dict]:
    from faster_whisper import WhisperModel

    for model_name in _WHISPER_MODELS:
        try:
            if log_fn:
                log_fn(f"Loading faster-whisper ({model_name})...")
            model = WhisperModel(model_name, device="auto", compute_type="auto")

            if log_fn:
                log_fn("Transcribing...")
            segments, _ = model.transcribe(audio_path, word_timestamps=True)

            words = []
            for segment in segments:
                if segment.words:
                    for w in segment.words:
                        words.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                            "confidence": round(w.probability, 3),
                        })

            if words:
                if log_fn:
                    log_fn(f"Transcribed {len(words)} words using {model_name}")
                return words
        except (MemoryError, RuntimeError) as e:
            if log_fn:
                log_fn(f"{model_name} failed ({e}), trying smaller model...")
            del model
            continue
        except Exception as e:
            if log_fn:
                log_fn(f"{model_name} failed ({e}), trying smaller model...")
            continue

    raise TranscriptionError("All whisper models failed")


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


def transcribe(video_path: str, log_fn=None) -> list[dict]:
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
        if log_fn:
            log_fn(f"Transcription complete: {len(words)} words (faster-whisper)")
        return words

    finally:
        try:
            os.unlink(audio_path)
        except OSError:
            pass
