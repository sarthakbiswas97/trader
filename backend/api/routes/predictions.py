"""
Predictions Routes.

Generate and view ML predictions.
Supports both batch (POST) and streaming (SSE) generation.
"""

import json
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from backend.api.dependencies import AppStateDep, AuthRequiredDep, PredictionServiceDep
from backend.api.schemas import (
    PredictionRequest,
    PredictionSchema,
    PredictionsResponse,
)
from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_100
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
    symbols = request.symbols or NIFTY_100
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
    symbols = NIFTY_100

    data_service = HistoricalDataService()
    if hasattr(broker, "_kite") and broker._kite:
        data_service.set_kite(broker._kite)

    feature_engine = FeatureEngine(data_service=data_service)

    session_id = f"manual_{uuid4().hex[:12]}"

    async def event_stream():
        total = len(symbols)
        completed = 0
        up_count = 0
        down_count = 0
        neutral_count = 0
        db_records = []
        ts = now_ist()

        for i, symbol in enumerate(symbols):
            try:
                yield f"event: progress\ndata: {json.dumps({'current': i + 1, 'total': total, 'symbol': symbol})}\n\n"

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

                # Collect for DB persistence
                db_records.append({
                    "symbol": pred.symbol,
                    "direction": pred.direction,
                    "probability": pred.probability,
                    "confidence": pred.confidence,
                    "prob_up": pred.prob_up,
                    "prob_down": pred.prob_down,
                    "prob_neutral": pred.prob_neutral,
                    "should_trade": pred.should_trade,
                    "source": "manual",
                    "session_id": session_id,
                    "timestamp": ts,
                })

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

        # Persist all predictions to DB
        try:
            from backend.db.database import get_session
            from backend.db.repository import PredictionRepository
            with get_session() as session:
                repo = PredictionRepository(session)
                repo.bulk_insert(db_records)
            logger.info(f"Persisted {len(db_records)} predictions (session={session_id})")
        except Exception as e:
            logger.warning(f"Failed to persist stream predictions: {e}")

        summary = {
            "symbols_analyzed": completed,
            "up_signals": up_count,
            "down_signals": down_count,
            "neutral_signals": neutral_count,
            "generated_at": datetime.now().isoformat(),
            "session_id": session_id,
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
    symbols = NIFTY_100

    return {
        "symbols": symbols,
        "count": len(symbols),
        "index": "NIFTY 100",
    }


@router.get("/reversal")
async def get_reversal_scores(state: AppStateDep):
    """
    Get reversal scores for all NIFTY 100 stocks with regime context.

    This is what the trading engine actually uses for decisions.
    Returns each stock's oversold score, returns, and the action
    the system would take (buy/skip/held and why).
    """
    from backend.core.scoring import compute_reversal_scores
    from backend.core.symbols import NIFTY_50, NIFTY_100_EXTRA
    from backend.services.historical_data import HistoricalDataService
    from backend.strategies.multi_engine import MultiEngine

    # Use running engine if available, otherwise create fresh
    if state.engine and hasattr(state.engine, "multi_engine"):
        me = state.engine.multi_engine
    else:
        kite = getattr(state.broker, "_kite", None) if state.broker else None
        me = MultiEngine(kite=kite)

    # Get regime info
    regime_status = me.regime_classifier.get_status()
    regime = regime_status["regime"]

    # Allocation targets
    from backend.strategies.multi_engine import REGIME_TARGETS
    from backend.strategies.regime import Regime
    regime_enum = Regime(regime)
    targets = REGIME_TARGETS.get(regime_enum, {})
    total_exposure = targets.get("total", 0)

    # Get prices (from broker or saved data)
    prices = me._fetch_prices()

    # Get today's returns for entry filter
    today_returns = me._fetch_today_returns(prices) if prices else {}

    # Compute reversal scores for both universes
    ds = HistoricalDataService()
    if me.kite:
        ds.set_kite(me.kite)

    largecap_scores = compute_reversal_scores(NIFTY_50, prices, ds)
    midcap_scores = compute_reversal_scores(NIFTY_100_EXTRA, prices, ds)

    # Determine actual data date (from saved candle files)
    from backend.utils.time_utils import is_market_open
    data_date = None
    try:
        sample_df = ds.load_candles("RELIANCE", "1d")
        if not sample_df.empty:
            last_ts = sample_df["timestamp"].iloc[-1]
            if hasattr(last_ts, "date"):
                data_date = str(last_ts.date())
            else:
                data_date = str(last_ts)[:10]
    except Exception:
        pass
    market_open = is_market_open()
    has_live_prices = me.kite is not None and market_open

    # Get held symbols
    held_symbols = set()
    for engine_state in me.engine_states.values():
        for batch in engine_state.positions:
            for stock in batch["stocks"]:
                held_symbols.add(stock["symbol"])

    # Check kill switches
    rolling_ic = me._compute_rolling_ic(prices) if prices else None
    ic_killed = rolling_ic is not None and rolling_ic < -0.02

    # Build response for each stock
    stocks = []

    for universe, score_df, config_name, top_n in [
        ("largecap", largecap_scores, "largecap", 7),
        ("midcap", midcap_scores, "midcap", 5),
    ]:
        if score_df.empty:
            continue

        for rank_idx, (symbol, row) in enumerate(score_df.iterrows()):
            is_top = rank_idx < top_n
            is_held = symbol in held_symbols
            today_ret = today_returns.get(symbol, 0)
            panic_drop = today_ret < -0.05

            # Determine action
            if is_held:
                action = "HELD"
                reason = "Currently in portfolio"
            elif ic_killed:
                action = "BLOCKED"
                reason = f"Kill switch: IC={rolling_ic:.4f}"
            elif total_exposure <= 0.08:
                action = "BLOCKED"
                reason = f"Regime {regime} — minimal allocation ({total_exposure*100:.0f}%)"
            elif panic_drop:
                action = "SKIP"
                reason = f"Down {today_ret*100:.1f}% today (panic filter)"
            elif is_top:
                action = "BUY"
                reason = f"Top {top_n} oversold in {universe}"
            else:
                action = "WATCH"
                reason = f"Rank #{rank_idx+1} — below top {top_n} cutoff"

            stocks.append({
                "symbol": symbol,
                "universe": universe,
                "score": round(float(row["score"]), 4),
                "ret_5d": round(float(row["ret_5d"]) * 100, 2),
                "ret_10d": round(float(row["ret_10d"]) * 100, 2),
                "ret_21d": round(float(row["ret_21d"]) * 100, 2),
                "price": round(float(row["price"]), 2),
                "rank": rank_idx + 1,
                "action": action,
                "reason": reason,
                "today_return": round(today_ret * 100, 2) if today_ret else 0,
            })

    # Sort by score descending
    stocks.sort(key=lambda s: s["score"], reverse=True)

    buy_count = sum(1 for s in stocks if s["action"] == "BUY")
    held_count = sum(1 for s in stocks if s["action"] == "HELD")
    blocked_count = sum(1 for s in stocks if s["action"] == "BLOCKED")

    return {
        "stocks": stocks,
        "regime": {
            "current": regime,
            "pending": regime_status.get("pending"),
            "pending_days": regime_status.get("pending_days", 0),
            "total_exposure": round(total_exposure * 100, 1),
        },
        "kill_switch": {
            "ic_killed": ic_killed,
            "rolling_ic": round(rolling_ic, 4) if rolling_ic is not None else None,
        },
        "data_source": {
            "market_open": market_open,
            "live_prices": has_live_prices,
            "data_date": data_date,
            "source": "Zerodha (real-time)" if has_live_prices else f"Last close ({data_date})" if data_date else "Saved data",
        },
        "summary": {
            "total_stocks": len(stocks),
            "buy_signals": buy_count,
            "held_positions": held_count,
            "blocked": blocked_count,
            "generated_at": datetime.now().isoformat(),
        },
    }


@router.get("/history")
async def get_prediction_history(limit: int = 10):
    """Get list of past prediction sessions (date-wise cards)."""
    try:
        from backend.db.database import get_session
        from backend.db.repository import PredictionRepository

        with get_session() as session:
            repo = PredictionRepository(session)
            return {"sessions": repo.get_sessions(limit=limit)}
    except Exception as e:
        logger.warning(f"Failed to read prediction history: {e}")
        return {"sessions": []}


@router.get("/history/{session_id}")
async def get_prediction_session(session_id: str):
    """Get all predictions for a specific session."""
    try:
        from backend.db.database import get_session
        from backend.db.repository import PredictionRepository

        with get_session() as session:
            repo = PredictionRepository(session)
            records = repo.get_by_session(session_id)
            if not records:
                raise HTTPException(status_code=404, detail="Session not found")
            return {
                "session_id": session_id,
                "predictions": [
                    {
                        "symbol": r.symbol,
                        "direction": r.direction,
                        "probability": r.probability,
                        "confidence": r.confidence,
                        "prob_up": r.prob_up,
                        "prob_down": r.prob_down,
                        "prob_neutral": r.prob_neutral,
                        "should_trade": r.should_trade,
                        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    }
                    for r in records
                ],
                "total": len(records),
                "generated_at": records[0].timestamp.isoformat() if records else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Failed to read session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read session")
