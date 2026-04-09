# Ops Layer

Autonomous ops layer for the trader, powered by Claude Code's `/schedule`, `/loop`, and hooks. Strategy code is untouched — this is purely additive monitoring + automation.

## Components

| Layer | Where it lives | What it does |
|---|---|---|
| Helper scripts | `backend/agents/` | Python modules that hit the trader's API and DB |
| Makefile targets | `Makefile` | `ops-health`, `ops-report`, `ops-monitor`, `test` |
| Slash commands | `.claude/commands/` | `/ops-health`, `/ops-report`, `/ops-status` |
| Pre-commit hook | `.claude/hooks/pre-commit.sh` | Runs ruff + pytest before any `git commit` |
| Scheduled agents | Anthropic cloud (registered via `/schedule` and `/loop`) | Run on cron and during market hours |
| Reports | `backend/data/ops_reports/` | Markdown ops trail (gitignored) |

## Helper scripts

All three are invoked from a Python venv and print structured JSON to stdout.

```bash
make ops-health   # python -m backend.agents.health_check
make ops-report   # python -m backend.agents.post_market_report
make ops-monitor  # python -m backend.agents.live_monitor
```

### `health_check`
- Verifies API liveness, Kite session, model, data freshness, bot status.
- **If session expired**: writes `backend/data/ops_reports/morning/AUTH_NEEDED_{date}.md` with instructions, sets `auth_required: true`, and stops. Auth requires the Kite mobile app — never automated.
- Otherwise: triggers `bot/prepare` if data is stale, starts the bot if it isn't running.

### `post_market_report`
- Reads `trades`, `daily_snapshots`, `stock_scores`, `regime_history` from Neon.
- Writes `backend/data/ops_reports/post_market/{date}.md` with capital, P&L, today's entries/exits, regime transitions, skipped top picks.

### `live_monitor`
- Polls `/api/v1/bot/status`, `/api/v1/bot/risk`.
- Returns `healthy: bool` plus an `alerts` array of: `bot_not_running`, `circuit_breaker_active`, `daily_loss_breach`, `stale_cycles`, `status_unreachable:*`.

## Slash commands

Run any of these inside Claude Code in this repo:
- `/ops-health` — runs `make ops-health` and explains the result
- `/ops-report` — generates today's report and adds an outlook section
- `/ops-status` — quick monitor pass with explanations

## Pre-commit hook

`/Users/sarthakbiswas/projects/ai/trader/.claude/hooks/pre-commit.sh` runs automatically before any `git commit` (configured via `PreToolUse` hook in `.claude/settings.local.json`).

It runs:
1. `ruff check backend/ tests/`
2. `pytest -x -q`

If either fails, the commit is blocked. Skips silently if `backend/.venv/` doesn't exist.

## Scheduled remote agents

These are not committed code. Register them once via `/schedule` and `/loop` inside Claude Code. Anthropic runs them on its cloud.

### 1. Morning Health Agent

```
/schedule
  cron: 30 3 * * 1-5    # 9:00 AM IST, weekdays
  prompt: |
    Run `make ops-health` in /Users/sarthakbiswas/projects/ai/trader.
    If `auth_required: true`, the script has already written an AUTH_NEEDED
    file — confirm it exists and stop. Auth needs the Kite mobile app — do
    NOT try to automate it. If `ok: false` for other reasons, diagnose using
    the `issues` array. If data stale, the script triggers a refresh — wait
    and verify. If bot failed to start, read recent logs from
    `backend/data/` and report root cause. Append a one-line status to
    `backend/data/ops_reports/morning/{today}.md`.
```

### 2. Post-Market Analyzer

```
/schedule
  cron: 5 10 * * 1-5    # 3:35 PM IST, weekdays
  prompt: |
    Run `make ops-report`. Read the generated markdown at
    `backend/data/ops_reports/post_market/{today}.md`. If realized P&L is
    negative beyond ₹1000, identify which positions caused it. If any kill
    switches fired, note the trigger. If a regime transition happened, note
    the cause. Append a brief 'Tomorrow's outlook' section.
```

### 3. Live Monitor (`/loop`)

```
/loop 5m "Run make ops-monitor in /Users/sarthakbiswas/projects/ai/trader. \
If healthy: do nothing. If alerts: investigate via /api/v1/bot/cycles \
and report root cause. Run only between 9:15 AM and 3:30 PM IST."
```

## Alert reference

| Alert | Meaning | First action |
|---|---|---|
| `bot_not_running` | Execution engine stopped | Check logs, run `/ops-health` to restart |
| `circuit_breaker_active` | Risk guardian tripped | Read circuit_breaker_reason, decide whether to manually reset |
| `daily_loss_breach` | Daily P&L below alert threshold (default 2%) | Review open positions, consider square-off |
| `stale_cycles` | Last cycle older than 10 min | Check execution engine for crash |
| `status_unreachable:*` | API endpoint failing | Check container is running, check logs |
| `auth_required` | Kite session expired | Run `make auth` (manual — needs mobile app) |

## Disable / inspect

```bash
# In Claude Code
/schedule list
/schedule delete <id>
```

## Reports location

```
backend/data/ops_reports/
├── morning/
│   ├── 2026-04-09.md
│   └── AUTH_NEEDED_2026-04-09.md   # only when session expired
└── post_market/
    └── 2026-04-09.md
```

These are gitignored — they're operational data, not source code.

## Tests

```bash
make test
```

The `tests/` directory covers the safety-critical paths:
- `test_risk_guardian.py` — position limits, circuit breakers, exit conditions
- `test_regime.py` — classifier mapping + 2-day persistence
- `test_scoring.py` — reversal ranking math
- `test_agents.py` — health_check, live_monitor, report_writer (mocked HTTP)
