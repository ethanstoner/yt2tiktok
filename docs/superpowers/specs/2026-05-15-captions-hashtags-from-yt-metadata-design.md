# YouTube-Metadata Captions & Hashtags — Design

**Date:** 2026-05-15
**Status:** Approved (pending spec review)
**Branch:** `feature/captions-hashtags-from-yt-metadata`

## Problem

The TikTok post caption is currently a static template (`{title} - Part
{part}`). The source YouTube video's **description** and **tags** are fetched
by `clipper.download_video` (via `ydl.extract_info`) but discarded — only the
sanitized `title` survives. This produces low-effort post text with no
hashtags, hurting reach.

## Goal

Generate a high-quality TikTok **post caption + hashtags** from the source
YouTube video's title and description, using the already-configured LLM with a
deterministic rule-based fallback. Persist the result at clip time and consume
it at upload time, while keeping the caption user-editable before posting.

This targets the **post caption/description text**, NOT the burned-in
word-by-word subtitles (those are out of scope).

## Non-Goals (YAGNI)

- Changing the burned-in karaoke subtitles (`captioner.py`).
- A unique LLM-written caption per individual clip/part.
- Trending-hashtag lookup via external APIs.
- Multi-language caption generation.

## Decisions (locked in brainstorming)

| Question | Decision |
|---|---|
| Target | TikTok post caption + hashtags |
| Generation | LLM, with rule-based fallback |
| Metadata flow | `_meta.json` sidecar written at clip time |
| Policy | One caption + hashtags per video; each clip appends `Part N`; user template still wraps it (editable before upload) |

## Architecture

Two new small modules plus targeted edits to the existing
clip→meta→upload flow. Each new file has one responsibility.

### `src/caption_gen.py` (new)

```python
def generate_caption(meta: dict, llm=None) -> dict
# returns {"caption": str, "hashtags": list[str], "source": "llm"|"rule"}
```

- Input `meta`: at least `{"title": str, "description": str, "tags": list}`.
- **LLM path** (when `llm` is truthy and `llm.is_available()`): one prompt
  containing the title and a length-truncated description (cap ~1500 chars),
  instructing: return a single punchy caption (<=150 chars, no hashtags inline)
  and 3–5 relevant lowercase hashtags, in a parseable shape (e.g. two labeled
  lines: `CAPTION:` / `HASHTAGS:`). Parse defensively. On `LLMError`,
  timeout, empty, or unparseable output → fall through to the rule path. The
  LLM must never block or raise out of `generate_caption`.
- **Rule path:** `caption` = cleaned title (strip channel boilerplate like
  trailing " | Channel", collapse whitespace, trim to 150 chars).
  `hashtags` = from `meta["tags"]`: lowercase, strip non-alphanumerics,
  drop empties/dupes, prefix `#`, cap at 5; then union with a small default
  set (`#fyp`, `#foryou`) without exceeding the cap. Deterministic and pure
  (no I/O) → unit-testable.
- `_sanitize_hashtag(s) -> str|None` helper (shared by both paths to normalize
  whatever the LLM returns too).

### `src/metadata.py` (new)

```python
def save_clip_meta(clip_dir: str, meta: dict) -> None
def load_clip_meta(clip_dir: str) -> dict | None   # None if absent/corrupt
```

- Writes `<clip_dir>/_meta.json`, UTF-8, atomic (temp file + `os.replace`),
  mirroring the audited `src/config.py` pattern.
- `load_clip_meta` returns `None` on missing/corrupt file (callers fall back
  to legacy behavior — no crash).
- Stored shape: `{url, title, description, tags, caption, hashtags, source}`.

### `src/clipper.py` — `download_video`

- Currently returns `(video_path, title)`. Change to
  `(video_path, title, meta)` where `meta = {"url", "title", "description",
  "tags"}` from the already-fetched `info` (no extra network call).
- Update the sole caller (`workers.clipper_worker`).
- Local-file path (no URL) has no YouTube metadata: the worker builds a
  minimal `meta = {"url": "", "title": <from filename>, "description": "",
  "tags": []}` so the rule path still yields a caption.

### `src/workers.py` — `clipper_worker`

- After clips are written (post `split_video`), build/extend `meta`, call
  `caption_gen.generate_caption(meta, llm)` reusing the LLM instance already
  constructed for cut/caption logic, merge `caption`/`hashtags`/`source`
  into `meta`, and `metadata.save_clip_meta(target_dir, meta)`.
- Gated by a new `state.auto_caption` boolean (default `True`). When off,
  skip generation but still write the raw metadata sidecar (so upload can at
  least use the real title).
- Generation failure must not fail the clip job (it already succeeded) —
  wrap in try/except, log, continue.

### Upload side — `src/uploader.py`

