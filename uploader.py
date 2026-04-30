import os
import json
import datetime
import calendar
import time
from pathlib import Path

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

UPLOAD_TIMEOUT = 600
RETRY_COUNT = 2
RETRY_DELAY = 30
QUIET_HOURS_START = 23
QUIET_HOURS_END = 8
MAX_SCHEDULE_DAYS = 10
DEBUG_DIR = Path(__file__).parent / "debug"

COOKIE_SEARCH_DIRS = [
    Path.cwd(),
    Path.home(),
    Path.home() / "tiktok_cookies",
]

_CONFIG_PATH = Path.home() / ".yt2tiktok.json"


def parse_cookies_file(cookie_file_path: str) -> list[dict] | None:
    cookies = []
    if not os.path.exists(cookie_file_path):
        return None
    try:
        with open(cookie_file_path, "r") as fp:
            for line in fp:
                if line.startswith("#") or line.strip() == "":
                    continue
                parts = line.strip().split("\t")
                if len(parts) == 7:
                    domain, _, path, _, expiry, name, value = parts
                    cookies.append({"name": name, "value": value, "domain": domain, "path": path, "expiry": int(expiry)})
    except Exception:
        return None
    return cookies if cookies else None


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
    try:
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text())
            path = data.get("last_cookie_path", "")
            if path and os.path.exists(path):
                return path
    except Exception:
        pass
    return ""


def save_last_cookie_path(path: str):
    try:
        data = {}
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text())
        data["last_cookie_path"] = path
        _CONFIG_PATH.write_text(json.dumps(data))
    except Exception:
        pass


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
        for cookie in cookies:
            driver.add_cookie(cookie)
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
        if driver and headless:
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
        driver.get("https://www.tiktok.com/upload")
        wait = WebDriverWait(driver, 30)
        file_input = wait.until(EC.presence_of_element_located((By.XPATH, SELECTORS["file_input"])))
        file_input.send_keys(video_path)
        if log_fn:
            log_fn("Waiting for video processing (up to 10 min)...")
        upload_wait = WebDriverWait(driver, UPLOAD_TIMEOUT)
        upload_wait.until(EC.element_to_be_clickable((By.XPATH, SELECTORS["replace_button"])))
        caption_div = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, SELECTORS["caption_editor"])))
        actions = ActionChains(driver)
        actions.move_to_element(caption_div).click()
        actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL)
        actions.send_keys(Keys.DELETE).perform()
        time.sleep(1)
        caption_div.send_keys(description)
        schedule_btn = wait.until(EC.element_to_be_clickable((By.XPATH, SELECTORS["schedule_radio"])))
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
        final_btn = wait.until(EC.element_to_be_clickable((By.XPATH, SELECTORS["post_button"])))
        final_btn.click()
        wait.until(EC.visibility_of_element_located((By.XPATH, SELECTORS["manage_posts"])))
        if log_fn:
            log_fn("Upload confirmed.")
        return True
    except TimeoutException as e:
        if log_fn:
            log_fn(f"Upload timed out: {str(e).splitlines()[0]}")
        _save_debug_screenshot(driver, f"timeout_{schedule_time.strftime('%H%M')}")
        return False
    except Exception as e:
        if log_fn:
            log_fn(f"Upload error: {str(e).splitlines()[0]}")
        _save_debug_screenshot(driver, f"error_{schedule_time.strftime('%H%M')}")
        return False


def _save_debug_screenshot(driver, name: str):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(str(DEBUG_DIR / f"{name}.png"))
    except Exception:
        pass


def _adjust_quiet_hours(dt: datetime.datetime) -> datetime.datetime:
    while dt.hour >= QUIET_HOURS_START or dt.hour < QUIET_HOURS_END:
        if dt.hour >= QUIET_HOURS_START:
            dt = (dt + datetime.timedelta(days=1)).replace(hour=QUIET_HOURS_END, minute=0, second=0)
        else:
            dt = dt.replace(hour=QUIET_HOURS_END, minute=0, second=0)
    return dt


def upload_clips(clips_dir: str, title: str, total_clips: int, cookie_file: str, caption_template: str = "{title} - Part {part}", start_time_str: str = "10:00", interval_hours: float = 2.0, headless: bool = True, log_fn=None) -> tuple[int, int]:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager

    cookies = parse_cookies_file(cookie_file)
    if not cookies:
        if log_fn:
            log_fn("Could not parse cookie file.")
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
    else:
        options.add_experimental_option("detach", True)
    options.add_argument("--log-level=3")

    driver = None
    successful = 0
    failed_clips: list[str] = []

    try:
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        driver.get("https://www.tiktok.com/")
        for cookie in cookies:
            driver.add_cookie(cookie)

        for idx, clip_path in enumerate(clip_files):
            part_num = idx + 1
            schedule_time = _adjust_quiet_hours(schedule_time)

            if (schedule_time - now).days > MAX_SCHEDULE_DAYS:
                if log_fn:
                    log_fn(f"Skipping Part {part_num}+: exceeds TikTok 10-day schedule limit.")
                failed_clips.extend(clip_files[idx:])
                break

            description = caption_template.format(title=title, part=part_num, total=total_clips)
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
        if driver and headless:
            driver.quit()

    if failed_clips:
        failed_path = os.path.join(clips_dir, "failed_clips.txt")
        with open(failed_path, "w") as f:
            for fp in failed_clips:
                f.write(f"{fp}\n")
        if log_fn:
            log_fn(f"Failed clips logged to: {failed_path}")

    if log_fn:
        log_fn(f"Done: {successful}/{total} clips scheduled.")
    return successful, total
