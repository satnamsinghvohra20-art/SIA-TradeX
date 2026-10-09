import pytest
from execution.paper_account import PaperAccount
from core.models import Position


def test_paper_account_init():
    acc = PaperAccount(starting_balance=1000.0)
    assert acc.cash == 1000.0
    assert acc.realized_pnl == 0.0


def test_paper_account_reserve_and_release_profit():
    acc = PaperAccount(starting_balance=1000.0)
    # Reserve margin for $50 trade
    ok = acc.reserve_margin(50.0)
    assert ok is True
    # Cash should be reduced by 50 + fee (0.0005 * 50 * 3 = 0.075)
    assert acc.cash < 950.0

    # Release margin with $5 profit
    acc.release_margin(50.0, pnl=5.0)
    # Cash should be back to starting balance + net profit
    assert acc.cash > 1004.5
    assert acc.realized_pnl > 4.5


def test_paper_account_insufficient_margin():
    acc = PaperAccount(starting_balance=20.0)
    # Trying to reserve $50 should fail
    ok = acc.reserve_margin(50.0)
    assert ok is False
    assert acc.cash == 20.0


def test_paper_account_total_equity():
    acc = PaperAccount(starting_balance=950.0)
    positions = {
        "p1": Position(
            symbol="BTCUSDT",
            direction="LONG",
            entry=50000.0,
            tp=52000.0,
            tp2=54000.0,
            sl=48000.0,
            qty=0.003,
            usdt_size=50.0,
            leverage=3,
            reason="test"
        )
    }
    # If price rises to 55000, 10% gain * 3x leverage = +30% on $50 = +$15 uPnL
    price_fn = lambda sym: 55000.0
    eq = acc.total_equity(positions, price_fn)
    assert eq == pytest.approx(950.0 + 50.0 + 15.0, abs=0.1)


def test_paper_account_reset():
    acc = PaperAccount(starting_balance=1000.0)
    acc.reserve_margin(100.0)
    acc.release_margin(100.0, pnl=-25.0)
    assert acc.cash < 1000.0

    acc.reset(starting_balance=1000.0)
    assert acc.cash == 1000.0
    assert acc.realized_pnl == 0.0
