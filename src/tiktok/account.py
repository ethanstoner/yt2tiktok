import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from src.tiktok.driver import make_driver
from src.tiktok.cookies import cookie_health, to_selenium_cookies

_ACCOUNTS_DIR = Path.home() / ".yt2tiktok" / "accounts"


@dataclass
class Account:
    id: str
    label: str
    cookies: list = field(default_factory=list)
    username: str | None = None
    last_verified: str | None = None

    def health(self) -> dict:
        return cookie_health(self.cookies)


def _ensure_dir():
    _ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)


def save_account(account: Account):
    _ensure_dir()
    path = _ACCOUNTS_DIR / f"{account.id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(account), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_accounts() -> list[Account]:
    if not _ACCOUNTS_DIR.exists():
        return []
    out = []
    for p in sorted(_ACCOUNTS_DIR.glob("*.json")):
        try:
            out.append(Account(**json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return out


def get_account(account_id: str) -> Account | None:
    for a in load_accounts():
        if a.id == account_id:
            return a
    return None


def _scrape_username(driver) -> str | None:
    """Navigate to the profile and return the @handle, or None."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    driver.get("https://www.tiktok.com/foryou")
    wait = WebDriverWait(driver, 20)
    avatar = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, 'header [data-e2e="nav-avatar"]')))
    avatar.click()
    link = wait.until(EC.visibility_of_element_located(
        (By.CSS_SELECTOR, 'a[href*="/@"]')))
    href = link.get_attribute("href") or ""
    return href.split("/@")[-1].split("?")[0] or None


def verify(account: Account, headless: bool = True) -> str | None:
    """Inject cookies, resolve @username, persist it. Returns username or None."""
    driver = None
    try:
        driver = make_driver(headless=headless, account_id=account.id)
        driver.get("https://www.tiktok.com/")
        for c in to_selenium_cookies(account.cookies):
            try:
                driver.add_cookie(c)
            except Exception:
                cc = dict(c)
                cc.pop("domain", None)
                try:
                    driver.add_cookie(cc)
                except Exception:
                    pass
        username = _scrape_username(driver)
        if username:
            account.username = username
            account.last_verified = datetime.now(timezone.utc).isoformat()
            save_account(account)
        return username
    except Exception:
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
