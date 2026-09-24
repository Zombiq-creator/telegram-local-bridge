"""Smoke test for telegram_local_bridge. Run with: python tests/test_smoke.py"""
import sys
from pathlib import Path

# Add src to path (when running from tools/telegram-local-bridge/)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import telegram_local_bridge as t  # noqa: E402
from telegram_local_bridge.audit import AuditConfig  # noqa: E402


def test_encoding():
    assert t.html_escape("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
    block = t.code_block("x" * 100, max_chars=50)
    assert block.startswith("<code>") and "truncated" in block


def test_approval_token():
    tok = t.approval_token("/etc/passwd", "evil")
    assert len(tok) == 16 and all(c in "0123456789abcdef" for c in tok)


def _safe_rmtree(path: str) -> None:
    """Best-effort cleanup that swallows KeyboardInterrupt (Windows sandbox)."""
    import shutil
    try:
        shutil.rmtree(path, ignore_errors=True)
    except BaseException:
        pass  # OS will clean /tmp eventually


def test_config():
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        root = Path(tmp)
        cfg = t.load_config(root / "cfg.toml", root)
        ok, _ = t.is_path_allowed(cfg, root / "data" / "test.txt", "read")
        assert ok, "data/ must be readable"
        ok, _ = t.is_path_allowed(cfg, root / ".env", "read")
        assert not ok, ".env must be forbidden"
    finally:
        _safe_rmtree(tmp)
    print("config smoke OK")


def test_audit():
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        cfg = AuditConfig(log_dir=Path(tmp))
        t.audit_log(cfg, chat_id="test", command="read", result="ok", path="/x")
        assert t.cleanup_old_audit_logs(cfg) == 0
    finally:
        _safe_rmtree(tmp)
    print("audit smoke OK")


def test_lockfile():
    import os
    import tempfile
    lf = t.LockfileData(terminal_pid=os.getpid())
    tmp = tempfile.mkdtemp()
    try:
        p = Path(tmp) / "bot.lock"
        t.write_lockfile(p, lf)
        rd = t.read_lockfile(p)
        assert rd is not None and rd.terminal_pid == os.getpid()
        assert t.pid_alive(os.getpid()) is True
        assert t.pid_alive(99999999) is False
    finally:
        _safe_rmtree(tmp)
    print("lockfile smoke OK")


def test_read_text_with_fallback():
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        p = Path(tmp) / "utf8.txt"
        p.write_bytes("hello \u00ff\n".encode("utf-8"))
        content, enc = t.read_text_with_fallback(p)
        assert enc == "utf-8" and "hello" in content
    finally:
        _safe_rmtree(tmp)
    print("read_text smoke OK")


if __name__ == "__main__":
    tests = [
        test_encoding,
        test_approval_token,
        test_config,
        test_audit,
        test_lockfile,
        test_read_text_with_fallback,
    ]
    for fn in tests:
        try:
            fn()
        except BaseException as e:
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(1)
    public_count = len([n for n in dir(t) if not n.startswith("_")])
    print(f"ALL SMOKE TESTS PASSED - v{t.__version__}, {public_count} public symbols")