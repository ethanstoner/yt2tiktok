from pathlib import Path

from src.logger import get_logger

_log = get_logger(__name__)
_PROFILE_ROOT = Path.home() / ".yt2tiktok" / "chrome-profile"


def _profile_dir(account_id: str) -> str:
    d = _PROFILE_ROOT / account_id
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _make_uc_driver(headless: bool, account_id: str):
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={_profile_dir(account_id)}")
    opts.add_argument("--log-level=3")
    opts.add_argument("--window-size=1280,900")
    if headless:
        opts.add_argument("--headless=new")
    return uc.Chrome(options=opts)


def _make_fallback_driver(headless: bool, account_id: str):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    opts = webdriver.ChromeOptions()
    opts.add_argument(f"--user-data-dir={_profile_dir(account_id)}")
    opts.add_argument("--log-level=3")
    if headless:
        opts.add_argument("--headless")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts)


def make_driver(headless: bool, account_id: str):
    """undetected-chromedriver with a persistent profile; plain Selenium
    fallback so the app never hard-fails if uc is unavailable."""
    try:
        return _make_uc_driver(headless, account_id)
    except Exception as e:
        _log.warning("undetected-chromedriver unavailable (%s); "
                     "falling back to plain Selenium", e)
        return _make_fallback_driver(headless, account_id)
