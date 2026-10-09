import pytest
from config.settings import settings
from execution.risk_manager import risk_manager
from core.models import Position


def test_guardrails_pass():
    can_trade, reason = risk_manager.check_guardrails(
        daily_pnl=10.0,
        consecutive_losses=0,
        current_balance=1000.0
    )
    assert can_trade is True
    assert reason == ""


def test_guardrails_daily_loss_limit():
    can_trade, reason = risk_manager.check_guardrails(
        daily_pnl=-settings.DAILY_LOSS_LIMIT - 1.0,
        consecutive_losses=2,
        current_balance=800.0
    )
    assert can_trade is False
    assert "Daily Loss Limit hit" in reason


def test_guardrails_consecutive_losses():
    can_trade, reason = risk_manager.check_guardrails(
        daily_pnl=-20.0,
        consecutive_losses=settings.MAX_CONSECUTIVE_LOSSES,
        current_balance=900.0
    )
    assert can_trade is False
    assert "consecutive losses trigger cooldown" in reason


def test_portfolio_heat():
    open_positions = {
        "p1": Position(symbol="BTCUSDT", direction="LONG", entry=60000, tp=61000, tp2=62000, sl=59000, qty=0.1, usdt_size=400.0, reason="test"),
        "p2": Position(symbol="ETHUSDT", direction="LONG", entry=3000, tp=3100, tp2=3200, sl=2900, qty=1.0, usdt_size=400.0, reason="test"),
    }
    # Total current heat = 800 on 1000 equity (80% heat)
    # MAX_PORTFOLIO_HEAT is 0.95 (950)
    # Adding 200 should exceed 950 limit
    heat_ok, reason = risk_manager.check_portfolio_heat(open_positions, new_usdt_size=200.0, equity=1000.0)
    assert heat_ok is False
    assert "Portfolio heat cap" in reason

    # Adding 50 should pass (850 < 950)
    heat_ok2, _ = risk_manager.check_portfolio_heat(open_positions, new_usdt_size=50.0, equity=1000.0)
    assert heat_ok2 is True


def test_kelly_position_size():
    size = risk_manager.calculate_kelly_position_size(
        equity=1000.0,
        confluence_score=6,
        regime_str="TRENDING_BULL"
    )
    assert size >= settings.MIN_TRADE_USDT
    assert size <= settings.MAX_TRADE_USDT
