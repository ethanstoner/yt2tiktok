import os
import datetime
import calendar
import time
import time as _time
from pathlib import Path
from selenium.webdriver.common.by import By
from src import config as cfg
from src.tiktok.account import get_account
from src.tiktok.cookies import to_selenium_cookies

# ─── TikTok Selector Constants ───────────────────────────────────────────
SELECTORS = {
    "file_input": '//input[@type="file"]',
    "replace_button": "//button[div[text()='Replace']]",
    "caption_editor": "div.public-DraftEditor-content",
    "schedule_radio": "//*[text()='Schedule']",
    "schedule_container": "//div[contains(@class, 'scheduled-picker')]",
    "time_input_class": "TUXTextInput",
    "time_picker_body": ".tiktok-time-picker-body",
    "calendar_header": "div[class*='-calendar-header-title']",
    "calendar_arrow_right": "button[class*='-calendar-arrow-right']",
    "calendar_arrow_left": "button[class*='-calendar-arrow-left']",
    "calendar_day": "-calendar-day",
    "post_button": "//button[@data-e2e='post-button' and not(@disabled)]",
    "manage_posts": "//*[text()='Manage your posts']",
    "nav_avatar": 'header [data-e2e="nav-avatar"]',
    "profile_link": 'a[href*="/@"]',
}

SELECTORS_FB = {
    "file_input": [(By.XPATH, '//input[@type="file"]')],
    "replace_button": [
        (By.XPATH, "//button[div[text()='Replace']]"),
        (By.XPATH, "//button[contains(.,'Replace')]"),
    ],
    "caption_editor": [
        # Verified live 2026-05-15: TikTok Studio still uses DraftEditor.
        (By.CSS_SELECTOR, '[data-e2e="caption_container"] div.public-DraftEditor-content'),
        (By.CSS_SELECTOR, "div.public-DraftEditor-content"),
        (By.CSS_SELECTOR, '[data-e2e="caption-editor"] [contenteditable="true"]'),
        (By.CSS_SELECTOR, 'div[contenteditable="true"]'),
    ],
    "schedule_radio": [
        (By.XPATH, "//*[text()='Schedule']"),
        (By.XPATH, "//*[contains(text(),'Schedule')]"),
    ],
    "post_button": [
        # Verified live 2026-05-15: TikTok Studio uses data-e2e="post_video_button".
        (By.CSS_SELECTOR, '[data-e2e="post_video_button"] button:not([disabled])'),
        (By.CSS_SELECTOR, 'button[data-e2e="post_video_button"]:not([disabled])'),
        (By.XPATH, "//button[@data-e2e='post-button' and not(@disabled)]"),
        (By.XPATH, "//button[.//div[text()='Post'] and not(@disabled)]"),
    ],
    "manage_posts": [
        (By.XPATH, "//*[text()='Manage your posts']"),
        (By.XPATH, "//*[contains(text(),'Manage your posts')]"),
    ],
}

UPLOAD_TIMEOUT = 600
RETRY_COUNT = 2
RETRY_DELAY = 30
QUIET_HOURS_START = 23
QUIET_HOURS_END = 8
MAX_SCHEDULE_DAYS = 10
DEBUG_DIR = Path(__file__).parent.parent / "debug"

COOKIE_SEARCH_DIRS = [
    Path.cwd(),
    Path.home(),
    Path.home() / "tiktok_cookies",
]


class UploadElementNotFound(Exception):
    pass


def _find(driver, locators, timeout: int = 15):
    """Try each (By, value) locator in order until one is present.
    `locators` is an ordered list of fallbacks. Raises
    UploadElementNotFound if none match within `timeout` seconds."""
    from selenium.common.exceptions import NoSuchElementException
    deadline = _time.time() + timeout
    while True:
        for by, value in locators:
            try:
                return driver.find_element(by, value)
            except NoSuchElementException:
                continue
        if _time.time() >= deadline:
            raise UploadElementNotFound(
                f"None of {len(locators)} locators matched: {locators}")
        _time.sleep(0.5)


def _resolve_cookies(account_id, cookie_file):
    """Single cookie-resolution path: stored account first, else legacy
    Netscape file. Returns Selenium-ready cookie dicts (or [])."""
    if account_id:
        acc = get_account(account_id)
        if acc and acc.cookies:
            return to_selenium_cookies(acc.cookies)
    if cookie_file:
        legacy = parse_cookies_file(cookie_file)
        if legacy:
            return legacy
    return []


