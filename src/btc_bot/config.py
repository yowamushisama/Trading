"""
Central configuration — loaded once at startup, validated strictly.
All settings flow from environment variables (and .env file).
No config file is parsed here; strategy yaml files are loaded by each strategy module.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(str, Enum):
    backtest = "backtest"
    paper_local = "paper_local"
    paper_testnet = "paper_testnet"
    live = "live"


class LLMProvider(str, Enum):
    anthropic = "anthropic"
    openai = "openai"
    groq = "groq"
    none = "none"


class NewsTagger(str, Enum):
    keyword = "keyword"
    llm = "llm"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Mode ──────────────────────────────────────────────────────
    mode: Mode = Mode.paper_local
    symbol: str = "BTC/USDT"
    exchange: str = "binance"
    binance_testnet: bool = False

    # ── Binance API Keys ──────────────────────────────────────────
    live_api_key: str = ""
    live_api_secret: str = ""
    testnet_api_key: str = ""
    testnet_api_secret: str = ""

    # ── Live Safety Gates ─────────────────────────────────────────
    live_trading_enabled: bool = False
    i_understand_live_trading_risk: bool = False

    # ── Database ──────────────────────────────────────────────────
    database_url: str = ""

    # ── LLM ───────────────────────────────────────────────────────
    llm_provider: LLMProvider = LLMProvider.none
    llm_model: str = "claude-opus-4-7"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""

    # ── News ──────────────────────────────────────────────────────
    cryptopanic_token: str = ""
    news_tagger: NewsTagger = NewsTagger.keyword
    news_cooldown_minutes: int = 30

    # ── Capital ───────────────────────────────────────────────────
    paper_capital_usdt: float = Field(10_000.0, gt=0)
    live_capital_cap_usdt: float = Field(0.0, ge=0)  # 0 = use full account balance

    # ── Risk ──────────────────────────────────────────────────────
    risk_per_trade_pct: float = Field(0.0025, gt=0, le=0.02)
    daily_loss_cap_pct: float = Field(0.015, gt=0, le=0.10)
    weekly_loss_cap_pct: float = Field(0.04, gt=0, le=0.20)
    max_consec_losses: int = Field(3, ge=1)
    consec_loss_cooldown_hours: int = Field(4, ge=1)
    max_open_positions: int = Field(1, ge=1)
    atr_stop_k: float = Field(1.5, gt=0)
    min_rr: float = Field(1.5, gt=0)
    fee_per_side_pct: float = Field(0.00075, gt=0)
    slippage_buffer_bps: float = Field(5.0, ge=0)
    allow_market_orders: bool = False

    # ── Execution ─────────────────────────────────────────────────
    protection_timeout_seconds: int = Field(5, ge=1)
    stale_order_seconds_scalper: int = Field(30, ge=5)
    stale_order_seconds_swing: int = Field(300, ge=30)
    reconciler_interval_seconds: int = Field(30, ge=5)

    # ── Strategies ────────────────────────────────────────────────
    strategies_enabled: str = "scalper,swing"

    # ── Halt ──────────────────────────────────────────────────────
    halt_file_path: str = "./HALT"
    halt: bool = False

    # ── Logging ───────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_file: str = "logs/bot.log"

    # ── Derived helpers ───────────────────────────────────────────
    @property
    def strategies_list(self) -> list[str]:
        return [s.strip() for s in self.strategies_enabled.split(",") if s.strip()]

    @property
    def fee_round_trip_pct(self) -> float:
        return self.fee_per_side_pct * 2

    @property
    def slippage_buffer_pct(self) -> float:
        return self.slippage_buffer_bps / 10_000

    @property
    def api_key(self) -> str:
        return self.testnet_api_key if self.binance_testnet else self.live_api_key

    @property
    def api_secret(self) -> str:
        return self.testnet_api_secret if self.binance_testnet else self.live_api_secret

    # ── Validators ────────────────────────────────────────────────
    @model_validator(mode="after")
    def _validate_live_gates(self) -> "Settings":
        if self.mode == Mode.live:
            if not self.live_trading_enabled:
                raise ValueError(
                    "Live trading blocked: set LIVE_TRADING_ENABLED=true to proceed."
                )
            if not self.i_understand_live_trading_risk:
                raise ValueError(
                    "Live trading blocked: set I_UNDERSTAND_LIVE_TRADING_RISK=true to proceed."
                )
            if not self.live_api_key or self.live_api_key == "your_live_api_key_here":
                raise ValueError("Live trading blocked: LIVE_API_KEY not set.")
        return self

    @model_validator(mode="after")
    def _validate_database(self) -> "Settings":
        if self.mode != Mode.backtest and not self.database_url:
            raise ValueError(
                f"DATABASE_URL is required for mode={self.mode.value}. "
                "Set it to your Supabase Postgres connection string."
            )
        return self

    @field_validator("risk_per_trade_pct")
    @classmethod
    def _warn_high_risk(cls, v: float) -> float:
        if v > 0.005:
            raise ValueError(
                f"risk_per_trade_pct={v:.4%} exceeds 0.5% — "
                "hardcoded safety limit. Edit this validator if you truly intend this."
            )
        return v


def get_settings() -> Settings:
    """Return a validated Settings instance. Call once at startup."""
    return Settings()
