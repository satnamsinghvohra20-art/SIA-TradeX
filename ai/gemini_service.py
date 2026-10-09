import os
import time
import json
import re
import hashlib
import threading
import logging
from typing import Optional, Dict, Any, List, Tuple
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
import google.generativeai as genai
from config.settings import settings
from core.models import (
    AISignalDecision, AISmartExitDecision, MarketContext,
    MarketRegime, Direction
)

logger = logging.getLogger("SIA-TradeX.AI")


class GeminiKeyRotator:
    """
    Multi-Key Pool for Google Gemini API.
    Discovers all available keys from:
    - GEMINI_API_KEY (single or comma-separated)
    - GEMINI_API_KEYS (comma or space separated)
    - GEMINI_API_KEY_1 .. GEMINI_API_KEY_25
    Automatically rotates to the next key on HTTP 429 or quota exhaustion.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.keys: List[str] = self._discover_keys()
        self.current_idx: int = 0
        self.rotations_count: int = 0
        self.cooldowns: Dict[str, float] = {}

    def _discover_keys(self) -> List[str]:
        found: List[str] = []
        raw_single = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        if raw_single and raw_single != "YOUR_GEMINI_KEY_HERE" and raw_single != "your_gemini_key_here":
            for k in raw_single.replace(";", ",").replace("\n", ",").split(","):
                k = k.strip()
                if k and k not in found and len(k) > 10:
                    found.append(k)

        raw_multi = getattr(settings, "GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEYS", "")
        if raw_multi:
            for k in raw_multi.replace(";", ",").replace("\n", ",").split(","):
                k = k.strip()
                if k and k not in found and len(k) > 10:
                    found.append(k)

        for i in range(1, 26):
            k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
            if k and k not in found and len(k) > 10:
                found.append(k)

        return found

    def get_current_key(self) -> Optional[str]:
        with self._lock:
            if not self.keys:
                return None
            return self.keys[self.current_idx % len(self.keys)]

    def rotate(self, reason: str = "Quota limit hit") -> Optional[str]:
        with self._lock:
            if not self.keys:
                return None
            old_idx = self.current_idx
            self.current_idx = (self.current_idx + 1) % len(self.keys)
            self.rotations_count += 1
            new_key = self.keys[self.current_idx]
            logger.warning(f"[GeminiRotator] Rotated key from index {old_idx+1} to {self.current_idx+1}/{len(self.keys)}. Reason: {reason}")
            return new_key

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_keys": len(self.keys),
                "active_key_index": (self.current_idx + 1) if self.keys else 0,
                "rotations_count": self.rotations_count,
                "has_keys": len(self.keys) > 0
            }


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
        self.rotator = GeminiKeyRotator()
        configured_model = settings.GEMINI_MODEL
        # Normalize model string: replace hallucinated 'gemini-2.5-flash' with supported official model
        if "2.5" in configured_model:
            configured_model = "gemini-1.5-flash"
        self.model_name = configured_model
        self.model = None
        self.ok = False
        self.limiter = TokenBucketRateLimiter(max_rpm=settings.GEMINI_MAX_RPM)
        self._cache_lock = threading.Lock()
        self._cache: Dict[str, Tuple[Any, float]] = {}

        self._configure_active_key()

    def _configure_active_key(self):
        key = self.rotator.get_current_key()
        if key:
            try:
                genai.configure(api_key=key)
                self.model = genai.GenerativeModel(self.model_name)
                self.ok = True
            except Exception as e:
                logger.error(f"[Gemini] Configuration error with key: {e}")
                self.ok = False
        else:
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
        prompt = f"""You are an elite quantitative crypto hedge fund AI and risk management specialist.
Analyze the setup for {symbol} (Directional Hint: {direction_hint}).

MARKET CONTEXT:
Price: ${ctx.price:,.4f}
Market Regime: {ctx.regime.value}
1h Trend: {ctx.momentum_1h or 'neutral'} | 4h Trend: {ctx.momentum_4h or 'neutral'}
RSI 1h: {ctx.rsi_1h or 'N/A'} | RSI 5m: {ctx.rsi_5m or 'N/A'}
VWAP: {'ABOVE' if ctx.price > (ctx.vwap or 0) else 'BELOW'} (VWAP: {ctx.vwap or 'N/A'})
Funding Rate: {f'{ctx.funding_rate:.5f}' if ctx.funding_rate is not None else 'N/A'}
Order Book Imbalance: {f'{ctx.order_book_imbalance:+.2f}' if ctx.order_book_imbalance is not None else 'N/A'}
TTM Volatility Squeeze: {'COMPRESSED (WAIT FOR BREAKOUT)' if ctx.squeeze_on else f'EXPANDING (Momentum {ctx.squeeze_momentum})'}
Smart Money Liquidity Sweep: {ctx.liquidity_sweep or 'None'}
ADX Trend Strength: {ctx.adx or 'N/A'} (>=25 strong trend, <20 choppy)
Breakout State: {ctx.breakout or 'none'}
Recent Catalysts: {catalysts_str}

INSTITUTIONAL QUANTITATIVE RULES:
1. HIGH PROBABILITY ONLY: Only approve LONG or SHORT when multi-timeframe trend aligns and there is an asymmetric mathematical edge.
2. CAPITAL PRESERVATION: If market is compressed inside Squeeze or ADX < 20 (choppy sideways range without liquidity sweep), vote IGNORE to prevent whipsaws.
3. SMART MONEY CONFLUENCE: If a Bullish or Bearish Liquidity Sweep occurred, prioritize trading the absorption bounce with high confidence.
4. Output JSON strictly matching this schema:
  {{
    "signal": "LONG" | "SHORT" | "IGNORE",
    "confidence": integer (0 to 100),
    "regime": "TRENDING_BULL" | "TRENDING_BEAR" | "RANGING" | "HIGH_VOLATILITY",
    "reason": "concise explanation under 100 characters",
    "key_drivers": ["factor 1", "factor 2"]
  }}
- Vote IGNORE if indicators contradict or RSI is extreme (>80 for Long, <20 for Short).
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

        except Exception as e:
            err_str = str(e)
            logger.warning(f"[Gemini] API error during signal eval for {symbol}: {err_str}")
            if any(k in err_str.lower() for k in ["429", "resourceexhausted", "quota", "invalid", "permission"]):
                self.rotator.rotate(err_str)
                self._configure_active_key()
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
        except Exception as e:
            err_str = str(e)
            logger.warning(f"[Gemini] API error during smart exit eval for {symbol}: {err_str}")
            if any(k in err_str.lower() for k in ["429", "resourceexhausted", "quota"]):
                self.rotator.rotate(err_str)
                self._configure_active_key()
            return fallback


gemini_service = GeminiService()
