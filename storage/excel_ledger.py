"""
SIA-TradeX: Multi-Tab Professional Excel Ledger & Daily Income Synchronizer
Maintains live, automated Excel workbooks containing:
1. Daily Income Summary (Every day's income, cumulative profit, win rate, ending balance & equity)
2. Every Trade Ledger (Complete granular record of every closed trade with entry, exit, PnL, reason)
3. Executive KPI Dashboard (Top-level trading statistics, peak returns, drawdown, win rate)
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

logger = logging.getLogger("SIA-TradeX.ExcelLedger")


class ExcelLedgerManager:
    def __init__(self, root_dir: Optional[Path] = None):
        if root_dir is None:
            self.root_dir = Path(__file__).resolve().parent.parent
        else:
            self.root_dir = root_dir

        self.reports_dir = self.root_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.primary_file = self.reports_dir / "SIA_TradeX_Income_Ledger.xlsx"
        self.root_mirror_file = self.root_dir / "SIA_TradeX_Income_Ledger.xlsx"

    def sync_ledger(
        self,
        trades: List[Dict[str, Any]],
        daily_incomes: List[Dict[str, Any]],
        current_balance: float = 1000.0,
        current_equity: float = 1000.0
    ) -> bool:
        """
        Synchronizes all trades and daily income records into a multi-tab styled Excel workbook.
        """
        if not OPENPYXL_AVAILABLE:
            logger.warning("openpyxl is not installed. Excel sync skipped.")
            return False

        wb = openpyxl.Workbook()
        # Remove default sheet
        wb.remove(wb.active)

        # Styling tokens
        font_family = "Segoe UI"
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
        sub_header_fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
        sub_header_font = Font(name=font_family, size=10, bold=True, color="F8FAFC")

        profit_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        profit_font = Font(name=font_family, size=10, bold=True, color="166534")
        loss_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
        loss_font = Font(name=font_family, size=10, bold=True, color="991B1B")

        data_font = Font(name=font_family, size=10)
        bold_data_font = Font(name=font_family, size=10, bold=True)
        center_align = Alignment(horizontal="center", vertical="center")
        left_align = Alignment(horizontal="left", vertical="center")
        right_align = Alignment(horizontal="right", vertical="center")

        thin_border_side = Side(border_style="thin", color="CBD5E1")
        cell_border = Border(top=thin_border_side, left=thin_border_side, right=thin_border_side, bottom=thin_border_side)

        # ----------------------------------------------------
        # TAB 1: DAILY INCOME SUMMARY (Every Day Ki Income)
        # ----------------------------------------------------
        ws_daily = wb.create_sheet(title="Daily Income Summary")
        ws_daily.views.sheetView[0].showGridLines = True

        daily_headers = [
            "Date (UTC)",
            "Daily Realized Income ($ USDT)",
            "Cumulative Income ($ USDT)",
            "Total Trades",
            "Wins",
            "Losses",
            "Win Rate (%)",
            "Capital Protected Wins",
            "Ending Wallet Balance ($ USDT)",
            "Total Portfolio Equity ($ USDT)",
            "Daily Status"
        ]

        # Header Title Banner
        ws_daily.merge_cells("A1:K1")
        banner_cell = ws_daily["A1"]
        banner_cell.value = "SIA-TradeX: DAILY INCOME & PROFIT SUMMARY LEDGER"
        banner_cell.font = Font(name=font_family, size=14, bold=True, color="FFFFFF")
        banner_cell.fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
        banner_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws_daily.row_dimensions[1].height = 36

        # Column Headers
        ws_daily.row_dimensions[2].height = 26
        for col_idx, h_text in enumerate(daily_headers, start=1):
            cell = ws_daily.cell(row=2, column=col_idx, value=h_text)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = cell_border

        # Populate Daily Income Rows
        row_idx = 3
        cumulative_pnl = 0.0
        for d in daily_incomes:
            d_pnl = float(d.get("realized_income", d.get("pnl", 0.0)))
            cumulative_pnl += d_pnl
            wins = int(d.get("wins", 0))
            losses = int(d.get("losses", 0))
            trades_count = int(d.get("total_trades", d.get("trades_count", wins + losses)))
            win_rate = float(d.get("win_rate", (wins / max(1, trades_count)) * 100))
            pp_wins = int(d.get("profit_protected_wins", 0))
            end_bal = float(d.get("ending_balance", current_balance))
            end_eq = float(d.get("ending_equity", current_equity))

            status = "🟢 PROFIT" if d_pnl > 0 else ("🔴 LOSS" if d_pnl < 0 else "⚪ BREAKEVEN")

            ws_daily.row_dimensions[row_idx].height = 22
            row_vals = [
                d.get("date", ""),
                d_pnl,
                cumulative_pnl,
                trades_count,
                wins,
                losses,
                win_rate / 100.0,
                pp_wins,
                end_bal,
                end_eq,
                status
            ]

            for c_idx, val in enumerate(row_vals, start=1):
                cell = ws_daily.cell(row=row_idx, column=c_idx, value=val)
                cell.font = data_font
                cell.border = cell_border

                if c_idx == 1:
                    cell.alignment = center_align
                elif c_idx in (2, 3):
                    cell.number_format = "$#,##0.00;($#,##0.00);\"$0.00\""
                    cell.alignment = right_align
                    if val > 0:
                        cell.fill = profit_fill
                        cell.font = profit_font
                    elif val < 0:
                        cell.fill = loss_fill
                        cell.font = loss_font
                elif c_idx in (4, 5, 6, 8):
                    cell.number_format = "#,##0"
                    cell.alignment = center_align
                elif c_idx == 7:
                    cell.number_format = "0.0%"
                    cell.alignment = center_align
                elif c_idx in (9, 10):
                    cell.number_format = "$#,##0.00"
                    cell.alignment = right_align
                elif c_idx == 11:
                    cell.alignment = center_align
                    if "PROFIT" in str(val):
                        cell.fill = profit_fill
                        cell.font = profit_font
                    elif "LOSS" in str(val):
                        cell.fill = loss_fill
                        cell.font = loss_font

            row_idx += 1

        # Total Summary Row for Daily Sheet
        if daily_incomes:
            ws_daily.row_dimensions[row_idx].height = 24
            ws_daily.cell(row=row_idx, column=1, value="TOTAL ALL-TIME").font = bold_data_font
            ws_daily.cell(row=row_idx, column=1).alignment = center_align
            ws_daily.cell(row=row_idx, column=1).fill = sub_header_fill
            ws_daily.cell(row=row_idx, column=1).font = sub_header_font

            for c_idx in range(2, 12):
                cell = ws_daily.cell(row=row_idx, column=c_idx)
                cell.fill = sub_header_fill
                cell.font = sub_header_font
                cell.border = cell_border

            # Total PnL formula / value
            tot_pnl_cell = ws_daily.cell(row=row_idx, column=2, value=cumulative_pnl)
            tot_pnl_cell.number_format = "$#,##0.00;($#,##0.00);\"$0.00\""
            tot_pnl_cell.alignment = right_align

            cum_pnl_cell = ws_daily.cell(row=row_idx, column=3, value=cumulative_pnl)
            cum_pnl_cell.number_format = "$#,##0.00;($#,##0.00);\"$0.00\""
            cum_pnl_cell.alignment = right_align

            ws_daily.cell(row=row_idx, column=4, value=sum(int(d.get("total_trades", d.get("trades_count", 0))) for d in daily_incomes)).alignment = center_align
            ws_daily.cell(row=row_idx, column=5, value=sum(int(d.get("wins", 0)) for d in daily_incomes)).alignment = center_align
            ws_daily.cell(row=row_idx, column=6, value=sum(int(d.get("losses", 0)) for d in daily_incomes)).alignment = center_align
            tot_trades = sum(int(d.get("total_trades", d.get("trades_count", 0))) for d in daily_incomes)
            tot_wins = sum(int(d.get("wins", 0)) for d in daily_incomes)
            avg_wr = (tot_wins / max(1, tot_trades))
            ws_daily.cell(row=row_idx, column=7, value=avg_wr).number_format = "0.0%"
            ws_daily.cell(row=row_idx, column=7).alignment = center_align

            ws_daily.cell(row=row_idx, column=9, value=current_balance).number_format = "$#,##0.00"
            ws_daily.cell(row=row_idx, column=9).alignment = right_align
            ws_daily.cell(row=row_idx, column=10, value=current_equity).number_format = "$#,##0.00"
            ws_daily.cell(row=row_idx, column=10).alignment = right_align
            ws_daily.cell(row=row_idx, column=11, value="ACTIVE LEDGER").alignment = center_align

        # Auto-adjust column widths for Daily sheet
        for col in ws_daily.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws_daily.column_dimensions[col_letter].width = max(max_len + 4, 14)

        # ----------------------------------------------------
        # TAB 2: EVERY TRADE LEDGER (Every Trade Ke Sath)
        # ----------------------------------------------------
        ws_trades = wb.create_sheet(title="Every Trade Ledger")
        ws_trades.views.sheetView[0].showGridLines = True

        trade_headers = [
            "Trade ID",
            "Date & Time (UTC)",
            "Symbol",
            "Direction",
            "Leverage",
            "Entry Price ($)",
            "Exit Price ($)",
            "Trade Net PnL ($ USDT)",
            "Result",
            "Exit Reason",
            "Account Equity ($)",
            "Capital Protected",
            "Conviction Score",
            "Mode"
        ]

        # Trade Sheet Header Banner
        ws_trades.merge_cells("A1:N1")
        t_banner = ws_trades["A1"]
        t_banner.value = "SIA-TradeX: COMPREHENSIVE INDIVIDUAL TRADE EXECUTION AUDIT"
        t_banner.font = Font(name=font_family, size=14, bold=True, color="FFFFFF")
        t_banner.fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
        t_banner.alignment = Alignment(horizontal="center", vertical="center")
        ws_trades.row_dimensions[1].height = 36

        ws_trades.row_dimensions[2].height = 26
        for col_idx, h_text in enumerate(trade_headers, start=1):
            cell = ws_trades.cell(row=2, column=col_idx, value=h_text)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = cell_border

        t_row_idx = 3
        for t in trades:
            ws_trades.row_dimensions[t_row_idx].height = 20
            pnl = float(t.get("pnl", 0.0))
            is_win = pnl >= 0
            res_str = "🟢 WIN" if is_win else "🔴 LOSS"
            direction = t.get("direction", "LONG")
            dir_str = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
            prot_str = "🛡️ YES" if t.get("profit_protected") else "NO"
            mode_str = "LIVE FUTURES" if t.get("live") else "PAPER SIMULATOR"

            trade_vals = [
                str(t.get("id", ""))[:14],
                str(t.get("timestamp", ""))[:19],
                t.get("symbol", ""),
                dir_str,
                f"{t.get('leverage', 3)}x",
                float(t.get("entry", 0.0)),
                float(t.get("exit", 0.0)),
                pnl,
                res_str,
                t.get("reason", ""),
                float(t.get("equity", current_equity)),
                prot_str,
                int(t.get("score", 0)),
                mode_str
            ]

            for c_idx, val in enumerate(trade_vals, start=1):
                cell = ws_trades.cell(row=t_row_idx, column=c_idx, value=val)
                cell.font = data_font
                cell.border = cell_border

                if c_idx in (1, 2, 3, 4, 5, 9, 12, 13, 14):
                    cell.alignment = center_align
                elif c_idx in (6, 7):
                    cell.number_format = "$#,##0.0000"
                    cell.alignment = right_align
                elif c_idx == 8:
                    cell.number_format = "$#,##0.00;($#,##0.00);\"$0.00\""
                    cell.alignment = right_align
                    if pnl > 0:
                        cell.fill = profit_fill
                        cell.font = profit_font
                    elif pnl < 0:
                        cell.fill = loss_fill
                        cell.font = loss_font
                elif c_idx == 10:
                    cell.alignment = left_align
                elif c_idx == 11:
                    cell.number_format = "$#,##0.00"
                    cell.alignment = right_align

            t_row_idx += 1

        for col in ws_trades.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws_trades.column_dimensions[col_letter].width = max(max_len + 3, 12)

        # ----------------------------------------------------
        # TAB 3: EXECUTIVE KPI DASHBOARD
        # ----------------------------------------------------
        ws_dash = wb.create_sheet(title="Executive Dashboard", index=0)
        ws_dash.views.sheetView[0].showGridLines = True

        ws_dash.merge_cells("A1:E1")
        d_banner = ws_dash["A1"]
        d_banner.value = "SIA-TradeX: PORTFOLIO PERFORMANCE & INCOME EXECUTIVE DASHBOARD"
        d_banner.font = Font(name=font_family, size=14, bold=True, color="FFFFFF")
        d_banner.fill = PatternFill(start_color="1E1B4B", end_color="1E1B4B", fill_type="solid")
        d_banner.alignment = center_align
        ws_dash.row_dimensions[1].height = 40

        # KPI Metrics computation
        total_pnl = sum(float(t.get("pnl", 0.0)) for t in trades)
        total_trades_count = len(trades)
        wins_count = sum(1 for t in trades if float(t.get("pnl", 0.0)) > 0)
        losses_count = sum(1 for t in trades if float(t.get("pnl", 0.0)) < 0)
        win_rate_all = (wins_count / max(1, total_trades_count)) * 100
        best_trade = max([float(t.get("pnl", 0.0)) for t in trades], default=0.0)
        worst_trade = min([float(t.get("pnl", 0.0)) for t in trades], default=0.0)
        now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")

        kpis = [
            ("Core Account Status", "100% Real Live Binance Futures Engine / Paper Simulator"),
            ("Last Ledger Sync Timestamp", now_str),
            ("Initial Starting Capital", 1000.0),
            ("Current Wallet Balance (Free Cash)", current_balance),
            ("Total Portfolio Account Equity", current_equity),
            ("Cumulative Realized Net Income", total_pnl),
            ("Total Trades Executed", total_trades_count),
            ("Winning Trades", wins_count),
            ("Losing Trades", losses_count),
            ("All-Time Win Rate", win_rate_all / 100.0),
            ("Best Trade Profit", best_trade),
            ("Maximum Single Trade Drawdown", worst_trade),
            ("Capital Protection (Section 55 Protocol)", "Active Breakeven SL & Multi-Tier TP Enforced")
        ]

        ws_dash.row_dimensions[2].height = 10
        kpi_row = 3
        for label, val in kpis:
            ws_dash.row_dimensions[kpi_row].height = 24
            lbl_cell = ws_dash.cell(row=kpi_row, column=2, value=label)
            lbl_cell.font = bold_data_font
            lbl_cell.fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
            lbl_cell.alignment = left_align
            lbl_cell.border = cell_border

            val_cell = ws_dash.cell(row=kpi_row, column=3, value=val)
            val_cell.font = data_font
            val_cell.border = cell_border

            if isinstance(val, (int, float)):
                val_cell.font = bold_data_font
                if "Rate" in label:
                    val_cell.number_format = "0.0%"
                    val_cell.alignment = center_align
                elif "Count" in label or "Trades" in label:
                    val_cell.number_format = "#,##0"
                    val_cell.alignment = center_align
                else:
                    val_cell.number_format = "$#,##0.00;($#,##0.00);\"$0.00\""
                    val_cell.alignment = right_align
                    if "Income" in label or "Profit" in label:
                        if val > 0:
                            val_cell.fill = profit_fill
                            val_cell.font = profit_font
                        elif val < 0:
                            val_cell.fill = loss_fill
                            val_cell.font = loss_font
            else:
                val_cell.alignment = left_align

            kpi_row += 1

        ws_dash.column_dimensions["A"].width = 5
        ws_dash.column_dimensions["B"].width = 38
        ws_dash.column_dimensions["C"].width = 46
        ws_dash.column_dimensions["D"].width = 5

        # Save workbook safely to primary file and mirror to project root
        temp_file = self.reports_dir / "SIA_TradeX_Income_Ledger.tmp.xlsx"
        try:
            wb.save(temp_file)
            if temp_file.exists():
                # Replace primary file
                if self.primary_file.exists():
                    try:
                        os.replace(temp_file, self.primary_file)
                    except PermissionError:
                        # If file is open in Microsoft Excel, save with timestamp
                        ts_file = self.reports_dir / f"SIA_TradeX_Income_Ledger_{int(datetime.now().timestamp())}.xlsx"
                        wb.save(ts_file)
                        logger.warning(f"Primary Excel file was locked by Excel, saved to: {ts_file.name}")
                else:
                    os.replace(temp_file, self.primary_file)

            # Copy to root mirror
            try:
                import shutil
                shutil.copy2(self.primary_file, self.root_mirror_file)
            except Exception as e:
                logger.warning(f"Could not mirror Excel to root: {e}")

            logger.info(f"Successfully synchronized Excel Income Ledger ({len(trades)} trades, {len(daily_incomes)} days)")
            print(f"[Excel Sync] Successfully updated Excel Ledger: {self.primary_file}")
            return True

        except Exception as e:
            logger.error(f"Error saving Excel Income Ledger: {e}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            return False


excel_ledger = ExcelLedgerManager()
