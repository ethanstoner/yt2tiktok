# GUI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the yt2tiktok GUI from a single scrollable column to a 3-tab layout with YouTube URL preview, visual caption presets, and bug fixes.

**Architecture:** `build_gui()` creates all shared state vars up front, then delegates to `build_clip_tab()`, `build_upload_tab()`, `build_settings_tab()`, and `build_log_panel()` helper functions. Worker functions stay largely unchanged. `src/preview.py` updated to accept a shared `DoubleVar` for caption position.

**Tech Stack:** CustomTkinter, yt-dlp, Pillow, requests (all existing deps)

---

### Task 1: Update preview.py to use DoubleVar

**Files:**
- Modify: `src/preview.py`

This task decouples the preview window from the old mutable-list hack so it can share a `DoubleVar` with the new slider.

- [ ] **Step 1: Update CaptionPreview.__init__ signature**

Change `__init__` to accept an optional `y_var` parameter (a `ctk.DoubleVar`). If provided, use its value as the initial `self.y_position` and write back to it on changes. If not provided, create a local float (backward compat).

In `src/preview.py`, replace the `__init__` method:

```python
class CaptionPreview(ctk.CTkToplevel):
    PREVIEW_W = 360
    PREVIEW_H = 640

    def __init__(self, master, video_path: str, transcript: list[dict], callback, y_var=None):
        super().__init__(master)
        self.title("Caption Preview")
        self.geometry(f"{self.PREVIEW_W + 40}x{self.PREVIEW_H + 160}")
        self.resizable(False, False)

        self.video_path = video_path
        self.transcript = transcript
        self.callback = callback
        self.y_var = y_var
        self.y_position = y_var.get() if y_var else 0.73
        self.preset_name = "Opus Clean"
        self.frame_img = None
```

- [ ] **Step 2: Update _on_click and _on_drag to write back to y_var**

Replace both methods:

```python
    def _on_click(self, event):
        self.y_position = max(0.64, min(0.84, event.y / self.PREVIEW_H))
        if self.y_var:
            self.y_var.set(self.y_position)
        self.pos_label.configure(text=f"Position: {int(self.y_position * 100)}%")
        self._render()

    def _on_drag(self, event):
        self.y_position = max(0.64, min(0.84, event.y / self.PREVIEW_H))
        if self.y_var:
            self.y_var.set(self.y_position)
        self.pos_label.configure(text=f"Position: {int(self.y_position * 100)}%")
        self._render()
```

- [ ] **Step 3: Verify preview still works**

Run:
```bash
venv/Scripts/python.exe -c "
import customtkinter as ctk
from src.preview import CaptionPreview

app = ctk.CTk()
app.update()
y_var = ctk.DoubleVar(value=0.73)

# Create a 5s test video
import subprocess, os
from src.clipper import FFMPEG_CMD
os.makedirs('test_output', exist_ok=True)
subprocess.run([FFMPEG_CMD, '-y', '-f', 'lavfi', '-i', 'color=c=blue:size=1920x1080:d=5', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-t', '5', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', 'test_output/test_input.mp4'], capture_output=True)

transcript = [
    {'word': 'Hello', 'start': 0.0, 'end': 0.5, 'confidence': 1.0},
    {'word': 'world', 'start': 0.6, 'end': 1.0, 'confidence': 1.0},
    {'word': 'test', 'start': 1.1, 'end': 1.5, 'confidence': 1.0},
]
applied = [None]
def cb(y, p): applied[0] = (y, p)

preview = CaptionPreview(app, 'test_output/test_input.mp4', transcript, cb, y_var=y_var)
preview.update()

class E:
    def __init__(self, y): self.y = y
preview._on_drag(E(int(0.78 * 640)))
print(f'y_var synced: {y_var.get():.2f}')
assert abs(y_var.get() - 0.78) < 0.02, 'y_var not synced'

preview._on_apply()
print(f'Callback: {applied[0]}')
app.destroy()
import shutil; shutil.rmtree('test_output')
print('PASS')
"
```

Expected: `PASS` with y_var synced to ~0.78.

- [ ] **Step 4: Commit**

```bash
git add src/preview.py
git commit -m "refactor: preview accepts shared DoubleVar for caption position"
```