def _save_debug(driver, label: str):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        driver.save_screenshot(str(DEBUG_DIR / f"{ts}_{label}.png"))
        (DEBUG_DIR / f"{ts}_{label}.html").write_text(
            driver.page_source, encoding="utf-8")
    except Exception:
        pass


def parse_cookies_file(cookie_file_path: str) -> list[dict] | None:
    cookies = []
    if not os.path.exists(cookie_file_path):
        return None
    try:
        with open(cookie_file_path, "r", encoding="utf-8", errors="replace") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    # "#HttpOnly_" is a real cookie line, not a comment.
                    if line.startswith("#HttpOnly_"):
                        line = line[len("#HttpOnly_"):]
                    else:
                        continue
                parts = line.split("\t")
                if len(parts) == 7:
                    domain, _, path, _, expiry, name, value = parts
                    try:
                        expiry_int = int(expiry)
                    except (ValueError, TypeError):
                        expiry_int = 0
                    cookies.append({"name": name, "value": value, "domain": domain, "path": path, "expiry": expiry_int})
    except Exception:
        return None
    return cookies if cookies else None


def _add_cookies(driver, cookies: list[dict], log_fn=None) -> int:
    """Add cookies one by one so a single bad/expired/domain-mismatched
    cookie can't abort the whole session. Returns count added."""
    added = 0
    for cookie in cookies:
        c = dict(cookie)
        # Selenium rejects expiry=0 (or non-positive) on many driver versions.
        if not c.get("expiry"):
            c.pop("expiry", None)
        try:
            driver.add_cookie(c)
            added += 1
        except Exception:
            try:
                # Retry without domain (lets the browser scope it to the
                # current page) — handles leading-dot/subdomain mismatches.
                c.pop("domain", None)
                driver.add_cookie(c)
                added += 1
            except Exception:
                if log_fn:
                    log_fn(f"Skipped unusable cookie: {c.get('name', '?')}")
    return added


def find_cookie_files() -> list[str]:
    found = []
    for d in COOKIE_SEARCH_DIRS:
        if d.is_dir():
            for f in d.iterdir():
                if f.suffix == ".txt" and not f.name.startswith(".") and f.name != "requirements.txt":
                    if parse_cookies_file(str(f)) is not None:
                        found.append(str(f))
    return sorted(found)


def load_last_cookie_path() -> str:
    path = cfg.get("last_cookie_path", "")
    if path and os.path.exists(path):
        return path
    return ""


def save_last_cookie_path(path: str):
    cfg.set("last_cookie_path", path)


def verify_cookies(cookie_file: str, headless: bool = True, log_fn=None) -> str | None:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    cookies = parse_cookies_file(cookie_file)
    if not cookies:
        return None

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-gpu")

    driver = None
    try:
        if log_fn:
            log_fn("Verifying cookies...")
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        driver.get("https://www.tiktok.com/")
        if _add_cookies(driver, cookies, log_fn) == 0:
            if log_fn:
                log_fn("No usable cookies could be loaded.")
            return None
        driver.get("https://www.tiktok.com/foryou")

        wait = WebDriverWait(driver, 20)
        avatar = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["nav_avatar"])))
        avatar.click()
        profile_link = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, SELECTORS["profile_link"])))
        href = profile_link.get_attribute("href")
        username = href.split("/@")[-1].split("?")[0]
        if log_fn:
            log_fn(f"Verified: @{username}")
        return username
    except TimeoutException:
        if log_fn:
            log_fn("Verification timed out. Login may have failed or CAPTCHA blocked.")
        return None
    except Exception as e:
        if log_fn:
            log_fn(f"Verification failed: {str(e).splitlines()[0]}")
        return None
    finally:
        if driver:
            driver.quit()


