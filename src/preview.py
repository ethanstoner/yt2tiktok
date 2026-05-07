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

    def __init__(self, master, video_path: str, transcript: list[dict], callback, y_var=None):
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

        frame_path = _grab_frame(video_path)
        if frame_path:
            self.base_image = Image.open(frame_path).resize(
                (self.PREVIEW_W, self.PREVIEW_H), Image.LANCZOS
            )
            os.unlink(frame_path)
        else:
            self.base_image = Image.new("RGB", (self.PREVIEW_W, self.PREVIEW_H), "#1a1a1a")

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

    def _get_sample_text(self) -> str:
        phrases = captioner.group_into_phrases(self.transcript)
        if phrases:
            phrase = phrases[0]
            return phrase, phrase[min(1, len(phrase) - 1)]
        return [0, 1, 2], 1

    def _render(self):
        img = self.base_image.convert("RGBA")
        draw = ImageDraw.Draw(img)
        preset = captioner.PRESETS.get(self.preset_name, captioner.PRESETS["Opus Clean"])

        phrase_indices, active_idx = self._get_sample_text()
        scale = self.PREVIEW_W / 1080
        font_size = int(preset["fontsize"] * scale)

        plain_words = []
        for idx in phrase_indices:
            word = self.transcript[idx]["word"]
            if preset["uppercase"]:
                word = word.upper()
            plain_words.append(word)
        font = captioner._load_font(font_size)

        anchor_y = int(self.y_position * self.PREVIEW_H)
        center_x = self.PREVIEW_W // 2

        # Measure full phrase for natural spacing
        full_phrase = " ".join(plain_words)
        full_w = captioner._measure_text(full_phrase, font)
        line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
        text_y = anchor_y - line_h

        # Draw background band
        band_top = max(0, text_y - 16)
        band_bottom = min(self.PREVIEW_H, anchor_y + 10)
        band = Image.new("RGBA", img.size, (0, 0, 0, 0))
        band_draw = ImageDraw.Draw(band)
        band_draw.rounded_rectangle(
            [(18, band_top), (self.PREVIEW_W - 18, band_bottom)],
            radius=18,
            fill=(0, 0, 0, 90),
        )
        img = Image.alpha_composite(img, band)
        draw = ImageDraw.Draw(img)

        stroke_w = max(1, preset["border"] * self.PREVIEW_W // 1080)
        line_left = center_x - full_w // 2

        for i, word in enumerate(plain_words):
            is_active = phrase_indices[i] == active_idx
            fill = "#78FF57" if is_active else "white"

            if i == 0:
                word_left = line_left
            else:
                prefix = " ".join(plain_words[:i]) + " "
                word_left = line_left + captioner._measure_text(prefix, font)

            word_w = captioner._measure_text(word, font)
            render_font = font
            y_offset = 0
            if is_active and preset.get("active_scale", 100) != 100:
                active_size = max(12, int(font_size * preset["active_scale"] / 100))
                render_font = captioner._load_font(active_size)
                y_offset = (active_size - font_size) // 2
                # Center the scaled word on the same center-x
                scaled_w = captioner._measure_text(word, render_font)
                word_left = word_left + word_w // 2 - scaled_w // 2

            draw.text(
                (word_left, text_y - y_offset),
                word, font=render_font, fill=fill,
                stroke_width=stroke_w, stroke_fill="black",
            )

        draw.line([(0, anchor_y), (self.PREVIEW_W, anchor_y)], fill="#00ff00", width=1)

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
