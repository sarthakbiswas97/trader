"""
Persistence bridge — connects multi-engine to database.

Called by the multi-engine after each daily cycle to persist:
  - trades (entries and exits)
  - daily snapshot
  - stock scores (full ranking)
  - regime transitions

Designed to be called ALONGSIDE the existing JSON persistence,
so the system works even if the DB is down.
"""

from datetime import date

from sqlalchemy.orm import Session

from backend.core.logger import get_logger
from backend.db.database import get_session
from backend.db.repository import (
    RegimeRepository,
    ScoreRepository,
    SnapshotRepository,
    TradeRepository,
)

logger = get_logger(__name__)

_DB_AVAILABLE = None


def _check_db() -> bool:
    """Check if database is available (cached)."""
    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE

    try:
        from sqlalchemy import text
        from backend.db.database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _DB_AVAILABLE = True
    except Exception:
        _DB_AVAILABLE = False
        logger.warning("Database not available — running without persistence")

    return _DB_AVAILABLE


def persist_daily_cycle(
    result: dict,
    engine_states: dict,
    regime_info: dict,
    total_capital: float = 100_000.0,
):
    """
    Persist a complete daily cycle to the database.

    Args:
        result: The dict returned by MultiEngine.run_daily()
        engine_states: The engine_states dict from MultiEngine
        regime_info: The regime classifier status
        total_capital: Initial capital for P&L calculation
    """
    if not _check_db():
        return

    try:
        with get_session() as session:
            _persist_snapshot(session, result, engine_states, regime_info, total_capital)
            _persist_trades(session, result, engine_states)
            _persist_scores(session, result)

        logger.info("Daily cycle persisted to database")
    except Exception as e:
        logger.error(f"Failed to persist daily cycle: {e}")


def persist_regime_change(
    today: date,
    old_regime: str,
    new_regime: str,
    nifty_close: float = None,
    nifty_vs_dma50: float = None,
    nifty_ret_5d: float = None,
    nifty_ret_1d: float = None,
    breadth_pct: float = None,
    score: int = None,
    trigger: str = "persistence",
):
    """Persist a regime transition."""
    if not _check_db():
        return

    try:
        with get_session() as session:
            repo = RegimeRepository(session)
            repo.insert_transition(
                date=today,
                old_regime=old_regime,
                new_regime=new_regime,
                nifty_close=nifty_close,
                nifty_vs_dma50=nifty_vs_dma50,
                nifty_ret_5d=nifty_ret_5d,
                nifty_ret_1d=nifty_ret_1d,
                breadth_pct=breadth_pct,
                score=score,
                trigger=trigger,
            )
    except Exception as e:
        logger.error(f"Failed to persist regime change: {e}")


def _persist_snapshot(
    session: Session,
    result: dict,
    engine_states: dict,
    regime_info: dict,
    total_capital: float = 100_000.0,
):
    """Write daily snapshot."""
    repo = SnapshotRepository(session)

    largecap = result.get("engines", {}).get("largecap", {})
    midcap = result.get("engines", {}).get("midcap", {})
    portfolio_value = result.get("portfolio_value", total_capital)
    pnl = portfolio_value - total_capital

    repo.upsert_snapshot(
        date=date.fromisoformat(result["date"]),
        regime=result.get("regime", "NEUTRAL"),
        regime_pending=regime_info.get("pending"),
        regime_pending_days=regime_info.get("pending_days", 0),
        total_capital=total_capital,
        cash=result.get("cash", 0),
        portfolio_value=portfolio_value,
        total_pnl=pnl,
        total_pnl_pct=pnl / total_capital * 100 if total_capital > 0 else 0,
        largecap_capital=largecap.get("capital", 0),
        largecap_pnl=largecap.get("pnl", 0),
        largecap_open_pos=largecap.get("open_positions", 0),
        largecap_active=largecap.get("active", False),
        midcap_capital=midcap.get("capital", 0),
        midcap_pnl=midcap.get("pnl", 0),
        midcap_open_pos=midcap.get("open_positions", 0),
        midcap_active=midcap.get("active", False),
        rolling_ic=result.get("rolling_ic"),
        kill_switch=any(
            e.get("action", "").startswith("kill_switch")
            for e in result.get("engines", {}).values()
        ),
        entries_count=sum(
            len(e.get("picks", []))
            for e in result.get("engines", {}).values()
        ),
        exits_count=sum(
            len(e.get("exits", []))
            for e in result.get("engines", {}).values()
        ),
        skipped_count=sum(
            len(e.get("skipped", []))
            for e in result.get("engines", {}).values()
        ),
    )


def _persist_trades(session: Session, result: dict, engine_states: dict):
    """Write new trade entries and exits."""
    repo = TradeRepository(session)
    today = date.fromisoformat(result["date"])
    regime = result.get("regime", "NEUTRAL")

    for engine_name, eng_result in result.get("engines", {}).items():
        # New entries
        for pick in eng_result.get("picks", []):
            repo.insert_trade(
                engine=engine_name,
                symbol=pick["symbol"],
                quantity=1,  # Will be refined
                entry_price=pick.get("price", 0),
                entry_date=today,
                entry_score=pick.get("score"),
                ret_5d_at_entry=pick.get("ret_5d"),
                ret_today_at_entry=pick.get("ret_today"),
                regime_at_entry=regime,
                status="open",
                decision_reason=f"rank_{pick.get('score', 0):.2f}_regime_{regime}",
                system_version="v1",
            )

        # Exits
        for exit_trade in eng_result.get("exits", []):
            # Find matching open trade
            from backend.db.models import Trade as TradeModel
            open_trades = (
                session.query(TradeModel)
                .filter_by(
                    engine=engine_name,
                    symbol=exit_trade["symbol"],
                    status="open",
                )
                .all()
            )
            if open_trades:
                t = open_trades[0]
                entry_val = t.entry_price * (t.quantity or 1)
                pnl_pct = exit_trade["net_pnl"] / entry_val * 100 if entry_val > 0 else 0
                repo.close_trade(
                    trade_id=t.id,
                    exit_price=exit_trade.get("exit_price", 0),
                    exit_date=today,
                    exit_cost=0,
                    gross_pnl=exit_trade.get("net_pnl", 0),
                    net_pnl=exit_trade.get("net_pnl", 0),
                    pnl_pct=pnl_pct,
                    hold_days=exit_trade.get("hold_days", 5),
                    exit_reason="hold_complete",
                    regime_at_exit=regime,
                )


def _persist_scores(session: Session, result: dict):
    """Write stock scores for all ranked stocks."""
    repo = ScoreRepository(session)
    today = date.fromisoformat(result["date"])

    # The picks and skipped lists contain scored stocks
    for engine_name, eng_result in result.get("engines", {}).items():
        scores = []

        for i, pick in enumerate(eng_result.get("picks", []), 1):
            scores.append({
                "date": today,
                "symbol": pick["symbol"],
                "engine": engine_name,
                "ret_5d": pick.get("ret_5d"),
                "reversal_score": pick.get("score"),
                "rank_in_universe": i,
                "selected": True,
                "skipped": False,
            })

        for skip in eng_result.get("skipped", []):
            scores.append({
                "date": today,
                "symbol": skip["symbol"],
                "engine": engine_name,
                "ret_5d": skip.get("ret_5d"),
                "selected": False,
                "skipped": True,
                "skip_reason": skip.get("reason", ""),
            })

        if scores:
            repo.bulk_insert_scores(scores)
