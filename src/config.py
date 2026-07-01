import json
import os
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
    "keep_source_video": False,
    "moments_count": 5,
    "moments_min_dur": 20,
    "moments_max_dur": 90,
    "onboarding_completed": False,
}


def _ensure_dir():
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, text: str):
    """Write to a temp file then replace, so a crash mid-write can't corrupt the config."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _migrate_old_config():
    if _OLD_CONFIG_PATH.exists() and not _CONFIG_PATH.exists():
        _ensure_dir()
        try:
            data = json.loads(_OLD_CONFIG_PATH.read_text(encoding="utf-8"))
            _atomic_write(_CONFIG_PATH, json.dumps(data, indent=2))
            _OLD_CONFIG_PATH.unlink()
        except Exception:
            pass


_migrate_old_config()


def load_config() -> dict:
    with _lock:
        try:
            if _CONFIG_PATH.exists():
                data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
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
                try:
                    existing = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
                    if not isinstance(existing, dict):
                        existing = {}
                except Exception:
                    # Corrupt existing file: start from defaults rather than
                    # silently refusing every future write.
                    existing = {}
            existing.update(data)
            _atomic_write(_CONFIG_PATH, json.dumps(existing, indent=2))
        except Exception:
            pass


_UNSET = object()


def get(key: str, default=_UNSET):
    config = load_config()
    if default is not _UNSET:
        return config.get(key, default)
    return config.get(key, DEFAULTS.get(key))


def set(key: str, value):
    save_config({key: value})


def reset_to_defaults():
    with _lock:
        _ensure_dir()
        try:
            _atomic_write(_CONFIG_PATH, json.dumps(DEFAULTS, indent=2))
        except Exception:
            pass


def export_config(path: str):
    config = load_config()
    Path(path).write_text(json.dumps(config, indent=2), encoding="utf-8")


def import_config(path: str):
    """Import a config file, fully replacing current settings.

    Raises ValueError on a missing/unreadable/malformed file so the caller
    can show a clean message instead of a raw traceback.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not read config file: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a JSON object.")
    # Full replace (merged onto defaults) rather than merging onto the
    # current file, so stale keys don't survive an import.
    merged = {**DEFAULTS, **data}
    with _lock:
        _ensure_dir()
        _atomic_write(_CONFIG_PATH, json.dumps(merged, indent=2))


def get_config_dir() -> Path:
    _ensure_dir()
    return _CONFIG_DIR
