import os
import queue
import threading
from pathlib import Path
from tkinter import messagebox

from src import clipper
from src import uploader
from src import transcriber
from src import captioner
from src.llm_provider import LLMProvider

log_queue: queue.Queue[str] = queue.Queue()
progress_queue: queue.Queue[str] = queue.Queue()

_cancel_event = threading.Event()


def log(msg: str):
    log_queue.put(msg)


def progress(msg: str):
    progress_queue.put(msg)


def request_cancel():
    _cancel_event.set()


def is_cancelled() -> bool:
    return _cancel_event.is_set()


def reset_cancel():
    _cancel_event.clear()


def clipper_worker(
    url, local_path, cookie_file, mode, cut_mode,
    captions_enabled, preset_name, y_position,
    llm_instance,
    state, clip_btn, preview_btn, cancel_btn,
):
    reset_cancel()
    try:
        if url:
            progress("downloading")
            video_path, title = clipper.download_video(
                url, log_fn=log, progress_fn=progress, cookiefile=cookie_file or None,
            )
        elif local_path:
            video_path = local_path
            title = clipper.sanitize_title(Path(local_path).stem)
        else:
            log("No URL or file provided.")
            return

        if is_cancelled():
            log("Clipping cancelled.")
            return

        clip_btn.winfo_toplevel().after(0, lambda v=video_path: state.video_path.set(v))

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

        if is_cancelled():
            log("Clipping cancelled.")
            return

        transcript = None
        if captions_enabled or cut_mode != "random":
            clip_btn.winfo_toplevel().after(0, lambda: state.transcription_status.set("Transcribing..."))
            try:
                transcript = transcriber.transcribe(video_path, url=url if url else None, log_fn=log)
                word_count = len(transcript)
                count_str = str(word_count)
                status_str = f"{word_count} words detected"
                def _on_transcription_done(s=status_str, c=count_str):
                    state.transcription_status.set(s)
                    state.transcript_count.set(c)
                    preview_btn.configure(state="normal")
                clip_btn.winfo_toplevel().after(0, _on_transcription_done)
            except Exception as e:
                log(f"Transcription failed: {e}")
                clip_btn.winfo_toplevel().after(0, lambda: state.transcription_status.set("Transcription failed"))
                transcript = None
                if cut_mode != "random":
                    log("Falling back to random cuts")
                    cut_mode = "random"

        if is_cancelled():
            log("Clipping cancelled.")
            return

        llm = llm_instance if llm_instance and llm_instance.is_available() else None
        cuts = clipper.calculate_cut_points(duration, cut_mode, transcript, llm)
        total_clips = len(cuts)

        caption_ass_map = {}
        if captions_enabled and transcript:
            target_dir = str(clipper.CLIPS_DIR / title)
            os.makedirs(target_dir, exist_ok=True)
            for i, (cut_start, cut_dur) in enumerate(cuts, 1):
                if is_cancelled():
                    log("Clipping cancelled.")
                    return
                cut_end = cut_start + cut_dur
                clip_transcript, _ = captioner.slice_transcript(
                    transcript, cut_start, cut_end, [],
                )
                if clip_transcript:
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

        # Wrap progress to include clip count
        original_progress_fn = progress
        def clip_progress_fn(msg):
            # Parse "Clip X/Y" messages from split_video and add fraction
            if msg.startswith("Clip "):
                try:
                    parts = msg.split("/")
                    done = int(parts[0].replace("Clip ", ""))
                    total = int(parts[1])
                    pct = int(done / total * 100)
                    progress_queue.put(f"progress:{done}/{total}:{pct}")
                    return
                except (ValueError, IndexError):
                    pass
            original_progress_fn(msg)

        target_dir, total = clipper.split_video(
            video_path, title, mode=mode.lower(),
            cut_mode=cut_mode, transcript=transcript, llm=llm,
            caption_ass_map=caption_ass_map,
            cuts=cuts,
            log_fn=log, progress_fn=clip_progress_fn,
        )

        for ass_path in caption_ass_map.values():
            try:
                os.unlink(ass_path)
            except OSError:
                pass

        # Optionally remove source video to save disk space
        if url and not state.keep_source_video.get():
            try:
                source_file = os.path.join(target_dir, f"{title}.mp4")
                if os.path.exists(source_file):
                    os.unlink(source_file)
                    log("Source video removed (enable 'Keep original video' to retain)")
            except OSError:
                pass

        root = clip_btn.winfo_toplevel()
        _td, _t = target_dir, title
        def _on_clip_complete(td=_td, t=_t):
            state.clip_dir.set(td)
            state.title.set(t)
            if captions_enabled and transcript:
                state.transcription_status.set("Captions ready")
        root.after(0, _on_clip_complete)
        log(f"Clipping complete: {total} clips in {target_dir}")
        progress("done")

    except Exception as e:
        log(f"Error: {e}")
    finally:
        def _restore_buttons():
            cancel_btn.pack_forget()
            clip_btn.configure(state="normal", text="Start Clipping")
        clip_btn.winfo_toplevel().after(0, _restore_buttons)


def uploader_worker(clips_dir, title, total_clips, cookie_file, caption_template, start_time, interval, headless, upload_btn):
    try:
        interval_hours = float(interval)
    except ValueError:
        log("Invalid interval value.")
        upload_btn.winfo_toplevel().after(0, lambda: upload_btn.configure(state="normal"))
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
        upload_btn.winfo_toplevel().after(0, lambda: upload_btn.configure(state="normal"))


def verify_worker(cookie_file, headless, status_var, widget):
    widget.winfo_toplevel().after(0, lambda: status_var.set("Verifying..."))
    username = uploader.verify_cookies(cookie_file, headless=headless, log_fn=log)
    if username:
        uname = username
        widget.winfo_toplevel().after(0, lambda u=uname: status_var.set(f"Logged in: @{u}"))
    else:
        widget.winfo_toplevel().after(0, lambda: status_var.set("Verification failed"))
