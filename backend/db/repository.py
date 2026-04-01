"""
Data access layer — write and query trading data.

All DB writes go through here. The multi-engine calls these
after each daily cycle to persist everything.
"""

from datetime import date, timedelta

from sqlalchemy import desc, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.core.logger import get_logger
from backend.db.models import (
    DailySnapshot,
    IntraTrade,
    PredictionRecord,
    RegimeHistory,
    StockScore,
    Trade,
)

logger = get_logger(__name__)


class TradeRepository:
    """Read/write trades."""

    def __init__(self, session: Session):
        self.session = session

    def insert_trade(self, **kwargs) -> Trade:
        trade = Trade(**kwargs)
        self.session.add(trade)
        self.session.flush()
        return trade

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        exit_date: date,
        exit_cost: float,
        gross_pnl: float,
        net_pnl: float,
        pnl_pct: float,
        hold_days: int,
        exit_reason: str = "hold_complete",
        regime_at_exit: str = None,
    ):
        trade = self.session.query(Trade).get(trade_id)
        if trade:
            trade.exit_price = exit_price
            trade.exit_date = exit_date
            trade.exit_cost = exit_cost
            trade.gross_pnl = gross_pnl
            trade.net_pnl = net_pnl
            trade.pnl_pct = pnl_pct
            trade.hold_days = hold_days
            trade.exit_reason = exit_reason
            trade.regime_at_exit = regime_at_exit
            trade.status = "closed"

    def get_open_trades(self, engine: str = None) -> list[Trade]:
        q = self.session.query(Trade).filter(Trade.status == "open")
        if engine:
            q = q.filter(Trade.engine == engine)
        return q.all()

    def get_recent_trades(self, limit: int = 20) -> list[Trade]:
        return (
            self.session.query(Trade)
            .filter(Trade.status == "closed")
            .order_by(desc(Trade.exit_date))
            .limit(limit)
            .all()
        )

    def get_trade_stats(self, engine: str = None) -> dict:
        q = self.session.query(Trade).filter(Trade.status == "closed")
        if engine:
            q = q.filter(Trade.engine == engine)

        trades = q.all()
        if not trades:
            return {"total": 0, "wins": 0, "win_rate": 0, "total_pnl": 0}

        wins = sum(1 for t in trades if (t.net_pnl or 0) > 0)
        total_pnl = sum(t.net_pnl or 0 for t in trades)

        return {
            "total": len(trades),
            "wins": wins,
            "win_rate": wins / len(trades) * 100,
            "total_pnl": total_pnl,
        }


class SnapshotRepository:
    """Read/write daily portfolio snapshots."""

    def __init__(self, session: Session):
        self.session = session

    def upsert_snapshot(self, **kwargs):
        """Insert or update snapshot for a date."""
        stmt = pg_insert(DailySnapshot).values(**kwargs)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={k: v for k, v in kwargs.items() if k != "date"},
        )
        self.session.execute(stmt)

    def get_equity_curve(self, days: int = 90) -> list[DailySnapshot]:
        cutoff = date.today() - timedelta(days=days)
        return (
            self.session.query(DailySnapshot)
            .filter(DailySnapshot.date >= cutoff)
            .order_by(DailySnapshot.date)
            .all()
        )

    def get_latest(self) -> DailySnapshot | None:
        return (
            self.session.query(DailySnapshot)
            .order_by(desc(DailySnapshot.date))
            .first()
        )


class ScoreRepository:
    """Read/write daily stock scores (RL action space)."""

    def __init__(self, session: Session):
        self.session = session

    def bulk_insert_scores(self, scores: list[dict]):
        """Insert stock scores for a day. Uses ON CONFLICT to handle re-runs."""
        if not scores:
            return

        for score_data in scores:
            stmt = pg_insert(StockScore).values(**score_data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_score_date_symbol_engine",
                set_={
                    k: v
                    for k, v in score_data.items()
                    if k not in ("date", "symbol", "engine")
                },
            )
            self.session.execute(stmt)

    def update_forward_returns(self, scoring_date: date, returns: dict[str, float]):
        """Fill in fwd_return_5d after the holding period completes."""
        scores = (
            self.session.query(StockScore)
            .filter(StockScore.date == scoring_date)
            .all()
        )
        for score in scores:
            if score.symbol in returns:
                score.fwd_return_5d = returns[score.symbol]


class PredictionRepository:
    """Read/write prediction records."""

    def __init__(self, session: Session):
        self.session = session

    def bulk_insert(self, predictions: list[dict]):
        """Insert a batch of predictions from one cycle."""
        for pred_data in predictions:
            self.session.add(PredictionRecord(**pred_data))
        self.session.flush()

    def get_latest_cycle(self, limit: int = 50) -> list[PredictionRecord]:
        """Get predictions from the most recent cycle."""
        latest = (
            self.session.query(func.max(PredictionRecord.cycle_id)).scalar()
        )
        if latest is None:
            return []
        return (
            self.session.query(PredictionRecord)
            .filter(PredictionRecord.cycle_id == latest)
            .order_by(desc(PredictionRecord.confidence))
            .limit(limit)
            .all()
        )

    def get_recent(self, limit: int = 50) -> list[PredictionRecord]:
        """Get most recent predictions."""
        return (
            self.session.query(PredictionRecord)
            .order_by(desc(PredictionRecord.timestamp))
            .limit(limit)
            .all()
        )


class IntraTradeRepository:
    """Read/write intraday bot trades."""

    def __init__(self, session: Session):
        self.session = session

    def insert_trade(self, **kwargs) -> IntraTrade:
        trade = IntraTrade(**kwargs)
        self.session.add(trade)
        self.session.flush()
        return trade

    def get_trades_for_date(self, session_date: date, limit: int = 200) -> list[IntraTrade]:
        return (
            self.session.query(IntraTrade)
            .filter(IntraTrade.session_date == session_date)
            .order_by(desc(IntraTrade.timestamp))
            .limit(limit)
            .all()
        )

    def get_recent_trades(self, limit: int = 50) -> list[IntraTrade]:
        return (
            self.session.query(IntraTrade)
            .order_by(desc(IntraTrade.timestamp))
            .limit(limit)
            .all()
        )


class RegimeRepository:
    """Read/write regime transitions."""

    def __init__(self, session: Session):
        self.session = session

    def insert_transition(self, **kwargs):
        entry = RegimeHistory(**kwargs)
        self.session.add(entry)

    def get_recent(self, limit: int = 20) -> list[RegimeHistory]:
        return (
            self.session.query(RegimeHistory)
            .order_by(desc(RegimeHistory.date))
            .limit(limit)
            .all()
        )
