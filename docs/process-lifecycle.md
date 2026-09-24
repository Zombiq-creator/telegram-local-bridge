# process-lifecycle.md — daemon spawn, detached windows, log capture

How the library starts and supervises subprocesses.

## The two-process model

A typical deployment has two long-running Python processes:

1. **The bot** — long-polls Telegram, handles commands, writes files.
2. **The watchdog** — checks every N seconds that the bot is alive;
   restarts if not.

The bot is what the user interacts with. The watchdog is invisible until
something goes wrong.

## Why two processes?

If the bot is single-process and hangs on a syscall (e.g. network call to
Telegram), nothing else can monitor it. The watchdog must be a separate
process to be able to kill a hung bot.

## Spawning the bot

```python
proc = subprocess.Popen(
    [python_executable, "-u", terminal_script],
    cwd=project_root,
    stdin=subprocess.DEVNULL,
    stdout=open(log_path, "ab"),
    stderr=open(err_log_path, "ab"),
    creationflags=(
        subprocess.DETACHED_PROCESS  # no console
        | subprocess.CREATE_NO_WINDOW  # no flashing window
    ),
)
```

On Windows:

- `DETACHED_PROCESS` (0x00000008) — the bot runs independent of the
  watchdog's lifetime. When the watchdog exits, the bot keeps running.
- `CREATE_NO_WINDOW` (0x08000000) — no console window is created, even
  briefly. Without this, every restart causes a 1-2 second console flash
  on Windows.

On Unix:

- `start_new_session=True` replaces the Windows flags. Puts the bot in
  a new session and process group, detached from the watchdog.

## `-u` for unbuffered I/O

`python -u` runs Python with unbuffered stdout/stderr. Without it, the bot
might buffer its log output until it exits — which defeats the point of
having a log file you can tail.

## Log capture

stdout and stderr go to separate log files:

```
data/logs/bot.log         # stdout — normal operation
data/logs/bot.err.log     # stderr — exceptions, audit failures
```

Why two files? Because you almost always care about stderr first; tailing
just `bot.err.log` gives you a noise-free view of what went wrong.

## PID liveness

```python
def pid_alive(pid: int | None) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # PID exists but owned by another user
    except OSError:
        return False
    return True
```

Works on Unix and Windows. On Windows, `os.kill` is a thin wrapper over
`TerminateProcess` semantics for signal 0.

## Restart policy

The watchdog restarts the bot when:

- The lockfile is missing or its PID is dead.
- The bot's source file hash has changed since the last successful run.

It does **not** restart on:

- Bot returned non-zero exit code (might be intentional — `sys.exit(2)`
  for "bad config").
- Bot logged an error (errors are normal, not reasons to restart).

If the bot fails to start 5 times in a row, the watchdog gives up and
logs "restart loop detected — manual intervention required". This
prevents a crashloop from burning CPU.

## Clean shutdown

The bot removes its lockfile on `SIGTERM` / `SIGINT` / clean `sys.exit()`.
The watchdog reads the lockfile; if it's gone, it knows the bot exited
cleanly (and won't restart unless the source hash changed).

If the lockfile is gone and the PID is dead but the source hash is the
same, the watchdog does **not** restart. This prevents accidental restart
loops when you Ctrl-C the bot to debug.

## Process tree on Windows

Windows process trees are weird: `taskkill /F /PID <watchdog_pid>` does
**not** kill the bot, because the bot was spawned with
`DETACHED_PROCESS`. To kill the whole tree:

```cmd
taskkill /F /IM python.exe /T
```

The `/T` flag kills the process and all its children. Use this for
emergency shutdown.

On Unix, `kill -TERM -<watchdog_pgid>` (negative PID = process group)
does the same thing because we used `start_new_session=True`.

## When to graduate from this

If you find yourself needing:

- Resource limits (CPU, memory, file descriptors)
- Log rotation
- Per-process metrics
- Crash dumps on non-zero exit

…wrap the watchdog in `nssm` (Windows) or a systemd unit (Linux). This
library's `Watchdog` becomes the in-process layer; the OS service becomes
the boot-survival layer.