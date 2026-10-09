import pytest
import time
from core.models import Signal
from core.queue import SignalQueue


def test_queue_add_and_flush():
    q = SignalQueue()
    sig1 = Signal(symbol="BTCUSDT", direction="LONG", source="test1", reason="Breakout", score=2)
    sig2 = Signal(symbol="BTCUSDT", direction="LONG", source="test2", reason="OFI positive", score=3)

    q.add(sig1)
    q.add(sig2)
    assert q.pending_count() == 2

    # Flush signals
    merged = q.flush_merged()
    assert len(merged) == 1
    item = merged[0]
    assert item["symbol"] == "BTCUSDT"
    assert item["direction"] == "LONG"
    assert item["score"] == 5
    assert set(item["sources"]) == {"test1", "test2"}

    # After flush, pending count must be 0 (no lingering duplicate signals)
    assert q.pending_count() == 0
    merged_again = q.flush_merged()
    assert len(merged_again) == 0


def test_queue_multi_direction_no_leak():
    q = SignalQueue()
    sig_long = Signal(symbol="ETHUSDT", direction="LONG", source="s1", reason="RSI dip", score=2)
    sig_short = Signal(symbol="ETHUSDT", direction="SHORT", source="s2", reason="Funding high", score=2)

    q.add(sig_long)
    q.add(sig_short)
    assert q.pending_count() == 2

    merged = q.flush_merged()
    # Both directions should be processed
    assert len(merged) == 2
    directions = {m["direction"] for m in merged}
    assert directions == {"LONG", "SHORT"}

    # CRITICAL: Neither signal should leak back into pending!
    assert q.pending_count() == 0
    assert len(q.flush_merged()) == 0


def test_manual_signal_priority():
    q = SignalQueue()
    manual = Signal(symbol="SOLUSDT", direction="LONG", source="manual", reason="Override", score=10, manual=True)
    q.add(manual)

    popped = q.pop_manual()
    assert len(popped) == 1
    assert popped[0].symbol == "SOLUSDT"
    assert popped[0].manual is True

    # After popping manual, queue must be empty
    assert len(q.pop_manual()) == 0
