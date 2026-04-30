import os
import queue
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path

import clipper
import uploader
import transcriber
import captioner
import config as cfg
from llm_provider import LLMProvider, PROVIDERS
from preview import CaptionPreview

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
                transcript = transcriber.transcribe(video_path, log_fn=log)
                transcription_status.set(f"{len(transcript)} words detected")
                transcript_var.set(str(len(transcript)))

                if llm_instance and llm_instance.is_available():
                    highlight_indices = captioner.detect_keywords_llm(transcript, llm_instance)
                else:
                    highlight_indices = captioner.detect_keywords_heuristic(transcript)
                highlight_var.set(",".join(str(i) for i in highlight_indices))

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
                clip_transcript, clip_highlights = captioner.slice_transcript(
                    transcript, cut_start, cut_end, highlight_indices,
                )
                if clip_transcript:
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


def build_gui():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = ctk.CTk()
    app.title("yt2tiktok")
    app.geometry("700x1000")
    app.minsize(600, 800)

    main_frame = ctk.CTkScrollableFrame(app)
    main_frame.pack(fill="both", expand=True, padx=10, pady=10)

    # ═══ CLIPPER SECTION ══════════════════════════════════════════════════
    ctk.CTkLabel(main_frame, text="Video Clipping", font=("", 18, "bold")).pack(pady=(10, 5))

    ctk.CTkLabel(main_frame, text="YouTube URL").pack(anchor="w", padx=10)
    url_var = ctk.StringVar()
    ctk.CTkEntry(main_frame, textvariable=url_var, width=600, placeholder_text="Paste YouTube URL here").pack(padx=10, pady=(0, 5))

    local_path_var = ctk.StringVar()
    file_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    file_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(file_frame, text="Or local MP4:").pack(side="left")
    ctk.CTkLabel(file_frame, textvariable=local_path_var, text_color="gray").pack(side="left", padx=5, expand=True, fill="x")
    ctk.CTkButton(file_frame, text="Browse", width=80, command=lambda: local_path_var.set(filedialog.askopenfilename(filetypes=[("MP4 files", "*.mp4")]) or "")).pack(side="right")

    yt_cookie_var = ctk.StringVar()
    cookie_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    cookie_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(cookie_frame, text="YouTube cookies (optional):").pack(side="left")
    ctk.CTkButton(cookie_frame, text="?", width=28, height=28, command=lambda: messagebox.showinfo("YouTube Cookies", "For age-restricted or private videos, export your YouTube cookies:\n\n1. Install 'Get cookies.txt LOCALLY' browser extension\n2. Log into YouTube in a regular window\n3. Click the extension, set domain to youtube.com, export\n4. Select the exported file here")).pack(side="left", padx=(5, 0))
    ctk.CTkLabel(cookie_frame, textvariable=yt_cookie_var, text_color="gray").pack(side="left", padx=5, expand=True, fill="x")
    ctk.CTkButton(cookie_frame, text="Browse", width=80, command=lambda: yt_cookie_var.set(filedialog.askopenfilename(filetypes=[("Cookie files", "*.txt")]) or "")).pack(side="right")

    mode_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    mode_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(mode_frame, text="Background:").pack(side="left")
    mode_var = ctk.StringVar(value="Blurred")
    ctk.CTkSegmentedButton(mode_frame, values=["Blurred", "Black Bars"], variable=mode_var).pack(side="left", padx=10)

    # Cut mode
    cut_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    cut_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(cut_frame, text="Cut mode:").pack(side="left")
    cut_mode_var = ctk.StringVar(value="Natural Pause")
    ctk.CTkSegmentedButton(cut_frame, values=["Random", "Natural Pause", "Cliffhanger"], variable=cut_mode_var).pack(side="left", padx=10)

    clip_progress = ctk.CTkProgressBar(main_frame)
    clip_progress.pack(fill="x", padx=10, pady=5)
    clip_progress.set(0)

    clip_dir_var = ctk.StringVar()
    title_var = ctk.StringVar()
    video_path_var = ctk.StringVar()
    transcript_var = ctk.StringVar()
    highlight_var = ctk.StringVar()

    # ═══ CAPTIONS SECTION ═════════════════════════════════════════════════
    ctk.CTkFrame(main_frame, height=2, fg_color="gray30").pack(fill="x", padx=10, pady=15)
    ctk.CTkLabel(main_frame, text="Captions", font=("", 18, "bold")).pack(pady=(5, 5))

    captions_var = ctk.BooleanVar(value=True)
    ctk.CTkCheckBox(main_frame, text="Enable auto-captions", variable=captions_var).pack(anchor="w", padx=10)

    preset_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    preset_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(preset_frame, text="Style:").pack(side="left")
    preset_var = ctk.StringVar(value="Opus Clean")
    ctk.CTkOptionMenu(preset_frame, values=list(captioner.PRESETS.keys()), variable=preset_var).pack(side="left", padx=5)

    caption_y_var = [0.76]

    transcription_status = ctk.StringVar(value="Waiting...")
    ctk.CTkLabel(main_frame, textvariable=transcription_status, text_color="gray").pack(anchor="w", padx=10)

    def on_preview():
        vp = video_path_var.get()
        if not vp:
            return
        sample = [
            {"word": "Sample", "start": 0, "end": 0.5, "confidence": 1.0},
            {"word": "caption", "start": 0.5, "end": 1.0, "confidence": 1.0},
            {"word": "text", "start": 1.0, "end": 1.5, "confidence": 1.0},
        ]
        def on_apply(y_pos, preset):
            caption_y_var[0] = y_pos
            preset_var.set(preset)
        CaptionPreview(app, vp, sample, on_apply)

    preview_btn = ctk.CTkButton(main_frame, text="Preview Captions", command=on_preview, state="disabled")
    preview_btn.pack(pady=5)

    # Clip button
    def _get_llm():
        if not llm_enabled_var.get():
            return None
        return LLMProvider(
            provider=provider_var.get(),
            api_key=api_key_var.get(),
            model=model_var.get(),
            base_url=base_url_var.get(),
        )

    def on_clip():
        clip_btn.configure(state="disabled")
        preview_btn.configure(state="disabled")
        cut = cut_mode_var.get().lower().replace(" ", "_")
        threading.Thread(
            target=clipper_worker,
            args=(
                url_var.get().strip(), local_path_var.get().strip(),
                yt_cookie_var.get().strip(), mode_var.get(), cut,
                captions_var.get(), preset_var.get(), caption_y_var[0],
                _get_llm(),
                clip_dir_var, title_var, transcript_var, highlight_var,
                video_path_var, clip_btn, transcription_status, preview_btn,
            ),
            daemon=True,
        ).start()

    clip_btn = ctk.CTkButton(main_frame, text="Start Clipping", command=on_clip)
    clip_btn.pack(pady=10)

    # ═══ UPLOADER SECTION ═════════════════════════════════════════════════
    ctk.CTkFrame(main_frame, height=2, fg_color="gray30").pack(fill="x", padx=10, pady=15)
    ctk.CTkLabel(main_frame, text="TikTok Upload", font=("", 18, "bold")).pack(pady=(5, 5))

    folder_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    folder_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(folder_frame, text="Clip folder:").pack(side="left")
    ctk.CTkLabel(folder_frame, textvariable=clip_dir_var, text_color="gray").pack(side="left", padx=5, expand=True, fill="x")
    ctk.CTkButton(folder_frame, text="Browse", width=80, command=lambda: clip_dir_var.set(filedialog.askdirectory() or clip_dir_var.get())).pack(side="right")

    tk_cookie_var = ctk.StringVar(value=uploader.load_last_cookie_path())
    tk_status_var = ctk.StringVar()
    headless_var = ctk.BooleanVar(value=True)

    tk_cookie_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    tk_cookie_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(tk_cookie_frame, text="TikTok cookies:").pack(side="left")
    ctk.CTkLabel(tk_cookie_frame, textvariable=tk_cookie_var, text_color="gray").pack(side="left", padx=5, expand=True, fill="x")
    ctk.CTkButton(tk_cookie_frame, text="Browse", width=80, command=lambda: tk_cookie_var.set(filedialog.askopenfilename(filetypes=[("Cookie files", "*.txt")]) or "")).pack(side="right")
    ctk.CTkButton(tk_cookie_frame, text="Verify", width=60, command=lambda: threading.Thread(target=verify_worker, args=(tk_cookie_var.get(), headless_var.get(), tk_status_var), daemon=True).start()).pack(side="right", padx=5)

    ctk.CTkLabel(main_frame, textvariable=tk_status_var, text_color="green").pack(padx=10, anchor="w")

    troubleshoot_visible = ctk.BooleanVar(value=False)
    troubleshoot_frame = ctk.CTkFrame(main_frame, fg_color="#2a2a2a", corner_radius=8)
    troubleshoot_text = "If verification fails or uploads get CAPTCHA blocked:\n1. Uncheck 'Headless mode' and try again\n2. Solve any CAPTCHA or login prompt in that window\n3. Close the window, re-export cookies, and try again\n4. Cookies expire regularly — re-export when sessions fail"

    def toggle_troubleshoot():
        if troubleshoot_visible.get():
            troubleshoot_frame.pack_forget()
            troubleshoot_visible.set(False)
        else:
            troubleshoot_frame.pack(fill="x", padx=10, pady=5)
            troubleshoot_visible.set(True)

    ctk.CTkButton(main_frame, text="Troubleshooting Tips", width=160, height=28, fg_color="transparent", border_width=1, command=toggle_troubleshoot).pack(anchor="w", padx=10, pady=(0, 5))
    ctk.CTkLabel(troubleshoot_frame, text=troubleshoot_text, justify="left", wraplength=580).pack(padx=10, pady=10)

    def on_cookie_selected(*_):
        path = tk_cookie_var.get()
        if path:
            uploader.save_last_cookie_path(path)
    tk_cookie_var.trace_add("write", on_cookie_selected)

    ctk.CTkLabel(main_frame, text="Caption ({title}, {part}, {total})").pack(anchor="w", padx=10, pady=(5, 0))
    caption_var = ctk.StringVar(value="{title} - Part {part}")
    ctk.CTkEntry(main_frame, textvariable=caption_var, width=600).pack(padx=10)

    schedule_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    schedule_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(schedule_frame, text="Start time:").pack(side="left")
    start_var = ctk.StringVar(value="10:00")
    ctk.CTkEntry(schedule_frame, textvariable=start_var, width=80, placeholder_text="HH:MM").pack(side="left", padx=5)
    ctk.CTkLabel(schedule_frame, text="Interval (hrs):").pack(side="left", padx=(15, 0))
    interval_var = ctk.StringVar(value="2")
    ctk.CTkEntry(schedule_frame, textvariable=interval_var, width=60).pack(side="left", padx=5)

    ctk.CTkCheckBox(main_frame, text="Headless mode (uncheck to debug)", variable=headless_var).pack(anchor="w", padx=10, pady=5)

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
            args=(clip_dir_var.get(), title_var.get(), clip_count, tk_cookie_var.get(), caption_var.get(), start_var.get(), interval_var.get(), headless_var.get(), upload_btn),
            daemon=True,
        ).start()

    upload_btn = ctk.CTkButton(main_frame, text="Upload to TikTok", command=on_upload)
    upload_btn.pack(pady=10)

    # ═══ LLM SETTINGS ════════════════════════════════════════════════════
    ctk.CTkFrame(main_frame, height=2, fg_color="gray30").pack(fill="x", padx=10, pady=15)

    llm_enabled_var = ctk.BooleanVar(value=cfg.get("llm_enabled", False))
    llm_frame = ctk.CTkFrame(main_frame, fg_color="#2a2a2a", corner_radius=8)
    llm_visible = ctk.BooleanVar(value=False)

    def toggle_llm():
        if llm_visible.get():
            llm_frame.pack_forget()
            llm_visible.set(False)
        else:
            llm_frame.pack(fill="x", padx=10, pady=5)
            llm_visible.set(True)

    ctk.CTkButton(main_frame, text="LLM Settings", width=140, height=28, fg_color="transparent", border_width=1, command=toggle_llm).pack(anchor="w", padx=10, pady=(0, 5))

    ctk.CTkCheckBox(llm_frame, text="Enable LLM", variable=llm_enabled_var).pack(anchor="w", padx=10, pady=5)

    provider_var = ctk.StringVar(value=cfg.get("llm_provider", "groq"))
    prov_frame = ctk.CTkFrame(llm_frame, fg_color="transparent")
    prov_frame.pack(fill="x", padx=10, pady=2)
    ctk.CTkLabel(prov_frame, text="Provider:").pack(side="left")
    ctk.CTkOptionMenu(prov_frame, values=["groq", "openai", "gemini", "claude", "ollama", "custom"], variable=provider_var).pack(side="left", padx=5)

    api_key_var = ctk.StringVar(value=cfg.get("llm_api_key", ""))
    key_frame = ctk.CTkFrame(llm_frame, fg_color="transparent")
    key_frame.pack(fill="x", padx=10, pady=2)
    ctk.CTkLabel(key_frame, text="API Key:").pack(side="left")
    ctk.CTkEntry(key_frame, textvariable=api_key_var, width=400, show="*").pack(side="left", padx=5, fill="x", expand=True)

    model_var = ctk.StringVar(value=cfg.get("llm_model", ""))
    mod_frame = ctk.CTkFrame(llm_frame, fg_color="transparent")
    mod_frame.pack(fill="x", padx=10, pady=2)
    ctk.CTkLabel(mod_frame, text="Model:").pack(side="left")
    ctk.CTkEntry(mod_frame, textvariable=model_var, width=300).pack(side="left", padx=5)

    base_url_var = ctk.StringVar(value=cfg.get("llm_base_url", ""))
    url_frame = ctk.CTkFrame(llm_frame, fg_color="transparent")
    url_frame.pack(fill="x", padx=10, pady=2)
    ctk.CTkLabel(url_frame, text="Base URL:").pack(side="left")
    ctk.CTkEntry(url_frame, textvariable=base_url_var, width=400).pack(side="left", padx=5, fill="x", expand=True)

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

    # ═══ LOG BOX ══════════════════════════════════════════════════════════
    ctk.CTkFrame(main_frame, height=2, fg_color="gray30").pack(fill="x", padx=10, pady=10)
    ctk.CTkLabel(main_frame, text="Log", font=("", 14, "bold")).pack(anchor="w", padx=10)
    progress_label = ctk.CTkLabel(main_frame, text="", text_color="green")
    progress_label.pack(anchor="w", padx=10)
    log_box = ctk.CTkTextbox(main_frame, height=200, font=("Consolas", 12), fg_color="#1a1a1a", text_color="#00ff00")
    log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def poll_queues():
        while not log_queue.empty():
            msg = log_queue.get()
            log_box.insert("end", msg + "\n")
            log_box.see("end")
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
