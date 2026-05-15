# Phase 1: Reliable Single-Account TikTok Upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a single TikTok account's clip upload reliably work end-to-end: ingest Cookie-Editor JSON cookies, resolve the `@username`, show cookie-expiry health, and post a clip via hardened `undetected-chromedriver` automation — verified with a real scheduled upload.

**Architecture:** New `src/tiktok/` package with one responsibility per module (`cookies.py` pure parsing/health, `account.py` persisted Account model, `driver.py` browser factory with uc + plain-Selenium fallback). `src/uploader.py` is refactored to consume these and use resilient fallback selectors. The Upload tab's cookie-path row becomes an Account card. Spec: `docs/superpowers/specs/2026-05-15-tiktok-upload-phase1-design.md`.

**Tech Stack:** Python 3.12, pytest, customtkinter, Selenium, undetected-chromedriver (new dependency), existing `src/config.py` atomic-write/utf-8 patterns.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/tiktok/__init__.py` | Package marker |
| `src/tiktok/cookies.py` | Pure: parse Cookie-Editor JSON, cookie health, Selenium mapping. No Selenium import. |
| `src/tiktok/account.py` | `Account` model + JSON persistence in `~/.yt2tiktok/accounts/`; `verify()`. |
| `src/tiktok/driver.py` | `make_driver()` — uc Chrome w/ persistent profile, plain-Selenium fallback. |
| `src/uploader.py` (modify) | Resilient `_find` + `SELECTORS`, `_post_video`, `upload_clip`, unified cookie source in `upload_clips`. |
| `src/ui/upload_tab.py` (modify) | Account card (paste JSON / load .json / @username / health pill / re-verify). |
| `src/workers.py` (modify) | `uploader_worker`/`verify_worker` use account id, not Netscape path. |
| `.gitignore` (modify) | Guards: `accounts/`, `chrome-profile/`, `debug/`, `*.cookies.json`. |
| `requirements.txt` (modify) | Add `undetected-chromedriver`. |
| `tests/test_cookies.py` (create) | Unit tests for cookies.py. |
| `tests/test_account.py` (create) | Unit tests for account persistence (no browser). |
| `tests/test_driver.py` (create) | Unit test for driver fallback selection (mocked). |
| `tests/test_uploader_phase1.py` (create) | Unit tests for `_find` fallback + cookie-source resolution. |

**TDD note:** every code task is failing-test-first. Browser/UI behavior that cannot be unit-tested is covered by the manual verification in Task 10, which is mandatory and recorded.

---

## Task 1: Dependency + gitignore guards

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Add dependency**

Append to `requirements.txt` (one line):

```
undetected-chromedriver>=3.5.5
```

- [ ] **Step 2: Install it**

Run: `./venv/Scripts/python.exe -m pip install "undetected-chromedriver>=3.5.5"`
Expected: `Successfully installed undetected-chromedriver-...`

- [ ] **Step 3: Add gitignore guards**

Append to `.gitignore`:

```
# Phase 1: never commit local TikTok account material
accounts/
chrome-profile/
debug/
*.cookies.json
```

- [ ] **Step 4: Verify import works**

Run: `./venv/Scripts/python.exe -c "import undetected_chromedriver; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .gitignore
git commit -m "build: add undetected-chromedriver, gitignore account material"
```

---

## Task 2: `cookies.parse_cookie_json`

**Files:**
- Create: `src/tiktok/__init__.py` (empty)
- Create: `src/tiktok/cookies.py`
- Test: `tests/test_cookies.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cookies.py`:

```python
import json
import pytest
from src.tiktok.cookies import parse_cookie_json

EDITOR_JSON = [
    {"domain": ".tiktok.com", "expirationDate": 1794412081.282036,
     "httpOnly": True, "name": "sessionid", "path": "/", "secure": True,
     "session": False, "value": "SESSIONVAL"},
    {"domain": ".tiktok.com", "name": "s_v_web_id", "path": "/",
     "httpOnly": False, "secure": True, "session": True, "value": "SVID"},
    {"domain": ".www.tiktok.com", "name": "tiktok_webapp_theme", "path": "/",
     "httpOnly": False, "secure": True, "session": False,
     "expirationDate": 1804780241, "value": "dark"},
]


