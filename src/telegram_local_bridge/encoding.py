"""encoding.py — UTF-8/cp1251 fallback, HTML escape, code block formatting.

Design rationale: see docs/encoding-strategy.md (10 rules distilled from
real-world Windows + Telegram mojibake incidents).
"""
from __future__ import annotations

import html
import sys
from pathlib import Path


def force_utf8_stdout() -> None:
    """Force UTF-8 on stdout/stderr. Safe to call multiple times.

    Rule 1 (from encoding-strategy.md): without this, print() on Windows
    PowerShell 5.1 produces mojibake (cp1251 default).
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass  # subprocess with closed stdout — ignore


def html_escape(s: str) -> str:
    """Escape HTML for Telegram parse_mode=HTML.

    quote=False: keep quotes as-is (Telegram <code> doesn't parse them).
    """
    return html.escape(s, quote=False)


def code_block(content: str, max_chars: int = 3500) -> str:
    """Format content as a Telegram <code> block, truncated to fit.

    Telegram message limit is 4096 chars; we reserve ~500 for the wrapper
    and surrounding text.
    """
    if len(content) <= max_chars:
        return f"<code>{html_escape(content)}</code>"
    truncated = content[:max_chars]
    return (
        f"<code>{html_escape(truncated)}</code>\n"
        f"<i>... truncated ({len(content) - max_chars} chars)</i>"
    )


def read_text_with_fallback(path: Path, max_bytes: int = 1_000_000) -> tuple[str, str]:
    """Read a text file with UTF-8 → cp1251 → errors='replace' fallback.

    Returns (content, detected_encoding) where detected_encoding is one of:
      'utf-8', 'cp1251', 'utf-8-replace'.

    max_bytes protects against accidentally reading huge files (default 1 MB).

    Rule 2 (encoding-strategy.md): on Windows, legacy files are often cp1251.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"not found: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"file too large: {size} bytes (max {max_bytes})")

    try:
        content = path.read_text(encoding="utf-8")
        if content.startswith("\ufeff"):
            content = content[1:]
        return content, "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        content = path.read_text(encoding="cp1251")
        return content, "cp1251"
    except UnicodeDecodeError:
        pass

    content = path.read_text(encoding="utf-8", errors="replace")
    if content.startswith("\ufeff"):
        content = content[1:]
    return content, "utf-8-replace"