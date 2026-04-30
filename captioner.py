import os
from pathlib import Path
from PIL import ImageFont

CAPTION_FONT_PATH = str(Path(__file__).parent / "fonts" / "RobotoCondensed-Bold.ttf")
if not os.path.isfile(CAPTION_FONT_PATH):
    CAPTION_FONT_PATH = str(Path(__file__).parent / "fonts" / "BubblegumSans-Regular.ttf")

PRESETS = {
    "Opus Clean": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H0057FF78",  # mint green #78FF57 in BGR
        "outline_color": "&H00000000",
        "border": 6,
        "shadow": 1,
        "shadow_color": "&H90000000",
        "fontsize": 62,
        "animation": "none",
        "uppercase": False,
        "bold": True,
        "tracking": 0,
        "active_scale": 125,
    },
    "Bold Pop": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H0057FF78",  # mint green #78FF57 in BGR
        "outline_color": "&H00000000",
        "border": 8,
        "shadow": 3,
        "shadow_color": "&H90000000",
        "fontsize": 70,
        "animation": "fade",
        "uppercase": False,
        "bold": True,
        "tracking": 1,
    },
    "Neon Glow": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00F6FF3C",  # electric lime #3CFFF6 in BGR
        "outline_color": "&H00000000",
        "border": 7,
        "shadow": 5,
        "shadow_color": "&H60FFFF00",
        "fontsize": 68,
        "animation": "bounce",
        "uppercase": False,
        "bold": True,
        "tracking": 1,
    },
    "Impact": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00FFCA3A",  # gold #3ACAFF in BGR
        "outline_color": "&H00000000",
        "border": 9,
        "shadow": 3,
        "shadow_color": "&H90000000",
        "fontsize": 76,
        "animation": "slam",
        "uppercase": True,
        "bold": True,
        "tracking": 1,
    },
    "Pastel": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00FFD6C7",  # soft peach #C7D6FF in BGR
        "outline_color": "&H00000000",
        "border": 7,
        "shadow": 2,
        "shadow_color": "&H90000000",
        "fontsize": 66,
        "animation": "fade",
        "uppercase": False,
        "bold": True,
        "tracking": 1,
    },
    "Minimal": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00C9F5FF",  # pale blue #FFF5C9 in BGR
        "outline_color": "&H00000000",
        "border": 5,
        "shadow": 2,
        "shadow_color": "&H90000000",
        "fontsize": 56,
        "animation": "fade",
        "uppercase": False,
        "bold": True,
        "tracking": 0,
    },
}


def group_into_phrases(
    transcript: list[dict],
    max_words: int = 4,
    gap_threshold: float = 0.35,
    max_duration: float = 2.8,
) -> list[list[int]]:
    if not transcript:
        return []
    phrases = []
    current_phrase = [0]
    for i in range(1, len(transcript)):
        gap = transcript[i]["start"] - transcript[i - 1]["end"]
        phrase_start = transcript[current_phrase[0]]["start"]
        phrase_duration = transcript[i]["end"] - phrase_start
        if gap > gap_threshold or len(current_phrase) >= max_words or phrase_duration >= max_duration:
            phrases.append(current_phrase)
            current_phrase = [i]
        else:
            current_phrase.append(i)
    if current_phrase:
        phrases.append(current_phrase)
    return phrases


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
    """Build ASS animation tags for the entire phrase appearance."""
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


def _wrap_phrase_words(words: list[str], font, max_width_px: int, max_lines: int = 2) -> str:
    if not words:
        return ""
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate_words = current + [word]
        candidate = " ".join(candidate_words)
        if current and _measure_text(candidate, font) > max_width_px:
            lines.append(" ".join(current))
            current = [word]
        else:
            current = candidate_words

    if current:
        lines.append(" ".join(current))

    if len(lines) <= max_lines:
        return r"\N".join(lines)

    midpoint = (len(words) + 1) // 2
    best_layout = None
    best_score = None

    for split in range(max(1, midpoint - 2), min(len(words), midpoint + 2) + 1):
        left = " ".join(words[:split])
        right = " ".join(words[split:])
        score = max(_measure_text(left, font), _measure_text(right, font))
        if best_score is None or score < best_score:
            best_score = score
            best_layout = (left, right)

    if best_layout:
        return r"\N".join(best_layout)
    return r"\N".join(lines[:max_lines])


def _format_base_phrase(
    transcript: list[dict],
    phrase_indices: list[int],
    phrase_start: float,
    preset: dict,
    max_width_px: int,
) -> tuple[str, int]:
    """Build the STABLE base layer: color-only transforms, no scaling.

    This layer never changes size so it stays rock solid.
    """
    font = _load_font(preset["fontsize"])

    plain_words = [
        transcript[i]["word"].upper() if preset["uppercase"] else transcript[i]["word"]
        for i in phrase_indices
    ]
    wrapped_plain = _wrap_phrase_words(plain_words, font, max_width_px=max_width_px)
    line_count = len(wrapped_plain.split(r"\N"))

    # Color-only transforms per word (no \fscx/\fscy — prevents reflow)
    markup_words = []
    for pos, global_idx in enumerate(phrase_indices):
        word = transcript[global_idx]["word"]
        if preset["uppercase"]:
            word = word.upper()

        word_start = transcript[global_idx]["start"] - phrase_start
        if pos + 1 < len(phrase_indices):
            word_end = transcript[phrase_indices[pos + 1]]["start"] - phrase_start
        else:
            word_end = transcript[global_idx]["end"] - phrase_start

        start_ms = max(0, int(round(word_start * 1000)))
        end_ms = max(start_ms + 10, int(round(word_end * 1000)))

        word = (
            "{"
            f"\\c{preset['text_color']}"
            f"\\t({start_ms},{end_ms},\\c{preset['highlight_color']})"
            f"\\t({end_ms},{end_ms + 10},\\c{preset['text_color']})"
            "}"
            f"{word}"
        )
        markup_words.append(word)

    markup_iter = iter(markup_words)
    wrapped_markup = []
    for line in wrapped_plain.split(r"\N"):
        n_words = len(line.split())
        wrapped_markup.append(" ".join(next(markup_iter) for _ in range(n_words)))
    phrase_text = r"\N".join(wrapped_markup)

    anim_tag = _build_phrase_animation(preset)
    spacing = preset.get("tracking", 0)
    if anim_tag or spacing:
        phrase_text = "{" + anim_tag + (f"\\fsp{spacing}" if spacing else "") + "}" + phrase_text
    return phrase_text, line_count


