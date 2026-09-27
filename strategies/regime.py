"""
SIA-TradeX: Dynamic Market Regime Detector
Replaces static directional bias with real-time multi-timeframe quantitative regime analysis.
"""

from typing import Dict, Any, Tuple
from core.models import MarketRegime
from strategies.indicators import Indicators


class MarketRegimeDetector:
    @staticmethod
    def classify(candles_1h: list, candles_4h: list) -> Tuple[MarketRegime, Dict[str, Any]]:
        """
        Classifies current regime based on ADX (trend strength) and EMA 200 (macro bias).
        """
        if not candles_1h or len(candles_1h) < 30:
            return MarketRegime.UNKNOWN, {}

        closes_1h = [c["close"] for c in candles_1h]
        price = closes_1h[-1]

        # 4h Trend & Bias (if available)
        ema_200_4h = None
        if candles_4h and len(candles_4h) >= 50:
            closes_4h = [c["close"] for c in candles_4h]
            ema_200_4h = Indicators.ema(closes_4h, min(len(closes_4h), 100))

        # ADX & Directional Movement on 1h
        adx, plus_di, minus_di = Indicators.adx(candles_1h, 14)
        vol_ratio = 1.0

        # Calculate Volatility Ratio (recent ATR vs 20-period baseline)
        atr_now = Indicators.atr(candles_1h, 14)
        if atr_now and len(candles_1h) >= 40:
            hist_atrs = []
            for i in range(15, 35):
                sub = candles_1h[-(i + 14):-i]
                sub_atr = Indicators.atr(sub, 14)
                if sub_atr:
                    hist_atrs.append(sub_atr)
            if hist_atrs:
                baseline_atr = sum(hist_atrs) / len(hist_atrs)
                vol_ratio = (atr_now / baseline_atr) if baseline_atr > 0 else 1.0

        metrics = {
            "adx": round(adx, 1) if adx is not None else 0.0,
            "plus_di": round(plus_di, 1) if plus_di is not None else 0.0,
            "minus_di": round(minus_di, 1) if minus_di is not None else 0.0,
            "vol_ratio": round(vol_ratio, 2),
            "macro_ema_4h": round(ema_200_4h, 4) if ema_200_4h else None,
        }

        # High Volatility Regime
        if vol_ratio > 1.85:
            return MarketRegime.HIGH_VOLATILITY, metrics

        # Trending vs Ranging
        if adx is not None and adx >= 23.0:
            # Strong trend in place
            if plus_di and minus_di and plus_di > minus_di:
                return MarketRegime.TRENDING_BULL, metrics
            elif plus_di and minus_di and minus_di > plus_di:
                return MarketRegime.TRENDING_BEAR, metrics
            elif ema_200_4h:
                return (MarketRegime.TRENDING_BULL if price > ema_200_4h
                        else MarketRegime.TRENDING_BEAR), metrics

        # Low ADX indicates choppy / ranging regime
        return MarketRegime.RANGING, metrics

    @staticmethod
    def evaluate_direction_alignment(direction: str, regime: MarketRegime) -> Tuple[int, str]:
        """
        Calculates score modifier based on whether trade direction matches the market regime.
        """
        if regime == MarketRegime.TRENDING_BULL:
            if direction == "LONG":
                return 2, "Regime alignment: Bull trend (+2)"
            elif direction == "SHORT":
                return -2, "Counter-trend trade against Bull trend (-2)"

        elif regime == MarketRegime.TRENDING_BEAR:
            if direction == "SHORT":
                return 2, "Regime alignment: Bear trend (+2)"
            elif direction == "LONG":
                return -2, "Counter-trend trade against Bear trend (-2)"

        elif regime == MarketRegime.RANGING:
            return 0, "Market ranging: Neutral regime"

        elif regime == MarketRegime.HIGH_VOLATILITY:
            return -1, "High volatility regime: Caution (-1)"

        return 0, "Regime unknown"
