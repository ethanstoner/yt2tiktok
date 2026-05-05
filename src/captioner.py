import os
from pathlib import Path
from PIL import ImageFont

# Font priority: FredokaOne (rounded bubbly) > Montserrat > BubblegumSans > Roboto
_FONT_CANDIDATES = [
    Path(__file__).parent.parent / "fonts" / "FredokaOne-Regular.ttf",
    Path(__file__).parent.parent / "fonts" / "Montserrat-ExtraBold.ttf",
    Path(__file__).parent.parent / "fonts" / "BubblegumSans-Regular.ttf",
    Path(__file__).parent.parent / "fonts" / "RobotoCondensed-Bold.ttf",
]
CAPTION_FONT_PATH = ""
for _f in _FONT_CANDIDATES:
    if _f.is_file():
        CAPTION_FONT_PATH = str(_f)
        break

PRESETS = {
    "Opus Clean": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H0000FF00",  # bright green #00FF00 in BGR
        "outline_color": "&H00000000",
        "border": 7,
        "shadow": 2,
        "shadow_color": "&HA0000000",
        "fontsize": 72,
        "animation": "none",
        "uppercase": False,
        "bold": True,
        "tracking": 1,
        "active_scale": 110,
    },
    "Bold Pop": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H0000FF00",
        "outline_color": "&H00000000",
        "border": 8,
        "shadow": 3,
        "shadow_color": "&HA0000000",
        "fontsize": 68,
        "animation": "fade",
        "uppercase": False,
        "bold": True,
        "tracking": 1,
        "active_scale": 110,
    },
    "Neon Glow": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00FFFF00",  # cyan
        "outline_color": "&H00000000",
        "border": 7,
        "shadow": 5,
        "shadow_color": "&H60FFFF00",
        "fontsize": 66,
        "animation": "bounce",
        "uppercase": False,
        "bold": True,
        "tracking": 1,
        "active_scale": 110,
    },
    "Impact": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H001414FF",  # bright red
        "outline_color": "&H00000000",
        "border": 9,
        "shadow": 3,
        "shadow_color": "&HA0000000",
        "fontsize": 72,
        "animation": "slam",
        "uppercase": True,
        "bold": True,
        "tracking": 1,
        "active_scale": 120,
    },
    "Pastel": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00FF88FF",  # hot pink
        "outline_color": "&H00000000",
        "border": 7,
        "shadow": 2,
        "shadow_color": "&HA0000000",
        "fontsize": 64,
        "animation": "fade",
        "uppercase": False,
        "bold": True,
        "tracking": 1,
        "active_scale": 110,
    },
    "Minimal": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H0088DDFF",  # warm yellow
        "outline_color": "&H00000000",
        "border": 5,
        "shadow": 2,
        "shadow_color": "&HA0000000",
        "fontsize": 56,
        "animation": "fade",
        "uppercase": False,
        "bold": True,
        "tracking": 0,
        "active_scale": 100,
    },
}


def group_into_phrases(
    transcript: list[dict],
    gap_threshold: float = 0.40,
    max_duration: float = 3.2,
    frame_width: int = 1080,
    fontsize: int = 72,
) -> list[list[int]]:
    """Group transcript words into display phrases based on actual text width.

    No hard word count limit — short words like 'of' 'it' 'a' pack tightly,
    while long words like 'calibration' take more space. Purely width-driven.
    """
    if not transcript:
        return []

    font = _load_font(fontsize)
    max_text_px = int(frame_width * 0.88)

    def _phrase_text(indices):
        return " ".join(transcript[i]["word"] for i in indices)

    def _fits(indices):
        return _measure_text(_phrase_text(indices), font) <= max_text_px

    # First pass: group by timing and text width
    phrases = []
    current_phrase = [0]
    for i in range(1, len(transcript)):
        gap = transcript[i]["start"] - transcript[i - 1]["end"]
        phrase_start = transcript[current_phrase[0]]["start"]
        phrase_duration = transcript[i]["end"] - phrase_start
        candidate = current_phrase + [i]

        too_wide = not _fits(candidate)
        too_long = gap > gap_threshold or phrase_duration >= max_duration

        if too_wide or too_long:
            phrases.append(current_phrase)
            current_phrase = [i]
        else:
            current_phrase.append(i)
    if current_phrase:
        phrases.append(current_phrase)

    # Second pass: never leave single-word orphans
    if len(phrases) <= 1:
        return phrases

    merged = []
    i = 0
    while i < len(phrases):
        phrase = phrases[i]
        if len(phrase) == 1:
            if merged and _fits(merged[-1] + phrase):
                merged[-1] = merged[-1] + phrase
            elif i + 1 < len(phrases) and _fits(phrase + phrases[i + 1]):
                phrases[i + 1] = phrase + phrases[i + 1]
            elif merged:
                merged[-1] = merged[-1] + phrase
            else:
                merged.append(phrase)
        else:
            merged.append(phrase)
        i += 1

    return merged


def detect_keywords_heuristic(transcript: list[dict], max_per_phrase: int = 5) -> list[int]:
    indices = []
    for i, w in enumerate(transcript):
        word = w["word"]
        if len(word) >= 6 or word.isupper() or any(c.isdigit() for c in word):
            indices.append(i)
    return indices[:max_per_phrase * 10]


def detect_keywords_llm(transcript: list[dict], llm) -> list[int]:
    word_list = " ".join(f"{i}:{w['word']}" for i, w in enumerate(transcript))
    prompt = (
        "Pick the 3-5 most impactful or emotional words from this transcript "
        "that should be visually highlighted in a TikTok caption. "
        "Return ONLY the word indices as comma-separated numbers.\n\n"
        f"Words: {word_list}"
    )
    try:
        response = llm.complete(prompt)
        indices = [int(x.strip()) for x in response.split(",") if x.strip().isdigit()]
        return [i for i in indices if 0 <= i < len(transcript)]
    except Exception:
        return detect_keywords_heuristic(transcript)


