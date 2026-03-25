"""
Predictions Routes.

Generate and view ML predictions.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, status

from backend.api.dependencies import AppStateDep, AuthRequiredDep, PredictionServiceDep
from backend.api.schemas import (
    PredictionRequest,
    PredictionSchema,
    PredictionsResponse,
)
from backend.core.logger import get_logger
from backend.services.feature_engine import FeatureEngine
from backend.services.historical_data import HistoricalDataService
from backend.utils.time_utils import now_ist

logger = get_logger(__name__)
router = APIRouter()

# Default symbols for predictions
DEFAULT_SYMBOLS = [
    "RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
]


@router.post("/generate", response_model=PredictionsResponse)
async def generate_predictions(
    request: PredictionRequest,
    state: AuthRequiredDep,
    prediction_service: PredictionServiceDep,
):
    """
    Generate fresh predictions for specified symbols.

    This fetches latest market data and computes ML predictions.
    """
    symbols = request.symbols or DEFAULT_SYMBOLS[:request.limit]
    broker = state.broker

    # Initialize services
    data_service = HistoricalDataService()
    if hasattr(broker, "_kite") and broker._kite:
        data_service.set_kite(broker._kite)

    feature_engine = FeatureEngine(data_service=data_service)

    predictions = []
    errors = []

    for symbol in symbols:
        try:
            # Fetch recent candles
            end_date = now_ist()
            start_date = end_date - timedelta(days=5)

            df = data_service.fetch_candles(
                symbol=symbol,
                interval="5m",
                start_date=start_date,
                end_date=end_date,
            )

            if df.empty or len(df) < 100:
                errors.append(f"{symbol}: insufficient data")
                continue

            # Compute features
            features = feature_engine.get_latest_features(symbol, df)
            if features is None:
                errors.append(f"{symbol}: feature computation failed")
                continue

            # Generate prediction
            pred = prediction_service.predict(features)

            predictions.append(PredictionSchema(
                symbol=pred.symbol,
                direction=pred.direction,
                probability=pred.probability,
                confidence=pred.confidence,
                should_trade=pred.should_trade,
                timestamp=pred.timestamp,
                top_features=pred.top_features[:3],
            ))

        except Exception as e:
            errors.append(f"{symbol}: {str(e)}")
            logger.error(f"Prediction failed for {symbol}: {e}")

    # Sort by confidence
    predictions.sort(key=lambda p: p.confidence, reverse=True)

    up_signals = sum(1 for p in predictions if p.direction == "UP")
    down_signals = sum(1 for p in predictions if p.direction == "DOWN")

    if errors:
        logger.warning(f"Prediction errors: {errors}")

    return PredictionsResponse(
        predictions=predictions,
        generated_at=datetime.now(),
        symbols_analyzed=len(predictions),
        up_signals=up_signals,
        down_signals=down_signals,
    )


@router.get("/latest", response_model=PredictionsResponse)
async def get_latest_predictions(state: AppStateDep):
    """
    Get latest predictions from the running bot.

    Returns cached predictions from the last execution cycle.
    """
    if not state.engine:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot not running. Start the bot or use /predictions/generate",
        )

    # Get from last cycle
    if not state.engine._cycle_history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No predictions available yet. Wait for first cycle.",
        )

    last_cycle = state.engine._cycle_history[-1]

    return PredictionsResponse(
        predictions=[],  # Would need to store predictions in cycle
        generated_at=last_cycle.timestamp,
        symbols_analyzed=last_cycle.predictions_generated,
        up_signals=last_cycle.signals_found,
        down_signals=last_cycle.predictions_generated - last_cycle.signals_found,
    )


@router.get("/symbols")
async def get_available_symbols(state: AuthRequiredDep):
    """
    Get list of available symbols for prediction.
    """
    # Return default NIFTY 50 symbols
    symbols = [
        "RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK",
        "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
        "HINDUNILVR", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
        "TITAN", "SUNPHARMA", "ULTRACEMCO", "NESTLEIND", "WIPRO",
        "HCLTECH", "POWERGRID", "NTPC", "TECHM", "M&M",
        "BAJAJFINSV", "ONGC", "ADANIENT", "ADANIPORTS", "COALINDIA",
        "JSWSTEEL", "TATASTEEL", "GRASIM", "INDUSINDBK", "BRITANNIA",
        "CIPLA", "DRREDDY", "DIVISLAB", "EICHERMOT", "HEROMOTOCO",
        "BPCL", "APOLLOHOSP", "SBILIFE", "TATACONSUM", "HINDALCO",
        "BAJAJ-AUTO", "UPL", "SHREECEM",
    ]

    return {
        "symbols": symbols,
        "count": len(symbols),
        "index": "NIFTY 50",
    }
