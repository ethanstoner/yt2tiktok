import os
from pathlib import Path
from PIL import ImageFont

CAPTION_FONT_PATH = str(Path(__file__).parent / "fonts" / "BubblegumSans-Regular.ttf")
if not os.path.isfile(CAPTION_FONT_PATH):
    CAPTION_FONT_PATH = str(Path(__file__).parent / "fonts" / "RobotoCondensed-Bold.ttf")

PRESETS = {
    "Bold Pop": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H0000D4FF",  # bright orange-yellow #FFD400 in BGR
        "outline_color": "&H00000000",
        "border": 8,
        "shadow": 3,
        "shadow_color": "&HA0000000",
        "fontsize": 72,
        "animation": "scale",
        "uppercase": False,
        "bold": True,
    },
    "Neon Glow": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00FFFF00",  # cyan #00FFFF in BGR
        "outline_color": "&H00000000",
        "border": 7,
        "shadow": 5,
        "shadow_color": "&H60FFFF00",
        "fontsize": 68,
        "animation": "bounce",
        "uppercase": False,
        "bold": True,
    },
    "Impact": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H001414FF",  # bright red #FF1414 in BGR
        "outline_color": "&H00000000",
        "border": 9,
        "shadow": 3,
        "shadow_color": "&HA0000000",
        "fontsize": 76,
        "animation": "slam",
        "uppercase": True,
        "bold": True,
    },
    "Pastel": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00FF88FF",  # hot pink #FF88FF in BGR
        "outline_color": "&H00000000",
        "border": 7,
        "shadow": 2,
        "shadow_color": "&HA0000000",
        "fontsize": 66,
        "animation": "fade",
        "uppercase": False,
        "bold": True,
    },
    "Minimal": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H0088DDFF",  # warm yellow #FFDD88 in BGR
        "outline_color": "&H00000000",
        "border": 5,
        "shadow": 2,
        "shadow_color": "&HA0000000",
        "fontsize": 56,
        "animation": "fade",
        "uppercase": False,
        "bold": True,
    },
}


def group_into_phrases(transcript: list[dict], max_words: int = 5, gap_threshold: float = 0.4) -> list[list[int]]:
    if not transcript:
        return []
    phrases = []
    current_phrase = [0]
    for i in range(1, len(transcript)):
        gap = transcript[i]["start"] - transcript[i - 1]["end"]
        if gap > gap_threshold or len(current_phrase) >= max_words:
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
    return ""


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
    p = PRESETS.get(preset, PRESETS["Bold Pop"])
    highlight_set = set(highlight_indices)
    phrases = group_into_phrases(transcript)

    y_margin = int((1.0 - y_position) * frame_height)
    fontname = "BubblegumSans-Regular"
    if not os.path.isfile(str(Path(__file__).parent / "fonts" / "BubblegumSans-Regular.ttf")):
        fontname = "RobotoCondensed-Bold"

    bold_flag = -1 if p["bold"] else 0

    header = f"""[Script Info]
Title: yt2tiktok captions
ScriptType: v4.00+
PlayResX: {frame_width}
PlayResY: {frame_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fontname},{p['fontsize']},{p['text_color']},&H000000FF,{p['outline_color']},{p['shadow_color']},{bold_flag},0,0,0,100,100,2,0,1,{p['border']},{p['shadow']},2,30,30,{y_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    for phrase_indices in phrases:
        if not phrase_indices:
            continue

        phrase_start = transcript[phrase_indices[0]]["start"]
        phrase_end = transcript[phrase_indices[-1]]["end"]

        # Build phrase text with inline color overrides for highlighted words
        parts = []
        for global_idx in phrase_indices:
            word = transcript[global_idx]["word"]
            if p["uppercase"]:
                word = word.upper()

            if global_idx in highlight_set:
                # Color override for highlighted word
                parts.append(f"{{\\c{p['highlight_color']}}}{word}{{\\c{p['text_color']}}}")
            else:
                parts.append(word)

        phrase_text = " ".join(parts)

        # Add animation
        anim_tag = _build_phrase_animation(p)
        if anim_tag:
            phrase_text = f"{{{anim_tag}}}" + phrase_text

        start_ts = _ass_timestamp(phrase_start)
        end_ts = _ass_timestamp(phrase_end)

        events.append(
            f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{phrase_text}"
        )

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
