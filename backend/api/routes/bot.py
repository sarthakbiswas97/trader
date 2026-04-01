"""
Bot Control Routes.

Start, stop, and monitor the trading bot.
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from backend.api.dependencies import AppStateDep, AuthRequiredDep
from backend.api.schemas import (
    BotStartRequest,
    BotStartResponse,
    BotStatus,
    BotStatusResponse,
    BotStopResponse,
    RiskStatus,
)
from backend.core.logger import get_logger
from backend.services.execution_engine import create_engine, PIPELINE_CAPITAL
from backend.services.pipeline import (
    get_pipeline_status,
    ensure_model_ready,
    model_exists,
    model_is_stale,
    pipeline_progress,
    run_full_pipeline,
)

from backend.core.symbols import NIFTY_100

logger = get_logger(__name__)
router = APIRouter()


@router.get("/status", response_model=BotStatusResponse)
async def get_bot_status(state: AppStateDep):
    """
    Get current bot status.
    """
    if not state.engine:
        return BotStatusResponse(
            status=BotStatus.STOPPED,
            symbols_count=0,
        )

    engine = state.engine

    return BotStatusResponse(
        status=BotStatus.RUNNING if engine.running else BotStatus.STOPPED,
        cycle_count=engine._cycle_count,
        last_cycle=(
            engine._cycle_history[-1].timestamp
            if engine._cycle_history else None
        ),
        symbols_count=len(engine.symbols),
    )


@router.post("/prepare")
async def prepare_bot(state: AuthRequiredDep):
    """
    Prepare the bot by downloading historical data.

    The reversal engine needs daily candle data for scoring.
    ML features and model training are optional (predictions page only).

    Runs in background — poll /bot/prepare/status for progress.
    """
    if pipeline_progress.running:
        return {"success": True, "message": "Pipeline already running"}

    kite = getattr(state.broker, "_kite", None)

    # Run pipeline in background thread
    import threading

    def run_pipeline():
        try:
            run_full_pipeline(kite=kite)
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            pipeline_progress.finish(error=str(e))

    thread = threading.Thread(target=run_pipeline, daemon=True)
    thread.start()

    return {"success": True, "message": "Pipeline started — downloading data"}


@router.get("/prepare/status")
async def get_prepare_status():
    """
    Get current pipeline preparation progress.

    Returns step-by-step progress for the frontend to display.
    """
    return pipeline_progress.get_status()


@router.post("/start", response_model=BotStartResponse)
async def start_bot(
    request: BotStartRequest,
    state: AuthRequiredDep,
):
    """
    Start the trading bot.

    Requires model to be ready (call /bot/prepare first if needed).
    """
    if state.is_running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot is already running",
        )

    try:
        # Create reversal-based trading engine
        engine = create_engine(
            broker=state.broker,
        )

        state.engine = engine
        engine.running = True

        # Start engine in background using asyncio task
        loop = asyncio.get_event_loop()

        async def run_engine():
            try:
                await engine.run()
            except Exception as e:
                logger.error(f"Engine error: {e}")
                engine.running = False

        loop.create_task(run_engine())

        logger.info("Reversal bot started", symbols=len(engine.symbols))

        return BotStartResponse(
            success=True,
            message=f"Reversal bot started — {len(engine.symbols)} symbols, regime-gated",
            status=BotStatus.RUNNING,
        )

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start bot: {str(e)}",
        )


@router.post("/stop", response_model=BotStopResponse)
async def stop_bot(state: AuthRequiredDep, square_off: bool = False):
    """
    Stop the trading bot.

    Args:
        square_off: If True, close all open positions before stopping
    """
    if not state.engine:
        return BotStopResponse(
            success=True,
            message="Bot was not running",
            positions_closed=0,
        )

    positions_closed = 0

    if square_off and state.engine:
        results = state.engine.square_off_all()
        positions_closed = len(results)

    state.engine.stop()

    logger.info(f"Bot stopped", positions_closed=positions_closed)

    return BotStopResponse(
        success=True,
        message="Bot stopped successfully",
        positions_closed=positions_closed,
    )


@router.get("/cycles")
async def get_recent_cycles(state: AppStateDep, limit: int = 10):
    limit = min(limit, 100)  # Cap at 100
    """
    Get recent execution cycles.
    """
    if not state.engine:
        return {"cycles": [], "total": 0}

    cycles = state.engine.get_recent_cycles(limit)

    return {
        "cycles": cycles,
        "total": state.engine._cycle_count,
    }


@router.get("/risk", response_model=RiskStatus)
async def get_risk_status(state: AuthRequiredDep):
    """
    Get current risk management status.
    """
    if not state.engine:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot not started",
        )

    risk = state.engine.risk_guardian.get_status()

    return RiskStatus(**risk)


@router.get("/watchlist")
async def get_hot_watchlist(state: AppStateDep):
    """
    Get Tier 1 (hot) watchlist — stocks being scanned every 2 minutes.
    """
    if not state.engine:
        return {"watchlist": [], "tier1_count": 0, "total_symbols": 0}

    watchlist = state.engine.get_hot_watchlist()

    return {
        "watchlist": watchlist,
        "tier1_count": len(watchlist),
        "total_symbols": len(state.engine.symbols),
    }


@router.post("/shorting")
async def toggle_shorting(state: AuthRequiredDep, enabled: bool = True):
    """
    Enable or disable short selling.
    """
    if not state.engine:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot not started",
        )

    state.engine.risk_guardian.set_shorting_enabled(enabled)

    return {
        "success": True,
        "shorting_enabled": enabled,
        "message": f"Shorting {'enabled' if enabled else 'disabled'}",
    }


@router.get("/pipeline")
async def get_pipeline_info(state: AppStateDep):
    """
    Get ML pipeline status (data, features, model).
    """
    return get_pipeline_status()


@router.post("/train")
async def trigger_training(state: AuthRequiredDep, force: bool = False):
    """
    Manually trigger the ML training pipeline.

    Args:
        force: If True, re-run all steps even if data/model exists
    """
    from backend.services.pipeline import run_full_pipeline

    kite = getattr(state.broker, "_kite", None)

    results = run_full_pipeline(
        kite=kite,
        force=force,
    )

    if not results["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {results}",
        )

    return {
        "success": True,
        "message": "Pipeline completed",
        "steps": results,
    }


@router.get("/multi-engine")
async def get_multi_engine_status(state: AppStateDep):
    """
    Get multi-engine orchestrator status.

    Returns regime state, per-engine metrics, and capital allocation.
    Uses the running engine if bot is started, otherwise creates a fresh one.
    """
    if state.engine and hasattr(state.engine, "multi_engine"):
        return state.engine.multi_engine.get_status()

    from backend.strategies.multi_engine import MultiEngine
    kite = getattr(state.broker, "_kite", None) if state.broker else None
    engine = MultiEngine(kite=kite)
    return engine.get_status()


@router.post("/multi-engine/run")
async def run_multi_engine_cycle(state: AuthRequiredDep):
    """
    Run one daily cycle of the multi-engine system.

    Uses the running engine if bot is started.
    """
    if state.engine and hasattr(state.engine, "multi_engine"):
        result = state.engine.multi_engine.run_daily()
        return result

    from backend.strategies.multi_engine import MultiEngine
    kite = getattr(state.broker, "_kite", None) if state.broker else None
    engine = MultiEngine(kite=kite)
    return engine.run_daily()


@router.post("/multi-engine/reset")
async def reset_multi_engine(state: AuthRequiredDep):
    """Reset multi-engine state."""
    if state.engine and hasattr(state.engine, "multi_engine"):
        state.engine.multi_engine.reset()
        return {"success": True, "message": "Multi-engine state reset"}

    from backend.strategies.multi_engine import MultiEngine
    engine = MultiEngine()
    engine.reset()
    return {"success": True, "message": "Multi-engine state reset"}


@router.post("/square-off")
async def square_off_all(state: AuthRequiredDep):
    """
    Emergency square off all positions.
    """
    if not state.engine:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot not started",
        )

    results = state.engine.square_off_all()

    return {
        "success": True,
        "positions_closed": len(results),
        "results": results,
    }


@router.post("/reset")
async def reset_trading_state(state: AuthRequiredDep):
    """
    Reset all trading state for a fresh start.

    Clears: trade history, open positions, P&L, multi-engine state.
    Resets capital to initial amount.
    """
    if state.is_running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stop the bot first before resetting.",
        )

    # Reset broker state
    if state.broker and hasattr(state.broker, "reset"):
        state.broker.reset()

    # Clear DB tables
    try:
        from backend.db.database import get_session
        from backend.db.repository import IntraTradeRepository, OpenPositionRepository

        with get_session() as session:
            OpenPositionRepository(session).clear_all()
            # Clear intra_trades
            from backend.db.models import IntraTrade
            session.query(IntraTrade).delete()
    except Exception as e:
        logger.warning(f"DB reset partial: {e}")

    # Reset multi-engine state
    try:
        from backend.strategies.multi_engine import MultiEngine
        engine = MultiEngine()
        engine.reset()
    except Exception as e:
        logger.warning(f"Multi-engine reset: {e}")

    # Clear app state engine
    state.engine = None

    logger.info("Trading state reset — fresh start")

    return {
        "success": True,
        "message": "All trading state cleared. Fresh start from initial capital.",
    }


# =============================================================================
# A/B Pipeline Endpoints
# =============================================================================


@router.get("/pipelines")
async def get_pipelines(state: AppStateDep):
    """Get status of both A/B pipelines."""
    if not state.engine or not hasattr(state.engine, "pipelines"):
        return {"pipelines": {}, "running": False}

    return state.engine.get_status()


@router.get("/pipelines/compare")
async def compare_pipelines(state: AppStateDep):
    """Side-by-side comparison of pipeline A vs B."""
    if not state.engine or not hasattr(state.engine, "pipelines"):
        return {"comparison": {}}

    comparison = {}
    for pid, p in state.engine.pipelines.items():
        me = p.multi_engine
        pipeline_broker = state.engine.brokers.get(pid) if hasattr(state.engine, "brokers") else None

        total_trades = sum(len(s.trade_history) for s in me.engine_states.values())
        wins = sum(
            1 for s in me.engine_states.values()
            for t in s.trade_history if t.get("net_pnl", 0) > 0
        )
        open_count = sum(
            len(b["stocks"])
            for s in me.engine_states.values()
            for b in s.positions
        )

        broker_positions = pipeline_broker.get_positions() if pipeline_broker else []
        realized = pipeline_broker.realized_pnl if pipeline_broker else 0
        unrealized = sum(pos.pnl for pos in broker_positions)
        total_pnl = realized + unrealized
        broker_capital = pipeline_broker.capital if pipeline_broker else PIPELINE_CAPITAL

        comparison[pid] = {
            "label": p.label,
            "scan_count": p.scan_count,
            "last_scan": p.last_scan.isoformat() if p.last_scan else None,
            "total_pnl": round(total_pnl, 2),
            "pnl_pct": round(total_pnl / PIPELINE_CAPITAL * 100, 2) if PIPELINE_CAPITAL else 0,
            "total_trades": total_trades,
            "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            "open_positions": open_count,
            "capital": PIPELINE_CAPITAL,
            "portfolio_value": round(broker_capital + unrealized, 2),
        }

    return {"comparison": comparison}


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline_detail(state: AppStateDep, pipeline_id: str):
    """Get detailed status for a specific pipeline (A or B)."""
    if not state.engine or not hasattr(state.engine, "pipelines"):
        return {"error": "Bot not running"}

    pipeline = state.engine.get_pipeline(pipeline_id)
    if not pipeline:
        return {"error": f"Pipeline {pipeline_id} not found"}

    me = pipeline.multi_engine
    pid = pipeline_id.upper()

    # Get live positions from the pipeline's own broker
    pipeline_broker = state.engine.brokers.get(pid) if hasattr(state.engine, "brokers") else None
    broker_positions = pipeline_broker.get_positions() if pipeline_broker else []

    positions = []
    for name, engine_state in me.engine_states.items():
        for batch in engine_state.positions:
            for stock in batch["stocks"]:
                # Find current price from broker
                current_price = stock["entry_price"]
                for bp in broker_positions:
                    if bp.symbol == stock["symbol"]:
                        current_price = bp.current_price
                        break
                pnl = (current_price - stock["entry_price"]) * stock["quantity"]

                positions.append({
                    "symbol": stock["symbol"],
                    "engine": name,
                    "entry_price": stock["entry_price"],
                    "current_price": current_price,
                    "quantity": stock["quantity"],
                    "pnl": round(pnl, 2),
                    "score": stock.get("score", 0),
                    "entry_date": batch["entry_date"],
                })

    trades = []
    for name, engine_state in me.engine_states.items():
        for t in engine_state.trade_history[-50:]:
            trades.append({**t, "engine": name})

    total_pnl = sum(t.get("net_pnl", 0) for t in me.engine_states["largecap"].trade_history)
    total_pnl += sum(t.get("net_pnl", 0) for t in me.engine_states["midcap"].trade_history)
    total_trades = sum(len(s.trade_history) for s in me.engine_states.values())
    wins = sum(
        1 for s in me.engine_states.values()
        for t in s.trade_history if t.get("net_pnl", 0) > 0
    )

    # Broker P&L (actual paper trading)
    broker_realized = pipeline_broker.realized_pnl if pipeline_broker else 0
    broker_unrealized = sum(p.pnl for p in broker_positions)
    broker_capital = pipeline_broker.capital if pipeline_broker else PIPELINE_CAPITAL

    return {
        "pipeline": pipeline.name,
        "label": pipeline.label,
        "interval_secs": pipeline.interval_secs,
        "scan_count": pipeline.scan_count,
        "last_scan": pipeline.last_scan.isoformat() if pipeline.last_scan else None,
        "regime": me.current_regime.value if me.current_regime else "unknown",
        "capital": PIPELINE_CAPITAL,
        "portfolio_value": broker_capital + broker_unrealized,
        "cash": broker_capital,
        "total_pnl": broker_realized + broker_unrealized,
        "realized_pnl": broker_realized,
        "unrealized_pnl": broker_unrealized,
        "total_trades": total_trades,
        "win_rate": (wins / total_trades * 100) if total_trades > 0 else 0,
        "positions": positions,
        "recent_trades": trades[-20:],
    }


@router.get("/pipelines/{pipeline_id}/scans")
async def get_pipeline_scans(pipeline_id: str, limit: int = 50):
    """Get scan history for a pipeline."""
    limit = min(limit, 200)
    try:
        from backend.db.database import get_session
        from backend.db.repository import ScanLogRepository

        with get_session() as session:
            repo = ScanLogRepository(session)
            logs = repo.get_by_pipeline(pipeline_id.upper(), limit=limit)
            return {
                "pipeline": pipeline_id.upper(),
                "scans": [
                    {
                        "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                        "regime": l.regime,
                        "buy_signals": l.buy_signals,
                        "entries_made": l.entries_made,
                        "exits_made": l.exits_made,
                        "portfolio_value": l.portfolio_value,
                        "cash": l.cash,
                        "open_positions": l.open_positions_count,
                        "top_picks": l.top_picks,
                        "scan_duration_ms": l.scan_duration_ms,
                    }
                    for l in logs
                ],
                "total": len(logs),
            }
    except Exception as e:
        return {"pipeline": pipeline_id.upper(), "scans": [], "error": str(e)}


