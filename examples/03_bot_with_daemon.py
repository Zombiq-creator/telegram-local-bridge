"""Example 03: bot with watchdog supervision.

Two processes:
  - bot.py  — long-polls Telegram, writes its PID to {project_root}/data/state/bot.lock
  - watchdog.py — runs separately, checks every 30s that the bot is alive
    (lockfile present + PID still running). If not, restarts the bot.

The bot and the watchdog are decoupled. The bot can be killed at any time
and the watchdog will respawn it within ~30s.

Run:
    # Terminal A: start the bot once (it writes bot.lock on startup)
    python examples/03a_bot.py

    # Terminal B: start the watchdog in a separate shell
    python examples/03_watchdog.py

    # Now kill Terminal A's bot (Ctrl-C). Within 30s, the watchdog will
    # restart it.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

from telegram_local_bridge import (  # noqa: E402
    audit_log,
    html_escape,
    AuditConfig,
    LockfileData,
    write_lockfile,
)


TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def api_call(token: str, method: str, **params) -> dict:
    url = TELEGRAM_API.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=35) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send(token: str, chat_id: str, text: str) -> None:
    api_call(token, "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("OWNER_CHAT_ID", "")
    if not token or not chat_id:
        print("set TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID", file=sys.stderr)
        return 2

    project_root = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
    lock_path = project_root / "data" / "state" / "bot.lock"
    audit_cfg = AuditConfig(
        log_dir=project_root / "data" / "state",
        filename_prefix="telegram_audit",
    )

    # Write lockfile so the watchdog can find us.
    write_lockfile(lock_path, LockfileData(
        terminal_pid=os.getpid(),
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    ))
    audit_log(audit_cfg, chat_id="system", command="bot_start",
              result="ok", extra={"pid": os.getpid()})
    print(f"bot started, PID={os.getpid()}, lockfile={lock_path}")

    offset: int | None = None
    try:
        while True:
            try:
                params: dict = {"timeout": 30, "allowed_updates": '["message"]'}
                if offset is not None:
                    params["offset"] = offset
                updates = api_call(token, "getUpdates", **params)
                for u in updates.get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message", {})
                    if str(msg.get("chat", {}).get("id")) != str(chat_id):
                        continue
                    text = (msg.get("text") or "").strip()
                    if text == "/ping":
                        send(token, chat_id, "pong")
            except Exception as e:
                print(f"loop error: {e}", file=sys.stderr)
                time.sleep(3)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    sys.exit(main())