# Phase 1: Reliable Single-Account TikTok Upload — Design

**Date:** 2026-05-15
**Status:** Approved (pending spec review)
**Scope:** Phase 1 of 5. Subsequent phases (multi-account UI, persistent scheduler,
GitHub self-update, packaging) are explicitly deferred to their own specs.

## Problem

The app produces TikTok-ready clips but the upload path is unproven and unusable
in practice:

1. It only parses **Netscape `cookies.txt`**; the user exports **Cookie-Editor
   JSON** (browser-extension format).
2. The UI exposes a raw cookie-file path with no feedback — no account identity,
   no indication the session is alive or about to expire.
3. The Selenium automation uses headless Chrome with single, brittle selectors
   and no resilience, so real uploads fail silently.

Phase 1 makes a single account's upload reliably work, end to end, verified with
a real scheduled post.

## Goals

- Ingest TikTok cookies from Cookie-Editor JSON via paste **or** `.json` file.
- Resolve and display the real account `@username`.
- Show cookie health: time until the auth session expires / needs refresh.
- Upload + schedule one clip reliably via hardened web automation.
- Prove it with a real upload of a Wall Hacks clip scheduled to a future time
  (not an immediate public post).

## Non-Goals (deferred, decisions recorded)

| Deferred item | Decided direction (future spec) |
|---|---|
| Multi-account management UI | Phase 2 — store is already a list |
| Persistent scheduler: prime-time, 1/day pacing, jitter, cross-account spacing, "what's scheduled when" | Phase 3 — local persistent scheduler |
| GitHub auto-update | Phase 4 — in-app download & self-replace |
| Packaging / ship v1 | Phase 5 |

## Architecture

New package `src/tiktok/`, one responsibility per module. The existing
`src/uploader.py` is refactored to consume these instead of doing parsing and
driver creation inline.

### `src/tiktok/cookies.py`

Pure functions, no Selenium import (independently unit-testable).

- `parse_cookie_json(source: str) -> list[dict]`
  - `source` is either raw JSON text or a filesystem path to a `.json` file
    (auto-detected: if `os.path.exists(source)` read it, else treat as text).
  - Accepts the Cookie-Editor array format: objects with `name`, `value`,
    `domain`, `path`, `secure`, `httpOnly`, `expirationDate` (float epoch,
    optional), `session` (bool).
  - Returns normalized internal cookies:
    `{"name", "value", "domain", "path", "secure": bool, "httpOnly": bool,
      "expiry": int|None}` (`expiry` = `int(expirationDate)` or `None` when
    `session` is true / `expirationDate` absent).
  - Raises `ValueError` with a clear message on invalid/empty/non-array JSON or
    when no usable cookies are present.
- `to_selenium_cookies(cookies: list[dict]) -> list[dict]`
  - Maps normalized cookies to Selenium `add_cookie` dicts. Omits `expiry` when
    `None`. Does not emit `sameSite` (Selenium/Chrome rejects some values; the
    existing per-cookie `_add_cookies` retry path already handles failures).
- `cookie_health(cookies: list[dict], now: datetime|None=None) -> dict`
  - Considers only auth-critical names: `sessionid`, `sessionid_ss`,
    `sid_guard`, `sid_tt`.
  - Returns `{"status", "expires_at": datetime|None, "days_left": float|None,
    "detail": str}` where `status` is one of:
    - `valid` — all present auth cookies have expiry > now + 7 days
    - `expiring` — earliest auth expiry within 7 days (still > now)
    - `expired` — earliest auth expiry <= now
    - `session-only` — auth cookies present but none carry an expiry
    - `missing` — no auth-critical cookie present at all

### `src/tiktok/account.py`

- `Account` dataclass: `id: str`, `label: str`, `cookies: list[dict]`,
  `username: str|None`, `last_verified: str|None` (ISO), plus a computed
  `health` via `cookie_health`.
- `load_accounts() -> list[Account]` / `save_account(account)` —
  persisted as JSON files in `~/.yt2tiktok/accounts/<id>.json` (user home,
  never in the repo). Phase 1 uses a single account with `id="main"`; the API
  returns a list so Phase 2 only adds UI.
- `verify(account, headless: bool) -> str|None` — uses `driver.make_driver`,
  injects cookies via existing `_add_cookies`, navigates to
  `tiktok.com/foryou`, scrapes the `@username` (reusing the proven logic in the
  current `verify_cookies`), caches `username` + `last_verified`, persists, and
  returns the username (or `None` on failure).

### `src/tiktok/driver.py`

- `make_driver(headless: bool, account_id: str) -> webdriver` — creates an
  `undetected_chromedriver` Chrome with a persistent
  `user-data-dir = ~/.yt2tiktok/chrome-profile/<account_id>`, standard options
  (`--log-level=3`, window size, headless flag).
- On any `undetected_chromedriver` import or launch error, logs a warning and
  falls back to the existing plain `selenium` Chrome via
  `webdriver_manager` — the app must never hard-fail because uc is unavailable.

### `src/uploader.py` (refactor, not rewrite)

- Remove inline Netscape parsing and inline `webdriver.Chrome(...)`; call the
  new modules.
