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
