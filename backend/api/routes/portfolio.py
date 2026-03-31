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


@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(state: AuthRequiredDep):
    """
    Get portfolio summary with P&L.
    """
    broker = state.broker
    margin = broker.get_margin()
    positions = broker.get_positions()

    invested = sum(p.invested_value for p in positions)
    current = sum(p.market_value for p in positions)
    unrealized_pnl = current - invested

    # Get realized P&L from paper broker if available
    realized_pnl = 0.0
    if hasattr(broker, "realized_pnl"):
        realized_pnl = broker.realized_pnl

    total_capital = margin.available_cash + current
    total_pnl = realized_pnl + unrealized_pnl
    total_pnl_pct = (total_pnl / total_capital * 100) if total_capital > 0 else 0

    return PortfolioSummary(
        total_capital=total_capital,
        available_cash=margin.available_cash,
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
    Get all open positions.
    """
    broker = state.broker
    positions = broker.get_positions()

    # Convert to schema
    position_list = []
    for p in positions:
        entry_time = None
        entry_reason = None

        # Get additional info from position manager if available
        if state.engine and state.engine.position_manager:
            managed = state.engine.position_manager.get_position(p.symbol)
            if managed:
                entry_time = managed.entry_time
                entry_reason = managed.entry_reason

        position_list.append(PositionSchema(
            symbol=p.symbol,
            quantity=p.quantity,
            avg_price=p.avg_price,
            current_price=p.current_price,
            pnl=p.pnl,
            pnl_percent=p.pnl_percent,
            entry_time=entry_time,
            entry_reason=entry_reason,
        ))

    # Calculate summary
    margin = broker.get_margin()
    invested = sum(p.invested_value for p in positions)
    current = sum(p.market_value for p in positions)
    unrealized = current - invested
    realized = broker.realized_pnl if hasattr(broker, "realized_pnl") else 0.0
    total_capital = margin.available_cash + current

    summary = PortfolioSummary(
        total_capital=total_capital,
        available_cash=margin.available_cash,
        invested_value=invested,
        current_value=current,
        unrealized_pnl=unrealized,
        realized_pnl=realized,
        total_pnl=realized + unrealized,
        total_pnl_percent=((realized + unrealized) / total_capital * 100) if total_capital > 0 else 0,
        open_positions=len(positions),
    )

    return PositionsResponse(
        positions=position_list,
        summary=summary,
    )


@router.get("/trades", response_model=TradesResponse)
async def get_trades(state: AuthRequiredDep, limit: int = 50):
    limit = min(limit, 500)  # Cap at 500
    """
    Get trade history.
    """
    broker = state.broker

    # Get trades from paper broker or trade executor
    trades_data = []

    if hasattr(broker, "get_trades"):
        paper_trades = broker.get_trades()
        for i, t in enumerate(paper_trades[-limit:]):
            trades_data.append(TradeSchema(
                id=t.trade_id,
                symbol=t.symbol,
                side=TradeSide(t.side.value),
                quantity=t.quantity,
                entry_price=t.price,
                exit_price=None,
                entry_time=t.timestamp,
                exit_time=None,
                pnl=None,
                pnl_percent=None,
                status=TradeStatus.CLOSED,
                exit_reason=None,
            ))

    # Also get from trade executor if available
    if state.engine and state.engine.trade_executor:
        history = state.engine.trade_executor.get_trade_history()
        for i, t in enumerate(history[-limit:]):
            trades_data.append(TradeSchema(
                id=t.get("order_id", f"trade_{i}"),
                symbol=t["symbol"],
                side=TradeSide(t["side"]),
                quantity=t["quantity"],
                entry_price=t["price"],
                exit_price=None,
                entry_time=datetime.fromisoformat(t["timestamp"]),
                exit_time=None,
                pnl=None,
                status=TradeStatus.CLOSED if t["success"] else TradeStatus.OPEN,
                exit_reason=t.get("message"),
            ))

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
    Get margin/funds information.
    """
    broker = state.broker
    margin = broker.get_margin()

    return {
        "available_cash": margin.available_cash,
        "used_margin": margin.used_margin,
        "total_balance": margin.total_balance,
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
