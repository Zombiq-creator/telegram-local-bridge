"""Companion watchdog for example 03.

Run alongside 03_bot_with_daemon.py. The watchdog checks every 30s whether
the bot's lockfile points at a live PID; if not, it respawns the bot.

Usage:
    python examples/03_watchdog.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

from telegram_local_bridge import (  # noqa: E402
    LockfileData,
    Watchdog,
    WatchdogConfig,
    pid_alive,
    read_lockfile,
    write_lockfile,
)


def main() -> int:
    project_root = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
    cfg = WatchdogConfig(
        project_root=project_root,
        terminal_script=_HERE / "03_bot_with_daemon.py",
        python_executable=Path(sys.executable),
        tick_interval_sec=30,
        process_names_to_kill=["python"],   # crude; refine for prod
    )
    wd = Watchdog(cfg)

    # Replace the watchdog's start_terminal with a thin wrapper that also
    # writes a fresh lockfile so the bot is discoverable.
    original_start = wd.start_terminal

    def start_and_track() -> subprocess.Popen | None:
        proc = original_start()
        if proc is not None:
            write_lockfile(cfg.lockfile_path, LockfileData(
                terminal_pid=proc.pid,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ))
        return proc

    wd.start_terminal = start_and_track  # type: ignore[method-assign]
    wd.run_forever()


if __name__ == "__main__":
    sys.exit(main())