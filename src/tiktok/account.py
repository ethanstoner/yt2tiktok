import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from src.tiktok.cookies import cookie_health

_ACCOUNTS_DIR = Path.home() / ".yt2tiktok" / "accounts"


@dataclass
class Account:
    id: str
    label: str
    cookies: list = field(default_factory=list)
    username: str | None = None
    last_verified: str | None = None

    def health(self) -> dict:
        return cookie_health(self.cookies)


def _ensure_dir():
    _ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)


def save_account(account: Account):
    _ensure_dir()
    path = _ACCOUNTS_DIR / f"{account.id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(account), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_accounts() -> list[Account]:
    if not _ACCOUNTS_DIR.exists():
        return []
    out = []
    for p in sorted(_ACCOUNTS_DIR.glob("*.json")):
        try:
            out.append(Account(**json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return out


def get_account(account_id: str) -> Account | None:
    for a in load_accounts():
        if a.id == account_id:
            return a
    return None
