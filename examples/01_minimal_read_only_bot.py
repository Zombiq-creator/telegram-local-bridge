"""Example 01: minimal read-only Telegram bot.

Demonstrates: long-poll loop, safe I/O with encoding fallback, path allowlist,
audit logging. No approval, no daemon, no watchdog — the simplest possible
bot that satisfies "let me read project files from my phone".

Run:
    TELEGRAM_BOT_TOKEN=... python examples/01_minimal_read_only_bot.py

Dependencies: only the library itself + stdlib (urllib for Telegram API).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

# Add src/ to path when running this example directly from the repo.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

from telegram_local_bridge import (  # noqa: E402
    audit_log,
    code_block,
    html_escape,
    AuditConfig,
    is_path_allowed,
    load_config,
    read_text_safe,
)


TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def api_call(token: str, method: str, **params) -> dict:
    """Minimal Telegram Bot API call (stdlib only)."""
    url = TELEGRAM_API.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=35) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send(token: str, chat_id: str, text: str) -> None:
    """Send a Telegram message (HTML parse mode, truncated to fit)."""
    api_call(token, "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")


def handle_read(token: str, chat_id: str, path_str: str,
                cfg: dict, audit_cfg: AuditConfig) -> None:
    """Process /read <path>: validate, read, reply."""
    target = Path(path_str).resolve()

    allowed, reason = is_path_allowed(cfg, target, mode="read")
    if not allowed:
        audit_log(audit_cfg, chat_id=chat_id, command="read",
                  result="denied", path=str(target), error=reason)
        send(token, chat_id, f"denied: {html_escape(reason)}")
        return

    try:
        content, encoding = read_text_safe(target)
    except (FileNotFoundError, ValueError) as e:
        audit_log(audit_cfg, chat_id=chat_id, command="read",
                  result="error", path=str(target), error=str(e))
        send(token, chat_id, f"error: {html_escape(str(e))}")
        return

    audit_log(audit_cfg, chat_id=chat_id, command="read",
              result="ok", path=str(target),
              detected_encoding=encoding, bytes_size=len(content.encode("utf-8")))

    header = f"<b>{html_escape(str(target))}</b>  <i>({encoding}, {len(content)} chars)</i>"
    send(token, chat_id, header + "\n\n" + code_block(content))


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("OWNER_CHAT_ID", "")  # single-user bot
    if not token or not chat_id:
        print("set TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID", file=sys.stderr)
        return 2

    project_root = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
    cfg_path = project_root / "data" / "state" / "telegram_allowed_paths.toml"
    cfg = load_config(cfg_path, project_root)

    audit_cfg = AuditConfig(
        log_dir=project_root / "data" / "state",
        filename_prefix="telegram_audit",
    )

    print(f"minimal bot started, chat_id={chat_id}, root={project_root}")
    offset: int | None = None
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
                    continue  # whitelist
                text = (msg.get("text") or "").strip()
                if text.startswith("/read "):
                    handle_read(token, str(chat_id), text[len("/read "):].strip(),
                                cfg, audit_cfg)
                elif text == "/start":
                    send(token, str(chat_id),
                         "minimal bot ready. send /read &lt;path&gt;")
        except Exception as e:
            print(f"loop error: {e}", file=sys.stderr)
            time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())