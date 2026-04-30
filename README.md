# yt2tiktok

A desktop application that downloads YouTube videos, splits them into 60-70 second vertical clips optimized for TikTok, burns in animated word-by-word captions, and uploads clips on a configurable schedule.

Built with CustomTkinter for a modern dark-themed interface.

<!-- Add a screenshot: ![yt2tiktok](assets/screenshot.png) -->

## Features

- **YouTube Download** -- Paste any YouTube URL to download via yt-dlp (1080p max, MP4)
- **Smart Clipping** -- Automatically splits videos into 60-70s segments with randomized boundaries; short tail clips merge into the previous segment
- **Two Visual Styles** -- Blurred background fill (9:16) or classic black bars (letterboxed), selectable per session
- **GPU Acceleration** -- NVENC hardware encoding with automatic CPU (libx264) fallback
- **Parallel Encoding** -- Clips encode concurrently (2-4x faster on multi-core machines)
- **Auto-Generated Captions** -- Word-by-word animated captions burned directly into each clip via ASS subtitles
- **5 Caption Style Presets** -- Bold Pop, Neon Glow, Impact, Pastel, and Minimal; each with distinct colors, font sizes, and animations
- **Caption Preview** -- Interactive preview window with drag-to-reposition; changes persist to config
- **Speech-to-Text** -- Transcription via faster-whisper (large-v3-turbo); upgrades automatically to NVIDIA Parakeet (1.1B) when a CUDA GPU and NeMo are available
- **Keyword Highlighting** -- Heuristic detection highlights notable words; optionally upgraded with LLM-driven selection
- **Smart Cut Modes** -- Natural Pause (silence-based boundaries) or Cliffhanger (LLM selects a mid-sentence hook point)
- **Multi-Provider LLM** -- Groq, OpenAI, Gemini, Claude, Ollama, or any OpenAI-compatible endpoint
- **Scheduled Uploads** -- Selenium-driven TikTok uploads with configurable start time and interval between posts
- **Quiet Hours** -- Suppresses uploads from 11 PM to 8 AM; automatically bumps to next available slot
- **Caption Templates** -- Supports `{title}`, `{part}`, and `{total}` placeholders in post captions
- **Retry Logic** -- Failed uploads retry twice with 30-second backoff; failures logged to `failed_clips.txt`
- **Cookie Verification** -- Validates TikTok session before uploading and displays the authenticated username
- **Long Video Guard** -- Warns before processing videos over 2 hours or 30+ clips
- **Centralized Config** -- All settings persist to `~/.yt2tiktok.json` with thread-safe reads and writes

## Caption Presets

| Preset | Highlight Color | Animation | Font Size | Uppercase |
|--------|----------------|-----------|-----------|-----------|
| Bold Pop | Blue (`#F7C204`) | Scale pop | 48 | No |
| Neon Glow | Yellow (`#FFF000`) | Bounce + glow shadow | 46 | No |
| Impact | Red-blue (`#3B3BFF`) | Slam in | 52 | Yes |
| Pastel | Lavender (`#DB8FFF`) | Fade | 44 | No |
| Minimal | Light gray (`#CCCCCC`) | Fade | 36 | No |

## Requirements

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and available in `PATH`
- Google Chrome (for Selenium-based uploads)

## Quick Start

```bash
git clone https://github.com/ethanstoner/yt2tiktok.git
cd yt2tiktok
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Optional: NVIDIA Parakeet (faster, higher-accuracy transcription)

Requires a CUDA-capable GPU and roughly 5 GB of VRAM.

```bash
pip install -r requirements-parakeet.txt
```

When both NeMo and a CUDA device are detected at runtime, the app automatically uses Parakeet instead of faster-whisper. No configuration change is needed.

## How It Works

```
YouTube URL ──> yt-dlp download ──> faster-whisper transcription
                                         │
                              ┌──────────┴──────────┐
                          Natural Pause          Cliffhanger
                         (silence gaps)        (LLM hook point)
                              └──────────┬──────────┘
                                         │
                                  FFmpeg split (60-70s)
                                  [parallel encoding]
                                         │
                              ┌──────────┴──────────┐
                              │  Blurred Background  │  Black Bars
                              │  (blur + overlay)    │  (pad 9:16)
                              └──────────┬──────────┘
                                         │
                              ASS captions burned in
                              (word-by-word animation)
                                         │
                              Selenium ──> TikTok upload
                              (scheduled, with retries)
