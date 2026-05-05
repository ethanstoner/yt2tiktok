import json
import os
import threading
from pathlib import Path

_CONFIG_PATH = Path.home() / ".yt2tiktok.json"
_lock = threading.Lock()


def load_config() -> dict:
    with _lock:
        try:
            if _CONFIG_PATH.exists():
                return json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass
        return {}


def save_config(data: dict):
    with _lock:
        try:
            existing = {}
            if _CONFIG_PATH.exists():
                existing = json.loads(_CONFIG_PATH.read_text())
            existing.update(data)
            _CONFIG_PATH.write_text(json.dumps(existing, indent=2))
        except Exception:
            pass


def get(key: str, default=None):
    return load_config().get(key, default)


def set(key: str, value):
    save_config({key: value})
