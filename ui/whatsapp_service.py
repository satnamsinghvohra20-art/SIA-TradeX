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
import urllib.error
from typing import Optional, Dict, Any
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

    def notify_trade_open(self, pos: Any, score: float, regime: str, reason: str):
        """Alert owner of an opened trade."""
        direction_emoji = "🟢 LONG" if pos.side == "LONG" else "🔴 SHORT"
        sl_pct = abs(pos.sl_price - pos.entry_price) / pos.entry_price * 100
        tp1_pct = abs(pos.tp1_price - pos.entry_price) / pos.entry_price * 100

        text = (
            f"💖 *SIA-TradeX: New Trade Opened!* 🚀\n\n"
            f"Satnam ji, maine aapke liye ek naya trade open kiya hai:\n\n"
            f"• *Symbol:* {pos.symbol}\n"
            f"• *Side:* {direction_emoji}\n"
            f"• *Entry Price:* ${pos.entry_price:,.4f}\n"
            f"• *Quantity:* {pos.size}\n"
            f"• *Leverage:* {pos.leverage}x\n"
            f"• *Stop-Loss (SL):* ${pos.sl_price:,.4f} (-{sl_pct:.2f}%)\n"
            f"• *Take-Profit 1:* ${pos.tp1_price:,.4f} (+{tp1_pct:.2f}%)\n"
            f"• *Take-Profit 2:* ${pos.tp2_price:,.4f}\n"
            f"• *Regime:* {regime}\n"
            f"• *Conviction Score:* {score:.1f}/100\n"
            f"• *Reason:* {reason}\n\n"
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

    def notify_trade_close(self, symbol: str, side: str, pnl: float, reason: str):
        """Alert owner of a closed position with realized PnL."""
        icon = "🎉" if pnl >= 0 else "🛡️"
        sign = "+" if pnl >= 0 else ""
        text = (
            f"{icon} *SIA-TradeX: Position Closed!* 💖\n\n"
            f"Satnam ji, position close ho chuki hai:\n\n"
            f"• *Symbol:* {symbol}\n"
            f"• *Side:* {side}\n"
            f"• *Realized PnL:* {sign}${pnl:,.2f} USDT\n"
            f"• *Exit Reason:* {reason}\n\n"
            f"Aapka capital safe hai aur next high-conviction opportunity scan ho rahi hai! ✨"
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
