<div align="center">

# telegram-local-bridge

**Run a process on your machine. Control it from Telegram. Safe I/O, audit log, approval-based writes, watchdog supervision. Stdlib-only.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Dependencies](https://img.shields.io/badge/dependencies-stdlib--only-success.svg)](#-stdlib-only)
[![Tests](https://img.shields.io/badge/tests-6%2F6%20passing-brightgreen.svg)](tests/test_smoke.py)
[![Source](https://img.shields.io/badge/source-~700%20lines-blue)](#-measured-proof)

[Quickstart](#-quickstart) · [Demo without Telegram](#-see-it-work-without-a-telegram-token) · [METHODOLOGY](METHODOLOGY.md) · [Threat model](docs/THREAT_MODEL.md) · [README на русском](README_ru.md)

</div>

![hero](docs/hero.svg)

> **Single-owner bot. Deny-by-default path allowlist. Audit log. Approval tokens. Fail-closed watchdog. Stdlib-only — no supply-chain risk for long-running processes.**

## Why this exists

You have a long-lived process on your machine — an AI agent, a build watcher, a daily report generator, a personal automation. You want to interact with it from your phone, in a chat app you already have open, **without exposing it to the public internet**.

Telegram bots support long polling (no public webhook required), Inline Keyboards (clean approval primitive), and are installed on every phone. They're an underused tool for local-process control.

`python-telegram-bot`, `aiogram`, `LangChain` give you the primitives. **None of them care if your bot deletes `/etc/passwd`.** We do.

This library distills what we learned running a Telegram-controlled AI assistant in production for months: encoding safety, path allowlists, audit logs, approval flows, watchdog supervision. Stdlib-only, MIT, opinionated.

## What makes us unique

A library that combines all six properties **does not exist** in our niche. Each property is partially addressed by competitors; none address all six:

| | Telegram | Local control | Safety/audit | Approval | Stdlib-only | **Library** |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `python-telegram-bot` | yes | no | no | manual | no | yes |
| `aiogram` | yes | no | no | manual | no | yes |
| `LightClaw` | yes | yes | receipts only | yes | no (3 deps) | no (product) |
| `supervisor` | no | yes | no | no | no | no |
| `watchdog` (PyPI) | no | files only | no | no | no | yes |
| `LangChain` | examples | no | no | no | no | yes |
| **`telegram-local-bridge`** | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** |

The combination **library + Telegram + local + safety + approval + supervision + stdlib-only** is the gap we fill.

## How it works

```
   ┌──────────────┐    poll    ┌─────────────┐
   │ Your phone   │ ─────────► │ Telegram API │
   │ (Telegram)   │ ◄───────── │             │
   └──────────────┘   reply    └──────┬──────┘
                                      │
                              HTTPS │
                                      ▼
                              ┌───────────────┐
                              │ bot.py        │ ──► data/state/   (audit log)
                              │ (your code)   │ ──► project files (via allowlist)
                              └───────┬───────┘
                                      │ lockfile (PID + state)
                                      ▼
                              ┌───────────────┐
                              │ watchdog.py   │ ──► restart on crash / code change
                              └───────────────┘
```

- **`bot.py`** (your code) uses the library to read/write files, log actions, request approval
- **`watchdog.py`** watches the lockfile + file-hash of bot.py, restarts on death or code change
- **Telegram** is the long-polling transport — no webhook, no public endpoint

## is / is not

| `telegram-local-bridge` is | `telegram-local-bridge` is not |
|---|---|
| A safety layer for Telegram-controlled local processes | A Telegram bot framework — use `python-telegram-bot` or `aiogram` |
| Stdlib-only, MIT, single-owner | A multi-user bot, a hosted service, an SDK for plugin authors |
| Path allowlist with deny-by-default + forbidden patterns | A file server, a remote shell, or a content search engine |
| Audit log with daily UTC rotation + retention | Semantic search, embeddings, or vector stores |
| Approval flow via Inline Keyboard + single-use tokens | A semantic approval system or a prompt-injection detector |
| Watchdog with lockfile-based PID liveness | An OS service manager — use `nssm` (Windows) or `systemd` (Linux) |
| Born from a real production system | A weekend prototype — see `docs/METHODOLOGY.md` for what we learned |

## Features

- **Safe I/O** with UTF-8 → cp1251 fallback and line-ending preservation
- **Audit log** with daily UTC rotation and configurable retention (jsonl)
- **Approval flow** via Inline Keyboard with single-use SHA-256 tokens (atomic consumption)
- **Path allowlist** in TOML (deny-by-default, forbidden patterns block secrets/.env/.git)
- **Watchdog supervision** with lockfile-based PID liveness (no heuristics like "any pythonw.exe")
- **Stdlib-only** — no httpx, no python-telegram-bot, no transitive deps
- **Cross-platform** — Windows (DETACHED_PROCESS + CREATE_NO_WINDOW) and Unix (start_new_session)

## Measured proof (not blanket claims)

Real numbers from this commit, not marketing:

| Measurement | Value |
|---|---:|
| Source lines (`src/`) | ~700 |
| Public symbols | 33 |
| Runtime dependencies | 0 |
| Test pass rate | 6 / 6 |
| Total bytes (`src/` + `tests/`) | ~50 KB |
| Python versions supported | 3.11, 3.12, 3.13 |
| 3rd-party license | MIT (yours) |

## Quickstart

```bash
git clone https://github.com/<your-username>/telegram-local-bridge.git
cd telegram-local-bridge
pip install -e .
cp .env.example .env  # fill TELEGRAM_BOT_TOKEN, OWNER_CHAT_ID

# Run the minimal read-only example
python examples/01_minimal_read_only_bot.py
```

Send `/read README.md` from your Telegram account. The bot replies with the file content (UTF-8 with cp1251 fallback).

## See it work without a Telegram token

```bash
python -m telegram_local_bridge.demo
```

Walks through the safety flow without any Telegram credentials: write → approval token → allow/deny → audit log entry. Useful for CI, for first-time evaluation, or for sharing a recording of how the library behaves.

## 5-minute tour of the patterns

| Pattern | Module | Example |
|---|---|---|
| Read a file safely with encoding fallback | `safe_io`, `encoding` | [`examples/01_minimal_read_only_bot.py`](examples/01_minimal_read_only_bot.py) |
| Allow only specific paths for read/write | `config` | 01, 02 |
| Log every read/write/denial to jsonl | `audit` | 01, 02, 03 |
| Approval flow via Inline Keyboard | `approval` | [`examples/02_bot_with_approval.py`](examples/02_bot_with_approval.py) |
| Detect bot death via lockfile + PID check | `lockfile`, `watchdog` | [`examples/03_bot_with_daemon.py`](examples/03_bot_with_daemon.py) |
| Auto-restart on code change or crash | `watchdog` | 03 |

## Honest limits

- **Single-owner.** One `OWNER_CHAT_ID`, no multi-user support. If you need it, fork the library.
- **No webhook support.** Long-polling only. We don't expose a public endpoint.
- **No prompt-injection detection.** Approval is by token, not by semantic analysis.
- **No embeddings / RAG.** This is not a search library. Pair with `pgvector` or `qdrant` if you need it.
- **In-process watchdog only.** Pair with `nssm` (Windows) or `systemd` (Linux) for boot-survival.

## Threat model

Read [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) for the full breakdown. Short version:

- **Mitigated:** non-owner chat access, replay attacks on approvals, accidental root access, file deletion by typos, encoding-based mojibake attacks, false-positive watchdog detection, supply-chain risk
- **Out of scope:** Telegram protocol compromise, host privilege escalation, side-channel on the Telegram servers themselves

## Roadmap

- **v0.1.0 (now):** library + examples + docs + tests. MIT, stdlib-only.
- **v0.2.0:** optional integrations with `python-telegram-bot` / `aiogram` (lightweight shims, opt-in)
- **v0.3.0:** multi-process supervision patterns (one bot + multiple daemons)
- **v1.0.0:** stable API, full Windows + Linux CI, semver guarantees

## Per-pattern deep dive

- [`docs/encoding-strategy.md`](docs/encoding-strategy.md) — 10 rules for UTF-8 / cp1251 / HTML
- [`docs/safe-io.md`](docs/safe-io.md) — path allowlist, audit log, line-ending preservation
- [`docs/watchdog-pattern.md`](docs/watchdog-pattern.md) — lockfile vs. heuristics, hash-based code-change detection
- [`docs/approval-flow.md`](docs/approval-flow.md) — single-use tokens, Inline Keyboard, atomic consumption
- [`docs/process-lifecycle.md`](docs/process-lifecycle.md) — daemon spawn, detached windows, log capture

## License

MIT. See [`LICENSE`](LICENSE).

## Contributing

Issues and PRs welcome. The library is intentionally a thin layer over stdlib — keep the public API surface small.