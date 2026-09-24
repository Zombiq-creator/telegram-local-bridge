# safe-io.md — path allowlist, audit log, line-ending preservation

The `safe_io` and `config` modules exist to answer one question safely:
"can I read or write this file?"

## The allowlist

A TOML config (default: `{project_root}/data/state/telegram_allowed_paths.toml`)
defines:

```toml
[read]
allowed_roots = [
    "/abs/path/to/project",
    "/abs/path/to/project/scripts",
    "/abs/path/to/project/data",
]

[write]
allowed_roots = [
    "/abs/path/to/project/data",
]

[forbidden_paths]
always_forbidden = [
    "**/.git/**",
    "**/.env",
    "**/secrets.toml",
    "**/.ssh/**",
]
```

On first run, the library writes this default if the file doesn't exist.
After that, edit the file (or use your bot's `/config edit` command if you
have one) and reload.

## The check

```python
from telegram_local_bridge import is_path_allowed, load_config

cfg = load_config(cfg_path, project_root)
allowed, reason = is_path_allowed(cfg, Path("/some/path"), mode="read")
if not allowed:
    audit_log(cfg.audit, chat_id=..., command="read",
              result="denied", path=str(path), error=reason)
    return
```

`reason` is human-readable. It's safe to send back to the user; it doesn't
leak path information.

## Forbidden patterns

Forbidden patterns are checked **before** allowed_roots. A path can be in
`read.allowed_roots` and still be denied if it matches a forbidden pattern.

Patterns are `fnmatch`-style globs:

| Pattern | Matches |
|---|---|
| `**/secrets.toml` | Any `secrets.toml` anywhere in the tree |
| `**/.env` | Top-level `.env` only (because of leading `**/`) |
| `**/.env*` | Any file starting with `.env` |
| `**/_private/**` | Everything under a `_private/` directory |
| `**/.git/**` | Everything under `.git/` |

Note the subtle distinction:

- `**/secrets.toml` matches `secrets.toml` and `path/to/secrets.toml`.
- `**/_private/**` matches `_private/x`, `path/_private/x`, etc. (any
  segment named `_private`).
- `secrets.toml` (no `**/`) only matches the literal `secrets.toml` in cwd.

## Audit log

Every read/write/denial/error produces one JSONL line:

```json
{"ts":"2026-09-24T12:34:56+00:00","chat_id":"...","command":"read","result":"ok","path":"...","detected_encoding":"utf-8","bytes":1234}
```

Result is one of:

- `ok` — operation succeeded
- `denied` — path allowlist rejected
- `error` — I/O failure (file not found, permission denied, etc.)

The log is rotated daily (UTC) and entries older than `retention_days` are
deleted on next bot startup. Both are configurable via `AuditConfig`.

## Why an allowlist?

Two reasons:

1. **Bug-resistant.** A typo (`Path("/")` instead of `Path("/data")`) fails
   closed instead of opening the entire filesystem.
2. **Explicit.** You can grep the config to see exactly what the bot can
   touch. Easier to audit than reading code.

## Line endings

`write_text_safe` uses `newline=""` which preserves whatever line endings
the file already has (CRLF on Windows, LF on Unix). Don't use this on a
file that needs to be normalized — those are rare and usually worth a
dedicated migration script.