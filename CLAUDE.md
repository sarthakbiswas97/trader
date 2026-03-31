# Autonomous Trading Agent - Project Context

## Commit Convention
COMPULSARILY, After completing any task or feature, provide a clear one-line commit message following commitlint convention:
`<type>: <description>` where type is one of: `feat`, `fix`, `refactor`, `perf`, `style`, `docs`, `test`, `chore`, `ci`, `security`.

## Project Overview
- **Goal**: Autonomous intraday trading agent for Indian equity markets
- **Broker**: Zerodha Kite Connect API
- **Target**: Y Combinator-ready product for retail traders
- **Stock Universe**: NIFTY 50 (expandable)

---

## Zerodha Kite Connect API Documentation

### Installation
```bash
pip install kiteconnect
```

### Authentication Flow

Kite Connect uses OAuth-style authentication:

1. **User visits login URL**
```python
from kiteconnect import KiteConnect

kite = KiteConnect(api_key="your_api_key")
print(kite.login_url())
# https://kite.zerodha.com/connect/login?v=3&api_key=xxx
```

2. **After login, user is redirected with request_token**
```
http://your_callback_url?request_token=xxx&action=login&status=success
```

3. **Exchange request_token for access_token**
```python
data = kite.generate_session(
    request_token="obtained_request_token",
    api_secret="your_api_secret"
)
access_token = data["access_token"]
kite.set_access_token(access_token)
```

**Note**: Access token expires at 6 AM the next day.

---

### API Headers
```
Authorization: token api_key:access_token
```

---

### Orders API

#### Place Order
```python
order_id = kite.place_order(
    variety="regular",           # regular, amo, co, iceberg, auction
    tradingsymbol="RELIANCE",
    exchange="NSE",              # NSE, BSE, NFO, CDS, BCD, MCX
    transaction_type="BUY",      # BUY, SELL
    quantity=10,
    order_type="MARKET",         # MARKET, LIMIT, SL, SL-M
    product="MIS",               # CNC, NRML, MIS
    validity="DAY",              # DAY, IOC, TTL
    price=None,                  # For LIMIT orders
    trigger_price=None,          # For SL/SL-M orders
    tag="my-order"               # Optional: max 20 chars
)
```

#### Modify Order
```python
kite.modify_order(
    variety="regular",
    order_id="order_id",
    quantity=15,
    price=2500.00,
    order_type="LIMIT"
)
```

#### Cancel Order
```python
kite.cancel_order(variety="regular", order_id="order_id")
```

#### Get Orders
```python
orders = kite.orders()  # All orders for the day
order_history = kite.order_history(order_id="order_id")
```

#### Get Trades
```python
trades = kite.trades()  # All executed trades
order_trades = kite.order_trades(order_id="order_id")
```

---

### Order Types

| Type | Description |
|------|-------------|
| `MARKET` | Execute at current market price |
| `LIMIT` | Execute at specified price |
| `SL` | Stop-loss limit order |
| `SL-M` | Stop-loss market order |

### Product Types

| Type | Description |
|------|-------------|
| `CNC` | Cash & Carry (equity delivery) |
| `MIS` | Margin Intraday Squareoff (auto square-off at 3:20 PM) |
| `NRML` | Normal (F&O overnight positions) |

### Order Varieties

| Variety | Description |
|---------|-------------|
| `regular` | Standard order |
| `amo` | After Market Order |
| `co` | Cover Order (with stop-loss) |
| `iceberg` | Iceberg Order |

### Order Status Values
```
PUT ORDER REQ RECEIVED → VALIDATION PENDING → OPEN PENDING → OPEN → COMPLETE
                                                          ↘ REJECTED
                                                          ↘ CANCELLED
                                                          ↘ TRIGGER PENDING (SL orders)
```

---

### Portfolio API

#### Get Positions
```python
positions = kite.positions()
# Returns: {"net": [...], "day": [...]}
# net = end-of-day positions
# day = intraday positions

# Position fields:
# tradingsymbol, exchange, product, quantity, overnight_quantity
# average_price, last_price, pnl, unrealised, realised
```

#### Get Holdings
```python
holdings = kite.holdings()

# Holding fields:
# tradingsymbol, exchange, isin, quantity, average_price
# last_price, pnl, day_change, day_change_percentage
```

#### Convert Position
```python
kite.convert_position(
    tradingsymbol="RELIANCE",
    exchange="NSE",
    transaction_type="BUY",
    position_type="day",
    quantity=10,
    old_product="MIS",
    new_product="CNC"
)
```

---

### Margins API

#### Get Margins
```python
margins = kite.margins(segment="equity")
# segment: equity, commodity

# Returns:
# available: {cash, collateral, intraday_payin}
# utilised: {debits, exposure, m2m_realised, m2m_unrealised}
# net: total net balance
```

