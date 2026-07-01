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
    if overlap_seconds >= window_seconds:
        raise MomentsError("overlap_seconds must be smaller than window_seconds.")
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
    if log_fn:
        log_fn(f"Window prompt ~{len(prompt) // 4} tokens")
    raw = _llm_json(llm, prompt, list, log_fn)
    if raw is None:
        return []

    moments = []
    for c in raw:
        try:
            si, ei = int(c["start_idx"]), int(c["end_idx"])
            score = max(0, min(100, int(c["score"])))
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


_RANKING_PROMPT = """You are picking the {count} best short-form clips to sell to a YouTuber from these candidate moments.

Candidates:
{candidates}

Rank by: hook strength in the first 3 seconds, emotional payoff, and whether the moment is fully self-contained (no missing context). Return ONLY JSON, best first:
{{"top": [candidate indices]}}"""

_CAPTION_PROMPT = """Write a TikTok/YouTube Shorts post caption for each clip below: 1-2 punchy sentences that create curiosity, then 3-5 relevant hashtags. Some clips include a transcript excerpt — use it to make the caption specific.

Clips:
{clips}

Return ONLY a JSON array:
[{{"index": int, "caption": "..."}}]"""


def _llm_json(llm, prompt: str, kind: type, log_fn=None):
    """One LLM call with a single stricter retry; returns parsed JSON or None."""
    for attempt, p in enumerate([prompt, prompt + _RETRY_SUFFIX]):
        try:
            return _extract_json(
                llm.complete(p, max_tokens=LLM_MAX_TOKENS, timeout=LLM_TIMEOUT), kind)
        except Exception as e:
            if log_fn:
                log_fn(f"LLM JSON call attempt {attempt + 1} failed: {e}")
    return None


