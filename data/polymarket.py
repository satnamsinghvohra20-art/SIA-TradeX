"""
SIA-TradeX: Polymarket Prediction Sentiment Feed
Monitors rapid probability spikes and prediction sentiment on crypto events via Gamma API.
"""

import time
import requests
import threading
from typing import Dict, List, Optional
from collections import defaultdict, deque
from config.settings import settings
from core.models import Signal
from core.queue import SignalQueue


class PolymarketFeed:
    SYMBOL_MAP = {
        "bitcoin": "BTCUSDT", "btc": "BTCUSDT",
        "ethereum": "ETHUSDT", "eth": "ETHUSDT",
        "solana": "SOLUSDT", "sol": "SOLUSDT",
        "doge": "DOGEUSDT", "dogecoin": "DOGEUSDT",
        "cardano": "ADAUSDT", "ada": "ADAUSDT",
        "avalanche": "AVAXUSDT", "avax": "AVAXUSDT",
        "chainlink": "LINKUSDT", "link": "LINKUSDT"
    }

    def __init__(self, queue: SignalQueue):
        self.queue = queue
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        self._price_history = defaultdict(lambda: deque(maxlen=120))
        self._known_markets: Dict[str, dict] = {}
        self._fired: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._markets: List[dict] = []
        self._running = False

    def _fetch_markets(self) -> List[dict]:
        try:
            r = self._session.get(
                f"{settings.GAMMA_API}/markets",
                params={"limit": settings.POLY_FETCH_LIMIT, "active": "true", "closed": "false"},
                timeout=12
            )
            r.raise_for_status()
            raw = r.json()
            markets = raw if isinstance(raw, list) else (raw.get("data") or raw.get("markets") or [])
            crypto_kw = {"bitcoin", "btc", "ethereum", "eth", "solana", "crypto", "fed", "rate", "etf", "sec"}
            return [m for m in markets if any(k in str(m.get("question", "")).lower() for k in crypto_kw)]
        except Exception:
            return []

    def _extract_symbol(self, question: str) -> Optional[str]:
        q = question.lower()
        for kw, sym in self.SYMBOL_MAP.items():
            if kw in q:
                return sym
        return None

    def _detect_spikes(self):
        now = time.time()
        with self._lock:
            for cid, history in self._price_history.items():
                if len(history) < 2:
                    continue
                window = [(t, p) for t, p in history if now - t <= settings.POLY_SPIKE_WINDOW_SEC]
                if len(window) < 2:
                    continue
                delta = window[-1][1] - window[0][1]
                abs_delta = abs(delta)

                if abs_delta >= settings.POLY_SPIKE_THRESHOLD:
                    m = self._known_markets.get(cid)
                    if not m:
                        continue
                    symbol = self._extract_symbol(m.get("question", ""))
                    if not symbol:
                        continue

                    direction = "LONG" if delta > 0 else "SHORT"
                    fire_key = f"{cid}_{direction}"
                    if self._fired.get(fire_key, 0) > now:
                        continue

                    self.queue.add(Signal(
                        symbol=symbol,
                        direction=direction,
                        source="polymarket",
                        reason=f"Polymarket {delta:+.1%} spike: {str(m.get('question',''))[:45]}",
                        score=3 if abs_delta > 0.08 else 2,
                        confidence=70,
                        raw_event={"question": m.get("question"), "delta": delta}
                    ))
                    self._fired[fire_key] = now + 300  # 5m cooldown

    def get_sentiment(self, symbol: str) -> Optional[str]:
        """Returns consensus sentiment (LONG or SHORT) from related prediction markets."""
        now = time.time()
        longs, shorts = 0, 0
        with self._lock:
            for cid, history in self._price_history.items():
                m = self._known_markets.get(cid)
                if not m:
                    continue
                if self._extract_symbol(m.get("question", "")) != symbol:
                    continue
                window = [(t, p) for t, p in history if now - t <= settings.POLY_SPIKE_WINDOW_SEC * 2]
                if len(window) >= 2:
                    diff = window[-1][1] - window[0][1]
                    if diff > 0.015:
                        longs += 1
                    elif diff < -0.015:
                        shorts += 1
        if longs > shorts:
            return "LONG"
        if shorts > longs:
            return "SHORT"
        return None

    def run_loop(self):
        self._running = True
        last_fetch = 0.0
        while self._running:
            try:
                now = time.time()
                if now - last_fetch > 120.0:
                    fresh = self._fetch_markets()
                    if fresh:
                        self._markets = fresh
                    last_fetch = now

                # Update prices
                for m in self._markets:
                    cid = m.get("conditionId") or m.get("id", "")
                    prices = m.get("outcomePrices", [])
                    if cid and prices:
                        try:
                            with self._lock:
                                self._known_markets[cid] = m
                                self._price_history[cid].append((now, float(prices[0])))
                        except Exception:
                            pass

                self._detect_spikes()
            except Exception:
                pass
            time.sleep(settings.POLY_SCAN_INTERVAL)

    def stop(self):
        self._running = False
