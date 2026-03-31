# Trading System — Dashboard

Web dashboard for monitoring the autonomous trading system.

## Pages

| Page | Path | Description |
|------|------|-------------|
| Research | `/` | System overview, version history, research journey |
| Dashboard | `/dashboard` | Live portfolio, regime status, multi-engine metrics |
| Positions | `/positions` | Open positions + trade history |
| Predictions | `/predictions` | ML prediction explorer (streaming) |
| Settings | `/settings` | Bot control, authentication, risk management |

## Quick Start

```bash
# From project root
make dev        # Starts backend (8000) + frontend (3000)
open http://localhost:3000
```

## Key Components

### Dashboard (`/dashboard`)

- **Broker Mode Banner** — Shows connection state:
  - Green: Live market data from Zerodha
  - Yellow: Kite session expired, showing last known data
  - Gray: Connecting to paper trading
- **Multi-Engine Regime Status** — Current regime (Bull/Neutral/Weak), capital allocation bar, per-engine metrics (capital, P&L, win rate), rolling IC, confidence score, capital utilization
- **System Status** — API, broker, model, session, bot health indicators
- **Positions Table** — Live open positions with P&L

### Research Page (`/`)

- System evolution (v1→v4) with return progression
- Research journey — 6 strategies tested, 1 validated
- Core idea explanation
- Capital protection mechanisms
- Live market status
- Historical replay mode

### Auto Paper-Connect

The dashboard auto-connects in paper trading mode on first visit. If the Kite session is expired, it falls back to standalone paper broker — visitors always see a working system.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Backend API URL |

Set in `frontend/.env.local` if backend runs on a different host.

## Tech Stack

- Next.js 16 (App Router)
- Tailwind CSS
- shadcn/ui components
- Lucide icons
- TypeScript

## Development

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000
npm run build   # Production build
```
