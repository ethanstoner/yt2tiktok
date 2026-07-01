import os
import re
import random
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import ImageFont

CLIPS_DIR = Path(__file__).parent.parent / "clips"
FFMPEG_CMD = shutil.which("ffmpeg")
FFPROBE_CMD = shutil.which("ffprobe")

CLIP_MIN = 60
CLIP_MAX = 70
WARN_DURATION = 7200
WARN_CLIPS = 30

def _find_font() -> str:
    from src.captioner import CAPTION_FONT_PATH
    if CAPTION_FONT_PATH:
        return CAPTION_FONT_PATH
    bundled = Path(__file__).parent.parent / "fonts" / "RobotoCondensed-Bold.ttf"
    if bundled.is_file():
        return str(bundled)
    return ""

FONT_PATH = _find_font()


def sanitize_title(title: str) -> str:
    for ch in '<>:"/\\|?*':
        title = title.replace(ch, "")
    cleaned = title.strip().rstrip(". ")
    return cleaned or "video"

def get_video_duration(video_path: str) -> float:
    if FFPROBE_CMD is None:
        raise RuntimeError("ffprobe not found in PATH. Install FFmpeg.")
    cmd = [FFPROBE_CMD, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise RuntimeError(
            f"Could not read video duration (ffprobe exit {result.returncode}). "
            f"The file may be corrupt or not a valid video: {result.stderr.strip()[:200]}"
        )

def get_video_dimensions(video_path: str) -> tuple[int, int]:
    if FFPROBE_CMD is None:
        raise RuntimeError("ffprobe not found in PATH. Install FFmpeg.")
    cmd = [FFPROBE_CMD, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        w, h = result.stdout.strip().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        raise RuntimeError(f"Could not determine video dimensions: {result.stdout.strip()}")


def wrap_text_to_fit(text: str, max_width_px: int, max_height_px: int, max_fontsize: int = 60, min_fontsize: int = 18) -> tuple[str, int, int]:
    if not FONT_PATH:
        return text, min_fontsize, 1
    for fontsize in range(max_fontsize, min_fontsize - 1, -2):
        font = ImageFont.truetype(FONT_PATH, fontsize)
        words = text.split()
        lines: list[str] = []
        current_line = ""
        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            w = font.getbbox(test_line)[2] - font.getbbox(test_line)[0]
            if w <= max_width_px:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        base_h = font.getbbox("A")[3] - font.getbbox("A")[1]
        line_spacing = int(base_h * 0.25)
        total_height = len(lines) * (base_h + line_spacing)
        if total_height <= max_height_px * 0.9:
            return "\n".join(lines), fontsize, len(lines)
    font = ImageFont.truetype(FONT_PATH, min_fontsize)
    lines = textwrap.wrap(text, width=14, break_long_words=False) or [text]
    return "\n".join(lines), min_fontsize, len(lines)


def download_video(url: str, log_fn=None, progress_fn=None, cookiefile: str = None) -> tuple[str, str]:
    import yt_dlp
    if log_fn:
        log_fn("Fetching video info...")
    def on_progress(d):
        if not progress_fn:
            return
        if d.get("status") == "downloading":
            pct = d.get("_percent_str", "0.0%").strip()
            spd = d.get("_speed_str", "0B/s").strip()
            eta = d.get("eta", 0) or 0
            mm, ss = divmod(int(eta), 60)
            progress_fn(f"{pct} | {spd} | ETA {mm}:{ss:02d}")
        elif d.get("status") == "finished":
            progress_fn("Processing download...")
    ydl_opts = {
        "format": "bestvideo[height<=1080]+bestaudio[ext=m4a]/best[height<=1080]",
        "merge_output_format": "mp4",
        "progress_hooks": [on_progress],
        "quiet": True,
        "no_warnings": True,
    }
    if FFMPEG_CMD:
        ydl_opts["ffmpeg_location"] = FFMPEG_CMD
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    title = sanitize_title(info.get("title", "video"))
    target_dir = CLIPS_DIR / title
    target_dir.mkdir(parents=True, exist_ok=True)
    ydl_opts["outtmpl"] = str(target_dir / f"{title}.%(ext)s")
    if log_fn:
        log_fn(f"Downloading: {title}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    # merge_output_format only applies when a merge happens; the
    # best[height<=1080] fallback keeps its native extension (webm/mkv).
    video_path = str(target_dir / f"{title}.mp4")
    if not os.path.exists(video_path):
        candidates = [
            p for p in target_dir.glob(f"{title}.*")
            if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv"}
        ]
        if candidates:
            video_path = str(max(candidates, key=lambda p: p.stat().st_size))
    if log_fn:
        log_fn(f"Saved to: {video_path}")
    if progress_fn:
        progress_fn("")
    return video_path, title


def _has_nvenc() -> bool:
    try:
        result = subprocess.run([FFMPEG_CMD, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10)
        return "h264_nvenc" in result.stdout
    except Exception:
        return False

_USE_NVENC = _has_nvenc() if FFMPEG_CMD else False


def _build_encoder_args() -> list[str]:
    if _USE_NVENC:
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-qmin", "1", "-qmax", "99", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "19"]


def _find_natural_pause(transcript: list[dict], window_start: float, window_end: float) -> float | None:
    words_in_window = [
        w for w in transcript
        if w["start"] >= window_start and w["end"] <= window_end
    ]
    if len(words_in_window) < 2:
        return None
    best_gap = 0.0
    best_cut = None
    for i in range(len(words_in_window) - 1):
        gap = words_in_window[i + 1]["start"] - words_in_window[i]["end"]
        if gap > best_gap:
            best_gap = gap
            best_cut = (words_in_window[i]["end"] + words_in_window[i + 1]["start"]) / 2
    if best_gap >= 0.15:
        return best_cut
    return None


def _find_cliffhanger(transcript: list[dict], window_start: float, window_end: float, llm) -> float | None:
    words_in_window = [
        (i, w) for i, w in enumerate(transcript)
        if w["start"] >= window_start and w["end"] <= window_end
    ]
    if len(words_in_window) < 5:
        return None
    indexed = " ".join(f"{j}:{w['word']}" for j, (_, w) in enumerate(words_in_window))
    prompt = (
        "Below is a transcript segment from a video (no punctuation). "
        "Find the word after which cutting the video would create maximum "
        "suspense or a cliffhanger that makes the viewer want to watch "
        "the next part. Return ONLY the index number of that word.\n\n"
        f"Words: {indexed}"
    )
    try:
        response = llm.complete(prompt)
        match = re.search(r'\d+', response.strip())
        if match:
            idx = int(match.group())
            if 0 <= idx < len(words_in_window):
                _, w = words_in_window[idx]
                return w["end"]
    except Exception:
        pass
    return None


def calculate_cut_points(
    duration: float,
    cut_mode: str = "random",
    transcript: list[dict] = None,
    llm=None,
) -> list[tuple[float, float]]:
    if cut_mode == "random" or transcript is None:
        clips = []
        start = 0.0
        while start < duration:
            length = random.randint(CLIP_MIN, CLIP_MAX)
            end = min(duration, start + length)
            clips.append((start, end - start))
            start = end
        if len(clips) >= 2 and clips[-1][1] < CLIP_MIN:
            prev_start, prev_dur = clips[-2]
            _, last_dur = clips[-1]
            if prev_dur + last_dur <= CLIP_MAX * 2:
                clips[-2] = (prev_start, prev_dur + last_dur)
                clips.pop()
        return clips

    clips = []
    start = 0.0
    target_length = 65

    while start < duration:
        target_end = start + target_length
        if target_end >= duration:
            clips.append((start, duration - start))
            break

        window_start = start + 55
        window_end = min(start + 75, duration)
        cut_at = None

        if cut_mode == "cliffhanger" and llm is not None:
            cut_at = _find_cliffhanger(transcript, window_start, window_end, llm)

        if cut_at is None:
            cut_at = _find_natural_pause(transcript, window_start, window_end)

        if cut_at is None:
            cut_at = start + random.randint(CLIP_MIN, CLIP_MAX)

        cut_at = min(cut_at, duration)
        clips.append((start, cut_at - start))
        start = cut_at

    if len(clips) >= 2 and clips[-1][1] < CLIP_MIN:
        prev_start, prev_dur = clips[-2]
        _, last_dur = clips[-1]
        if prev_dur + last_dur <= CLIP_MAX * 2:
            clips[-2] = (prev_start, prev_dur + last_dur)
            clips.pop()

    return clips


def build_overlay_filters(title: str, idx: int, top_text: str | None, show_part_label: bool,
                          top_bar_height: int = 140, pad_y: int = 140,
                          textfile_path: str | None = None) -> str:
    """Build the drawtext filter string for the top text (hook title or
    video title) and optional bottom Part label. Empty string if no font.

    The top text is written to textfile_path (UTF-8) and referenced via
    textfile=...:expansion=none. Inline text= is NOT safe for free-form
    text: ffmpeg 7.1's filtergraph parser silently corrupts quoted
    apostrophes (filter options get burned into the frame with returncode
    0) and argv-encoded non-ASCII renders nothing on Windows.

    top_bar_height/pad_y come from process_clip's dimension-aware
    computation; the 140 defaults match its minimum reserved band."""
    if not FONT_PATH:
        return ""
    if textfile_path is None:
        raise ValueError("textfile_path is required to render overlay text")
    display_top = top_text if top_text else title
    wrapped_title, title_fontsize, num_lines = wrap_text_to_fit(
        display_top, max_width_px=1080 - 80, max_height_px=top_bar_height, max_fontsize=80)
    with open(textfile_path, "w", encoding="utf-8") as fh:
        fh.write(wrapped_title)
    safe_textfile = textfile_path.replace("\\", "/").replace(":", "\\:")
    borderw = 5
    text_pad = borderw * 2 + 8
    safe_font = FONT_PATH.replace("\\", "/").replace(":", "\\:")
    font = ImageFont.truetype(FONT_PATH, title_fontsize)
    base_h = font.getbbox("A")[3] - font.getbbox("A")[1]
    line_spacing = int(base_h * 0.25)
    title_block_h = num_lines * base_h + (num_lines - 1) * line_spacing
    top_text_y = (top_bar_height - title_block_h) // 2 + text_pad
    filters = (
        f"drawtext=fontfile='{safe_font}':textfile='{safe_textfile}':expansion=none:fontcolor=white:"
        f"fontsize={title_fontsize}:x=(w-text_w)/2:y={top_text_y}:"
        f"borderw={borderw}:bordercolor=black:line_spacing=12:text_align=center"
    )
    if show_part_label:
        bottom_fontsize = 100
        font_bottom = ImageFont.truetype(FONT_PATH, bottom_fontsize)
        bottom_h = font_bottom.getbbox("A")[3] - font_bottom.getbbox("A")[1]
        bottom_text_y = (1920 - pad_y) + (pad_y - bottom_h) // 2 + text_pad
        # Fully controlled ASCII, safe inline; expansion=none anyway so a
        # literal % could never be expanded.
        filters += (
            f",drawtext=fontfile='{safe_font}':text='Part {idx}':expansion=none:fontcolor=white:"
            f"fontsize={bottom_fontsize}:x=(w-text_w)/2:y={bottom_text_y}:"
            f"borderw={borderw}:bordercolor=black"
        )
    return filters


def process_clip(video_path: str, title: str, idx: int, total: int, start: float, duration: float, target_dir: str, mode: str = "blurred", caption_ass: str = None, log_fn=None, dimensions: tuple[int, int] = None, top_text: str | None = None, show_part_label: bool = True) -> str | None:
    out = os.path.join(target_dir, f"{title}_clip_{idx}.mp4")
    os.makedirs(target_dir, exist_ok=True)
    orig_w, orig_h = dimensions if dimensions is not None else get_video_dimensions(video_path)
    if not orig_w or not orig_h or orig_w <= 0 or orig_h <= 0:
        orig_w, orig_h = 1920, 1080
    scaled_h = int(orig_h * (1080 / orig_w))
    pad_y = int((1920 - scaled_h) / 2)
    # Source taller than 16:9 (vertical/square) leaves no letterbox bar;
    # reserve a minimum band so the title/part overlays stay on-screen.
    pad_y = max(pad_y, 140)
    top_bar_height = pad_y
    # Unique per clip: process_clip runs concurrently in a thread pool.
    overlay_textfile = os.path.join(target_dir, f"_title_{idx}.txt")
    try:
        text_filters = build_overlay_filters(title, idx, top_text, show_part_label, top_bar_height=top_bar_height, pad_y=pad_y, textfile_path=overlay_textfile)
        safe_ass = ""
        fonts_dir = str(Path(__file__).parent.parent / "fonts").replace("\\", "/").replace(":", "\\:")
        if caption_ass:
            safe_ass = caption_ass.replace("\\", "/").replace(":", "\\:")
        ass_suffix = f",ass='{safe_ass}':fontsdir='{fonts_dir}'" if caption_ass else ""
        text_and_ass = (f",{text_filters}" if text_filters else "") + ass_suffix
        if mode == "blurred":
            filter_chain = (
                "[0:v]scale=540:960,gblur=sigma=30,scale=1080:1920:flags=lanczos,setsar=1[bg];"
                "[0:v]scale=1080:ih*1080/iw:force_original_aspect_ratio=decrease,setsar=1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2{text_and_ass}[v]"
            )
            filter_flag = "-filter_complex"
            map_args = ["-map", "[v]", "-map", "0:a?"]
        else:
            filter_chain = (
                "scale=1080:ih*1080/iw:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black{text_and_ass}"
            )
            filter_flag = "-vf"
            map_args = []
        cmd = [FFMPEG_CMD, "-y", "-ss", str(start), "-t", str(duration), "-i", video_path, filter_flag, filter_chain, *map_args, *_build_encoder_args(), "-c:a", "aac", "-b:a", "128k", out]
        if log_fn:
            log_fn(f"Encoding clip {idx}/{total}...")
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            _, stderr = process.communicate()
            if process.returncode != 0:
                if log_fn:
                    log_fn(f"FFmpeg error on clip {idx}: {stderr[:200]}")
                if os.path.exists(out):
                    os.remove(out)
                return None
        except Exception as e:
            if log_fn:
                log_fn(f"Error processing clip {idx}: {e}")
            if os.path.exists(out):
                os.remove(out)
            return None
        return out
    finally:
        try:
            os.remove(overlay_textfile)
        except OSError:
            pass


def split_video(
    video_path: str,
    title: str,
    mode: str = "blurred",
    cut_mode: str = "random",
    transcript: list[dict] = None,
    llm=None,
    parallel: int = None,
    caption_ass_map: dict = None,
    cuts: list[tuple[float, float]] = None,
    log_fn=None,
    progress_fn=None,
    overlay_map: dict = None,
    show_part_label: bool = True,
) -> tuple[str, int]:
    import concurrent.futures
    import threading as _threading

    target_dir = str(CLIPS_DIR / title)

    if cuts is None:
        duration = get_video_duration(video_path)
        if cut_mode != "random" and transcript is None:
            if log_fn:
                log_fn("Transcription unavailable, using random cuts")
            cut_mode = "random"
        clips = calculate_cut_points(duration, cut_mode, transcript, llm)
    else:
        clips = cuts
    total = len(clips)

    if parallel is None:
        parallel = 2 if _USE_NVENC else 4

    if log_fn:
        encoder = "GPU (NVENC)" if _USE_NVENC else "CPU (libx264)"
        log_fn(f"Splitting into {total} clips using {encoder} ({parallel} workers)...")

    video_dimensions = get_video_dimensions(video_path)

    completed = [0]
    lock = _threading.Lock()

    def encode_clip(args):
        i, clip_start, clip_dur = args
        ass_path = caption_ass_map.get(i) if caption_ass_map else None
        result = process_clip(
            video_path, title, i, total, clip_start, clip_dur,
            target_dir, mode=mode, caption_ass=ass_path, log_fn=log_fn,
            dimensions=video_dimensions,
            top_text=overlay_map.get(i) if overlay_map else None,
            show_part_label=show_part_label,
        )
        with lock:
            completed[0] += 1
            if progress_fn:
                progress_fn(f"Clip {completed[0]}/{total}")
        return result

    clip_args = [(i, cs, cd) for i, (cs, cd) in enumerate(clips, 1)]

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {executor.submit(encode_clip, args): args for args in clip_args}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    if log_fn:
        log_fn(f"Completed {len(results)}/{total} clips in: {target_dir}")
    if progress_fn:
        progress_fn("")

    return target_dir, total
