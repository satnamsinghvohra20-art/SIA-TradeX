"""
SIA-TradeX: Smart Profit Protection Engine
Monitors profitable positions tick-by-tick and locks gains before stop loss or mean-reversal occurs.
"""

from typing import Tuple, List, Optional
from config.settings import settings
from core.models import Position, MarketContext


class ProfitProtector:
    @staticmethod
    def evaluate(
        pos: Position,
        price: float,
        pnl_usd: float,
        ctx: MarketContext
    ) -> Tuple[Optional[str], List[str]]:
        """
        Returns (exit_title, [supporting_reasons]) if position should be locked and closed.
        """
        if not settings.PROFIT_PROTECT_ENABLED:
            return None, []

        # Floor threshold
        if pnl_usd < settings.PROFIT_PROTECT_MIN_PNL_USD:
            return None, []

        reasons = []
        rev_score = 0

        # 1. Peak Giveback Check
        if pos.peak_pnl > 0.0:
            giveback = (pos.peak_pnl - pnl_usd) / pos.peak_pnl
            if giveback >= settings.PROFIT_PROTECT_GIVEBACK_PCT:
                reasons.append(
                    f"Gave back {giveback*100:.0f}% from peak profit (${pos.peak_pnl:+.2f} -> ${pnl_usd:+.2f})"
                )
                return "PROFIT PROTECT (giveback)", reasons

        # 2. Higher Timeframe Momentum Flip
        if ctx.momentum_1h and ctx.momentum_1h != pos.direction:
            rev_score += 1
            reasons.append(f"1h momentum flipped against {pos.direction} to {ctx.momentum_1h}")

        # 3. 5m RSI Swing / Rollover
        if ctx.rsi_5m is not None and pos.last_rsi5 is not None:
            if pos.direction == "LONG":
                if (pos.last_rsi5 - ctx.rsi_5m >= settings.PROFIT_PROTECT_RSI_SWING) and pos.last_rsi5 >= 60.0:
                    rev_score += 1
                    reasons.append(f"5m RSI rolling over: {pos.last_rsi5:.0f} -> {ctx.rsi_5m:.0f}")
            else:
                if (ctx.rsi_5m - pos.last_rsi5 >= settings.PROFIT_PROTECT_RSI_SWING) and pos.last_rsi5 <= 40.0:
                    rev_score += 1
                    reasons.append(f"5m RSI bouncing from floor: {pos.last_rsi5:.0f} -> {ctx.rsi_5m:.0f}")

        # 4. Order Book Depth Reversal
        if ctx.order_book_imbalance is not None:
            if pos.direction == "LONG" and ctx.order_book_imbalance < -0.15:
                rev_score += 1
                reasons.append(f"Order book turned ask-heavy ({ctx.order_book_imbalance:.2f})")
            elif pos.direction == "SHORT" and ctx.order_book_imbalance > 0.15:
                rev_score += 1
                reasons.append(f"Order book turned bid-heavy ({ctx.order_book_imbalance:+.2f})")

        if rev_score >= settings.PROFIT_PROTECT_REVERSAL_SCORE:
            reasons.insert(0, f"Microstructure reversal score: {rev_score}/4 while in profit (${pnl_usd:+.2f})")
            return "PROFIT PROTECT (reversal)", reasons

        return None, []
