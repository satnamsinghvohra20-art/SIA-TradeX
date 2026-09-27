"""
SIA-TradeX: Unified Engine Orchestrator
Coordinates multi-source data ingestion, AI evaluation, confluence gating, risk defense, and order execution.
"""

import time
import copy
import threading
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional

from config.settings import settings
from core.models import (
    Signal, Position, TradeRecord, MarketContext, MarketRegime, AISignalDecision
)
from core.queue import SignalQueue
from storage.database import db
from data.market_data import market_data
from data.polymarket import PolymarketFeed
from data.news_client import NewsFeed
from ai.gemini_service import gemini_service
from strategies.confluence import confluence_strategy
from strategies.regime import MarketRegimeDetector
from execution.paper_account import PaperAccount
from execution.risk_manager import risk_manager
from execution.profit_protector import ProfitProtector
from execution.binance_executor import BinanceExecutor
from ui.telegram_service import telegram_service
from ui.web_server import set_engine, broadcast_state


class QuantEngine:
    def __init__(self, live_mode: bool = False):
        self.live_mode = live_mode
        self.running = False
        self.consecutive_losses = 0
        self.positions: Dict[str, Position] = {}
        self._positions_lock = threading.Lock()
        self.latest_ai_event: Optional[Dict[str, Any]] = None

        # Core subsystems
        self.queue = SignalQueue()
        self.paper_account = PaperAccount()
        self.binance = BinanceExecutor()

        if self.live_mode:
            conn_ok = self.binance.connect()
            if not conn_ok:
                print("⚠️ [Binance] Live connection failed. Reverting safely to PAPER mode.")
                self.live_mode = False

        # Ingestion Feeds
        self.polymarket = PolymarketFeed(self.queue)
        self.news = NewsFeed(self.queue)

        # Wire Telegram callbacks
        telegram_service.cb_status = self.get_status_text
        telegram_service.cb_balance = self.get_balance_text
        telegram_service.cb_close = self.force_close_symbol
        telegram_service.cb_panic = self.force_close_all
        telegram_service.cb_trade = self.inject_manual_trade
        telegram_service.cb_regime = self.get_regime_text

        # Link engine reference to FastAPI
        set_engine(self)

    def get_equity(self) -> float:
        if self.live_mode:
            return self.binance.get_live_balance()
        with self._positions_lock:
            return self.paper_account.total_equity(self.positions, market_data.mark_price)

    def get_dashboard_snapshot(self) -> Dict[str, Any]:
        equity = self.get_equity()
        metrics = db.get_daily_metrics()

        pos_list = []
        with self._positions_lock:
            for sym, p in self.positions.items():
                cur_price = market_data.mark_price(sym) or p.entry
                mult = p.leverage * p.usdt_size
                pnl = ((cur_price - p.entry) / p.entry * mult) if p.direction == "LONG" else ((p.entry - cur_price) / p.entry * mult)
                pos_list.append({
                    "symbol": sym,
                    "direction": p.direction,
                    "entry": p.entry,
                    "current_price": cur_price,
                    "pnl": round(pnl, 2),
                    "tp": p.tp,
                    "tp2": p.tp2,
                    "sl": p.sl,
                    "usdt_size": p.usdt_size,
                    "leverage": p.leverage,
                    "age_mins": round((time.time() - p.ts) / 60, 1),
                })

        # Calculate current regime on BTC
        btc_ctx = market_data.get_market_context("BTCUSDT")
        current_heat = sum(p["usdt_size"] for p in pos_list) / max(equity, 1.0)

        return {
            "live_mode": self.live_mode,
            "equity": round(equity, 2),
            "daily_pnl": metrics["pnl"],
            "wins": metrics["wins"],
            "losses": metrics["losses"],
            "win_rate": metrics["win_rate"],
            "positions_count": len(pos_list),
            "max_positions": settings.MAX_OPEN_TRADES,
            "portfolio_heat": round(current_heat, 2),
            "regime": btc_ctx.regime.value if btc_ctx else "UNKNOWN",
            "positions": pos_list,
            "latest_ai_event": self.latest_ai_event,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }

    def get_status_text(self) -> str:
        snap = self.get_dashboard_snapshot()
        mode = "LIVE" if self.live_mode else "PAPER"
        lines = [
            f"<b>SIA-TradeX Pro Status ({mode})</b>",
            f"Equity: <code>${snap['equity']:,.2f}</code> | Today P&L: <b>{'+' if snap['daily_pnl']>=0 else ''}${snap['daily_pnl']:.2f}</b>",
            f"Win Rate: <b>{snap['win_rate']}%</b> ({snap['wins']}W / {snap['losses']}L)",
            f"Active Regime: <code>{snap['regime']}</code>",
            f"Open Positions ({snap['positions_count']}/{snap['max_positions']}):"
        ]
        if not snap["positions"]:
            lines.append("  <i>No active positions. Scanning markets...</i>")
        else:
            for p in snap["positions"]:
                tag = "🟢" if p["direction"] == "LONG" else "🔴"
                lines.append(
                    f"  {tag} <b>{p['symbol']}</b> {p['direction']} PnL: <b>${p['pnl']:+.2f}</b> (in: ${p['entry']:,.4f})"
                )
        return "\n".join(lines)

    def get_balance_text(self) -> str:
        eq = self.get_equity()
        mode = "LIVE FUTURES" if self.live_mode else "PAPER SIMULATOR"
        return f"<b>Wallet Balance ({mode}):</b>\nAvailable Equity: <code>${eq:,.2f} USDT</code>"

    def get_regime_text(self) -> str:
        btc_ctx = market_data.get_market_context("BTCUSDT")
        return (
            f"<b>Market Regime Analysis:</b>\n"
            f"BTC Regime: <code>{btc_ctx.regime.value}</code>\n"
            f"1h Trend: <code>{btc_ctx.momentum_1h or 'neutral'}</code>\n"
            f"4h Trend: <code>{btc_ctx.momentum_4h or 'neutral'}</code>\n"
            f"RSI 1h: <code>{btc_ctx.rsi_1h or 'N/A'}</code> | Funding: <code>{btc_ctx.funding_rate or 0.0:.5f}</code>"
        )

    def force_close_symbol(self, symbol: str) -> str:
        with self._positions_lock:
            pos = self.positions.get(symbol)
        if not pos:
            return f"No open position on {symbol}."
        self._close_position(pos, "MANUAL / FORCE CLOSE")
        return f"Closed {symbol} at market price."

    def force_close_all(self) -> str:
        with self._positions_lock:
            open_syms = list(self.positions.keys())
        if not open_syms:
            return "No positions currently open."
        for s in open_syms:
            with self._positions_lock:
                pos = self.positions.get(s)
            if pos:
                self._close_position(pos, "PANIC / EMERGENCY CLOSE ALL")
        return f"Emergency closed {len(open_syms)} positions."

    def inject_manual_trade(self, symbol: str, direction: str, size: Optional[float], force: bool):
        self.queue.add(Signal(
            symbol=symbol,
            direction=direction,
            source="manual",
            reason=f"Manual user trigger {'[FORCE]' if force else ''}",
            score=10 if force else 5,
            manual=True,
            size_override=size,
            force=force
        ))

    def _open_position(
        self,
        symbol: str,
        direction: str,
        score: int,
        usdt_size: float,
        reasons: List[str],
        sources: List[str],
        ai_decision: AISignalDecision,
        ctx: MarketContext
    ):
        price = ctx.price
        atr_val = ctx.atr or (price * 0.015)

        # TP / SL Levels (Multi-target + SL)
        if direction == "LONG":
            tp1 = price + (atr_val * settings.ATR_TP1_MULT)
            tp2 = price + (atr_val * settings.ATR_TP2_MULT)
            sl = price - (atr_val * settings.ATR_SL_MULT)
        else:
            tp1 = price - (atr_val * settings.ATR_TP1_MULT)
            tp2 = price - (atr_val * settings.ATR_TP2_MULT)
            sl = price + (atr_val * settings.ATR_SL_MULT)

        qty = (usdt_size * settings.DEFAULT_LEVERAGE) / price

        if self.live_mode:
            order, levels = self.binance.open_market_position(
                symbol, direction, usdt_size, tp1, tp2, sl
            )
            if not order or not levels:
                return
            price = levels["entry"]
            tp1, tp2, sl = levels["tp"], levels["tp2"], levels["sl"]
            qty = levels["qty"]
        else:
            if not self.paper_account.reserve_margin(usdt_size):
                return

        new_pos = Position(
            symbol=symbol,
            direction=direction,
            entry=price,
            tp=tp1,
            tp2=tp2,
            sl=sl,
            atr=atr_val,
            qty=qty,
            usdt_size=usdt_size,
            reason=" | ".join(reasons[:2]),
            sources=sources,
            score=score,
            ai_reason=ai_decision.reason,
            leverage=settings.DEFAULT_LEVERAGE
        )

        with self._positions_lock:
            self.positions[symbol] = new_pos

        # Notify via Telegram
        telegram_service.notify_trade_open(new_pos, score, ctx.regime.value, ai_decision.reason)

    def _close_position(self, pos: Position, reason: str, protect_reasons: Optional[List[str]] = None):
        symbol = pos.symbol
        price = market_data.mark_price(symbol) or pos.entry
        mult = pos.leverage * pos.usdt_size
        pnl = ((price - pos.entry) / pos.entry * mult) if pos.direction == "LONG" else ((pos.entry - price) / pos.entry * mult)

        if self.live_mode:
            self.binance.close_market_position(symbol, pos.direction, pos.qty)
        else:
            self.paper_account.release_margin(pos.usdt_size, pnl)

        with self._positions_lock:
            self.positions.pop(symbol, None)

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Persist trade record
        equity = self.get_equity()
        record = TradeRecord(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            symbol=symbol,
            direction=pos.direction,
            entry=pos.entry,
            exit=price,
            pnl=round(pnl, 2),
            reason=reason,
            sources=pos.sources,
            score=pos.score,
            ai_reason=pos.ai_reason,
            equity=round(equity, 2),
            profit_protected=bool(protect_reasons),
            live=self.live_mode,
            leverage=pos.leverage
        )
        db.record_trade(record)

        # Notify
        daily_metrics = db.get_daily_metrics()
        if protect_reasons:
            telegram_service.notify_profit_protect(
                symbol, pos.direction, pnl, pos.peak_pnl, protect_reasons, equity
            )
        else:
            telegram_service.notify_trade_close(
                symbol, pos.direction, pnl, reason, daily_metrics["pnl"], equity
            )

    def _process_signal_batch(self):
        equity = self.get_equity()
        metrics = db.get_daily_metrics()

        # Guardrails check
        can_trade, guard_reason = risk_manager.check_guardrails(
            metrics["pnl"], self.consecutive_losses, equity
        )
        if not can_trade and not telegram_service.paused:
            return

        # 1. Process manual override signals first
        manual_signals = self.queue.pop_manual()
        for sig in manual_signals:
            if sig.symbol in self.positions:
                continue
            ctx = market_data.get_market_context(sig.symbol)
            ai_decision = gemini_service.evaluate_signal(sig.symbol, sig.direction, ctx)
            size = sig.size_override or settings.MIN_TRADE_USDT
            self._open_position(
                sig.symbol, sig.direction, sig.score, size,
                [sig.reason], [sig.source], ai_decision, ctx
            )

        # 2. Process automated confluence signals
        merged_signals = self.queue.flush_merged()
        for item in merged_signals:
            sym = item["symbol"]
            direction = item["direction"]

            with self._positions_lock:
                if sym in self.positions:
                    continue
                if len(self.positions) >= settings.MAX_OPEN_TRADES:
                    break

            ctx = market_data.get_market_context(sym)

            # Quantitative Confluence Strategy Evaluation
            strat_eval = confluence_strategy.evaluate(sym, direction, ctx, equity)
            if strat_eval["blocked"]:
                continue

            # Risk & Correlation Check
            with self._positions_lock:
                corr_blocked, _ = risk_manager.check_correlation_exposure(
                    sym, direction, self.positions, equity
                )
                if corr_blocked:
                    continue

                heat_ok, _ = risk_manager.check_portfolio_heat(
                    self.positions, strat_eval["position_size"], equity
                )
                if not heat_ok:
                    continue

            # AI Evaluation via Gemini 2.5 Flash (Rate-Safe)
            ai_decision = gemini_service.evaluate_signal(sym, direction, ctx, item["reasons"])
            self.latest_ai_event = {
                "symbol": sym,
                "signal": ai_decision.signal,
                "confidence": ai_decision.confidence,
                "reason": ai_decision.reason
            }

            if settings.GEMINI_VETO and ai_decision.signal == "IGNORE":
                continue

            total_score = item["score"] + strat_eval["score_bonus"]
            if ai_decision.signal == direction and ai_decision.confidence >= 65:
                total_score += 2

            if total_score >= settings.MIN_SIGNAL_SCORE:
                self._open_position(
                    sym, direction, total_score, strat_eval["position_size"],
                    item["reasons"], item["sources"], ai_decision, ctx
                )

    def _check_positions_health(self):
        """Monitors open positions for Take Profit, Stop Loss, Trailing Stops, and Smart Exits."""
        with self._positions_lock:
            active_symbols = list(self.positions.keys())

        for sym in active_symbols:
            with self._positions_lock:
                pos = self.positions.get(sym)
            if not pos:
                continue

            price = market_data.mark_price(sym)
            if not price or price <= 0:
                continue

            mult = pos.leverage * pos.usdt_size
            pnl_usd = ((price - pos.entry) / pos.entry * mult) if pos.direction == "LONG" else ((pos.entry - price) / pos.entry * mult)

            # Update Peak PnL
            if pnl_usd > pos.peak_pnl:
                pos.peak_pnl = pnl_usd

            ctx = market_data.get_market_context(sym)

            # 1. Smart Profit Protection Check
            pp_title, pp_reasons = ProfitProtector.evaluate(pos, price, pnl_usd, ctx)
            if pp_title:
                self._close_position(pos, pp_title, protect_reasons=pp_reasons)
                continue

            # 2. Hard Take Profit & Stop Loss
            if pos.direction == "LONG":
                if price >= pos.tp2:
                    self._close_position(pos, "TAKE PROFIT (Target 2 Hit)")
                    continue
                elif price <= pos.sl:
                    self._close_position(pos, "STOP LOSS HIT")
                    continue
            else:
                if price <= pos.tp2:
                    self._close_position(pos, "TAKE PROFIT (Target 2 Hit)")
                    continue
                elif price >= pos.sl:
                    self._close_position(pos, "STOP LOSS HIT")
                    continue

            # 3. Trailing Stop
            if settings.TRAILING_STOP:
                trig_usd = pos.usdt_size * (settings.TRAILING_TRIGGER_PCT / 100.0)
                dist_usd = pos.usdt_size * (settings.TRAILING_DISTANCE_PCT / 100.0)
                if pos.peak_pnl >= trig_usd and pnl_usd <= (pos.peak_pnl - dist_usd):
                    self._close_position(pos, "TRAILING STOP TRIGGERED")
                    continue

            # 4. Smart Exit via Gemini
            age_min = (time.time() - pos.ts) / 60.0
            if age_min > 2.0:
                pnl_pct = (pnl_usd / pos.usdt_size) * 100.0
                exit_eval = gemini_service.evaluate_smart_exit(
                    sym, pos.direction, pos.entry, price, pnl_pct, age_min, ctx
                )
                if exit_eval.action == "EXIT" and exit_eval.confidence >= 70:
                    self._close_position(pos, f"SMART AI EXIT: {exit_eval.reason}")
                    continue

    def _autonomous_gemini_scanner(self):
        """Rotates through active symbols periodically to detect AI setups."""
        idx = 0
        while self.running:
            try:
                sym = settings.ACTIVE_SYMBOLS[idx % len(settings.ACTIVE_SYMBOLS)]
                idx += 1
                ctx = market_data.get_market_context(sym)
                decision = gemini_service.evaluate_signal(sym, "LONG", ctx)
                if decision.signal in ("LONG", "SHORT") and decision.confidence >= settings.GEMINI_AUTO_MIN_CONF:
                    self.queue.add(Signal(
                        symbol=sym,
                        direction=decision.signal,
                        source="gemini_auto",
                        reason=f"Gemini [{decision.confidence}%]: {decision.reason}",
                        score=3 if decision.confidence >= 75 else 2,
                        confidence=decision.confidence
                    ))
            except Exception:
                pass
            time.sleep(settings.GEMINI_AUTO_SCAN_SEC)

    def run(self):
        self.running = True

        # Launch background threads
        threads = [
            ("polymarket", self.polymarket.run_loop),
            ("news", self.news.run_loop),
            ("telegram", telegram_service.run_loop),
            ("gemini_scanner", self._autonomous_gemini_scanner),
        ]
        for name, target in threads:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()

        last_snap = 0.0
        while self.running:
            try:
                self._check_positions_health()
                self._process_signal_batch()

                now = time.time()
                if now - last_snap >= 5.0:
                    with self._positions_lock:
                        self.paper_account.snapshot(self.positions, market_data.mark_price)
                    last_snap = now

            except Exception:
                pass
            time.sleep(1.0)

    def stop(self):
        self.running = False
        self.polymarket.stop()
        self.news.stop()
        telegram_service.stop()
