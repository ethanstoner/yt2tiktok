import sys
import shutil
import subprocess
import customtkinter as ctk
from src.constants import *
from src import updater
from src.ui.overlay import Overlay


class AboutPanel(Overlay):
    def __init__(self, master):
        super().__init__(master, title="About")

        c = self.content

        ctk.CTkLabel(c, text="yt2tiktok", font=("", 24, "bold")).pack(pady=(SP_32, SP_4))
        ctk.CTkLabel(c, text=f"v{APP_VERSION}", font=("", FONT_LABEL), text_color=TEXT_MUTED).pack()
        ctk.CTkLabel(c, text="YouTube to TikTok clip converter\nwith karaoke-style captions",
                     font=("", FONT_BODY), text_color=TEXT_SECONDARY, justify="center").pack(pady=SP_12)

        info_frame = ctk.CTkFrame(c, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        info_frame.pack(fill="x", pady=SP_8)

        rows = [
            ("Python", sys.version.split()[0]),
            ("FFmpeg", self._get_ffmpeg_ver()),
            ("GPU", self._get_gpu_status()),
        ]
        for label, value in rows:
            row = ctk.CTkFrame(info_frame, fg_color="transparent")
            row.pack(fill="x", padx=SP_16, pady=3)
            ctk.CTkLabel(row, text=label, font=("", FONT_BODY), text_color=TEXT_MUTED).pack(side="left")
            ctk.CTkLabel(row, text=value, font=("", FONT_BODY)).pack(side="right")

        self.update_label = ctk.CTkLabel(c, text="", font=("", FONT_MUTED))
        self.update_label.pack(pady=SP_12)

        ctk.CTkButton(c, text="Check for Updates", width=160, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._check_update).pack()

        self.show()

    def _get_ffmpeg_ver(self) -> str:
        try:
            result = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-version"],
                                   capture_output=True, text=True, timeout=5)
            parts = result.stdout.split("\n")[0].split()
            for i, p in enumerate(parts):
                if p == "version" and i + 1 < len(parts):
                    return parts[i + 1].split("-")[0]
        except Exception:
            pass
        return "not found"

    def _get_gpu_status(self) -> str:
        try:
            result = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-encoders"],
                                   capture_output=True, text=True, timeout=5)
            if "h264_nvenc" in result.stdout:
                return "NVENC"
        except Exception:
            pass
        return "CPU only"

    def _check_update(self):
        self.update_label.configure(text="Checking...", text_color=TEXT_MUTED)
        def _on_result(version, url):
            def _update():
                if version:
                    self.update_label.configure(text=f"Update available: {version}", text_color=SUCCESS)
                else:
                    self.update_label.configure(text="You're up to date!", text_color=SUCCESS)
            self.after(0, _update)
        updater.check_for_update(_on_result)
