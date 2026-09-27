"""
SIA-TradeX: Core Signal Aggregation Queue
Manages incoming multi-source signals, deduplication, merging, and prioritization.
"""

import time
import threading
from collections import defaultdict
from typing import List, Dict, Any, Optional
from core.models import Signal


class SignalQueue:
    STALE_SEC: int = 600  # Drop signals older than 10 minutes

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Dict[str, List[Signal]] = defaultdict(list)
        self._manual: List[Signal] = []

    def add(self, sig: Signal):
        with self._lock:
            if sig.manual:
                self._manual.append(sig)
            else:
                self._pending[sig.symbol].append(sig)

    def pop_manual(self) -> List[Signal]:
        with self._lock:
            items = list(self._manual)
            self._manual.clear()
            return items

    def flush_merged(self) -> List[Dict[str, Any]]:
        """
        Groups pending signals by symbol and direction, summing scores and merging reasons.
        """
        results = []
        now = time.time()
        with self._lock:
            for symbol, signals in list(self._pending.items()):
                # Filter out stale signals
                active = [s for s in signals if now - s.ts < self.STALE_SEC]
                self._pending[symbol] = active
                if not active:
                    continue

                for direction in ("LONG", "SHORT"):
                    group = [s for s in active if s.direction == direction]
                    if not group:
                        continue

                    # Sum scores up to maximum sensible cap
                    merged_score = sum(s.score for s in group)
                    reasons = [s.reason for s in group]
                    sources = list({s.source for s in group})
                    raw_events = [s.raw_event for s in group if s.raw_event]

                    results.append({
                        "symbol": symbol,
                        "direction": direction,
                        "score": merged_score,
                        "reasons": reasons,
                        "sources": sources,
                        "raw_events": raw_events,
                    })

                    # Retain any signals for opposite direction if any
                    self._pending[symbol] = [s for s in active if s.direction != direction]

        return results

    def pending_count(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._pending.values()) + len(self._manual)

    def clear(self, symbol: Optional[str] = None):
        with self._lock:
            if not symbol or symbol == "ALL":
                self._pending.clear()
                self._manual.clear()
            else:
                self._pending.pop(symbol, None)
