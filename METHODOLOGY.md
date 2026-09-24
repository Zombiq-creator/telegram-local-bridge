# METHODOLOGY — building a local-process → Telegram bridge

This document explains the *why* behind every design decision in
`telegram-local-bridge`. Each pattern is paired with the failure mode that
motivated it and the trade-off it accepts.

If you're going to copy this library into your own project, read this first.
If you're going to fork it, the principles matter more than the code.

---

## 1. The shape of the problem

You have:

- A long-running process on your machine (a tool, a daemon, an AI agent, a
  build watcher).
- A need to interact with it from your phone, in a chat app you already have
  open.
- Files on disk that the process must read or modify.
- A security model: you don't want a chat leak to mean "delete my whole
  project".

A Telegram bot is a good fit because:

- No new app to install.
- Long polling is supported without exposing a public webhook.
- Inline Keyboards give you a clean approval primitive.

A Telegram bot is **not** a good fit when:

- You need real-time sub-second latency (use WebSocket + native app).
- Your "process" is actually a cluster (use a queue + dashboard).
- The data you handle is regulated (HIPAA, etc.) — Telegram is not a BAA
  provider.

---

## 2. Six design principles

### 2.1 Stdlib-only

The library depends on **nothing** beyond Python 3.11+ stdlib. This is
deliberate:

- The library is run inside long-lived processes that you don't want to
  break with a transitive dependency upgrade.
- It keeps the supply-chain surface small.
- Most of the work is file I/O, hashing, JSON, and TOML — all in stdlib.

If you want richer Telegram ergonomics, plug in `python-telegram-bot` or
`httpx` in your bot script. The library does not need them.

### 2.2 Explicit > implicit

Every file read passes `encoding="utf-8"`. Every audit log entry carries the
detected encoding and byte size. Every approved write carries the approval
token. If something fails, the log entry tells you what happened.

This is at odds with Python's usual "just open it" idiom. The cost is a few
extra parameters per call. The benefit is that debugging from a phone, in a
chat log, is possible — `path`, `encoding`, `bytes`, `result` are all there.

### 2.3 Allowlist, not blocklist

`config.is_path_allowed()` defaults to **no access**. Paths must be in
`allowed_roots` AND not match `forbidden_paths` to be readable. This is the
opposite of the usual Unix "deny by default" model and is intentional:

- A typo in the bot code that says `Path("/")` instead of `Path("/data")`
  should fail closed, not open the entire filesystem.
- `forbidden_paths` is a *second* line of defense for paths that look
  legitimate (e.g. `**/secrets.toml`) but must never be exposed even if the
  caller allows them.

The default config that ships with the library includes `**/.env`,
`**/secrets.toml`, `**/.ssh/**`, `**/.git/**` in `forbidden_paths`.

### 2.4 Audit everything, but don't fail loudly

Every read, every write, every denial — logged to a JSONL file in UTC, rotated
daily, retained for 30 days (configurable).

If `audit_log()` itself fails (disk full, permission denied), it prints to
stderr but does **not** raise. The reasoning: the audit log is for *you* to
forensically review what happened; if it breaks, the bot should keep
running, not crash and lose the user's context.

If you need stronger guarantees (e.g. financial transactions), point the
audit at a syslog forwarder or an append-only DB.

### 2.5 Approval by token, not by reference

When a write command comes in:

1. Compute `token = sha256(path + content + ts)[:16]`.
2. Store the pending approval under that token, with TTL.
3. Show the user an Inline Keyboard with `Approve` / `Reject` buttons whose
   `callback_data` is the token.
4. When the user taps a button, look up the token, validate, and either
   write the file (approve) or delete the pending entry (reject).

Why tokens, not file paths or "current pending request"?

- The user might have multiple approvals pending. Path-based references
  can't distinguish them.
- Tokens are short (16 hex chars) — fit in Inline Keyboard callbacks.
- Tokens are single-use: `consume_pending_approval` atomically reads and
  deletes, so a button tap can't be replayed.
- The TTL (10 min default) means stale approvals are auto-expired.

### 2.6 Lockfile, not heuristics

The watchdog needs to know: is the bot still running?

The naive answer: `tasklist /FI "IMAGENAME eq pythonw.exe"`. The
problem: the watchdog itself is `pythonw.exe`, so it false-positives on
itself. (We hit this in production. The terminal died, the watchdog was
"running" by its own detection, and the bot never came back.)

The robust answer: the bot writes a JSON lockfile with its PID on startup,
and removes it on clean shutdown. The watchdog reads the lockfile and
checks PID liveness via `os.kill(pid, 0)`.

