"""Application configuration using Pydantic Settings."""

from functools import lru_cache
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
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

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
