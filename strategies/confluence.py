"""
SIA-TradeX: Multi-Factor Confluence Strategy Engine
Combines technical filters, market microstructure, regime alignment, and AI analysis.
"""

from typing import Dict, Any, Tuple
from config.settings import settings
from core.models import MarketContext, MarketRegime
from strategies.regime import MarketRegimeDetector


class ConfluenceStrategy:
    def __init__(self):
        pass

    def evaluate(
        self,
        symbol: str,
        direction: str,
        ctx: MarketContext,
        equity: float
    ) -> Dict[str, Any]:
        """
        Evaluates a candidate setup against systematic quantitative gates.
        Returns:
            {
                "score_bonus": int,
                "blocked": bool,
                "block_reason": str,
                "filters": dict,
                "position_size": float
            }
        """
        score_bonus = 0
        blocked = False
        block_reason = ""
        filters: Dict[str, Any] = {}

        # 1. RSI Filter
        if ctx.rsi_1h is not None:
            filters["rsi_1h"] = ctx.rsi_1h
            if direction == "LONG" and ctx.rsi_1h > settings.RSI_OVERBOUGHT:
                return self._block(f"RSI {ctx.rsi_1h:.0f} overbought (>{settings.RSI_OVERBOUGHT})", filters)
            elif direction == "SHORT" and ctx.rsi_1h < settings.RSI_OVERSOLD:
                return self._block(f"RSI {ctx.rsi_1h:.0f} oversold (<{settings.RSI_OVERSOLD})", filters)
            elif direction == "LONG" and ctx.rsi_1h < 55.0:
                score_bonus += 1
            elif direction == "SHORT" and ctx.rsi_1h > 45.0:
                score_bonus += 1

        # 2. VWAP Filter
        if ctx.vwap and ctx.price > 0:
            filters["vwap"] = ctx.vwap
            if direction == "LONG":
                if ctx.price > ctx.vwap:
                    score_bonus += 1
                elif ctx.price < ctx.vwap * 0.98:
                    score_bonus -= 1
            else:
                if ctx.price < ctx.vwap:
                    score_bonus += 1
                elif ctx.price > ctx.vwap * 1.02:
                    score_bonus -= 1

        # 3. Higher Timeframe (4h) Momentum
        if ctx.momentum_4h:
            filters["mtf_4h"] = ctx.momentum_4h
            if ctx.momentum_4h == direction:
                score_bonus += 2
            else:
                score_bonus -= 1

        # 4. Dynamic Market Regime Alignment
        regime_bonus, regime_reason = MarketRegimeDetector.evaluate_direction_alignment(direction, ctx.regime)
        score_bonus += regime_bonus
        filters["regime"] = ctx.regime.value
        filters["regime_reason"] = regime_reason

        # 5. Breakout Filter
        if ctx.breakout:
            filters["breakout"] = ctx.breakout
            if ctx.breakout == direction:
                score_bonus += 2
            else:
                score_bonus -= 1

        # 6. Volume Confirmation
        filters["volume_confirmed"] = ctx.volume_confirmed
        if ctx.volume_confirmed:
            score_bonus += 1

        # 7. Microstructure: Funding Rate & Order Book Imbalance
        if ctx.funding_rate is not None:
            if direction == "LONG" and ctx.funding_rate < -0.0006:
                score_bonus += 1  # Short squeeze potential
            elif direction == "SHORT" and ctx.funding_rate > 0.0006:
                score_bonus += 1  # Long liquidation overhang

        if ctx.order_book_imbalance is not None:
            if direction == "LONG" and ctx.order_book_imbalance > 0.12:
                score_bonus += 1
            elif direction == "SHORT" and ctx.order_book_imbalance < -0.12:
                score_bonus += 1

        # 8. Dynamic Sizing (Risk 1.5% of Equity / SL distance)
        sl_pct = (settings.FIXED_SL_PCT / 100.0)
        risk_usdt = equity * (settings.RISK_PER_TRADE_PCT / 100.0)
        calculated_size = risk_usdt / (settings.DEFAULT_LEVERAGE * sl_pct)
        position_size = round(max(settings.MIN_TRADE_USDT, min(settings.MAX_TRADE_USDT, calculated_size)), 2)

        return {
            "score_bonus": max(0, score_bonus),
            "blocked": False,
            "block_reason": "",
            "filters": filters,
            "position_size": position_size
        }

    def _block(self, reason: str, filters: dict) -> Dict[str, Any]:
        return {
            "score_bonus": 0,
            "blocked": True,
            "block_reason": reason,
            "filters": filters,
            "position_size": settings.MIN_TRADE_USDT
        }


confluence_strategy = ConfluenceStrategy()
