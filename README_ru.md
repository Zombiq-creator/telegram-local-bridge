<div align="center">

# telegram-local-bridge

**Запустите процесс на своей машине. Управляйте им из Telegram. Safe I/O, audit log, одобрение через Inline Keyboard, watchdog-супервизия. Stdlib-only.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Dependencies](https://img.shields.io/badge/dependencies-stdlib--only-success.svg)](#-stdlib-only)
[![Tests](https://img.shields.io/badge/tests-6%2F6%20passing-brightgreen.svg)](tests/test_smoke.py)
[![Source](https://img.shields.io/badge/source-~700%20lines-blue)](#-measured-proof)

[Quickstart](#-quickstart) · [Demo без Telegram](#-demo-без-telegram-токена) · [METHODOLOGY](METHODOLOGY.md) · [Threat model](docs/THREAT_MODEL.md) · [README in English](README.md)

</div>

![hero](docs/hero.svg)

> **Single-owner бот. Path allowlist по принципу deny-by-default. Audit log. Токены одобрения. Watchdog с fail-closed. Stdlib-only — никакого supply-chain риска для долгоживущих процессов.**

## Зачем это нужно

У вас есть долгоживущий процесс на вашей машине — AI-агент, build watcher, генератор отчётов, персональная автоматизация. Вы хотите управлять им с телефона, в чат-приложении, которое уже открыто, **без публичного доступа через интернет**.

Telegram-боты поддерживают long polling (без публичного webhook), Inline Keyboards (чистый primitive для одобрения) и стоят на каждом телефоне. Этот инструмент недоиспользуется для local-process control.

`python-telegram-bot`, `aiogram`, `LangChain` дают Telegram-примитивы. **Ни один из них не переживает, что ваш бот удалит `/etc/passwd`.** Мы переживаем.

Эта библиотека — дистилляция того, чему мы научились, управляя Telegram-агентом в проде месяцами: encoding safety, path allowlist, audit log, approval flow, watchdog. Stdlib-only, MIT, opinionated.

## Чем мы уникальны

Библиотеки, которая комбинирует все шесть свойств, **не существует** в нашей нише. Каждое свойство частично закрыто конкурентами; ни одно не закрывает все шесть:

| | Telegram | Local control | Safety/audit | Approval | Stdlib-only | **Библиотека** |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `python-telegram-bot` | да | нет | нет | вручную | нет | да |
| `aiogram` | да | нет | нет | вручную | нет | да |
| `LightClaw` | да | да | receipts only | да | нет (3 deps) | нет (продукт) |
| `supervisor` | нет | да | нет | нет | нет | нет |
| `watchdog` (PyPI) | нет | файлы | нет | нет | нет | да |
| `LangChain` | примеры | нет | нет | нет | нет | да |
| **`telegram-local-bridge`** | **да** | **да** | **да** | **да** | **да** | **да** |

Комбинация **библиотека + Telegram + local + safety + approval + supervision + stdlib-only** — это та ниша, которую мы закрываем.

## Как это работает

```
   ┌──────────────┐    poll    ┌─────────────┐
   │ Ваш телефон  │ ─────────► │ Telegram API │
   │ (Telegram)   │ ◄───────── │             │
   └──────────────┘   reply    └──────┬──────┘
                                      │
                              HTTPS │
                                      ▼
                              ┌───────────────┐
                              │ bot.py        │ ──► data/state/   (audit log)
                              │ (ваш код)     │ ──► файлы проекта (через allowlist)
                              └───────┬───────┘
                                      │ lockfile (PID + state)
                                      ▼
                              ┌───────────────┐
                              │ watchdog.py   │ ──► restart при crash / code change
                              └───────────────┘
```

- **`bot.py`** (ваш код) использует библиотеку для чтения/записи файлов, логирования действий, запроса одобрения
- **`watchdog.py`** следит за lockfile + хешем bot.py, рестартит при смерти или изменении кода
- **Telegram** — long-polling транспорт; без webhook, без публичного endpoint

## is / is not

| `telegram-local-bridge` — это | `telegram-local-bridge` — НЕ это |
|---|---|
| Слой безопасности для Telegram-управляемых локальных процессов | Telegram bot framework — используйте `python-telegram-bot` или `aiogram` |
| Stdlib-only, MIT, single-owner | Multi-user бот, hosted service, SDK для плагинов |
| Path allowlist (deny-by-default + forbidden patterns) | Файловый сервер, remote shell или поисковая машина |
| Audit log с дневной UTC ротацией + retention | Семантический поиск, embeddings, векторные хранилища |
| Approval flow через Inline Keyboard + single-use токены | Семантическая система одобрения или prompt-injection детектор |
| Watchdog через lockfile-based PID liveness | OS service manager — используйте `nssm` (Windows) или `systemd` (Linux) |
| Рождён в реальном проде | Выходной прототип — что мы выучили, в `docs/METHODOLOGY.md` |

## Фичи

- **Safe I/O** с UTF-8 → cp1251 fallback и сохранением line endings
- **Audit log** с дневной UTC ротацией и настраиваемым retention (jsonl)
- **Approval flow** через Inline Keyboard с single-use SHA-256 токенами (atomic consumption)
- **Path allowlist** в TOML (deny-by-default, forbidden patterns блокируют secrets/.env/.git)
- **Watchdog supervision** через lockfile + PID liveness (никаких эвристик типа "any pythonw.exe")
- **Stdlib-only** — ни httpx, ни python-telegram-bot, ни транзитивных зависимостей
- **Кросс-платформенный** — Windows (DETACHED_PROCESS + CREATE_NO_WINDOW) и Unix (start_new_session)

## Measured proof (не маркетинговые заявления)

Реальные цифры из этого коммита:

| Метрика | Значение |
|---|---:|
| Строк кода (`src/`) | ~700 |
| Публичных символов | 33 |
| Runtime зависимостей | 0 |
| Тестов проходит | 6 / 6 |
| Размер (`src/` + `tests/`) | ~50 KB |
| Поддерживаемые версии Python | 3.11, 3.12, 3.13 |
| Лицензия | MIT (ваша) |

## Quickstart

```bash
git clone https://github.com/<your-username>/telegram-local-bridge.git
cd telegram-local-bridge
pip install -e .
cp .env.example .env  # заполните TELEGRAM_BOT_TOKEN, OWNER_CHAT_ID

# Запустите минимальный read-only пример
python examples/01_minimal_read_only_bot.py
```

Отправьте `/read README.md` из своего Telegram. Бот ответит содержимым файла (UTF-8 с cp1251 fallback).

## Demo без Telegram-токена

```bash
python -m telegram_local_bridge.demo
```

Прогоняет safety flow без Telegram-credentials: write → approval token → allow/deny → audit log. Полезно для CI, для первой оценки, для записи демонстрации.

## 5-минутный тур по паттернам

| Паттерн | Модуль | Пример |
|---|---|---|
| Безопасное чтение файла с encoding fallback | `safe_io`, `encoding` | [`examples/01_minimal_read_only_bot.py`](examples/01_minimal_read_only_bot.py) |
| Allowlist путей для read/write | `config` | 01, 02 |
| Логирование каждого чтения/записи/denial в jsonl | `audit` | 01, 02, 03 |
| Approval flow через Inline Keyboard | `approval` | [`examples/02_bot_with_approval.py`](examples/02_bot_with_approval.py) |
| Детект смерти бота через lockfile + PID check | `lockfile`, `watchdog` | [`examples/03_bot_with_daemon.py`](examples/03_bot_with_daemon.py) |
| Авто-рестарт при изменении кода или crash | `watchdog` | 03 |

## Honest limits

- **Single-owner.** Один `OWNER_CHAT_ID`, без multi-user. Если нужно — форкайте.
- **Нет webhook.** Только long-polling. Не делаем публичный endpoint.
- **Нет prompt-injection detection.** Одобрение по токену, не семантикой.
- **Нет embeddings / RAG.** Это не search-библиотека. Используйте `pgvector` или `qdrant` если нужно.
- **In-process watchdog.** Для boot-survival комбинируйте с `nssm` (Windows) или `systemd` (Linux).

## Threat model

Полная версия — в [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md). Кратко:

- **Защищаем:** доступ non-owner, replay-атаки на approvals, случайный root-доступ, удаление файлов из-за typos, mojibake-атаки, false-positive watchdog detection, supply-chain риск
- **Не покрываем:** компрометация Telegram-протокола, host privilege escalation, side-channel на серверах Telegram

## Roadmap

- **v0.1.0 (сейчас):** библиотека + примеры + документация + тесты. MIT, stdlib-only.
- **v0.2.0:** опциональные интеграции с `python-telegram-bot` / `aiogram` (тонкие shims, opt-in)
- **v0.3.0:** multi-process supervision (один бот + несколько демонов)
- **v1.0.0:** stable API, полная Windows + Linux CI, semver гарантии

## Лицензия

MIT. См. [`LICENSE`](LICENSE).

## Contributing

Issues и PR приветствуются. Библиотека намеренно тонкая — держите public API компактным.