#### Order Margins
```python
order_margins = kite.order_margins([
    {
        "exchange": "NSE",
        "tradingsymbol": "RELIANCE",
        "transaction_type": "BUY",
        "variety": "regular",
        "product": "MIS",
        "order_type": "MARKET",
        "quantity": 10
    }
])
```

---

### Market Quotes API

#### LTP (up to 1000 instruments)
```python
ltp = kite.ltp(["NSE:RELIANCE", "NSE:INFY"])
# {"NSE:RELIANCE": {"instrument_token": xxx, "last_price": 2450.50}}
```

#### OHLC (up to 1000 instruments)
```python
ohlc = kite.ohlc(["NSE:RELIANCE"])
# {"NSE:RELIANCE": {"last_price": 2450, "ohlc": {"open": 2440, "high": 2460, "low": 2435, "close": 2448}}}
```

#### Full Quote (up to 500 instruments)
```python
quote = kite.quote(["NSE:RELIANCE"])
# Includes: ohlc, volume, buy_quantity, sell_quantity, depth (bid/ask)
```

---

### Historical Data API

#### Fetch Historical Candles
```python
from datetime import datetime

candles = kite.historical_data(
    instrument_token=738561,      # Get from instruments()
    from_date=datetime(2025, 1, 1),
    to_date=datetime(2025, 3, 1),
    interval="5minute",           # See intervals below
    continuous=False,             # For F&O continuous data
    oi=False                      # Include open interest
)

# Returns list of dicts:
# [{"date": datetime, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 50000}]
```

#### Intervals
| Interval | Value |
|----------|-------|
| 1 minute | `minute` |
| 3 minutes | `3minute` |
| 5 minutes | `5minute` |
| 10 minutes | `10minute` |
| 15 minutes | `15minute` |
| 30 minutes | `30minute` |
| 1 hour | `60minute` |
| 1 day | `day` |

**Note**: Intraday data available for last 60 days. Daily data available for years.

---

### Instruments

#### Get All Instruments
```python
instruments = kite.instruments(exchange="NSE")
# Returns list of dicts with: instrument_token, tradingsymbol, name, exchange, etc.
```

#### Instrument Fields
| Field | Description |
|-------|-------------|
| `instrument_token` | Unique numeric identifier (use for historical data) |
| `tradingsymbol` | Trading symbol (e.g., RELIANCE) |
| `name` | Full name |
| `exchange` | NSE, BSE, NFO, etc. |
| `segment` | Segment code |
| `lot_size` | Lot size for derivatives |
| `tick_size` | Minimum price movement |

---

### WebSocket Streaming (KiteTicker)

```python
from kiteconnect import KiteTicker

ticker = KiteTicker(api_key="api_key", access_token="access_token")

def on_ticks(ws, ticks):
    for tick in ticks:
        print(f"{tick['instrument_token']}: {tick['last_price']}")

def on_connect(ws, response):
    ws.subscribe([738561, 256265])  # instrument_tokens
    ws.set_mode(ws.MODE_FULL, [738561, 256265])

ticker.on_ticks = on_ticks
ticker.on_connect = on_connect
ticker.connect()  # Blocking
```

#### Tick Modes
| Mode | Data Included |
|------|---------------|
| `MODE_LTP` | Last traded price only |
| `MODE_QUOTE` | LTP + OHLC + volume |
| `MODE_FULL` | All data including depth |

---

### User Profile

```python
profile = kite.profile()
# {"user_id": "XX1234", "user_name": "John", "email": "...", "exchanges": ["NSE", "BSE"]}
```

---

### GTT Orders (Good Till Triggered)

```python
# Create GTT
gtt_id = kite.place_gtt(
    trigger_type="single",        # single, two-leg (OCO)
    tradingsymbol="RELIANCE",
    exchange="NSE",
    trigger_values=[2500],        # Price triggers
    last_price=2450,
    orders=[{
        "transaction_type": "BUY",
        "quantity": 10,
        "price": 2505,
        "order_type": "LIMIT",
        "product": "CNC"
    }]
)

# Get GTT orders
gtts = kite.get_gtts()

# Delete GTT
kite.delete_gtt(trigger_id=gtt_id)
```

---

### Error Handling

```python
from kiteconnect import exceptions

try:
    kite.place_order(...)
except exceptions.TokenException:
    # Access token expired, re-authenticate
    pass
except exceptions.OrderException as e:
    # Order placement failed
    print(e.message)
except exceptions.InputException:
    # Invalid input parameters
    pass
except exceptions.NetworkException:
    # Network error
    pass
except exceptions.GeneralException:
    # Other errors
    pass
```

---

## Feature Engineering