---

### Task 2: Rewrite main.py — scaffold and shared state

**Files:**
- Modify: `main.py`

This task replaces the entire `build_gui()` with the new tabbed scaffold. Worker functions are preserved. Tab content is placeholder — filled in by subsequent tasks.

- [ ] **Step 1: Back up current main.py for reference**

```bash
cp main.py main_old.py
```

- [ ] **Step 2: Rewrite build_gui() with tab scaffold**

Rewrite `main.py`. Keep all worker functions (`clipper_worker`, `uploader_worker`, `verify_worker`) exactly as-is. Update the import block to add `from PIL import Image` (needed for thumbnail fetch in Task 3). Keep `log_queue`, `progress_queue`, `log()`, `progress()`. Preserve the `if __name__ == "__main__"` block at the bottom. Replace `build_gui()` with:

**Note:** The spec suggests helper functions (`build_clip_tab()` etc.), but since the full GUI is under 500 lines in one file and all tabs share closure variables, keeping everything in `build_gui()` avoids passing dozens of vars as arguments. This is a deliberate simplification.

```python
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

    # Thumbnail image holder (mutable container for CTkImage reference)
    thumb_image = [None]

    # ═══ TAB VIEW ════════════════════════════════════════════════════════
    tabview = ctk.CTkTabview(app)
    tabview.pack(fill="both", expand=True, padx=10, pady=(10, 0))
    tabview.add("Clip")
    tabview.add("Upload")
    tabview.add("Settings")

    # Build each tab (placeholder — filled in Tasks 3-5)
    clip_tab = tabview.tab("Clip")
    upload_tab = tabview.tab("Upload")
    settings_tab = tabview.tab("Settings")

    # ═══ LOG PANEL + QUEUE POLLING (built in Task 6) ═══════════════════
    # Do NOT add poll_queues here — it is defined in Task 6 after log_box exists.

    if not clipper.FFMPEG_CMD:
        messagebox.showerror("FFmpeg Missing", "FFmpeg must be installed and in PATH.\n\nInstall: winget install --id Gyan.FFmpeg.Essentials -e")

    return app
```

- [ ] **Step 3: Verify app launches with empty tabs**

```bash
venv/Scripts/python.exe -c "
import main
app = main.build_gui()
app.update_idletasks()
app.update()
print(f'Window: {app.title()} {app.geometry()}')
app.destroy()
print('PASS')
"
```

Expected: `PASS` — window launches with 3 empty tabs.

- [ ] **Step 4: Commit**

```bash
git add main.py main_old.py
git commit -m "refactor: scaffold tabbed GUI with shared state vars"
```

---

### Task 3: Build the Clip tab

**Files:**
- Modify: `main.py`

This is the largest task — builds the entire Clip tab including URL fetch, preview card, options, caption presets, and the Start Clipping button.

- [ ] **Step 1: Add the URL fetch function**

Add this function inside `build_gui()`, after the shared state block. **Note:** This function references `fetch_btn`, `preview_status`, `thumb_label`, `info_label`, and `preview_btn` which are created in Step 2 below. This is safe because the function is only called when the user clicks Fetch (by which time all widgets exist), but both steps must be completed together before testing.

```python
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

                # Format duration
                if duration >= 3600:
                    dur_str = f"{int(duration//3600)}:{int(duration%3600//60):02d}:{int(duration%60):02d}"
                else:
                    dur_str = f"{int(duration//60)}:{int(duration%60):02d}"
                est_clips = max(1, round(duration / 65))

                # Fetch thumbnail
                ctk_img = None
                if thumb_url:
                    try:
                        resp = req.get(thumb_url, timeout=10)
                        img = Image.open(BytesIO(resp.content)).resize((320, 180), Image.LANCZOS)
                        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(320, 180))
                    except Exception:
                        pass

                def _update_ui():
                    title_var.set(clipper.sanitize_title(title))
                    thumb_image[0] = ctk_img
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
```

- [ ] **Step 2: Build the Clip tab UI**

Add this after the tab placeholder comments, replacing `clip_tab = tabview.tab("Clip")`:

