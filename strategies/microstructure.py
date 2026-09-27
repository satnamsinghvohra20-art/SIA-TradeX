"""
SIA-TradeX Pro: Leading Microstructural Alpha Engine
Harnesses Cumulative Volume Delta (CVD), Liquidation Cascade Sniping, and Order Flow Imbalance.
"""

import time
from typing import Dict, List, Optional, Tuple, Any
from data.binance_stream import binance_stream
from core.models import Signal


class MicrostructureAlpha:
    def __init__(self):
        self.stream = binance_stream
        self.liq_threshold_usd = 250_000.0  # $250k cascade threshold
        self.liq_window_sec = 6.0
        self._last_snipe: Dict[str, float] = {}

    def check_liquidation_cascade(self, symbol: str) -> Optional[Signal]:
        """
        Detects liquidation stop-run cascades to snipe mean-reversion counter-trend entries.
        - Cluster of LONG liquidations (forced sell orders) = oversold flush -> Long snipe.
        - Cluster of SHORT liquidations (forced buy orders) = overbought squeeze -> Short snipe.
        """
        now = time.time()
        if now - self._last_snipe.get(symbol, 0.0) < 180.0:  # 3 min cooldown per symbol
            return None

        # Filter recent liquidations for this symbol within window
        recent = [
            l for l in self.stream.recent_liquidations
            if l["symbol"] == symbol and (now - l["ts"] <= self.liq_window_sec)
        ]

        if not recent:
            return None

        long_liq_usd = sum(l["usd_value"] for l in recent if l["side"] == "SELL")
        short_liq_usd = sum(l["usd_value"] for l in recent if l["side"] == "BUY")

        if long_liq_usd >= self.liq_threshold_usd:
            self._last_snipe[symbol] = now
            return Signal(
                symbol=symbol,
                direction="LONG",
                source="liq_sniper",
                reason=f"Liquidation Cascade Snipe: ${long_liq_usd:,.0f} Longs flushed",
                score=4,
                confidence=85,
                raw_event={"type": "liquidation_cascade", "long_liq_usd": long_liq_usd}
            )

        if short_liq_usd >= self.liq_threshold_usd:
            self._last_snipe[symbol] = now
            return Signal(
                symbol=symbol,
                direction="SHORT",
                source="liq_sniper",
                reason=f"Liquidation Cascade Snipe: ${short_liq_usd:,.0f} Shorts squeezed",
                score=4,
                confidence=85,
                raw_event={"type": "liquidation_cascade", "short_liq_usd": short_liq_usd}
            )

        return None

    def get_order_flow_imbalance(self, symbol: str) -> float:
        """
        Calculates instantaneous top-of-book depth ratio.
        Positive (>0) = Bids outweigh Asks (buy support).
        Negative (<0) = Asks outweigh Bids (sell resistance).
        """
        with self.stream._lock:
            data = self.stream._book_tickers.get(symbol.upper())
            if not data:
                return 0.0
            bid_qty = data.get("bid_qty", 0.0)
            ask_qty = data.get("ask_qty", 0.0)
            total = bid_qty + ask_qty
            return ((bid_qty - ask_qty) / total) if total > 0 else 0.0


microstructure_alpha = MicrostructureAlpha()