def _upload_single_video(driver, video_path: str, description: str, schedule_time, log_fn=None) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains

    try:
        if log_fn:
            log_fn("Navigating to upload page...")
        # TikTok moved uploads to TikTok Studio (verified live 2026-05-15);
        # the legacy /upload path redirects here anyway.
        driver.get("https://www.tiktok.com/tiktokstudio/upload")
        wait = WebDriverWait(driver, 30)
        file_input = _find(driver, SELECTORS_FB["file_input"], timeout=30)
        file_input.send_keys(video_path)
        if log_fn:
            log_fn("Waiting for video processing (up to 10 min)...")
        _find(driver, SELECTORS_FB["replace_button"], timeout=UPLOAD_TIMEOUT)
        caption_div = _find(driver, SELECTORS_FB["caption_editor"], timeout=30)
        actions = ActionChains(driver)
        actions.move_to_element(caption_div).click()
        actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL)
        actions.send_keys(Keys.DELETE).perform()
        time.sleep(1)
        caption_div.send_keys(description)
        schedule_btn = _find(driver, SELECTORS_FB["schedule_radio"], timeout=30)
        schedule_btn.click()
        time.sleep(1)
        container = wait.until(EC.visibility_of_element_located((By.XPATH, SELECTORS["schedule_container"])))
        time.sleep(1)
        pickers = container.find_elements(By.XPATH, f".//div[contains(@class, '{SELECTORS['time_input_class']}')]")
        if len(pickers) < 2:
            if log_fn:
                log_fn(f"Could not find time/date pickers (found {len(pickers)})")
            return False
        time_dropdown, date_dropdown = pickers[0], pickers[1]
        driver.execute_script("arguments[0].click();", time_dropdown)
        time.sleep(1)
        time_picker = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, SELECTORS["time_picker_body"])))
        columns = time_picker.find_elements(By.TAG_NAME, "ul")
        hour_col, minute_col = columns[0], columns[1]
        hour_el = hour_col.find_element(By.XPATH, f".//li[text()='{schedule_time.hour}']")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", hour_el)
        time.sleep(0.5)
        hour_el.click()
        minute_el = minute_col.find_element(By.XPATH, f".//li[text()='{schedule_time.strftime('%M')}']")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", minute_el)
        time.sleep(0.5)
        minute_el.click()
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(1)
        container = wait.until(EC.visibility_of_element_located((By.XPATH, SELECTORS["schedule_container"])))
        date_dropdown = container.find_elements(By.XPATH, f".//div[contains(@class, '{SELECTORS['time_input_class']}')]")[1]
        driver.execute_script("arguments[0].click();", date_dropdown)
        time.sleep(1)
        month_name_to_num = {name: num for num, name in enumerate(calendar.month_name) if num}
        while True:
            header_text = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, SELECTORS["calendar_header"]))).text
            current_month_str, current_year_str = header_text.split(" / ")
            current_year = int(current_year_str)
            current_month = month_name_to_num[current_month_str.strip()]
            if current_year == schedule_time.year and current_month == schedule_time.month:
                break
            current_val = current_year * 12 + current_month
            target_val = schedule_time.year * 12 + schedule_time.month
            if target_val > current_val:
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["calendar_arrow_right"]))).click()
            else:
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["calendar_arrow_left"]))).click()
            time.sleep(0.5)
        day_xpath = (f"//div[contains(@class, '{SELECTORS['calendar_day']}') and not(contains(@class, 'outside')) and text()='{schedule_time.day}']")
        wait.until(EC.element_to_be_clickable((By.XPATH, day_xpath))).click()
        final_btn = _find(driver, SELECTORS_FB["post_button"], timeout=30)
        final_btn.click()
        _find(driver, SELECTORS_FB["manage_posts"], timeout=30)
        if log_fn:
            log_fn("Upload confirmed.")
        return True
    except TimeoutException as e:
        if log_fn:
            log_fn(f"Upload timed out: {str(e).splitlines()[0]}")
        _save_debug(driver, f"post_fail_{schedule_time.strftime('%H%M')}")
        return False
    except Exception as e:
        if log_fn:
            log_fn(f"Upload error: {str(e).splitlines()[0]}")
        _save_debug(driver, f"post_fail_{schedule_time.strftime('%H%M')}")
        return False


def _safe_caption(template: str, title, part, total) -> str:
    """Format a user-supplied caption template without crashing on unknown
    placeholders or stray braces."""
    fields = {"title": title, "part": part, "total": total}

    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return template.format_map(_Safe(fields))
    except (ValueError, IndexError):
        # Unbalanced/positional braces — fall back to a sane default.
        return f"{title} - Part {part}"


def _adjust_quiet_hours(dt: datetime.datetime) -> datetime.datetime:
    while dt.hour >= QUIET_HOURS_START or dt.hour < QUIET_HOURS_END:
        if dt.hour >= QUIET_HOURS_START:
            dt = (dt + datetime.timedelta(days=1)).replace(hour=QUIET_HOURS_END, minute=0, second=0)
        else:
            dt = dt.replace(hour=QUIET_HOURS_END, minute=0, second=0)
    return dt


