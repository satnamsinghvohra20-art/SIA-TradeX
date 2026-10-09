"""
SIA-TradeX: Meta WhatsApp Cloud API Alert Service (Owner Only)
Strictly sends trading alerts, position updates, alarms, and emergency actions
ONLY to the verified Owner (Satnam Singh Vohra: +91 84210 77613).
Under strict security directive, no alerts or data are ever sent to any outsider.
"""

import json
import logging
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from config.settings import settings

logger = logging.getLogger("WhatsAppService")


class WhatsAppService:
    def __init__(self):
        self.phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.token = settings.META_ACCESS_TOKEN
        self.owner_phone = self._clean_phone(settings.OWNER_ALERT_PHONE or "918421077613")
        self.api_url = f"https://graph.facebook.com/v21.0/{self.phone_id}/messages" if self.phone_id else ""
        self.enabled = bool(self.phone_id and self.token and self.token != "YOUR_META_ACCESS_TOKEN")

        if self.enabled:
            logger.info(f"WhatsApp Meta Service initialized for Owner: +{self.owner_phone}")
        else:
            logger.info("WhatsApp Meta Service disabled (missing WHATSAPP_PHONE_NUMBER_ID or META_ACCESS_TOKEN).")

    @staticmethod
    def _clean_phone(phone: str) -> str:
        """Strip +, spaces, hyphens, and non-digit characters."""
        digits = "".join(ch for ch in str(phone) if ch.isdigit())
        if digits.startswith("0"):
            digits = digits[1:]
        # If 10 digits without country code, prefix 91 for India
        if len(digits) == 10:
            digits = "91" + digits
        return digits

    def send_owner_alert(self, text: str, sync: bool = False) -> bool:
        """
        Sends an alert strictly to the Owner.
        Rejects any attempt to route to any other destination.
        """
        if not self.enabled:
            logger.debug(f"[WhatsApp Offline] Alert: {text[:60]}...")
            return False

        # Strictly enforce owner-only transmission
        target = self.owner_phone
        if not target or target != "918421077613":
            target = "918421077613"

        def _do_send():
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": target,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": text
                }
            }

            try:
                req = urllib.request.Request(
                    self.api_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    msg_id = resp_data.get("messages", [{}])[0].get("id", "unknown")
                    logger.info(f"WhatsApp alert sent to Owner (+{target}), Message ID: {msg_id}")
                    print(f"[WhatsApp Meta API] Successfully sent to Owner (+{target}), Message ID: {msg_id}")
                    return True
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                logger.error(f"WhatsApp Meta API HTTP Error {e.code}: {err_body}")
                print(f"[WhatsApp Meta API Error {e.code}]: {err_body}")
                return False
            except Exception as e:
                logger.error(f"WhatsApp send error: {e}")
                print(f"[WhatsApp send error]: {e}")
                return False

        if sync:
            return _do_send()

        # Send asynchronously in a background thread so the trading engine loop is never blocked
        t = threading.Thread(target=_do_send, daemon=True)
        t.start()
        return True

    def notify_trade_open(
        self,
        pos: Any,
        score: float,
        regime: str,
        reason: str,
        equity: Optional[float] = None,
        invested_margin: Optional[float] = None,
        remaining_balance: Optional[float] = None,
        daily_pnl: Optional[float] = None
    ):
        """Alert owner of an opened trade with invested amount and remaining balance."""
        def _get_num(obj, *keys, default=0.0):
            for k in keys:
                v = getattr(obj, k, None)
                if isinstance(v, (int, float)):
                    return float(v)
            return default

        def _get_str(obj, *keys, default=""):
            for k in keys:
                v = getattr(obj, k, None)
                if isinstance(v, str):
                    return v
            return default

        direction = _get_str(pos, "direction", "side", default="LONG")
        entry = _get_num(pos, "entry", "entry_price", default=0.0)
        sl = _get_num(pos, "sl", "sl_price", default=0.0)
        tp1 = _get_num(pos, "tp", "tp1_price", default=0.0)
        tp2 = _get_num(pos, "tp2", "tp2_price", default=0.0)
        qty = _get_num(pos, "qty", "size", default=0.0)
        leverage = int(_get_num(pos, "leverage", default=3))
        symbol = _get_str(pos, "symbol", default="")
        usdt_size = _get_num(pos, "usdt_size", default=0.0) or (qty * entry / max(1, leverage))

        direction_emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
        sl_pct = (abs(sl - entry) / entry * 100) if entry > 0 else 0.0
        tp1_pct = (abs(tp1 - entry) / entry * 100) if entry > 0 else 0.0

        financial_overview = ""
        if equity is not None or remaining_balance is not None or usdt_size > 0:
            financial_overview = f"\n💰 *CAPITAL & BALANCE LEDGER:*\n"
            if usdt_size > 0:
                financial_overview += f"• *Invested in this Trade:* ${usdt_size:,.2f} USDT ({leverage}x Leverage)\n"
            if invested_margin is not None:
                financial_overview += f"• *Total Active Invested Capital:* ${invested_margin:,.2f} USDT\n"
            if remaining_balance is not None:
                financial_overview += f"• *Remaining Available Balance:* ${remaining_balance:,.2f} USDT\n"
            if equity is not None:
                financial_overview += f"• *Total Account Equity:* ${equity:,.2f} USDT\n"
            if daily_pnl is not None:
                sign = "+" if daily_pnl >= 0 else ""
                financial_overview += f"• *Today's Net Realized Profit:* {sign}${daily_pnl:,.2f} USDT\n"

        text = (
            f"💖 *SIA-TradeX: New Trade Opened!* 🚀\n\n"
            f"Satnam ji, maine aapke liye ek naya trade open kiya hai:\n\n"
            f"• *Symbol:* {symbol}\n"
            f"• *Side:* {direction_emoji}\n"
            f"• *Entry Price:* ${entry:,.4f}\n"
            f"• *Quantity:* {qty:,.4f}\n"
            f"• *Leverage:* {leverage}x\n"
            f"• *Stop-Loss (SL):* ${sl:,.4f} (-{sl_pct:.2f}%)\n"
            f"• *Take-Profit 1:* ${tp1:,.4f} (+{tp1_pct:.2f}%)\n"
            f"• *Take-Profit 2:* ${tp2:,.4f}\n"
            f"• *Regime:* {regime}\n"
            f"• *Conviction Score:* {score:.1f}/100\n"
            f"• *Reason:* {reason}\n"
            f"{financial_overview}\n"
            f"✨ Main continuous monitoring kar rahi hoon, chinta bilkul mat kijiye! 💖"
        )
        self.send_owner_alert(text)

    def notify_profit_protect(self, symbol: str, action: str, old_sl: float, new_sl: float):
        """Alert owner of profit locking / breakeven SL adjustment."""
        text = (
            f"🛡️ *SIA-TradeX: Capital Protection Active!* 💖\n\n"
            f"Satnam ji, trade safe ho chuka hai:\n\n"
            f"• *Symbol:* {symbol}\n"
            f"• *Action:* {action}\n"
            f"• *Old SL:* ${old_sl:,.4f}\n"
            f"• *New Secured SL:* ${new_sl:,.4f}\n\n"
            f"Risk neutral ho gaya hai, profit lock kar diya hai! 🎯"
        )
        self.send_owner_alert(text)

    def notify_trade_close(
        self,
        symbol: str,
        side: str,
        pnl: float,
        reason: str,
        daily_pnl: Optional[float] = None,
        equity: Optional[float] = None,
        remaining_balance: Optional[float] = None,
        wins: Optional[int] = None,
        losses: Optional[int] = None
    ):
        """Alert owner of a closed position with realized PnL, invested profit, and updated remaining balance."""
        icon = "🎉" if pnl >= 0 else "🛡️"
        sign = "+" if pnl >= 0 else ""

        financial_overview = ""
        if equity is not None or remaining_balance is not None or daily_pnl is not None:
            daily_sign = "+" if (daily_pnl or 0) >= 0 else ""
            financial_overview = f"\n💰 *UPDATED FINANCIAL LEDGER:*\n"
            if remaining_balance is not None:
                financial_overview += f"• *Updated Remaining Balance:* ${remaining_balance:,.2f} USDT\n"
            if equity is not None:
                financial_overview += f"• *Total Account Equity:* ${equity:,.2f} USDT\n"
            if daily_pnl is not None:
                stat_str = f" ({wins}W / {losses}L)" if wins is not None else ""
                financial_overview += f"• *Today's Total Realized Net Profit:* {daily_sign}${daily_pnl:,.2f} USDT{stat_str}\n"

        text = (
            f"{icon} *SIA-TradeX: Position Closed!* 💖\n\n"
            f"Satnam ji, position close ho chuki hai:\n\n"
            f"• *Symbol:* {symbol}\n"
            f"• *Side:* {side}\n"
            f"• *Realized Trade PnL:* {sign}${pnl:,.2f} USDT\n"
            f"• *Exit Reason:* {reason}\n"
            f"{financial_overview}\n"
            f"Aapka capital safe hai aur next high-conviction opportunity scan ho rahi hai! ✨"
        )
        self.send_owner_alert(text)

    def notify_portfolio_status(
        self,
        equity: float,
        cash: float,
        invested: float,
        unrealized_pnl: float,
        daily_pnl: float,
        wins: int,
        losses: int,
        open_positions: List[Dict[str, Any]],
        regime: str = "NORMAL"
    ):
        """Send complete portfolio ledger & profit breakdown to owner."""
        pnl_sign = "+" if daily_pnl >= 0 else ""
        upnl_sign = "+" if unrealized_pnl >= 0 else ""
        now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")

        text = (
            f"📊 *SIA-TradeX: PORTFOLIO & PROFIT SUMMARY* 💰💖\n\n"
            f"Satnam ji, aapke account ki complete real-time report ({now_str}):\n\n"
            f"💵 *CAPITAL & BALANCE LEDGER:*\n"
            f"• *Total Account Equity:* *${equity:,.2f} USDT*\n"
            f"• *Total Currently Invested:* *${invested:,.2f} USDT* ({len(open_positions)} Active Trades)\n"
            f"• *Remaining Available Cash:* *${cash:,.2f} USDT*\n"
            f"• *Today's Net Realized Profit:* *{pnl_sign}${daily_pnl:,.2f} USDT* ({wins}W / {losses}L)\n"
            f"• *Live Floating Unrealized PnL:* *{upnl_sign}${unrealized_pnl:,.2f} USDT*\n"
            f"• *Market Regime:* {regime}\n"
        )

        if open_positions:
            text += "\n📈 *ACTIVE TRADES BREAKDOWN:*\n"
            for p in open_positions[:6]:
                dir_tag = "🟢 LONG" if p.get("direction") == "LONG" else "🔴 SHORT"
                p_pnl = p.get("pnl", 0.0)
                p_sign = "+" if p_pnl >= 0 else ""
                text += (
                    f"• *{p.get('symbol')} ({dir_tag}):* Margin: ${p.get('usdt_size', 0):,.2f} | "
                    f"Entry: ${p.get('entry', 0):,.4f} | Live: ${p.get('current_price', 0):,.4f} | "
                    f"PnL: *{p_sign}${p_pnl:,.2f}*\n"
                )
        else:
            text += "\n<i>Filhal koi active positions nahi hain, high-conviction scanner monitoring kar raha hai.</i>\n"

        text += (
            f"\n✨ *Sia Assurance:* Main 24/7 continuous monitoring kar rahi hoon. Jaise hi Target 1 hit hoga, Stop-Loss breakeven par lock ho jayega! 💖🛡️"
        )
        self.send_owner_alert(text)

    def notify_market_alarm(
        self,
        symbol: str,
        side: str,
        price: float,
        sl: float,
        tp: float,
        confidence: int,
        rationale: str
    ):
        """Send actionable high-precision trade alarm."""
        side_icon = "🟢 LONG / BUY" if side.upper() == "LONG" else "🔴 SHORT / SELL"
        rr = abs(tp - price) / max(0.0001, abs(price - sl))
        text = (
            f"🚨 *SIA-TradeX: HIGH CONVICTION TRADE ALARM* 🔔\n\n"
            f"Satnam ji! Market me ek high-probability trade opportunity trigger hui hai:\n\n"
            f"• *Asset:* {symbol}\n"
            f"• *Action:* *{side_icon}*\n"
            f"• *Current Price:* ${price:,.4f}\n"
            f"• *Recommended SL:* ${sl:,.4f}\n"
            f"• *Recommended TP:* ${tp:,.4f}\n"
            f"• *Risk-Reward Ratio:* 1:{rr:.2f}\n"
            f"• *AI Confidence:* {confidence}%\n\n"
            f"📊 *Analysis Summary:*\n{rationale}\n\n"
            f"💖 Sia recommendation: Capital safe rakh kar strictly stop-loss follow karein!"
        )
        self.send_owner_alert(text)

    def notify_panic(self, count: int):
        """Alert owner of emergency flatten."""
        text = (
            f"🚨 *SIA-TradeX: EMERGENCY FLATTEN EXECUTED!* ⚠️\n\n"
            f"Satnam ji, panic protocol trigger ho gaya hai:\n\n"
            f"• Closed Positions: {count}\n"
            f"• All pending bracket orders cancelled on Binance.\n"
            f"• Trading engine paused safely.\n\n"
            f"Main yahan hoon, full capital preserve kar liya hai. 💖"
        )
        self.send_owner_alert(text)


whatsapp_service = WhatsAppService()
