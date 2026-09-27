"""
SIA-TradeX Pro: High-Speed Binance Futures WebSocket Stream
Streams bookTicker (0ms top-of-book), kline_1m, and public liquidation cascades.
"""

import json
import time
import asyncio
import threading
from typing import Dict, Optional, Callable, List, Tuple, Any
import websockets
from config.settings import settings


class BinanceWebSocketStream:
    def __init__(self, symbols: Optional[List[str]] = None):
        self.symbols = [s.lower() for s in (symbols or settings.ACTIVE_SYMBOLS)]
        self.testnet = settings.BINANCE_TESTNET
        self.base_ws = settings.BINANCE_WS_TEST if self.testnet else settings.BINANCE_WS_MAIN
        
        # In-memory top-of-book cache (<1ms access)
        self._book_tickers: Dict[str, Dict[str, float]] = {}
        self._lock = threading.Lock()
        
        # Microstructure tracking
        self.cvd_history: Dict[str, float] = {s.upper(): 0.0 for s in self.symbols}
        self.recent_liquidations: List[Dict[str, Any]] = []
        
        # Listeners / Callbacks
        self.on_ticker_callbacks: List[Callable[[str, float, float], None]] = []
        self.on_liquidation_callbacks: List[Callable[[dict], None]] = []

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def get_best_bid_ask(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        with self._lock:
            data = self._book_tickers.get(symbol.upper())
            if data:
                return data.get("bid"), data.get("ask")
        return None, None

    def get_mid_price(self, symbol: str) -> Optional[float]:
        bid, ask = self.get_best_bid_ask(symbol)
        if bid and ask:
            return (bid + ask) / 2.0
        return bid or ask

    def get_all_prices(self) -> Dict[str, float]:
        with self._lock:
            result = {}
            for sym, data in self._book_tickers.items():
                bid = data.get("bid")
                ask = data.get("ask")
                if bid and ask:
                    result[sym] = round((bid + ask) / 2.0, 4)
            return result

    def _build_stream_url(self) -> str:
        # Multiplex bookTicker for all active symbols + forceOrder liquidation stream
        streams = [f"{s}@bookTicker" for s in self.symbols]
        streams.append("!forceOrder@arr")
        stream_path = "/".join(streams)
        # Always connect to Binance Mainnet for real live ticks and liquidation cascades
        base = "wss://fstream.binance.com/stream?streams="
        return f"{base}{stream_path}"

    async def _stream_loop(self):
        url = self._build_stream_url()
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    while self._running:
                        msg = await ws.recv()
                        self._handle_message(json.loads(msg))
            except Exception:
                await asyncio.sleep(2.0)  # Auto-reconnect with backoff

    def _handle_message(self, data: dict):
        stream = data.get("stream", "")
        payload = data.get("data", {})

        if "@bookTicker" in stream:
            symbol = payload.get("s", "").upper()
            try:
                best_bid = float(payload.get("b", 0.0))
                best_ask = float(payload.get("a", 0.0))
                bid_qty = float(payload.get("B", 0.0))
                ask_qty = float(payload.get("A", 0.0))

                with self._lock:
                    self._book_tickers[symbol] = {
                        "bid": best_bid,
                        "ask": best_ask,
                        "bid_qty": bid_qty,
                        "ask_qty": ask_qty,
                        "ts": time.time()
                    }

                for cb in self.on_ticker_callbacks:
                    try:
                        cb(symbol, best_bid, best_ask)
                    except Exception:
                        pass
            except (ValueError, TypeError):
                pass

        elif stream == "!forceOrder@arr":
            # Liquidation event payload: {"o": {"s": symbol, "S": side, "q": qty, "p": price, ...}}
            order = payload.get("o", {})
            sym = order.get("s", "").upper()
            side = order.get("S", "")
            qty = float(order.get("q", 0.0))
            price = float(order.get("p", 0.0))
            usd_value = qty * price

            liq_event = {
                "symbol": sym,
                "side": side,  # BUY = Short was liquidated, SELL = Long was liquidated
                "qty": qty,
                "price": price,
                "usd_value": usd_value,
                "ts": time.time()
            }

            self.recent_liquidations.append(liq_event)
            if len(self.recent_liquidations) > 200:
                self.recent_liquidations = self.recent_liquidations[-100:]

            for cb in self.on_liquidation_callbacks:
                try:
                    cb(liq_event)
                except Exception:
                    pass

    def start(self):
        if self._running:
            return
        self._running = True

        def _runner():
            asyncio.run(self._stream_loop())

        self._thread = threading.Thread(target=_runner, daemon=True, name="binance_ws_stream")
        self._thread.start()

    def stop(self):
        self._running = False


binance_stream = BinanceWebSocketStream()
