"""Best Moments selection: two-pass LLM extraction of viral-worthy clips.

Pure functions only — no UI imports. The worker converts the returned
Moment objects to (start, duration) tuples for clipper.split_video.
"""
import json
import re
from dataclasses import dataclass, field

WINDOW_SECONDS = 600.0
OVERLAP_SECONDS = 60.0
MAX_CANDIDATES_PER_WINDOW = 6
SNAP_WINDOW = 2.0
MIN_GAP = 0.15
PRE_ROLL = 0.3
LLM_TIMEOUT = 90
LLM_MAX_TOKENS = 2048


class MomentsError(Exception):
    pass


@dataclass
class Moment:
    start: float
    end: float
    score: int
    hook_title: str
    reason: str
    caption: str = ""


def chunk_transcript(
    transcript: list[dict],
    window_seconds: float = WINDOW_SECONDS,
    overlap_seconds: float = OVERLAP_SECONDS,
) -> list[list[dict]]:
    """Split a word-level transcript into overlapping time windows."""
    if not transcript:
        raise MomentsError("Transcript is empty.")
    total_end = transcript[-1]["end"]
    if total_end <= window_seconds:
        return [transcript]
    windows = []
    start = 0.0
    while start < total_end:
        end = start + window_seconds
        win = [w for w in transcript if w["start"] >= start and w["start"] < end]
        if win:
            windows.append(win)
        if end >= total_end:
            break
        start = end - overlap_seconds
    return windows
