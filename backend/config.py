"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main application settings."""

    # Zerodha Kite Connect API
    kite_api_key: str = Field(..., description="Kite Connect API key")
    kite_api_secret: str = Field(..., description="Kite Connect API secret")

    # Environment
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    log_level: str = "INFO"

    # Trading
    trading_mode: Literal["paper", "live"] = "paper"
    paper_trading_capital: float = 100000.0

    # Database
    database_url: str = "postgresql://postgres:password@localhost:5432/trader"

    # CORS
    cors_origins: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Risk Management
    max_position_pct: float = 0.05
    max_total_exposure: float = 0.20
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10
    trade_cooldown_secs: int = 60
    max_trades_per_day: int = 20

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Merge default localhost origins with any extra origins from env."""
        defaults = ["http://localhost:3000", "http://127.0.0.1:3000"]
        if not self.cors_origins:
            return defaults
        extra = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return list(dict.fromkeys(defaults + extra))

    @property
    def is_paper_mode(self) -> bool:
        return self.trading_mode == "paper"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
