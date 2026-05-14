"""Configuration loader. All secrets live in .env — never hardcode."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


# Per-asset bid/ask thresholds (fraction of mid).
BID_ASK_THRESHOLDS: dict[str, float] = {
    "ZN": 0.05, "ZF": 0.05, "ZB": 0.05, "ZT": 0.05, "TN": 0.05, "UB": 0.05,
    "ES": 0.05, "NQ": 0.05,
    "RTY": 0.10, "CL": 0.10, "GC": 0.10,
    "SI": 0.15, "HG": 0.15, "NG": 0.15,
    "VX": 0.20, "6E": 0.20, "6J": 0.20, "6B": 0.20, "6A": 0.20, "6C": 0.20, "6S": 0.20,
    # ETFs (equity options)
    "EEM": 0.05, "SPY": 0.05, "QQQ": 0.05, "IWM": 0.05,
    "FXI": 0.05, "GLD": 0.05, "TLT": 0.05, "XLF": 0.05,
    "XLE": 0.05, "XLK": 0.05, "HYG": 0.05, "LQD": 0.05,
}

SUPPORTED_ROOTS = set(BID_ASK_THRESHOLDS.keys())

# ETFs use STK secType, not FUT
ETF_ROOTS = {"EEM", "SPY", "QQQ", "IWM", "FXI", "GLD", "TLT", "XLF",
             "XLE", "XLK", "HYG", "LQD"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Primary LLM (Grok) ---
    xai_api_key: str = ""
    grok_model: str = "grok-4.1"
    grok_base_url: str = "https://api.x.ai/v1"
    grok_thinking: bool = True

    # --- Validator (Opus) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-7"
    extended_thinking: bool = True
    thinking_budget_tokens: int = 8000

    # --- News ---
    gdelt_enabled: bool = True
    newsapi_key: str = ""
    reuters_api_key: str = ""

    # --- Macro ---
    fred_api_key: str = ""
    fmp_api_key: str = ""

    # --- Markets ---
    cme_api_key: str = ""
    cme_api_secret: str = ""
    ibkr_enabled: bool = False
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 12

    # --- Data layer ---
    db_url: str = ""          # postgresql://... — overrides db_path when set
    redis_url: str = "redis://localhost:6379/0"
    db_path: str = "./data/macro_scout.db"  # SQLite fallback

    # --- Modes ---
    paper_mode: bool = True
    allow_live_trading: bool = False
    mock_data: bool = False
    allow_0dte: bool = Field(default=False, alias="ALLOW_0DTE")

    # --- Headline rules ---
    max_headline_age_hours: int = 24

    # --- Trade rules ---
    min_spread_rr: float = 2.0
    min_option_volume: int = 50
    min_open_interest: int = 100
    yolo_max_premium_dollars: float = 500.0

    # --- Sizing ---
    default_account_size: float | None = None
    default_risk_per_spread_pct: float = 0.50
    default_risk_per_yolo_pct: float = 0.25

    # --- Caching (minutes) ---
    cache_headlines_min: int = 30
    cache_regime_min: int = 60
    cache_chain_min: int = 5

    # --- Quote freshness ---
    max_chain_staleness_min: int = 1440

    # --- Risk profile selection ---
    default_risk_profile: Literal["conservative", "balanced", "aggressive", "yolo"] = "balanced"

    @field_validator("default_account_size", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v

    @property
    def has_grok(self) -> bool:
        return bool(self.xai_api_key) and not self.mock_data

    @property
    def has_opus(self) -> bool:
        return bool(self.anthropic_api_key) and not self.mock_data

    @property
    def fixtures_dir(self) -> Path:
        return REPO_ROOT / "fixtures"

    def bid_ask_threshold(self, root: str) -> float:
        return BID_ASK_THRESHOLDS.get(root.upper(), 0.10)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
