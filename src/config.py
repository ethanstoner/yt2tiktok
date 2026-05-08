import json
import os
import shutil
import threading
from pathlib import Path

_CONFIG_DIR = Path.home() / ".yt2tiktok"
_CONFIG_PATH = _CONFIG_DIR / "config.json"
_OLD_CONFIG_PATH = Path.home() / ".yt2tiktok.json"
_lock = threading.Lock()

DEFAULTS = {
    "llm_enabled": False,
    "llm_provider": "groq",
    "llm_api_key": "",
    "llm_model": "",
    "llm_base_url": "",
    "mode": "Blurred",
    "cut_mode": "Natural Pause",
    "preset": "Opus Clean",
    "caption_y": 0.73,
    "captions_enabled": True,
    "output_dir": "",
    "caption_template": "{title} - Part {part}",
    "start_time": "10:00",
    "interval": "2",
    "headless": True,
    "window_geometry": "750x900",
    "last_cookie_path": "",
    "onboarding_completed": False,
}


def _ensure_dir():
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _migrate_old_config():
    if _OLD_CONFIG_PATH.exists() and not _CONFIG_PATH.exists():
        _ensure_dir()
        try:
            data = json.loads(_OLD_CONFIG_PATH.read_text())
            _CONFIG_PATH.write_text(json.dumps(data, indent=2))
            _OLD_CONFIG_PATH.unlink()
        except Exception:
            pass


_migrate_old_config()


def load_config() -> dict:
    with _lock:
        try:
            if _CONFIG_PATH.exists():
                data = json.loads(_CONFIG_PATH.read_text())
                merged = {**DEFAULTS, **data}
                return merged
        except Exception:
            pass
        return dict(DEFAULTS)


def save_config(data: dict):
    with _lock:
        _ensure_dir()
        try:
            existing = {}
            if _CONFIG_PATH.exists():
                existing = json.loads(_CONFIG_PATH.read_text())
            existing.update(data)
            _CONFIG_PATH.write_text(json.dumps(existing, indent=2))
        except Exception:
            pass


def get(key: str, default=None):
    config = load_config()
    if default is not None:
        return config.get(key, default)
    return config.get(key, DEFAULTS.get(key))


def set(key: str, value):
    save_config({key: value})


def reset_to_defaults():
    with _lock:
        _ensure_dir()
        try:
            _CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=2))
        except Exception:
            pass


def export_config(path: str):
    config = load_config()
    Path(path).write_text(json.dumps(config, indent=2))


def import_config(path: str):
    data = json.loads(Path(path).read_text())
    save_config(data)


def get_config_dir() -> Path:
    _ensure_dir()
    return _CONFIG_DIR
