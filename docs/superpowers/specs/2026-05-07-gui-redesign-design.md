# GUI Redesign Spec

## Goal

Redesign the yt2tiktok CustomTkinter GUI from a single scrollable column into a clean 3-tab layout with better visual hierarchy, working controls, and a YouTube URL preview.

## Current Problems

1. **Single long scroll** — all sections crammed into one column, cluttered
2. **Collapsible panels broken** — Troubleshooting Tips and LLM Settings toggle buttons do nothing (widget pack order bug in CTkScrollableFrame)
3. **Verification status always green** — `text_color="green"` hardcoded on the status label regardless of success/failure
4. **No URL preview** — pasting a YouTube URL shows nothing until you click Start Clipping and wait for the full download
5. **Caption preset selector is blind** — dropdown shows names only, no visual indication of what each style looks like
6. **Preview button locked** — disabled until transcription completes, no way to preview captions before clipping

## Architecture

### Shared State

All `StringVar`/`BooleanVar` instances are created in `build_gui()` **before** the tab view, then passed into per-tab builder functions. This keeps state centralized and accessible across tabs.

```
build_gui():
    # Create all shared vars
    url_var, clip_dir_var, title_var, video_path_var, ...
    llm_enabled_var, provider_var, api_key_var, ...
    preset_var, caption_y_var (DoubleVar, default 0.73), ...

    # Build tabs, passing vars
    tabview = CTkTabview(app)
    build_clip_tab(tabview.tab("Clip"), shared_vars)
    build_upload_tab(tabview.tab("Upload"), shared_vars)
    build_settings_tab(tabview.tab("Settings"), shared_vars)

    # Build shared log panel below tabview
    build_log_panel(app, log_queue, progress_queue)
```

### Window Geometry

Window size: 750x900, minsize 650x750. Tabbed layout is more compact than the current scrollable column.

## Design

### Tab Structure

Three tabs using `CTkTabview`: **Clip**, **Upload**, **Settings**.

A shared log panel sits below the tab view (not inside any tab), always visible.

### Tab 1: Clip

Top-to-bottom layout:

1. **URL Input Row** — text entry + "Fetch" button. Auto-fetch triggers on Enter key via `<Return>` binding on the entry widget.
2. **Video Preview Card** — appears after URL fetch. Shows:
   - Thumbnail (320x180, fetched via yt-dlp `extract_info`)
   - Title
   - Duration (formatted as MM:SS or HH:MM:SS)
   - Estimated clips count (`max(1, round(duration / 65))` — approximation, noted as "~N clips")
   - If fetch fails, the card area shows red error text. If no URL has been fetched yet, the area is empty/hidden.
3. **Local File Alternative** — "Or browse local MP4" row with file picker
4. **YouTube Cookies** — optional, single row with Browse button and "?" help tooltip
5. **Clip Options** — two segmented buttons side by side:
   - Background: Blurred | Black Bars
   - Cut Mode: Random | Natural Pause | Cliffhanger
6. **Caption Section**:
   - Enable checkbox
   - **Visual Preset Selector** — horizontal row of styled chips/buttons, one per preset (6 total). Each chip shows the preset name rendered in that preset's highlight color with a colored accent bar or background tint. Clicking selects it. Selected chip gets a visible border/highlight. Row wraps to a second line if the window is too narrow.
   - Caption position: `CTkSlider` bound to a `DoubleVar` (default 0.73, range 0.64–0.84), with a percentage label beside it. This replaces the mutable list hack. The preview window's drag-to-reposition still works — dragging updates the same `DoubleVar`, so both slider and drag stay in sync.
   - Preview Captions button: enabled once a video path is available (after URL fetch sets `video_path_var`, or after local file browse). Uses sample transcript data for preview (same as current `on_preview` behavior with hardcoded sample words). This is a deliberate behavior change from current code which waits for full transcription.
7. **Start Clipping** button (prominent, full-width)

### Tab 2: Upload

1. **Clip Folder** — path label + Browse button (auto-filled after clipping via shared `clip_dir_var`)
2. **TikTok Cookies** — Browse + Verify button
   - Status label: dynamically colored via trace on `tk_status_var` — green if contains "Logged in", red if contains "failed" or "error", gray otherwise
3. **Caption Template** — text entry with placeholder showing `{title}`, `{part}`, `{total}`
4. **Schedule Settings** — start time (HH:MM) + interval (hours) side by side
5. **Headless Mode** — checkbox
6. **Troubleshooting Tips** — collapsible section. The content frame is created/destroyed inside the toggle callback (not pre-created) to avoid the pack-order bug.
7. **Upload to TikTok** button (prominent)

### Tab 3: Settings

1. **LLM Configuration** — always visible (no broken toggle):
   - Enable LLM checkbox
   - Provider dropdown
   - API Key entry (masked)
   - Model entry
   - Base URL entry
   - All values auto-save to config on change via variable traces
2. Future settings can go here (output directory, clip duration range, etc.)

### Shared Log Panel (below tabs)

- Sits below the `CTkTabview`, always visible regardless of active tab
- **Progress bar** at the top of the panel
- **Header row**: "Log" label on the left + one-line progress status text (green) on the right + toggle button (expand/collapse)
- **Log textbox**: `CTkTextbox` with dark bg and green monospace text. Starts **hidden** (collapsed). Toggle button shows/hides it. When visible, fixed height of 180px.
- The toggle button text switches between "Show Log" and "Hide Log"

### YouTube URL Auto-Preview

When the user presses Enter in the URL field or clicks Fetch:
1. Disable the Fetch button, show "Fetching..." status
2. Spawn a background thread
3. Call `yt_dlp.YoutubeDL.extract_info(url, download=False)` to get metadata
4. Extract thumbnail URL from info dict, download with `requests.get()` (already a dependency in requirements.txt), load into `CTkImage` via Pillow
5. Store the video title and thumbnail URL — the actual video file is NOT downloaded yet (that happens on "Start Clipping")
6. Show title, duration, estimated clips in the preview card
7. Re-enable the Fetch button
8. If fetch fails, show error inline (red text in the card area)

### Visual Caption Preset Selector

Replace the `CTkOptionMenu` dropdown with a horizontal row of `CTkButton` widgets:
- Each button labeled with preset name
- Text color or accent bar uses the preset's highlight color (converted from ASS BGR `&H00BBGGRR` to RGB hex `#RRGGBB`)
- Selected preset has a highlighted border or distinct background
- Clicking a preset button selects it and updates `preset_var`
- 6 presets fit in a row at 750px window width; if window is narrower, they wrap

### Bug Fixes (integrated)

- **Collapsible sections**: content frames created/destroyed inside toggle callbacks, not pre-created.
- **Status colors**: trace on `tk_status_var` dynamically sets `text_color` based on content.
- **LLM Settings**: moved to Settings tab, always visible — no toggle needed.
- **Caption position**: `DoubleVar` replaces mutable list, shared between slider and preview window.

## File Changes

- `main.py` — full rewrite of `build_gui()`. Extract tab builders into helper functions. Worker functions (`clipper_worker`, `uploader_worker`, `verify_worker`) stay the same with minor signature updates to accept the new `DoubleVar` for caption position.
- `src/preview.py` — update `CaptionPreview.__init__` to accept and write back to the shared `DoubleVar` instead of using a local `self.y_position` float.
- No new files needed.

## Out of Scope

- No changes to clipper, captioner, transcriber, uploader, llm_provider, or config modules
- No new dependencies (yt-dlp already has `extract_info`, requests and Pillow already in requirements.txt)
- No changes to the clipping/encoding pipeline
