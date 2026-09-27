"""
SIA-TradeX: Live Binance Futures Execution
Connects directly to Binance USDT-M Futures API with precision rounding, isolated margin, and bracket orders.
"""

import math
from typing import Dict, Tuple, Optional, Any
from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException
from config.settings import settings
from data.market_data import market_data


class BinanceExecutor:
    def __init__(self):
        self.api_key = settings.BINANCE_API_KEY
        self.api_secret = settings.BINANCE_API_SECRET
        self.testnet = settings.BINANCE_TESTNET
        self.client: Optional[BinanceClient] = None
        self._sym_info: Dict[str, Dict[str, float]] = {}
        self.connected = False

    def connect(self) -> bool:
        if not self.api_key or self.api_key == "YOUR_BINANCE_API_KEY_HERE":
            return False

        try:
            self.client = BinanceClient(self.api_key, self.api_secret, testnet=self.testnet)
            self.client.futures_ping()
            self.connected = True
            self._prefetch_symbol_filters()
            return True
        except Exception:
            self.connected = False
            return False

    def _prefetch_symbol_filters(self):
        if not self.client:
            return
        try:
            info = self.client.futures_exchange_info()
            for s in info.get("symbols", []):
                sym = s["symbol"]
                entry = {"step": 1.0, "min_qty": 0.001, "tick": 0.01}
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        entry["step"] = float(f["stepSize"])
                        entry["min_qty"] = float(f["minQty"])
                    elif f["filterType"] == "PRICE_FILTER":
                        entry["tick"] = float(f["tickSize"])
                self._sym_info[sym] = entry
        except Exception:
            pass

    def get_live_balance(self) -> float:
        if not self.client:
            return 0.0
        try:
            for b in self.client.futures_account_balance():
                if b["asset"] == "USDT":
                    return float(b["availableBalance"])
        except Exception:
            pass
        return 0.0

    def round_qty(self, symbol: str, raw_qty: float) -> float:
        info = self._sym_info.get(symbol)
        if info:
            step = info["step"]
            qty = math.floor(raw_qty / step) * step
            decimals = len(f"{step:.10f}".rstrip("0").split(".")[-1])
            return max(round(qty, decimals), info["min_qty"])
        return round(raw_qty, 3)

    def round_price(self, symbol: str, raw_price: float) -> float:
        info = self._sym_info.get(symbol)
        if info:
            tick = info["tick"]
            decimals = len(f"{tick:.10f}".rstrip("0").split(".")[-1])
            return round(round(raw_price / tick) * tick, decimals)
        return round(raw_price, 2)

    def set_leverage_and_margin(self, symbol: str, leverage: int = settings.DEFAULT_LEVERAGE):
        if not self.client:
            return
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception:
            pass
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType="ISOLATED")
        except Exception:
            pass

    def open_market_position(
        self,
        symbol: str,
        direction: str,
        usdt_size: float,
        tp: float,
        tp2: float,
        sl: float
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not self.client:
            return None, None

        price = market_data.mark_price(symbol)
        if not price or price <= 0:
            return None, None

        qty = self.round_qty(symbol, (usdt_size * settings.DEFAULT_LEVERAGE) / price)
        if qty <= 0:
            return None, None

        self.set_leverage_and_margin(symbol)
        side = "BUY" if direction == "LONG" else "SELL"
        opp_side = "SELL" if direction == "LONG" else "BUY"

        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=qty
            )
            fill_price = float(order.get("avgPrice") or price)
            tp_rounded = self.round_price(symbol, tp2)
            sl_rounded = self.round_price(symbol, sl)

            # Attached Bracket Protection (Take Profit & Stop Loss)
            try:
                self.client.futures_create_order(
                    symbol=symbol,
                    side=opp_side,
                    type="TAKE_PROFIT_MARKET",
                    stopPrice=tp_rounded,
                    closePosition=True,
                    timeInForce="GTE_GTC"
                )
            except Exception:
                pass

            try:
                self.client.futures_create_order(
                    symbol=symbol,
                    side=opp_side,
                    type="STOP_MARKET",
                    stopPrice=sl_rounded,
                    closePosition=True,
                    timeInForce="GTE_GTC"
                )
            except Exception:
                pass

            levels = {
                "entry": fill_price,
                "tp": tp,
                "tp2": tp2,
                "sl": sl,
                "qty": qty
            }
            return order, levels

        except BinanceAPIException:
            return None, None

    def close_market_position(self, symbol: str, direction: str, qty: float) -> bool:
        if not self.client:
            return False
        opp_side = "SELL" if direction == "LONG" else "BUY"
        try:
            self.client.futures_create_order(
                symbol=symbol,
                side=opp_side,
                type="MARKET",
                quantity=self.round_qty(symbol, qty),
                reduceOnly=True
            )
            return True
        except Exception:
            return False
