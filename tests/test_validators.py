import pytest
from src.validators import (
    validate_youtube_url,
    validate_file_path,
    validate_cookie_file,
    validate_time_format,
    validate_interval,
)


class TestValidateYoutubeUrl:
    def test_valid_watch_url(self):
        assert validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")[0] is True

    def test_valid_short_url(self):
        assert validate_youtube_url("https://youtu.be/dQw4w9WgXcQ")[0] is True

    def test_valid_shorts_url(self):
        assert validate_youtube_url("https://www.youtube.com/shorts/abc123")[0] is True

    def test_invalid_url(self):
        ok, msg = validate_youtube_url("https://example.com")
        assert ok is False
        assert "Invalid" in msg

    def test_empty_url(self):
        assert validate_youtube_url("")[0] is False

    def test_url_with_params(self):
        assert validate_youtube_url("https://www.youtube.com/watch?v=abc123&t=60")[0] is True

    def test_mobile_url(self):
        assert validate_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ")[0] is True

    def test_music_url(self):
        assert validate_youtube_url("https://music.youtube.com/watch?v=dQw4w9WgXcQ")[0] is True

    def test_live_url(self):
        assert validate_youtube_url("https://www.youtube.com/live/dQw4w9WgXcQ")[0] is True

    def test_embed_url(self):
        assert validate_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ")[0] is True

    def test_params_before_v(self):
        assert validate_youtube_url("https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ")[0] is True

    def test_none_url(self):
        assert validate_youtube_url(None)[0] is False


class TestValidateIntervalExtra:
    def test_inf_rejected(self):
        assert validate_interval("inf")[0] is False

    def test_nan_rejected(self):
        assert validate_interval("nan")[0] is False

    def test_huge_rejected(self):
        assert validate_interval("1e9")[0] is False


class TestValidateTimeFormat:
    def test_valid_time(self):
        assert validate_time_format("10:00")[0] is True

    def test_valid_single_digit_hour(self):
        assert validate_time_format("9:30")[0] is True

    def test_invalid_hour(self):
        assert validate_time_format("25:00")[0] is False

    def test_invalid_minute(self):
        assert validate_time_format("10:60")[0] is False

    def test_invalid_format(self):
        assert validate_time_format("abc")[0] is False

    def test_empty(self):
        assert validate_time_format("")[0] is False


class TestValidateInterval:
    def test_valid_int(self):
        assert validate_interval("2")[0] is True

    def test_valid_float(self):
        assert validate_interval("1.5")[0] is True

    def test_zero(self):
        assert validate_interval("0")[0] is False

    def test_negative(self):
        assert validate_interval("-1")[0] is False

    def test_non_numeric(self):
        assert validate_interval("abc")[0] is False