def _rank_and_caption(candidates: list[Moment], llm, count: int, log_fn=None,
                      transcript: list[dict] | None = None) -> list[Moment]:
    """Pick the top `count` candidates via one ranking call, then generate
    captions for only the winners. Falls back to score order if ranking
    fails; captions stay empty if caption generation fails."""
    lines = [
        f'{i}. [score {m.score}, {m.end - m.start:.0f}s] "{m.hook_title}" — {m.reason}'
        for i, m in enumerate(candidates)
    ]
    parsed = _llm_json(llm, _RANKING_PROMPT.format(count=count, candidates="\n".join(lines)),
                       dict, log_fn)
    order: list[int] = []
    if parsed and isinstance(parsed.get("top"), list):
        for i in parsed["top"]:
            # Accept int or float indices (llama models emit 2.0), never bool.
            if isinstance(i, bool) or not isinstance(i, (int, float)):
                continue
            idx = int(i)
            if 0 <= idx < len(candidates) and idx not in order:
                order.append(idx)
    if not order and log_fn:
        log_fn("Ranking pass failed; falling back to score order.")
    # Pad partial/invalid rankings with the remaining candidates in
    # score-descending order so we never under-deliver clips.
    remaining = sorted((i for i in range(len(candidates)) if i not in order),
                       key=lambda i: -candidates[i].score)
    while len(order) < min(count, len(candidates)) and remaining:
        order.append(remaining.pop(0))
    winners = [candidates[i] for i in order[:count]]

    clip_lines = []
    for i, m in enumerate(winners):
        line = f'{i}. "{m.hook_title}" — {m.reason}'
        if transcript is not None:
            excerpt = [w["word"] for w in transcript
                       if m.start <= w["start"] < m.end][:40]
            if excerpt:
                line += "\n   Excerpt: " + " ".join(excerpt)
        clip_lines.append(line)
    captions = _llm_json(llm, _CAPTION_PROMPT.format(clips="\n".join(clip_lines)),
                         list, log_fn)
    if captions:
        for entry in captions:
            try:
                idx, text = int(entry["index"]), str(entry["caption"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= idx < len(winners):
                winners[idx].caption = text
    return winners


def _nearest_gap_mid(transcript: list[dict], t: float) -> float | None:
    """Midpoint of the silence gap (>= MIN_GAP) whose midpoint is closest
    to t, within SNAP_WINDOW. None if no qualifying gap."""
    best_mid, best_dist = None, SNAP_WINDOW
    for a, b in zip(transcript, transcript[1:]):
        gap = b["start"] - a["end"]
        if gap < MIN_GAP:
            continue
        mid = (a["end"] + b["start"]) / 2
        dist = abs(mid - t)
        if dist <= best_dist:
            best_mid, best_dist = mid, dist
    return best_mid


def snap_moment(start: float, end: float, transcript: list[dict]) -> tuple[float, float]:
    """Shift boundaries to nearby silence gaps, then back the start up
    slightly before the first word so the hook is never clipped."""
    s = _nearest_gap_mid(transcript, start)
    e = _nearest_gap_mid(transcript, end)
    if s is not None:
        start = s
    if e is not None:
        end = e
    first = next((w for w in transcript if w["start"] >= start), None)
    if first is not None and first["start"] < end:
        start = max(0.0, first["start"] - PRE_ROLL)
    return start, end


def find_best_moments(
    transcript: list[dict],
    llm,
    count: int = 5,
    min_dur: float = 20.0,
    max_dur: float = 90.0,
    log_fn=None,
    cancel_check=None,
) -> list[Moment]:
    """Two-pass LLM moment selection. Returns winners in rank order
    (best first), boundaries snapped. Raises MomentsError if nothing
    viable is found.

    cancel_check: optional zero-arg callable returning True to abort;
    checked between LLM calls (each can take up to 90s). Raises
    MomentsError("Cancelled by user.") when it fires."""
    def _check_cancel():
        if cancel_check is not None and cancel_check():
            raise MomentsError("Cancelled by user.")

    windows = chunk_transcript(transcript)
    if log_fn:
        log_fn(f"Scanning {len(windows)} transcript window(s) for viral moments...")
    candidates: list[Moment] = []
    for wi, window in enumerate(windows, 1):
        _check_cancel()
        found = _candidates_for_window(window, llm, min_dur, max_dur, log_fn)
        if log_fn:
            log_fn(f"Window {wi}/{len(windows)}: {len(found)} candidate(s)")
        candidates.extend(found)
    _check_cancel()
    if not candidates:
        raise MomentsError(
            "The LLM found no viable moments. Try widening the duration "
            "range or check that the video has spoken content. If you are "
            "using a small-context local model (e.g. Ollama llama3.1:8b "
            "with a 4k context), it may silently truncate the 10-minute "
            "transcript windows — try a larger-context model.")
    candidates = dedupe_candidates(candidates)
    if log_fn:
        log_fn(f"{len(candidates)} candidates after dedup; ranking...")
    winners = _rank_and_caption(candidates, llm, count, log_fn, transcript=transcript)
    for m in winners:
        s, e = snap_moment(m.start, m.end, transcript)
        # Keep the snap only if it doesn't push the clip outside the
        # requested duration bounds; otherwise revert to raw boundaries.
        if min_dur <= e - s <= max_dur:
            m.start, m.end = s, e
    return winners


def write_deliverables(moments: list[Moment], title: str, target_dir: str):
    """Write moments.json (machine-readable) and report.md (client-facing)
    next to the clips. Clip filenames follow clipper's convention."""
    import os
    entries = []
    for i, m in enumerate(moments, 1):
        entries.append({
            "file": f"{title}_clip_{i}.mp4",
            "start": round(m.start, 2),
            "end": round(m.end, 2),
            "duration": round(m.end - m.start, 2),
            "score": m.score,
            "hook_title": m.hook_title,
            "reason": m.reason,
            "caption": m.caption,
        })
    with open(os.path.join(target_dir, "moments.json"), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    lines = [f"# Best Moments Report — {title}", ""]
    for i, e in enumerate(entries, 1):
        h_s, rem_s = divmod(int(e["start"]), 3600)
        mm_s, ss_s = divmod(rem_s, 60)
        ts = f"{h_s}:{mm_s:02d}:{ss_s:02d}" if h_s else f"{mm_s}:{ss_s:02d}"
        lines += [
            f"## Clip {i}: {e['hook_title']}",
            "",
            f"- **File:** `{e['file']}`",
            f"- **Source timestamp:** {ts} ({e['duration']:.0f}s)",
            f"- **Virality score:** {e['score']}/100",
            f"- **Why this clip:** {e['reason']}",
            "",
            "**Ready-to-paste caption:**",
            "",
            f"> {e['caption']}" if e["caption"] else "> (caption generation unavailable)",
            "",
        ]
    with open(os.path.join(target_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
