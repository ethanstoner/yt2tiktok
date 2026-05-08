import sys
import shutil
import subprocess
import customtkinter as ctk
from src.constants import *
from src import updater


class AboutDialog(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("About yt2tiktok")
        self.geometry("400x380")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus_force()

        ctk.CTkLabel(self, text="yt2tiktok", font=("", 24, "bold")).pack(pady=(SP_24, SP_4))
        ctk.CTkLabel(self, text=f"v{APP_VERSION}", font=("", FONT_LABEL), text_color=TEXT_MUTED).pack()
        ctk.CTkLabel(self, text="YouTube to TikTok clip converter\nwith karaoke-style captions",
                     font=("", FONT_BODY), text_color=TEXT_SECONDARY, justify="center").pack(pady=SP_12)

        info_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        info_frame.pack(fill="x", padx=SP_24, pady=SP_8)

        rows = [
            ("Python", sys.version.split()[0]),
            ("FFmpeg", self._get_ffmpeg_ver()),
            ("GPU", self._get_gpu_status()),
        ]
        for label, value in rows:
            row = ctk.CTkFrame(info_frame, fg_color="transparent")
            row.pack(fill="x", padx=SP_12, pady=2)
            ctk.CTkLabel(row, text=label, font=("", FONT_MUTED), text_color=TEXT_MUTED).pack(side="left")
            ctk.CTkLabel(row, text=value, font=("", FONT_MUTED)).pack(side="right")

        self.update_label = ctk.CTkLabel(self, text="", font=("", FONT_MUTED))
        self.update_label.pack(pady=SP_8)

        ctk.CTkButton(self, text="Check for Updates", width=160, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._check_update).pack(pady=SP_4)

        ctk.CTkButton(self, text="Close", width=100, command=self.destroy).pack(pady=SP_12)

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
            if version:
                self.update_label.configure(text=f"Update available: {version}", text_color=SUCCESS)
            else:
                self.update_label.configure(text="You're up to date!", text_color=SUCCESS)
        updater.check_for_update(_on_result)