```

### Clipping

1. Paste a YouTube URL or browse for a local MP4.
2. Select a clip style: **Blurred** (default) creates a blurred, zoomed copy of the video as the background; **Black Bars** pads with solid black.
3. Choose a cut mode: **Natural Pause** finds silence-based boundaries; **Cliffhanger** uses an LLM to pick a hook point mid-sentence.
4. Select a caption preset (or disable captions entirely).
5. Click **Start Clipping**. Clips are saved to `./clips/<video-title>/`.

### Uploading

1. Export your TikTok cookies using a browser extension (see below).
2. Select the cookie file and click **Verify** to confirm your session.
3. Set your caption template, start time, and interval.
4. Click **Upload to TikTok**. Each clip is scheduled at the configured interval, skipping quiet hours.

## Cookie Setup

TikTok does not offer a public upload API. This app authenticates using exported browser cookies in Netscape format.

### TikTok (required)

1. Install the [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) extension.
2. Log in to [tiktok.com](https://www.tiktok.com) in a regular browser window.
3. Click the extension icon, set the domain filter to `.tiktok.com`, and export.
4. Select the exported `.txt` file in the app's Upload section.

Cookies expire periodically. Re-export when uploads fail with authentication errors.

### YouTube (optional)

Only needed for age-restricted or members-only videos. Same process as above but export cookies from `youtube.com`.

## LLM Setup (Optional)

LLM integration enables two features: **keyword highlighting** (picks the most impactful words to color in captions) and **Cliffhanger cut mode** (selects a hook point within each segment).

Open the **LLM Settings** panel in the app and configure:

| Field | Description |
|-------|-------------|
| Provider | `groq`, `openai`, `gemini`, `claude`, `ollama`, or `custom` |
| API Key | Your provider's API key (not required for Ollama) |
| Model | Leave blank to use each provider's default model |
| Base URL | Only needed for `custom` endpoints |

Default models per provider:

| Provider | Default Model |
|----------|--------------|
| Groq | llama-3.3-70b-versatile |
| OpenAI | gpt-4o-mini |
| Gemini | gemini-2.0-flash |
| Claude | claude-sonnet-4-latest |
| Ollama | llama3.1:8b |

If no LLM is configured, keyword detection falls back to a built-in heuristic (long words, numbers, and all-caps terms) and Cliffhanger mode is disabled.

## Configuration

All settings are saved in-app and persist to `~/.yt2tiktok.json`:

| Setting | Default |
|---------|---------|
| Output directory | `./clips/` |
| Clip style | Blurred |
| Cut mode | Natural Pause |
| Caption preset | Bold Pop |
| Captions enabled | Yes |
| Caption vertical position | 70% from top |
| LLM provider | (none) |
| Post caption | `{title} - Part {part}` |
| Clip duration | 60-70 seconds (randomized) |
| Quiet hours | 11 PM - 8 AM |
| Upload retries | 2 (with 30s backoff) |
| Schedule horizon | 10 days max (TikTok limit) |

## Project Structure

```
yt2tiktok/
├── main.py              # CustomTkinter GUI and thread management
├── clipper.py           # YouTube download, FFmpeg splitting, parallel encoding
├── uploader.py          # TikTok cookie auth, Selenium upload, scheduling
├── transcriber.py       # Speech-to-text (faster-whisper + optional Parakeet)
├── captioner.py         # ASS subtitle generation, 5 presets, keyword detection
├── llm_provider.py      # Multi-provider LLM client (Groq, OpenAI, Gemini, Claude, Ollama)
├── preview.py           # Caption preview window with drag-to-reposition
├── config.py            # Thread-safe JSON config persistence (~/.yt2tiktok.json)
├── requirements.txt
├── requirements-parakeet.txt   # Optional: NeMo + NVIDIA Parakeet
├── fonts/               # Bundled caption font (BubblegumSans, fallback RobotoCondensed)
└── clips/               # Output directory (gitignored)
```

## Troubleshooting

**FFmpeg not found** -- Verify with `ffmpeg -version`. On Windows, ensure the FFmpeg `bin/` directory is in your system PATH, or install via `winget install --id Gyan.FFmpeg.Essentials -e`.

**Captions not appearing** -- Confirm FFmpeg was built with libass support (`ffmpeg -filters | grep ass`). Most standard builds include it.

**Transcription is slow** -- faster-whisper runs on CPU by default when no CUDA device is found. A GPU reduces transcription time significantly. For the fastest results, install Parakeet (`requirements-parakeet.txt`) on a machine with an NVIDIA GPU.

**CAPTCHA during upload** -- TikTok may challenge new sessions. Uncheck "Headless mode" in the app, complete the CAPTCHA in the visible browser window, then re-export cookies and retry.

**Cookies expired** -- TikTok cookies typically last days to weeks. Re-export a fresh file when uploads fail.

**Uploads stuck in quiet hours** -- Uploads are suppressed 11 PM - 8 AM local time. The next upload will automatically schedule for 8 AM.

**LLM request timeout** -- The LLM client has a 30-second timeout per request. If your provider is slow or offline, the app falls back to heuristic keyword detection and disables Cliffhanger mode for that session.

## License

[MIT](LICENSE)