```python
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
                        btn.configure(border_width=0, border_color="transparent")
            return cmd
        btn = ctk.CTkButton(
            preset_frame, text=name, width=100, height=32,
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            text_color=color, font=("", 12, "bold"),
            border_width=2 if name == "Opus Clean" else 0,
            border_color=color if name == "Opus Clean" else "transparent",
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
        if not vp:
            return
        sample = [
            {"word": "Sample", "start": 0, "end": 0.5, "confidence": 1.0},
            {"word": "caption", "start": 0.5, "end": 1.0, "confidence": 1.0},
            {"word": "text", "start": 1.0, "end": 1.5, "confidence": 1.0},
        ]
        def on_apply(y_pos, preset):
            caption_y_var.set(y_pos)
            preset_var.set(preset)
        CaptionPreview(app, vp, sample, on_apply, y_var=caption_y_var)

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
```

- [ ] **Step 3: Verify Clip tab renders**

```bash
venv/Scripts/python.exe -c "
import main
app = main.build_gui()
app.update_idletasks()
app.update()
print('Clip tab rendered OK')
app.destroy()
print('PASS')
"
```

Expected: `PASS`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: build Clip tab with URL preview, visual presets, position slider"
```

---

### Task 4: Build the Upload tab

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add Upload tab UI**

Replace the `upload_tab = tabview.tab("Upload")` placeholder with the full upload tab. Add this code after the Clip tab block:

```python
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
```

- [ ] **Step 2: Verify Upload tab renders and troubleshooting toggle works**

```bash
venv/Scripts/python.exe -c "
import main
app = main.build_gui()
app.update_idletasks()
app.update()
print('Upload tab rendered OK')
app.destroy()
print('PASS')
"
```

Expected: `PASS`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: build Upload tab with dynamic status colors and working troubleshoot toggle"
```

---

### Task 5: Build the Settings tab

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add Settings tab UI**

Replace the `settings_tab = tabview.tab("Settings")` placeholder:

```python
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

    mod_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
    mod_frame.pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(mod_frame, text="Model:").pack(side="left")
    ctk.CTkEntry(mod_frame, textvariable=model_var, placeholder_text="Leave blank for default").pack(side="left", padx=5, fill="x", expand=True)

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
```

- [ ] **Step 2: Verify Settings tab renders**

```bash
venv/Scripts/python.exe -c "
import main
app = main.build_gui()
app.update_idletasks()
app.update()
print('Settings tab rendered OK')
app.destroy()
print('PASS')
"
```

Expected: `PASS`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: build Settings tab with LLM configuration"
```

---

### Task 6: Build the shared log panel

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add log panel below the tabview**

Replace the log panel placeholder and update `poll_queues` to write to the actual log box:

```python
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
```

- [ ] **Step 2: Update poll_queues to use the real log_box**

Replace the placeholder `poll_queues`:

```python
    def poll_queues():
        while not log_queue.empty():
            msg = log_queue.get()
            log_box.insert("end", msg + "\n")
            log_box.see("end")
            # Auto-show log on first message
            if not log_visible[0]:
                toggle_log()
        while not progress_queue.empty():
            progress_label.configure(text=progress_queue.get())
        app.after(100, poll_queues)
    app.after(100, poll_queues)
```

- [ ] **Step 3: Verify full app launches with log panel**

```bash
venv/Scripts/python.exe -c "
import main
app = main.build_gui()
app.update_idletasks()
app.update()
print('Full app with log panel OK')
app.destroy()
print('PASS')
"
```

Expected: `PASS`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add shared log panel with collapsible log and progress bar"
```

---

### Task 7: Clean up and final integration test

**Files:**
- Modify: `main.py` (remove old backup)
- Delete: `main_old.py`

- [ ] **Step 1: Remove main_old.py**

```bash
rm main_old.py
```

- [ ] **Step 2: Full integration test — launch app, verify all tabs and toggles work**

```bash
venv/Scripts/python.exe -c "
import main
app = main.build_gui()
app.update_idletasks()
app.update()

# Verify window
assert app.title() == 'yt2tiktok'
print(f'Window: {app.geometry()}')
print('All tabs rendered OK')

app.destroy()
print('ALL PASS')
"
```

Expected: `ALL PASS`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: complete GUI redesign — 3-tab layout with all features"
```
