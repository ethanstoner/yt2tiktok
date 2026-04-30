# yt2tiktok

A desktop application that downloads YouTube videos, splits them into 60-70 second vertical clips optimized for TikTok, and uploads them on a configurable schedule.

Built with CustomTkinter for a modern dark-themed interface.

<!-- Add a screenshot: ![yt2tiktok](assets/screenshot.png) -->

## Features

- **YouTube Download** -- Paste any YouTube URL to download via yt-dlp (1080p max, MP4)
- **Smart Clipping** -- Automatically splits videos into 60-70s segments with randomized boundaries; short tail clips merge into the previous segment
- **Two Visual Styles** -- Blurred background fill (9:16) or classic black bars (letterboxed), selectable per session
- **GPU Acceleration** -- NVENC hardware encoding with automatic CPU (libx264) fallback
- **Scheduled Uploads** -- Selenium-driven TikTok uploads with configurable start time and interval between posts
- **Quiet Hours** -- Suppresses uploads from 11 PM to 8 AM; automatically bumps to next available slot
- **Caption Templates** -- Supports `{title}`, `{part}`, and `{total}` placeholders
- **Retry Logic** -- Failed uploads retry twice with 30-second backoff; failures logged to `failed_clips.txt`
- **Cookie Verification** -- Validates TikTok session before uploading and displays the authenticated username
- **Long Video Guard** -- Warns before processing videos over 2 hours or 30+ clips

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

## How It Works

```
YouTube URL ──> yt-dlp download ──> FFmpeg split (60-70s clips)
                                         │
                              ┌──────────┴──────────┐
                              │  Blurred Background  │  Black Bars
                              │  (blur + overlay)    │  (pad 9:16)
                              └──────────┬──────────┘
                                         │
                                    Title + Part N
                                    text overlays
                                         │
                              Selenium ──> TikTok upload
                              (scheduled, with retries)
```

### Clipping

1. Paste a YouTube URL or browse for a local MP4.
2. Select a clip style: **Blurred** (default) creates a blurred, zoomed copy of the video as the background; **Black Bars** pads with solid black.
3. Click **Start Clipping**. Clips are saved to `./clips/<video-title>/`.

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

## Configuration

All settings are in-app with sensible defaults:

| Setting | Default |
|---------|---------|
| Output directory | `./clips/` |
| Clip style | Blurred |
| Caption | `{title} - Part {part}` |
| Clip duration | 60-70 seconds (randomized) |
| Quiet hours | 11 PM - 8 AM |
| Upload retries | 2 (with 30s backoff) |
| Schedule horizon | 10 days max (TikTok limit) |

## Project Structure

```
yt2tiktok/
├── main.py           # CustomTkinter GUI and thread management
├── clipper.py         # YouTube download, FFmpeg splitting, text overlays
├── uploader.py        # TikTok cookie auth, Selenium upload, scheduling
├── requirements.txt
├── fonts/             # Bundled fallback font (Roboto Condensed, OFL)
└── clips/             # Output directory (gitignored)
```

## Troubleshooting

**FFmpeg not found** -- Verify with `ffmpeg -version`. On Windows, ensure the FFmpeg `bin/` directory is in your system PATH, or install via `winget install --id Gyan.FFmpeg.Essentials -e`.

**CAPTCHA during upload** -- TikTok may challenge new sessions. Uncheck "Headless mode" in the app, complete the CAPTCHA in the visible browser window, then re-export cookies and retry.

**Cookies expired** -- TikTok cookies typically last days to weeks. Re-export a fresh file when uploads fail.

**Uploads stuck in quiet hours** -- Uploads are suppressed 11 PM - 8 AM local time. The next upload will automatically schedule for 8 AM.

## License

[MIT](LICENSE)
