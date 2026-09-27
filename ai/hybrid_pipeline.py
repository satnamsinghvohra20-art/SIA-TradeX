"""
SIA-TradeX Pro: Two-Tier Decoupled AI Pipeline
Tier-1 Local Micro-Classifier (<200 µs hot path) + Tier-2 Asynchronous Gemini Reasoner.
"""

import time
import threading
from typing import Dict, Any, Optional, Tuple
from core.models import MarketContext, AISignalDecision
from ai.gemini_service import gemini_service


class HybridAIPipeline:
    def __init__(self):
        self.gemini = gemini_service
        self._macro_bias_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()

    def tier1_fast_gate(self, symbol: str, direction: str, ctx: MarketContext) -> Tuple[bool, int, str]:
        """
        Tier-1 Local Hot Path: Evaluates microstructural and technical features in <200 microseconds.
        Returns: (approved, score_bonus, reason)
        """
        score = 0
        reasons = []

        # 1. Macro cache check from Tier-2 background AI
        with self._cache_lock:
            cached_ai = self._macro_bias_cache.get(symbol)

        if cached_ai:
            if cached_ai.get("signal") == direction and cached_ai.get("confidence", 0) >= 65:
                score += 2
                reasons.append(f"AI Tier-2 Concurrence ({cached_ai.get('confidence')}%)")
            elif cached_ai.get("signal") == "IGNORE":
                return False, 0, f"AI Tier-2 Veto: {cached_ai.get('reason')}"

        # 2. Microstructural Momentum
        if ctx.momentum_1h == direction:
            score += 1
            reasons.append(f"1h Trend ({direction})")

        # 3. Order Book Depth Support
        if ctx.order_book_imbalance is not None:
            if direction == "LONG" and ctx.order_book_imbalance > 0.10:
                score += 1
                reasons.append("Top-of-book bid depth")
            elif direction == "SHORT" and ctx.order_book_imbalance < -0.10:
                score += 1
                reasons.append("Top-of-book ask pressure")

        # 4. RSI Boundary Guard
        if ctx.rsi_1h is not None:
            if direction == "LONG" and ctx.rsi_1h > 72.0:
                return False, 0, f"RSI {ctx.rsi_1h:.0f} overbought"
            elif direction == "SHORT" and ctx.rsi_1h < 28.0:
                return False, 0, f"RSI {ctx.rsi_1h:.0f} oversold"

        approved = score >= 1
        return approved, score, " | ".join(reasons) if reasons else "Fast-gate approved"

    def tier2_async_update(self, symbol: str, ctx: MarketContext):
        """
        Tier-2 Background Task: Queries Gemini 2.5 Flash asynchronously.
        Never blocks the execution hot path.
        """
        def _task():
            decision = self.gemini.evaluate_signal(symbol, "LONG", ctx)
            with self._cache_lock:
                self._macro_bias_cache[symbol] = {
                    "signal": decision.signal,
                    "confidence": decision.confidence,
                    "regime": decision.regime,
                    "reason": decision.reason,
                    "updated_at": time.time()
                }

        threading.Thread(target=_task, daemon=True, name=f"tier2_ai_{symbol}").start()


hybrid_ai = HybridAIPipeline()
