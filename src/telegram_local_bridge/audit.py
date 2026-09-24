"""audit.py — append-only audit log with daily rotation and retention.

Rule 10 (encoding-strategy.md): every read/write/denied action should be logged
with timestamp, chat_id, command, result, and optional path/error.

Original log path: data/state/telegram_audit.jsonl (legacy) +
data/state/telegram_audit-YYYY-MM-DD.jsonl (rotated).

In this library, the directory and filename prefix are configurable.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .safe_io import write_text_safe


@dataclass
class AuditConfig:
    """Audit log configuration."""

    log_dir: Path
    filename_prefix: str = "telegram_audit"
    retention_days: int = 30       # 0 = keep forever
    max_size_mb: int = 50          # 0 = no intra-day rotation
    legacy_filename: str = "telegram_audit.jsonl"  # for back-compat reads

    def __post_init__(self) -> None:
        self.log_dir = Path(self.log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def audit_log(
    cfg: AuditConfig,
    *,
    chat_id: str,
    command: str,
    result: str,                   # 'ok' | 'denied' | 'error'
    path: str | None = None,
    detected_encoding: str | None = None,
    bytes_size: int | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append an audit entry (jsonl). Daily rotation by UTC date.

    Best-effort: failures print to stderr but never crash the caller.
    """
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "chat_id": chat_id,
        "command": command,
        "result": result,
    }
    if path is not None:
        entry["path"] = path
    if detected_encoding is not None:
        entry["detected_encoding"] = detected_encoding
    if bytes_size is not None:
        entry["bytes"] = bytes_size
    if error is not None:
        entry["error"] = error
    if extra:
        entry.update(extra)

    log_path = _audit_log_path_for_now(cfg)
    _maybe_rotate_intraday(cfg, log_path)

    try:
        line = json.dumps(entry, ensure_ascii=False)
        with log_path.open("a", encoding="utf-8", newline="") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[telegram_local_bridge.audit] audit_log FAILED: {e}", file=sys.stderr)


def _audit_log_path_for_now(cfg: AuditConfig) -> Path:
    """Path for the current UTC day: {prefix}-YYYY-MM-DD.jsonl."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return cfg.log_dir / f"{cfg.filename_prefix}-{today}.jsonl"


def _maybe_rotate_intraday(cfg: AuditConfig, path: Path) -> None:
    """If the day's log exceeds max_size_mb, rotate to .1, .2, ... suffix."""
    if cfg.max_size_mb <= 0:
        return
    try:
        if path.exists() and path.stat().st_size > cfg.max_size_mb * 1024 * 1024:
            stem = path.stem
            i = 1
            while True:
                rotated = path.with_name(f"{stem}.{i}{path.suffix}")
                if not rotated.exists():
                    path.rename(rotated)
                    break
                i += 1
    except Exception:
        pass


def cleanup_old_audit_logs(cfg: AuditConfig) -> int:
    """Delete rotated audit logs older than retention_days. Returns count.

    Safe to call periodically (e.g. on bot startup).
    """
    if cfg.retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.retention_days)
    deleted = 0
    try:
        for f in cfg.log_dir.glob(f"{cfg.filename_prefix}-*.jsonl*"):
            try:
                parts = f.stem.split("-")
                if len(parts) < 4:
                    continue
                date_str = f"{parts[1]}-{parts[2]}-{parts[3]}"
                file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if file_date < cutoff:
                    f.unlink()
                    deleted += 1
            except (ValueError, OSError):
                continue
    except Exception:
        pass
    return deleted