"""
SIA-TradeX: Configuration & Settings Module
Typed settings with environment variable support, validation, and defaults.
"""

import os
from pathlib import Path
from typing import Dict, List, Set, Tuple
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env from current directory or subfolder
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
if not os.getenv("BINANCE_API_KEY") and (BASE_DIR / "bot_v13_fixed" / ".env").exists():
    load_dotenv(BASE_DIR / "bot_v13_fixed" / ".env")


class Settings(BaseSettings):
    # System & Execution Mode
    PROJECT_NAME: str = "SIA-TradeX Pro"
    VERSION: str = "2.0.0-QUANT"
    PAPER_MODE: bool = True
    BOT_LOG_LEVEL: str = "INFO"
    WEB_PORT: int = 8080
    WEB_HOST: str = "0.0.0.0"

    # Binance API Configuration
    BINANCE_API_KEY: str = Field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    BINANCE_API_SECRET: str = Field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))
    BINANCE_TESTNET: bool = Field(
        default_factory=lambda: os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("true", "1", "yes")
    )
    BINANCE_FAPI_MAIN: str = "https://fapi.binance.com"
    BINANCE_FAPI_TEST: str = "https://testnet.binancefuture.com"
    BINANCE_WS_MAIN: str = "wss://fstream.binance.com/ws"
    BINANCE_WS_TEST: str = "wss://stream.binancefuture.com/ws"

    # AI Configuration (Gemini)
    GEMINI_API_KEY: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_MAX_RPM: int = 14  # Max 14 requests/min to strictly respect 15 RPM free tier
    GEMINI_AUTO_TRADE: bool = True
    GEMINI_AUTO_SCAN_SEC: int = 25
    GEMINI_AUTO_MIN_CONF: int = 65
    GEMINI_VETO: bool = True
    GEMINI_SYMBOL_COOLDOWN: int = 90

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    TELEGRAM_CHAT_ID: str = Field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    TG_POLL_INTERVAL: float = 2.0

    # NewsAPI
    NEWS_API_KEY: str = Field(default_factory=lambda: os.getenv("NEWS_API_KEY", ""))
    NEWS_API_BASE: str = "https://newsapi.org/v2"
    NEWS_SCAN_INTERVAL: int = 60
    NEWS_LOOKBACK_MIN: int = 15
    NEWS_SIGNAL_COOLDOWN: int = 300

    # Polymarket Gamma API
    GAMMA_API: str = "https://gamma-api.polymarket.com"
    POLY_SCAN_INTERVAL: int = 4
    POLY_SPIKE_THRESHOLD: float = 0.03
    POLY_SPIKE_WINDOW_SEC: int = 120
    POLY_FETCH_LIMIT: int = 300

    # Quantitative Risk & Position Sizing
    DEFAULT_LEVERAGE: int = 3
    PAPER_STARTING_BALANCE: float = 1000.0
    RISK_PER_TRADE_PCT: float = 1.5      # 1.5% capital risked per trade
    MIN_TRADE_USDT: float = 10.0
    MAX_TRADE_USDT: float = 65.0
    MAX_OPEN_TRADES: int = 6
    MAX_PORTFOLIO_HEAT: float = 0.50     # Max 50% capital committed in margins

    # Circuit Breakers
    DAILY_LOSS_LIMIT: float = 50.0       # Max $50 loss in 24h before automatic circuit break
    DAILY_PROFIT_TARGET: float = 150.0   # Stop taking new entries once target is secured
    MAX_CONSECUTIVE_LOSSES: int = 3
    COOLDOWN_MINUTES: int = 15

    # Strategy Parameters
    USE_ATR_EXITS: bool = True
    ATR_PERIOD: int = 14
    ATR_TP1_MULT: float = 1.2
    ATR_TP2_MULT: float = 4.0
    ATR_SL_MULT: float = 0.75
    FIXED_TP1_PCT: float = 1.2
    FIXED_TP2_PCT: float = 4.0
    FIXED_SL_PCT: float = 0.75

    # Trailing Stop & Profit Protection
    TRAILING_STOP: bool = True
    TRAILING_TRIGGER_PCT: float = 0.60
    TRAILING_DISTANCE_PCT: float = 0.25
    PROFIT_PROTECT_ENABLED: bool = True
    PROFIT_PROTECT_MIN_PNL_USD: float = 0.15
    PROFIT_PROTECT_GIVEBACK_PCT: float = 0.25
    PROFIT_PROTECT_REVERSAL_SCORE: int = 2
    PROFIT_PROTECT_RSI_SWING: float = 4.0

    # Technical Indicators Setup
    RSI_PERIOD: int = 14
    RSI_OVERBOUGHT: float = 70.0
    RSI_OVERSOLD: float = 30.0
    VOL_ATR_LOOKBACK: int = 20
    VOL_MIN_RATIO: float = 0.28
    BREAKOUT_PERIOD: int = 15
    VOLUME_SPIKE_MULT: float = 1.15

    # Signal Score Thresholds
    MIN_SIGNAL_SCORE: int = 5
    MAX_SIGNAL_SCORE: int = 8

    # Symbol Universe
    ACTIVE_SYMBOLS: List[str] = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT",
        "DOGEUSDT", "AVAXUSDT", "ADAUSDT"
    ]

    CORRELATION_GROUPS: Dict[str, Set[str]] = {
        "btc_group": {"BTCUSDT"},
        "eth_group": {"ETHUSDT", "ARBUSDT", "OPUSDT"},
        "l1_group":  {"SOLUSDT", "AVAXUSDT", "NEARUSDT", "SUIUSDT"},
        "meme_group": {"DOGEUSDT", "PEPEUSDT"},
    }
    CORRELATION_LIMIT_PCT: float = 0.50

    # Database
    DB_PATH: str = str(BASE_DIR / "sia_tradex.db")

    class Config:
        arbitrary_types_allowed = True


settings = Settings()
