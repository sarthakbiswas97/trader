"""
Pipeline Service - Automated data download, feature generation, and model training.

Checks if model exists / is stale and runs the full pipeline if needed.
Exposes progress state for frontend polling.
"""

import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from backend.core.logger import get_logger
from backend.core.symbols import NIFTY_50
from backend.ml.labeling import DEFAULT_FEATURES_PATH

logger = get_logger(__name__)


# =============================================================================
# Pipeline Progress Tracker (thread-safe singleton)
# =============================================================================

class PipelineProgress:
    """Thread-safe progress tracker for the pipeline."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.running = False
        self.current_step = ""
        self.step_number = 0
        self.total_steps = 3
        self.detail = ""
        self.error = ""
        self.completed = False
        self._initialized = True

    def start(self):
        with self._lock:
            self.running = True
            self.current_step = "checking"
            self.step_number = 0
            self.detail = "Checking pipeline status..."
            self.error = ""
            self.completed = False

    def update(self, step: str, step_number: int, detail: str = ""):
        with self._lock:
            self.current_step = step
            self.step_number = step_number
            self.detail = detail

    def finish(self, error: str = ""):
        with self._lock:
            self.running = False
            self.completed = not error
            self.error = error
            if not error:
                self.current_step = "done"
                self.detail = "Pipeline complete"

    def get_status(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "current_step": self.current_step,
                "step_number": self.step_number,
                "total_steps": self.total_steps,
                "detail": self.detail,
                "error": self.error,
                "completed": self.completed,
            }

    def reset(self):
        with self._lock:
            self.running = False
            self.current_step = ""
            self.step_number = 0
            self.detail = ""
            self.error = ""
            self.completed = False


pipeline_progress = PipelineProgress()

_BACKEND_DIR = Path(__file__).parent.parent
MODEL_DIR = _BACKEND_DIR / "ml" / "models"
MODEL_PATH = MODEL_DIR / "model_latest.joblib"
DATA_DIR = _BACKEND_DIR / "data" / "historical"
FEATURES_PATH = Path(DEFAULT_FEATURES_PATH)




# Model is stale after this many days
MODEL_MAX_AGE_DAYS = 7


def model_exists() -> bool:
    """Check if a trained model exists."""
    return MODEL_PATH.exists()


def model_age_days() -> float | None:
    """Get model age in days, or None if no model."""
    if not MODEL_PATH.exists():
        return None
    mtime = datetime.fromtimestamp(MODEL_PATH.stat().st_mtime)
    return (datetime.now() - mtime).total_seconds() / 86400


def model_is_stale(max_age_days: float = MODEL_MAX_AGE_DAYS) -> bool:
    """Check if model needs retraining."""
    age = model_age_days()
    if age is None:
        return True  # No model = stale
    return age > max_age_days


def has_historical_data(symbols: list[str] = None) -> bool:
    """Check if we have downloaded historical data."""
    symbols = symbols or NIFTY_50
    if not DATA_DIR.exists():
        return False
    # Check if at least half the symbols have 5m data
    found = sum(1 for s in symbols if (DATA_DIR / f"{s}_5m.csv").exists())
    return found >= len(symbols) // 2


def has_features() -> bool:
    """Check if features file exists and is non-empty."""
    return FEATURES_PATH.exists() and FEATURES_PATH.stat().st_size > 100


def get_pipeline_status() -> dict:
    """Get status of each pipeline stage."""
    age = model_age_days()
    return {
        "historical_data": has_historical_data(),
        "features": has_features(),
        "model_exists": model_exists(),
        "model_age_days": round(age, 1) if age is not None else None,
        "model_stale": model_is_stale(),
        "needs_training": not model_exists() or model_is_stale(),
    }


def run_download(kite, symbols: list[str] = None) -> bool:
    """
    Download historical data for all symbols.

    Args:
        kite: Authenticated KiteConnect instance
        symbols: Symbols to download

    Returns:
        True if successful
    """
    symbols = symbols or NIFTY_50

    from backend.services.historical_data import HistoricalDataService

    data_service = HistoricalDataService()
    data_service.set_kite(kite)

    logger.info(f"Downloading historical data for {len(symbols)} symbols...")

    try:
        data_service.download_universe(
            symbols=symbols,
            intervals=["5m", "1h", "1d"],
            days=60,
        )
        logger.info("Historical data download complete")
        return True
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return False


def run_feature_generation(symbols: list[str] = None) -> bool:
    """
    Generate features from downloaded historical data.

    Args:
        symbols: Symbols to generate features for

    Returns:
        True if successful
    """
    symbols = symbols or NIFTY_50

    from backend.services.feature_engine import FeatureEngine
    from backend.services.historical_data import HistoricalDataService

    data_service = HistoricalDataService()
    feature_engine = FeatureEngine(data_service=data_service)

    logger.info(f"Generating features for {len(symbols)} symbols...")

    try:
        df = feature_engine.generate_features_for_universe(symbols, save=True)
        if df.empty:
            logger.error("No features generated")
            return False
        logger.info(f"Generated {len(df)} feature rows")
        return True
    except Exception as e:
        logger.error(f"Feature generation failed: {e}")
        return False


def run_training(half_life_days: float = 45.0, num_classes: int = 3) -> bool:
    """
    Train ML model on generated features.

    Args:
        half_life_days: Decay half-life for sample weighting

    Returns:
        True if successful
    """
    from backend.ml.train_model import train_and_save

    logger.info("Starting model training...")

    try:
        results = train_and_save(
            features_path=DEFAULT_FEATURES_PATH,
            half_life_days=half_life_days,
            num_classes=num_classes,
        )
        logger.info(
            "Training complete",
            accuracy=results["metrics"]["accuracy"],
            f1=results["metrics"]["f1"],
        )
        return True
    except Exception as e:
        logger.error(f"Training failed: {e}")
        return False


def run_full_pipeline(
    kite=None,
    symbols: list[str] = None,
    force: bool = False,
    half_life_days: float = 45.0,
) -> dict:
    """
    Run the full pipeline: download → features → train.

    Skips steps that are already done unless force=True.

    Args:
        kite: Authenticated KiteConnect instance (needed for download)
        symbols: Symbols to process
        force: Force re-run all steps
        half_life_days: Decay half-life for training

    Returns:
        Dict with status of each step
    """
    symbols = symbols or NIFTY_50
    results = {
        "download": "skipped",
        "features": "skipped",
        "training": "skipped",
        "success": False,
    }

    pipeline_progress.start()

    try:
        # Step 1: Download historical data
        if force or not has_historical_data(symbols):
            if kite is None:
                logger.error("Cannot download data: no Kite client provided")
                results["download"] = "error: no kite client"
                pipeline_progress.finish(error="No Kite client for data download")
                return results

            pipeline_progress.update("download", 1, f"Downloading candles for {len(symbols)} symbols...")
            if run_download(kite, symbols):
                results["download"] = "completed"
            else:
                results["download"] = "failed"
                pipeline_progress.finish(error="Data download failed")
                return results
        else:
            logger.info("Step 1/3: Historical data exists, skipping download")
            results["download"] = "skipped"

        # Step 2: Generate features
        if force or not has_features():
            pipeline_progress.update("features", 2, "Computing 17 technical features...")
            if run_feature_generation(symbols):
                results["features"] = "completed"
            else:
                results["features"] = "failed"
                pipeline_progress.finish(error="Feature generation failed")
                return results
        else:
            logger.info("Step 2/3: Features exist, skipping generation")
            results["features"] = "skipped"

        # Step 3: Train model
        if force or not model_exists() or model_is_stale():
            pipeline_progress.update("training", 3, "Training XGBoost model with decay weighting...")
            if run_training(half_life_days):
                results["training"] = "completed"
            else:
                results["training"] = "failed"
                pipeline_progress.finish(error="Model training failed")
                return results
        else:
            logger.info("Step 3/3: Model is fresh, skipping training")
            results["training"] = "skipped"

        results["success"] = True
        pipeline_progress.finish()
        return results

    except Exception as e:
        pipeline_progress.finish(error=str(e))
        raise


def ensure_model_ready(kite=None, symbols: list[str] = None) -> bool:
    """
    Ensure a model is ready for inference.
    Runs the pipeline if needed.

    Args:
        kite: Authenticated KiteConnect instance
        symbols: Symbols to process

    Returns:
        True if model is ready
    """
    if model_exists() and not model_is_stale():
        logger.info("Model is ready (fresh)")
        return True

    if model_exists():
        age = model_age_days()
        logger.info(f"Model is {age:.1f} days old, retraining...")
    else:
        logger.info("No model found, running full pipeline...")

    results = run_full_pipeline(kite=kite, symbols=symbols)
    return results["success"]
