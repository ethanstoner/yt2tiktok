import os
import queue
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path
from PIL import Image

from src import clipper
from src import uploader
from src import transcriber
from src import captioner
from src import config as cfg
from src.llm_provider import LLMProvider, PROVIDERS, detect_ollama_url
from src.preview import CaptionPreview

log_queue: queue.Queue[str] = queue.Queue()
progress_queue: queue.Queue[str] = queue.Queue()


def log(msg: str):
    log_queue.put(msg)


def progress(msg: str):
    progress_queue.put(msg)


def clipper_worker(
    url, local_path, cookie_file, mode, cut_mode,
    captions_enabled, preset_name, y_position,
    llm_instance,
    clip_dir_var, title_var, transcript_var, highlight_var,
    video_path_var, clip_btn, transcription_status, preview_btn,
):
    try:
        if url:
            video_path, title = clipper.download_video(
                url, log_fn=log, progress_fn=progress, cookiefile=cookie_file or None,
            )
        elif local_path:
            video_path = local_path
            title = clipper.sanitize_title(Path(local_path).stem)
        else:
            log("No URL or file provided.")
            return

        video_path_var.set(video_path)

        duration = clipper.get_video_duration(video_path)
        est_clips = int(duration / 65) + 1
        if duration > clipper.WARN_DURATION or est_clips > clipper.WARN_CLIPS:
            log(f"Warning: Video is {duration/60:.0f} min, ~{est_clips} clips.")
            result = [None]
            event = threading.Event()
            def ask():
                result[0] = messagebox.askyesno(
                    "Long Video",
                    f"This video is {duration/60:.0f} minutes and will produce ~{est_clips} clips.\n\nContinue?",
                )
                event.set()
            clip_btn.winfo_toplevel().after(0, ask)
            event.wait()
            if not result[0]:
                log("Clipping cancelled by user.")
                return

        transcript = None
        highlight_indices = []
        if captions_enabled or cut_mode != "random":
            transcription_status.set("Transcribing...")
            try:
                transcript = transcriber.transcribe(video_path, url=url if url else None, log_fn=log)
                transcription_status.set(f"{len(transcript)} words detected")
                transcript_var.set(str(len(transcript)))

                preview_btn.configure(state="normal")
            except Exception as e:
                log(f"Transcription failed: {e}")
                transcription_status.set("Transcription failed")
                transcript = None
                if cut_mode != "random":
                    log("Falling back to random cuts")
                    cut_mode = "random"

        llm = llm_instance if llm_instance and llm_instance.is_available() else None
        cuts = clipper.calculate_cut_points(duration, cut_mode, transcript, llm)

        caption_ass_map = {}
        if captions_enabled and transcript:
            target_dir = str(clipper.CLIPS_DIR / title)
            os.makedirs(target_dir, exist_ok=True)
            for i, (cut_start, cut_dur) in enumerate(cuts, 1):
                cut_end = cut_start + cut_dur
                clip_transcript, _ = captioner.slice_transcript(
                    transcript, cut_start, cut_end, [],
                )
                if clip_transcript:
                    # Detect keywords per-clip so every clip gets highlights
                    if llm and llm.is_available():
                        clip_highlights = captioner.detect_keywords_llm(clip_transcript, llm)
                    else:
                        clip_highlights = captioner.detect_keywords_heuristic(clip_transcript)
                    ass_path = os.path.join(target_dir, f"_caption_{i}.ass")
                    captioner.generate_caption_ass(
                        clip_transcript, preset_name, y_position,
                        clip_highlights, ass_path,
                    )
                    caption_ass_map[i] = ass_path

        target_dir, total = clipper.split_video(
            video_path, title, mode=mode.lower(),
            cut_mode=cut_mode, transcript=transcript, llm=llm,
            caption_ass_map=caption_ass_map,
            cuts=cuts,
            log_fn=log, progress_fn=progress,
        )

        for ass_path in caption_ass_map.values():
            try:
                os.unlink(ass_path)
            except OSError:
                pass

        clip_dir_var.set(target_dir)
        title_var.set(title)
        if captions_enabled and transcript:
            transcription_status.set("Captions ready")
        log(f"Clipping complete: {total} clips in {target_dir}")

    except Exception as e:
        log(f"Error: {e}")
    finally:
        clip_btn.configure(state="normal")


