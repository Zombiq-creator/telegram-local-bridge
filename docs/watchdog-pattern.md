# watchdog-pattern.md — lockfile, PID liveness, file-hash detection

The watchdog supervises the bot. Without it, a bot that dies at 3 AM stays
dead until you notice.

## Why not just use systemd / Docker / supervisord?

You can. The library's `watchdog.py` is the **in-process** layer; it
coexists with whatever the OS provides. The trade-offs:

| Approach | Pros | Cons |
|---|---|---|
| OS service manager (systemd, nssm) | Resource limits, logging, restart on boot | Heavy; configuration in a different language |
| Container orchestrator (k8s, Docker Compose) | Portable, declarative | Massive overkill for a single-user bot |
| This library's `Watchdog` | In-process, no extra deps, knows about the lockfile | No resource limits, no log rotation |

The recommended deployment is **both**: an OS service that starts the
watchdog on boot, and the watchdog that supervises the bot. If the watchdog
itself dies, the OS restarts it. If the bot dies, the watchdog restarts it.

## The lockfile

The bot writes a JSON lockfile on startup:

```json
{
  "terminal_pid": 12345,
  "daemon_pid": null,
  "started_at": "2026-09-24T12:00:00Z",
  "version": "0.1.0"
}
```

It removes the file on clean shutdown (Ctrl-C, SIGTERM). The watchdog reads
the lockfile and checks `os.kill(pid, 0)` to confirm the PID is still alive.

Atomic write via `os.replace(tmp, path)` — partial writes never appear as
valid JSON.

## PID liveness

```python
def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False  # PID doesn't exist
    except PermissionError:
        return True   # PID exists but we don't own it — count as alive
    except OSError:
        return False
    return True
```

`os.kill(pid, 0)` sends no signal but performs the existence + permission
check. Cross-platform (Unix and Windows).

## Why not "is any pythonw.exe running"?

The naive heuristic (`tasklist /FI "IMAGENAME eq pythonw.exe"`) will
false-positive on the watchdog itself, because the watchdog is also a
`pythonw.exe`. We hit this in production: the bot died, the watchdog's own
process showed up as "bot", and nothing got restarted.

The lockfile eliminates the ambiguity: the watchdog knows the exact PID to
check, and only that PID counts.

## File-hash detection

The watchdog computes `sha256(terminal_script)[:16]` every tick. If it
differs from the hash in `state.json`, the source changed — restart to
pick up the patch.

Why? Because long-running bots don't reload their code automatically. If
you `git pull` and your bot doesn't restart, you ship the new code to
disk but the running process is still using the old bytecode.

Trade-offs:

- 16 hex chars = 64 bits of SHA-256. Collision probability is negligible.
- Only the entry-point script is hashed, not all dependencies. If you
  change a library the bot imports, the watchdog won't notice — restart
  manually or extend the watchdog to hash more files.
- Hashing is fast (<1 ms for a typical bot script) so it can run every
  tick.

## Cross-platform restart

```python
if sys.platform == "win32":
    creationflags = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NO_WINDOW
    )
else:
    start_new_session = True  # detach from controlling terminal
```

On Windows, `DETACHED_PROCESS | CREATE_NO_WINDOW` ensures the bot runs
without a console window and independent of the watchdog's lifetime.

On Unix, `start_new_session=True` puts the bot in a new process group so
it survives the watchdog exiting.

In both cases, stdout/stderr are redirected to a log file so you can
debug from your phone.

## Tick interval

Default 60 seconds. Lower means faster restart after death; higher means
less idle CPU. For a single-user bot, 30-60s is fine.

## State persistence

The watchdog keeps its `state.json` (last seen hashes, last restart
timestamp) in `{project_root}/data/state/bot_watchdog_state.json`. If the
watchdog itself restarts, it picks up where it left off.

Important: the watchdog does **not** save state if a restart attempt
failed (lockfile missing or PID still dead). This prevents a "stuck bad"
state where the watchdog keeps thinking everything is fine.