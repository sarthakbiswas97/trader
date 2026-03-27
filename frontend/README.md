# Trading Bot — Dashboard Guide

Web dashboard for monitoring and controlling the ML-powered autonomous trading bot.

---

## Quick Start

```bash
# From the project root (trader/)

# 1. Authenticate with Zerodha (once per day)
make auth

# 2. Start both backend + frontend
make dev

# 3. Open in browser
open http://localhost:3000
```

---

## Getting Started (First Time)

### 1. Install Everything

```bash
make install
```

This sets up both the Python backend and the Next.js frontend.

### 2. Set Your Credentials

Create a `.env` file in the project root:

```
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
```

You get these from the [Kite Connect Developer Console](https://developers.kite.trade) (requires ₹500+GST/month subscription). Set the redirect URL to `http://127.0.0.1:5000` in the developer console.

### 3. Authenticate with Zerodha

```bash
make auth
```

This opens your browser. Login with your Zerodha credentials and TOTP. The token is saved automatically and is valid until 6 AM the next day.

### 4. Start the Dashboard

```bash
make dev
```

This starts:
- Backend API on `http://127.0.0.1:8000`
- Frontend on `http://localhost:3000`

Open `http://localhost:3000` in your browser.

---

## Daily Workflow

Zerodha tokens expire daily at 6 AM. Each trading day:

```bash
make auth    # Login to Zerodha (30 seconds)
make dev     # Start the servers
```

Then use the dashboard for everything else.

---

## Dashboard Pages

### Dashboard (`/`)

The main overview page. Shows everything at a glance.

**What you see:**
- **Connection Banner** — Yellow banner at the top if the broker isn't connected. Click **Connect** to connect in paper trading mode (virtual money, real market prices).
- **Stats Cards** — Total capital, total P&L, number of open positions, bot cycle count.
- **Open Positions Table** — Every position the bot has taken, with symbol, quantity, average price, current price, and live P&L.
- **System Status Panel** — Health of each component: API, broker connection, ML model, session validity, bot status. Green dot = healthy.

**Auto-refresh:** Data updates every 5–10 seconds automatically. Click the refresh icon (top right) to force an immediate update.

---

### Settings (`/settings`)

Control center for the bot. This is where you start/stop trading.

#### Connecting to Zerodha

1. Under **Zerodha Authentication**, click **Connect (Paper Mode)**
2. If your session is valid (you ran `make auth` today), it connects instantly
3. Badge changes from "Disconnected" to "Connected"

To disconnect, click **Disconnect**. The bot must be stopped first.

#### Starting the Bot

1. Click **Start Bot**
2. The system checks if an ML model is ready:
   - **Model exists and is fresh (< 7 days)?** — Bot starts immediately
   - **Model missing or stale?** — The pipeline runs automatically:

```
Step 1: Download Data        — Fetches 60 days of candles from Zerodha (~2 min)
Step 2: Generate Features    — Computes 17 technical indicators (~10 sec)
Step 3: Train Model          — Trains XGBoost with decay weighting (~30 sec)
```

A progress indicator shows each step in real-time. Once complete, the bot starts automatically.

3. Once running, the bot executes a cycle every 5 minutes:
   - Fetches the latest 5-minute candles
   - Generates ML predictions for each stock
   - Checks exit conditions for existing positions (stop-loss at -2%, take-profit at +2%, signal reversal, market close)
   - Ranks UP signals by confidence
   - Executes paper trades for the strongest signals

#### Stopping the Bot

- **Stop Bot** — Stops the trading loop. Open positions stay open.
- **Square Off All** — Closes all open positions immediately. Use this before market close or in an emergency. Asks for confirmation before executing.

#### Risk Management

The bottom card shows the hard risk limits the bot enforces. These cannot be bypassed:

| Rule | Limit | What Happens |
|------|-------|--------------|
| Max position size | 5% of capital | Rejects orders larger than this |
| Max total exposure | 20% of capital | No new entries once exposure hits 20% |
| Max daily loss | 3% of capital | Circuit breaker triggers — all trading halts |
| Max drawdown | 10% from peak | Circuit breaker triggers — all trading halts |
| Trade cooldown | 60 seconds | Queues orders placed within 60s of each other |
| Max trades/day | 20 | No new trades after 20 in a single day |

When the bot is running, live risk metrics appear: trades today, daily P&L, current exposure, and risk score.

---

### Positions (`/positions`)

Detailed view of positions and trade history. Two tabs:

#### Open Positions Tab

Shows all positions the bot currently holds:
- **Symbol** — Stock name with a green/red arrow indicating direction
- **Quantity** — Number of shares
- **Avg Price / Current Price** — Entry price vs live market price
- **P&L** — Absolute and percentage profit/loss
- **Entry Reason** — Why the bot entered (e.g., "ML signal (score: 45.2)")

#### Trade History Tab

Shows all completed trades:
- Summary badges: total trades, won, lost, win rate
- Table with symbol, side (BUY/SELL), quantity, price, timestamp, and exit reason

---

### Predictions (`/predictions`)

Explore what the ML model thinks about each stock right now. This page is **independent of the bot** — it's a diagnostic tool.

#### Generating Predictions

1. Click **Generate Predictions**
2. The system fetches the latest 5 days of candle data for 10 stocks
3. Computes features and runs the ML model
4. Takes 15–30 seconds

#### Reading the Results

**Summary cards** show:
- Symbols analyzed
- Number of UP signals / DOWN signals
- Timestamp of generation

**Signal cards** are grouped by direction:

- **UP signals (green)** — Model predicts the stock will rise ≥0.5% in the next 30 minutes
- **DOWN signals (red)** — Model predicts the stock will fall

Each card shows:
- **Probability** — How likely the model thinks the stock goes UP (0-100%). Bar shows this visually.
- **Confidence** — How far the prediction is from 50/50. Higher = more certain. Bar shows this visually.
- **Top Features** — Which technical indicators contributed most to this prediction (e.g., `daily_trend: 0.15`, `adx: 0.09`)
- **Tradeable Signal** badge — Appears when confidence meets the minimum threshold. These are the signals the bot would actually trade on.

---

## Understanding the Numbers

### P&L Colors
- **Green** — Profit
- **Red** — Loss
- **Gray** — Zero / neutral

### Bot Status Badge
- **Running** (green, pulsing dot) — Bot is actively trading
- **Preparing** (yellow, spinner) — Pipeline is running (download/features/training)
- **Stopped** (gray) — Bot is idle

### System Status Indicators
- **Green dot** — Component is healthy
- **Gray dot** — Component is offline or unavailable

---

## Keyboard Shortcuts

The dashboard is mouse-driven. Use the top navbar to navigate between pages.

---

## Troubleshooting

### "Broker Not Connected" won't go away
Your Zerodha session has expired. Run `make auth` in the terminal, then click **Connect** again.

### "Start Bot" does nothing
Make sure you're connected to the broker first (Settings → Connect). The button is disabled when disconnected.

### Pipeline fails at "Download Data"
The market may be closed or your session expired. Check the terminal running the backend for detailed error logs.

### Predictions take too long
Each symbol requires an API call to Zerodha (rate limited to 3/sec). 10 symbols takes ~15 seconds. This is normal.

### Dashboard shows stale data
Click the refresh icon in the top-right corner. Data auto-refreshes every 5–10 seconds, but polling may pause if the browser tab is inactive.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Backend API base URL |

Set this in `frontend/.env.local` if your backend runs on a different host/port.
