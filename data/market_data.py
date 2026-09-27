"""
SIA-TradeX: Market Data Provider
High-precision Binance Futures market data client with warm-up caching and error resilience.
"""

import time
import requests
import threading
from typing import Dict, List, Optional, Any
from config.settings import settings
from core.models import MarketContext, MarketRegime
from strategies.indicators import Indicators
from strategies.regime import MarketRegimeDetector


class MarketData:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "SIA-TradeX/2.0 (Institutional Quant Engine)",
            "Accept": "application/json"
        })
        self._cache_lock = threading.Lock()
        self._cache: Dict[str, Tuple[Any, float]] = {}
        # Always connect to Binance Futures Mainnet for real live market data & prices
        self._base = settings.BINANCE_FAPI_MAIN

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 6.0, cache_ttl: float = 2.0) -> Any:
        key = path + str(sorted((params or {}).items()))
        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and (now - hit[1] < cache_ttl):
                return hit[0]

        try:
            resp = self._session.get(f"{self._base}{path}", params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            with self._cache_lock:
                self._cache[key] = (data, now)
            return data
        except Exception:
            # Fallback to stale cache if API error occurs
            with self._cache_lock:
                hit = self._cache.get(key)
                if hit:
                    return hit[0]
            return None

    def mark_price(self, symbol: str) -> Optional[float]:
        data = self._get("/fapi/v1/premiumIndex", {"symbol": symbol}, cache_ttl=2.0)
        if data and "markPrice" in data:
            try:
                return float(data["markPrice"])
            except (ValueError, TypeError):
                pass

        data2 = self._get("/fapi/v1/ticker/price", {"symbol": symbol}, cache_ttl=2.0)
        if data2 and "price" in data2:
            try:
                return float(data2["price"])
            except (ValueError, TypeError):
                pass
        return None

    def klines(self, symbol: str, interval: str = "1h", limit: int = 150) -> List[Dict[str, float]]:
        """
        Fetches historical klines. Default limit=150 ensures indicator warm-up.
        """
        ttl = 15.0 if interval in ("1h", "4h") else 5.0
        data = self._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit}, cache_ttl=ttl)
        if not data or not isinstance(data, list):
            return []

        candles = []
        for k in data:
            try:
                candles.append({
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "time": int(k[0]),
                })
            except (IndexError, ValueError, TypeError):
                continue
        return candles

    def funding_rate(self, symbol: str) -> Optional[float]:
        data = self._get("/fapi/v1/premiumIndex", {"symbol": symbol}, cache_ttl=10.0)
        if data and "lastFundingRate" in data:
            try:
                return float(data["lastFundingRate"])
            except (ValueError, TypeError):
                pass
        return None

    def order_book_imbalance(self, symbol: str, depth: int = 10) -> Optional[float]:
        data = self._get("/fapi/v1/depth", {"symbol": symbol, "limit": depth}, cache_ttl=3.0)
        if not data:
            return None
        try:
            bids = sum(float(b[1]) for b in data.get("bids", []))
            asks = sum(float(a[1]) for a in data.get("asks", []))
            total = bids + asks
            return ((bids - asks) / total) if total > 0 else 0.0
        except Exception:
            return None

    def get_market_context(self, symbol: str) -> MarketContext:
        candles_1h = self.klines(symbol, "1h", limit=150)
        candles_4h = self.klines(symbol, "4h", limit=80)
        candles_5m = self.klines(symbol, "5m", limit=50)

        price = self.mark_price(symbol) or (candles_1h[-1]["close"] if candles_1h else 0.0)
        closes_1h = [c["close"] for c in candles_1h]
        closes_5m = [c["close"] for c in candles_5m]

        rsi_1h = Indicators.rsi(closes_1h, settings.RSI_PERIOD)
        rsi_5m = Indicators.rsi(closes_5m, settings.RSI_PERIOD)
        atr_val = Indicators.atr(candles_1h, settings.ATR_PERIOD)
        vwap_val = Indicators.vwap(candles_1h[-24:]) if len(candles_1h) >= 24 else None
        breakout_val = Indicators.breakout(candles_1h, settings.BREAKOUT_PERIOD)
        regime_val, _ = MarketRegimeDetector.classify(candles_1h, candles_4h)

        # Momentum: close relative to EMA 20
        mom_1h = None
        if len(closes_1h) >= 20:
            ema20 = Indicators.ema(closes_1h, 20)
            if price > ema20 * 1.001:
                mom_1h = "LONG"
            elif price < ema20 * 0.999:
                mom_1h = "SHORT"

        mom_4h = None
        if candles_4h and len(candles_4h) >= 20:
            closes_4h = [c["close"] for c in candles_4h]
            ema20_4h = Indicators.ema(closes_4h, 20)
            if price > ema20_4h * 1.001:
                mom_4h = "LONG"
            elif price < ema20_4h * 0.999:
                mom_4h = "SHORT"

        # Volume spike confirmation
        vol_confirmed = True
        if len(candles_1h) >= 21:
            vols = [c["volume"] for c in candles_1h]
            avg_vol = sum(vols[-21:-1]) / 20.0
            vol_confirmed = vols[-1] >= (avg_vol * settings.VOLUME_SPIKE_MULT)

        return MarketContext(
            symbol=symbol,
            price=price,
            regime=regime_val,
            momentum_1h=mom_1h,
            momentum_4h=mom_4h,
            rsi_1h=round(rsi_1h, 1) if rsi_1h else None,
            rsi_5m=round(rsi_5m, 1) if rsi_5m else None,
            vwap=round(vwap_val, 4) if vwap_val else None,
            atr=round(atr_val, 4) if atr_val else None,
            breakout=breakout_val,
            funding_rate=self.funding_rate(symbol),
            order_book_imbalance=self.order_book_imbalance(symbol),
            volume_confirmed=vol_confirmed,
        )


market_data = MarketData()
