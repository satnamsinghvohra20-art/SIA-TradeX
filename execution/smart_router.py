"""
SIA-TradeX Pro: Smart Order Router (SOR) with Maker-First Execution
Captures maker fee rebate (0.02% vs 0.05%) via Post-Only (GTX) placement, falling back to aggressive fill.
"""

import time
import logging
from typing import Dict, Tuple, Optional, Any
from config.settings import settings
from data.binance_stream import binance_stream
from data.market_data import market_data

logger = logging.getLogger("SIA-TradeX.Router")


class SmartOrderRouter:
    def __init__(self, binance_executor):
        self.executor = binance_executor
        self.stream = binance_stream
        self.post_only_timeout_sec = 0.400  # 400ms passive window

    def execute_maker_first_order(
        self,
        symbol: str,
        direction: str,
        usdt_size: float,
        tp: float,
        tp2: float,
        sl: float
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Attempts a Post-Only (GTX) limit fill at top-of-book. If unfilled within timeout,
        falls back to immediate market sweep for remaining unfilled balance.
        """
        client = self.executor.client
        if not client or not self.executor.connected:
            return None, None

        best_bid, best_ask = self.stream.get_best_bid_ask(symbol)
        if not best_bid or not best_ask:
            best_bid = best_ask = market_data.mark_price(symbol)

        if not best_bid or best_bid <= 0:
            return None, None

        # Price targeting:
        # Long: place at Best Bid (passive maker)
        # Short: place at Best Ask (passive maker)
        passive_price = self.executor.round_price(symbol, best_bid if direction == "LONG" else best_ask)
        qty = self.executor.round_qty(symbol, (usdt_size * settings.DEFAULT_LEVERAGE) / passive_price)

        if qty <= 0:
            return None, None

        self.executor.set_leverage_and_margin(symbol)
        side = "BUY" if direction == "LONG" else "SELL"
        opp_side = "SELL" if direction == "LONG" else "BUY"

        # 1. Post-Only (GTX) Attempt
        try:
            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                timeInForce="GTX",  # Post-Only: guarantees maker fee rebate
                price=passive_price,
                quantity=qty
            )
            order_id = order.get("orderId")

            # Wait up to 400ms for passive fill
            start = time.time()
            filled = False
            executed_qty = 0.0
            while time.time() - start < self.post_only_timeout_sec:
                check = client.futures_get_order(symbol=symbol, orderId=order_id)
                status = check.get("status")
                executed_qty = float(check.get("executedQty", 0.0))
                if status == "FILLED":
                    filled = True
                    order = check
                    break
                elif status in ("CANCELED", "EXPIRED", "REJECTED"):
                    break
                time.sleep(0.05)

            if not filled:
                # Cancel post-only order and sweep remaining unfilled quantity with market order
                try:
                    canceled = client.futures_cancel_order(symbol=symbol, orderId=order_id)
                    executed_qty = float(canceled.get("executedQty", executed_qty))
                except Exception:
                    pass

                rem_qty = self.executor.round_qty(symbol, qty - executed_qty)
                if rem_qty > 0:
                    order = client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type="MARKET",
                        quantity=rem_qty
                    )
                    logger.info(f"[Router] Swept remaining unfilled {rem_qty} on {symbol} via market")

            fill_price = float(order.get("avgPrice") or passive_price)
            tp_rounded = self.executor.round_price(symbol, tp2)
            sl_rounded = self.executor.round_price(symbol, sl)

            # Attached Bracket Protection (Take Profit & Stop Loss)
            # On Binance Futures, STOP_MARKET and TAKE_PROFIT_MARKET with closePosition=True do NOT take timeInForce
            try:
                client.futures_create_order(
                    symbol=symbol,
                    side=opp_side,
                    type="TAKE_PROFIT_MARKET",
                    stopPrice=tp_rounded,
                    closePosition=True
                )
            except Exception as e:
                logger.warning(f"[Router] Could not attach exchange TP on {symbol}: {e}")

            try:
                client.futures_create_order(
                    symbol=symbol,
                    side=opp_side,
                    type="STOP_MARKET",
                    stopPrice=sl_rounded,
                    closePosition=True
                )
            except Exception as e:
                logger.warning(f"[Router] Could not attach exchange SL on {symbol}: {e}")

            return order, {
                "entry": fill_price,
                "tp": tp,
                "tp2": tp2,
                "sl": sl,
                "qty": qty
            }

        except Exception as e:
            logger.warning(f"[Router] Post-only failed on {symbol} ({e}), falling back to direct market")
            return self.executor.open_market_position(symbol, direction, usdt_size, tp, tp2, sl)
