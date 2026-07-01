import os
import threading
import customtkinter as ctk
from tkinter import messagebox, TclError
from PIL import Image

from src import clipper
from src import captioner
from src.constants import *
from src.llm_provider import LLMProvider
from src.preview import CaptionPreview
from src.ui.widgets import SectionHeader, Divider, FilePickerRow, Tooltip
from src.validators import validate_youtube_url, validate_file_path


def _ass_color_to_hex(ass_color: str) -> str:
    raw = ass_color.replace("&H", "").replace("&h", "")
    if len(raw) == 8:
        raw = raw[2:]
    b, g, r = raw[0:2], raw[2:4], raw[4:6]
    return f"#{r}{g}{b}"


class ClipTab:
    def __init__(self, parent, state, workers_module):
        self.state = state
        self.workers = workers_module
        self.parent = parent

        scroll = ctk.CTkScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)
        self.scroll = scroll

        # --- URL Input ---
        url_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        url_frame.pack(fill="x", padx=SP_12, pady=(SP_12, SP_4))
        ctk.CTkLabel(url_frame, text="YouTube URL", font=("", FONT_LABEL)).pack(anchor="w")
        url_row = ctk.CTkFrame(url_frame, fg_color="transparent")
        url_row.pack(fill="x")
        self.url_entry = ctk.CTkEntry(url_row, textvariable=state.url, placeholder_text="Paste YouTube URL here")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, SP_4))
        self.fetch_btn = ctk.CTkButton(url_row, text="Fetch", width=70, command=self._fetch_url_info)
        self.fetch_btn.pack(side="right")
        self.url_entry.bind("<Return>", lambda e: self._fetch_url_info())
        Tooltip(self.fetch_btn, "Fetch video info, thumbnail, and duration")

        # --- Preview Card ---
        self.preview_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        self.preview_card.pack(fill="x", padx=SP_12, pady=SP_4)
        self.preview_status = ctk.CTkLabel(self.preview_card, text="", text_color=TEXT_MUTED)
        self.preview_status.pack(padx=SP_12, pady=(SP_4, 0), anchor="w")
        preview_inner = ctk.CTkFrame(self.preview_card, fg_color="transparent")
        preview_inner.pack(fill="x", padx=SP_12, pady=SP_12)
        self.thumb_label = ctk.CTkLabel(preview_inner, text="", width=320, height=180)
        self.thumb_label.pack(side="left", padx=(0, SP_12))
        self.info_label = ctk.CTkLabel(
            preview_inner, text="Enter a URL and click Fetch", text_color=TEXT_MUTED,
            justify="left", wraplength=320, font=("", FONT_BODY),
        )
        self.info_label.pack(side="left", fill="both", expand=True, anchor="nw")

        # --- Local File ---
        file_row = FilePickerRow(scroll, "Or local MP4:", state.local_path,
                                 filetypes=[("MP4 files", "*.mp4")])
        file_row.pack(fill="x", padx=SP_12, pady=SP_4)

        # --- YouTube Cookies ---
        cookie_row = ctk.CTkFrame(scroll, fg_color="transparent")
        cookie_row.pack(fill="x", padx=SP_12, pady=SP_4)
        ctk.CTkLabel(cookie_row, text="YouTube cookies:").pack(side="left")
        help_btn = ctk.CTkButton(cookie_row, text="?", width=28, height=28, command=lambda: messagebox.showinfo(
            "YouTube Cookies",
            "For age-restricted or private videos, export your YouTube cookies:\n\n"
            "1. Install 'Get cookies.txt LOCALLY' browser extension\n"
            "2. Log into YouTube in a regular window\n"
            "3. Click the extension, set domain to youtube.com, export\n"
            "4. Select the exported file here",
        ))
        help_btn.pack(side="left", padx=(SP_4, 0))
        ctk.CTkLabel(cookie_row, textvariable=state.yt_cookie, text_color=TEXT_MUTED).pack(side="left", padx=SP_4, expand=True, fill="x")
        ctk.CTkButton(cookie_row, text="Browse", width=80,
                      command=self._browse_yt_cookie).pack(side="right")

        # --- Divider ---
        Divider(scroll).pack(fill="x", padx=SP_12, pady=SP_12)

        # --- Options Row ---
        opts_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        opts_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        left_opt = ctk.CTkFrame(opts_frame, fg_color="transparent")
        left_opt.pack(side="left", expand=True, fill="x")
        bg_label = ctk.CTkLabel(left_opt, text="Background", font=("", FONT_LABEL))
        bg_label.pack(anchor="w")
        ctk.CTkSegmentedButton(left_opt, values=["Blurred", "Black Bars"], variable=state.mode).pack(anchor="w", pady=(2, 0))
        Tooltip(bg_label, "Blurred: zoomed blurred background behind video\nBlack Bars: simple black padding")

        right_opt = ctk.CTkFrame(opts_frame, fg_color="transparent")
        right_opt.pack(side="right", expand=True, fill="x")
        cut_label = ctk.CTkLabel(right_opt, text="Cut Mode", font=("", FONT_LABEL))
        cut_label.pack(anchor="w")
        ctk.CTkSegmentedButton(right_opt, values=["Random", "Natural Pause", "Cliffhanger", "Best Moments"], variable=state.cut_mode).pack(anchor="w", pady=(2, 0))
        Tooltip(cut_label, "Random: fixed 60-70s clips\nNatural Pause: cuts at silence gaps\nCliffhanger: LLM picks suspenseful cut points\nBest Moments: LLM picks only the top viral-worthy clips (requires LLM)")

        # --- Best Moments options (visible only in that mode) ---
        self.opts_frame = opts_frame
        self.moments_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        ctk.CTkLabel(self.moments_frame, text="Clips to make").pack(side="left")
        ctk.CTkEntry(self.moments_frame, textvariable=state.moments_count, width=50).pack(side="left", padx=(SP_4, SP_12))
        ctk.CTkLabel(self.moments_frame, text="Min (s)").pack(side="left")
        ctk.CTkEntry(self.moments_frame, textvariable=state.moments_min_dur, width=50).pack(side="left", padx=(SP_4, SP_12))
        ctk.CTkLabel(self.moments_frame, text="Max (s)").pack(side="left")
        ctk.CTkEntry(self.moments_frame, textvariable=state.moments_max_dur, width=50).pack(side="left", padx=(SP_4, 0))
        state.cut_mode.trace_add("write", self._on_cut_mode_change)
        self._on_cut_mode_change()

        # --- Extra Options ---
        extra_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        extra_frame.pack(fill="x", padx=SP_12, pady=(SP_4, 0))
        ctk.CTkCheckBox(extra_frame, text="Keep original video after clipping",
                        variable=state.keep_source_video).pack(anchor="w")

        # --- Captions Section ---
        Divider(scroll).pack(fill="x", padx=SP_12, pady=SP_12)
        SectionHeader(scroll, "Captions").pack(anchor="w", padx=SP_12)
        ctk.CTkCheckBox(scroll, text="Enable auto-captions", variable=state.captions_enabled).pack(anchor="w", padx=SP_12, pady=(SP_4, SP_4))

        # --- Preset Selector ---
        ctk.CTkLabel(scroll, text="Style", font=("", FONT_BODY)).pack(anchor="w", padx=SP_12)
        preset_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        preset_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        self.preset_buttons = {}
        for name, p in captioner.PRESETS.items():
            color = _ass_color_to_hex(p["highlight_color"])
            def make_cmd(n=name):
                def cmd():
                    state.preset.set(n)
                    for bn, btn in self.preset_buttons.items():
                        if bn == n:
                            btn.configure(border_width=2, border_color=_ass_color_to_hex(captioner.PRESETS[bn]["highlight_color"]))
                        else:
                            btn.configure(border_width=0, border_color=BG_INPUT)
                return cmd
            btn = ctk.CTkButton(
                preset_frame, text=name, width=100, height=32,
                fg_color=BG_INPUT, hover_color="#3a3a3a",
                text_color=color, font=("", FONT_MUTED, "bold"),
                border_width=2 if name == state.preset.get() else 0,
                border_color=color if name == state.preset.get() else BG_INPUT,
                command=make_cmd(),
            )
            btn.pack(side="left", padx=3, pady=2)
            self.preset_buttons[name] = btn

        # --- Caption Position ---
        pos_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        pos_frame.pack(fill="x", padx=SP_12, pady=SP_4)
        ctk.CTkLabel(pos_frame, text="Position").pack(side="left")
        self.pos_label = ctk.CTkLabel(pos_frame, text=f"{int(state.caption_y.get() * 100)}%", width=40)
        self.pos_label.pack(side="right")
        ctk.CTkSlider(
            pos_frame, from_=0.64, to=0.84, variable=state.caption_y,
            command=lambda v: self.pos_label.configure(text=f"{int(float(v) * 100)}%"),
        ).pack(side="left", fill="x", expand=True, padx=SP_12)
        Tooltip(pos_frame, "Vertical position of captions (64-84% from top)")

        # --- Transcription Status ---
        ctk.CTkLabel(scroll, textvariable=state.transcription_status, text_color=TEXT_MUTED).pack(anchor="w", padx=SP_12)

        # --- Preview Button ---
        self.preview_btn = ctk.CTkButton(scroll, text="Preview Captions", command=self._on_preview, state="disabled")
        self.preview_btn.pack(pady=SP_4)

        # --- Action Buttons ---
        action_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        action_frame.pack(fill="x", padx=SP_12, pady=(SP_12, SP_4))
        self.clip_btn = ctk.CTkButton(
            action_frame, text="Start Clipping", height=40,
            font=("", 15, "bold"), command=self._on_clip,
        )
        self.clip_btn.pack(side="left", fill="x", expand=True)
        self.cancel_btn = ctk.CTkButton(
            action_frame, text="Cancel", height=40, width=100,
            fg_color=ERROR, hover_color="#dc2626",
            command=self._on_cancel,
        )
        # Cancel hidden initially

        # --- Open Folder Button (hidden until clipping done) ---
        self.open_folder_btn = ctk.CTkButton(
            scroll, text="Open Output Folder", height=32,
            fg_color="transparent", border_width=1,
            command=self._open_output_folder,
        )
        # Show after clipping completes
        state.clip_dir.trace_add("write", self._on_clip_dir_change)

    def _browse_yt_cookie(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(filetypes=[("Cookie files", "*.txt")])
        if path:
            self.state.yt_cookie.set(path)

    def _on_cut_mode_change(self, *_):
        if self.state.cut_mode.get() == "Best Moments":
            self.moments_frame.pack(fill="x", padx=SP_12, pady=SP_4, after=self.opts_frame)
        else:
            self.moments_frame.pack_forget()

    def _on_clip_dir_change(self, *_):
        if self.state.clip_dir.get():
            self.open_folder_btn.pack(fill="x", padx=SP_12, pady=(0, SP_12))
        else:
            self.open_folder_btn.pack_forget()

    def _open_output_folder(self):
        path = self.state.clip_dir.get()
        if path and os.path.isdir(path):
            os.startfile(path)

    def _get_llm(self):
        if not self.state.llm_enabled.get():
            return None
        return LLMProvider(
            provider=self.state.llm_provider.get(),
            api_key=self.state.llm_api_key.get(),
            model=self.state.llm_model.get(),
            base_url=self.state.llm_base_url.get(),
        )

    def _fetch_url_info(self):
        url = self.state.url.get().strip()
        if not url:
            return
        self.fetch_btn.configure(state="disabled", text="Fetching...")
        self.preview_status.configure(text="Fetching...", text_color=TEXT_MUTED)

        def _fetch():
            import yt_dlp
            import requests as req
            from io import BytesIO
            try:
                ydl_opts = {"quiet": True, "no_warnings": True}
                cookie = self.state.yt_cookie.get().strip()
                if cookie:
                    ydl_opts["cookiefile"] = cookie
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                title = info.get("title", "Unknown")
                duration = info.get("duration", 0)
                thumb_url = info.get("thumbnail", "")

                if duration >= 3600:
                    dur_str = f"{int(duration//3600)}:{int(duration%3600//60):02d}:{int(duration%60):02d}"
                else:
                    dur_str = f"{int(duration//60)}:{int(duration%60):02d}"
                est_clips = max(1, round(duration / 65))

                ctk_img = None
                pil_img = None
                if thumb_url:
                    try:
                        resp = req.get(thumb_url, timeout=10)
                        pil_img = Image.open(BytesIO(resp.content))
                        img_resized = pil_img.resize((320, 180), Image.LANCZOS)
                        ctk_img = ctk.CTkImage(light_image=img_resized, dark_image=img_resized, size=(320, 180))
                    except Exception:
                        pass

                def _update_ui():
                    self.state.title.set(clipper.sanitize_title(title))
                    self.state.thumb_ctk_image = ctk_img
                    self.state.thumb_pil_image = pil_img
                    if ctk_img:
                        self.thumb_label.configure(image=ctk_img, text="")
                    else:
                        self.thumb_label.configure(image=None, text="No thumbnail")
                    self.info_label.configure(
                        text=f"{title}\n{dur_str}  |  ~{est_clips} clips",
                        text_color=TEXT_PRIMARY,
                    )
                    self.preview_status.configure(text="")
                    self.fetch_btn.configure(state="normal", text="Fetch")
                    self.preview_btn.configure(state="normal")
                self.parent.winfo_toplevel().after(0, _update_ui)

            except Exception as e:
                def _show_error():
                    self.info_label.configure(text=f"Error: {str(e)[:80]}", text_color=ERROR)
                    self.preview_status.configure(text="")
                    self.fetch_btn.configure(state="normal", text="Fetch")
                    self.thumb_label.configure(image=None, text="")
                self.parent.winfo_toplevel().after(0, _show_error)

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_preview(self):
        vp = self.state.video_path.get()
        bg = self.state.thumb_pil_image
        if not vp and not bg:
            return
        sample = [
            {"word": "Sample", "start": 0, "end": 0.5, "confidence": 1.0},
            {"word": "caption", "start": 0.5, "end": 1.0, "confidence": 1.0},
            {"word": "text", "start": 1.0, "end": 1.5, "confidence": 1.0},
        ]
        def on_apply(y_pos, preset):
            self.state.caption_y.set(y_pos)
            self.state.preset.set(preset)
        vid_title = self.state.title.get() or "Sample Video Title"
        app = self.parent.winfo_toplevel()
        CaptionPreview(app, vp or "", sample, on_apply, y_var=self.state.caption_y,
                       background_image=bg if not vp else None, video_title=vid_title)

    def _on_clip(self):
        # Guard the keyboard shortcut (Ctrl+Return) which bypasses the
        # disabled button and could start a second concurrent job.
        if str(self.clip_btn.cget("state")) == "disabled":
            return
        url = self.state.url.get().strip()
        local_path = self.state.local_path.get().strip()
        if url:
            valid, err = validate_youtube_url(url)
            if not valid:
                messagebox.showerror("Invalid URL", err)
                return
        elif local_path:
            valid, err = validate_file_path(local_path, extensions=[".mp4"])
            if not valid:
                messagebox.showerror("Invalid File", err)
                return
        else:
            messagebox.showerror("Error", "Enter a YouTube URL or select a local file.")
            return
        cut = self.state.cut_mode.get().lower().replace(" ", "_")
        moments_count = moments_min = moments_max = 0
        if cut == "best_moments":
            llm = self._get_llm()
            if llm is None or not llm.is_available():
                messagebox.showerror(
                    "LLM Required",
                    "Best Moments mode needs a configured LLM.\n"
                    "Enable and set one up in Settings → LLM Settings.")
                return
            try:
                moments_count = int(self.state.moments_count.get())
                moments_min = int(self.state.moments_min_dur.get())
                moments_max = int(self.state.moments_max_dur.get())
                if moments_count < 1 or moments_min < 5 or moments_max <= moments_min:
                    raise ValueError
            except (ValueError, TypeError, TclError):
                messagebox.showerror(
                    "Invalid Settings",
                    "Check Best Moments settings: clips ≥ 1, min ≥ 5s, max > min.")
                return
        self.clip_btn.configure(state="disabled", text="Clipping...")
        self.cancel_btn.pack(side="right", padx=(SP_4, 0))
        self.preview_btn.configure(state="disabled")
        # Clear any stale cancel flag before the worker starts, so a cancel
        # requested between start() and the worker body can't be lost.
        self.workers.reset_cancel()
        threading.Thread(
            target=self.workers.clipper_worker,
            args=(
                self.state.url.get().strip(), self.state.local_path.get().strip(),
                self.state.yt_cookie.get().strip(), self.state.mode.get(), cut,
                self.state.captions_enabled.get(), self.state.preset.get(), self.state.caption_y.get(),
                self._get_llm(),
                moments_count, moments_min, moments_max,
                self.state, self.clip_btn, self.preview_btn, self.cancel_btn,
            ),
            daemon=True,
        ).start()

    def _on_cancel(self):
        self.workers.request_cancel()
        self.cancel_btn.pack_forget()
        self.clip_btn.configure(state="normal", text="Start Clipping")
        self.preview_btn.configure(state="normal")
