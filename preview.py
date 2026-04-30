import os
import subprocess
import shutil
import tempfile
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageFont
from pathlib import Path

import captioner

FFMPEG_CMD = shutil.which("ffmpeg")


def _grab_frame(video_path: str, time_sec: float = 30) -> str | None:
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    cmd = [
        FFMPEG_CMD, "-y", "-ss", str(time_sec),
        "-i", video_path, "-vframes", "1", "-f", "image2", tmp.name,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(tmp.name):
        return None
    return tmp.name


class CaptionPreview(ctk.CTkToplevel):
    PREVIEW_W = 360
    PREVIEW_H = 640

    def __init__(self, master, video_path: str, transcript: list[dict], callback):
        super().__init__(master)
        self.title("Caption Preview")
        self.geometry(f"{self.PREVIEW_W + 40}x{self.PREVIEW_H + 160}")
        self.resizable(False, False)

        self.video_path = video_path
        self.transcript = transcript
        self.callback = callback
        self.y_position = 0.72
        self.preset_name = "Bold Pop"
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
            return " ".join(self.transcript[i]["word"] for i in phrases[0])
        return "Sample caption text"

    def _render(self):
        img = self.base_image.copy()
        draw = ImageDraw.Draw(img)
        preset = captioner.PRESETS.get(self.preset_name, captioner.PRESETS["Bold Pop"])

        text = self._get_sample_text()
        if preset["uppercase"]:
            text = text.upper()

        fontsize = int(preset["fontsize"] * self.PREVIEW_W / 1080)
        try:
            font = ImageFont.truetype(captioner.CAPTION_FONT_PATH, fontsize)
        except Exception:
            font = ImageFont.load_default()

        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        x = (self.PREVIEW_W - tw) // 2
        y = int(self.y_position * self.PREVIEW_H)

        stroke_w = max(1, preset["border"] * self.PREVIEW_W // 1080)
        draw.text((x, y), text, font=font, fill="white", stroke_width=stroke_w, stroke_fill="black")
        draw.line([(0, y), (self.PREVIEW_W, y)], fill="#00ff00", width=1)

        self.frame_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.frame_img)

    def _on_click(self, event):
        self.y_position = max(0.1, min(0.9, event.y / self.PREVIEW_H))
        self.pos_label.configure(text=f"Position: {int(self.y_position * 100)}%")
        self._render()

    def _on_drag(self, event):
        self.y_position = max(0.1, min(0.9, event.y / self.PREVIEW_H))
        self.pos_label.configure(text=f"Position: {int(self.y_position * 100)}%")
        self._render()

    def _on_preset_change(self, value):
        self.preset_name = value
        self._render()

    def _on_apply(self):
        self.callback(self.y_position, self.preset_name)
        self.destroy()
