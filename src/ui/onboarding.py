import shutil
import subprocess
import customtkinter as ctk
from src import config as cfg
from src.constants import *
from src.ui.overlay import Overlay


class OnboardingPanel(Overlay):
    def __init__(self, master):
        super().__init__(master, title="Setup Wizard")

        self._step = 0
        self._steps = [self._step_welcome, self._step_gpu, self._step_llm, self._step_done]

        self._body = ctk.CTkFrame(self.content, fg_color="transparent")
        self._body.pack(fill="both", expand=True)

        nav = ctk.CTkFrame(self.content, fg_color="transparent")
        nav.pack(fill="x", pady=(SP_12, 0))

        self._step_dots = ctk.CTkLabel(nav, text="", font=("", FONT_MUTED), text_color=TEXT_MUTED)
        self._step_dots.pack(side="left")

        self._next_btn = ctk.CTkButton(nav, text="Next", width=100, command=self._next)
        self._next_btn.pack(side="right")
        self._back_btn = ctk.CTkButton(nav, text="Back", width=80, command=self._prev,
                                        fg_color="transparent", border_width=1)
        self._back_btn.pack(side="right", padx=(0, SP_8))

        self._render_step()
        self.show()

    def close(self):
        cfg.set("onboarding_completed", True)
        super().close()

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()

    def _render_step(self):
        self._clear_body()
        self._steps[self._step]()
        self._back_btn.configure(state="normal" if self._step > 0 else "disabled")
        self._next_btn.configure(text="Get Started" if self._step == len(self._steps) - 1 else "Next")
        dots = "  ".join("●" if i == self._step else "○" for i in range(len(self._steps)))
        self._step_dots.configure(text=dots)

    def _next(self):
        if self._step >= len(self._steps) - 1:
            self.close()
            return
        self._step += 1
        self._render_step()

    def _prev(self):
        if self._step > 0:
            self._step -= 1
            self._render_step()

    def _step_welcome(self):
        b = self._body
        ctk.CTkLabel(b, text="Welcome to yt2tiktok!", font=("", FONT_HEADER, "bold")).pack(pady=(SP_32, SP_8))
        ctk.CTkLabel(b, text="Convert YouTube videos into TikTok-ready vertical clips\nwith karaoke-style captions.",
                     font=("", FONT_BODY), text_color=TEXT_SECONDARY, justify="center").pack(pady=SP_8)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            ctk.CTkLabel(b, text="FFmpeg detected", text_color=SUCCESS, font=("", FONT_LABEL)).pack(pady=SP_16)
        else:
            ctk.CTkLabel(b, text="FFmpeg not found! Please install it.", text_color=ERROR, font=("", FONT_LABEL)).pack(pady=SP_16)
            ctk.CTkLabel(b, text="winget install --id Gyan.FFmpeg.Essentials -e",
                         font=("Consolas", FONT_MUTED), text_color=TEXT_MUTED).pack()

    def _step_gpu(self):
        b = self._body
        ctk.CTkLabel(b, text="GPU Status", font=("", FONT_HEADER, "bold")).pack(pady=(SP_32, SP_8))
        try:
            result = subprocess.run(
                [shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=5,
            )
            has_nvenc = "h264_nvenc" in result.stdout
        except Exception:
            has_nvenc = False

        if has_nvenc:
            ctk.CTkLabel(b, text="NVIDIA GPU detected (NVENC)", text_color=SUCCESS, font=("", FONT_LABEL)).pack(pady=SP_16)
            ctk.CTkLabel(b, text="Video encoding will use GPU acceleration for faster processing.",
                         text_color=TEXT_SECONDARY, font=("", FONT_BODY)).pack()
        else:
            ctk.CTkLabel(b, text="No GPU acceleration available", text_color=WARNING, font=("", FONT_LABEL)).pack(pady=SP_16)
            ctk.CTkLabel(b, text="Videos will encode using CPU (libx264). This works fine but is slower.",
                         text_color=TEXT_SECONDARY, font=("", FONT_BODY)).pack()

    def _step_llm(self):
        b = self._body
        ctk.CTkLabel(b, text="LLM Setup (Optional)", font=("", FONT_HEADER, "bold")).pack(pady=(SP_32, SP_8))
        ctk.CTkLabel(b, text="An LLM improves caption keyword highlighting\nand enables Cliffhanger cut mode.",
                     font=("", FONT_BODY), text_color=TEXT_SECONDARY, justify="center").pack(pady=SP_4)
        ctk.CTkLabel(b, text="You can configure this later in Settings.",
                     font=("", FONT_BODY), text_color=TEXT_MUTED).pack(pady=SP_8)

    def _step_done(self):
        b = self._body
        ctk.CTkLabel(b, text="You're all set!", font=("", FONT_HEADER, "bold")).pack(pady=(SP_32, SP_8))
        ctk.CTkLabel(b, text="Quick start:\n\n1. Paste a YouTube URL and click Fetch\n2. Choose your background and cut mode\n3. Click Start Clipping\n4. Upload to TikTok from the Upload tab",
                     font=("", FONT_BODY), text_color=TEXT_SECONDARY, justify="left").pack(pady=SP_8)

        shortcuts = ctk.CTkFrame(b, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        shortcuts.pack(fill="x", pady=SP_12)
        ctk.CTkLabel(shortcuts, text="Keyboard shortcuts", font=("", FONT_LABEL, "bold")).pack(anchor="w", padx=SP_16, pady=(SP_8, SP_4))
        for key, action in [("Ctrl+Enter", "Start clipping"), ("Ctrl+1/2/3", "Switch tabs"), ("Ctrl+L", "Toggle log")]:
            row = ctk.CTkFrame(shortcuts, fg_color="transparent")
            row.pack(fill="x", padx=SP_16, pady=1)
            ctk.CTkLabel(row, text=key, font=("Consolas", FONT_MUTED), text_color=ACCENT_BLUE, width=100, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=action, font=("", FONT_MUTED), text_color=TEXT_MUTED).pack(side="left")
        # bottom padding
        ctk.CTkFrame(shortcuts, fg_color="transparent", height=SP_8).pack()
