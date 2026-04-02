"""
Portfolio Routes.

View positions, holdings, and P&L.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from backend.api.dependencies import AppStateDep, AuthRequiredDep, BrokerDep
from backend.api.schemas import (
    PortfolioSummary,
    PositionSchema,
    PositionsResponse,
    TradeSchema,
    TradeSide,
    TradesResponse,
    TradeStatus,
)
from backend.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _get_all_pipeline_brokers(state) -> list:
    """Get broker instances from A/B pipelines if available."""
    if state.engine and hasattr(state.engine, "brokers"):
        return list(state.engine.brokers.values())
    return [state.broker] if state.broker else []


def _aggregate_positions(state):
    """Get positions from all pipeline brokers."""
    all_positions = []
    brokers = _get_all_pipeline_brokers(state)
    seen = set()
    for broker in brokers:
        for p in broker.get_positions():
            key = f"{p.symbol}_{p.quantity}_{p.avg_price}"
            if key not in seen:
                seen.add(key)
                all_positions.append(p)
    return all_positions


def _aggregate_pnl(state) -> tuple[float, float, float]:
    """Get total realized P&L, cash, capital from all pipeline brokers."""
    brokers = _get_all_pipeline_brokers(state)
    total_realized = sum(b.realized_pnl for b in brokers if hasattr(b, "realized_pnl"))
    total_cash = sum(b.capital for b in brokers if hasattr(b, "capital"))
    return total_realized, total_cash


@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(state: AuthRequiredDep):
    """
    Get portfolio summary with P&L (aggregated from all pipeline brokers).
    """
    positions = _aggregate_positions(state)
    realized_pnl, cash = _aggregate_pnl(state)

    invested = sum(p.invested_value for p in positions)
    current = sum(p.market_value for p in positions)
    unrealized_pnl = current - invested

    total_capital = cash + current
    total_pnl = realized_pnl + unrealized_pnl
    total_pnl_pct = (total_pnl / total_capital * 100) if total_capital > 0 else 0

    return PortfolioSummary(
        total_capital=total_capital,
        available_cash=cash,
        invested_value=invested,
        current_value=current,
        unrealized_pnl=unrealized_pnl,
        realized_pnl=realized_pnl,
        total_pnl=total_pnl,
        total_pnl_percent=total_pnl_pct,
        open_positions=len(positions),
    )


@router.get("/positions", response_model=PositionsResponse)
async def get_positions(state: AuthRequiredDep):
    """
    Get all open positions (aggregated from all pipeline brokers).
    """
    positions = _aggregate_positions(state)
    realized_pnl, cash = _aggregate_pnl(state)

    position_list = []
    for p in positions:
        position_list.append(PositionSchema(
            symbol=p.symbol,
            quantity=p.quantity,
            avg_price=p.avg_price,
            current_price=p.current_price,
            pnl=p.pnl,
            pnl_percent=p.pnl_percent,
            entry_time=None,
            entry_reason=None,
        ))

    invested = sum(p.invested_value for p in positions)
    current = sum(p.market_value for p in positions)
    unrealized = current - invested
    total_capital = cash + current

    summary = PortfolioSummary(
        total_capital=total_capital,
        available_cash=cash,
        invested_value=invested,
        current_value=current,
        unrealized_pnl=unrealized,
        realized_pnl=realized_pnl,
        total_pnl=realized_pnl + unrealized,
        total_pnl_percent=((realized_pnl + unrealized) / total_capital * 100) if total_capital > 0 else 0,
        open_positions=len(positions),
    )

    return PositionsResponse(
        positions=position_list,
        summary=summary,
    )


def _safe_trade_side(side_value: str) -> TradeSide:
    """Safely convert a side string to TradeSide enum."""
    try:
        return TradeSide(side_value)
    except ValueError:
        return TradeSide.BUY  # fallback


@router.get("/trades", response_model=TradesResponse)
async def get_trades(state: AuthRequiredDep, limit: int = 50):
    """Get trade history from pipeline engines + database fallback."""
    limit = min(limit, 500)
    trades_data = []

    # 1. Get from pipeline MultiEngine trade histories
    if state.engine and hasattr(state.engine, "pipelines"):
        for pid, pipeline in state.engine.pipelines.items():
            for eng_name, eng_state in pipeline.multi_engine.engine_states.items():
                for t in eng_state.trade_history[-limit:]:
                    trades_data.append(TradeSchema(
                        id=f"{pid}_{eng_name}_{t.get('symbol')}_{t.get('entry_date')}",
                        symbol=t.get("symbol", ""),
                        side=_safe_trade_side("BUY"),
                        quantity=t.get("quantity", 0),
                        entry_price=t.get("entry_price", 0),
                        exit_price=t.get("exit_price"),
                        entry_time=datetime.fromisoformat(t["entry_date"]) if t.get("entry_date") else None,
                        exit_time=datetime.fromisoformat(t["exit_date"]) if t.get("exit_date") else None,
                        pnl=t.get("net_pnl"),
                        status=TradeStatus.CLOSED,
                        exit_reason=f"Pipeline {pid} | {eng_name}",
                    ))

    # 2. Fallback: Get from trade executor (in-memory, current session)
    if not trades_data and state.engine and state.engine.trade_executor:
        history = state.engine.trade_executor.get_trade_history()
        for i, t in enumerate(history[-limit:]):
            trades_data.append(TradeSchema(
                id=t.get("order_id", f"trade_{i}"),
                symbol=t["symbol"],
                side=_safe_trade_side(t["side"]),
                quantity=t["quantity"],
                entry_price=t["price"],
                exit_price=None,
                entry_time=datetime.fromisoformat(t["timestamp"]),
                exit_time=None,
                pnl=None,
                status=TradeStatus.CLOSED if t["success"] else TradeStatus.OPEN,
                exit_reason=t.get("message"),
            ))

    # 2. If no in-memory trades, read from database
    if not trades_data:
        try:
            from backend.db.database import get_session
            from backend.db.repository import IntraTradeRepository

            with get_session() as session:
                repo = IntraTradeRepository(session)
                db_trades = repo.get_recent_trades(limit=limit)
                for t in db_trades:
                    trades_data.append(TradeSchema(
                        id=t.trade_id,
                        symbol=t.symbol,
                        side=_safe_trade_side(t.side),
                        quantity=t.quantity,
                        entry_price=t.price,
                        exit_price=None,
                        entry_time=t.timestamp,
                        exit_time=None,
                        pnl=None,
                        status=TradeStatus.CLOSED if t.success else TradeStatus.OPEN,
                        exit_reason=t.message,
                    ))
        except Exception as e:
            logger.warning(f"Failed to read trades from DB: {e}")

    # Calculate stats
    winning = sum(1 for t in trades_data if t.pnl and t.pnl > 0)
    losing = sum(1 for t in trades_data if t.pnl and t.pnl < 0)
    total = len(trades_data)
    win_rate = (winning / total * 100) if total > 0 else 0

    return TradesResponse(
        trades=trades_data[-limit:],
        total_count=total,
        winning_trades=winning,
        losing_trades=losing,
        win_rate=win_rate,
    )


@router.get("/margin")
async def get_margin(state: AuthRequiredDep):
    """
    Get margin/funds information (aggregated from pipeline brokers).
    """
    brokers = _get_all_pipeline_brokers(state)
    total_cash = 0
    total_used = 0
    total_balance = 0
    for b in brokers:
        m = b.get_margin()
        total_cash += m.available_cash
        total_used += m.used_margin
        total_balance += m.total_balance

    return {
        "available_cash": total_cash,
        "used_margin": total_used,
        "total_balance": total_balance,
    }


@router.get("/holdings")
async def get_holdings(state: AuthRequiredDep):
    """
    Get delivery holdings (CNC positions).
    """
    broker = state.broker
    holdings = broker.get_holdings()

    return {
        "holdings": [
            {
                "symbol": h.symbol,
                "quantity": h.quantity,
                "avg_price": h.avg_price,
                "current_price": h.current_price,
                "pnl": h.pnl,
                "pnl_percent": h.pnl_percent,
            }
            for h in holdings
        ],
        "total_count": len(holdings),
    }
