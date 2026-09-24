# approval-flow.md — single-use tokens, Inline Keyboard, atomic consumption

A write command without approval is a footgun. A write command with a
yes/no prompt in chat is fragile. The library's `approval` module gives you
a robust pattern.

## The flow

```
User: /write /path/to/file.txt
      this is the new content

Bot:  approve write to /path/to/file.txt?
      this is the new
      [content preview]
      [Approve] [Reject]   <- Inline Keyboard buttons

User: [taps Approve]

Bot:  approved & written
```

If the user taps Reject, the pending approval is deleted and the file is
not touched.

If the user taps nothing for 10 minutes (TTL), the pending approval
auto-expires and the file is not touched.

## The token

```python
from telegram_local_bridge import approval_token

tok = approval_token(path, content, ts=time.time())
# 16 hex chars: "3f7a1b9c8d2e4f5a"
```

The token is `sha256(path + "|" + content + "|" + ts)[:16]`. Properties:

- **Deterministic** for a given (path, content, ts) — useful for testing.
- **Collision-resistant** — 64 bits of entropy, more than enough for a
  single bot's pending approvals within a 10-minute TTL.
- **Short** — fits in Inline Keyboard `callback_data` (Telegram limits
  callback_data to 64 bytes).

The token is the **only** thing the user sees and the only thing the bot
uses to look up the pending approval. The path and content never appear
in the callback URL — only in the Inline Keyboard button's `callback_data`.

## The store

Pending approvals live in a JSON file at
`{project_root}/data/state/telegram_pending_approvals.json`:

```json
{
  "3f7a1b9c8d2e4f5a": {
    "chat_id": "123456789",
    "command": "write",
    "path": "/abs/path/to/file.txt",
    "content_preview": "first 500 chars...",
    "content_full": "full content for write",
    "created_at": 1727123456.789,
    "expires_at": 1727124056.789
  }
}
```

Two operations:

- `save_pending_approval(path, token, ...)` — add or overwrite.
- `consume_pending_approval(path, token)` — atomically read AND delete.
  Returns None if the token is missing or expired.

`consume_pending_approval` is atomic in the sense that `pop` + `save` run
in immediate succession within the same function call. A second tap on
the same button after the first consumed will get `None` and reply
"expired or unknown".

## Inline Keyboard

Telegram's Inline Keyboard is the right primitive because:

- The user doesn't have to type anything — fewer typos, faster interaction.
- The button's `callback_data` is opaque — users can't see the token.
- The button can only be tapped once (each callback is one-shot from
  Telegram's side); combined with our atomic consumption, this is
  defense-in-depth against replay.

```python
keyboard = {
    "inline_keyboard": [[
        {"text": "Approve", "callback_data": tok},
        {"text": "Reject",  "callback_data": f"reject:{tok}"},
    ]]
}
api_call("sendMessage", chat_id=chat_id, text=preview,
         reply_markup=json.dumps(keyboard))
```

Note the `reject:` prefix on the Reject button — this lets the callback
handler distinguish "explicit reject" from "expired token" without
consulting the store (and racing against the TTL).

## Audit trail

Every state change is logged:

```json
{"ts": "...", "chat_id": "...", "command": "write",
 "result": "ok", "path": "...", "bytes": 1234}
{"ts": "...", "chat_id": "...", "command": "write",
 "result": "denied", "path": "...", "error": "forbidden by pattern: **/secrets.toml"}
```

If you ever wonder "did I actually write that file last Tuesday?", grep the
audit log. The answer is in 5 seconds.

## What approval does NOT solve

- **Compromise of the Telegram session.** If someone gets into your
  Telegram account, they can approve anything. Mitigation: enable 2FA on
  Telegram; lock your phone.
- **Replay across bot restarts.** The token is single-use, but if you
  re-deploy the bot and forget the pending-approvals.json, an old token
  becomes a new token if (path, content, ts) collide. Mitigation: keep
  the store on persistent disk (which the library does by default).
- **Race between two approvals.** If two write requests arrive within the
  same second for the same (path, content), they get the same token.
  Mitigation: include sub-second precision in `ts` (`time.time_ns()`), or
  always include a nonce. The library uses `time.time()` (second
  precision) which is fine for a single-user bot but not for high-rate
  scenarios.