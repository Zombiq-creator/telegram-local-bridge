"""approval.py — single-use tokens + pending approval store.

Approval flow:
  1. write_command generates a token via approval_token()
  2. save_pending_approval() stores {chat_id, command, path, content} with TTL
  3. user confirms in Telegram (Inline Keyboard button or text reply)
  4. consume_pending_approval() atomically reads + deletes the entry

If the entry expires (TTL exceeded), consume returns None — write is denied.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .safe_io import write_text_safe


def approval_token(
    path: str,
    content: str,
    ts: float | None = None,
) -> str:
    """Generate a short approval token from path + content + timestamp.

    16 hex chars = 64 bits of SHA-256. Collision-safe enough for a single
    bot's pending approvals within a 10-minute TTL window.

    Same path + content + ts produces the same token (so the Inline Keyboard
    callback can verify the user saw the same preview they approved).
    """
    ts = ts or time.time()
    payload = f"{path}|{content}|{ts}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def save_pending_approval(
    store_path: Path,
    token: str,
    *,
    chat_id: str,
    command: str,
    path: str,
    content_preview: str,
    content_full: str | None = None,
    ttl_sec: int = 600,
) -> None:
    """Save a pending approval for later /approve_once or Inline Keyboard.

    ttl_sec: default 10 minutes.
    content_full: full content for write commands; if None, content_preview
    is used (for /session-style approvals that don't write a file).
    """
    pending = _load_pending(store_path)
    pending[token] = {
        "chat_id": chat_id,
        "command": command,
        "path": path,
        "content_preview": content_preview[:500],
        "content_full": content_full if content_full is not None else content_preview,
        "created_at": time.time(),
        "expires_at": time.time() + ttl_sec,
    }
    _save_pending(store_path, pending)


def load_pending_approval(store_path: Path, token: str) -> dict[str, Any] | None:
    """Load a pending approval by token. Returns None if missing or expired."""
    pending = _load_pending(store_path)
    entry = pending.get(token)
    if not entry:
        return None
    if time.time() > entry.get("expires_at", 0):
        del pending[token]
        _save_pending(store_path, pending)
        return None
    return entry


def consume_pending_approval(store_path: Path, token: str) -> dict[str, Any] | None:
    """Atomically load AND delete a pending approval."""
    pending = _load_pending(store_path)
    entry = pending.pop(token, None)
    if entry and time.time() <= entry.get("expires_at", 0):
        _save_pending(store_path, pending)
        return entry
    _save_pending(store_path, pending)
    return None


def _load_pending(store_path: Path) -> dict[str, Any]:
    if not store_path.exists():
        return {}
    try:
        return json.loads(store_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_pending(store_path: Path, pending: dict[str, Any]) -> None:
    write_text_safe(store_path, json.dumps(pending, ensure_ascii=False, indent=2))