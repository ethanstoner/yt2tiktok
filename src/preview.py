import os
import subprocess
import shutil
import tempfile
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageFont
from pathlib import Path

from src import captioner

FFMPEG_CMD = shutil.which("ffmpeg")


def _grab_frame(video_path: str, time_sec: float = 30) -> str | None:
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    for seek in [time_sec, 0]:
        cmd = [
            FFMPEG_CMD, "-y", "-ss", str(seek),
            "-i", video_path, "-vframes", "1", "-f", "image2", tmp.name,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 0:
            return tmp.name
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
    return None


class CaptionPreview(ctk.CTkToplevel):
    PREVIEW_W = 360
    PREVIEW_H = 640

    def __init__(self, master, video_path: str, transcript: list[dict], callback, y_var=None, background_image=None, video_title: str = "Sample Video Title", clip_index: int = 1):
        super().__init__(master)
        self.title("Caption Preview")
        self.geometry(f"{self.PREVIEW_W + 40}x{self.PREVIEW_H + 160}")
        self.resizable(False, False)

        self.video_path = video_path
        self.transcript = transcript
        self.callback = callback
        self.y_var = y_var
        self.y_position = y_var.get() if y_var else 0.73
        self.preset_name = "Opus Clean"
        self.frame_img = None
        self.video_title = video_title
        self.clip_index = clip_index

        source_img = None
        if background_image:
            source_img = background_image
        else:
            frame_path = _grab_frame(video_path) if video_path else None
            if frame_path:
                try:
                    # Fully load into memory before deleting; PIL keeps the
                    # file open lazily and Windows refuses to unlink it.
                    with Image.open(frame_path) as _im:
                        source_img = _im.copy()
                except Exception:
                    source_img = None
                finally:
                    try:
                        os.unlink(frame_path)
                    except OSError:
                        pass

        if source_img:
            self.base_image = self._make_9x16_background(source_img)
        else:
            self.base_image = Image.new("RGB", (self.PREVIEW_W, self.PREVIEW_H), "#1a1a1a")

        self.lift()
        self.focus_force()

        preset_frame = ctk.CTkFrame(self, fg_color="transparent")
        preset_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(preset_frame, text="Style:").pack(side="left")
        self.preset_var = ctk.StringVar(value=self.preset_name)
        ctk.CTkOptionMenu(
            preset_frame,
            values=list(captioner.PRESETS.keys()),
            variable=self.preset_var,
            command=self._on_preset_change,
        ).pack(side="left", padx=5)

        self.canvas = ctk.CTkCanvas(self, width=self.PREVIEW_W, height=self.PREVIEW_H)
        self.canvas.pack(padx=10, pady=5)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)

        self.pos_label = ctk.CTkLabel(self, text=f"Position: {int(self.y_position * 100)}%")
        self.pos_label.pack()

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(btn_frame, text="Apply", command=self._on_apply).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", command=self.destroy).pack(side="right", expand=True, padx=5)

        self._render()

    def _make_9x16_background(self, source: Image.Image) -> Image.Image:
        """Create a 9:16 preview with blurred background, matching actual clip output."""
        from PIL import ImageFilter
        w, h = self.PREVIEW_W, self.PREVIEW_H  # 360x640 = 9:16

        # Blurred, zoomed background
        bg = source.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=15))

        # Scaled foreground (fit width, maintain aspect ratio)
        src_w, src_h = source.size
        fg_w = w
        fg_h = int(src_h * (w / src_w))
        fg = source.resize((fg_w, fg_h), Image.LANCZOS)

        # Overlay centered
        y_offset = (h - fg_h) // 2
        bg.paste(fg, (0, y_offset))
        return bg

    def _get_sample_text(self) -> str:
        if not self.transcript:
            self.transcript = [
                {"word": "Sample", "start": 0, "end": 0.5, "confidence": 1.0},
                {"word": "caption", "start": 0.5, "end": 1.0, "confidence": 1.0},
                {"word": "text", "start": 1.0, "end": 1.5, "confidence": 1.0},
            ]
        phrases = captioner.group_into_phrases(self.transcript)
        if phrases:
            phrase = phrases[0]
            return phrase, phrase[min(1, len(phrase) - 1)]
        valid = list(range(min(3, len(self.transcript))))
        return valid, valid[min(1, len(valid) - 1)]

    def _render(self):
        img = self.base_image.convert("RGBA")
        draw = ImageDraw.Draw(img)
        preset = captioner.PRESETS.get(self.preset_name, captioner.PRESETS["Opus Clean"])
        scale = self.PREVIEW_W / 1080
        center_x = self.PREVIEW_W // 2

        # ── Title and Part label (matching clipper.py layout) ──
        # Calculate the blurred bar height (top/bottom padding)
        # For 16:9 source on 9:16 frame: video is 360x202, bars are ~219px each
        fg_h = int(self.PREVIEW_H * 9 / 16)  # approximate 16:9 video height
        pad_y = (self.PREVIEW_H - fg_h) // 2

        # Title at top
        title_fontsize = max(10, int(40 * scale))
        title_font = captioner._load_font(title_fontsize)
        title_text = self.video_title
        title_w = captioner._measure_text(title_text, title_font)
        # Shrink if too wide
        while title_w > self.PREVIEW_W - 30 and title_fontsize > 8:
            title_fontsize -= 1
            title_font = captioner._load_font(title_fontsize)
            title_w = captioner._measure_text(title_text, title_font)
        title_h = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1]
        title_x = center_x - title_w // 2
        title_y = (pad_y - title_h) // 2
        draw.text(
            (title_x, title_y), title_text, font=title_font, fill="white",
            stroke_width=2, stroke_fill="black",
        )

        # Part label at bottom
        part_text = f"Part {self.clip_index}"
        part_fontsize = max(10, int(60 * scale))
        part_font = captioner._load_font(part_fontsize)
        part_w = captioner._measure_text(part_text, part_font)
        part_h = part_font.getbbox("Ag")[3] - part_font.getbbox("Ag")[1]
        part_x = center_x - part_w // 2
        part_y = (self.PREVIEW_H - pad_y) + (pad_y - part_h) // 2
        draw.text(
            (part_x, part_y), part_text, font=part_font, fill="white",
            stroke_width=2, stroke_fill="black",
        )

        # ── Caption text ──
        phrase_indices, active_idx = self._get_sample_text()
        font_size = int(preset["fontsize"] * scale)

        plain_words = []
        for idx in phrase_indices:
            word = self.transcript[idx]["word"]
            if preset["uppercase"]:
                word = word.upper()
            plain_words.append(word)
        font = captioner._load_font(font_size)

        anchor_y = int(self.y_position * self.PREVIEW_H)
        space_w = captioner._measure_text(" ", font)

        # Measure each word at its render size (accounting for active scale)
        word_widths = []
        word_fonts = []
        word_y_offsets = []
        for i, word in enumerate(plain_words):
            is_active = phrase_indices[i] == active_idx
            if is_active and preset.get("active_scale", 100) != 100:
                active_size = max(12, int(font_size * preset["active_scale"] / 100))
                rf = captioner._load_font(active_size)
                word_widths.append(captioner._measure_text(word, rf))
                word_fonts.append(rf)
                word_y_offsets.append((active_size - font_size) // 2)
            else:
                word_widths.append(captioner._measure_text(word, font))
                word_fonts.append(font)
                word_y_offsets.append(0)

        total_w = sum(word_widths) + space_w * (len(plain_words) - 1)
        line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
        text_y = anchor_y - line_h

        # Draw background band behind caption
        band_top = max(0, text_y - 12)
        band_bottom = min(self.PREVIEW_H, anchor_y + 8)
        band = Image.new("RGBA", img.size, (0, 0, 0, 0))
        band_draw = ImageDraw.Draw(band)
        band_draw.rounded_rectangle(
            [(18, band_top), (self.PREVIEW_W - 18, band_bottom)],
            radius=14,
            fill=(0, 0, 0, 90),
        )
        img = Image.alpha_composite(img, band)
        draw = ImageDraw.Draw(img)

        stroke_w = max(1, preset["border"] * self.PREVIEW_W // 1080)

        # Convert ASS BGR highlight color to RGB hex
        raw = preset["highlight_color"].replace("&H", "").replace("&h", "")
        if len(raw) == 8:
            raw = raw[2:]
        bv, gv, rv = raw[0:2], raw[2:4], raw[4:6]
        highlight_hex = f"#{rv}{gv}{bv}"

        # Draw words with correct spacing
        cursor_x = center_x - total_w // 2
        for i, word in enumerate(plain_words):
            is_active = phrase_indices[i] == active_idx
            fill = highlight_hex if is_active else "white"

            draw.text(
                (cursor_x, text_y - word_y_offsets[i]),
                word, font=word_fonts[i], fill=fill,
                stroke_width=stroke_w, stroke_fill="black",
            )
            cursor_x += word_widths[i] + space_w

        self.frame_img = ImageTk.PhotoImage(img.convert("RGB"))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.frame_img)

    def _on_click(self, event):
        self.y_position = max(0.64, min(0.84, event.y / self.PREVIEW_H))
        if self.y_var:
            self.y_var.set(self.y_position)
        self.pos_label.configure(text=f"Position: {int(self.y_position * 100)}%")
        self._render()

    def _on_drag(self, event):
        self.y_position = max(0.64, min(0.84, event.y / self.PREVIEW_H))
        if self.y_var:
            self.y_var.set(self.y_position)
        self.pos_label.configure(text=f"Position: {int(self.y_position * 100)}%")
        self._render()

    def _on_preset_change(self, value):
        self.preset_name = value
        self._render()

    def _on_apply(self):
        self.callback(self.y_position, self.preset_name)
        self.destroy()