def _build_overlay_events(
    transcript: list[dict],
    phrase_indices: list[int],
    phrase_start: float,
    phrase_end: float,
    preset: dict,
    frame_width: int,
    caption_zone_top: int,
) -> list[str]:
    """Build overlay layer events: one per word, absolute positioned, scaled up.

    Each word gets its own event on layer 1, absolutely positioned so scaling
    one word doesn't affect others. Only visible while that word is active.
    """
    active_scale = preset.get("active_scale", 100)
    if active_scale == 100:
        return []  # no overlay needed

    font = _load_font(preset["fontsize"])
    events = []

    # Calculate word positions by measuring cumulative widths
    plain_words = [
        transcript[i]["word"].upper() if preset["uppercase"] else transcript[i]["word"]
        for i in phrase_indices
    ]
    space_w = _measure_text(" ", font)
    word_widths = [_measure_text(w, font) for w in plain_words]
    total_w = sum(word_widths) + space_w * (len(plain_words) - 1)
    x_start = (frame_width - total_w) / 2

    # Y position: use MarginV from style — libass places text from bottom
    # For \an8 (top-center), MarginV is from top. Overlay needs same Y.
    # We use \an5 (center) with explicit \pos for each word.
    line_height = preset["fontsize"]
    y_center = caption_zone_top + line_height // 2

    x_cursor = x_start
    for pos, global_idx in enumerate(phrase_indices):
        word = plain_words[pos]
        word_w = word_widths[pos]
        word_center_x = x_cursor + word_w / 2

        word_start = transcript[global_idx]["start"]
        if pos + 1 < len(phrase_indices):
            word_end = transcript[phrase_indices[pos + 1]]["start"]
        else:
            word_end = transcript[global_idx]["end"]

        # Scale animation: start at 100, pop to active_scale, back to 100
        pop_ms = 80
        override = (
            "{"
            f"\\an5\\pos({word_center_x:.0f},{y_center})"
            f"\\c{preset['highlight_color']}"
            f"\\bord{preset['border']}\\shad0"
            f"\\fscx100\\fscy100"
            f"\\t(0,{pop_ms},\\fscx{active_scale}\\fscy{active_scale})"
            f"\\t({pop_ms},{pop_ms + 60},\\fscx100\\fscy100)"
            "}"
        )

        events.append(
            f"Dialogue: 1,{_ass_timestamp(word_start)},{_ass_timestamp(word_end)},Default,,0,0,0,,{override}{word}"
        )

        x_cursor += word_w + space_w

    return events


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

    Uses centered phrases with inline color tags for highlighted words.
    Each phrase appears as one subtitle event, centered on screen.
    """
    p = PRESETS.get(preset, PRESETS["Opus Clean"])
    phrases = group_into_phrases(transcript)

    line_height = p["fontsize"] + int(p["fontsize"] * 0.30)
    caption_zone_top = int(y_position * frame_height) - (line_height * 2)
    caption_zone_top = max(1260, min(1360, caption_zone_top))
    fontname = Path(CAPTION_FONT_PATH).stem

    bold_flag = -1 if p["bold"] else 0

    header = f"""[Script Info]
Title: yt2tiktok captions
ScriptType: v4.00+
PlayResX: {frame_width}
PlayResY: {frame_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fontname},{p['fontsize']},{p['text_color']},&H000000FF,{p['outline_color']},{p['shadow_color']},{bold_flag},0,0,0,100,100,{p.get('tracking', 0)},0,1,{p['border']},{p['shadow']},8,70,70,{caption_zone_top},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    max_width_px = int(frame_width * 0.78)
    active_scale = p.get("active_scale", 100)

    for phrase_indices in phrases:
        if not phrase_indices:
            continue

        phrase_start = transcript[phrase_indices[0]]["start"]
        phrase_end = transcript[phrase_indices[-1]]["end"]

        # Layer 0: stable base phrase (color changes only, no scaling)
        phrase_text, line_count = _format_base_phrase(
            transcript, phrase_indices, phrase_start, p, max_width_px,
        )
        if line_count == 1:
            phrase_text = r"{\alpha&HFF&}_\N{\alpha&H00&}" + phrase_text
        events.append(
            f"Dialogue: 0,{_ass_timestamp(phrase_start)},{_ass_timestamp(phrase_end)},Default,,0,0,0,,{phrase_text}"
        )

        # Layer 1: overlay with scale pop per word (absolute positioned, won't shift base)
        if active_scale != 100 and line_count == 1:
            overlay_events = _build_overlay_events(
                transcript, phrase_indices, phrase_start, phrase_end,
                p, frame_width, caption_zone_top,
            )
            events.extend(overlay_events)

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
