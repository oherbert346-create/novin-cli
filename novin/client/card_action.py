"""Public ingest action as shown on the CLI card. No extra deps."""
from __future__ import annotations

from typing import Any


def public_card_action(response: dict[str, Any] | None, fallback: str = "") -> str:
    """ALERT if this would outgest, otherwise SUPPRESS. No public review."""
    resp = response or {}
    notify = resp.get("notify")
    action = str(resp.get("action") or fallback or "").lower()
    if notify is True or action == "alert":
        return "ALERT"
    return "SUPPRESS"
