"""lockfile.py — PID-based process lockfile.

Used by the watchdog to detect whether the bot (and any spawned daemon)
are still alive without resorting to heuristics like "is any pythonw.exe
running".

Lockfile format (JSON):
  {
    "terminal_pid": 12345,
    "daemon_pid": 12346,
    "started_at": "2026-09-24T12:00:00Z",
    "version": "0.1.0"
  }
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class LockfileData:
    """Contents of the lockfile."""

    terminal_pid: int
    daemon_pid: int | None = None
    started_at: str | None = None
    version: str | None = None


def write_lockfile(path: Path, data: LockfileData) -> None:
    """Atomically write a lockfile with current PIDs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(asdict(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def read_lockfile(path: Path) -> LockfileData | None:
    """Read a lockfile. Returns None if missing, invalid, or stale format."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if "terminal_pid" not in raw:
            return None
        return LockfileData(
            terminal_pid=int(raw["terminal_pid"]),
            daemon_pid=int(raw["daemon_pid"]) if raw.get("daemon_pid") is not None else None,
            started_at=raw.get("started_at"),
            version=raw.get("version"),
        )
    except (ValueError, OSError, json.JSONDecodeError):
        return None


def pid_alive(pid: int | None) -> bool:
    """True if `pid` is a running process on this host.

    Cross-platform: uses os.kill(pid, 0) which works on Unix and Windows
    (returns without error if PID exists with access, raises PermissionError
    if no access, ProcessLookupError if not found).
    """
    if not pid:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but we don't own it — count as alive.
        return True
    except OSError:
        return False
    return True


def is_alive_and_mine(pid: int | None, my_pid: int) -> bool:
    """True if pid is alive AND not our own process (avoids self-detection).

    Useful for watchers that should not detect themselves as their target.
    """
    if not pid or pid == my_pid:
        return False
    return pid_alive(pid)