- `_safe_caption` field set expanded to: `title`, `part`, `total`,
  `caption`, `hashtags` (hashtags joined with spaces). It already tolerates
  unknown/missing placeholders via the existing `_Safe` mapping.
- `upload_clips`: load `load_clip_meta(clips_dir)`; if present, pass its
  `caption`/`hashtags` into `_safe_caption`; if absent, behave exactly as
  today (legacy `{title} - Part {part}`) — zero regression for old clip
  folders.
- New default `caption_template` in `config.DEFAULTS`:
  `"{caption}\n\n{hashtags}"`. A single helper
  `_build_description(template, title, part, total, meta) -> str` is the ONE
  place the post text is assembled: it renders the template via
  `_safe_caption` and appends `" Part {part}"` only when `total > 1`.
  **Source of truth for `total`:** the discovered `len(clip_files)` inside
  `upload_clips` (the value the loop actually iterates), NOT the passed
  `total_clips` argument — this avoids a mismatch when a folder's file count
  differs from the recorded total. The UI caption preview MUST call this same
  `_build_description` helper so the preview can never drift from what
  `upload_clips` actually sends. Existing user-customized templates are
  respected unchanged.

### UI

- **Clip tab:** one checkbox "Auto-generate caption from video metadata"
  bound to `state.auto_caption` (default on). Persisted via the existing
  `AppState` auto-persist list.
- **Upload tab:** a read-only resolved-caption preview label that shows the
  effective post text for Part 1 when a `_meta.json` exists in the selected
  clip folder; refreshes when the folder changes. The editable template
  entry stays.
- No other UI changes.

## Data Flow

```
clip run:
  download_video -> info -> (video_path, title, meta{url,title,description,tags})
  split_video -> clips in target_dir
  if state.auto_caption: caption_gen.generate_caption(meta, llm)
  metadata.save_clip_meta(target_dir, meta{...,caption,hashtags,source})

upload run:
  load_clip_meta(clips_dir) -> meta or None
  per clip: description = _safe_caption(template,
              title, part, total, caption=meta.caption,
              hashtags=" ".join(meta.hashtags))   # or legacy if meta None
  _studio_post(... description ...)
```

## Error Handling

- LLM unavailable / `LLMError` / timeout / empty / unparseable → rule path.
- `generate_caption` never raises; worst case returns the rule result.
- Clip job already done before generation runs → generation failure logged,
  job still reported complete.
- `_meta.json` missing/corrupt at upload → legacy caption behavior.
- Description truncated before LLM prompt to bound token use.
- Hashtags sanitized: lowercase, alphanumerics only, deduped, capped 5.

## Testing

Unit (pytest, no network/browser):

- `caption_gen.generate_caption`:
  - Rule path (llm=None): title cleaned, hashtags from `tags` sanitized +
    capped + defaults, `source == "rule"`.
  - LLM path with a stub LLM returning well-formed output → parsed
    `caption`/`hashtags`, `source == "llm"`.
  - Stub LLM raising / returning garbage → falls back to rule, `source ==
    "rule"`, no exception.
  - `_sanitize_hashtag` edge cases (spaces, emoji, punctuation, dupes, empty).
- `metadata`: save then load roundtrip; `load_clip_meta` returns `None` for
  missing dir and for corrupt JSON; atomic (no `.tmp` left behind).
- `_safe_caption`: new `{caption}`/`{hashtags}` fields render; missing meta
  still yields the legacy string; unknown placeholder still tolerated.
- Light: a `clipper_worker`-level test (mocking download/split) asserts a
  `_meta.json` is written with caption fields when `auto_caption` is on, and
  raw-only when off. (If full worker mocking is too heavy, instead unit-test
  a small extracted helper that does the meta-build+save step.)

Existing suites (cookies/account/driver/uploader/clipper/validators/config)
must stay green.

## Acceptance Criteria

1. Clipping a YouTube video writes `<clip_dir>/_meta.json` containing the
   real title, description, tags, and a generated `caption` + `hashtags`.
2. With an LLM configured, `source == "llm"` and the caption is a concise
   hook with 3–5 sanitized hashtags; with no LLM, `source == "rule"` and a
   sane caption + tag-derived hashtags are still produced.
3. Uploading from that clip folder posts with the generated caption +
   hashtags (verified via the existing Studio path; `_safe_caption` output
   inspected — no live post required for this feature's automated tests).
4. A clip folder with no `_meta.json` uploads exactly as before (no
   regression).
5. The "Auto-generate caption" checkbox toggles generation; all existing and
   new unit tests pass.
6. A bare local-file source (no URL, no tags) yields `url: ""`, a non-empty
   rule caption, and empty `hashtags`; `_build_description` renders
   `"{caption}\n\n{hashtags}"` cleanly with empty hashtags (no trailing
   `\n\n`, no literal `{hashtags}`) — covered by a unit test.
