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
from backend.services.execution_engine import create_engine
from backend.services.pipeline import (
    get_pipeline_status,
    ensure_model_ready,
    model_exists,
    model_is_stale,
    pipeline_progress,
    run_full_pipeline,
)

from backend.core.symbols import NIFTY_50

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
    Prepare the bot by running the ML pipeline if needed.
    Runs in background — poll /bot/prepare/status for progress.

    Pipeline steps:
    1. Download historical data (if missing)
    2. Generate features (if missing)
    3. Train model (if missing or stale > 7 days)
    """
    if pipeline_progress.running:
        return {"success": True, "message": "Pipeline already running"}

    # Check if pipeline is even needed
    if model_exists() and not model_is_stale():
        pipeline_progress.start()
        pipeline_progress.finish()  # Immediately done
        return {"success": True, "message": "Model is fresh, no preparation needed"}

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

    return {"success": True, "message": "Pipeline started"}


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

    if not model_exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML model not found. Call /bot/prepare first.",
        )

    symbols = request.symbols or NIFTY_50

    try:
        # Create execution engine
        engine = create_engine(
            broker=state.broker,
            symbols=symbols,
        )

        state.engine = engine

        # Start engine in background using asyncio task
        loop = asyncio.get_event_loop()

        async def run_engine():
            try:
                await engine.run()
            except Exception as e:
                logger.error(f"Engine error: {e}")

        loop.create_task(run_engine())

        logger.info(f"Bot started", symbols=len(symbols))

        return BotStartResponse(
            success=True,
            message=f"Bot started with {len(symbols)} symbols",
            status=BotStatus.RUNNING,
        )

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start bot. Check model and broker status.",
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
    """
    from backend.strategies.multi_engine import MultiEngine

    kite = getattr(state.broker, "_kite", None) if state.broker else None
    engine = MultiEngine(kite=kite)

    return engine.get_status()


@router.post("/multi-engine/run")
async def run_multi_engine_cycle(state: AuthRequiredDep):
    """
    Run one daily cycle of the multi-engine system.
    """
    from backend.strategies.multi_engine import MultiEngine

    kite = getattr(state.broker, "_kite", None) if state.broker else None
    engine = MultiEngine(kite=kite)

    result = engine.run_daily()
    return result


@router.post("/multi-engine/reset")
async def reset_multi_engine(state: AuthRequiredDep):
    """Reset multi-engine state."""
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
