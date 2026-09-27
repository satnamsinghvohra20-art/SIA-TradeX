"""
SIA-TradeX: Core Domain Models & Schemas
Typed models for signals, positions, orders, market context, and AI decisions.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, Field
import time
import hashlib


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"
    IGNORE = "IGNORE"


class MarketRegime(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNKNOWN = "UNKNOWN"


class AISignalDecision(BaseModel):
    """Structured response schema for Google Gemini AI evaluations."""
    signal: Literal["LONG", "SHORT", "IGNORE"] = Field(
        description="The trading verdict: LONG, SHORT, or IGNORE"
    )
    confidence: int = Field(
        ge=0, le=100,
        description="Confidence score from 0 to 100"
    )
    regime: Literal["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "HIGH_VOLATILITY", "UNKNOWN"] = Field(
        default="UNKNOWN",
        description="Assessed macro market regime"
    )
    reason: str = Field(
        max_length=120,
        description="Concise rationale for the decision (under 120 chars)"
    )
    key_drivers: List[str] = Field(
        default_factory=list,
        description="Top 2-3 factors driving this evaluation"
    )


class AISmartExitDecision(BaseModel):
    """Structured response for Smart Exit monitoring."""
    action: Literal["HOLD", "EXIT"] = Field(
        description="Action to take: HOLD or EXIT"
    )
    confidence: int = Field(
        ge=0, le=100,
        description="Confidence percentage"
    )
    reason: str = Field(
        max_length=100,
        description="Short reason why position should hold or close immediately"
    )


class Signal(BaseModel):
    """Normalized multi-source signal."""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    source: str
    reason: str
    score: int = 1
    confidence: int = 50
    manual: bool = False
    size_override: Optional[float] = None
    force: bool = False
    raw_event: Dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)
    id: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            raw = f"{self.symbol}_{self.direction}_{self.source}_{self.ts}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]


class Position(BaseModel):
    """Active open position."""
    id: str = ""
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry: float
    tp: float
    tp2: float
    sl: float
    atr: Optional[float] = None
    qty: float
    usdt_size: float
    reason: str
    sources: List[str] = Field(default_factory=list)
    score: int = 0
    ai_reason: str = ""
    ts: float = Field(default_factory=time.time)
    peak_pnl: float = 0.0
    tp1_done: bool = False
    last_rsi5: Optional[float] = None
    leverage: int = 3

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            raw = f"{self.symbol}_{self.direction}_{self.ts}_{time.time()}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]


class TradeRecord(BaseModel):
    """Completed trade record for journal and database persistence."""
    id: Optional[str] = None
    timestamp: str
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry: float
    exit: float
    pnl: float
    reason: str
    sources: List[str] = Field(default_factory=list)
    score: int = 0
    ai_reason: str = ""
    equity: float = 0.0
    profit_protected: bool = False
    live: bool = False
    leverage: int = 3


class MarketContext(BaseModel):
    """Real-time market context snapshot for a specific symbol."""
    symbol: str
    price: float
    regime: MarketRegime = MarketRegime.UNKNOWN
    momentum_1h: Optional[str] = None
    momentum_4h: Optional[str] = None
    rsi_1h: Optional[float] = None
    rsi_5m: Optional[float] = None
    vwap: Optional[float] = None
    atr: Optional[float] = None
    volatility_ratio: Optional[float] = None
    breakout: Optional[str] = None
    funding_rate: Optional[float] = None
    order_book_imbalance: Optional[float] = None
    volume_confirmed: bool = False
