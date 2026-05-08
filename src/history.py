import json
from datetime import datetime
from pathlib import Path
from src.config import get_config_dir

_HISTORY_PATH = get_config_dir() / "history.json"
MAX_HISTORY = 20


def _load() -> list[dict]:
    try:
        if _HISTORY_PATH.exists():
            return json.loads(_HISTORY_PATH.read_text())
    except Exception:
        pass
    return []


def _save(entries: list[dict]):
    try:
        _HISTORY_PATH.write_text(json.dumps(entries, indent=2))
    except Exception:
        pass


def add_entry(title: str, url: str, clip_count: int, output_dir: str):
    entries = _load()
    entry = {
        "title": title,
        "url": url,
        "date": datetime.now().isoformat(),
        "clip_count": clip_count,
        "output_dir": output_dir,
    }
    # Remove duplicate URLs
    entries = [e for e in entries if e.get("url") != url]
    entries.insert(0, entry)
    entries = entries[:MAX_HISTORY]
    _save(entries)


def get_entries() -> list[dict]:
    return _load()


def clear():
    _save([])