Why is this better?

- PID liveness is unambiguous.
- The lockfile can carry metadata (started_at, version) for diagnostics.
- Atomic writes via `os.replace` mean a partial write can never be read as
  valid JSON.

---

## 3. The encoding trap (and how we got out of it)

A surprising fraction of the time spent on this library went into encoding
issues. The full list is in [`docs/encoding-strategy.md`](docs/encoding-strategy.md);
here's the summary:

- Windows PowerShell defaults to cp1251; Python inherits this and writes
  mojibake when the source is UTF-8.
- `read_text()` without an explicit encoding is platform-dependent.
- Telegram's `parse_mode=HTML` re-parses entities, so `<` and `>` in your
  text must be escaped.
- Telegram's `parse_mode=HTML` ALSO doesn't parse entities inside `<code>`
  blocks — but if you forget to escape `<` and `>` outside `<code>`, your
  whole message breaks.
- PowerShell `5.1` reads files in cp1251 even when they're saved as UTF-8.

The fix is a 10-rule checklist, baked into `encoding.py` and enforced by
`safe_io.py`. Anyone who works with text on Windows + Telegram should read
that doc.

---

## 4. Process supervision without containers

You don't need Docker to supervise a process. You need:

1. **A lockfile.** Bot writes `{pid, started_at}` on startup, removes on
   clean shutdown.
2. **A watchdog loop.** Every N seconds: is the lockfile present? Is the PID
   alive? If no to either, kill any stragglers and restart.
3. **File-hash detection.** If the bot's source code changes, restart so the
   patch is picked up within N seconds (no manual service restarts).

This is what `watchdog.py` does. It's ~200 lines and replaces a systemd
unit, a Docker container, or a process supervisor. The trade-off is that
it doesn't do resource limits, log rotation, or graceful shutdown signaling
— those are out of scope.

For production-grade supervision, wrap it in `nssm` (Windows) or a systemd
service (Linux) — the watchdog is the in-process layer, not the OS layer.

---

## 5. Security model

Threat model:

- A Telegram user other than the owner discovers the bot and sends commands.
- A Telegram user (or a replay attack) tries to approve a write they didn't
  request.
- A misconfigured `PROJECT_ROOT` exposes too much of the filesystem.
- The bot is compromised (e.g. via a supply-chain attack on a dependency).

Mitigations:

- **Single-user whitelist:** the bot only responds to `OWNER_CHAT_ID`. Multi-
  user is not supported — if you need it, fork the library.
- **Single-use approval tokens:** the Inline Keyboard callback can only be
  used once (atomic consumption). Replay = denial.
- **Allowlist + forbidlist:** see §2.3.
- **Audit log:** every action is logged; compromise can be forensically
  reconstructed.
- **No network outside Telegram:** the bot only talks to `api.telegram.org`
  (or your proxy). It does not fetch URLs or call other APIs.

Out of scope (and you should not pretend otherwise):

- Side-channel attacks on the Telegram protocol.
- Compromise of the Telegram servers themselves.
- Local privilege escalation (if an attacker can run code as your user, the
  game is already over).

---

## 6. When *not* to use this library

- You need multi-user chat. (This is a single-owner bot.)
- You need sub-second latency. (Telegram long-poll is ~1-3s latency.)
- Your data is regulated. (Use a BAA-covered service.)
- You need to expose the bot to the public internet. (A reverse proxy with
  webhook + TLS termination is more appropriate.)
- You're building a full AI agent with memory and tool use. (This library
  gives you the safe-IO primitives — the agent itself is your code.)

---

## 7. Extending the library

The library is intentionally narrow. If you need:

- **More commands:** write a handler function, register it in your bot loop.
  Use `audit_log` for every state change.
- **More storage backends:** the lockfile and pending-approval store are
  JSON-on-disk. Replace them with SQLite or Redis if you need concurrency.
- **Multi-process supervision:** see §4. Layer `nssm` / systemd / `runit`
  on top of the in-process watchdog.

The library's job is to handle the **boring, error-prone parts** — encoding
fallbacks, audit logging, atomic file replacement, PID liveness — so your
bot code can focus on the **interesting parts** — what to do with the
commands it receives.

---

## 8. References

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Python tomllib](https://docs.python.org/3/library/tomllib.html)
- [os.kill(pid, 0) for liveness checks](https://docs.python.org/3/library/os.html#os.kill)
- Windows [DETACHED_PROCESS](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
  and [CREATE_NO_WINDOW](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)