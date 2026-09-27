"""
SIA-TradeX: Telegram Command & Notification Service
Interactive remote control, automated trade execution notifications, and panic circuit breaker.
"""

import time
import requests
import threading
from typing import Callable, Optional
from config.settings import settings


class TelegramService:
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.ok = bool(self.token and self.chat_id and self.token != "YOUR_TELEGRAM_BOT_TOKEN_HERE")
        self._base = f"https://api.telegram.org/bot{self.token}" if self.ok else ""
        self._offset = 0
        self._running = False
        self.paused = False

        # Command Callbacks
        self.cb_status: Optional[Callable[[], str]] = None
        self.cb_balance: Optional[Callable[[], str]] = None
        self.cb_close: Optional[Callable[[str], str]] = None
        self.cb_panic: Optional[Callable[[], str]] = None
        self.cb_trade: Optional[Callable[[str, str, Optional[float], bool], None]] = None
        self.cb_regime: Optional[Callable[[], str]] = None

    def send_message(self, text: str, parse_mode: str = "HTML"):
        if not self.ok:
            return
        try:
            requests.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text[:4000],
                    "parse_mode": parse_mode
                },
                timeout=6.0
            )
        except Exception:
            pass

    def notify_trade_open(self, pos, score: int, regime: str, ai_reason: str):
        tag = "PAPER" if settings.PAPER_MODE else "LIVE"
        arrow = "🟢 LONG" if pos.direction == "LONG" else "🔴 SHORT"
        self.send_message(
            f"⚡ <b>[{tag}] TRADE OPENED: {pos.symbol}</b>\n"
            f"Direction: <b>{arrow}</b> | Score: <b>{score}</b>\n"
            f"Entry: <code>${pos.entry:,.4f}</code>\n"
            f"TP1: <code>${pos.tp:,.4f}</code> | TP2: <code>${pos.tp2:,.4f}</code> | SL: <code>${pos.sl:,.4f}</code>\n"
            f"Margin: ${pos.usdt_size:.1f} ({pos.leverage}x Lev)\n"
            f"Regime: <i>{regime}</i>\n"
            f"AI Verdict: <i>{ai_reason[:80]}</i>"
        )

    def notify_trade_close(self, sym: str, direction: str, pnl: float, reason: str, daily_pnl: float, equity: float):
        tag = "🏆 PROFIT" if pnl >= 0 else "🛑 LOSS"
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        self.send_message(
            f"<b>[{tag}] CLOSED {sym} ({direction})</b>\n"
            f"Realized P&L: <b>{pnl_str}</b>\n"
            f"Exit Reason: <i>{reason}</i>\n"
            f"Today's Net: <b>${daily_pnl:+.2f}</b> | Balance: <b>${equity:,.2f}</b>"
        )

    def notify_profit_protect(self, sym: str, direction: str, pnl: float, peak: float, reasons: list, equity: float):
        self.send_message(
            f"🛡️ <b>[PROFIT PROTECTED] {sym} ({direction})</b>\n"
            f"Locked Gain: <b>+${pnl:.2f}</b> (Peak was +${peak:.2f})\n"
            f"Signals:\n" + "\n".join(f"  • {r}" for r in reasons[:3]) + "\n"
            f"<i>Exited before reversal/stop-loss hit! Balance: ${equity:,.2f}</i>"
        )

    def _handle_update(self, update: dict):
        msg = update.get("message") or update.get("channel_post") or {}
        text = (msg.get("text") or "").strip()
        if not text:
            return

        chat_id = str(msg.get("chat", {}).get("id", ""))
        if str(self.chat_id) and chat_id != str(self.chat_id):
            return

        parts = text.split()
        cmd = parts[0].lower()

        if cmd == "/status":
            if self.cb_status:
                self.send_message(self.cb_status())

        elif cmd == "/balance":
            if self.cb_balance:
                self.send_message(self.cb_balance())

        elif cmd == "/regime":
            if self.cb_regime:
                self.send_message(self.cb_regime())

        elif cmd in ("/long", "/short"):
            if len(parts) < 2:
                self.send_message(f"Usage: {cmd} BTCUSDT [size]")
                return
            sym = parts[1].upper()
            if not sym.endswith("USDT"):
                sym += "USDT"
            size = float(parts[2]) if len(parts) >= 3 else None
            direction = "LONG" if cmd == "/long" else "SHORT"
            self.send_message(f"Evaluating {direction} {sym} through confluence gates...")
            if self.cb_trade:
                self.cb_trade(sym, direction, size, False)

        elif cmd in ("/forcelong", "/forceshort"):
            if len(parts) < 2:
                self.send_message(f"Usage: {cmd} BTCUSDT")
                return
            sym = parts[1].upper()
            if not sym.endswith("USDT"):
                sym += "USDT"
            direction = "LONG" if "long" in cmd else "SHORT"
            self.send_message(f"⚡ OVERRIDE: Executing immediate market {direction} on {sym}!")
            if self.cb_trade:
                self.cb_trade(sym, direction, None, True)

        elif cmd == "/close":
            sym = parts[1].upper() if len(parts) >= 2 else ""
            if not sym.endswith("USDT") and sym:
                sym += "USDT"
            if self.cb_close:
                self.send_message(self.cb_close(sym))

        elif cmd in ("/panic", "/closeall"):
            self.send_message("🚨 <b>PANIC TRIGGERED:</b> Closing all open positions at market!")
            if self.cb_panic:
                self.send_message(self.cb_panic())

        elif cmd == "/pause":
            self.paused = True
            self.send_message("⏸️ Auto-trading <b>PAUSED</b>. Active positions will still manage exits.")

        elif cmd == "/resume":
            self.paused = False
            self.send_message("▶️ Auto-trading <b>RESUMED</b>.")

        elif cmd in ("/help", "/start"):
            self.send_message(
                "<b>SIA-TradeX Pro Commands</b>\n"
                "/status - Active positions and metrics\n"
                "/balance - Live wallet & equity\n"
                "/regime - Real-time market regime analysis\n"
                "/long SYMBOL - Check confluence & enter Long\n"
                "/short SYMBOL - Check confluence & enter Short\n"
                "/close SYMBOL - Close specific position\n"
                "/panic - Immediate close-all circuit breaker\n"
                "/pause | /resume - Toggle automated entries"
            )

    def run_loop(self):
        if not self.ok:
            return
        self._running = True
        while self._running:
            try:
                r = requests.get(
                    f"{self._base}/getUpdates",
                    params={"offset": self._offset, "timeout": 2},
                    timeout=8.0
                )
                if r.status_code == 200:
                    data = r.json()
                    for u in data.get("result", []):
                        self._offset = u["update_id"] + 1
                        self._handle_update(u)
            except Exception:
                pass
            time.sleep(settings.TG_POLL_INTERVAL)

    def stop(self):
        self._running = False


telegram_service = TelegramService()
