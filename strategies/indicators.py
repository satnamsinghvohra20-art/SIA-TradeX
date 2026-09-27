"""
SIA-TradeX: Quantitative Technical Indicators
Mathematically accurate calculations with sufficient historical warm-up.
"""

from typing import List, Dict, Optional, Tuple


class Indicators:
    @staticmethod
    def ema(closes: List[float], period: int = 20) -> float:
        """Calculates Exponential Moving Average with full sequence smoothing."""
        if not closes or len(closes) < period:
            return closes[-1] if closes else 0.0
        k = 2.0 / (period + 1.0)
        # Seed with SMA of first period
        val = sum(closes[:period]) / period
        for c in closes[period:]:
            val = (c * k) + (val * (1.0 - k))
        return val

    @staticmethod
    def rsi(closes: List[float], period: int = 14) -> Optional[float]:
        """
        Calculates Wilder's Smoothed Relative Strength Index.
        Requires at least period + 1 points (ideally 100+ for exact convergence).
        """
        if not closes or len(closes) < period + 1:
            return None

        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(0.0, diff))
            losses.append(max(0.0, -diff))

        # Initial average
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        # Wilder's Smoothing
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def atr(candles: List[Dict[str, float]], period: int = 14) -> Optional[float]:
        """Calculates Average True Range."""
        if not candles or len(candles) < period + 1:
            return None

        trs = []
        for i in range(1, len(candles)):
            hi = candles[i]["high"]
            lo = candles[i]["low"]
            pc = candles[i - 1]["close"]
            tr = max(hi - lo, abs(hi - pc), abs(lo - pc))
            trs.append(tr)

        if len(trs) < period:
            return None

        # Wilder's smoothed ATR
        val = sum(trs[:period]) / period
        for tr in trs[period:]:
            val = (val * (period - 1) + tr) / period
        return val

    @staticmethod
    def vwap(candles: List[Dict[str, float]]) -> Optional[float]:
        """
        Volume-Weighted Average Price across provided candles.
        Typically fed candles from 00:00 UTC session open.
        """
        if not candles:
            return None
        cum_pv = 0.0
        cum_vol = 0.0
        for c in candles:
            typical_price = (c["high"] + c["low"] + c["close"]) / 3.0
            vol = c["volume"]
            cum_pv += typical_price * vol
            cum_vol += vol
        return (cum_pv / cum_vol) if cum_vol > 0 else None

    @staticmethod
    def adx(candles: List[Dict[str, float]], period: int = 14) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Calculates Average Directional Index (ADX) along with +DI and -DI.
        Returns: (adx, plus_di, minus_di)
        """
        if not candles or len(candles) < period * 2:
            return None, None, None

        trs, plus_dms, minus_dms = [], [], []
        for i in range(1, len(candles)):
            curr = candles[i]
            prev = candles[i - 1]
            tr = max(curr["high"] - curr["low"],
                     abs(curr["high"] - prev["close"]),
                     abs(curr["low"] - prev["close"]))
            up_move = curr["high"] - prev["high"]
            down_move = prev["low"] - curr["low"]

            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

            trs.append(tr)
            plus_dms.append(plus_dm)
            minus_dms.append(minus_dm)

        if len(trs) < period:
            return None, None, None

        tr_smooth = sum(trs[:period])
        plus_smooth = sum(plus_dms[:period])
        minus_smooth = sum(minus_dms[:period])

        dx_list = []
        for i in range(period, len(trs)):
            tr_smooth = tr_smooth - (tr_smooth / period) + trs[i]
            plus_smooth = plus_smooth - (plus_smooth / period) + plus_dms[i]
            minus_smooth = minus_smooth - (minus_smooth / period) + minus_dms[i]

            plus_di = 100.0 * (plus_smooth / tr_smooth) if tr_smooth > 0 else 0.0
            minus_di = 100.0 * (minus_smooth / tr_smooth) if tr_smooth > 0 else 0.0
            di_sum = plus_di + minus_di
            dx = (100.0 * abs(plus_di - minus_di) / di_sum) if di_sum > 0 else 0.0
            dx_list.append((dx, plus_di, minus_di))

        if len(dx_list) < period:
            return None, None, None

        adx_val = sum(x[0] for x in dx_list[:period]) / period
        for item in dx_list[period:]:
            adx_val = (adx_val * (period - 1) + item[0]) / period

        last_plus = dx_list[-1][1]
        last_minus = dx_list[-1][2]
        return adx_val, last_plus, last_minus

    @staticmethod
    def breakout(candles: List[Dict[str, float]], period: int = 15) -> Optional[str]:
        """Detects Donchian channel breakout beyond historical highs/lows."""
        if not candles or len(candles) < period + 1:
            return None
        window = candles[-(period + 1):-1]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        current_close = candles[-1]["close"]

        if current_close > max(highs):
            return "LONG"
        if current_close < min(lows):
            return "SHORT"
        return None
