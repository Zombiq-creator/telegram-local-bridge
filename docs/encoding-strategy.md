# encoding-strategy.md — 10 rules for UTF-8 / cp1251 / Telegram HTML

Distilled from months of Windows + Telegram mojibake incidents. Apply all 10
or expect pain.

## Rule 1 — Force UTF-8 stdout/stderr on startup

```python
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
```

Without this, `print()` on Windows PowerShell 5.1 produces mojibake because
Python inherits the cp1251 console encoding. The library does this in
`encoding.force_utf8_stdout()` — call it once on bot startup.

## Rule 2 — Always pass `encoding="utf-8"` explicitly

`open(path)` without an encoding argument is platform-dependent. On Linux
it's usually UTF-8; on Windows it can be cp1251. Always explicit.

## Rule 3 — Preserve line endings

Use `newline=""` when writing text files. Otherwise Python translates
`\n` to `os.linesep` on Windows, double-converting existing CRLF files.

## Rule 4 — Fall back to cp1251 on read

Legacy Russian Windows files are often cp1251. The library tries UTF-8
first, then cp1251, then `errors="replace"`. The detected encoding is
returned alongside the content so you can decide what to do.

## Rule 5 — UTF-8 BOM

Some Windows editors (Notepad) save UTF-8 with a BOM. Strip it:

```python
if content.startswith("\ufeff"):
    content = content[1:]
```

## Rule 6 — HTML-escape Telegram text

Telegram's `parse_mode=HTML` re-parses HTML entities. If your text contains
`<`, `>`, `&`, they'll be interpreted as tags and your message will be
silently broken or rejected.

Use `html_escape()` from the library. Note: `quote=False` keeps quotes
intact (Telegram's `<code>` blocks don't parse them, so escaping is
wasteful and ugly).

## Rule 7 — TOML is UTF-8

`tomllib.load()` requires binary read; the bytes must be UTF-8. Don't pass
a text-mode handle — it will fail or misbehave on Windows.

## Rule 8 — JSON in audit logs: `ensure_ascii=False`

```python
json.dumps(entry, ensure_ascii=False)
```

`ensure_ascii=True` (the default) escapes all non-ASCII characters as
`\uXXXX`, which makes the logs unreadable in any text viewer. The library
uses `ensure_ascii=False`.

## Rule 9 — Code blocks truncate before escaping

Telegram's message limit is 4096 chars. Reserve ~500 for the wrapper and
surrounding text. The library's `code_block()` truncates at 3500 chars by
default and appends a `<i>... truncated</i>` marker.

## Rule 10 — Audit log every state change

Every read, every write, every denial — log it. JSONL with daily UTC
rotation. If you can't reconstruct what happened from the log, the log is
not detailed enough.

## The 10 rules, in 10 lines of code

```python
sys.stdout.reconfigure(encoding="utf-8")                    # Rule 1
content = path.read_text(encoding="utf-8")                  # Rule 2
path.write_text(content, encoding="utf-8", newline="")      # Rule 3
content, enc = read_text_with_fallback(path)                # Rule 4
if content.startswith("\ufeff"): content = content[1:]      # Rule 5
safe = html_escape(text, quote=False)                       # Rule 6
tomllib.loads(path.read_bytes())                            # Rule 7
json.dumps(entry, ensure_ascii=False)                       # Rule 8
send(code_block(content))                                   # Rule 9
audit_log(chat_id=cid, command="read", result="ok", ...)    # Rule 10
```

That's the whole encoding strategy. Stick to it.