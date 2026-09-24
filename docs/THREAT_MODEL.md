# Threat Model

This document describes the security properties of `telegram-local-bridge`,
the threats it mitigates, and the threats it does **not** address.

The library is intended for **single-owner, self-hosted** deployments: one
human, one Telegram account, one bot. Multi-user deployments are explicitly
out of scope.

## System overview

```
+-----------+    HTTPS    +-----------+    UDP     +--------------+
| bot.py    | <---------> | Telegram  | <--------> | OWNER phone  |
| (library) |  long-poll  | Bot API   |  Telegram  | (Telegram)   |
+-----------+             +-----------+            +--------------+
     |
     | file I/O (allowlist)        audit log (jsonl)
     v
+-----------+             +-----------+
| project   |             | data/     |
| files     |             | state/    |
+-----------+             +-----------+

+-----------+
| watchdog  |  supervises bot.py via lockfile + file-hash
+-----------+
```

**Trust boundary:** the user's machine. Everything outside (Telegram API,
the Telegram phone app, any other Telegram user) is untrusted.

**Out of trust boundary:** the Telegram servers themselves. We treat them
as a black box that delivers messages from `OWNER_CHAT_ID` and no one else.

## Threats mitigated

### T1 — Non-owner chat access

- **Threat:** A Telegram user other than `OWNER_CHAT_ID` discovers the bot
  and sends commands.
- **Mitigation:** Single-user whitelist at the message-dispatch layer.
  Any incoming message with `chat_id != OWNER_CHAT_ID` is logged via
  `audit_log(result="denied", error="chat_id not in whitelist")` and ignored.
- **Residual risk:** If `OWNER_CHAT_ID` is misconfigured (e.g. typed
  wrong), an attacker with the bot token could impersonate. Mitigation:
  the bot logs a warning when chat_id from secrets.toml differs from the
  hardcoded `OWNER_CHAT_ID` constant.

### T2 — Replay attacks on approvals

- **Threat:** An attacker captures a Telegram Inline Keyboard callback and
  replays it later to re-approve a write.
- **Mitigation:** Approval tokens are single-use.
  `consume_pending_approval()` atomically reads AND deletes the pending
  entry. A second tap returns `None`. TTL of 10 minutes by default
  prevents indefinitely-stale tokens.
- **Residual risk:** If the pending-approval JSON file is deleted between
  first approval and second tap, replay succeeds against a *new* request
  that happens to share `(path, content, ts)`. Probability is negligible
  for a single-user bot at sub-second `(path, content, ts)` collisions.

### T3 — Accidental root access (deny-by-default)

- **Threat:** A typo (`Path("/")` instead of `Path("/data")`) causes the
  bot to read or write the entire filesystem.
- **Mitigation:** Deny-by-default in `config.is_path_allowed()`. Default
  config has narrow `allowed_roots`. `forbidden_paths` always blocks
  `.env`, `.git`, `.ssh`, `secrets.toml`, etc. — even if accidentally
  added to `allowed_roots`.
- **Residual risk:** If the user edits the config and explicitly adds `/`
  to `allowed_roots`, all bets are off. Documented in `docs/safe-io.md`.

### T4 — File deletion or overwrite by typos

- **Threat:** A bot command like `delete <path>` or `write <path>` has a
  typo and points at `/etc`, `C:\Windows`, or another critical directory.
- **Mitigation:** Same path allowlist applies to all operations, not just
  reads. Forbidden patterns override allowed_roots.
- **Residual risk:** Same as T3 — depends on config.

### T5 — Encoding-based mojibake attacks

- **Threat:** Attacker sends a message with carefully-crafted Unicode
  (RTL override, zero-width characters, homoglyphs) that hijacks
  Telegram's HTML rendering or the audit log.
- **Mitigation:** `encoding.html_escape()` always escapes `<`, `>`, `&`
  before sending. `code_block()` truncates and wraps in `<code>` tags.
  Full rationale in `docs/encoding-strategy.md`.
