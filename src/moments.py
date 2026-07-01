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


def _extract_json(text: str, kind: type):
    """Extract a JSON list or dict from LLM output that may include
    code fences or surrounding prose. kind is list or dict."""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    open_ch, close_ch = ("[", "]") if kind is list else ("{", "}")
    s, e = text.find(open_ch), text.rfind(close_ch)
    if s == -1 or e <= s:
        raise ValueError(f"No JSON {kind.__name__} found in LLM response.")
    parsed = json.loads(text[s:e + 1])
    if not isinstance(parsed, kind):
        raise ValueError(f"Expected JSON {kind.__name__}.")
    return parsed


_CANDIDATE_PROMPT = """You are selecting the most viral-worthy moments from a video transcript to sell as TikTok/YouTube Shorts clips.

Below is a word-indexed transcript segment (format index:word, with [t=Ns] time markers).

Find up to {max_candidates} self-contained moments that would perform as standalone short clips: strong hook in the first seconds, emotional peak, punchline, hot take, surprising fact, or a complete mini-story with payoff.

Rules:
- Each moment must be {min_dur:.0f} to {max_dur:.0f} seconds long (use the [t=Ns] markers to judge duration).
- start_idx must land on a natural sentence beginning; end_idx on a natural stopping point.
- score is 0-100 predicted virality. Be selective: mediocre moments score below 50.
- hook_title: max 8 words, punchy, curiosity-driving. reason: one sentence.

Return ONLY a JSON array, no other text:
[{{"start_idx": int, "end_idx": int, "score": int, "hook_title": "...", "reason": "..."}}]

Words:
{words}"""

_RETRY_SUFFIX = "\n\nYour previous reply was not valid JSON. Respond with ONLY the JSON array — no prose, no code fences."


def _format_window(window: list[dict]) -> str:
    parts = []
    for i, w in enumerate(window):
        if i % 15 == 0:
            parts.append(f"[t={int(w['start'])}s]")
        parts.append(f"{i}:{w['word']}")
    return " ".join(parts)


def _candidates_for_window(
    window: list[dict], llm, min_dur: float, max_dur: float, log_fn=None,
) -> list[Moment]:
    prompt = _CANDIDATE_PROMPT.format(
        max_candidates=MAX_CANDIDATES_PER_WINDOW,
        min_dur=min_dur, max_dur=max_dur,
        words=_format_window(window),
    )
    raw = None
    for attempt, p in enumerate([prompt, prompt + _RETRY_SUFFIX]):
        try:
            response = llm.complete(p, max_tokens=LLM_MAX_TOKENS, timeout=LLM_TIMEOUT)
            raw = _extract_json(response, list)
            break
        except Exception as e:
            if log_fn:
                log_fn(f"Moment candidate pass attempt {attempt + 1} failed: {e}")
    if raw is None:
        return []

    moments = []
    for c in raw:
        try:
            si, ei = int(c["start_idx"]), int(c["end_idx"])
            score = int(c["score"])
            hook, reason = str(c["hook_title"]), str(c["reason"])
        except (KeyError, TypeError, ValueError):
            if log_fn:
                log_fn(f"Dropping malformed candidate: {c!r}")
            continue
        if not (0 <= si < ei < len(window)):
            if log_fn:
                log_fn(f"Dropping out-of-range candidate {si}-{ei}")
            continue
        start, end = window[si]["start"], window[ei]["end"]
        dur = end - start
        if not (min_dur <= dur <= max_dur):
            if log_fn:
                log_fn(f"Dropping candidate with duration {dur:.0f}s (bounds {min_dur:.0f}-{max_dur:.0f}s)")
            continue
        moments.append(Moment(start=start, end=end, score=score,
                              hook_title=hook, reason=reason))
    return moments


def dedupe_candidates(candidates: list[Moment]) -> list[Moment]:
    """Merge candidates whose time ranges overlap >= 50% of the shorter
    one, keeping the higher-scored. Result sorted by start time."""
    survivors: list[Moment] = []
    for cand in sorted(candidates, key=lambda m: -m.score):
        clash = False
        for kept in survivors:
            overlap = min(cand.end, kept.end) - max(cand.start, kept.start)
            shorter = min(cand.end - cand.start, kept.end - kept.start)
            if shorter > 0 and overlap / shorter >= 0.5:
                clash = True
                break
        if not clash:
            survivors.append(cand)
    return sorted(survivors, key=lambda m: m.start)