class TestParseCookieJson:
    def test_parses_raw_text(self):
        cookies = parse_cookie_json(json.dumps(EDITOR_JSON))
        names = {c["name"] for c in cookies}
        assert "sessionid" in names and "s_v_web_id" in names

    def test_session_cookie_has_no_expiry(self):
        cookies = parse_cookie_json(json.dumps(EDITOR_JSON))
        svid = next(c for c in cookies if c["name"] == "s_v_web_id")
        assert svid["expiry"] is None

    def test_expiry_is_int(self):
        cookies = parse_cookie_json(json.dumps(EDITOR_JSON))
        sid = next(c for c in cookies if c["name"] == "sessionid")
        assert sid["expiry"] == 1794412081
        assert sid["secure"] is True and sid["httpOnly"] is True

    def test_domains_preserved(self):
        cookies = parse_cookie_json(json.dumps(EDITOR_JSON))
        domains = {c["domain"] for c in cookies}
        assert ".tiktok.com" in domains and ".www.tiktok.com" in domains

    def test_reads_from_file(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(json.dumps(EDITOR_JSON), encoding="utf-8")
        assert len(parse_cookie_json(str(p))) == 3

    def test_invalid_json_raises_valueerror(self):
        with pytest.raises(ValueError):
            parse_cookie_json("not json")

    def test_empty_array_raises_valueerror(self):
        with pytest.raises(ValueError):
            parse_cookie_json("[]")

    def test_non_cookie_array_raises_valueerror(self):
        with pytest.raises(ValueError):
            parse_cookie_json(json.dumps([{"foo": "bar"}]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_cookies.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tiktok'`

- [ ] **Step 3: Write minimal implementation**

Create `src/tiktok/__init__.py` (empty file).

Create `src/tiktok/cookies.py`:

```python
import json
import os

_AUTH_NAMES = ("sessionid", "sessionid_ss", "sid_guard", "sid_tt")


def parse_cookie_json(source: str) -> list[dict]:
    """Parse a Cookie-Editor JSON export (raw text or path to a .json file)
    into normalized cookie dicts.

    Returns: list of {name, value, domain, path, secure, httpOnly, expiry}
    where expiry is int epoch seconds or None for session cookies.
    Raises ValueError on invalid/empty/non-cookie input.
    """
    if not source or not isinstance(source, str):
        raise ValueError("No cookie data provided.")
    text = source
    if os.path.exists(source):
        try:
            text = open(source, "r", encoding="utf-8").read()
        except OSError as e:
            raise ValueError(f"Could not read cookie file: {e}") from e
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(f"Not valid JSON: {e}") from e
    if not isinstance(data, list) or not data:
        raise ValueError("Cookie JSON must be a non-empty array.")

    out = []
    for item in data:
        if not isinstance(item, dict) or "name" not in item or "value" not in item:
            continue
        is_session = bool(item.get("session"))
        exp_raw = item.get("expirationDate")
        expiry = None if (is_session or exp_raw is None) else int(float(exp_raw))
        out.append({
            "name": item["name"],
            "value": item["value"],
            "domain": item.get("domain", ".tiktok.com"),
            "path": item.get("path", "/"),
            "secure": bool(item.get("secure", False)),
            "httpOnly": bool(item.get("httpOnly", False)),
            "expiry": expiry,
        })
    if not out:
        raise ValueError("No usable cookies found in the provided data.")
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_cookies.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/tiktok/__init__.py src/tiktok/cookies.py tests/test_cookies.py
git commit -m "feat(tiktok): parse Cookie-Editor JSON cookies"
```

---

## Task 3: `cookies.cookie_health`

**Files:**
- Modify: `src/tiktok/cookies.py`
- Test: `tests/test_cookies.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cookies.py`:

```python
from datetime import datetime, timezone
from src.tiktok.cookies import cookie_health


def _c(name, expiry):
    return {"name": name, "value": "v", "domain": ".tiktok.com",
            "path": "/", "secure": True, "httpOnly": True, "expiry": expiry}


class TestCookieHealth:
    NOW = datetime(2026, 5, 15, tzinfo=timezone.utc)
    NOW_TS = int(NOW.timestamp())

    def test_valid_far_future(self):
        h = cookie_health([_c("sessionid", self.NOW_TS + 60 * 86400)], self.NOW)
        assert h["status"] == "valid"
        assert 59 < h["days_left"] < 61

    def test_expiring_within_7_days(self):
        h = cookie_health([_c("sessionid", self.NOW_TS + 3 * 86400)], self.NOW)
        assert h["status"] == "expiring"

    def test_expired(self):
        h = cookie_health([_c("sessionid", self.NOW_TS - 86400)], self.NOW)
        assert h["status"] == "expired"

    def test_session_only(self):
        h = cookie_health([_c("sessionid", None)], self.NOW)
        assert h["status"] == "session-only"

    def test_missing_auth_cookie(self):
        h = cookie_health([_c("tiktok_webapp_theme", self.NOW_TS + 99999)], self.NOW)
        assert h["status"] == "missing"

    def test_uses_earliest_auth_expiry(self):
        h = cookie_health(
            [_c("sessionid", self.NOW_TS + 60 * 86400),
             _c("sid_guard", self.NOW_TS + 2 * 86400)], self.NOW)
        assert h["status"] == "expiring"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_cookies.py::TestCookieHealth -q`
Expected: FAIL — `ImportError: cannot import name 'cookie_health'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/tiktok/cookies.py`:

```python
from datetime import datetime, timezone


def cookie_health(cookies: list[dict], now: datetime | None = None) -> dict:
    """Assess auth-session health from the earliest auth-critical cookie."""
    now = now or datetime.now(timezone.utc)
    auth = [c for c in cookies if c["name"] in _AUTH_NAMES]
    if not auth:
        return {"status": "missing", "expires_at": None,
                "days_left": None, "detail": "No login cookies found."}
    expiries = [c["expiry"] for c in auth if c["expiry"] is not None]
    if not expiries:
        return {"status": "session-only", "expires_at": None,
                "days_left": None,
                "detail": "Login cookies are session-only and may drop."}
    earliest = min(expiries)
    expires_at = datetime.fromtimestamp(earliest, tz=timezone.utc)
    days_left = (expires_at - now).total_seconds() / 86400
    if days_left <= 0:
        status, detail = "expired", "Login expired — re-export cookies."
    elif days_left <= 7:
        status = "expiring"
        detail = f"Login expires in {days_left:.0f} day(s)."
    else:
        status = "valid"
        detail = f"Valid · expires in {days_left:.0f} days."
    return {"status": status, "expires_at": expires_at,
            "days_left": days_left, "detail": detail}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_cookies.py -q`
Expected: PASS (all cookies tests)

- [ ] **Step 5: Commit**

```bash
git add src/tiktok/cookies.py tests/test_cookies.py
git commit -m "feat(tiktok): cookie_health status from auth-cookie expiry"
```

---

## Task 4: `cookies.to_selenium_cookies`

**Files:**
- Modify: `src/tiktok/cookies.py`
- Test: `tests/test_cookies.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cookies.py`:

```python
from src.tiktok.cookies import to_selenium_cookies


class TestToSeleniumCookies:
    def test_maps_fields_and_keeps_expiry(self):
        out = to_selenium_cookies([_c("sessionid", 1794412081)])
        c = out[0]
        assert c["name"] == "sessionid" and c["expiry"] == 1794412081
        assert c["secure"] is True and c["httpOnly"] is True
        assert "sameSite" not in c

    def test_omits_expiry_when_none(self):
        out = to_selenium_cookies([_c("s_v_web_id", None)])
        assert "expiry" not in out[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_cookies.py::TestToSeleniumCookies -q`
Expected: FAIL — `ImportError: cannot import name 'to_selenium_cookies'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/tiktok/cookies.py`:

```python
def to_selenium_cookies(cookies: list[dict]) -> list[dict]:
    """Map normalized cookies to Selenium add_cookie dicts (no sameSite)."""
    out = []
    for c in cookies:
        sc = {
            "name": c["name"], "value": c["value"],
            "domain": c["domain"], "path": c["path"],
            "secure": c["secure"], "httpOnly": c["httpOnly"],
        }
        if c.get("expiry") is not None:
            sc["expiry"] = int(c["expiry"])
        out.append(sc)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_cookies.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tiktok/cookies.py tests/test_cookies.py
git commit -m "feat(tiktok): to_selenium_cookies mapping"
```

---

## Task 5: `account` model + persistence

**Files:**
- Create: `src/tiktok/account.py`
- Test: `tests/test_account.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_account.py`:

```python
import pytest
from src.tiktok import account as acct


@pytest.fixture
def tmp_accounts(tmp_path, monkeypatch):
    d = tmp_path / "accounts"
    monkeypatch.setattr(acct, "_ACCOUNTS_DIR", d)
    return d


class TestAccountStore:
    def test_save_then_load_roundtrip(self, tmp_accounts):
        a = acct.Account(id="main", label="Main",
                          cookies=[{"name": "sessionid", "value": "x",
                                    "domain": ".tiktok.com", "path": "/",
                                    "secure": True, "httpOnly": True,
                                    "expiry": 1794412081}])
        acct.save_account(a)
        loaded = acct.load_accounts()
        assert len(loaded) == 1
        assert loaded[0].id == "main"
        assert loaded[0].cookies[0]["name"] == "sessionid"

    def test_load_empty_when_no_dir(self, tmp_accounts):
        assert acct.load_accounts() == []

    def test_health_computed_from_cookies(self, tmp_accounts):
        a = acct.Account(id="main", label="Main",
                         cookies=[{"name": "sessionid", "value": "x",
                                   "domain": ".tiktok.com", "path": "/",
                                   "secure": True, "httpOnly": True,
                                   "expiry": 32503680000}])
        assert a.health()["status"] == "valid"

    def test_get_account_returns_none_when_absent(self, tmp_accounts):
        assert acct.get_account("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_account.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Create `src/tiktok/account.py`:

```python
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from src.tiktok.cookies import cookie_health

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_account.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/tiktok/account.py tests/test_account.py
git commit -m "feat(tiktok): Account model + atomic JSON persistence"
```

---

## Task 6: `driver.make_driver` with fallback

**Files:**
- Create: `src/tiktok/driver.py`
- Test: `tests/test_driver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_driver.py`:

```python
from src.tiktok import driver as drv


class TestMakeDriverFallback:
    def test_falls_back_when_uc_fails(self, monkeypatch):
        calls = []
        monkeypatch.setattr(drv, "_make_uc_driver",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no uc")))
        monkeypatch.setattr(drv, "_make_fallback_driver",
                            lambda *a, **k: calls.append("fallback") or "DRIVER")
        d = drv.make_driver(headless=True, account_id="main")
        assert d == "DRIVER" and calls == ["fallback"]

    def test_uses_uc_when_available(self, monkeypatch):
        monkeypatch.setattr(drv, "_make_uc_driver", lambda *a, **k: "UC")
        monkeypatch.setattr(drv, "_make_fallback_driver",
                            lambda *a, **k: "SHOULD_NOT_BE_CALLED")
        assert drv.make_driver(headless=False, account_id="main") == "UC"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_driver.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Create `src/tiktok/driver.py`:

```python
from pathlib import Path

from src.logger import get_logger

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
        get_logger().warning("undetected-chromedriver unavailable (%s); "
                              "falling back to plain Selenium", e)
        return _make_fallback_driver(headless, account_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_driver.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/tiktok/driver.py tests/test_driver.py
git commit -m "feat(tiktok): make_driver with uc + Selenium fallback"
```

---

## Task 7: `account.verify` (mocked-driver test)

**Files:**
- Modify: `src/tiktok/account.py`
- Test: `tests/test_account.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_account.py`:

```python
class _FakeEl:
    def __init__(self, href): self._h = href
    def click(self): pass
    def get_attribute(self, k): return self._h


class _FakeDriver:
    def __init__(self): self.added = []
    def get(self, url): pass
    def add_cookie(self, c): self.added.append(c)
    def quit(self): pass


def test_verify_resolves_username(tmp_accounts, monkeypatch):
    fake = _FakeDriver()
    monkeypatch.setattr(acct, "make_driver", lambda **k: fake)
    # _scrape_username is the single seam that touches Selenium waits.
    monkeypatch.setattr(acct, "_scrape_username", lambda d: "cooluser")
    a = acct.Account(id="main", label="Main",
                     cookies=[{"name": "sessionid", "value": "x",
                               "domain": ".tiktok.com", "path": "/",
                               "secure": True, "httpOnly": True,
                               "expiry": 32503680000}])
    name = acct.verify(a, headless=True)
    assert name == "cooluser"
    assert a.username == "cooluser" and a.last_verified is not None
    assert acct.get_account("main").username == "cooluser"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_account.py::test_verify_resolves_username -q`
Expected: FAIL — `AttributeError: module 'src.tiktok.account' has no attribute 'verify'`

- [ ] **Step 3: Write minimal implementation**

Add imports at top of `src/tiktok/account.py`:

```python
from datetime import datetime, timezone

from src.tiktok.driver import make_driver
from src.tiktok.cookies import to_selenium_cookies
```

Append to `src/tiktok/account.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_account.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/tiktok/account.py tests/test_account.py
git commit -m "feat(tiktok): account.verify resolves and persists @username"
```

---

## Task 8: Uploader resilient selectors + cookie-source unification

**Files:**
- Modify: `src/uploader.py`
- Test: `tests/test_uploader_phase1.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_uploader_phase1.py`:

```python
import pytest
from src import uploader


class _El: pass


class _FakeDriver:
    def __init__(self, found):  # found: set of (by,value) that "exist"
        self._found = found
    def find_element(self, by, value):
        if (by, value) in self._found:
            return _El()
        from selenium.common.exceptions import NoSuchElementException
        raise NoSuchElementException(value)


class TestFindFallback:
    def test_returns_first_matching_locator(self):
        from selenium.webdriver.common.by import By
        d = _FakeDriver(found={(By.XPATH, "//b")})
        el = uploader._find(d, [(By.XPATH, "//a"), (By.XPATH, "//b")], timeout=0)
        assert isinstance(el, _El)

    def test_raises_when_no_locator_matches(self):
        from selenium.webdriver.common.by import By
        d = _FakeDriver(found=set())
        with pytest.raises(uploader.UploadElementNotFound):
            uploader._find(d, [(By.XPATH, "//a")], timeout=0)


class TestCookieSource:
    def test_prefers_account_store(self, monkeypatch):
        from src.tiktok.account import Account
        a = Account(id="main", label="m",
                    cookies=[{"name": "sessionid", "value": "v",
                              "domain": ".tiktok.com", "path": "/",
                              "secure": True, "httpOnly": True, "expiry": 1}])
        monkeypatch.setattr(uploader, "get_account", lambda i: a)
        cookies = uploader._resolve_cookies(account_id="main", cookie_file=None)
        assert cookies[0]["name"] == "sessionid"

    def test_falls_back_to_legacy_netscape(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uploader, "get_account", lambda i: None)
        f = tmp_path / "c.txt"
        f.write_text(".tiktok.com\tTRUE\t/\tTRUE\t99\tsessionid\tval\n",
                     encoding="utf-8")
        cookies = uploader._resolve_cookies(account_id=None,
                                            cookie_file=str(f))
        assert cookies and cookies[0]["name"] == "sessionid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_uploader_phase1.py -q`
Expected: FAIL — `AttributeError: module 'src.uploader' has no attribute '_find'`

- [ ] **Step 3: Write minimal implementation**

Add near the top of `src/uploader.py` (after existing imports):

```python
import time as _time
from src.tiktok.account import get_account
from src.tiktok.cookies import to_selenium_cookies


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
```

> **Note for implementer:** `parse_cookies_file` returns dicts shaped
> `{name,value,domain,path,expiry}` (no `secure`/`httpOnly`). That is
> already accepted by Selenium `add_cookie`, so `_resolve_cookies` may
> return it as-is for the legacy path.

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_uploader_phase1.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Run full suite (no regression)**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS (all prior tests + new ones)

- [ ] **Step 6: Commit**

```bash
git add src/uploader.py tests/test_uploader_phase1.py
git commit -m "feat(uploader): resilient _find selectors + unified cookie source"
```

---

## Task 9: Refactor `_post_video` to use `_find` + debug dump

**Files:**
- Modify: `src/uploader.py`

This task rewrites the element lookups inside the existing
`_upload_single_video` to go through `_find` with fallback locators and to
call `_save_debug` on failure. Behavior (scheduled-post flow) is unchanged;
only robustness improves. No new unit test (browser-bound) — covered by
Task 10 manual verification.

- [ ] **Step 1: Add the SELECTORS fallback table**

Add to `src/uploader.py` near the existing `SELECTORS` dict (keep the old
one; add a new fallback map used by `_find`):

```python
from selenium.webdriver.common.by import By

SELECTORS_FB = {
    "file_input": [(By.XPATH, '//input[@type="file"]')],
    "replace_button": [
        (By.XPATH, "//button[div[text()='Replace']]"),
        (By.XPATH, "//button[contains(.,'Replace')]"),
    ],
    "caption_editor": [
        (By.CSS_SELECTOR, "div.public-DraftEditor-content"),
        (By.CSS_SELECTOR, '[data-e2e="caption-editor"] [contenteditable="true"]'),
        (By.CSS_SELECTOR, 'div[contenteditable="true"]'),
    ],
    "schedule_radio": [
        (By.XPATH, "//*[text()='Schedule']"),
        (By.XPATH, "//*[contains(text(),'Schedule')]"),
    ],
    "post_button": [
        (By.XPATH, "//button[@data-e2e='post-button' and not(@disabled)]"),
        (By.XPATH, "//button[.//div[text()='Post'] and not(@disabled)]"),
    ],
    "manage_posts": [
        (By.XPATH, "//*[text()='Manage your posts']"),
        (By.XPATH, "//*[contains(text(),'Manage your posts')]"),
    ],
}
```

- [ ] **Step 2: Replace `wait.until(... presence/clickable ...)` lookups in `_upload_single_video`**

For each of `file_input`, `replace_button`, `caption_editor`,
`schedule_radio`, `post_button`, `manage_posts`, replace the existing
`wait.until(EC...( (By.X, SELECTORS[...]) ))` call with:

```python
element = _find(driver, SELECTORS_FB["<key>"], timeout=<existing timeout>)
```

Keep the existing date/time-picker interaction code as-is (it is
position-based, not a single selector). Wrap the whole `try` body so that the
existing `except TimeoutException` / `except Exception` blocks also call
`_save_debug(driver, f"post_fail_{schedule_time.strftime('%H%M')}")` (replace
the current `_save_debug_screenshot` call).

- [ ] **Step 3: Add the `upload_clip` thin wrapper**

Append:

```python
def upload_clip(driver, clip_path, description, schedule_time,
                visibility: str = "public", log_fn=None) -> tuple[bool, str]:
    """Post a single clip with a ready (cookie-injected) driver.
    Phase 1 supports scheduled public posts only."""
    if visibility != "public":
        return (False, f"visibility '{visibility}' not supported in Phase 1")
    ok = _upload_single_video(driver, clip_path, description,
                              schedule_time, log_fn)
    return (ok, "" if ok else "upload failed (see debug/)")
```

- [ ] **Step 4: Run full suite (no regression)**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS (unchanged count; this task is browser-bound logic)

- [ ] **Step 5: Commit**

```bash
git add src/uploader.py
git commit -m "refactor(uploader): resilient selectors + debug dump in post flow"
```

---

## Task 10: Wire Account card UI + workers, then REAL verification

**Files:**
- Modify: `src/ui/upload_tab.py`
- Modify: `src/workers.py`

- [ ] **Step 1: Replace the cookie row with an Account card**

In `src/ui/upload_tab.py`, replace the "TikTok cookies" row (the
`ctk.CTkLabel(... "TikTok cookies:")` block, its Browse and Verify buttons,
and the `on_cookie_selected` trace) with:

```python
# --- Account card ---
acct_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
acct_card.pack(fill="x", padx=SP_12, pady=SP_4)
self.acct_user = ctk.CTkLabel(acct_card, text="No account loaded",
                              font=("", FONT_LABEL, "bold"))
self.acct_user.pack(anchor="w", padx=SP_12, pady=(SP_8, 0))
self.acct_health = ctk.CTkLabel(acct_card, text="", text_color=TEXT_MUTED)
self.acct_health.pack(anchor="w", padx=SP_12, pady=(0, SP_4))
btnrow = ctk.CTkFrame(acct_card, fg_color="transparent")
btnrow.pack(fill="x", padx=SP_12, pady=(0, SP_8))
ctk.CTkButton(btnrow, text="Paste cookies JSON", width=150,
              command=self._paste_cookies).pack(side="left", padx=(0, SP_4))
ctk.CTkButton(btnrow, text="Load .json", width=90,
              command=self._load_cookies_file).pack(side="left", padx=SP_4)
ctk.CTkButton(btnrow, text="Re-verify", width=90,
              command=self._reverify).pack(side="left", padx=SP_4)
self._render_account_card()
```

- [ ] **Step 2: Add the card methods**

Add to `UploadTab` (full code):

```python
def _render_account_card(self):
    from src.tiktok.account import get_account
    a = get_account("main")
    if not a:
        self.acct_user.configure(text="No account loaded")
        self.acct_health.configure(text="Paste or load your TikTok cookies.",
                                   text_color=TEXT_MUTED)
        return
    self.acct_user.configure(
        text=f"@{a.username}" if a.username else "Loaded (not verified)")
    h = a.health()
    color = {"valid": SUCCESS, "expiring": WARNING, "expired": ERROR,
             "session-only": TEXT_MUTED, "missing": ERROR}.get(
                 h["status"], TEXT_MUTED)
    self.acct_health.configure(text=h["detail"], text_color=color)

def _store_cookies(self, source: str):
    from src.tiktok.cookies import parse_cookie_json
    from src.tiktok.account import Account, save_account
    from tkinter import messagebox
    try:
        cookies = parse_cookie_json(source)
    except ValueError as e:
        messagebox.showerror("Invalid cookies", str(e))
        return
    save_account(Account(id="main", label="Main", cookies=cookies))
    self._render_account_card()
    self._reverify()

def _paste_cookies(self):
    dlg = ctk.CTkToplevel(self.acct_user.winfo_toplevel())
    dlg.title("Paste cookies JSON")
    dlg.geometry("520x360")
    box = ctk.CTkTextbox(dlg)
    box.pack(fill="both", expand=True, padx=SP_12, pady=SP_12)
    def _load():
        txt = box.get("1.0", "end").strip()
        dlg.destroy()
        if txt:
            self._store_cookies(txt)
    ctk.CTkButton(dlg, text="Load", command=_load).pack(pady=(0, SP_12))

def _load_cookies_file(self):
    from tkinter import filedialog
    p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
    if p:
        self._store_cookies(p)

def _reverify(self):
    import threading
    from src.tiktok.account import get_account, verify
    a = get_account("main")
    if not a:
        return
    self.acct_health.configure(text="Verifying…", text_color=TEXT_MUTED)
    def _run():
        verify(a, headless=self.state.headless.get())
        self.acct_user.winfo_toplevel().after(0, self._render_account_card)
    threading.Thread(target=_run, daemon=True).start()
```

- [ ] **Step 3: Rewire `_on_upload` and `workers.uploader_worker` to account id**

In `upload_tab._on_upload`: replace the cookie validity check and the
`self.state.tk_cookie.get()` argument with account id `"main"`; if
`get_account("main")` is None or `health()["status"] in {"expired","missing"}`,
`messagebox.showerror` and return.

In `workers.uploader_worker` and `uploader.upload_clips`: replace the
`cookie_file` parameter usage with `account_id`, calling
`_resolve_cookies(account_id, cookie_file=None)` and passing the result to the
existing `_add_cookies(driver, cookies, log_fn)` path. Keep the parameter name
`cookie_file` accepted but unused-except-fallback for back-compat.

- [ ] **Step 4: Smoke-test imports + full suite**

Run: `./venv/Scripts/python.exe -c "import ast; [ast.parse(open(f,encoding='utf-8').read()) for f in ['src/ui/upload_tab.py','src/workers.py','src/uploader.py']]; print('syntax ok')"`
Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: `syntax ok`; all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/ui/upload_tab.py src/workers.py src/uploader.py
git commit -m "feat(ui): TikTok Account card; wire upload to account store"
```

- [ ] **Step 6: REAL verification (mandatory, recorded — not pytest)**

1. Persist the user's pasted Cookie-Editor JSON to
   `~/.yt2tiktok/accounts/main.json` via a one-off script that calls
   `parse_cookie_json` + `save_account(Account(id="main",...))`.
2. Run a script: `verify(get_account("main"), headless=False)` — confirm it
   prints the resolved `@username`. (Headful first run is more robust against
   TikTok bot checks; uc persists the profile for later headless runs.)
3. Generate (or reuse) one Wall Hacks clip.
4. Call `upload_clip(driver, clip, "<caption>", schedule_time=now+30min,
   visibility="public")` with a cookie-injected driver from
   `make_driver(headless=False, account_id="main")`.
5. Observe the on-screen "Manage your posts" / scheduled confirmation; capture
   a screenshot to `debug/`.
6. **Only if** the scheduled post is confirmed: report success with the
   screenshot. If it fails, inspect the `debug/<ts>_*.png/.html`, fix the
   affected `SELECTORS_FB` entry, and repeat (this is the expected
   selector-tuning loop and is why the debug dump exists).
7. Delete the one-off scripts; keep `~/.yt2tiktok/accounts/main.json`.

- [ ] **Step 7: Commit any selector fixes from Step 6**

```bash
git add src/uploader.py
git commit -m "fix(uploader): selector tuning from live TikTok verification"
```

---

## Task 11: Final regression + branch wrap-up

- [ ] **Step 1: Full suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all PASS (prior 67 + new cookies/account/driver/uploader tests)

- [ ] **Step 2: Update project memory**

Append to `MEMORY.md` index a pointer to a new memory noting Phase 1 done,
account store location (`~/.yt2tiktok/accounts/`), and that Phases 2–5
(multi-account UI, scheduler, auto-update, packaging) remain.

- [ ] **Step 3: Final commit + PR offer**

```bash
git add -A
git commit -m "chore: Phase 1 TikTok upload complete"
```

Then surface to the user: branch `feature/tiktok-upload-phase1` ready;
ask whether to open a PR (do not auto-merge — per repo agentic PR policy).

---

## Notes / Skill References

- Use @superpowers:test-driven-development for every code task (red→green→commit).
- Use @superpowers:verification-before-completion before claiming Task 10 success — the live scheduled post must be confirmed on-screen with a screenshot; no asserting success without it.
- DRY: one cookie-resolution path (`_resolve_cookies`), one selector lookup (`_find`).
- YAGNI: no multi-account UI, no scheduler, no auto-update, no packaging in this plan — those are Phases 2–5 with their own specs.
