"""Example 02: bot with token-based write approval.

Demonstrates: pending-approval store, Inline Keyboard callbacks, atomic
approval consumption, audit trail with denied/ok/error results.

Flow:
  1. User sends /write <path> <content>
  2. Bot validates path is writable, generates a token, saves pending approval,
     replies with Inline Keyboard "Approve / Reject"
  3. User taps Approve → callback arrives with token → bot consumes pending
     approval atomically and writes the file
  4. User taps Reject → pending approval is deleted, audit "denied"

Run:
    TELEGRAM_BOT_TOKEN=... python examples/02_bot_with_approval.py
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
    approval_token,
    audit_log,
    code_block,
    consume_pending_approval,
    html_escape,
    is_path_allowed,
    load_config,
    save_pending_approval,
    write_text_safe,
    AuditConfig,
)


TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def api_call(token: str, method: str, **params) -> dict:
    url = TELEGRAM_API.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=35) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send(token: str, chat_id: str, text: str, reply_markup: dict | None = None) -> None:
    params: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup)
    api_call(token, "sendMessage", **params)


def answer_callback(token: str, callback_id: str, text: str = "") -> None:
    api_call(token, "answerCallbackQuery", callback_query_id=callback_id, text=text)


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("OWNER_CHAT_ID", "")
    if not token or not chat_id:
        print("set TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID", file=sys.stderr)
        return 2

    project_root = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
    cfg_path = project_root / "data" / "state" / "telegram_allowed_paths.toml"
    cfg = load_config(cfg_path, project_root)
    pending_path = project_root / "data" / "state" / "telegram_pending_approvals.json"
    audit_cfg = AuditConfig(
        log_dir=project_root / "data" / "state",
        filename_prefix="telegram_audit",
    )

    print(f"approval bot started, chat_id={chat_id}")

    offset: int | None = None
    while True:
        try:
            params: dict = {"timeout": 30,
                            "allowed_updates": '["message","callback_query"]'}
            if offset is not None:
                params["offset"] = offset
            updates = api_call(token, "getUpdates", **params)

            for u in updates.get("result", []):
                offset = u["update_id"] + 1

                # --- callback (Approve/Reject button tap) ---
                cb = u.get("callback_query")
                if cb:
                    tok = cb.get("data", "")
                    entry = consume_pending_approval(pending_path, tok)
                    if entry is None:
                        answer_callback(token, cb["id"], "expired or unknown")
                        continue
                    target = Path(entry["path"]).resolve()
                    ok, reason = is_path_allowed(cfg, target, mode="write")
                    if not ok:
                        audit_log(audit_cfg, chat_id=chat_id, command="write",
                                  result="denied", path=str(target), error=reason)
                        answer_callback(token, cb["id"], f"denied: {reason}")
                        continue
                    try:
                        write_text_safe(target, entry["content_full"])
                        audit_log(audit_cfg, chat_id=chat_id, command="write",
                                  result="ok", path=str(target),
                                  bytes_size=len(entry["content_full"].encode("utf-8")))
                        answer_callback(token, cb["id"], "approved & written")
                    except Exception as e:
                        audit_log(audit_cfg, chat_id=chat_id, command="write",
                                  result="error", path=str(target), error=str(e))
                        answer_callback(token, cb["id"], f"error: {e}")
                    continue

                # --- text command ---
                msg = u.get("message", {})
                if str(msg.get("chat", {}).get("id")) != str(chat_id):
                    continue
                text = (msg.get("text") or "").strip()

                if text.startswith("/write "):
                    # Format: /write <path>\n<content>
                    body = text[len("/write "):]
                    if "\n" not in body:
                        send(token, chat_id, "usage: /write &lt;path&gt;\\n&lt;content&gt;")
                        continue
                    path_str, content = body.split("\n", 1)
                    target = Path(path_str.strip()).resolve()
                    ok, reason = is_path_allowed(cfg, target, mode="write")
                    if not ok:
                        audit_log(audit_cfg, chat_id=chat_id, command="write",
                                  result="denied", path=str(target), error=reason)
                        send(token, chat_id, f"denied: {html_escape(reason)}")
                        continue
                    tok = approval_token(str(target), content)
                    save_pending_approval(
                        pending_path, tok,
                        chat_id=chat_id, command="write", path=str(target),
                        content_preview=content[:500], content_full=content,
                    )
                    keyboard = {
                        "inline_keyboard": [[
                            {"text": "Approve", "callback_data": tok},
                            {"text": "Reject",  "callback_data": f"reject:{tok}"},
                        ]]
                    }
                    preview = code_block(content[:300])
                    send(token, chat_id,
                         f"approve write to <b>{html_escape(str(target))}</b>?\n{preview}",
                         reply_markup=keyboard)

                elif text == "/start":
                    send(token, chat_id,
                         "approval bot ready. send /write &lt;path&gt;\\n&lt;content&gt;")
        except Exception as e:
            print(f"loop error: {e}", file=sys.stderr)
            time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())