def _ass_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _build_phrase_animation(preset: dict) -> str:
    anim = preset["animation"]
    if anim == "scale":
        return "\\fscx85\\fscy85\\t(0,120,\\fscx100\\fscy100)"
    elif anim == "bounce":
        return "\\fscx80\\fscy80\\t(0,100,\\fscx108\\fscy108)\\t(100,200,\\fscx100\\fscy100)"
    elif anim == "slam":
        return "\\fscx140\\fscy140\\t(0,100,\\fscx100\\fscy100)"
    elif anim == "fade":
        return "\\fad(200,0)"
    elif anim == "none":
        return ""
    return ""


def _load_font(size: int):
    try:
        return ImageFont.truetype(CAPTION_FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _measure_text(text: str, font) -> int:
    bbox = font.getbbox(text or "A")
    return bbox[2] - bbox[0]



def _build_phrase_events(
    transcript: list[dict],
    phrase_indices: list[int],
    preset: dict,
    center_x: int,
    y_pos: int,
    highlight_indices: list[int] = None,
) -> list[str]:
    """Build a single Dialogue event per phrase with per-word color highlights.

    Karaoke style: the active word snaps to highlight_color, then back to white.
    """
    anim_tag = _build_phrase_animation(preset)

    plain_words = [
        transcript[i]["word"].upper() if preset["uppercase"] else transcript[i]["word"]
        for i in phrase_indices
    ]

    phrase_start = transcript[phrase_indices[0]]["start"]
    phrase_end = transcript[phrase_indices[-1]]["end"]

    parts = []
    first_word = True
    for pos, global_idx in enumerate(phrase_indices):
        word = plain_words[pos]
        ws = transcript[global_idx]["start"] - phrase_start
        if pos + 1 < len(phrase_indices):
            we = transcript[phrase_indices[pos + 1]]["start"] - phrase_start
        else:
            we = transcript[global_idx]["end"] - phrase_start
        ws_ms = max(0, int(round(ws * 1000)))
        we_ms = max(ws_ms + 10, int(round(we * 1000)))

        tags = ""
        if first_word:
            tags += f"\\an5\\pos({center_x},{y_pos})"
            if anim_tag:
                tags += anim_tag
            first_word = False

        tags += f"\\c{preset['text_color']}"
        # Snap to highlight color instantly, then snap back
        tags += f"\\t({ws_ms},{ws_ms + 1},\\c{preset['highlight_color']})"
        tags += f"\\t({we_ms},{we_ms + 1},\\c{preset['text_color']})"

        parts.append("{" + tags + "}" + word)

    text = " ".join(parts)
    return [
        f"Dialogue: 0,{_ass_timestamp(phrase_start)},{_ass_timestamp(phrase_end)},Default,,0,0,0,,{text}"
    ]


def generate_caption_ass(
    transcript: list[dict],
    preset: str,
    y_position: float,
    highlight_indices: list[int],
    output_path: str,
    frame_width: int = 1080,
    frame_height: int = 1920,
) -> str:
    """Generate an ASS subtitle file for one clip.

    Hybrid approach for natural spacing + scale-pop highlights:
    - Layer 0: single Dialogue event per phrase with inline color transforms
    - Layer 1: per-word overlay for scale-pop (only the active word visible)
    """
    p = PRESETS.get(preset, PRESETS["Opus Clean"])
    phrases = group_into_phrases(transcript, frame_width=frame_width, fontsize=p["fontsize"])

    line_height = p["fontsize"] + int(p["fontsize"] * 0.30)
    y_pos = int(y_position * frame_height)
    # Allow captions from mid-frame down into the lower blurred bar zone
    y_min = int(frame_height * 0.40)
    y_max = int(frame_height * 0.85)
    y_pos = max(y_min, min(y_max, y_pos))
    # Use the font's internal family name (libass matches on this, not filename)
    try:
        _font_meta = ImageFont.truetype(CAPTION_FONT_PATH, 10)
        fontname = _font_meta.getname()[0]
    except Exception:
        fontname = Path(CAPTION_FONT_PATH).stem

    bold_flag = -1 if p["bold"] else 0
    center_x = frame_width // 2

    header = f"""[Script Info]
Title: yt2tiktok captions
ScriptType: v4.00+
PlayResX: {frame_width}
PlayResY: {frame_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fontname},{p['fontsize']},{p['text_color']},&H000000FF,{p['outline_color']},{p['shadow_color']},{bold_flag},0,0,0,100,100,0,0,1,{p['border']},{p['shadow']},5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    for phrase_indices in phrases:
        if not phrase_indices:
            continue

        phrase_events = _build_phrase_events(
            transcript, phrase_indices, p, center_x, y_pos,
            highlight_indices=highlight_indices,
        )
        events.extend(phrase_events)

    ass_content = header + "\n".join(events) + "\n"

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    return output_path


def slice_transcript(
    full_transcript: list[dict],
    cut_start: float,
    cut_end: float,
    highlight_indices: list[int],
) -> tuple[list[dict], list[int]]:
    clip_words = []
    old_to_new = {}
    for i, w in enumerate(full_transcript):
        if w["start"] >= cut_start and w["end"] <= cut_end:
            new_idx = len(clip_words)
            old_to_new[i] = new_idx
            clip_words.append({
                "word": w["word"],
                "start": round(w["start"] - cut_start, 3),
                "end": round(w["end"] - cut_start, 3),
                "confidence": w["confidence"],
            })
    clip_highlights = [old_to_new[i] for i in highlight_indices if i in old_to_new]
    return clip_words, clip_highlights
