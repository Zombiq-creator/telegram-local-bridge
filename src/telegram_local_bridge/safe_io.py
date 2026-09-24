"""safe_io.py — file I/O with explicit UTF-8 and encoding fallback.

Rule 3 (encoding-strategy.md): always pass encoding="utf-8" explicitly.
Rule 4: newline="" preserves existing line endings (don't normalize CRLF→LF).
"""
from __future__ import annotations

from pathlib import Path

from .encoding import read_text_with_fallback


def read_text_safe(path: Path, max_bytes: int = 1_000_000) -> tuple[str, str]:
    """Read a text file safely with encoding fallback.

    Thin wrapper around encoding.read_text_with_fallback. Kept as a public
    API entry point so existing callers don't need to change imports.

    Returns (content, detected_encoding).
    """
    return read_text_with_fallback(path, max_bytes=max_bytes)


def write_text_safe(path: Path, content: str) -> None:
    """Write a text file as UTF-8, preserving existing line endings.

    newline="" disables Python's universal newline translation — this prevents
    accidental CRLF→LF (or vice versa) conversion when the file already has
    consistent line endings.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(content)