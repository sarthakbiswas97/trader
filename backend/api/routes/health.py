"""
Health Check Routes.
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from backend.api.dependencies import get_app_state
from backend.api.schemas import HealthResponse
from backend.broker.session import load_access_token

router = APIRouter()

MODEL_PATH = Path(__file__).parent.parent.parent / "ml" / "models" / "model_latest.joblib"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.

    Returns status of all system components.
    """
    state = get_app_state()

    # Check components
    components = {
        "api": True,
        "broker_authenticated": state.is_authenticated,
        "bot_running": state.is_running,
        "model_available": MODEL_PATH.exists(),
        "session_valid": load_access_token() is not None,
    }

    # Overall status
    critical_components = ["api", "model_available"]
    all_critical_healthy = all(components.get(c, False) for c in critical_components)

    return HealthResponse(
        status="healthy" if all_critical_healthy else "degraded",
        timestamp=datetime.now(),
        version="1.0.0",
        components=components,
    )


@router.get("/market/status")
async def market_status():
    """
    Get current market status and trade recommendation.
    Used by frontend to show market sentiment banner.
    """
    state = get_app_state()

    nifty_change = 0.0
    nifty_price = 0.0
    breadth_falling = 0
    breadth_total = 0
    should_trade = True
    reason = "Market data not available"

    if state.broker and state.is_authenticated:
        try:
            # Get NIFTY
            broker = state.broker
            if hasattr(broker, "_kite") and broker._kite:
                kite = broker._kite
                nifty_data = kite.ohlc(["NSE:NIFTY 50"])
                n = nifty_data.get("NSE:NIFTY 50", {})
                nifty_price = n.get("last_price", 0)
                prev_close = n.get("ohlc", {}).get("close", nifty_price)

                if prev_close > 0:
                    nifty_change = (nifty_price - prev_close) / prev_close

                # Breadth: check a sample of stocks
                from backend.core.symbols import NIFTY_50
                sample = NIFTY_50[:20]
                ltp = kite.ltp([f"NSE:{s}" for s in sample])
                ohlc_data = kite.ohlc([f"NSE:{s}" for s in sample])

                for s in sample:
                    key = f"NSE:{s}"
                    if key in ohlc_data:
                        breadth_total += 1
                        curr = ohlc_data[key].get("last_price", 0)
                        prev = ohlc_data[key].get("ohlc", {}).get("close", curr)
                        if curr < prev:
                            breadth_falling += 1

            # Determine trade signal
            if nifty_change < -0.005:
                should_trade = False
                reason = f"NIFTY down {nifty_change*100:.1f}% — regime gate blocking trades"
            elif breadth_total > 10 and breadth_falling / breadth_total > 0.7:
                should_trade = False
                breadth_pct = breadth_falling / breadth_total * 100
                reason = f"Weak breadth: {breadth_falling}/{breadth_total} ({breadth_pct:.0f}%) stocks falling"
            elif nifty_change > 0.005:
                should_trade = True
                reason = f"Market healthy — NIFTY up {nifty_change*100:.1f}%, conditions favorable for reversal trades"
            else:
                should_trade = True
                reason = f"Market flat ({nifty_change*100:+.1f}%) — conditions acceptable for trading"

        except Exception as e:
            reason = f"Market data check failed: {str(e)}"

    # Trade probability
    if not should_trade:
        trade_probability = "none"
    elif nifty_change > 0.003:
        trade_probability = "high"
    else:
        trade_probability = "low"

    return {
        "nifty_change": nifty_change,
        "nifty_price": nifty_price,
        "breadth_falling": breadth_falling,
        "breadth_total": breadth_total,
        "should_trade": should_trade,
        "reason": reason,
        "trade_probability": trade_probability,
    }


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness():
    """Kubernetes readiness probe."""
    state = get_app_state()

    if not MODEL_PATH.exists():
        return {"status": "not_ready", "reason": "model_not_found"}

    return {"status": "ready"}