- `upload_clip(driver, clip_path, description, schedule_time: datetime|None,
  visibility: str)`:
  - `visibility` ∈ `{"public", "private", "draft"}` (Phase 1 verification uses
    a future `schedule_time` with `visibility="public"` — scheduled, not live
    now; `private`/`draft` available as safer options).
  - All element lookups go through a single `SELECTORS` dict where each logical
    element maps to an **ordered list of fallback locators**; a helper
    `_find(driver, key, timeout)` tries each in order.
  - On any step failure: save `<debug_dir>/<ts>_<step>.png` and
    `.html` (page source), then return a structured
    `(success: bool, reason: str)`.
  - Keep the existing `_safe_caption`, quiet-hours, retry, and per-cookie
    `_add_cookies` logic already added in the recent audit.
- `upload_clips(...)` keeps its current signature/behaviour but now sources
  cookies/driver from the new modules and calls `upload_clip` per file.

### UI: `src/ui/upload_tab.py`

Replace the cookie-path row with an **Account card**:

- Buttons: **Paste cookies JSON** (modal with a textarea + Load) and
  **Load .json file** (file picker, `*.json`).
- On load: `parse_cookie_json` → `save_account` → background `verify`.
- Card displays:
  - `@username` (or "Not verified yet").
  - A status pill driven by `cookie_health.status`:
    🟢 `Valid · expires in N days` · 🟠 `Expiring in N days` ·
    🔴 `Expired — re-export cookies` · ⚪ `Session-only — may drop` ·
    🔴 `No login cookies found`.
  - **Re-verify** button.
- Backward compatibility: if a legacy Netscape cookie path is already
  configured, it is still accepted (existing `parse_cookies_file` retained).
- Threading: parse on the UI thread (fast, pure); `verify` on a daemon thread
  marshalling UI updates via `after()` (matches existing `verify_worker`
  pattern), with `winfo_exists()` guards.

## Data Flow

```
Paste/Load JSON
  -> parse_cookie_json (normalize, validate)
  -> save_account (~/.yt2tiktok/accounts/main.json)
  -> [bg] make_driver(uc, profile) -> inject cookies -> scrape @username
  -> cookie_health -> update Account -> render card

Upload:
  pick clip(s) -> make_driver -> upload_clip(schedule_time, visibility)
    -> resilient selectors -> confirm via "Manage your posts"
    -> (success,reason); on fail: debug screenshot+html
```

## Error Handling

- Invalid/empty/non-array JSON, or no usable cookies → `ValueError`; card shows
  a clear message; nothing is persisted.
- Verify fails (CAPTCHA, expired, network) → card shows red/amber status with
  the reason; debug screenshot saved; no crash.
- Per-element selector fallback; hard failure saves screenshot+HTML and returns
  a structured failure rather than raising.
- `undetected_chromedriver` unavailable/incompatible → logged warning, fall
  back to plain Selenium.
- All new file writes use `encoding="utf-8"`; account store writes are atomic
  (temp + `os.replace`) consistent with the audited `config.py` pattern.

## Security

- The user's live session cookies are written only to
  `~/.yt2tiktok/accounts/main.json` (user home, outside the git repo).
- `.gitignore` gains explicit guards: `*.cookies.json`, `accounts/`,
  `chrome-profile/`, `debug/` (defense-in-depth against accidental commits of
  any local copies inside the working tree).
- No cookie value is logged; logs reference cookie **names** only (existing
  `_add_cookies` behaviour).

## Testing

Unit (pytest, no network/browser):

- `parse_cookie_json`:
  - The exact Cookie-Editor shape the user provided (fixture with scrubbed
    values) → `sessionid` present, `.www.tiktok.com` and `.tiktok.com` domains
    preserved, `session:true` cookie → `expiry None`.
  - Raw text input and file-path input both work.
  - Invalid JSON / `{}` / `[]` / non-cookie array → `ValueError`.
- `cookie_health`:
  - Future `sessionid` expiry > 7d → `valid` with correct `days_left`.
  - Expiry within 7d → `expiring`.
  - Past expiry → `expired`.
  - Auth cookies but all `session:true` → `session-only`.
  - No auth cookie → `missing`.
- `to_selenium_cookies`: keys correct, `expiry` omitted when `None`.
- Existing `test_uploader.py`, `test_validators.py`, `test_config.py`,
  `test_clipper.py` remain green (no regression).

Real verification (manual, recorded in the conversation, not pytest):

- Persist the user's cookies to `~/.yt2tiktok/accounts/main.json`.
- Load account → `verify` resolves `@username`.
- Take one existing Wall Hacks clip → `upload_clip` with
  `schedule_time = now + ~30 min`, `visibility="public"` (scheduled, not
  immediately live).
- Confirm TikTok accepts it ("Manage your posts" / scheduled-post
  confirmation); capture a screenshot as evidence.
- Success is claimed only after that confirmation is observed.

## Acceptance Criteria

1. Pasting the user's Cookie-Editor JSON (or loading the `.json`) produces a
   stored account with no errors.
2. The Account card shows the correct `@username` and an accurate expiry
   status derived from `sessionid`/`sid_guard` expiry.
3. One Wall Hacks clip is successfully scheduled on the user's real TikTok
   account to a future time, confirmed on-screen, with screenshot evidence.
4. All existing unit tests plus the new `cookies` tests pass.
5. No cookie material is committed to the repo; `.gitignore` guards are in
   place.
