"""watchdog.py — file-change + process-liveness monitoring.

The watchdog's job is to detect when:
  1. the bot's source code changes (file hash differs from last seen) →
     restart to pick up patches
  2. the bot or its daemon dies (PID no longer alive) → restart

Detection uses lockfile-based PID tracking, not heuristics like "is any
pythonw.exe running" (which false-positives on the watchdog itself).

This module is platform-agnostic where possible. On Windows the helper
process spawn uses DETACHED_PROCESS + CREATE_NO_WINDOW flags from
subprocess; on Unix, start_new_session=True is used.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .lockfile import (
    LockfileData,
    pid_alive,
    read_lockfile,
    write_lockfile,
)


@dataclass
class WatchdogConfig:
    """All paths and process names the watchdog tracks."""

    project_root: Path
    terminal_script: Path             # bot entry-point (e.g. bot.py)
    daemon_script: Path | None = None  # optional daemon spawned by the bot
    python_executable: Path | None = None  # defaults to sys.executable
    lockfile_path: Path | None = None      # defaults to {project_root}/data/state/bot.lock
    state_path: Path | None = None         # defaults to {project_root}/data/state/bot_watchdog_state.json
    watchdog_log_path: Path | None = None
    process_names_to_kill: list[str] = field(default_factory=lambda: ["bot"])
    tick_interval_sec: int = 60

    def __post_init__(self) -> None:
        self.project_root = Path(self.project_root)
        self.terminal_script = Path(self.terminal_script)
        if self.daemon_script is not None:
            self.daemon_script = Path(self.daemon_script)
        if self.python_executable is None:
            self.python_executable = Path(sys.executable)
        else:
            self.python_executable = Path(self.python_executable)
        if self.lockfile_path is None:
            self.lockfile_path = self.project_root / "data" / "state" / "bot.lock"
        else:
            self.lockfile_path = Path(self.lockfile_path)
        if self.state_path is None:
            self.state_path = self.project_root / "data" / "state" / "bot_watchdog_state.json"
        else:
            self.state_path = Path(self.state_path)
        if self.watchdog_log_path is None:
            self.watchdog_log_path = self.project_root / "data" / "logs" / "bot_watchdog.log"
        else:
            self.watchdog_log_path = Path(self.watchdog_log_path)
        for p in (self.lockfile_path.parent, self.state_path.parent, self.watchdog_log_path.parent):
            p.mkdir(parents=True, exist_ok=True)


def file_hash(path: Path) -> str:
    """SHA-256 (first 16 hex chars) of file contents. Empty string if missing."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def load_state(state_path: Path) -> dict[str, Any]:
    """Load last known file hashes. Returns empty hashes if missing/corrupt."""
    if not state_path.exists():
        return {"daemon_hash": "", "terminal_hash": ""}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {"daemon_hash": "", "terminal_hash": ""}


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class Watchdog:
    """Detect code changes and dead processes; restart as needed."""

    def __init__(self, cfg: WatchdogConfig):
        self.cfg = cfg

    # ----- liveness -----

    def has_terminal(self) -> bool:
        """True if the bot's terminal process is alive per the lockfile."""
        lock = read_lockfile(self.cfg.lockfile_path)
        if not lock:
            return False
        return pid_alive(lock.terminal_pid)

    def has_daemon(self) -> bool:
        """True if the daemon process (if any) is alive per the lockfile."""
        lock = read_lockfile(self.cfg.lockfile_path)
        if not lock or lock.daemon_pid is None:
            return False
        return pid_alive(lock.daemon_pid)

    # ----- code-change detection -----

    def detect_code_changes(self, state: dict[str, Any]) -> tuple[bool, bool]:
        """Returns (terminal_changed, daemon_changed)."""
        cur_terminal = file_hash(self.cfg.terminal_script)
        cur_daemon = (
            file_hash(self.cfg.daemon_script) if self.cfg.daemon_script else ""
        )
        terminal_changed = bool(
            cur_terminal and state.get("terminal_hash") != cur_terminal
        )
        daemon_changed = bool(
            cur_daemon and state.get("daemon_hash") != cur_daemon
        )
        return terminal_changed, daemon_changed

    # ----- restart -----

    def kill_all_named(self) -> None:
        """Best-effort kill of processes matching configured names.

        Note: this implementation is platform-portable; for production use,
        consider a more selective kill (by PID from lockfile).
        """
        for name in self.cfg.process_names_to_kill:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/IM", f"{name}.exe"],
                        check=False,
                        capture_output=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    subprocess.run(
                        ["pkill", "-f", name],
                        check=False,
                        capture_output=True,
                    )
            except Exception as e:
                self.log(f"kill_all_named({name}) error: {e}")

    def start_terminal(self) -> subprocess.Popen | None:
        """Spawn the bot process detached, no console window."""
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
        try:
            proc = subprocess.Popen(
                [str(self.cfg.python_executable), "-u", str(self.cfg.terminal_script)],
                cwd=str(self.cfg.project_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                start_new_session=(sys.platform != "win32"),
            )
            self.log(f"start_terminal dispatched PID={proc.pid}")
            return proc
        except Exception as e:
            self.log(f"start_terminal error: {e}")
            return None

    # ----- logging -----

    def log(self, msg: str) -> None:
        from datetime import datetime
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
        print(line, flush=True)
        try:
            with self.cfg.watchdog_log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # ----- main tick -----

    def tick(self) -> bool:
        """One watchdog iteration. Returns True if restart was attempted."""
        state = load_state(self.cfg.state_path)
        terminal_changed, daemon_changed = self.detect_code_changes(state)
        has_t = self.has_terminal()
        has_d = self.has_daemon() if self.cfg.daemon_script else True
        self.log(
            f"terminal_alive={has_t} daemon_alive={has_d} "
            f"terminal_changed={terminal_changed} daemon_changed={daemon_changed}"
        )

        need_restart = (
            (not has_t)
            or (self.cfg.daemon_script is not None and not has_d)
            or terminal_changed
            or daemon_changed
        )
        if not need_restart:
            self.log("all alive, no code changes — no action")
            return False

        self.log("ACTION: kill + restart terminal")
        self.kill_all_named()
        time.sleep(1)
        self.start_terminal()
        time.sleep(3)
        if self.has_terminal():
            self.log("restart SUCCESS, saving new state")
            save_state(
                self.cfg.state_path,
                {
                    "daemon_hash": file_hash(self.cfg.daemon_script) if self.cfg.daemon_script else "",
                    "terminal_hash": file_hash(self.cfg.terminal_script),
                    "last_restart_ts": time.time(),
                },
            )
            return True
        self.log("restart FAIL — terminal not alive; next tick will retry")
        return False

    def run_forever(self) -> None:
        """Loop tick() every cfg.tick_interval_sec seconds."""
        self.log(f"watchdog started, interval={self.cfg.tick_interval_sec}s")
        while True:
            try:
                self.tick()
            except Exception as e:
                self.log(f"tick error: {e}")
            time.sleep(self.cfg.tick_interval_sec)


if __name__ == "__main__":
    # Minimal CLI: `python -m telegram_local_bridge.watchdog <terminal_script> [daemon_script]`
    if len(sys.argv) < 2:
        print("usage: python -m telegram_local_bridge.watchdog <terminal_script> [daemon_script]", file=sys.stderr)
        sys.exit(2)
    root = Path.cwd()
    term = Path(sys.argv[1]).resolve()
    daemon = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    cfg = WatchdogConfig(
        project_root=root,
        terminal_script=term,
        daemon_script=daemon,
    )
    Watchdog(cfg).run_forever()