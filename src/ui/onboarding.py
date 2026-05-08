import shutil
import subprocess
import customtkinter as ctk
from src import config as cfg
from src.constants import *


class OnboardingDialog(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Welcome to yt2tiktok")
        self.geometry("500x400")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus_force()

        self._step = 0
        self._steps = [self._step_welcome, self._step_gpu, self._step_llm, self._step_done]

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=SP_24, pady=SP_24)

        self.nav_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.nav_frame.pack(fill="x", padx=SP_24, pady=(0, SP_16))

        self.back_btn = ctk.CTkButton(self.nav_frame, text="Back", width=80, command=self._prev,
                                       fg_color="transparent", border_width=1)
        self.back_btn.pack(side="left")
        self.next_btn = ctk.CTkButton(self.nav_frame, text="Next", width=80, command=self._next)
        self.next_btn.pack(side="right")

        self._show_step()

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _show_step(self):
        self._clear_content()
        self._steps[self._step]()
        self.back_btn.configure(state="normal" if self._step > 0 else "disabled")
        if self._step == len(self._steps) - 1:
            self.next_btn.configure(text="Get Started")
        else:
            self.next_btn.configure(text="Next")

    def _next(self):
        if self._step >= len(self._steps) - 1:
            cfg.set("onboarding_completed", True)
            self.destroy()
            return
        self._step += 1
        self._show_step()

    def _prev(self):
        if self._step > 0:
            self._step -= 1
            self._show_step()

    def _step_welcome(self):
        ctk.CTkLabel(self.content, text="Welcome to yt2tiktok!", font=("", FONT_HEADER, "bold")).pack(pady=(SP_16, SP_8))
        ctk.CTkLabel(self.content, text="Convert YouTube videos into TikTok-ready vertical clips\nwith karaoke-style captions.",
                     font=("", FONT_BODY), text_color=TEXT_SECONDARY, justify="center").pack(pady=SP_8)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            ctk.CTkLabel(self.content, text="FFmpeg detected", text_color=SUCCESS, font=("", FONT_LABEL)).pack(pady=SP_12)
        else:
            ctk.CTkLabel(self.content, text="FFmpeg not found! Please install it.", text_color=ERROR, font=("", FONT_LABEL)).pack(pady=SP_12)
            ctk.CTkLabel(self.content, text="winget install --id Gyan.FFmpeg.Essentials -e",
                         font=("Consolas", FONT_MUTED), text_color=TEXT_MUTED).pack()

    def _step_gpu(self):
        ctk.CTkLabel(self.content, text="GPU Status", font=("", FONT_HEADER, "bold")).pack(pady=(SP_16, SP_8))
        try:
            result = subprocess.run(
                [shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=5,
            )
            has_nvenc = "h264_nvenc" in result.stdout
        except Exception:
            has_nvenc = False

        if has_nvenc:
            ctk.CTkLabel(self.content, text="NVIDIA GPU detected (NVENC)", text_color=SUCCESS, font=("", FONT_LABEL)).pack(pady=SP_12)
            ctk.CTkLabel(self.content, text="Video encoding will use GPU acceleration for faster processing.",
                         text_color=TEXT_SECONDARY, font=("", FONT_BODY)).pack()
        else:
            ctk.CTkLabel(self.content, text="No GPU acceleration available", text_color=WARNING, font=("", FONT_LABEL)).pack(pady=SP_12)
            ctk.CTkLabel(self.content, text="Videos will encode using CPU (libx264). This works fine but is slower.",
                         text_color=TEXT_SECONDARY, font=("", FONT_BODY)).pack()

    def _step_llm(self):
        ctk.CTkLabel(self.content, text="LLM Setup (Optional)", font=("", FONT_HEADER, "bold")).pack(pady=(SP_16, SP_8))
        ctk.CTkLabel(self.content, text="An LLM improves caption keyword highlighting\nand enables Cliffhanger cut mode.",
                     font=("", FONT_BODY), text_color=TEXT_SECONDARY, justify="center").pack(pady=SP_4)
        ctk.CTkLabel(self.content, text="You can configure this later in Settings.",
                     font=("", FONT_BODY), text_color=TEXT_MUTED).pack(pady=SP_8)

    def _step_done(self):
        ctk.CTkLabel(self.content, text="You're all set!", font=("", FONT_HEADER, "bold")).pack(pady=(SP_16, SP_8))
        ctk.CTkLabel(self.content, text="Quick start:\n\n1. Paste a YouTube URL and click Fetch\n2. Choose your background and cut mode\n3. Click Start Clipping\n4. Upload to TikTok from the Upload tab",
                     font=("", FONT_BODY), text_color=TEXT_SECONDARY, justify="left").pack(pady=SP_8)
        ctk.CTkLabel(self.content, text="Keyboard shortcuts:\nCtrl+Enter: Start clipping\nCtrl+1/2/3: Switch tabs\nCtrl+L: Toggle log",
                     font=("Consolas", FONT_MUTED), text_color=TEXT_MUTED, justify="left").pack(pady=SP_8)
