"""Configuration loader. All secrets live in .env — never hardcode."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


# Per-asset bid/ask thresholds (fraction of mid). Replaces single MAX_BID_ASK_PCT.
BID_ASK_THRESHOLDS: dict[str, float] = {
    "ZN": 0.05, "ZF": 0.05, "ZB": 0.05, "ZT": 0.05, "TN": 0.05, "UB": 0.05,
    "ES": 0.05, "NQ": 0.05,
    "RTY": 0.10, "CL": 0.10, "GC": 0.10,
    "SI": 0.15, "HG": 0.15, "NG": 0.15,
    "VX": 0.20, "6E": 0.20, "6J": 0.20, "6B": 0.20, "6A": 0.20, "6C": 0.20, "6S": 0.20,
}

SUPPORTED_ROOTS = set(BID_ASK_THRESHOLDS.keys())


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

    # --- Storage ---
    db_path: str = "./data/macro_scout.db"

    # --- Risk profile selection (overridable per poke) ---
    default_risk_profile: Literal["conservative", "balanced", "aggressive", "yolo"] = "balanced"

    # ---------- helpers ----------
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
