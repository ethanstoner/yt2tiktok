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
