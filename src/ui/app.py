import customtkinter as ctk
from tkinter import messagebox

from src import clipper
from src import config as cfg
from src import workers
from src import updater
from src.constants import *
from src.app_state import AppState
from src.logger import setup_logging, install_crash_handler
from src.ui.clip_tab import ClipTab
from src.ui.upload_tab import UploadTab
from src.ui.settings_tab import SettingsTab
from src.ui.log_panel import LogPanel
from src.ui.status_bar import StatusBar


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        setup_logging()
        install_crash_handler()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"yt2tiktok v{APP_VERSION}")
        self.geometry("750x900")
        self.minsize(650, 750)

        # Try to set icon
        try:
            from pathlib import Path
            icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.ico"
            if icon_path.exists():
                self.iconbitmap(str(icon_path))
        except Exception:
            pass

        self.app_state = AppState()

        # Update banner (hidden by default)
        self.update_banner = ctk.CTkFrame(self, fg_color=ACCENT_BLUE, height=32, corner_radius=0)
        self.update_label = ctk.CTkLabel(self.update_banner, text="", font=("", FONT_MUTED))
        self.update_label.pack(side="left", padx=SP_12)
        ctk.CTkButton(self.update_banner, text="Dismiss", width=60, height=24,
                      fg_color="transparent", border_width=1, font=("", 11),
                      command=self.update_banner.pack_forget).pack(side="right", padx=SP_8)

        # Tab view
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=SP_12, pady=(SP_12, 0))
        self.tabview.add("Clip")
        self.tabview.add("Upload")
        self.tabview.add("Settings")

        # Build tabs — force geometry update between each to prevent flicker
        self.clip_tab = ClipTab(self.tabview.tab("Clip"), self.app_state, workers)
        self.update_idletasks()
        self.upload_tab = UploadTab(self.tabview.tab("Upload"), self.app_state, workers)
        self.update_idletasks()
        self.settings_tab = SettingsTab(self.tabview.tab("Settings"), self.app_state, self)
        self.update_idletasks()

        # Log panel
        self.log_panel = LogPanel(self)
        self.log_panel.pack(fill="x", padx=SP_12, pady=(SP_4, SP_4))

        # Status bar
        self.status_bar = StatusBar(self)
        self.status_bar.pack(fill="x", side="bottom")

        # Debounced tab switching to prevent rapid-click glitches
        self._tab_switch_pending = False
        def _safe_set_tab(name):
            if self._tab_switch_pending:
                return
            self._tab_switch_pending = True
            self.tabview.set(name)
            self.after(150, lambda: setattr(self, '_tab_switch_pending', False))

        # Keyboard shortcuts
        self.bind("<Control-Return>", lambda e: self.clip_tab._on_clip())
        self.bind("<Control-Key-1>", lambda e: _safe_set_tab("Clip"))
        self.bind("<Control-Key-2>", lambda e: _safe_set_tab("Upload"))
        self.bind("<Control-Key-3>", lambda e: _safe_set_tab("Settings"))
        self.bind("<Control-l>", lambda e: self.log_panel._toggle())

        # Check FFmpeg
        if not clipper.FFMPEG_CMD:
            messagebox.showerror(
                "FFmpeg Missing",
                "FFmpeg must be installed and in PATH.\n\n"
                "Install: winget install --id Gyan.FFmpeg.Essentials -e",
            )

        # First-run onboarding
        if not cfg.get("onboarding_completed"):
            self.after(500, self._show_onboarding)

        # Check for updates (non-blocking)
        updater.check_for_update(self._on_update_check)

        # Start queue polling
        self._poll_queues()

    def _show_onboarding(self):
        from src.ui.onboarding import OnboardingPanel
        OnboardingPanel(self)

    def _on_update_check(self, version, url):
        if version:
            def _show():
                self.update_label.configure(text=f"Update available: {version}")
                self.update_banner.pack(fill="x", before=self.tabview)
            self.after(0, _show)

    def _poll_queues(self):
        while not workers.log_queue.empty():
            msg = workers.log_queue.get()
            self.log_panel.append_log(msg)

        while not workers.progress_queue.empty():
            msg = workers.progress_queue.get()
            if msg.startswith("progress:"):
                try:
                    parts = msg.split(":")
                    clip_info = parts[1]
                    pct = int(parts[2])
                    self.log_panel.set_progress(pct / 100)
                    self.log_panel.set_progress_text(f"Encoding: {clip_info} clips ({pct}%)")
                except (IndexError, ValueError):
                    pass
            elif msg == "downloading":
                self.log_panel.progress_bar.configure(mode="indeterminate")
                self.log_panel.progress_bar.start()
                self.log_panel.set_progress_text("Downloading...")
            elif msg == "done":
                self.log_panel.progress_bar.stop()
                self.log_panel.progress_bar.configure(mode="determinate")
                self.log_panel.set_progress(1.0)
                self.log_panel.set_progress_text("Complete")
            elif msg == "":
                self.log_panel.set_progress_text("")
            else:
                self.log_panel.set_progress_text(msg)

        self.after(100, self._poll_queues)
