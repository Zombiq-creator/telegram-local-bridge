"""config.py — TOML path-whitelist config loader.

Defines which paths the bot can read or write. Forbidden patterns (e.g.
secrets, .ssh, .env) are always blocked regardless of mode.

The shipped defaults are intentionally conservative: read access is broad
(root + a few typical subdirs); write access is restricted to data/ and
tools/. Forbidden patterns always block secrets, config, .git, and SSH
material. Callers can override by editing the TOML file (or passing a
custom config dict to is_path_allowed).
"""
from __future__ import annotations

import fnmatch
import sys
import tomllib
from pathlib import Path
from typing import Any

from .safe_io import write_text_safe


def default_config(project_root: Path) -> dict[str, Any]:
    """Default allowlist rooted at the caller's project directory.

    Read access is broad (root + a few typical subdirs); write access is
    restricted to data/ and tools/. Forbidden patterns always block secrets,
    config, .git, and SSH material.
    """
    root = str(project_root).replace("\\", "/")
    return {
        "read": {
            "allowed_roots": [
                root,
                f"{root}/scripts",
                f"{root}/tools",
                f"{root}/templates",
                f"{root}/docs",
                f"{root}/data",
            ]
        },
        "write": {
            "allowed_roots": [
                f"{root}/scripts",
                f"{root}/tools",
                f"{root}/templates",
                f"{root}/data",
            ]
        },
        "forbidden_paths": {
            "always_forbidden": [
                "**/.git/**",
                "**/.env",
                "**/.env.*",
                "**/secrets.toml",
                "**/secret.toml",
                "**/api_keys*",
                "**/auth.txt",
                "**/.ssh/**",
            ]
        },
    }


def load_config(config_path: Path, project_root: Path) -> dict[str, Any]:
    """Load TOML config. If missing, write defaults and return them.

    Rule 7 (encoding-strategy.md): TOML is UTF-8 (Python 3.11+ tomllib).
    """
    if not config_path.exists():
        write_default_config(config_path, project_root)
        return default_config(project_root)

    try:
        with config_path.open("rb") as f:
            return tomllib.load(f)
    except Exception as e:
        print(
            f"[telegram_local_bridge.config] config load failed: {e}; using defaults",
            file=sys.stderr,
        )
        return default_config(project_root)


def write_default_config(config_path: Path, project_root: Path) -> None:
    """Write an initial config with the standard defaults."""
    cfg = default_config(project_root)
    lines = [
        "# Telegram bot — path whitelist (configurable).",
        "# Edit and reload (or restart) to apply changes.",
        "# Encoding: UTF-8 no-BOM.",
        "",
        "[read]",
        "allowed_roots = [",
    ]
    for r in cfg["read"]["allowed_roots"]:
        lines.append(f'    "{r}",')
    lines.append("]")
    lines.append("")
    lines.append("[write]")
    lines.append("allowed_roots = [")
    for r in cfg["write"]["allowed_roots"]:
        lines.append(f'    "{r}",')
    lines.append("]")
    lines.append("")
    lines.append("[forbidden_paths]")
    lines.append("always_forbidden = [")
    for p in cfg["forbidden_paths"]["always_forbidden"]:
        lines.append(f'    "{p}",')
    lines.append("]")
    lines.append("")
    write_text_safe(config_path, "\n".join(lines))


def is_path_allowed(config: dict[str, Any], path: Path, mode: str = "read") -> tuple[bool, str]:
    """Check if `path` is allowed for `mode` ('read' | 'write').

    Returns (allowed, reason). Forbidden patterns take precedence over
    allowed_roots.
    """
    path = Path(path).resolve()
    path_str = str(path).replace("\\", "/")

    forbidden = config.get("forbidden_paths", {}).get("always_forbidden", [])
    for pattern in forbidden:
        norm_pattern = pattern.replace("\\", "/")
        if norm_pattern.startswith("**/"):
            suffix = norm_pattern[3:]
            if suffix.endswith("/**"):
                dir_name = suffix[:-3]
                parts = path.parts
                if dir_name in parts:
                    return False, f"forbidden dir: {dir_name}"
                continue
            if fnmatch.fnmatch(path_str, norm_pattern):
                return False, f"forbidden by pattern: {pattern}"
            continue
        if fnmatch.fnmatch(path_str, norm_pattern):
            return False, f"forbidden by pattern: {pattern}"

    allowed_roots = config.get(mode, {}).get("allowed_roots", [])
    for root_str in allowed_roots:
        root_str_norm = root_str.replace("\\", "/").rstrip("/")
        if path_str == root_str_norm or path_str.startswith(root_str_norm + "/"):
            return True, f"allowed via {root_str}"

    return False, f"path not in {mode}.allowed_roots"