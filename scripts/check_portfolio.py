#!/usr/bin/env python3
"""
SIA-TradeX: Live Portfolio & Financial Ledger Reporter
Inspects:
- Total Capital Invested
- Remaining Available Balance (Free Cash)
- Live Unrealized Floating PnL
- Today's Realized Cumulative Profit / Loss
- Win Rate & Trade Count
- Open & Recent Trades Breakdown
Usage:
    python scripts/check_portfolio.py [--whatsapp]
"""

import sys
import json
import urllib.request
import urllib.error
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
from storage.database import db
from ui.whatsapp_service import whatsapp_service


def fetch_live_engine_status():
    """Attempts to fetch real-time state from the running supervisor engine."""
    url = f"http://localhost:{settings.WEB_PORT}/api/status"
    req = urllib.request.Request(url, headers={"User-Agent": "SIA-TradeX-CLI"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def print_and_report_portfolio(send_whatsapp: bool = False):
    print("=================================================================")
    print("SIA-TradeX: REAL-TIME PORTFOLIO & FINANCIAL LEDGER")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("Account Mode: PAPER SIMULATOR (Risk-Free Fake Money)")
    print("Market Feed: 100% Real Live Binance Futures Mainnet")
    print("=================================================================\n")

    live_status = fetch_live_engine_status()
    daily_metrics = db.get_daily_metrics()
    recent_trades = db.get_recent_trades(limit=10)

    if live_status:
        equity = live_status.get("equity", 1000.0)
        cash = live_status.get("cash", 1000.0)
        invested = live_status.get("invested", 0.0)
        unrealized = live_status.get("unrealized_pnl", 0.0)
        open_pos = live_status.get("open_positions", [])
    else:
        # Fallback to DB snapshots
        snaps = db.get_equity_history(limit=1)
        if snaps:
            equity = snaps[-1]["equity"]
            cash = snaps[-1]["balance"]
            unrealized = snaps[-1]["unrealized_pnl"]
            invested = max(0.0, equity - cash)
        else:
            equity = settings.PAPER_STARTING_BALANCE
            cash = settings.PAPER_STARTING_BALANCE
            unrealized = 0.0
            invested = 0.0
        open_pos = []

    daily_pnl = daily_metrics.get("pnl", 0.0)
    wins = daily_metrics.get("wins", 0)
    losses = daily_metrics.get("losses", 0)
    win_rate = daily_metrics.get("win_rate", 0.0)
    trades_count = daily_metrics.get("trades_count", 0)

    pnl_sign = "+" if daily_pnl >= 0 else ""
    upnl_sign = "+" if unrealized >= 0 else ""

    print("💵 CAPITAL & BALANCE LEDGER:")
    print(f"  • Total Portfolio Equity:        ${equity:,.2f} USDT")
    print(f"  • Total Active Invested Margin:  ${invested:,.2f} USDT ({len(open_pos)} active positions)")
    print(f"  • Remaining Available Cash:      ${cash:,.2f} USDT")
    print(f"  • Floating Unrealized PnL:       {upnl_sign}${unrealized:,.2f} USDT")
    print(f"  • Today's Cumulative Net Profit: {pnl_sign}${daily_pnl:,.2f} USDT ({wins}W / {losses}L | Win Rate: {win_rate}%)")
    print(f"  • Total Closed Trades Today:     {trades_count}")

    if open_pos:
        print("\n📈 ACTIVE OPEN POSITIONS:")
        for p in open_pos:
            direction = p.get("direction", "LONG")
            tag = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
            p_pnl = p.get("pnl", 0.0)
            sign = "+" if p_pnl >= 0 else ""
            print(f"  • {p.get('symbol'):8} ({tag}) | Invested: ${p.get('usdt_size', 0):,.2f} | Entry: ${p.get('entry', 0):,.4f} | Live Price: ${p.get('current_price', 0):,.4f} | PnL: {sign}${p_pnl:,.2f}")
    else:
        print("\n📈 ACTIVE OPEN POSITIONS: None (Ready for next institutional alpha setup)")

    if recent_trades:
        print("\n📜 RECENT CLOSED TRADES:")
        for t in recent_trades[:5]:
            t_pnl = t.get("pnl", 0.0)
            sign = "+" if t_pnl >= 0 else ""
            print(f"  • {t.get('timestamp')[:19]} | {t.get('symbol'):8} ({t.get('direction')}) | Entry: ${t.get('entry', 0):,.4f} -> Exit: ${t.get('exit', 0):,.4f} | PnL: {sign}${t_pnl:,.2f} USDT | Reason: {t.get('reason')}")

    if send_whatsapp:
        print("\nDispatching full portfolio report to Owner via WhatsApp (+91 84210 77613)...")
        whatsapp_service.notify_portfolio_status(
            equity=equity,
            cash=cash,
            invested=invested,
            unrealized_pnl=unrealized,
            daily_pnl=daily_pnl,
            wins=wins,
            losses=losses,
            open_positions=open_pos,
            regime="NORMAL"
        )
        print("✅ Report dispatched to Owner WhatsApp.")


if __name__ == "__main__":
    send_wa = "--whatsapp" in sys.argv
    print_and_report_portfolio(send_whatsapp=send_wa)
