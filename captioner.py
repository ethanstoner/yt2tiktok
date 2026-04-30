import os
from pathlib import Path
from PIL import ImageFont

CAPTION_FONT_PATH = str(Path(__file__).parent / "fonts" / "BubblegumSans-Regular.ttf")
if not os.path.isfile(CAPTION_FONT_PATH):
    CAPTION_FONT_PATH = str(Path(__file__).parent / "fonts" / "RobotoCondensed-Bold.ttf")

PRESETS = {
    "Bold Pop": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H0004C2F7",
        "border": 4,
        "shadow_color": None,
        "fontsize": 48,
        "animation": "scale",
        "uppercase": False,
    },
    "Neon Glow": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00FFF000",
        "border": 3,
        "shadow_color": "&H00FFF000",
        "fontsize": 46,
        "animation": "bounce",
        "uppercase": False,
    },
    "Impact": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H003B3BFF",
        "border": 5,
        "shadow_color": None,
        "fontsize": 52,
        "animation": "slam",
        "uppercase": True,
    },
    "Pastel": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00DB8FFF",
        "border": 3,
        "shadow_color": None,
        "fontsize": 44,
        "animation": "fade",
        "uppercase": False,
    },
    "Minimal": {
        "text_color": "&H00FFFFFF",
        "highlight_color": "&H00CCCCCC",
        "border": 2,
        "shadow_color": None,
        "fontsize": 36,
        "animation": "fade",
        "uppercase": False,
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
    text = " ".join(w["word"] for w in transcript)
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


def _build_word_animation(preset: dict, word_start: float, phrase_start: float) -> str:
    anim = preset["animation"]
    delay_ms = int((word_start - phrase_start) * 1000)

    if anim == "scale":
        return f"\\fscx90\\fscy90\\t({delay_ms},{delay_ms + 100},\\fscx100\\fscy100)"
    elif anim == "bounce":
        return (
            f"\\fscx85\\fscy85"
            f"\\t({delay_ms},{delay_ms + 80},\\fscx105\\fscy105)"
            f"\\t({delay_ms + 80},{delay_ms + 150},\\fscx100\\fscy100)"
        )
    elif anim == "slam":
        return f"\\fscx130\\fscy130\\t({delay_ms},{delay_ms + 80},\\fscx100\\fscy100)"
    elif anim == "fade":
        return f"\\fad({max(100, delay_ms)},0)"
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
    p = PRESETS.get(preset, PRESETS["Bold Pop"])
    highlight_set = set(highlight_indices)
    phrases = group_into_phrases(transcript)

    y_px = int(y_position * frame_height)
    fontname = "BubblegumSans-Regular"
    if not os.path.isfile(str(Path(__file__).parent / "fonts" / "BubblegumSans-Regular.ttf")):
        fontname = "RobotoCondensed-Bold"

    header = f"""[Script Info]
Title: yt2tiktok captions
ScriptType: v4.00+
PlayResX: {frame_width}
PlayResY: {frame_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fontname},{p['fontsize']},{p['text_color']},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{p['border']},0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    try:
        font = ImageFont.truetype(CAPTION_FONT_PATH, p["fontsize"])
    except Exception:
        font = None

    for phrase_indices in phrases:
        if not phrase_indices:
            continue

        phrase_start = transcript[phrase_indices[0]]["start"]
        phrase_end = transcript[phrase_indices[-1]]["end"]

        words_in_phrase = [transcript[i]["word"] for i in phrase_indices]
        if p["uppercase"]:
            words_in_phrase = [w.upper() for w in words_in_phrase]

        phrase_text = " ".join(words_in_phrase)
        if font:
            total_width = font.getbbox(phrase_text)[2] - font.getbbox(phrase_text)[0]
        else:
            total_width = len(phrase_text) * p["fontsize"] * 0.6

        x_start = (frame_width - total_width) // 2
        x_cursor = x_start

        for word_idx_in_phrase, global_idx in enumerate(phrase_indices):
            word = transcript[global_idx]
            display_word = word["word"].upper() if p["uppercase"] else word["word"]

            if font:
                word_width = font.getbbox(display_word)[2] - font.getbbox(display_word)[0]
                space_width = font.getbbox(" ")[2] - font.getbbox(" ")[0] if word_idx_in_phrase > 0 else 0
            else:
                word_width = len(display_word) * p["fontsize"] * 0.6
                space_width = p["fontsize"] * 0.3 if word_idx_in_phrase > 0 else 0

            x_cursor += space_width
            x_pos = x_cursor
            x_cursor += word_width

            is_highlighted = global_idx in highlight_set
            color_tag = f"\\c{p['highlight_color']}" if is_highlighted else f"\\c{p['text_color']}"

            shadow_tag = ""
            if p["shadow_color"]:
                shadow_tag = f"\\4c{p['shadow_color']}\\shad3"

            anim_tag = _build_word_animation(p, word["start"], phrase_start)
            pos_tag = f"\\pos({x_pos},{y_px})"
            align_tag = "\\an7"

            override = f"{{{pos_tag}{align_tag}{color_tag}{shadow_tag}\\bord{p['border']}\\be0{anim_tag}}}"

            start_ts = _ass_timestamp(phrase_start)
            end_ts = _ass_timestamp(phrase_end)

            events.append(
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{override}{display_word}"
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