def uploader_worker(clips_dir, title, total_clips, cookie_file, caption_template, start_time, interval, headless, upload_btn):
    try:
        interval_hours = float(interval)
    except ValueError:
        log("Invalid interval value.")
        upload_btn.configure(state="normal")
        return
    try:
        successful, total = uploader.upload_clips(
            clips_dir=clips_dir, title=title, total_clips=total_clips,
            cookie_file=cookie_file, caption_template=caption_template,
            start_time_str=start_time, interval_hours=interval_hours,
            headless=headless, log_fn=log,
        )
        log(f"Upload complete: {successful}/{total} scheduled.")
    except Exception as e:
        log(f"Upload error: {e}")
    finally:
        upload_btn.configure(state="normal")


def verify_worker(cookie_file, headless, status_var):
    status_var.set("Verifying...")
    username = uploader.verify_cookies(cookie_file, headless=headless, log_fn=log)
    if username:
        status_var.set(f"Logged in: @{username}")
    else:
        status_var.set("Verification failed")


def _ass_color_to_hex(ass_color: str) -> str:
    """Convert ASS BGR color '&H00BBGGRR' to hex '#RRGGBB'."""
    raw = ass_color.replace("&H", "").replace("&h", "")
    if len(raw) == 8:
        raw = raw[2:]  # strip alpha
    b, g, r = raw[0:2], raw[2:4], raw[4:6]
    return f"#{r}{g}{b}"