def upload_clips(clips_dir: str, title: str, total_clips: int, account_id: str = None, cookie_file: str = None, caption_template: str = "{title} - Part {part}", start_time_str: str = "10:00", interval_hours: float = 2.0, headless: bool = True, log_fn=None) -> tuple[int, int]:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager

    cookies = _resolve_cookies(account_id, cookie_file)
    if not cookies:
        if log_fn:
            log_fn("Could not load cookies (no account or cookie file).")
        return 0, 0

    clip_files = sorted(
        [os.path.join(clips_dir, f) for f in os.listdir(clips_dir) if f.endswith(".mp4") and "_clip_" in f],
        key=lambda x: int(x.split("_clip_")[-1].split(".")[0]),
    )
    if not clip_files:
        if log_fn:
            log_fn("No clips found in directory.")
        return 0, 0

    total = len(clip_files)
    if log_fn:
        log_fn(f"Found {total} clips to upload.")

    start_hour, start_minute = map(int, start_time_str.split(":"))
    local_tz = datetime.datetime.now().astimezone().tzinfo
    now = datetime.datetime.now(local_tz)
    schedule_time = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    if schedule_time < now:
        schedule_time += datetime.timedelta(days=1)
    interval = datetime.timedelta(hours=interval_hours)

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--log-level=3")

    driver = None
    successful = 0
    failed_clips: list[str] = []

    try:
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        driver.get("https://www.tiktok.com/")
        if _add_cookies(driver, cookies, log_fn) == 0:
            if log_fn:
                log_fn("No usable cookies could be loaded; aborting upload.")
            return 0, total

        for idx, clip_path in enumerate(clip_files):
            part_num = idx + 1
            schedule_time = _adjust_quiet_hours(schedule_time)

            if (schedule_time - now).days > MAX_SCHEDULE_DAYS:
                if log_fn:
                    log_fn(f"Skipping Part {part_num}+: exceeds TikTok 10-day schedule limit.")
                failed_clips.extend(clip_files[idx:])
                break

            description = _safe_caption(caption_template, title, part_num, total_clips)
            if log_fn:
                log_fn(f"Scheduling Part {part_num} for {schedule_time.strftime('%Y-%m-%d %H:%M')}")

            success = False
            for attempt in range(1, RETRY_COUNT + 2):
                success = _upload_single_video(driver, clip_path, description, schedule_time, log_fn)
                if success:
                    break
                if attempt <= RETRY_COUNT:
                    if log_fn:
                        log_fn(f"Retry {attempt}/{RETRY_COUNT} in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)

            if success:
                successful += 1
                if log_fn:
                    log_fn(f"Part {part_num} scheduled successfully.")
            else:
                failed_clips.append(clip_path)
                if log_fn:
                    log_fn(f"Part {part_num} failed after retries.")

            schedule_time += interval
            time.sleep(5)

    except Exception as e:
        if log_fn:
            log_fn(f"Upload session error: {e}")
    finally:
        if driver:
            driver.quit()

    if failed_clips:
        try:
            failed_path = os.path.join(clips_dir, "failed_clips.txt")
            with open(failed_path, "w", encoding="utf-8") as f:
                for fp in failed_clips:
                    f.write(f"{fp}\n")
            if log_fn:
                log_fn(f"Failed clips logged to: {failed_path}")
        except OSError as e:
            if log_fn:
                log_fn(f"Could not write failed_clips.txt: {e}")

    if log_fn:
        log_fn(f"Done: {successful}/{total} clips scheduled.")
    return successful, total


_VISIBILITY_LABELS = {
    "public": "Everyone",
    "friends": "Friends",
    "private": "Only you",
}


def _studio_post(driver, video_path: str, description: str,
                 visibility: str = "private", log_fn=None) -> tuple[bool, str]:
    """Immediate post via TikTok Studio (verified live 2026-05-15).

    Scheduling is intentionally NOT handled here — Phase 3's persistent
    scheduler owns timing; Phase 1 only needs a reliable immediate post.
    `visibility`: 'public' | 'friends' | 'private' (default private =
    'Only you', the no-public-exposure verification path).
    """
    import time as _t
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    def _log(m):
        if log_fn:
            log_fn(m)

    try:
        driver.get("https://www.tiktok.com/tiktokstudio/upload")
        file_input = _find(driver, SELECTORS_FB["file_input"], timeout=30)
        file_input.send_keys(video_path)
        _log("Clip sent; waiting for TikTok to finish processing...")

        # Wait until the upload-status widget stops reporting progress.
        deadline = _t.time() + UPLOAD_TIMEOUT
        while _t.time() < deadline:
            try:
                el = driver.find_element(
                    By.CSS_SELECTOR, '[data-e2e="upload_status_container"]')
                txt = (el.text or "")
            except Exception:
                txt = ""
            if txt and "%" not in txt and "left" not in txt.lower():
                break
            _t.sleep(2)
        _log("Processing complete.")

        # Dismiss the react-joyride coach-mark tour: its full-page overlay
        # (z-index 1001) intercepts every click. Click any "Got it"/"Skip"
        # tour buttons, then hard-remove leftover joyride layers via JS.
        for _ in range(4):
            clicked = False
            for label in ("Got it", "Skip", "Next", "Close"):
                try:
                    b = driver.find_element(
                        By.XPATH, f"//button[normalize-space()='{label}']")
                    driver.execute_script("arguments[0].click();", b)
                    _t.sleep(0.8)
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                break
        driver.execute_script(
            "document.querySelectorAll("
            "'.react-joyride__overlay,.react-joyride__spotlight,"
            "[data-test-id=\"overlay\"]').forEach(e=>e.remove());")

        # Dismiss any "automatic content checks" / info modal if present.
        for label in ("Cancel", "Got it", "Not now"):
            try:
                btn = driver.find_element(
                    By.XPATH,
                    f"//div[contains(@class,'modal') or @role='dialog']"
                    f"//button[normalize-space()='{label}']")
                btn.click()
                _t.sleep(1)
                break
            except Exception:
                continue

        # Caption: clear the auto-filled filename, type our description.
        cap = _find(driver, SELECTORS_FB["caption_editor"], timeout=30)
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", cap)
        _t.sleep(0.3)
        driver.execute_script("arguments[0].click();", cap)
        cap.send_keys(Keys.CONTROL, "a")
        cap.send_keys(Keys.DELETE)
        _t.sleep(0.5)
        cap.send_keys(description)

        # Visibility ("Who can see this post").
        want = _VISIBILITY_LABELS.get(visibility, "Only you")
        if want != "Everyone":
            try:
                vis = driver.find_element(
                    By.CSS_SELECTOR, '[data-e2e="video_visibility_container"]')
                vis.click()
                _t.sleep(1)
                opt = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, f"//*[normalize-space()='{want}']")))
                opt.click()
                _t.sleep(1)
                _log(f"Visibility set to '{want}'.")
            except Exception as e:
                _save_debug(driver, "studio_visibility_fail")
                return (False, f"could not set visibility '{want}': {e}")

        # Post.
        post_btn = _find(driver, SELECTORS_FB["post_button"], timeout=30)
        driver.execute_script("arguments[0].click();", post_btn)
        _log("Post submitted; waiting for confirmation...")

        # Success = redirect to /tiktokstudio/content or a success toast.
        ok = False
        end = _t.time() + 120
        while _t.time() < end:
            url = driver.current_url
            if "content" in url or "upload" not in url:
                ok = True
                break
            try:
                if driver.find_elements(
                        By.XPATH, "//*[contains(text(),'Manage your posts') "
                        "or contains(text(),'Your video is being uploaded') "
                        "or contains(text(),'posted')]"):
                    ok = True
                    break
            except Exception:
                pass
            _t.sleep(2)
        _save_debug(driver, "studio_post_" + ("ok" if ok else "unconfirmed"))
        if ok:
            return (True, "")
        return (False, "post submitted but confirmation not detected (see debug/)")
    except UploadElementNotFound as e:
        _save_debug(driver, "studio_element_missing")
        return (False, f"element not found: {e}")
    except Exception as e:
        _save_debug(driver, "studio_error")
        return (False, f"error: {e}")


def upload_clip(driver, clip_path, description, schedule_time=None,
                visibility: str = "private", log_fn=None) -> tuple[bool, str]:
    """Post a single clip with a ready (cookie-injected) driver.

    Phase 1: immediate post via TikTok Studio. `schedule_time` is accepted
    for forward signature stability but ignored — Phase 3's persistent
    scheduler owns timing.
    """
    return _studio_post(driver, clip_path, description, visibility, log_fn)
