"""
SIA-TradeX: Google Gemini AI Intelligence Engine
Thread-safe Token Bucket rate limiter, structured Pydantic outputs, and anti-429 backoff.
"""

import time
import json
import re
import hashlib
import threading
from typing import Optional, Dict, Any, List
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
import google.generativeai as genai
from config.settings import settings
from core.models import (
    AISignalDecision, AISmartExitDecision, MarketContext,
    MarketRegime, Direction
)


class TokenBucketRateLimiter:
    """
    Strict token-bucket rate limiter to prevent HTTP 429 quota exhaustion.
    Guarantees calls stay below Gemini free-tier RPM limits across all worker threads.
    """
    def __init__(self, max_rpm: int = 14):
        self.capacity = float(max_rpm)
        self.tokens = float(max_rpm)
        self.fill_rate = float(max_rpm) / 60.0  # Tokens per second
        self.last_update = time.time()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 60.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                now = time.time()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + (elapsed * self.fill_rate))
                self.last_update = now

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True

            time.sleep(0.5)
        return False


class GeminiService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model_name = settings.GEMINI_MODEL
        self.ok = bool(self.api_key and self.api_key != "YOUR_GEMINI_KEY_HERE")
        self.model = None
        self.limiter = TokenBucketRateLimiter(max_rpm=settings.GEMINI_MAX_RPM)
        self._cache_lock = threading.Lock()
        self._cache: Dict[str, Tuple[Any, float]] = {}

        if self.ok:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(self.model_name)
            except Exception:
                self.ok = False

    def _clean_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Strips markdown and parses valid JSON from LLM output."""
        if not text:
            return None
        cleaned = re.sub(r"```(?:json)?\n?", "", text).strip()
        cleaned = cleaned.rstrip("`").strip()
        
        # Locate the outermost JSON brackets
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)

        try:
            return json.loads(cleaned)
        except Exception:
            return None

    def evaluate_signal(
        self,
        symbol: str,
        direction_hint: str,
        ctx: MarketContext,
        catalysts: Optional[List[str]] = None
    ) -> AISignalDecision:
        """
        Evaluates a trading candidate with market context, trend indicators, and news catalysts.
        """
        fallback = AISignalDecision(
            signal=direction_hint if direction_hint in ("LONG", "SHORT") else "IGNORE",
            confidence=50,
            regime=ctx.regime.value if ctx.regime else "UNKNOWN",
            reason="AI fallback (rate-limit / service unavailable)",
            key_drivers=["Technical Confluence"]
        )

        if not self.ok or not self.model:
            return fallback

        # Cache key based on symbol, direction, and rounded price level
        cache_key = hashlib.md5(
            f"eval_{symbol}_{direction_hint}_{round(ctx.price, 2)}_{ctx.regime}".encode()
        ).hexdigest()

        with self._cache_lock:
            hit = self._cache.get(cache_key)
            if hit and time.time() < hit[1]:
                return hit[0]

        # Rate-limiter acquisition
        if not self.limiter.acquire(timeout=5.0):
            return fallback

        catalysts_str = "; ".join(catalysts[:2]) if catalysts else "None"
        prompt = f"""You are an elite quantitative crypto hedge fund AI.
Analyze the setup for {symbol} (Hint: {direction_hint}).

MARKET CONTEXT:
Price: ${ctx.price:,.4f}
Market Regime: {ctx.regime.value}
1h Trend: {ctx.momentum_1h or 'neutral'} | 4h Trend: {ctx.momentum_4h or 'neutral'}
RSI 1h: {ctx.rsi_1h or 'N/A'} | RSI 5m: {ctx.rsi_5m or 'N/A'}
VWAP: {'ABOVE' if ctx.price > (ctx.vwap or 0) else 'BELOW'} (VWAP: {ctx.vwap or 'N/A'})
Funding Rate: {f'{ctx.funding_rate:.5f}' if ctx.funding_rate is not None else 'N/A'}
Order Book Imbalance: {f'{ctx.order_book_imbalance:+.2f}' if ctx.order_book_imbalance is not None else 'N/A'}
Breakout State: {ctx.breakout or 'none'}
Recent Catalysts: {catalysts_str}

DECISION RULES:
- Output JSON strictly matching this schema:
  {{
    "signal": "LONG" | "SHORT" | "IGNORE",
    "confidence": integer (0 to 100),
    "regime": "TRENDING_BULL" | "TRENDING_BEAR" | "RANGING" | "HIGH_VOLATILITY",
    "reason": "concise explanation under 100 characters",
    "key_drivers": ["factor 1", "factor 2"]
  }}
- Vote IGNORE if indicators heavily contradict or RSI is extreme (>80 for Long, <20 for Short).
- Output raw JSON only with NO markdown fences.
"""
        try:
            resp = self.model.generate_content(prompt)
            data = self._clean_json_response(resp.text)
            if not data:
                return fallback

            decision = AISignalDecision(**data)
            with self._cache_lock:
                self._cache[cache_key] = (decision, time.time() + 60.0)
            return decision

        except Exception:
            return fallback

    def evaluate_smart_exit(
        self,
        symbol: str,
        direction: str,
        entry: float,
        current_price: float,
        pnl_pct: float,
        age_minutes: float,
        ctx: MarketContext
    ) -> AISmartExitDecision:
        """
        Evaluates an active position to determine if it should be closed early due to momentum failure.
        """
        fallback = AISmartExitDecision(action="HOLD", confidence=50, reason="Default hold")
        if not self.ok or not self.model:
            return fallback

        # Don't ask Gemini if position is in solid profit and momentum is still aligned
        if pnl_pct > 0.4 and ctx.momentum_1h == direction:
            return fallback

        if not self.limiter.acquire(timeout=3.0):
            return fallback

        prompt = f"""Position Health Monitor:
Symbol: {symbol} | Direction: {direction}
Entry: ${entry:,.4f} | Current: ${current_price:,.4f}
Unrealized PnL: {pnl_pct:+.2f}% | Age: {age_minutes:.0f} mins
1h Trend: {ctx.momentum_1h or 'neutral'}
RSI 5m: {ctx.rsi_5m or 'N/A'} | Order Book Imbalance: {f'{ctx.order_book_imbalance:+.2f}' if ctx.order_book_imbalance is not None else 'N/A'}

TASK:
Should this position HOLD or EXIT immediately?
Only exit if momentum has severely reversed or high probability of stop loss hit.

JSON only:
{{
  "action": "HOLD" | "EXIT",
  "confidence": integer (0-100),
  "reason": "short explanation"
}}
"""
        try:
            resp = self.model.generate_content(prompt)
            data = self._clean_json_response(resp.text)
            if not data:
                return fallback
            return AISmartExitDecision(**data)
        except Exception:
            return fallback


gemini_service = GeminiService()
