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
