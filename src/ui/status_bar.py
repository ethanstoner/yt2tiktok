import shutil
import subprocess
import customtkinter as ctk
from src.constants import *


class StatusBar(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=BG_CARD, height=28, corner_radius=0, **kwargs)
        self.pack_propagate(False)

        # GPU status
        gpu_text = self._detect_gpu()
        ctk.CTkLabel(self, text=gpu_text, font=("", 11),
                     text_color=TEXT_MUTED).pack(side="left", padx=SP_8)

        # FFmpeg version
        ffmpeg_ver = self._get_ffmpeg_version()
        ctk.CTkLabel(self, text=f"FFmpeg: {ffmpeg_ver}", font=("", 11),
                     text_color=TEXT_MUTED).pack(side="left", padx=SP_8)

        # App version
        ctk.CTkLabel(self, text=f"v{APP_VERSION}", font=("", 11),
                     text_color=TEXT_MUTED).pack(side="right", padx=SP_8)

    def _detect_gpu(self) -> str:
        try:
            result = subprocess.run(
                [shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=5,
            )
            if "h264_nvenc" in result.stdout:
                return "GPU: NVENC"
        except Exception:
            pass
        return "GPU: CPU-only"

    def _get_ffmpeg_version(self) -> str:
        try:
            result = subprocess.run(
                [shutil.which("ffmpeg") or "ffmpeg", "-version"],
                capture_output=True, text=True, timeout=5,
            )
            line = result.stdout.split("\n")[0]
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "version" and i + 1 < len(parts):
                    return parts[i + 1].split("-")[0]
        except Exception:
            pass
        return "not found"
