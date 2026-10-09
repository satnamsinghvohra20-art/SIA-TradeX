import pytest
from execution.profit_protector import ProfitProtector
from core.models import Position, MarketContext, MarketRegime


def test_profit_protector_floor():
    pos = Position(
        symbol="BTCUSDT", direction="LONG", entry=60000.0,
        tp=62000.0, tp2=64000.0, sl=58000.0, qty=0.001, usdt_size=20.0, reason="test"
    )
    ctx = MarketContext(symbol="BTCUSDT", price=60005.0)
    # PnL below floor ($0.15) should not trigger
    exit_title, reasons = ProfitProtector.evaluate(pos, price=60005.0, pnl_usd=0.05, ctx=ctx)
    assert exit_title is None
    assert reasons == []


def test_profit_protector_peak_giveback():
    pos = Position(
        symbol="BTCUSDT", direction="LONG", entry=60000.0,
        tp=62000.0, tp2=64000.0, sl=58000.0, qty=0.001, usdt_size=20.0, reason="test"
    )
    pos.peak_pnl = 5.0  # Peak was +$5.00
    ctx = MarketContext(symbol="BTCUSDT", price=63000.0)

    # Current PnL dropped to $3.50 (giveback of 30% >= 25% threshold)
    exit_title, reasons = ProfitProtector.evaluate(pos, price=63000.0, pnl_usd=3.50, ctx=ctx)
    assert exit_title == "PROFIT PROTECT (giveback)"
    assert len(reasons) > 0


def test_profit_protector_rsi_rollover():
    pos = Position(
        symbol="ETHUSDT", direction="LONG", entry=3000.0,
        tp=3100.0, tp2=3200.0, sl=2900.0, qty=0.05, usdt_size=50.0, reason="test"
    )
    pos.last_rsi5 = 72.0  # Previous RSI was high
    # Context has flipped 1h momentum to SHORT, and 5m RSI rolled over to 64 (drop of 8 >= 4)
    ctx = MarketContext(
        symbol="ETHUSDT",
        price=3020.0,
        momentum_1h="SHORT",
        rsi_5m=64.0,
        order_book_imbalance=-0.20
    )
    exit_title, reasons = ProfitProtector.evaluate(pos, price=3020.0, pnl_usd=1.0, ctx=ctx)
    assert exit_title == "PROFIT PROTECT (reversal)"
    assert any("5m RSI rolling over" in r for r in reasons)
