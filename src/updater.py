import threading
import requests
from src.constants import APP_VERSION, GITHUB_REPO_URL


def _parse_version(v: str) -> tuple:
    return tuple(int(x) for x in v.strip("v").split("."))


def check_for_update(callback):
    """Check GitHub releases API for newer version. Calls callback(latest_version, url) if update available, or callback(None, None) if not."""
    def _check():
        try:
            api_url = GITHUB_REPO_URL.replace("github.com", "api.github.com/repos") + "/releases/latest"
            r = requests.get(api_url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                latest = data.get("tag_name", "")
                if latest and _parse_version(latest) > _parse_version(APP_VERSION):
                    callback(latest, data.get("html_url", ""))
                    return
        except Exception:
            pass
        callback(None, None)
    threading.Thread(target=_check, daemon=True).start()
