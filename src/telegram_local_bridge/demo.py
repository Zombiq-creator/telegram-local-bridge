"""demo.py — see the safety flow without needing a Telegram token.

Walks through:
  1. Load default config (writes TOML on first run)
  2. Demonstrate path allowlist (allow data/, deny .env / .git / secrets.toml)
  3. Generate an approval token for a write
  4. Save pending approval
  5. Simulate user tap on "Approve" button
  6. Atomically consume the approval
  7. Write the file
  8. Log to audit log
  9. Demonstrate lockfile + PID liveness
 10. Show the resulting audit trail

Useful for CI smoke tests, first-time evaluation, demo recordings, and
teaching how the library behaves end-to-end without needing a real
Telegram bot token.

Usage:
    python -m telegram_local_bridge.demo
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from .approval import (
    approval_token,
    consume_pending_approval,
    save_pending_approval,
)
from .audit import AuditConfig, audit_log
from .config import (
    default_config,
    is_path_allowed,
    write_default_config,
)
from .lockfile import LockfileData, pid_alive, read_lockfile, write_lockfile
from .safe_io import write_text_safe


def _safe_rmtree(path: str) -> None:
    """Best-effort cleanup that swallows BaseException (Windows sandbox)."""
    import shutil
    try:
        shutil.rmtree(path, ignore_errors=True)
    except BaseException:
        pass


def main() -> int:
    print("=" * 64)
    print(" telegram-local-bridge demo (no Telegram token required) ")
    print("=" * 64)

    tmp = tempfile.mkdtemp()
    try:
        project_root = Path(tmp) / "demo-project"
        project_root.mkdir()
        state_dir = project_root / "data" / "state"
        state_dir.mkdir(parents=True)

        # Step 1: load default config
        cfg_path = state_dir / "telegram_allowed_paths.toml"
        cfg = default_config(project_root)
        write_default_config(cfg_path, project_root)
        print(f"\n[1] Config written to {cfg_path.relative_to(project_root)}")

        # Step 2: demonstrate path allowlist
        print("\n[2] Path allowlist demo:")
        for test_path, label in [
            (project_root / "data" / "readme.md", "data/readme.md  (should allow)"),
            (project_root / ".env", ".env              (should deny: forbidden)"),
            (project_root / ".git" / "config", ".git/config     (should deny: forbidden)"),
            (project_root / "secrets.toml", "secrets.toml     (should deny: forbidden)"),
        ]:
            ok, reason = is_path_allowed(cfg, test_path, mode="read")
            mark = "OK " if ok and "should allow" in label else (
                "OK " if (not ok) and "should deny" in label else "FAIL"
            )
            print(f"  [{mark}] {label}: {'ALLOW' if ok else 'DENY '} ({reason})")

        # Step 3-7: write-with-approval flow
        print("\n[3-7] Write-with-approval flow:")
        target = project_root / "data" / "notes.md"
        content = "# Demo note\n\nThis file was written via the approval flow.\n"
        tok = approval_token(str(target), content)
        print(f"  [3] Generated approval token: {tok}")

        pending_path = state_dir / "telegram_pending_approvals.json"
        save_pending_approval(
            pending_path, tok,
            chat_id="demo-user", command="write", path=str(target),
            content_preview=content, content_full=content,
        )
        print(f"  [4] Saved pending approval to {pending_path.name}")

        audit_cfg = AuditConfig(log_dir=state_dir, filename_prefix="demo_audit")
        audit_log(audit_cfg, chat_id="demo-user", command="write",
                  result="pending", path=str(target))

        print(f"  [5] Simulating user tap on 'Approve' Inline Keyboard button...")
        entry = consume_pending_approval(pending_path, tok)
        if entry is None:
            print("  [FAIL] Token expired or unknown")
            return 1
        print(f"  [OK ] Approval consumed (token): {entry['command']} for {entry['path']}")

        write_text_safe(target, entry["content_full"])
        print(f"  [6] File written: {target.relative_to(project_root)} "
              f"({len(content)} bytes)")
        audit_log(audit_cfg, chat_id="demo-user", command="write",
                  result="ok", path=str(target),
                  bytes_size=len(content.encode("utf-8")))

        # Step 8: lockfile demo
        print("\n[8] Lockfile + PID liveness demo:")
        lock_path = state_dir / "demo.lock"
        write_lockfile(lock_path, LockfileData(
            terminal_pid=os.getpid(),
            started_at="2026-09-24T12:00:00Z",
        ))
        rd = read_lockfile(lock_path)
        if rd is None:
            print("  [FAIL] Could not read lockfile")
            return 1
        is_alive = pid_alive(rd.terminal_pid)
        print(f"  [OK ] Lockfile read: terminal_pid={rd.terminal_pid}")
        print(f"  [OK ] PID liveness check: pid_alive({rd.terminal_pid}) = {is_alive}")

        # Step 9: show audit trail
        print("\n[9] Audit trail (jsonl):")
        log_files = sorted(state_dir.glob("demo_audit-*.jsonl"))
        if not log_files:
            print("  (no audit log files found)")
            return 1
        for line in log_files[0].read_text(encoding="utf-8").splitlines():
            print(f"  {line}")

        print("\n" + "=" * 64)
        print(" Demo complete. No Telegram token was needed. ")
        print(" To run with a real bot: see examples/01_minimal_read_only_bot.py ")
        print("=" * 64)
        return 0
    finally:
        _safe_rmtree(tmp)


if __name__ == "__main__":
    sys.exit(main())