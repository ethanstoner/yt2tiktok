import re
import os
import math


def validate_youtube_url(url: str) -> tuple[bool, str]:
    """Check that url is a valid youtube.com or youtu.be URL."""
    if not url or not isinstance(url, str):
        return (False, "URL must be a non-empty string.")
    pattern = re.compile(
        r'^https?://'
        r'(?:'
        r'(?:(?:www\.|m\.|music\.)?youtube\.com|(?:www\.)?youtube-nocookie\.com)'
        r'/(?:watch\?(?:[^\s]*&)?v=[\w-]{3,}'
        r'|shorts/[\w-]{3,}'
        r'|live/[\w-]{3,}'
        r'|embed/[\w-]{3,})'
        r'|youtu\.be/[\w-]{3,}'
        r')'
        r'(?:[?&#].*)?$',
        re.IGNORECASE,
    )
    if pattern.match(url.strip()):
        return (True, "")
    return (False, f"Invalid YouTube URL: '{url}'. Must be a youtube.com or youtu.be link.")


def validate_file_path(path: str, extensions: list[str] = None) -> tuple[bool, str]:
    """Check that path exists on disk and optionally has one of the allowed extensions."""
    if not path or not isinstance(path, str):
        return (False, "File path must be a non-empty string.")
    if not os.path.exists(path):
        return (False, f"Path does not exist: '{path}'.")
    if extensions:
        _, ext = os.path.splitext(path)
        normalized_ext = ext.lower()
        normalized_allowed = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions]
        if normalized_ext not in normalized_allowed:
            return (False, f"File '{path}' has extension '{ext}'; expected one of {extensions}.")
    return (True, "")


def validate_cookie_file(path: str) -> tuple[bool, str]:
    """Check that path exists and contains at least one valid Netscape cookie line (7 tab-separated fields)."""
    if not path or not isinstance(path, str):
        return (False, "Cookie file path must be a non-empty string.")
    if not os.path.exists(path):
        return (False, f"Cookie file does not exist: '{path}'.")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    # "#HttpOnly_" is a real cookie line, not a comment.
                    if stripped.startswith("#HttpOnly_"):
                        stripped = stripped[len("#HttpOnly_"):]
                    else:
                        continue
                fields = stripped.split("\t")
                if len(fields) == 7:
                    return (True, "")
    except OSError as exc:
        return (False, f"Could not read cookie file '{path}': {exc}.")
    return (False, f"Cookie file '{path}' contains no valid cookie lines (expected tab-separated rows with 7 fields).")


def validate_time_format(time_str: str) -> tuple[bool, str]:
    """Check that time_str matches HH:MM with valid hours (0-23) and minutes (0-59)."""
    if not time_str or not isinstance(time_str, str):
        return (False, "Time must be a non-empty string.")
    pattern = re.compile(r'^(\d{1,2}):(\d{2})$')
    match = pattern.match(time_str.strip())
    if not match:
        return (False, f"Invalid time format '{time_str}'. Expected HH:MM.")
    hours, minutes = int(match.group(1)), int(match.group(2))
    if not (0 <= hours <= 23):
        return (False, f"Invalid hours '{hours}' in '{time_str}'. Must be between 0 and 23.")
    if not (0 <= minutes <= 59):
        return (False, f"Invalid minutes '{minutes}' in '{time_str}'. Must be between 0 and 59.")
    return (True, "")


def validate_interval(val: str) -> tuple[bool, str]:
    """Check that val represents a positive number."""
    if not val or not isinstance(val, str):
        return (False, "Interval must be a non-empty string.")
    try:
        numeric = float(val.strip())
    except ValueError:
        return (False, f"Interval '{val}' is not a valid number.")
    if not math.isfinite(numeric):
        return (False, f"Interval '{val}' must be a finite number.")
    if numeric <= 0:
        return (False, f"Interval '{val}' must be a positive number greater than zero.")
    if numeric > 168:
        return (False, f"Interval '{val}' is too large (max 168 hours / 1 week).")
    return (True, "")
