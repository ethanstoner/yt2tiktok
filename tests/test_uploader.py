from src.uploader import _safe_caption, parse_cookies_file
from src.validators import validate_cookie_file


class TestSafeCaption:
    def test_basic(self):
        assert _safe_caption("{title} - Part {part}", "Vid", 2, 5) == "Vid - Part 2"

    def test_total_placeholder(self):
        assert _safe_caption("{part}/{total}", "Vid", 2, 5) == "2/5"

    def test_unknown_placeholder_kept_literally(self):
        # Must not raise KeyError; unknown placeholder left as-is.
        out = _safe_caption("My {episode} clip", "Vid", 1, 3)
        assert out == "My {episode} clip"

    def test_unbalanced_braces_fall_back(self):
        out = _safe_caption("Broken { template", "Vid", 1, 3)
        assert out == "Vid - Part 1"


def _write_cookie(path, line):
    path.write_text(line + "\n", encoding="utf-8")
    return str(path)


class TestHttpOnlyCookies:
    LINE = "#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tabc123"

    def test_parse_httponly_cookie(self, tmp_path):
        p = _write_cookie(tmp_path / "c.txt", self.LINE)
        cookies = parse_cookies_file(p)
        assert cookies and cookies[0]["name"] == "sessionid"

    def test_validate_httponly_cookie(self, tmp_path):
        p = _write_cookie(tmp_path / "c.txt", self.LINE)
        ok, _ = validate_cookie_file(p)
        assert ok is True

    def test_real_comment_still_skipped(self, tmp_path):
        p = _write_cookie(tmp_path / "c.txt", "# Netscape HTTP Cookie File")
        ok, _ = validate_cookie_file(p)
        assert ok is False