def build_gui():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = ctk.CTk()
    app.title("yt2tiktok")
    app.geometry("750x900")
    app.minsize(650, 750)

    # ═══ SHARED STATE ════════════════════════════════════════════════════
    url_var = ctk.StringVar()
    local_path_var = ctk.StringVar()
    yt_cookie_var = ctk.StringVar()
    video_path_var = ctk.StringVar()
    clip_dir_var = ctk.StringVar()
    title_var = ctk.StringVar()
    transcript_var = ctk.StringVar()
    highlight_var = ctk.StringVar()
    mode_var = ctk.StringVar(value="Blurred")
    cut_mode_var = ctk.StringVar(value="Natural Pause")
    captions_var = ctk.BooleanVar(value=True)
    preset_var = ctk.StringVar(value="Opus Clean")
    caption_y_var = ctk.DoubleVar(value=0.73)
    transcription_status = ctk.StringVar(value="")

    # Upload vars
    tk_cookie_var = ctk.StringVar(value=uploader.load_last_cookie_path())
    tk_status_var = ctk.StringVar()
    headless_var = ctk.BooleanVar(value=True)
    caption_template_var = ctk.StringVar(value="{title} - Part {part}")
    start_var = ctk.StringVar(value="10:00")
    interval_var = ctk.StringVar(value="2")

    # LLM vars
    llm_enabled_var = ctk.BooleanVar(value=cfg.get("llm_enabled", False))
    provider_var = ctk.StringVar(value=cfg.get("llm_provider", "groq"))
    api_key_var = ctk.StringVar(value=cfg.get("llm_api_key", ""))
    model_var = ctk.StringVar(value=cfg.get("llm_model", ""))
    base_url_var = ctk.StringVar(value=cfg.get("llm_base_url", ""))

    # Thumbnail image holders (CTkImage for display, PIL Image for preview)
    thumb_image = [None]
    thumb_pil = [None]

    # ═══ TAB VIEW ════════════════════════════════════════════════════════
    tabview = ctk.CTkTabview(app)
    tabview.pack(fill="both", expand=True, padx=10, pady=(10, 0))
    tabview.add("Clip")
    tabview.add("Upload")
    tabview.add("Settings")

    def fetch_url_info():
        """Fetch YouTube video metadata and show preview card."""
        url = url_var.get().strip()
        if not url:
            return
        fetch_btn.configure(state="disabled")
        preview_status.configure(text="Fetching...", text_color="gray")

        def _fetch():
            import yt_dlp
            import requests as req
            from io import BytesIO
            try:
                ydl_opts = {"quiet": True, "no_warnings": True}
                cookie = yt_cookie_var.get().strip()
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
                    title_var.set(clipper.sanitize_title(title))
                    thumb_image[0] = ctk_img
                    thumb_pil[0] = pil_img
                    if ctk_img:
                        thumb_label.configure(image=ctk_img, text="")
                    else:
                        thumb_label.configure(image=None, text="No thumbnail")
                    info_label.configure(
                        text=f"{title}\n{dur_str}  •  ~{est_clips} clips",
                        text_color="white",
                    )
                    preview_status.configure(text="")
                    fetch_btn.configure(state="normal")
                    preview_btn.configure(state="normal")
                app.after(0, _update_ui)

            except Exception as e:
                def _show_error():
                    info_label.configure(text=f"Error: {str(e)[:80]}", text_color="#ff4444")
                    preview_status.configure(text="")
                    fetch_btn.configure(state="normal")
                    thumb_label.configure(image=None, text="")
                app.after(0, _show_error)

        threading.Thread(target=_fetch, daemon=True).start()

    # ═══ CLIP TAB ════════════════════════════════════════════════════════
    clip_tab = tabview.tab("Clip")
    clip_scroll = ctk.CTkScrollableFrame(clip_tab)
    clip_scroll.pack(fill="both", expand=True)

    # URL input row
    url_frame = ctk.CTkFrame(clip_scroll, fg_color="transparent")
    url_frame.pack(fill="x", padx=10, pady=(10, 5))
    ctk.CTkLabel(url_frame, text="YouTube URL").pack(anchor="w")
    url_row = ctk.CTkFrame(url_frame, fg_color="transparent")
    url_row.pack(fill="x")
    url_entry = ctk.CTkEntry(url_row, textvariable=url_var, placeholder_text="Paste YouTube URL here")
    url_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
    fetch_btn = ctk.CTkButton(url_row, text="Fetch", width=70, command=fetch_url_info)
    fetch_btn.pack(side="right")
    url_entry.bind("<Return>", lambda e: fetch_url_info())

    # Preview card
    preview_card = ctk.CTkFrame(clip_scroll, fg_color="#1e1e1e", corner_radius=10)
    preview_card.pack(fill="x", padx=10, pady=5)
    preview_status = ctk.CTkLabel(preview_card, text="", text_color="gray")
    preview_status.pack(padx=10, pady=(5, 0), anchor="w")
    preview_inner = ctk.CTkFrame(preview_card, fg_color="transparent")
    preview_inner.pack(fill="x", padx=10, pady=10)
    thumb_label = ctk.CTkLabel(preview_inner, text="", width=320, height=180)
    thumb_label.pack(side="left", padx=(0, 10))
    info_label = ctk.CTkLabel(
        preview_inner, text="Enter a URL and click Fetch", text_color="gray",
        justify="left", wraplength=320, font=("", 13),
    )
    info_label.pack(side="left", fill="both", expand=True, anchor="nw")

    # Local file alternative
    file_frame = ctk.CTkFrame(clip_scroll, fg_color="transparent")
    file_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(file_frame, text="Or local MP4:").pack(side="left")
    ctk.CTkLabel(file_frame, textvariable=local_path_var, text_color="gray").pack(side="left", padx=5, expand=True, fill="x")
    ctk.CTkButton(file_frame, text="Browse", width=80, command=lambda: local_path_var.set(
        filedialog.askopenfilename(filetypes=[("MP4 files", "*.mp4")]) or ""
    )).pack(side="right")

    # YouTube cookies
    cookie_frame = ctk.CTkFrame(clip_scroll, fg_color="transparent")
    cookie_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(cookie_frame, text="YouTube cookies:").pack(side="left")
    ctk.CTkButton(cookie_frame, text="?", width=28, height=28, command=lambda: messagebox.showinfo(
        "YouTube Cookies",
        "For age-restricted or private videos, export your YouTube cookies:\n\n"
        "1. Install 'Get cookies.txt LOCALLY' browser extension\n"
        "2. Log into YouTube in a regular window\n"
        "3. Click the extension, set domain to youtube.com, export\n"
        "4. Select the exported file here",
    )).pack(side="left", padx=(5, 0))
    ctk.CTkLabel(cookie_frame, textvariable=yt_cookie_var, text_color="gray").pack(side="left", padx=5, expand=True, fill="x")
    ctk.CTkButton(cookie_frame, text="Browse", width=80, command=lambda: yt_cookie_var.set(
        filedialog.askopenfilename(filetypes=[("Cookie files", "*.txt")]) or ""
    )).pack(side="right")

    # Clip options
    ctk.CTkFrame(clip_scroll, height=1, fg_color="gray30").pack(fill="x", padx=10, pady=10)
    opts_frame = ctk.CTkFrame(clip_scroll, fg_color="transparent")
    opts_frame.pack(fill="x", padx=10, pady=5)
    left_opt = ctk.CTkFrame(opts_frame, fg_color="transparent")
    left_opt.pack(side="left", expand=True, fill="x")
    ctk.CTkLabel(left_opt, text="Background").pack(anchor="w")
    ctk.CTkSegmentedButton(left_opt, values=["Blurred", "Black Bars"], variable=mode_var).pack(anchor="w", pady=(2, 0))
    right_opt = ctk.CTkFrame(opts_frame, fg_color="transparent")
    right_opt.pack(side="right", expand=True, fill="x")
    ctk.CTkLabel(right_opt, text="Cut Mode").pack(anchor="w")
    ctk.CTkSegmentedButton(right_opt, values=["Random", "Natural Pause", "Cliffhanger"], variable=cut_mode_var).pack(anchor="w", pady=(2, 0))

    # Caption section
    ctk.CTkFrame(clip_scroll, height=1, fg_color="gray30").pack(fill="x", padx=10, pady=10)
    ctk.CTkLabel(clip_scroll, text="Captions", font=("", 16, "bold")).pack(anchor="w", padx=10)
    ctk.CTkCheckBox(clip_scroll, text="Enable auto-captions", variable=captions_var).pack(anchor="w", padx=10, pady=(5, 5))

    # Visual preset selector
    ctk.CTkLabel(clip_scroll, text="Style", font=("", 13)).pack(anchor="w", padx=10)
    preset_frame = ctk.CTkFrame(clip_scroll, fg_color="transparent")
    preset_frame.pack(fill="x", padx=10, pady=5)
    preset_buttons = {}
    for name, p in captioner.PRESETS.items():
        color = _ass_color_to_hex(p["highlight_color"])
        def make_cmd(n=name):
            def cmd():
                preset_var.set(n)
                for bn, btn in preset_buttons.items():
                    if bn == n:
                        btn.configure(border_width=2, border_color=_ass_color_to_hex(captioner.PRESETS[bn]["highlight_color"]))
                    else:
                        btn.configure(border_width=0, border_color="#2a2a2a")
            return cmd
        btn = ctk.CTkButton(
            preset_frame, text=name, width=100, height=32,
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            text_color=color, font=("", 12, "bold"),
            border_width=2 if name == "Opus Clean" else 0,
            border_color=color if name == "Opus Clean" else "#2a2a2a",
            command=make_cmd(),
        )
        btn.pack(side="left", padx=3, pady=2)
        preset_buttons[name] = btn

    # Caption position slider
    pos_frame = ctk.CTkFrame(clip_scroll, fg_color="transparent")
    pos_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(pos_frame, text="Position").pack(side="left")
    pos_label = ctk.CTkLabel(pos_frame, text=f"{int(caption_y_var.get() * 100)}%", width=40)
    pos_label.pack(side="right")
    pos_slider = ctk.CTkSlider(
        pos_frame, from_=0.64, to=0.84, variable=caption_y_var,
        command=lambda v: pos_label.configure(text=f"{int(float(v) * 100)}%"),
    )
    pos_slider.pack(side="left", fill="x", expand=True, padx=10)

    # Transcription status
    ctk.CTkLabel(clip_scroll, textvariable=transcription_status, text_color="gray").pack(anchor="w", padx=10)

    # Preview button
    def on_preview():
        vp = video_path_var.get()
        bg = thumb_pil[0]
        if not vp and not bg:
            return
        sample = [
            {"word": "Sample", "start": 0, "end": 0.5, "confidence": 1.0},
            {"word": "caption", "start": 0.5, "end": 1.0, "confidence": 1.0},
            {"word": "text", "start": 1.0, "end": 1.5, "confidence": 1.0},
        ]
        def on_apply(y_pos, preset):
            caption_y_var.set(y_pos)
            preset_var.set(preset)
        vid_title = title_var.get() or "Sample Video Title"
        CaptionPreview(app, vp or "", sample, on_apply, y_var=caption_y_var, background_image=bg if not vp else None, video_title=vid_title)

    preview_btn = ctk.CTkButton(clip_scroll, text="Preview Captions", command=on_preview, state="disabled")
    preview_btn.pack(pady=5)

    # _get_llm helper
    def _get_llm():
        if not llm_enabled_var.get():
            return None
        return LLMProvider(
            provider=provider_var.get(),
            api_key=api_key_var.get(),
            model=model_var.get(),
            base_url=base_url_var.get(),
        )

    # Start Clipping button
    def on_clip():
        clip_btn.configure(state="disabled")
        preview_btn.configure(state="disabled")
        cut = cut_mode_var.get().lower().replace(" ", "_")
        threading.Thread(
            target=clipper_worker,
            args=(
                url_var.get().strip(), local_path_var.get().strip(),
                yt_cookie_var.get().strip(), mode_var.get(), cut,
                captions_var.get(), preset_var.get(), caption_y_var.get(),
                _get_llm(),
                clip_dir_var, title_var, transcript_var, highlight_var,
                video_path_var, clip_btn, transcription_status, preview_btn,
            ),
            daemon=True,
        ).start()

    clip_btn = ctk.CTkButton(clip_scroll, text="Start Clipping", height=40, font=("", 15, "bold"), command=on_clip)
    clip_btn.pack(fill="x", padx=10, pady=(10, 10))

    # ═══ UPLOAD TAB ══════════════════════════════════════════════════════
    upload_tab = tabview.tab("Upload")
    upload_scroll = ctk.CTkScrollableFrame(upload_tab)
    upload_scroll.pack(fill="both", expand=True)

    ctk.CTkLabel(upload_scroll, text="TikTok Upload", font=("", 18, "bold")).pack(pady=(10, 10))

    # Clip folder
    folder_frame = ctk.CTkFrame(upload_scroll, fg_color="transparent")
    folder_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(folder_frame, text="Clip folder:").pack(side="left")
    ctk.CTkLabel(folder_frame, textvariable=clip_dir_var, text_color="gray").pack(side="left", padx=5, expand=True, fill="x")
    ctk.CTkButton(folder_frame, text="Browse", width=80, command=lambda: clip_dir_var.set(
        filedialog.askdirectory() or clip_dir_var.get()
    )).pack(side="right")

    # TikTok cookies
    tk_cookie_frame = ctk.CTkFrame(upload_scroll, fg_color="transparent")
    tk_cookie_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(tk_cookie_frame, text="TikTok cookies:").pack(side="left")
    ctk.CTkLabel(tk_cookie_frame, textvariable=tk_cookie_var, text_color="gray").pack(side="left", padx=5, expand=True, fill="x")
    ctk.CTkButton(tk_cookie_frame, text="Browse", width=80, command=lambda: tk_cookie_var.set(
        filedialog.askopenfilename(filetypes=[("Cookie files", "*.txt")]) or ""
    )).pack(side="right")
    ctk.CTkButton(tk_cookie_frame, text="Verify", width=60, command=lambda: threading.Thread(
        target=verify_worker, args=(tk_cookie_var.get(), headless_var.get(), tk_status_var), daemon=True,
    ).start()).pack(side="right", padx=5)

    # Dynamic status color
    tk_status_label = ctk.CTkLabel(upload_scroll, textvariable=tk_status_var, text_color="gray")
    tk_status_label.pack(padx=10, anchor="w")

    def _update_status_color(*_):
        text = tk_status_var.get().lower()
        if "logged in" in text:
            tk_status_label.configure(text_color="green")
        elif "failed" in text or "error" in text:
            tk_status_label.configure(text_color="#ff4444")
        else:
            tk_status_label.configure(text_color="gray")
    tk_status_var.trace_add("write", _update_status_color)

    def on_cookie_selected(*_):
        path = tk_cookie_var.get()
        if path:
            uploader.save_last_cookie_path(path)
    tk_cookie_var.trace_add("write", on_cookie_selected)

    # Caption template
    ctk.CTkFrame(upload_scroll, height=1, fg_color="gray30").pack(fill="x", padx=10, pady=10)
    ctk.CTkLabel(upload_scroll, text="Caption template").pack(anchor="w", padx=10)
    ctk.CTkEntry(upload_scroll, textvariable=caption_template_var, placeholder_text="{title} - Part {part}").pack(fill="x", padx=10, pady=(0, 5))
    ctk.CTkLabel(upload_scroll, text="Placeholders: {title}, {part}, {total}", text_color="gray", font=("", 11)).pack(anchor="w", padx=10)

    # Schedule settings
    ctk.CTkFrame(upload_scroll, height=1, fg_color="gray30").pack(fill="x", padx=10, pady=10)
    schedule_frame = ctk.CTkFrame(upload_scroll, fg_color="transparent")
    schedule_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(schedule_frame, text="Start time:").pack(side="left")
    ctk.CTkEntry(schedule_frame, textvariable=start_var, width=80, placeholder_text="HH:MM").pack(side="left", padx=5)
    ctk.CTkLabel(schedule_frame, text="Interval (hrs):").pack(side="left", padx=(15, 0))
    ctk.CTkEntry(schedule_frame, textvariable=interval_var, width=60).pack(side="left", padx=5)

    # Headless
    ctk.CTkCheckBox(upload_scroll, text="Headless mode (uncheck to debug)", variable=headless_var).pack(anchor="w", padx=10, pady=5)

    # Troubleshooting tips (properly collapsible)
    troubleshoot_frame_ref = [None]
    def toggle_troubleshoot():
        if troubleshoot_frame_ref[0] is not None:
            troubleshoot_frame_ref[0].destroy()
            troubleshoot_frame_ref[0] = None
            troubleshoot_btn.configure(text="Show Troubleshooting Tips")
        else:
            f = ctk.CTkFrame(upload_scroll, fg_color="#2a2a2a", corner_radius=8)
            f.pack(fill="x", padx=10, pady=5, before=upload_btn)
            ctk.CTkLabel(f, text=(
                "If verification fails or uploads get CAPTCHA blocked:\n"
                "1. Uncheck 'Headless mode' and try again\n"
                "2. Solve any CAPTCHA or login prompt in that window\n"
                "3. Close the window, re-export cookies, and try again\n"
                "4. Cookies expire regularly - re-export when sessions fail"
            ), justify="left", wraplength=580).pack(padx=10, pady=10)
            troubleshoot_frame_ref[0] = f
            troubleshoot_btn.configure(text="Hide Troubleshooting Tips")

    troubleshoot_btn = ctk.CTkButton(
        upload_scroll, text="Show Troubleshooting Tips", width=200, height=28,
        fg_color="transparent", border_width=1, command=toggle_troubleshoot,
    )
    troubleshoot_btn.pack(anchor="w", padx=10, pady=(5, 5))

    # Upload button
    def on_upload():
        if not tk_cookie_var.get():
            messagebox.showerror("Error", "Select a TikTok cookie file first.")
            return
        if not clip_dir_var.get() or not os.path.isdir(clip_dir_var.get()):
            messagebox.showerror("Error", "Select a valid clip folder.")
            return
        upload_btn.configure(state="disabled")
        clip_count = len([f for f in os.listdir(clip_dir_var.get()) if f.endswith(".mp4") and "_clip_" in f])
        threading.Thread(
            target=uploader_worker,
            args=(clip_dir_var.get(), title_var.get(), clip_count, tk_cookie_var.get(),
                  caption_template_var.get(), start_var.get(), interval_var.get(),
                  headless_var.get(), upload_btn),
            daemon=True,
        ).start()

    upload_btn = ctk.CTkButton(upload_scroll, text="Upload to TikTok", height=40, font=("", 15, "bold"), command=on_upload)
    upload_btn.pack(fill="x", padx=10, pady=(10, 10))

    # ═══ SETTINGS TAB ════════════════════════════════════════════════════
    settings_tab = tabview.tab("Settings")
    settings_scroll = ctk.CTkScrollableFrame(settings_tab)
    settings_scroll.pack(fill="both", expand=True)

    ctk.CTkLabel(settings_scroll, text="LLM Configuration", font=("", 18, "bold")).pack(pady=(10, 10))
    ctk.CTkCheckBox(settings_scroll, text="Enable LLM (keyword detection + Cliffhanger mode)", variable=llm_enabled_var).pack(anchor="w", padx=10, pady=5)

    prov_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
    prov_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(prov_frame, text="Provider:").pack(side="left")
    ctk.CTkOptionMenu(prov_frame, values=["groq", "openai", "gemini", "claude", "ollama", "custom"], variable=provider_var).pack(side="left", padx=5)

    key_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
    key_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(key_frame, text="API Key:").pack(side="left")
    ctk.CTkEntry(key_frame, textvariable=api_key_var, show="*").pack(side="left", padx=5, fill="x", expand=True)

    # Model selector with dropdown + fetch
    mod_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
    mod_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(mod_frame, text="Model:").pack(side="left")
    model_status = ctk.CTkLabel(mod_frame, text="", text_color="gray", font=("", 11))
    model_status.pack(side="right")

    # Default model list from provider
    default_model = PROVIDERS.get(provider_var.get(), {}).get("default_model", "")
    initial_models = [default_model] if default_model else ["(default)"]

    model_dropdown = ctk.CTkOptionMenu(mod_frame, values=initial_models, variable=model_var, width=250)
    model_dropdown.pack(side="left", padx=5)

    fetch_models_btn = ctk.CTkButton(mod_frame, text="Fetch Models", width=100, height=28, command=lambda: None)
    fetch_models_btn.pack(side="left", padx=5)

    def _fetch_models():
        fetch_models_btn.configure(state="disabled")
        model_status.configure(text="Fetching...", text_color="gray")
        provider = provider_var.get()
        api_key = api_key_var.get()
        base_url = base_url_var.get()

        def _do_fetch():
            llm = LLMProvider(provider=provider, api_key=api_key, base_url=base_url)
            models = llm.list_models()

            def _update():
                fetch_models_btn.configure(state="normal")
                if models:
                    model_dropdown.configure(values=models)
                    # If current model not in list, select first
                    if model_var.get() not in models:
                        model_var.set(models[0])
                    model_status.configure(text=f"{len(models)} models", text_color="green")
                else:
                    model_status.configure(text="No models found", text_color="#ff4444")
            app.after(0, _update)

        threading.Thread(target=_do_fetch, daemon=True).start()

    fetch_models_btn.configure(command=_fetch_models)

    # Auto-fetch models when provider changes
    def _on_provider_change(*_):
        provider = provider_var.get()
        info = PROVIDERS.get(provider, {})
        default = info.get("default_model", "")
        # Reset model to default for new provider
        model_var.set(default)
        model_dropdown.configure(values=[default] if default else ["(default)"])
        model_status.configure(text="")
        # Auto-detect Ollama port and fetch models
        if provider == "ollama":
            def _detect_and_fetch():
                detected = detect_ollama_url()
                def _apply():
                    if detected:
                        base_url_var.set(detected)
                        model_status.configure(text=f"Found Ollama on {detected.replace('/v1','')}", text_color="green")
                    else:
                        model_status.configure(text="Ollama not detected", text_color="#ff4444")
                    _fetch_models()
                app.after(0, _apply)
            threading.Thread(target=_detect_and_fetch, daemon=True).start()
    provider_var.trace_add("write", _on_provider_change)

    url_frame_s = ctk.CTkFrame(settings_scroll, fg_color="transparent")
    url_frame_s.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(url_frame_s, text="Base URL:").pack(side="left")
    ctk.CTkEntry(url_frame_s, textvariable=base_url_var, placeholder_text="Only for custom endpoints").pack(side="left", padx=5, fill="x", expand=True)

    # Auto-save LLM settings
    def save_llm(*_):
        cfg.save_config({
            "llm_enabled": llm_enabled_var.get(),
            "llm_provider": provider_var.get(),
            "llm_api_key": api_key_var.get(),
            "llm_model": model_var.get(),
            "llm_base_url": base_url_var.get(),
        })
    for v in [llm_enabled_var, provider_var, api_key_var, model_var, base_url_var]:
        v.trace_add("write", save_llm)

    # ═══ LOG PANEL ═══════════════════════════════════════════════════════
    log_panel = ctk.CTkFrame(app, fg_color="transparent")
    log_panel.pack(fill="x", padx=10, pady=(5, 10))

    clip_progress = ctk.CTkProgressBar(log_panel)
    clip_progress.pack(fill="x", pady=(0, 5))
    clip_progress.set(0)

    log_header = ctk.CTkFrame(log_panel, fg_color="transparent")
    log_header.pack(fill="x")
    ctk.CTkLabel(log_header, text="Log", font=("", 13, "bold")).pack(side="left")
    progress_label = ctk.CTkLabel(log_header, text="", text_color="green", font=("", 12))
    progress_label.pack(side="left", padx=10)

    log_box = ctk.CTkTextbox(log_panel, height=180, font=("Consolas", 12), fg_color="#1a1a1a", text_color="#00ff00")
    log_visible = [False]

    def toggle_log():
        if log_visible[0]:
            log_box.pack_forget()
            log_visible[0] = False
            log_toggle_btn.configure(text="Show Log")
        else:
            log_box.pack(fill="x", pady=(5, 0))
            log_visible[0] = True
            log_toggle_btn.configure(text="Hide Log")

    log_toggle_btn = ctk.CTkButton(
        log_header, text="Show Log", width=80, height=24,
        fg_color="transparent", border_width=1, font=("", 11),
        command=toggle_log,
    )
    log_toggle_btn.pack(side="right")

    # Queue polling
    def poll_queues():
        while not log_queue.empty():
            msg = log_queue.get()
            log_box.insert("end", msg + "\n")
            log_box.see("end")
            if not log_visible[0]:
                toggle_log()
        while not progress_queue.empty():
            progress_label.configure(text=progress_queue.get())
        app.after(100, poll_queues)
    app.after(100, poll_queues)

    if not clipper.FFMPEG_CMD:
        messagebox.showerror("FFmpeg Missing", "FFmpeg must be installed and in PATH.\n\nInstall: winget install --id Gyan.FFmpeg.Essentials -e")

    return app


if __name__ == "__main__":
    app = build_gui()
    app.mainloop()
