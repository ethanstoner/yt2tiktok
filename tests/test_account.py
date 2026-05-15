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