- **Residual risk:** Telegram's HTML parser has historically had edge
  cases. Mitigation: `code_block()` truncates to 3500 chars to keep
  messages well under Telegram's 4096-char limit.

### T6 — False-positive watchdog detection

- **Threat:** Watchdog mistakenly detects the bot as alive when it's
  actually dead (or vice versa), leading to either no-restart or
  restart-loops.
- **Mitigation:** Lockfile with explicit PID (not "any pythonw.exe").
  `os.kill(pid, 0)` for liveness. Atomic lockfile writes via
  `os.replace(tmp, path)` — partial writes never read as valid JSON.
- **Residual risk:** If the bot writes a lockfile and then crashes before
  the lockfile is committed, watchdog correctly detects dead state. If
  the bot writes the lockfile but the process is hung, watchdog sees
  alive state (see T8).

### T7 — Supply-chain attack via dependency upgrade

- **Threat:** A transitive dependency (e.g. `httpx` upgrade) introduces a
  vulnerability or backdoor.
- **Mitigation:** Stdlib-only. No runtime dependencies. `pip-audit`,
  `dependabot`, and `safety` find nothing to scan. CVE in stdlib itself
  is rare but possible — see deployment notes.
- **Residual risk:** Python interpreter itself has had CVEs. Mitigation:
  pin Python version in deployment, apply OS security updates promptly.

### T8 — Process hangs blocking the bot

- **Threat:** A long-running file operation or network call freezes the
  bot, preventing response to Telegram polls. Watchdog sees the lockfile
  and PID, thinks the bot is alive.
- **Mitigation:** (Out of scope for the library itself.) The user's bot
  code must use timeouts on all I/O. Future enhancement: watchdog could
  add a "last heartbeat" check.
- **Workaround now:** Run your bot behind an OS service that kills
  unresponsive processes (e.g. systemd `WatchdogSec`).

### T9 — Audit log tampering

- **Threat:** An attacker (or a bug) modifies the audit log to hide
  evidence of malicious activity.
- **Mitigation:** Audit log is append-only (jsonl). Old rotated files
  are kept for `retention_days` (default 30). Deletion requires explicit
  `cleanup_old_audit_logs()` call.
- **Residual risk:** If the attacker has filesystem write access, they
  can delete the audit log. Mitigation: ship logs off-host (syslog,
  cloud logging) if you need tamper-evidence.

## Out of scope

The following are **explicitly not mitigated** by this library. Users are
responsible for additional defenses.

- **Telegram protocol compromise.** If Telegram itself is compromised,
  the library cannot help. Mitigation: enable 2FA on Telegram.
- **Host privilege escalation.** If an attacker can run code as the
  bot's user, the game is over. Mitigation: standard OS hardening.
- **Side-channel on Telegram servers.** Out of library scope.
- **Multi-user support.** Library is single-owner. Multi-user bot = fork.
- **Public exposure.** Library uses long-polling. If you put a webhook
  server in front, you must handle TLS / authentication yourself.
- **Semantic content filtering.** Approvals are by token, not by content
  analysis. A clever prompt injection that tricks the bot into calling
  `write_file("/etc/cron.d/backdoor", "...")` still requires user approval
  via the Inline Keyboard — but a user who taps "Approve" without reading
  the preview is on their own.

## Audit trail

Every state-changing operation produces an entry in
`data/state/telegram_audit-YYYY-MM-DD.jsonl`:

```json
{"ts":"2026-09-24T12:34:56+00:00","chat_id":"...","command":"write","result":"ok","path":"...","bytes":1234}
{"ts":"2026-09-24T12:34:57+00:00","chat_id":"...","command":"write","result":"denied","path":"...","error":"forbidden by pattern: **/secrets.toml"}
```

`result` is one of: `ok` | `denied` | `error` | `pending`.

If you ever wonder "did I actually write that file last Tuesday?", grep
the audit log. The answer is in 5 seconds.

## Reporting vulnerabilities

Open a GitHub issue **without** including exploit details, or use GitHub's
private vulnerability reporting (`Security` tab → "Report a vulnerability").
Do not post full exploits to public issues.