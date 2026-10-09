"""
SIA-TradeX: Vectorized Technical Indicators Engine
Accelerated with C-level NumPy vectorization for microsecond execution.
"""

from typing import List, Dict, Optional, Tuple, Any
import numpy as np


class Indicators:
    @staticmethod
    def ema(closes: List[float], period: int = 20) -> float:
        """Vectorized Exponential Moving Average."""
        if not closes or len(closes) < period:
            return closes[-1] if closes else 0.0

        arr = np.asarray(closes, dtype=np.float64)
        k = 2.0 / (period + 1.0)
        # Vectorized weights
        alpha = k
        weights = (1 - alpha) ** np.arange(len(arr) - 1, -1, -1)
        weights /= weights.sum()
        return float(np.dot(arr, weights))

    @staticmethod
    def rsi(closes: List[float], period: int = 14) -> Optional[float]:
        """
        Wilder's Smoothed RSI accelerated via vectorized NumPy differences.
        """
        if not closes or len(closes) < period + 1:
            return None

        arr = np.asarray(closes, dtype=np.float64)
        diff = np.diff(arr)
        gains = np.where(diff > 0, diff, 0.0)
        losses = np.where(diff < 0, -diff, 0.0)

        # Seed with initial SMA
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        # Wilder's exponential smoothing
        for i in range(period, len(diff)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    @staticmethod
    def atr(candles: List[Dict[str, float]], period: int = 14) -> Optional[float]:
        """Vectorized Average True Range."""
        if not candles or len(candles) < period + 1:
            return None

        highs = np.array([c["high"] for c in candles], dtype=np.float64)
        lows = np.array([c["low"] for c in candles], dtype=np.float64)
        closes = np.array([c["close"] for c in candles], dtype=np.float64)

        prev_closes = closes[:-1]
        h_l = highs[1:] - lows[1:]
        h_pc = np.abs(highs[1:] - prev_closes)
        l_pc = np.abs(lows[1:] - prev_closes)

        # True Range: max across the 3 vectors
        tr = np.maximum(h_l, np.maximum(h_pc, l_pc))

        if len(tr) < period:
            return None

        val = np.mean(tr[:period])
        for t in tr[period:]:
            val = (val * (period - 1) + t) / period

        return float(val)

    @staticmethod
    def vwap(candles: List[Dict[str, float]]) -> Optional[float]:
        """Vectorized Volume-Weighted Average Price."""
        if not candles:
            return None

        highs = np.array([c["high"] for c in candles], dtype=np.float64)
        lows = np.array([c["low"] for c in candles], dtype=np.float64)
        closes = np.array([c["close"] for c in candles], dtype=np.float64)
        vols = np.array([c["volume"] for c in candles], dtype=np.float64)

        typical = (highs + lows + closes) / 3.0
        cum_vol = np.sum(vols)
        if cum_vol == 0:
            return None

        return float(np.sum(typical * vols) / cum_vol)

    @staticmethod
    def adx(candles: List[Dict[str, float]], period: int = 14) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Vectorized Average Directional Index (ADX)."""
        if not candles or len(candles) < period * 2:
            return None, None, None

        highs = np.array([c["high"] for c in candles], dtype=np.float64)
        lows = np.array([c["low"] for c in candles], dtype=np.float64)
        closes = np.array([c["close"] for c in candles], dtype=np.float64)

        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        prev_closes = closes[:-1]

        h_l = highs[1:] - lows[1:]
        h_pc = np.abs(highs[1:] - prev_closes)
        l_pc = np.abs(lows[1:] - prev_closes)
        tr = np.maximum(h_l, np.maximum(h_pc, l_pc))

        up_move = highs[1:] - prev_highs
        down_move = prev_lows - lows[1:]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr_smooth = np.sum(tr[:period])
        plus_smooth = np.sum(plus_dm[:period])
        minus_smooth = np.sum(minus_dm[:period])

        dx_list = []
        for i in range(period, len(tr)):
            tr_smooth = tr_smooth - (tr_smooth / period) + tr[i]
            plus_smooth = plus_smooth - (plus_smooth / period) + plus_dm[i]
            minus_smooth = minus_smooth - (minus_smooth / period) + minus_dm[i]

            plus_di = 100.0 * (plus_smooth / tr_smooth) if tr_smooth > 0 else 0.0
            minus_di = 100.0 * (minus_smooth / tr_smooth) if tr_smooth > 0 else 0.0
            di_sum = plus_di + minus_di
            dx = (100.0 * abs(plus_di - minus_di) / di_sum) if di_sum > 0 else 0.0
            dx_list.append((dx, plus_di, minus_di))

        if len(dx_list) < period:
            return None, None, None

        adx_val = np.mean([x[0] for x in dx_list[:period]])
        for item in dx_list[period:]:
            adx_val = (adx_val * (period - 1) + item[0]) / period

        return float(adx_val), float(dx_list[-1][1]), float(dx_list[-1][2])

    @staticmethod
    def breakout(candles: List[Dict[str, float]], period: int = 15) -> Optional[str]:
        """Donchian channel breakout beyond historical highs/lows."""
        if not candles or len(candles) < period + 1:
            return None

        highs = [c["high"] for c in candles[-(period + 1):-1]]
        lows = [c["low"] for c in candles[-(period + 1):-1]]
        current_close = candles[-1]["close"]

        if current_close > max(highs):
            return "LONG"
        if current_close < min(lows):
            return "SHORT"
        return None

    @staticmethod
    def bollinger_bands(closes: List[float], period: int = 20, num_std: float = 2.0) -> Tuple[float, float, float]:
        """Calculates Bollinger Bands: (upper, mid, lower)."""
        if not closes or len(closes) < period:
            c = closes[-1] if closes else 0.0
            return c, c, c
        arr = np.asarray(closes[-period:], dtype=np.float64)
        mid = float(np.mean(arr))
        std = float(np.std(arr))
        return mid + (num_std * std), mid, mid - (num_std * std)

    @staticmethod
    def keltner_channels(candles: List[Dict[str, float]], period: int = 20, mult: float = 1.5) -> Tuple[float, float, float]:
        """Calculates Keltner Channels: (upper, mid, lower)."""
        if not candles or len(candles) < period:
            c = candles[-1]["close"] if candles else 0.0
            return c, c, c
        closes = [c["close"] for c in candles]
        mid = Indicators.ema(closes[-period:], period=period)
        atr_val = Indicators.atr(candles, period=10) or (mid * 0.01)
        return mid + (mult * atr_val), mid, mid - (mult * atr_val)

    @staticmethod
    def ttm_squeeze(candles: List[Dict[str, float]], period: int = 20) -> Dict[str, Any]:
        """
        Institutional TTM Squeeze Detector:
        Detects volatility compression when Bollinger Bands fit inside Keltner Channels.
        When squeeze releases, strong explosive directional impulse follows.
        """
        if not candles or len(candles) < period:
            return {"squeeze_on": False, "momentum": 0.0, "signal": None}

        closes = [c["close"] for c in candles]
        bb_upper, bb_mid, bb_lower = Indicators.bollinger_bands(closes, period=period, num_std=2.0)
        kc_upper, kc_mid, kc_lower = Indicators.keltner_channels(candles, period=period, mult=1.5)

        # Squeeze is ON when Bollinger Bands are completely inside Keltner Channels
        squeeze_on = (bb_lower > kc_lower) and (bb_upper < kc_upper)

        # Linear regression momentum oscillator
        arr = np.asarray(closes[-period:], dtype=np.float64)
        x = np.arange(len(arr))
        slope, intercept = np.polyfit(x, arr, 1)
        momentum = float(slope)

        signal = None
        if not squeeze_on:  # Squeeze released / active momentum expansion
            if momentum > 0:
                signal = "LONG"
            elif momentum < 0:
                signal = "SHORT"

        return {
            "squeeze_on": squeeze_on,
            "momentum": momentum,
            "signal": signal,
            "bb_bandwidth": (bb_upper - bb_lower) / max(0.001, bb_mid)
        }

    @staticmethod
    def liquidity_sweep(candles: List[Dict[str, float]], lookback: int = 20) -> Optional[Dict[str, Any]]:
        """
        Smart Money Concept: Liquidity Sweep & Stop Hunt Detector.
        Identifies wick sweeps beyond previous swing high/low that immediately close back inside.
        """
        if not candles or len(candles) < lookback + 2:
            return None

        historical = candles[-(lookback + 2):-1]
        cur = candles[-1]

        swing_high = max(c["high"] for c in historical)
        swing_low = min(c["low"] for c in historical)

        # Bullish Liquidity Sweep (Swept low for retail stop orders, but closed strong above swing low)
        if cur["low"] < swing_low and cur["close"] > swing_low:
            body = abs(cur["close"] - cur["open"])
            lower_wick = min(cur["open"], cur["close"]) - cur["low"]
            if lower_wick > body * 1.5:  # Strong rejection hammer wick
                return {
                    "type": "BULLISH_SWEEP",
                    "direction": "LONG",
                    "sweep_level": swing_low,
                    "conviction": 90
                }

        # Bearish Liquidity Sweep (Swept high, closed below swing high with long upper wick)
        if cur["high"] > swing_high and cur["close"] < swing_high:
            body = abs(cur["close"] - cur["open"])
            upper_wick = cur["high"] - max(cur["open"], cur["close"])
            if upper_wick > body * 1.5:  # Shooting star rejection wick
                return {
                    "type": "BEARISH_SWEEP",
                    "direction": "SHORT",
                    "sweep_level": swing_high,
                    "conviction": 90
                }

        return None
