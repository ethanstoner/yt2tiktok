import json
import os
from datetime import datetime, timezone

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
