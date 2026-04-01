"""
Database models — 4 core tables for paper trading persistence.

Designed for:
  1. Paper trade audit trail
  2. Dashboard analytics
  3. Future RL training data (state/action/reward tuples)

Tables:
  trades          — every entry/exit with full context
  daily_snapshots — portfolio state each day
  stock_scores    — daily ranking for all stocks (RL action space)
  regime_history  — every regime transition
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Trade(Base):
    """Every entry/exit — the core audit trail.

    For RL: each row is a (state, action, reward) tuple.
      state  = entry_score + regime + ret_5d
      action = BUY
      reward = net_pnl
    """

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    engine = Column(String(20), nullable=False)         # 'largecap' | 'midcap'
    symbol = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)

    # Entry
    entry_price = Column(Float, nullable=False)
    entry_date = Column(Date, nullable=False)
    entry_score = Column(Float)                         # reversal rank at entry
    ret_5d_at_entry = Column(Float)                     # how much stock had fallen
    ret_today_at_entry = Column(Float)                  # intraday return at entry
    entry_cost = Column(Float)

    # Exit (null while open)
    exit_price = Column(Float)
    exit_date = Column(Date)
    exit_cost = Column(Float)
    hold_days = Column(Integer)
    exit_reason = Column(String(30))                    # 'hold_complete' | 'kill_switch'

    # P&L
    gross_pnl = Column(Float)
    net_pnl = Column(Float)
    pnl_pct = Column(Float)

    # Context
    regime_at_entry = Column(String(10))                # 'BULL' | 'NEUTRAL' | 'WEAK'
    regime_at_exit = Column(String(10))
    status = Column(String(10), default="open")         # 'open' | 'closed'
    decision_reason = Column(Text)                      # e.g. "rank_1, regime_neutral"
    system_version = Column(String(20), default="v1")
    experiment_tag = Column(String(50))                 # for A/B testing

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_trades_engine", "engine"),
        Index("idx_trades_symbol", "symbol"),
        Index("idx_trades_entry_date", "entry_date"),
        Index("idx_trades_status", "status"),
    )


class DailySnapshot(Base):
    """Portfolio state each day — the equity curve table."""

    __tablename__ = "daily_snapshots"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True)
    regime = Column(String(10), nullable=False)
    regime_pending = Column(String(10))
    regime_pending_days = Column(Integer, default=0)

    # Portfolio
    total_capital = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    portfolio_value = Column(Float, nullable=False)
    total_pnl = Column(Float, nullable=False)
    total_pnl_pct = Column(Float, nullable=False)

    # Per-engine
    largecap_capital = Column(Float)
    largecap_pnl = Column(Float)
    largecap_open_pos = Column(Integer)
    largecap_active = Column(Boolean)
    midcap_capital = Column(Float)
    midcap_pnl = Column(Float)
    midcap_open_pos = Column(Integer)
    midcap_active = Column(Boolean)

    # Signals
    rolling_ic = Column(Float)
    rolling_wr_20 = Column(Float)
    kill_switch = Column(Boolean, default=False)

    # Market context
    nifty_close = Column(Float)
    nifty_change_1d = Column(Float)
    nifty_change_5d = Column(Float)
    breadth_pct = Column(Float)

    # Actions
    entries_count = Column(Integer, default=0)
    exits_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)

    system_version = Column(String(20), default="v1")
    created_at = Column(DateTime, server_default=func.now())


class StockScore(Base):
    """Daily ranking for every stock — the RL action space.

    Captures what the system COULD have picked, not just what it did.
    Critical for counterfactual analysis and RL training.
    """

    __tablename__ = "stock_scores"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    symbol = Column(String(20), nullable=False)
    engine = Column(String(20), nullable=False)

    # Raw returns at ranking time
    ret_1d = Column(Float)
    ret_5d = Column(Float)
    ret_10d = Column(Float)
    ret_21d = Column(Float)

    # Computed score
    reversal_score = Column(Float)      # composite rank (0-1)
    rank_in_universe = Column(Integer)  # 1 = most oversold
    universe_size = Column(Integer)

    # Decision made
    selected = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    skip_reason = Column(String(100))   # 'today_drop_limit' | 'already_held'

    # Outcome (filled after hold period)
    fwd_return_5d = Column(Float)

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", "symbol", "engine", name="uq_score_date_symbol_engine"),
        Index("idx_scores_date", "date"),
        Index("idx_scores_symbol", "symbol"),
    )


class PredictionRecord(Base):
    """Persisted ML predictions — survives restarts, enables historical analysis."""

    __tablename__ = "prediction_records"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)  # UP, DOWN, NEUTRAL
    probability = Column(Float)
    confidence = Column(Float)
    prob_up = Column(Float)
    prob_down = Column(Float)
    prob_neutral = Column(Float)
    should_trade = Column(Boolean)
    cycle_id = Column(Integer)  # which execution cycle
    source = Column(String(10), default="bot")  # 'bot' or 'manual'
    session_id = Column(String(30))  # groups predictions from one generation run
    timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_pred_timestamp", "timestamp"),
        Index("idx_pred_session", "session_id"),
        Index("idx_pred_symbol", "symbol"),
    )


class IntraTrade(Base):
    """Intraday bot trades — persisted across container restarts."""

    __tablename__ = "intra_trades"

    id = Column(Integer, primary_key=True)
    trade_id = Column(String(30), unique=True, nullable=False)
    order_id = Column(String(30))
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # BUY, SELL, SHORT, COVER
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    success = Column(Boolean, default=True)
    message = Column(String(200))
    session_date = Column(Date, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_intra_session_date", "session_date"),
        Index("idx_intra_symbol", "symbol"),
    )


class RegimeHistory(Base):
    """Every regime transition — audit trail for regime classifier."""

    __tablename__ = "regime_history"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    old_regime = Column(String(10), nullable=False)
    new_regime = Column(String(10), nullable=False)

    # Signals that caused the transition
    nifty_close = Column(Float)
    nifty_vs_dma50 = Column(Float)      # % above/below 50-DMA
    nifty_ret_5d = Column(Float)
    nifty_ret_1d = Column(Float)
    breadth_pct = Column(Float)
    score = Column(Integer)             # raw regime score (-3 to +3)

    trigger = Column(String(20))        # 'persistence' | 'daily_override'

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_regime_date", "date"),
    )
