import os
import random
import shutil
import subprocess
import sys
import platform
import textwrap
from pathlib import Path

from PIL import ImageFont

CLIPS_DIR = Path(__file__).parent / "clips"
FFMPEG_CMD = shutil.which("ffmpeg")
FFPROBE_CMD = shutil.which("ffprobe")

CLIP_MIN = 60
CLIP_MAX = 70
WARN_DURATION = 7200
WARN_CLIPS = 30

def _find_font() -> str:
    candidates = []
    system = platform.system()
    if system == "Windows":
        candidates.append(r"C:\Windows\Fonts\arialbd.ttf")
    elif system == "Darwin":
        candidates.append("/Library/Fonts/Arial Bold.ttf")
    else:
        candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    bundled = Path(__file__).parent / "fonts" / "RobotoCondensed-Bold.ttf"
    candidates.append(str(bundled))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""

FONT_PATH = _find_font()


def sanitize_title(title: str) -> str:
    for ch in '<>:"/\\|?*':
        title = title.replace(ch, "")
    return title.strip().rstrip(". ")

def get_video_duration(video_path: str) -> float:
    cmd = [FFPROBE_CMD, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())

def get_video_dimensions(video_path: str) -> tuple[int, int]:
    cmd = [FFPROBE_CMD, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    w, h = result.stdout.strip().split("x")
    return int(w), int(h)


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
    video_path = str(target_dir / f"{title}.mp4")
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

def process_clip(video_path: str, title: str, idx: int, total: int, start: float, duration: float, target_dir: str, mode: str = "blurred", log_fn=None) -> str | None:
    out = os.path.join(target_dir, f"{title}_clip_{idx}.mp4")
    os.makedirs(target_dir, exist_ok=True)
    orig_w, orig_h = get_video_dimensions(video_path)
    scaled_h = int(orig_h * (1080 / orig_w))
    pad_y = int((1920 - scaled_h) / 2)
    top_bar_height = pad_y
    wrapped_title, title_fontsize, num_lines = wrap_text_to_fit(title, max_width_px=1080 - 60, max_height_px=top_bar_height)
    safe_font = FONT_PATH.replace("\\", "/").replace(":", "\\:")
    safe_title = wrapped_title.replace("'", "\\'")
    bottom_fontsize = 90
    borderw = 3
    text_pad = borderw * 2 + 8
    if FONT_PATH:
        font = ImageFont.truetype(FONT_PATH, title_fontsize)
        base_h = font.getbbox("A")[3] - font.getbbox("A")[1]
        line_spacing = int(base_h * 0.25)
        title_block_h = num_lines * base_h + (num_lines - 1) * line_spacing
        top_text_y = (top_bar_height - title_block_h) // 2 + text_pad
        font_bottom = ImageFont.truetype(FONT_PATH, bottom_fontsize)
        bottom_h = font_bottom.getbbox("A")[3] - font_bottom.getbbox("A")[1]
        bottom_text_y = (1920 - pad_y) + (pad_y - bottom_h) // 2 + text_pad
    else:
        top_text_y = pad_y // 4
        bottom_text_y = 1920 - pad_y + pad_y // 4
    part_label = f"Part {idx}/{total}"
    text_filters = (
        f"drawtext=fontfile='{safe_font}':text='{safe_title}':fontcolor=white:"
        f"fontsize={title_fontsize}:x=(w-text_w)/2:y={top_text_y}:"
        f"borderw={borderw}:bordercolor=black:line_spacing=12:text_align=center,"
        f"drawtext=fontfile='{safe_font}':text='{part_label}':fontcolor=white:"
        f"fontsize={bottom_fontsize}:x=(w-text_w)/2:y={bottom_text_y}:"
        f"borderw={borderw}:bordercolor=black"
    )
    if mode == "blurred":
        filter_chain = (
            "[0:v]scale=540:960,gblur=sigma=30,scale=1080:1920:flags=lanczos,setsar=1[bg];"
            "[0:v]scale=1080:ih*1080/iw:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{text_filters}[v]"
        )
        filter_flag = "-filter_complex"
        map_args = ["-map", "[v]", "-map", "0:a?"]
    else:
        filter_chain = (
            "scale=1080:ih*1080/iw:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,{text_filters}"
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


def split_video(video_path: str, title: str, mode: str = "blurred", log_fn=None, progress_fn=None) -> tuple[str, int]:
    target_dir = str(CLIPS_DIR / title)
    duration = get_video_duration(video_path)
    clips: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        length = random.randint(CLIP_MIN, CLIP_MAX)
        end = min(duration, start + length)
        clips.append((start, end - start))
        start = end
    if len(clips) >= 2 and clips[-1][1] < CLIP_MIN:
        prev_start, prev_dur = clips[-2]
        _, last_dur = clips[-1]
        clips[-2] = (prev_start, prev_dur + last_dur)
        clips.pop()
    total = len(clips)
    if log_fn:
        encoder = "GPU (NVENC)" if _USE_NVENC else "CPU (libx264)"
        log_fn(f"Splitting into {total} clips using {encoder}...")
    completed = 0
    for i, (clip_start, clip_dur) in enumerate(clips, 1):
        result = process_clip(video_path, title, i, total, clip_start, clip_dur, target_dir, mode=mode, log_fn=log_fn)
        if result:
            completed += 1
        if progress_fn:
            progress_fn(f"Clip {i}/{total}")
    if log_fn:
        log_fn(f"Completed {completed}/{total} clips in: {target_dir}")
    if progress_fn:
        progress_fn("")
    return target_dir, total
