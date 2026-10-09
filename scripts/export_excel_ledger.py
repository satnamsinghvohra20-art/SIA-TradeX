#!/usr/bin/env python3
"""
SIA-TradeX: Standalone Excel Ledger Exporter & Daily Income Sync
Exports and verifies the multi-tab Excel Workbook:
- Executive Dashboard
- Daily Income Summary (Every day's income)
- Every Trade Ledger (Every individual trade record)
"""

import sys
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

from storage.database import db
from storage.excel_ledger import excel_ledger


def run_export():
    print("=================================================================")
    print("SIA-TradeX: EXCEL LEDGER & DAILY INCOME EXPORTER")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=================================================================\n")

    print("[1/3] Fetching trades and daily income from SQLite database...")
    all_trades = db.get_all_trades()
    all_daily = db.get_all_daily_income()

    print(f"  • Total Individual Trades in DB: {len(all_trades)}")
    print(f"  • Total Daily Income Days in DB: {len(all_daily)}")

    print("\n[2/3] Daily Income Breakdown:")
    for d in all_daily:
        pnl = d.get("realized_income", 0.0)
        pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        print(f"  • Date: {d.get('date')} | Realized Income: {pnl_str:10} | Trades: {d.get('total_trades', 0):3} | Wins: {d.get('wins', 0):2} | Losses: {d.get('losses', 0):2} | Win Rate: {d.get('win_rate', 0.0):.1f}% | Protected Wins: {d.get('profit_protected_wins', 0)}")

    print("\n[3/3] Synchronizing Multi-Tab Excel Workbook...")
    success = db.sync_excel_ledger()

    if success:
        print("\n✅ EXCEL LEDGER GENERATED SUCCESSFULLY!")
        print(f"  • Primary Path: {excel_ledger.primary_file}")
        print(f"  • Root Mirror:  {excel_ledger.root_mirror_file}")
        print(f"  • File Size:    {excel_ledger.primary_file.stat().st_size:,} bytes")
        print("  • Sheets Included: ['Executive Dashboard', 'Daily Income Summary', 'Every Trade Ledger']")
    else:
        print("\n❌ Failed to synchronize Excel ledger.")


if __name__ == "__main__":
    run_export()
