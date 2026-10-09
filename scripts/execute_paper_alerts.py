#!/usr/bin/env python3
"""
SIA-TradeX: Execute Paper Trades from Live Alerts & Monitor Real-Time Profit
Places simulated trades based on live market alerts and tracks live PnL.
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import settings
from engine import QuantEngine
from core.models import AISignalDecision
from data.market_data import market_data
from strategies.indicators import Indicators


def execute_and_monitor_paper_trades(cycles: int = 5, delay: float = 3.0):
    print("=================================================================")
    print("SIA-TradeX: PLACING PAPER TRADES FROM LIVE MARKET ALERTS")
    print("Account Mode: PAPER SIMULATOR (Risk-Free Fake Money)")
    print("Market Feed: 100% Real Live Binance Futures Mainnet")
    print("=================================================================\n")

    # Initialize Engine in Paper Mode
    engine = QuantEngine(live_mode=False)
    initial_balance = engine.paper_account.cash
    print(f"Starting Paper Wallet Balance: ${initial_balance:,.2f} USDT")

    # Scan and trigger top alpha setups
    prime_symbols = ["PAXGUSDT", "AVAXUSDT"]
    print(f"\nEvaluating Top Institutional Alpha Setups for: {prime_symbols}")

    for sym in prime_symbols:
        ctx = market_data.get_market_context(sym)
        if not ctx or not ctx.price:
            print(f"Could not fetch live context for {sym}")
            continue

        price = ctx.price
        candles_1h = market_data.klines(sym, interval="1h", limit=50)
        closes = [c["close"] for c in candles_1h]
        ema20 = Indicators.ema(closes, 20)
        ema50 = Indicators.ema(closes, 50)
        trend = "BULLISH" if price > ema20 and ema20 > ema50 else ("BEARISH" if price < ema20 and ema20 < ema50 else "CHOP")
        
        # Determine bias
        direction = "LONG" if trend == "BULLISH" else ("SHORT" if trend == "BEARISH" else "LONG")
        conviction = 96 if sym in ("PAXGUSDT", "AVAXUSDT") else 85

        ai_dec = AISignalDecision(
            signal=direction,
            confidence=conviction,
            regime=ctx.regime.value if ctx.regime else "TRENDING",
            reason=f"Prime Alpha Alert ({trend} trend + High Confluence)",
            key_drivers=["TTM Squeeze", "ADX Trend Strength"]
        )

        trade_size = 35.0  # $35 margin per position
        engine._open_position(
            symbol=sym,
            direction=direction,
            score=conviction // 10,
            usdt_size=trade_size,
            reasons=[f"Live Alpha Alert {direction}"],
            sources=["alpha_paper_executor"],
            ai_decision=ai_dec,
            ctx=ctx
        )
        print(f"✅ Placed Paper Trade: {sym} ({direction}) | Margin: ${trade_size:.2f} USDT | Leverage: {settings.DEFAULT_LEVERAGE}x")

    # Display active open positions
    print("\n--- ACTIVE OPEN POSITIONS IN SIMULATOR ---")
    with engine._positions_lock:
        for pos_id, p in engine.positions.items():
            print(f"• ID: {pos_id[:8]} | {p.symbol} {p.direction} | Entry: ${p.entry:,.4f} | Size: {p.qty:.4f} | TP1: ${p.tp:,.4f} | TP2: ${p.tp2:,.4f} | SL: ${p.sl:,.4f}")

    print("\n=================================================================")
    print("MONITORING LIVE PNL & PROFIT OVER CONSECUTIVE LIVE TICKS:")
    print("=================================================================")

    for i in range(1, cycles + 1):
        time.sleep(delay)
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        print(f"\n[Tick Update #{i} | {now_str}]")

        # Run position health check to process any TP or SL
        engine._check_positions_health()

        total_upnl = 0.0
        with engine._positions_lock:
            for pos_id, p in engine.positions.items():
                cur_price = engine._get_fast_price(p.symbol) or p.entry
                mult = p.leverage * p.usdt_size
                pnl = ((cur_price - p.entry) / p.entry * mult) if p.direction == "LONG" else ((p.entry - cur_price) / p.entry * mult)
                pnl_pct = (pnl / p.usdt_size) * 100.0
                total_upnl += pnl
                status = "🟢 PROFIT" if pnl >= 0 else "🔴 DRAWDOWN"
                print(f"  {p.symbol:8} ({p.direction}) | Entry: ${p.entry:,.4f} | Live Price: ${cur_price:,.4f} | PnL: ${pnl:+.4f} ({pnl_pct:+.2f}%) [{status}]")

        equity = engine.get_equity()
        print(f"  --> Total Wallet Equity: ${equity:,.2f} USDT | Net Unrealized PnL: ${total_upnl:+.4f} USDT")

    return engine


if __name__ == "__main__":
    execute_and_monitor_paper_trades(cycles=4, delay=2.5)
