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
    """Resolve the logged-in account's @handle, or None.

    Reads the profile link directly (no avatar click). When cookies are
    valid, /foryou exposes anchors like
    https://www.tiktok.com/@<handle> — we pick the first that looks like a
    bare profile URL (no extra path segment such as /video/).
    """
    import re
    import time as _t
    driver.get("https://www.tiktok.com/foryou")
    deadline = _t.time() + 20
    pat = re.compile(r"tiktok\.com/@([A-Za-z0-9._]+)/?(?:\?|$)")
    while _t.time() < deadline:
        for a in driver.find_elements("css selector", 'a[href*="/@"]'):
            href = a.get_attribute("href") or ""
            m = pat.search(href)
            if m:
                return m.group(1)
        _t.sleep(0.5)
    return None


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
