"""
Predictions Routes.

Generate and view ML predictions.
Supports both batch (POST) and streaming (SSE) generation.
"""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from backend.api.dependencies import AppStateDep, AuthRequiredDep, PredictionServiceDep
from backend.api.schemas import (
    PredictionRequest,
    PredictionSchema,
    PredictionsResponse,
)
from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_50
from backend.services.feature_engine import FeatureEngine
from backend.services.historical_data import HistoricalDataService
from backend.utils.time_utils import now_ist

logger = get_logger(__name__)
router = APIRouter()


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
    symbols = request.symbols or NIFTY_50
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


@router.get("/stream")
async def stream_predictions(state: AuthRequiredDep):
    """
    Stream predictions via Server-Sent Events.

    Each prediction is sent as it's computed (~1 per second).
    Frontend uses EventSource to receive them one-by-one.

    Events:
      - "prediction": Individual prediction result
      - "progress": Progress update (X/total)
      - "done": Stream complete with summary
      - "error": Error for a specific symbol
    """
    from backend.api.dependencies import get_prediction_service

    try:
        prediction_service = get_prediction_service(state)
    except HTTPException:
        async def error_stream():
            yield f"event: error\ndata: {json.dumps({'error': 'ML model not found'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    broker = state.broker
    symbols = NIFTY_50

    data_service = HistoricalDataService()
    if hasattr(broker, "_kite") and broker._kite:
        data_service.set_kite(broker._kite)

    feature_engine = FeatureEngine(data_service=data_service)

    async def event_stream():
        total = len(symbols)
        completed = 0
        up_count = 0
        down_count = 0
        neutral_count = 0

        for i, symbol in enumerate(symbols):
            try:
                # Progress event
                yield f"event: progress\ndata: {json.dumps({'current': i + 1, 'total': total, 'symbol': symbol})}\n\n"

                # Fetch and compute
                end_date = now_ist()
                start_date = end_date - timedelta(days=5)

                df = data_service.fetch_candles(
                    symbol=symbol,
                    interval="5m",
                    start_date=start_date,
                    end_date=end_date,
                )

                if df.empty or len(df) < 100:
                    yield f"event: error\ndata: {json.dumps({'symbol': symbol, 'error': 'Insufficient data'})}\n\n"
                    continue

                features = feature_engine.get_latest_features(symbol, df)
                if features is None:
                    yield f"event: error\ndata: {json.dumps({'symbol': symbol, 'error': 'Feature computation failed'})}\n\n"
                    continue

                pred = prediction_service.predict(features)
                completed += 1

                if pred.direction == "UP":
                    up_count += 1
                elif pred.direction == "DOWN":
                    down_count += 1
                else:
                    neutral_count += 1

                # Send prediction event
                prediction_data = {
                    "symbol": pred.symbol,
                    "direction": pred.direction,
                    "probability": round(pred.probability, 4),
                    "confidence": round(pred.confidence, 4),
                    "prob_up": round(pred.prob_up, 4),
                    "prob_down": round(pred.prob_down, 4),
                    "prob_neutral": round(pred.prob_neutral, 4),
                    "should_trade": pred.should_trade,
                    "is_long_signal": pred.is_long_signal,
                    "is_short_signal": pred.is_short_signal,
                    "timestamp": pred.timestamp.isoformat() if pred.timestamp else None,
                    "top_features": [(n, round(float(v), 4)) for n, v in pred.top_features[:3]],
                }
                yield f"event: prediction\ndata: {json.dumps(prediction_data)}\n\n"

            except Exception as e:
                logger.error(f"Stream prediction failed for {symbol}: {e}")
                yield f"event: error\ndata: {json.dumps({'symbol': symbol, 'error': str(e)})}\n\n"

        # Done event with summary
        summary = {
            "symbols_analyzed": completed,
            "up_signals": up_count,
            "down_signals": down_count,
            "neutral_signals": neutral_count,
            "generated_at": datetime.now().isoformat(),
        }
        yield f"event: done\ndata: {json.dumps(summary)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/latest", response_model=PredictionsResponse)
async def get_latest_predictions(state: AppStateDep):
    """
    Get latest predictions — from in-memory cache or database.
    """
    predictions = []

    # 1. Try in-memory from running engine
    if state.engine and state.engine._latest_predictions:
        for pred in state.engine._latest_predictions.values():
            predictions.append(PredictionSchema(
                symbol=pred.symbol,
                direction=pred.direction,
                probability=pred.probability,
                confidence=pred.confidence,
                should_trade=pred.should_trade,
                timestamp=pred.timestamp,
                top_features=pred.top_features[:3],
            ))

    # 2. Fallback to database
    if not predictions:
        try:
            from backend.db.database import get_session
            from backend.db.repository import PredictionRepository

            with get_session() as session:
                repo = PredictionRepository(session)
                db_preds = repo.get_latest_cycle(limit=50)
                for p in db_preds:
                    predictions.append(PredictionSchema(
                        symbol=p.symbol,
                        direction=p.direction,
                        probability=p.probability or 0,
                        confidence=p.confidence or 0,
                        should_trade=p.should_trade or False,
                        timestamp=p.timestamp,
                        top_features=[],
                    ))
        except Exception as e:
            logger.warning(f"Failed to read predictions from DB: {e}")

    if not predictions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No predictions available. Start the bot or use /predictions/generate",
        )

    predictions.sort(key=lambda p: p.confidence, reverse=True)
    up_signals = sum(1 for p in predictions if p.direction == "UP")
    down_signals = sum(1 for p in predictions if p.direction == "DOWN")

    return PredictionsResponse(
        predictions=predictions,
        generated_at=datetime.now(),
        symbols_analyzed=len(predictions),
        up_signals=up_signals,
        down_signals=down_signals,
    )


@router.get("/symbols")
async def get_available_symbols(state: AuthRequiredDep):
    """
    Get list of available symbols for prediction.
    """
    symbols = NIFTY_50

    return {
        "symbols": symbols,
        "count": len(symbols),
        "index": "NIFTY 50",
    }
