"""
SIA-TradeX: News Catalyst Feed
Integrates with NewsAPI to extract breaking crypto developments and sentiment catalysts.
"""

import time
import requests
import hashlib
import threading
from typing import List, Tuple, Optional
from datetime import datetime, timezone
from config.settings import settings
from core.models import Signal
from core.queue import SignalQueue


class NewsFeed:
    BULLISH_KEYWORDS = [
        "etf approved", "etf approval", "etf launch", "rate cut", "fed cut",
        "institutional buy", "whale accumulation", "strategic reserve",
        "all-time high", "partnership", "listing", "bullish"
    ]
    BEARISH_KEYWORDS = [
        "hack", "hacked", "exploit", "ban", "banned", "crackdown", "seized",
        "sec sues", "lawsuit", "rate hike", "bankruptcy", "bankrupt", "crash",
        "collapse", "dump", "exchange halted"
    ]

    def __init__(self, queue: SignalQueue):
        self.queue = queue
        self.api_key = settings.NEWS_API_KEY
        self.ok = bool(self.api_key and self.api_key != "YOUR_NEWS_API_KEY_HERE")
        self._fired: dict = {}
        self._recent: list = []
        self._lock = threading.Lock()
        self._running = False

    def get_recent_headlines(self) -> List[dict]:
        with self._lock:
            return list(self._recent)

    def _classify(self, text: str) -> Optional[Tuple[str, int, str]]:
        t = text.lower()
        for kw in self.BEARISH_KEYWORDS:
            if kw in t:
                score = 3 if any(x in t for x in ["hack", "ban", "sec sues", "bankruptcy"]) else 2
                return "SHORT", score, kw
        for kw in self.BULLISH_KEYWORDS:
            if kw in t:
                score = 3 if any(x in t for x in ["etf approved", "rate cut", "strategic reserve"]) else 2
                return "LONG", score, kw
        return None

    def _symbol_from_title(self, title: str) -> str:
        t = title.lower()
        for kws, sym in [
            (["solana", "sol"], "SOLUSDT"),
            (["ethereum", "eth"], "ETHUSDT"),
            (["bitcoin", "btc"], "BTCUSDT"),
            (["doge", "dogecoin"], "DOGEUSDT"),
            (["chainlink", "link"], "LINKUSDT"),
            (["avalanche", "avax"], "AVAXUSDT"),
            (["cardano", "ada"], "ADAUSDT"),
        ]:
            if any(k in t for k in kws):
                return sym
        return "BTCUSDT"

    def _fetch_and_process(self):
        if not self.ok:
            return
        query = "bitcoin OR ethereum OR crypto OR solana OR SEC crypto OR ETF"
        try:
            r = requests.get(
                f"{settings.NEWS_API_BASE}/everything",
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 20,
                    "apiKey": self.api_key
                },
                timeout=10
            )
            r.raise_for_status()
            articles = r.json().get("articles", [])
            now = time.time()
            cutoff = now - (settings.NEWS_LOOKBACK_MIN * 60)

            fresh = []
            for a in articles:
                pub = a.get("publishedAt", "")
                try:
                    dt = datetime.strptime(pub[:19], "%Y-%m-%dT%H:%M:%S")
                    if dt.replace(tzinfo=timezone.utc).timestamp() >= cutoff:
                        fresh.append(a)
                except Exception:
                    pass

            with self._lock:
                self._recent = fresh[:20]

            for a in fresh:
                title = a.get("title") or ""
                desc = a.get("description") or ""
                classification = self._classify(f"{title} {desc}")
                if not classification:
                    continue

                direction, score, kw = classification
                symbol = self._symbol_from_title(title)
                h_key = hashlib.md5(title.encode()).hexdigest()
                if self._fired.get(h_key, 0) > now:
                    continue

                self.queue.add(Signal(
                    symbol=symbol,
                    direction=direction,
                    source="newsapi",
                    reason=f"News [{kw}]: {title[:65]}",
                    score=score,
                    confidence=70,
                    raw_event={"title": title, "keyword": kw}
                ))
                self._fired[h_key] = now + settings.NEWS_SIGNAL_COOLDOWN

        except Exception:
            pass

    def run_loop(self):
        self._running = True
        while self._running:
            self._fetch_and_process()
            time.sleep(settings.NEWS_SCAN_INTERVAL)

    def stop(self):
        self._running = False