### Base Features (9)
| Feature | Formula | Range |
|---------|---------|-------|
| RSI | EMA-smoothed relative strength (14) | 0-100 |
| MACD | EMA(12) - EMA(26), normalized | normalized |
| MACD Signal | EMA(9) of MACD | normalized |
| MACD Histogram | MACD - Signal | normalized |
| EMA Ratio | Price / EMA(20) | ~0.95-1.05 |
| Volatility | Std dev of returns (20) | 0.001-0.05 |
| Volume Spike | Volume / avg volume (20) | 0.2-3.0 |
| Momentum | (Price - Price[10]) / Price[10] | -0.1 to 0.1 |
| Bollinger Position | Position in bands (20, 2σ) | -1 to 1 |

### Regime Features (5)
| Feature | Formula | Range |
|---------|---------|-------|
| ADX | Average Directional Index (14) | 0-100 |
| ATR | Average True Range (14) | price-based |
| Volatility Regime | Vol percentile over 100 candles | 0-1 |
| Price Acceleration | 2nd derivative of price | ~-0.01 to 0.01 |
| Range Position | Position in 50-candle high/low | -1 to 1 |

### Multi-Timeframe Context (3)
| Feature | Source | Values |
|---------|--------|--------|
| Hourly Trend | 1-hour candles | -1, 0, 1 |
| Daily Trend | Daily candles | -1, 0, 1 |
| Daily Range Position | Today's high/low | 0-1 |

---

## Risk Management Rules

| Rule | Limit | Action |
|------|-------|--------|
| Max position size | 5% of capital | Reject order |
| Max total exposure | 20% | Reject new entries |
| Max daily loss | 3% | Halt trading |
| Max drawdown | 10% | Circuit breaker |
| Trade cooldown | 60 seconds | Queue order |
| Max trades/day | 20 | Halt trading |

---

## Trading Strategy

### Entry Conditions (ALL must pass)
1. Direction == "UP"
2. Confidence >= 60%
3. ADX > 25 (trend exists)
4. Volume Spike > 1.0 (confirms move)
5. Multi-TF alignment (hourly + daily bullish)

### Exit Conditions (ANY triggers exit)
1. Stop-loss hit (ATR × 2 or -3%)
2. Take profit (>= 2%)
3. Reversal signal (DOWN + 55% confidence)
4. Position age > 2 hours
5. Near market close (3:15 PM)

---

## Market Hours (IST)

- **Pre-market**: 9:00 AM - 9:15 AM
- **Market open**: 9:15 AM
- **Market close**: 3:30 PM
- **MIS auto square-off**: 3:20 PM
- **No new entries after**: 3:15 PM

---

## NIFTY 50 Symbols

```
RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, HINDUNILVR, SBIN, BHARTIARTL,
ITC, KOTAKBANK, LT, AXISBANK, BAJFINANCE, ASIANPAINT, MARUTI, TITAN,
SUNPHARMA, ULTRACEMCO, NESTLEIND, WIPRO, HCLTECH, TATAMOTORS, POWERGRID,
NTPC, TECHM, M&M, BAJAJFINSV, ONGC, ADANIENT, ADANIPORTS, COALINDIA,
JSWSTEEL, TATASTEEL, GRASIM, INDUSINDBK, BRITANNIA, CIPLA, DRREDDY,
DIVISLAB, EICHERMOT, HEROMOTOCO, BPCL, APOLLOHOSP, SBILIFE, TATACONSUM,
HINDALCO, LTIM, BAJAJ-AUTO, SHRIRAMFIN, TRENT
```

---

## Quick Reference

### Typical Intraday Order Flow
```python
from kiteconnect import KiteConnect

kite = KiteConnect(api_key="xxx")
kite.set_access_token("access_token")

# Buy
order_id = kite.place_order(
    variety="regular",
    tradingsymbol="RELIANCE",
    exchange="NSE",
    transaction_type="BUY",
    quantity=10,
    order_type="MARKET",
    product="MIS"
)

# Check position
positions = kite.positions()

# Sell (square off)
kite.place_order(
    variety="regular",
    tradingsymbol="RELIANCE",
    exchange="NSE",
    transaction_type="SELL",
    quantity=10,
    order_type="MARKET",
    product="MIS"
)
```

### Get Current State
```python
# Available capital
margins = kite.margins(segment="equity")
available = margins["available"]["cash"]

# Open positions
positions = kite.positions()["net"]

# Current price
ltp = kite.ltp(["NSE:RELIANCE"])["NSE:RELIANCE"]["last_price"]
```

### Live Price Updates
```python
from kiteconnect import KiteTicker

ticker = KiteTicker("api_key", "access_token")

def on_ticks(ws, ticks):
    for tick in ticks:
        print(tick["last_price"])

def on_connect(ws, response):
    ws.subscribe([738561])  # RELIANCE instrument_token
    ws.set_mode(ws.MODE_LTP, [738561])

ticker.on_ticks = on_ticks
ticker.on_connect = on_connect
ticker.connect()
```
