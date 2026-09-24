"""telegram-local-bridge — a library for local-process to Telegram bridges.

Public API for safe file I/O, audit logging, path allowlist, approval-based
writes, lockfile-based process supervision, and a watchdog that ties them
all together. Stdlib-only; see README.md and METHODOLOGY.md for the design.
"""
from .encoding import (
    force_utf8_stdout,
    html_escape,
    code_block,
    read_text_with_fallback,
)
from .safe_io import read_text_safe, write_text_safe
from .audit import audit_log, cleanup_old_audit_logs, AuditConfig
from .approval import (
    approval_token,
    save_pending_approval,
    load_pending_approval,
    consume_pending_approval,
)
from .config import (
    load_config,
    is_path_allowed,
    write_default_config,
    default_config,
)
from .lockfile import (
    write_lockfile,
    read_lockfile,
    pid_alive,
    LockfileData,
)
from .watchdog import (
    file_hash,
    load_state,
    save_state,
    Watchdog,
    WatchdogConfig,
)

__version__ = "0.1.0"

__all__ = [
    # encoding
    "force_utf8_stdout",
    "html_escape",
    "code_block",
    "read_text_with_fallback",
    # safe_io
    "read_text_safe",
    "write_text_safe",
    # audit
    "audit_log",
    "cleanup_old_audit_logs",
    "AuditConfig",
    # approval
    "approval_token",
    "save_pending_approval",
    "load_pending_approval",
    "consume_pending_approval",
    # config
    "load_config",
    "is_path_allowed",
    "write_default_config",
    "default_config",
    # lockfile
    "write_lockfile",
    "read_lockfile",
    "pid_alive",
    "LockfileData",
    # watchdog
    "file_hash",
    "load_state",
    "save_state",
    "Watchdog",
    "WatchdogConfig",
]