import pytest
import os
import tempfile
import time
from datetime import datetime
from storage.database import Database
from core.models import TradeRecord


@pytest.fixture
def temp_db():
    temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_fd)
    db = Database(db_path=temp_path)
    yield db
    # Cleanup immediately
    try:
        os.remove(temp_path)
        for ext in ["-wal", "-shm"]:
            if os.path.exists(temp_path + ext):
                os.remove(temp_path + ext)
    except Exception:
        pass


def test_db_record_and_get_trades(temp_db):
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    record = TradeRecord(
        timestamp=now_utc,
        symbol="BTCUSDT",
        direction="LONG",
        entry=65000.0,
        exit=66000.0,
        pnl=4.50,
        reason="TP Target hit",
        sources=["test_strat"],
        score=5,
        ai_reason="Bullish test",
        equity=1004.50,
        profit_protected=False,
        live=False,
        leverage=3
    )
    tid = temp_db.record_trade(record)
    assert tid is not None

    recent = temp_db.get_recent_trades(limit=10)
    assert len(recent) == 1
    assert recent[0]["symbol"] == "BTCUSDT"
    assert recent[0]["pnl"] == 4.50
    assert recent[0]["direction"] == "LONG"


def test_db_daily_metrics(temp_db):
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    temp_db.record_trade(TradeRecord(
        timestamp=now_utc, symbol="SOLUSDT", direction="LONG",
        entry=140.0, exit=145.0, pnl=2.50, reason="TP1",
        sources=["s1"], score=4, equity=1002.50
    ))
    temp_db.record_trade(TradeRecord(
        timestamp=now_utc, symbol="ETHUSDT", direction="SHORT",
        entry=3500.0, exit=3520.0, pnl=-1.20, reason="SL",
        sources=["s2"], score=4, equity=1001.30
    ))

    metrics = temp_db.get_daily_metrics()
    assert metrics["trades_count"] == 2
    assert metrics["wins"] == 1
    assert metrics["losses"] == 1
    assert metrics["pnl"] == pytest.approx(1.30, abs=0.01)
    assert metrics["win_rate"] == 50.0


def test_db_equity_snapshots(temp_db):
    temp_db.record_equity_snapshot(balance=1000.0, equity=1015.0, unrealized_pnl=15.0, open_positions=1)
    history = temp_db.get_equity_history(limit=10)
    assert len(history) == 1
    assert history[0]["equity"] == 1015.0
    assert history[0]["open_positions"] == 1


def test_db_state_persistence(temp_db):
    temp_db.set_state("ai_mode", {"status": "active", "rpm": 14})
    val = temp_db.get_state("ai_mode")
    assert val == {"status": "active", "rpm": 14}
    assert temp_db.get_state("non_existent", default="def") == "def"


def test_db_daily_income_and_all_trades(temp_db):
    now_utc = "2026-10-10 12:00:00 UTC"
    temp_db.record_trade(TradeRecord(
        timestamp=now_utc, symbol="AVAXUSDT", direction="SHORT",
        entry=10.20, exit=10.05, pnl=1.50, reason="TP1",
        sources=["alpha"], score=9, equity=1001.50
    ))
    all_trades = temp_db.get_all_trades()
    assert len(all_trades) >= 1

    daily = temp_db.get_all_daily_income()
    assert len(daily) >= 1
    assert daily[0]["date"] == "2026-10-10"
    assert daily[0]["realized_income"] >= 1.50
