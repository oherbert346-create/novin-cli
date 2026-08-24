"""Local CLI login: master key first time, brand API key after that."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

NOVIN_DIR = Path.home() / ".novin"

AccountKind = Literal["master", "brand"]


def session_path() -> Path:
    return NOVIN_DIR / "session.json"


def config_path() -> Path:
    return NOVIN_DIR / "config.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    NOVIN_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_config() -> dict[str, Any]:
    return _read_json(config_path())


def save_config(cfg: dict[str, Any]) -> None:
    _write_json(config_path(), cfg)


def load_session() -> dict[str, Any] | None:
    data = _read_json(session_path())
    if not data.get("api_key"):
        return None
    return data


def save_session(
    *,
    api_url: str,
    api_key: str,
    brand_id: str,
    kind: AccountKind,
    brand_name: str | None = None,
) -> dict[str, Any]:
    session = {
        "api_url": api_url,
        "api_key": api_key,
        "brand_id": brand_id,
        "kind": kind,
        "logged_in": True,
    }
    if brand_name:
        session["brand_name"] = brand_name
    _write_json(session_path(), session)
    cfg = load_config()
    account = dict(cfg.get("account") or {})
    account["brand_id"] = brand_id
    account["kind"] = kind
    if brand_name:
        account["brand_name"] = brand_name
    cfg["account"] = account
    save_config(cfg)
    return session


def clear_session() -> None:
    """Sign out as a fresh machine: drop session, brand account, and local sites."""
    try:
        path = session_path()
        if path.exists():
            path.unlink()
    except OSError:
        pass
    save_config({"sites": {}, "active_site_id": ""})


def has_brand_account() -> bool:
    """True once this machine has set up (or previously used) a CLI brand."""
    cfg = load_config()
    account = cfg.get("account") or {}
    if account.get("brand_id"):
        return True
    if cfg.get("sites") or cfg.get("active_site_id"):
        return True
    return False


def clear_local_sites() -> None:
    cfg = load_config()
    cfg["sites"] = {}
    cfg["active_site_id"] = ""
    save_config(cfg)


def saved_brand_id() -> str:
    account = load_config().get("account") or {}
    return str(account.get("brand_id") or "default")


def default_api_url() -> str:
    return os.environ.get("NOVIN_API_URL") or "https://novin-api.fly.dev"
