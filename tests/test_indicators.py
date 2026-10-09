import pytest
import numpy as np
from strategies.indicators import Indicators


def test_ema_calculation():
    closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
    ema_val = Indicators.ema(closes, period=5)
    assert ema_val > 15.0
    assert ema_val <= 20.0


def test_rsi_calculation():
    # Uptrend prices should produce high RSI
    uptrend = [float(100 + i * 2) for i in range(30)]
    rsi_up = Indicators.rsi(uptrend, period=14)
    assert rsi_up is not None
    assert rsi_up > 70.0

    # Downtrend prices should produce low RSI
    downtrend = [float(200 - i * 2) for i in range(30)]
    rsi_down = Indicators.rsi(downtrend, period=14)
    assert rsi_down is not None
    assert rsi_down < 30.0

    # Short list returns None
    assert Indicators.rsi([100.0, 101.0], period=14) is None


def test_atr_calculation():
    candles = []
    for i in range(30):
        base = 100.0 + i
        candles.append({
            "high": base + 2.0,
            "low": base - 2.0,
            "close": base + 1.0,
            "volume": 1000.0
        })
    atr = Indicators.atr(candles, period=14)
    assert atr is not None
    assert atr > 0.0
    assert 3.5 <= atr <= 5.0


def test_vwap_calculation():
    candles = [
        {"high": 105.0, "low": 95.0, "close": 100.0, "volume": 100.0},
        {"high": 115.0, "low": 105.0, "close": 110.0, "volume": 200.0},
        {"high": 125.0, "low": 115.0, "close": 120.0, "volume": 300.0},
    ]
    vwap = Indicators.vwap(candles)
    assert vwap is not None
    # Higher volume at higher prices means vwap should be weighted towards 110-120
    assert 110.0 < vwap < 120.0


def test_breakout_donchian():
    candles = []
    for i in range(20):
        candles.append({
            "high": 100.0 + (i % 5),
            "low": 95.0,
            "close": 98.0
        })
    # Add breakout high
    candles.append({"high": 115.0, "low": 100.0, "close": 112.0})
    res_long = Indicators.breakout(candles, period=15)
    assert res_long == "LONG"

    # Add breakdown low
    candles[-1] = {"high": 96.0, "low": 85.0, "close": 88.0}
    res_short = Indicators.breakout(candles, period=15)
    assert res_short == "SHORT"
