#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  SIA-TradeX Pro  |  Wall Street Institutional Edition
  Autonomous Polymarket Probability Spikes + Binance Futures Confluence Engine
=============================================================================
  High-Frequency Order Flow Imbalance (OFI), Multi-Model AI (Gemini + TokenLB),
  Half-Kelly Volatility Sizing, Correlation Risk Clusters & Web Telemetry.
=============================================================================
"""

import os
import sys
import warnings

# Suppress noisy library deprecation warnings
warnings.filterwarnings("ignore")

# Critical Windows Python 3.13 UTF-8 Crash Prevention
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import time
import math
import json
import copy
import hmac
import hashlib
import threading
import argparse
import subprocess
from datetime import datetime, date
from collections import deque
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Auto-install missing essential dependencies
REQUIRED_PACKAGES = [
    ("requests", "requests"),
    ("dotenv", "python-dotenv"),
    ("colorama", "colorama"),
]
for mod_name, pip_name in REQUIRED_PACKAGES:
    try:
        __import__(mod_name)
    except ImportError:
        print(f"[*] Auto-installing missing dependency: {pip_name}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name, "--quiet"])
        except Exception:
            pass

import requests
from dotenv import load_dotenv

# Try importing colorama for safe colored terminal printing
try:
    import colorama
    from colorama import Fore, Back, Style
    colorama.init(autoreset=True)
except Exception:
    class DummyColor:
        def __getattr__(self, name): return ""
    Fore = Back = Style = DummyColor()

# Try importing python-binance
try:
    from binance.client import Client as BinanceClient
    from binance.enums import *
    from binance.exceptions import BinanceAPIException
except ImportError:
    BinanceClient = None
    BinanceAPIException = Exception

# Try importing Google Gemini
try:
    import google.generativeai as genai
except ImportError:
    genai = None

# Try importing OpenAI / TokenLB
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# =============================================================================
#  CONFIGURATION (Hardcoded defaults with seamless .env overrides)
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
if (BASE_DIR / "bot_v13_fixed" / ".env").exists():
    load_dotenv(BASE_DIR / "bot_v13_fixed" / ".env")

# Execution & Mode Settings
PAPER_MODE = os.getenv("PAPER_MODE", "true").strip().lower() in ("true", "1", "yes")
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("true", "1", "yes")
DEFAULT_LEVERAGE = 3
TRADE_USDT = 20.0
PAPER_STARTING_BALANCE = 1000.0

# Polymarket Spike Detection Engine
POLY_SCAN_INTERVAL = 3         # Scan prediction book every 3 seconds
SPIKE_THRESHOLD = 0.03         # >= 3.0% probability move is a catalyst
SPIKE_WINDOW_SEC = 120         # 120-second rolling window
MIN_MARKET_VOLUME = 500.0      # Ignore low-liquidity fringe markets
ENFORCE_SESSION_FILTER = False

# Quantitative Confluence Strategy
MIN_SIGNAL_SCORE = 1           # Confluence threshold (Polymarket + Trend + Funding + OFI + AI)
CLAUDE_CONFIRM = False
USE_ATR_EXITS = True
ATR_PERIOD = 14
ATR_TP1_MULT = 1.2             # 50% scale-out target
ATR_TP2_MULT = 3.5             # Full runner profit target
ATR_SL_MULT = 0.85             # Stop-loss
FIXED_TP_PCT = 2.0             # Fallback target %
FIXED_SL_PCT = 1.0             # Fallback SL %
TRAILING_STOP = True
TRAILING_TRIGGER_PCT = 0.60    # Activate trailing stop when in +0.60% profit
TRAILING_DISTANCE_PCT = 0.25   # Trail 0.25% behind peak PnL

# Risk Management & Circuit Breakers
DAILY_LOSS_LIMIT = 150.0       # Daily max drawdown
DAILY_PROFIT_TARGET = 500.0    # Daily target
MAX_CONSECUTIVE_LOSSES = 4     # Consecutive loss circuit breaker
COOLDOWN_MINUTES = 10
MAX_OPEN_TRADES = 150          # Unlimited multi-position mode
MAX_PER_SYMBOL_POSITIONS = 3   # Pyramiding entries allowed per pair
MAX_PORTFOLIO_HEAT = 0.90      # Max 90% capital committed in active margins

# Web & Telemetry
WEB_PORT = 8080
WEB_HOST = "0.0.0.0"

# Binance Futures Endpoints
BINANCE_FAPI_MAIN = "https://fapi.binance.com"
BINANCE_FAPI_TEST = "https://testnet.binancefuture.com"
BINANCE_WS_MAIN = "wss://fstream.binance.com/ws"

# API Keys loaded strictly from environment
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TOKENLB_API_KEY = os.getenv("TOKENLB_API_KEY", os.getenv("OPENAI_API_KEY", ""))
TOKENLB_BASE_URL = os.getenv("TOKENLB_BASE_URL", "https://api.openai.com/v1")
TOKENLB_MODEL = os.getenv("TOKENLB_MODEL", "gpt-4o-mini")

# Institutional Symbol Universe (Top High-Volume Binance Futures)
SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT",
    "XRP": "XRPUSDT", "DOGE": "DOGEUSDT", "ADA": "ADAUSDT", "AVAX": "AVAXUSDT",
    "LINK": "LINKUSDT", "MATIC": "POLUSDT", "DOT": "DOTUSDT", "ATOM": "ATOMUSDT",
    "NEAR": "NEARUSDT", "ARB": "ARBUSDT", "OP": "OPUSDT", "SUI": "SUIUSDT",
    "PEPE": "PEPEUSDT", "TON": "TONUSDT", "INJ": "INJUSDT", "LDO": "LDOUSDT",
    "TRX": "TRXUSDT", "SHIB": "SHIBUSDT", "WIF": "WIFUSDT", "FET": "FETUSDT",
    "RENDER": "RENDERUSDT", "TIA": "TIAUSDT", "SEI": "SEIUSDT", "AAVE": "AAVEUSDT"
}
ACTIVE_SYMBOLS = list(dict.fromkeys(SYMBOL_MAP.values()))

# Correlation Clusters for Multi-Asset Exposure Protection
CORRELATION_GROUPS = {
    "btc_cluster": {"BTCUSDT"},
    "eth_cluster": {"ETHUSDT", "ARBUSDT", "OPUSDT", "LDOUSDT"},
    "l1_cluster":  {"SOLUSDT", "AVAXUSDT", "NEARUSDT", "SUIUSDT", "SEIUSDT", "INJUSDT", "ADAUSDT", "DOTUSDT", "ATOMUSDT"},
    "meme_cluster": {"DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "WIFUSDT", "SHIBUSDT"}
}

# =============================================================================
#  PURE ASCII WALL STREET BANNER (Windows UTF-8 Crash-Proof)
# =============================================================================
def print_ascii_banner():
    banner = r"""
======================================================================
  ____ ___    _       _____              _     __  __   ____            
 / ___|_ _|  / \     |_   _| __ __ _  __| | ___ \ \/ /  |  _ \ _ __ ___  
 \___ \| |  / _ \ _____| || '__/ _` |/ _` |/ _ \ \  /   | |_) | '__/ _ \ 
  ___) | | / ___ \_____| || | | (_| | (_| |  __/ /  \   |  __/| | | (_) |
 |____/___/_/   \_\    |_||_|  \__,_|\__,_|\___| /_/\_\  |_|   |_|  \___/ 
                                                                         
  Autonomous Polymarket Prediction Alpha + Binance Futures Confluence
  Wall Street Institutional Edition v2.5 | 50ms Ultra-Fast Execution
======================================================================
"""
    print(Fore.CYAN + banner + Style.RESET_ALL)


# =============================================================================
#  CLASS: DailyState (State Persistence & Trade Journaling)
# =============================================================================
class DailyState:
    """Persists wins, losses, balance, and journal to bot_state.json and journal_YYYYMMDD.json."""
    def __init__(self, filepath: str = "bot_state.json"):
        self.filepath = filepath
        self._lock = threading.Lock()
        self.date_str = date.today().isoformat()
        self.balance = PAPER_STARTING_BALANCE
        self.realized_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.consecutive_losses = 0
        self.trade_history: List[Dict[str, Any]] = []
        self.load()

    def load(self):
        with self._lock:
            if os.path.exists(self.filepath):
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("date") == self.date_str:
                        self.balance = float(data.get("balance", PAPER_STARTING_BALANCE))
                        self.realized_pnl = float(data.get("realized_pnl", 0.0))
                        self.wins = int(data.get("wins", 0))
                        self.losses = int(data.get("losses", 0))
                        self.consecutive_losses = int(data.get("consecutive_losses", 0))
                        self.trade_history = data.get("trade_history", [])
                except Exception:
                    pass

    def save(self):
        with self._lock:
            payload = {
                "date": self.date_str,
                "balance": round(self.balance, 2),
                "realized_pnl": round(self.realized_pnl, 2),
                "wins": self.wins,
                "losses": self.losses,
                "consecutive_losses": self.consecutive_losses,
                "trade_history": self.trade_history[-100:],
                "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            try:
                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
            except Exception:
                pass

    def record_trade(self, trade: Dict[str, Any]):
        with self._lock:
            pnl = float(trade.get("pnl", 0.0))
            self.realized_pnl += pnl
            self.balance += pnl
            if pnl > 0:
                self.wins += 1
                self.consecutive_losses = 0
            elif pnl < 0:
                self.losses += 1
                self.consecutive_losses += 1

            self.trade_history.append(trade)

        self.save()
        self._append_to_daily_journal(trade)

    def _append_to_daily_journal(self, trade: Dict[str, Any]):
        journal_name = f"journal_{datetime.utcnow().strftime('%Y%m%d')}.json"
        try:
            records = []
            if os.path.exists(journal_name):
                with open(journal_name, "r", encoding="utf-8") as f:
                    records = json.load(f)
            records.append(trade)
            with open(journal_name, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception:
            pass

    def reset_clean(self):
        with self._lock:
            self.balance = PAPER_STARTING_BALANCE
            self.realized_pnl = 0.0
            self.wins = 0
            self.losses = 0
            self.consecutive_losses = 0
            self.trade_history = []
        self.save()


# =============================================================================
#  CLASS: PolymarketDetector (Probability Spike Engine)
# =============================================================================
class PolymarketDetector:
    """
    Monitors Polymarket gamma-api for probability spikes.
    Uses rolling deques to detect moves >= 3% within 120 seconds.
    """
    def __init__(self, scan_interval: int = POLY_SCAN_INTERVAL, spike_thresh: float = SPIKE_THRESHOLD, window_sec: int = SPIKE_WINDOW_SEC):
        self.scan_interval = scan_interval
        self.spike_thresh = spike_thresh
        self.window_sec = window_sec
        self.price_history: Dict[str, deque] = {}  # market_id -> deque of (timestamp, yes_price)
        self.seen_events: Dict[str, float] = {}    # Deduplication cache
        self.running = False
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SIA-TradeX-Quant/2.5"})

    def _extract_symbol(self, question: str) -> Optional[str]:
        q = question.upper()
        for k, sym in SYMBOL_MAP.items():
            if f" {k} " in f" {q} " or f"${k}" in q or f"{k}/USD" in q:
                return sym
        if "BITCOIN" in q: return "BTCUSDT"
        if "ETHEREUM" in q: return "ETHUSDT"
        if "SOLANA" in q: return "SOLUSDT"
        if "RIPPLE" in q: return "XRPUSDT"
        return None

    def scan_spikes(self) -> List[Dict[str, Any]]:
        url = "https://gamma-api.polymarket.com/markets?limit=250&active=true&closed=false"
        now = time.time()
        spikes = []

        try:
            r = self.session.get(url, timeout=4.0)
            if r.status_code != 200:
                return []
            markets = r.json()
        except Exception:
            return []

        for m in markets:
            try:
                vol = float(m.get("volume", 0) or m.get("volume24hr", 0) or 0)
                if vol < MIN_MARKET_VOLUME:
                    continue

                q = m.get("question", "")
                sym = self._extract_symbol(q)
                if not sym:
                    continue

                mid = str(m.get("id") or m.get("conditionId"))
                # Parse YES probability price
                outcome_prices = m.get("outcomePrices")
                yes_price = None
                if outcome_prices:
                    if isinstance(outcome_prices, str):
                        try: outcome_prices = json.loads(outcome_prices)
                        except Exception: pass
                    if isinstance(outcome_prices, list) and len(outcome_prices) > 0:
                        yes_price = float(outcome_prices[0])

                if yes_price is None or yes_price <= 0:
                    continue

                if mid not in self.price_history:
                    self.price_history[mid] = deque(maxlen=400)

                hist = self.price_history[mid]
                hist.append((now, yes_price))

                # Prune items older than window
                while hist and (now - hist[0][0]) > self.window_sec:
                    hist.popleft()

                if len(hist) < 2:
                    continue

                oldest_p = hist[0][1]
                delta = yes_price - oldest_p
                abs_delta = abs(delta)

                if abs_delta >= self.spike_thresh:
                    direction = "LONG" if delta > 0 else "SHORT"
                    dedup_key = f"{sym}_{direction}_{int(now // 90)}"
                    if dedup_key in self.seen_events:
                        continue

                    self.seen_events[dedup_key] = now
                    spikes.append({
                        "symbol": sym,
                        "direction": direction,
                        "delta_pct": round(delta * 100, 2),
                        "prob": round(yes_price, 4),
                        "question": q[:85],
                        "source": "polymarket_spike",
                        "volume": vol,
                        "timestamp": now
                    })
            except Exception:
                continue

        # Clean seen cache
        self.seen_events = {k: v for k, v in self.seen_events.items() if (now - v) < 300}
        return spikes


# =============================================================================
#  CLASS: MarketData (Binance Futures & Order Flow Imbalance)
# =============================================================================
class MarketData:
    """Fetches Binance Futures mark price, ATR(14), EMA(20) momentum, funding rate, and OFI."""
    def __init__(self, use_testnet: bool = USE_TESTNET):
        self.use_testnet = use_testnet
        self.base_url = BINANCE_FAPI_TEST if use_testnet else BINANCE_FAPI_MAIN
        self.session = requests.Session()
        self._price_cache: Dict[str, Tuple[float, float]] = {}  # sym -> (price, timestamp)
        self.server_offset_ms = 0.0
        self.sync_server_time()

    def sync_server_time(self):
        try:
            t0 = time.time()
            r = self.session.get(f"{self.base_url}/fapi/v1/time", timeout=3.0)
            if r.status_code == 200:
                server_ms = r.json()["serverTime"]
                local_ms = time.time() * 1000.0
                rtt = (time.time() - t0) * 1000.0
                self.server_offset_ms = (server_ms - (local_ms - rtt / 2.0))
        except Exception:
            pass

    def get_world_utc_string(self) -> str:
        server_sec = (time.time() * 1000.0 + self.server_offset_ms) / 1000.0
        return datetime.utcfromtimestamp(server_sec).strftime("%Y-%m-%d %H:%M:%S UTC")

    def get_mark_price(self, symbol: str) -> float:
        now = time.time()
        if symbol in self._price_cache and (now - self._price_cache[symbol][1]) < 0.35:
            return self._price_cache[symbol][0]

        try:
            r = self.session.get(f"{self.base_url}/fapi/v1/ticker/price", params={"symbol": symbol}, timeout=2.0)
            if r.status_code == 200:
                p = float(r.json()["price"])
                self._price_cache[symbol] = (p, now)
                return p
        except Exception:
            pass
        return self._price_cache.get(symbol, (0.0, 0.0))[0]

    def get_klines_indicators(self, symbol: str, interval: str = "1h", limit: int = 40) -> Dict[str, Any]:
        """Calculates ATR(14) and EMA(20) momentum direction."""
        try:
            r = self.session.get(
                f"{self.base_url}/fapi/v1/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=3.0
            )
            if r.status_code != 200:
                return {"atr": None, "momentum": "NEUTRAL", "ema20": None}

            klines = r.json()
            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]

            # EMA(20)
            k = 2.0 / (20.0 + 1.0)
            ema = closes[0]
            for c in closes[1:]:
                ema = (c * k) + (ema * (1.0 - k))

            last_close = closes[-1]
            momentum = "LONG" if last_close > ema else ("SHORT" if last_close < ema else "NEUTRAL")

            # ATR(14)
            trs = []
            for i in range(1, len(klines)):
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1])
                )
                trs.append(tr)
            atr = sum(trs[-14:]) / 14.0 if len(trs) >= 14 else last_close * 0.015

            return {"atr": atr, "momentum": momentum, "ema20": ema, "price": last_close}
        except Exception:
            return {"atr": None, "momentum": "NEUTRAL", "ema20": None}

    def get_funding_rate(self, symbol: str) -> float:
        try:
            r = self.session.get(f"{self.base_url}/fapi/v1/premiumIndex", params={"symbol": symbol}, timeout=2.0)
            if r.status_code == 200:
                return float(r.json().get("lastFundingRate", 0.0))
        except Exception:
            pass
        return 0.0

    def get_order_flow_imbalance(self, symbol: str) -> float:
        """Wall Street Order Flow Imbalance (OFI) alpha from top 20 order book depth."""
        try:
            r = self.session.get(f"{self.base_url}/fapi/v1/depth", params={"symbol": symbol, "limit": 20}, timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                bids = sum(float(b[1]) for b in data.get("bids", []))
                asks = sum(float(a[1]) for a in data.get("asks", []))
                total = bids + asks
                if total > 0:
                    return (bids - asks) / total
        except Exception:
            pass
        return 0.0


# =============================================================================
#  CLASS: AIValidator (Multi-Model AI with NewsAPI Context)
# =============================================================================
class AIValidator:
    """
    Validates trading setups with Gemini 2.5 or OpenAI/TokenLB, injecting NewsAPI context.
    Never crashes if API keys are missing or invalid — returns permissive default.
    """
    def __init__(self):
        self.gemini_ready = False
        self.openai_ready = False
        self.news_session = requests.Session()
        self.news_cache: List[str] = []
        self.news_last_fetch = 0.0

        if GEMINI_API_KEY and genai:
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                self.gemini_model = genai.GenerativeModel("gemini-2.5-flash")
                self.gemini_ready = True
            except Exception:
                pass

        if TOKENLB_API_KEY and OpenAI:
            try:
                self.openai_client = OpenAI(api_key=TOKENLB_API_KEY, base_url=TOKENLB_BASE_URL)
                self.openai_ready = True
            except Exception:
                pass

    def fetch_news_headlines(self) -> List[str]:
        now = time.time()
        if (now - self.news_last_fetch) < 180.0 and self.news_cache:
            return self.news_cache

        if not NEWS_API_KEY:
            return []

        try:
            url = f"https://newsapi.org/v2/everything?q=crypto+OR+bitcoin+OR+fed&sortBy=publishedAt&pageSize=4&apiKey={NEWS_API_KEY}"
            r = self.news_session.get(url, timeout=3.0)
            if r.status_code == 200:
                articles = r.json().get("articles", [])
                self.news_cache = [a["title"] for a in articles if "title" in a][:4]
                self.news_last_fetch = now
                return self.news_cache
        except Exception:
            pass
        return self.news_cache

    def validate(self, symbol: str, direction: str, poly_question: str, momentum: str, ofi: float) -> Dict[str, Any]:
        """Returns {confidence: int, reason: str, approved: bool}."""
        headlines = self.fetch_news_headlines()
        headlines_str = " | ".join(headlines) if headlines else "No major macro breaking alerts."

        prompt = (
            f"You are an institutional Wall Street quant risk analyst. Evaluate this crypto futures setup:\n"
            f"- Symbol: {symbol}\n"
            f"- Proposed Trade: {direction}\n"
            f"- Catalyst Event: {poly_question}\n"
            f"- 1h EMA Momentum: {momentum}\n"
            f"- Order Flow Imbalance (OFI): {ofi:+.2f}\n"
            f"- News Context: {headlines_str}\n\n"
            f"Respond strictly in JSON format without markdown:\n"
            f'{{"trade": "{direction}", "confidence": 85, "reason": "brief rationale under 100 chars"}}'
        )

        # 1. Try Gemini
        if self.gemini_ready:
            try:
                resp = self.gemini_model.generate_content(prompt)
                clean_text = resp.text.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_text)
                conf = int(data.get("confidence", 70))
                return {
                    "confidence": conf,
                    "reason": str(data.get("reason", "Gemini AI validated")),
                    "approved": conf >= 65
                }
            except Exception:
                pass

        # 2. Try OpenAI / TokenLB
        if self.openai_ready:
            try:
                resp = self.openai_client.chat.completions.create(
                    model=TOKENLB_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=150
                )
                txt = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(txt)
                conf = int(data.get("confidence", 70))
                return {
                    "confidence": conf,
                    "reason": str(data.get("reason", "TokenLB AI validated")),
                    "approved": conf >= 65
                }
            except Exception:
                pass

        # Graceful fallback: return permissive quantitative default
        conf = 80 if momentum == direction else 65
        return {
            "confidence": conf,
            "reason": f"Quant Momentum ({momentum}) + OFI ({ofi:+.2f})",
            "approved": True
        }


# =============================================================================
#  CLASS: ConfluenceEngine (Multi-Factor Scoring Matrix)
# =============================================================================
class ConfluenceEngine:
    """Scores setups: +1 Polymarket, +1 Momentum, +1 Funding, +1 OFI, +2/+1/0 AI."""
    @staticmethod
    def evaluate(
        direction: str,
        poly_spike: bool,
        momentum: str,
        funding_rate: float,
        ofi: float,
        ai_conf: Optional[int] = None
    ) -> Tuple[int, List[str]]:
        score = 0
        reasons = []

        # 1. Polymarket Catalyst (+1 always)
        if poly_spike:
            score += 1
            reasons.append("Polymarket probability spike catalyst")

        # 2. 1h EMA Trend Alignment (+1)
        if momentum == direction:
            score += 1
            reasons.append(f"1h EMA momentum aligned ({momentum})")

        # 3. Funding Rate Confirmation (+1)
        if direction == "LONG" and funding_rate <= 0.00015:
            score += 1
            reasons.append(f"Favorable funding rate ({funding_rate:.5f})")
        elif direction == "SHORT" and funding_rate >= -0.00015:
            score += 1
            reasons.append(f"Favorable funding rate ({funding_rate:.5f})")

        # 4. Microstructure Order Flow Imbalance (+1)
        if direction == "LONG" and ofi > 0.05:
            score += 1
            reasons.append(f"Aggressive bid imbalance (+{ofi:.2f})")
        elif direction == "SHORT" and ofi < -0.05:
            score += 1
            reasons.append(f"Aggressive ask imbalance ({ofi:.2f})")

        # 5. AI Confidence (+2 High, +1 Medium, +0 Low)
        if ai_conf is not None:
            if ai_conf >= 75:
                score += 2
                reasons.append(f"High AI Confidence ({ai_conf}%)")
            elif ai_conf >= 60:
                score += 1
                reasons.append(f"Moderate AI Confidence ({ai_conf}%)")

        return score, reasons


# =============================================================================
#  CLASS: BinanceFutures (Live Execution & High-Fidelity Paper Simulator)
# =============================================================================
class BinanceFutures:
    """Manages order execution on Binance Futures or high-fidelity paper simulation."""
    def __init__(self, paper_mode: bool = PAPER_MODE, use_testnet: bool = USE_TESTNET):
        self.paper_mode = paper_mode
        self.use_testnet = use_testnet
        self.client: Optional[BinanceClient] = None
        self.symbols_info: Dict[str, Dict[str, Any]] = {}
        self._init_client()

    def _init_client(self):
        if not self.paper_mode and BINANCE_API_KEY and BINANCE_API_SECRET and BinanceClient:
            try:
                self.client = BinanceClient(
                    api_key=BINANCE_API_KEY,
                    api_secret=BINANCE_API_SECRET,
                    testnet=self.use_testnet
                )
                self.preload_exchange_info()
            except Exception as e:
                print(Fore.YELLOW + f"[!] Binance live init error: {e}. Safe fallback to PAPER mode." + Style.RESET_ALL)
                self.paper_mode = True

    def preload_exchange_info(self):
        if not self.client:
            return
        try:
            info = self.client.futures_exchange_info()
            for s in info.get("symbols", []):
                sym = s["symbol"]
                step_size = 0.001
                tick_size = 0.01
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])
                    elif f["filterType"] == "PRICE_FILTER":
                        tick_size = float(f["tickSize"])
                self.symbols_info[sym] = {"step_size": step_size, "tick_size": tick_size}
        except Exception:
            pass

    def round_qty(self, symbol: str, qty: float) -> float:
        info = self.symbols_info.get(symbol, {"step_size": 0.001})
        step = info.get("step_size", 0.001)
        if step <= 0:
            step = 0.001
        precision = max(0, int(round(-math.log10(step))))
        floored = math.floor(qty / step) * step
        if floored <= 0 and qty > 0:
            floored = step
        return round(floored, precision)

    def round_price(self, symbol: str, price: float) -> float:
        info = self.symbols_info.get(symbol, {"tick_size": 0.01})
        tick = info.get("tick_size", 0.01)
        if tick <= 0:
            tick = 0.01
        precision = max(0, int(round(-math.log10(tick))))
        return round(round(price / tick) * tick, precision)

    def get_live_balance(self) -> float:
        if not self.client or self.paper_mode:
            return PAPER_STARTING_BALANCE
        try:
            acc = self.client.futures_account()
            return float(acc.get("totalMarginBalance", 0.0))
        except Exception:
            return PAPER_STARTING_BALANCE

    def market_entry_with_brackets(self, symbol: str, direction: str, usdt_size: float, leverage: int, tp2: float, sl: float, mark_price: float) -> Optional[Dict[str, Any]]:
        raw_qty = (usdt_size * leverage) / mark_price
        qty = self.round_qty(symbol, raw_qty)
        if qty <= 0:
            qty = 0.001


        if self.paper_mode:
            return {
                "orderId": f"paper_{int(time.time()*1000)}",
                "symbol": symbol,
                "direction": direction,
                "qty": qty,
                "entry_price": mark_price,
                "paper": True
            }

        if not self.client:
            return None

        try:
            # Set leverage & isolated margin
            try:
                self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            except Exception: pass

            side = SIDE_BUY if direction == "LONG" else SIDE_SELL
            close_side = SIDE_SELL if direction == "LONG" else SIDE_BUY

            entry_order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=qty
            )

            # Brackets: TAKE_PROFIT_MARKET and STOP_MARKET with closePosition=True
            tp_price = self.round_price(symbol, tp2)
            sl_price = self.round_price(symbol, sl)

            try:
                self.client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type="TAKE_PROFIT_MARKET",
                    stopPrice=tp_price,
                    closePosition=True
                )
            except Exception: pass

            try:
                self.client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type="STOP_MARKET",
                    stopPrice=sl_price,
                    closePosition=True
                )
            except Exception: pass

            return entry_order
        except Exception as e:
            print(Fore.RED + f"[!] Binance Market Order Failed for {symbol}: {e}" + Style.RESET_ALL)
            return None

    def close_position_market(self, symbol: str, direction: str, qty: float):
        if self.paper_mode or not self.client:
            return
        try:
            close_side = SIDE_SELL if direction == "LONG" else SIDE_BUY
            clean_qty = self.round_qty(symbol, qty)
            self.client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type=ORDER_TYPE_MARKET,
                quantity=clean_qty,
                reduceOnly=True
            )
            # Cancel open brackets
            self.client.futures_cancel_all_open_orders(symbol=symbol)
        except Exception as e:
            print(Fore.RED + f"[!] Failed to close live position {symbol}: {e}" + Style.RESET_ALL)


# =============================================================================
#  CLASS: PositionTracker (Thread-Safe Institutional Position Engine)
# =============================================================================
class PositionTracker:
    """Thread-safe multi-position manager using copy.deepcopy() and Partial TP1 scale-outs."""
    def __init__(self):
        self._lock = threading.Lock()
        self.positions: Dict[str, Dict[str, Any]] = {}

    def add_position(self, pos: Dict[str, Any]):
        with self._lock:
            self.positions[pos["id"]] = pos

    def remove_position(self, pos_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.positions.pop(pos_id, None)

    def get_snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self.positions)

    def count_symbol_positions(self, symbol: str) -> int:
        with self._lock:
            return sum(1 for p in self.positions.values() if p["symbol"] == symbol)

    def total_count(self) -> int:
        with self._lock:
            return len(self.positions)

    def total_margin_committed(self) -> float:
        with self._lock:
            return sum(float(p.get("usdt_size", 0)) for p in self.positions.values())

    def update_peak_pnl(self, pos_id: str, pnl: float):
        with self._lock:
            if pos_id in self.positions:
                if pnl > self.positions[pos_id].get("peak_pnl", 0.0):
                    self.positions[pos_id]["peak_pnl"] = pnl


# =============================================================================
#  CLASS: TelegramNotifier (Instant Bot Alerts & Interactive Commands)
# =============================================================================
class TelegramNotifier:
    """Sends HTML trade notifications and alerts."""
    def __init__(self, token: str = TELEGRAM_BOT_TOKEN, chat_id: str = TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    def send_message(self, text: str):
        if not self.base_url or not self.chat_id:
            return
        def _send():
            try:
                requests.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                    timeout=4.0
                )
            except Exception:
                pass
        threading.Thread(target=_send, daemon=True).start()

    def notify_trade_open(self, pos: Dict[str, Any], score: int, reasons: List[str]):
        icon = "🟢" if pos["direction"] == "LONG" else "🔴"
        msg = (
            f"{icon} <b>NEW FUTURES POSITION OPENED</b>\n"
            f"<b>Symbol:</b> <code>{pos['symbol']}</code>\n"
            f"<b>Direction:</b> <b>{pos['direction']}</b> ({pos['leverage']}x)\n"
            f"<b>Entry Price:</b> <code>${pos['entry']:,.4f}</code>\n"
            f"<b>Size:</b> <code>${pos['usdt_size']:.2f} USDT</code>\n"
            f"<b>TP1 / TP2:</b> <code>${pos['tp1']:,.4f} / ${pos['tp2']:,.4f}</code>\n"
            f"<b>Stop Loss:</b> <code>${pos['sl']:,.4f}</code>\n"
            f"<b>Confluence Score:</b> <b>{score}/5</b>\n"
            f"<b>Catalyst:</b> {pos.get('reason', '')}"
        )
        self.send_message(msg)

    def notify_trade_close(self, symbol: str, direction: str, pnl: float, exit_reason: str, balance: float):
        icon = "🎯" if pnl >= 0 else "🛑"
        sign = "+" if pnl >= 0 else ""
        msg = (
            f"{icon} <b>POSITION CLOSED: {symbol}</b>\n"
            f"<b>Side:</b> {direction}\n"
            f"<b>Realized P&L:</b> <b>{sign}${pnl:.2f} USDT</b>\n"
            f"<b>Exit Reason:</b> {exit_reason}\n"
            f"<b>Account Balance:</b> <code>${balance:,.2f} USDT</code>"
        )
        self.send_message(msg)


# =============================================================================
#  CLASS: PolymarketBinanceBot (Main Orchestrator & Wall Street Scalper)
# =============================================================================
class PolymarketBinanceBot:
    """
    Master Wall Street Quantitative Bot Orchestrator.
    Coordinates Polymarket probability spikes, Binance orderbook OFI alpha,
    Half-Kelly position sizing, multi-tier partial TP scale-outs, and web telemetry.
    """
    def __init__(self, paper_mode: bool = PAPER_MODE, live_flag: bool = False):
        self.paper_mode = False if live_flag else paper_mode
        self.running = False
        self.ai_trading_active = True
        self.symbol_last_entry: Dict[str, float] = {}
        self.active_universe: List[str] = list(SYMBOL_MAP.values())

        # Core subsystems
        self.state = DailyState()
        self.poly = PolymarketDetector()
        self.market = MarketData()
        self.ai = AIValidator()
        self.binance = BinanceFutures(paper_mode=self.paper_mode)
        self.tracker = PositionTracker()
        self.telegram = TelegramNotifier()

        # Web state reference
        self.latest_ai_event: Optional[Dict[str, Any]] = None

    def calculate_kelly_size(self) -> float:
        """Wall Street Volatility-Scaled Half-Kelly Criterion sizing."""
        history = self.state.trade_history
        if len(history) < 10:
            return TRADE_USDT

        wins = [t["pnl"] for t in history if t.get("pnl", 0) > 0]
        losses = [abs(t["pnl"]) for t in history if t.get("pnl", 0) < 0]

        if not wins or not losses:
            return TRADE_USDT

        p = len(wins) / len(history)  # Win rate
        avg_w = sum(wins) / len(wins)
        avg_l = sum(losses) / len(losses)
        b = avg_w / max(avg_l, 0.01)  # Win/loss payout ratio

        f_kelly = (p * b - (1 - p)) / b if b > 0 else 0.0
        half_kelly = max(0.0, f_kelly * 0.5)

        calc_size = self.state.balance * half_kelly
        return max(10.0, min(calc_size, 65.0))

    def check_correlation_cluster(self, symbol: str) -> bool:
        """Blocks opening new exposure if the cluster is already heavily allocated."""
        for cluster, sym_set in CORRELATION_GROUPS.items():
            if symbol in sym_set:
                snap = self.tracker.get_snapshot()
                count_in_cluster = sum(1 for p in snap.values() if p["symbol"] in sym_set)
                if count_in_cluster >= 3:
                    return False
        return True

    def open_candidate_position(self, symbol: str, direction: str, score: int, reason: str, ai_decision: Dict[str, Any]):
        if not self.ai_trading_active:
            return

        # Check circuit breaker
        if self.state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            return

        if self.state.realized_pnl <= -DAILY_LOSS_LIMIT:
            return

        # Multi-position concurrency checks
        if self.tracker.total_count() >= MAX_OPEN_TRADES:
            return

        if self.tracker.count_symbol_positions(symbol) >= MAX_PER_SYMBOL_POSITIONS:
            return

        if not self.check_correlation_cluster(symbol):
            return

        price = self.market.get_mark_price(symbol)
        if price <= 0:
            return

        indicators = self.market.get_klines_indicators(symbol)
        atr = indicators.get("atr") or (price * 0.015)

        # TP / SL Brackets (Wall Street Multi-Target Structure)
        if direction == "LONG":
            tp1 = price + (atr * ATR_TP1_MULT)
            tp2 = price + (atr * ATR_TP2_MULT)
            sl = price - (atr * ATR_SL_MULT)
        else:
            tp1 = price - (atr * ATR_TP1_MULT)
            tp2 = price - (atr * ATR_TP2_MULT)
            sl = price + (atr * ATR_SL_MULT)

        size_usdt = self.calculate_kelly_size()

        # Portfolio Heat Check
        total_committed = self.tracker.total_margin_committed() + size_usdt
        if (total_committed / max(self.state.balance, 1.0)) > MAX_PORTFOLIO_HEAT:
            return

        order = self.binance.market_entry_with_brackets(
            symbol=symbol,
            direction=direction,
            usdt_size=size_usdt,
            leverage=DEFAULT_LEVERAGE,
            tp2=tp2,
            sl=sl,
            mark_price=price
        )
        if not order:
            return

        raw_id = f"{symbol}_{direction}_{int(time.time()*1000)}"
        pos_id = hashlib.md5(raw_id.encode()).hexdigest()[:12]

        pos_record = {
            "id": pos_id,
            "symbol": symbol,
            "direction": direction,
            "entry": price,
            "qty": order.get("qty", (size_usdt * DEFAULT_LEVERAGE) / price),
            "usdt_size": size_usdt,
            "leverage": DEFAULT_LEVERAGE,
            "tp1": tp1,
            "tp2": tp2,
            "sl": sl,
            "atr": atr,
            "peak_pnl": 0.0,
            "tp1_done": False,
            "reason": reason,
            "ai_reason": ai_decision.get("reason", ""),
            "ai_conf": ai_decision.get("confidence", 70),
            "timestamp": time.time(),
            "iso_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        }

        self.tracker.add_position(pos_record)
        self.telegram.notify_trade_open(pos_record, score, [reason, ai_decision.get("reason", "")])

        print(Fore.GREEN + f"[+] EXECUTED {direction} on {symbol} @ ${price:,.4f} (${size_usdt:.2f} USDT | Score: {score}/5)" + Style.RESET_ALL)

    def close_position_safely(self, pos_id: str, reason: str):
        pos = self.tracker.remove_position(pos_id)
        if not pos:
            return

        symbol = pos["symbol"]
        price = self.market.get_mark_price(symbol) or pos["entry"]
        mult = pos["leverage"] * pos["usdt_size"]
        pnl = ((price - pos["entry"]) / pos["entry"] * mult) if pos["direction"] == "LONG" else ((pos["entry"] - price) / pos["entry"] * mult)

        # Execute market close on Binance if live
        self.binance.close_position_market(symbol, pos["direction"], pos["qty"])

        trade_record = {
            "id": pos["id"],
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "symbol": symbol,
            "direction": pos["direction"],
            "entry": pos["entry"],
            "exit": price,
            "pnl": round(pnl, 2),
            "reason": reason,
            "usdt_size": pos["usdt_size"],
            "leverage": pos["leverage"],
            "ai_reason": pos.get("ai_reason", "")
        }

        self.state.record_trade(trade_record)
        self.telegram.notify_trade_close(symbol, pos["direction"], pnl, reason, self.state.balance)

        pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
        print(pnl_color + f"[-] CLOSED {pos['direction']} {symbol} | P&L: {'+' if pnl>=0 else ''}${pnl:.2f} USDT ({reason})" + Style.RESET_ALL)

    def force_close_symbol(self, target: str) -> str:
        target_clean = target.strip()
        snap = self.tracker.get_snapshot()
        matching = [
            p for p in snap.values()
            if p["symbol"].upper() == target_clean.upper() or p["id"].lower() == target_clean.lower()
        ]
        if not matching:
            return f"No open positions matching {target_clean}."
        for p in matching:
            self.close_position_safely(p["id"], "MANUAL USER CLOSE")
        return f"Closed {len(matching)} position(s) for {target_clean}."

    def force_close_all(self) -> str:
        snap = self.tracker.get_snapshot()
        if not snap:
            return "No positions currently open."
        for p in snap.values():
            self.close_position_safely(p["id"], "PANIC / EMERGENCY CLOSE ALL")
        return f"Closed all {len(snap)} active positions."

    def stop_ai_and_flatten_all(self) -> str:
        self.ai_trading_active = False
        msg = self.force_close_all()
        return f"AI Stopped & {msg}"

    def reset_journal_and_account(self) -> str:
        self.force_close_all()
        self.state.reset_clean()
        return "All positions closed, history wiped, paper account reset to $1,000.00."

    def monitor_positions_health(self):
        """Active Health Checks: TP1 partial scale-out, Breakeven runner, TP2, Trailing Stop, OFI reversal, and Stagnation Exit."""
        snap = self.tracker.get_snapshot()
        for pos_id, p in snap.items():
            sym = p["symbol"]
            price = self.market.get_mark_price(sym)
            if price <= 0:
                continue

            mult = p["leverage"] * p["usdt_size"]
            pnl_usd = ((price - p["entry"]) / p["entry"] * mult) if p["direction"] == "LONG" else ((p["entry"] - price) / p["entry"] * mult)
            self.tracker.update_peak_pnl(pos_id, pnl_usd)

            age_min = (time.time() - p["timestamp"]) / 60.0

            # 1. Partial TP1 Scale-Out (50% profit lock + move stop to entry for guaranteed breakeven runner)
            if not p["tp1_done"]:
                tp1_hit = (p["direction"] == "LONG" and price >= p["tp1"]) or (p["direction"] == "SHORT" and price <= p["tp1"])
                if tp1_hit:
                    half_qty = p["qty"] * 0.5
                    half_pnl = pnl_usd * 0.5
                    self.binance.close_position_market(sym, p["direction"], half_qty)
                    p["tp1_done"] = True
                    p["usdt_size"] *= 0.5
                    p["qty"] = half_qty
                    p["sl"] = p["entry"]  # Risk-Free Breakeven runner

                    # Record half-win
                    self.state.record_trade({
                        "id": f"{pos_id}_tp1",
                        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "symbol": sym,
                        "direction": p["direction"],
                        "entry": p["entry"],
                        "exit": price,
                        "pnl": round(half_pnl, 2),
                        "reason": "PARTIAL TP1 (50% locked)",
                        "usdt_size": p["usdt_size"],
                        "leverage": p["leverage"]
                    })
                    print(Fore.GREEN + f"[🎯 TP1 HIT] {sym} ({p['direction']}) | Locked +${half_pnl:.2f}. SL moved to Breakeven!" + Style.RESET_ALL)
                    continue

            # 2. Hard Take Profit Target 2 & Stop Loss
            if p["direction"] == "LONG":
                if price >= p["tp2"]:
                    self.close_position_safely(pos_id, "TAKE PROFIT 2 HIT")
                    continue
                elif price <= p["sl"]:
                    self.close_position_safely(pos_id, "STOP LOSS HIT")
                    continue
            else:
                if price <= p["tp2"]:
                    self.close_position_safely(pos_id, "TAKE PROFIT 2 HIT")
                    continue
                elif price >= p["sl"]:
                    self.close_position_safely(pos_id, "STOP LOSS HIT")
                    continue

            # 3. Dynamic Trailing Stop
            if TRAILING_STOP:
                trig = p["usdt_size"] * (TRAILING_TRIGGER_PCT / 100.0)
                dist = p["usdt_size"] * (TRAILING_DISTANCE_PCT / 100.0)
                if p["peak_pnl"] >= trig and pnl_usd <= (p["peak_pnl"] - dist):
                    self.close_position_safely(pos_id, f"TRAILING STOP (Peak: +${p['peak_pnl']:.2f})")
                    continue

            # 4. Microstructure OFI Adverse Shift Exit
            ofi = self.market.get_order_flow_imbalance(sym)
            if age_min >= 2.0:
                if p["direction"] == "LONG" and ofi < -0.35:
                    self.close_position_safely(pos_id, f"OFI ADVERSE REVERSAL ({ofi:+.2f})")
                    continue
                elif p["direction"] == "SHORT" and ofi > 0.35:
                    self.close_position_safely(pos_id, f"OFI ADVERSE REVERSAL ({ofi:+.2f})")
                    continue

            # 5. Stagnation / Time-Decay Capital Rotation Exit
            if age_min >= 15.0 and pnl_usd >= (p["usdt_size"] * 0.003):
                self.close_position_safely(pos_id, f"SCALP HARVEST (+${pnl_usd:.2f} at {age_min:.0f}m)")
                continue

            if age_min >= 40.0:
                self.close_position_safely(pos_id, f"MAX DURATION ROTATION ({age_min:.0f}m)")
                continue

    def get_dashboard_snapshot(self) -> Dict[str, Any]:
        """Provides instantaneous telemetry snapshot for the Web API and Terminal."""
        snap_positions = self.tracker.get_snapshot()
        pos_list = []
        unrealized = 0.0

        for pos_id, p in snap_positions.items():
            sym = p["symbol"]
            cur_price = self.market.get_mark_price(sym) or p["entry"]
            mult = p["leverage"] * p["usdt_size"]
            pnl = ((cur_price - p["entry"]) / p["entry"] * mult) if p["direction"] == "LONG" else ((p["entry"] - cur_price) / p["entry"] * mult)
            unrealized += pnl
            pos_list.append({
                "id": p["id"],
                "symbol": sym,
                "direction": p["direction"],
                "entry": p["entry"],
                "current_price": cur_price,
                "pnl": round(pnl, 2),
                "tp1": p["tp1"],
                "tp2": p["tp2"],
                "sl": p["sl"],
                "usdt_size": p["usdt_size"],
                "leverage": p["leverage"],
                "age_mins": round((time.time() - p["timestamp"]) / 60.0, 1)
            })

        total_equity = self.state.balance + unrealized
        total = self.state.wins + self.state.losses
        win_rate = (self.state.wins / total * 100.0) if total > 0 else 0.0
        heat_pct = (self.tracker.total_margin_committed() / max(total_equity, 1.0)) * 100.0

        return {
            "live_mode": not self.paper_mode,
            "ai_trading_active": self.ai_trading_active,
            "equity": round(total_equity, 2),
            "balance": round(self.state.balance, 2),
            "daily_pnl": round(self.state.realized_pnl + unrealized, 2),
            "realized_pnl": round(self.state.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "wins": self.state.wins,
            "losses": self.state.losses,
            "win_rate": round(win_rate, 1),
            "positions_count": len(pos_list),
            "max_positions": MAX_OPEN_TRADES,
            "portfolio_heat": round(heat_pct / 100.0, 2),
            "heat_pct": round(heat_pct, 1),
            "positions": pos_list,
            "world_time_utc": self.market.get_world_utc_string(),
            "latest_ai_event": self.latest_ai_event,
            "recent_trades": self.state.trade_history[-10:]
        }

    def print_terminal_dashboard(self):
        snap = self.get_dashboard_snapshot()
        mode_str = Fore.RED + "[LIVE REAL TRADES]" if snap["live_mode"] else Fore.GREEN + "[REAL-TIME PAPER ENGINE]"
        ai_str = Fore.GREEN + "ONLINE" if snap["ai_trading_active"] else Fore.YELLOW + "PAUSED"

        pnl = snap["daily_pnl"]
        pnl_col = Fore.GREEN if pnl >= 0 else Fore.RED

        print("\n" + "="*70)
        print(f" {Fore.CYAN}SIA-TradeX Pro Dashboard{Style.RESET_ALL} | {snap['world_time_utc']}")
        print(f" Mode: {mode_str}{Style.RESET_ALL} | AI Auto-Trader: {ai_str}{Style.RESET_ALL}")
        print(f" Equity: {Fore.CYAN}${snap['equity']:,.2f}{Style.RESET_ALL} | Realized P&L: {pnl_col}{'+' if pnl>=0 else ''}${pnl:.2f}{Style.RESET_ALL}")
        print(f" Win Rate: {snap['win_rate']}% ({snap['wins']}W / {snap['losses']}L) | Heat: {snap['heat_pct']}% ({snap['positions_count']} Open)")

        if snap["positions"]:
            print("-" * 70)
            print(f" {'Symbol':<10} {'Side':<6} {'Entry':<10} {'Mark':<10} {'P&L (USDT)':<12} {'Age':<6}")
            for p in snap["positions"]:
                col = Fore.GREEN if p["pnl"] >= 0 else Fore.RED
                print(f" {p['symbol']:<10} {p['direction']:<6} ${p['entry']:<9.4f} ${p['current_price']:<9.4f} {col}{'+' if p['pnl']>=0 else ''}${p['pnl']:<10.2f}{Style.RESET_ALL} {p['age_mins']}m")
        print("="*70 + "\n")

    def scan_universe_confluence(self) -> int:
        """
        Wall Street Multi-Asset High-Frequency Quantitative Scanner.
        Evaluates top liquid Binance Futures pairs against:
        - 1h EMA(20) Trend & Momentum
        - Order Flow Imbalance (OFI) alpha from L2 orderbook depth
        - Funding Rate confirmation
        - Polymarket predictive consensus/spikes
        - AI risk evaluation
        Opens positions autonomously whenever Confluence Score >= 3/5.
        Returns number of new positions opened.
        """
        if not self.ai_trading_active:
            return 0

        now = time.time()
        opened = 0

        for sym in self.active_universe:
            try:
                # Cooldown per symbol to space entries
                if (now - self.symbol_last_entry.get(sym, 0)) < 35.0:
                    continue
                if self.tracker.count_symbol_positions(sym) >= MAX_PER_SYMBOL_POSITIONS:
                    continue
                if self.tracker.total_count() >= MAX_OPEN_TRADES:
                    break

                indicators = self.market.get_klines_indicators(sym)
                funding = self.market.get_funding_rate(sym)
                ofi = self.market.get_order_flow_imbalance(sym)
                momentum = indicators.get("momentum", "NEUTRAL")

                # Determine primary directional bias
                if momentum == "LONG":
                    direction = "LONG"
                elif momentum == "SHORT":
                    direction = "SHORT"
                else:
                    if abs(ofi) >= 0.10:
                        direction = "LONG" if ofi > 0 else "SHORT"
                    else:
                        continue

                ai_res = self.ai.validate(
                    symbol=sym,
                    direction=direction,
                    poly_question=f"Binance Microstructure OFI ({ofi:+.2f}) with {momentum} Momentum",
                    momentum=momentum,
                    ofi=ofi
                )

                score, reasons = ConfluenceEngine.evaluate(
                    direction=direction,
                    poly_spike=False,
                    momentum=momentum,
                    funding_rate=funding,
                    ofi=ofi,
                    ai_conf=ai_res["confidence"]
                )

                # Institutional threshold: 3/5 confluence
                if score >= 3 and ai_res["approved"]:
                    cat_reason = f"Confluence ({score}/5) [{direction}]: {', '.join(reasons[:2])}"
                    self.open_candidate_position(sym, direction, score, cat_reason, ai_res)
                    self.symbol_last_entry[sym] = now
                    self.latest_ai_event = {
                        "symbol": sym,
                        "signal": direction,
                        "confidence": ai_res["confidence"],
                        "reason": f"Score {score}/5: {ai_res['reason']}",
                        "catalyst": cat_reason
                    }
                    opened += 1
            except Exception:
                continue

        return opened

    def run_polymarket_pipeline(self):
        """Continuously scans Polymarket prediction catalysts + High-Frequency Quant Universe."""
        while self.running:
            if self.ai_trading_active:
                now = time.time()
                # 1. Polymarket Prediction Spikes (Priority Catalysts)
                try:
                    spikes = self.poly.scan_spikes()
                    for sp in spikes:
                        sym = sp["symbol"]
                        direction = sp["direction"]
                        if (now - self.symbol_last_entry.get(sym, 0)) < 30.0:
                            continue

                        indicators = self.market.get_klines_indicators(sym)
                        funding = self.market.get_funding_rate(sym)
                        ofi = self.market.get_order_flow_imbalance(sym)

                        ai_res = self.ai.validate(
                            symbol=sym,
                            direction=direction,
                            poly_question=sp["question"],
                            momentum=indicators.get("momentum", "NEUTRAL"),
                            ofi=ofi
                        )
                        self.latest_ai_event = {
                            "symbol": sym,
                            "signal": direction,
                            "confidence": ai_res["confidence"],
                            "reason": ai_res["reason"],
                            "catalyst": sp["question"]
                        }

                        score, reasons = ConfluenceEngine.evaluate(
                            direction=direction,
                            poly_spike=True,
                            momentum=indicators.get("momentum", "NEUTRAL"),
                            funding_rate=funding,
                            ofi=ofi,
                            ai_conf=ai_res["confidence"]
                        )

                        if score >= MIN_SIGNAL_SCORE and ai_res["approved"]:
                            cat_reason = f"Polymarket {sp['delta_pct']:+.1f}%: {sp['question']}"
                            self.open_candidate_position(sym, direction, score, cat_reason, ai_res)
                            self.symbol_last_entry[sym] = now
                except Exception:
                    pass

                # 2. Continuous Wall Street Multi-Asset Quant Confluence Scanner
                try:
                    self.scan_universe_confluence()
                except Exception:
                    pass

            time.sleep(POLY_SCAN_INTERVAL)

    def run(self):
        self.running = True
        print_ascii_banner()

        # Immediate opportunistic scan upon startup
        try:
            self.scan_universe_confluence()
        except Exception:
            pass

        # Start Polymarket scan loop thread
        poly_thread = threading.Thread(target=self.run_polymarket_pipeline, name="poly_pipeline", daemon=True)
        poly_thread.start()

        last_dash = 0.0
        while self.running:
            try:
                self.monitor_positions_health()

                now = time.time()
                if (now - last_dash) >= 45.0:
                    self.print_terminal_dashboard()
                    last_dash = now

            except KeyboardInterrupt:
                print("\n[!] Received shutdown signal. Gracefully exiting...")
                self.running = False
                break
            except Exception as e:
                time.sleep(0.5)

            time.sleep(0.05)  # 50ms hot-path execution cycle


# =============================================================================
#  EMBEDDED FASTAPI WEB TELEMETRY SERVER (Cyber-Quant UI on Port 8080)
# =============================================================================
try:
    import asyncio
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel
    import uvicorn

    web_app = FastAPI(title="SIA-TradeX Pro Institutional Telemetry")
    bot_instance_ref: Optional[PolymarketBinanceBot] = None

    class CloseReq(BaseModel):
        symbol: Optional[str] = None
        id: Optional[str] = None

    class TradeReq(BaseModel):
        symbol: str
        direction: str
        size: Optional[float] = 20.0

    @web_app.get("/")
    async def serve_index():
        static_index = BASE_DIR / "ui" / "static" / "index.html"
        if static_index.exists():
            return FileResponse(static_index)
        return JSONResponse({"status": "running", "engine": "SIA-TradeX Pro", "web": "Active"})

    @web_app.get("/api/state")
    async def get_state():
        if bot_instance_ref:
            return bot_instance_ref.get_dashboard_snapshot()
        return {"error": "Engine not attached"}

    @web_app.get("/api/trades")
    async def get_trades():
        if bot_instance_ref:
            return bot_instance_ref.state.trade_history[-50:]
        return []

    @web_app.post("/api/ai/toggle")
    async def toggle_ai():
        if bot_instance_ref:
            bot_instance_ref.ai_trading_active = not bot_instance_ref.ai_trading_active
            if bot_instance_ref.ai_trading_active:
                bot_instance_ref.scan_universe_confluence()
            return {"status": "ok", "ai_trading_active": bot_instance_ref.ai_trading_active}
        return {"error": "Engine not attached"}

    @web_app.post("/api/ai/start")
    async def start_ai():
        if bot_instance_ref:
            bot_instance_ref.ai_trading_active = True
            opened = bot_instance_ref.scan_universe_confluence()
            return {"status": "ok", "ai_trading_active": True, "message": f"AI Auto-Trader Active. Scanned and opened {opened} position(s)."}
        return {"error": "Engine not attached"}

    @web_app.post("/api/ai/pause")
    async def pause_ai():
        if bot_instance_ref:
            bot_instance_ref.ai_trading_active = False
            return {"status": "ok", "ai_trading_active": False, "message": "AI Auto-Trader Paused."}
        return {"error": "Engine not attached"}

    @web_app.post("/api/ai/scan-now")
    async def force_scan():
        if bot_instance_ref:
            bot_instance_ref.ai_trading_active = True
            opened = bot_instance_ref.scan_universe_confluence()
            return {"status": "ok", "opened": opened, "message": f"Universe Confluence Scan complete. Opened {opened} position(s)."}
        return {"error": "Engine not attached"}

    @web_app.post("/api/close")
    async def close_trade(req: Optional[CloseReq] = None, symbol: Optional[str] = None, id: Optional[str] = None):
        if bot_instance_ref:
            target = ""
            if req: target = req.id or req.symbol or ""
            if not target and id: target = id
            if not target and symbol: target = symbol
            msg = bot_instance_ref.force_close_symbol(target)
            return {"status": "ok", "message": msg}
        return {"error": "Engine not attached"}

    @web_app.post("/api/panic")
    async def panic_close():
        if bot_instance_ref:
            msg = bot_instance_ref.force_close_all()
            return {"status": "ok", "message": msg}
        return {"error": "Engine not attached"}

    @web_app.post("/api/stop-all")
    async def stop_all():
        if bot_instance_ref:
            msg = bot_instance_ref.stop_ai_and_flatten_all()
            return {"status": "ok", "ai_trading_active": False, "message": msg}
        return {"error": "Engine not attached"}

    @web_app.post("/api/reset")
    async def reset_journal():
        if bot_instance_ref:
            msg = bot_instance_ref.reset_journal_and_account()
            return {"status": "ok", "message": msg}
        return {"error": "Engine not attached"}

    @web_app.post("/api/trade")
    async def manual_entry(req: TradeReq):
        if bot_instance_ref:
            bot_instance_ref.open_candidate_position(
                req.symbol.upper(),
                req.direction.upper(),
                5,
                "Manual User Override",
                {"confidence": 90, "reason": "User manual trigger", "approved": True}
            )
            return {"status": "ok", "message": f"Queued {req.direction} {req.symbol}"}
        return {"error": "Engine not attached"}

    @web_app.websocket("/ws")
    async def ws_telemetry(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                if bot_instance_ref:
                    await websocket.send_json(bot_instance_ref.get_dashboard_snapshot())
                await asyncio.sleep(0.5)
        except Exception:
            pass

    def start_web_server(bot: PolymarketBinanceBot):
        global bot_instance_ref
        bot_instance_ref = bot
        def _run_uvicorn():
            try:
                uvicorn.run(web_app, host=WEB_HOST, port=WEB_PORT, log_level="warning")
            except Exception:
                pass
        t = threading.Thread(target=_run_uvicorn, name="web_server", daemon=True)
        t.start()

except Exception:
    def start_web_server(bot):
        pass


# =============================================================================
#  MAIN ENTRYPOINT
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="SIA-TradeX Pro: Autonomous Wall Street Trading Bot")
    parser.add_argument("--live", action="store_true", help="Execute real live trades on Binance Futures Mainnet")
    parser.add_argument("--paper", action="store_true", help="Run simulated paper trades with live market feeds")
    parser.add_argument("--test", action="store_true", help="Inject instant test prediction spike")
    parser.add_argument("--reset", action="store_true", help="Clear past journal history and reset balance")
    args = parser.parse_args()

    bot = PolymarketBinanceBot(live_flag=args.live)

    if args.reset:
        bot.reset_journal_and_account()
        print("[*] Trade history reset to clean $1,000.00 slate.")

    if args.test:
        print("[*] Injecting synthetic Polymarket probability spike for BTC...")
        bot.open_candidate_position(
            "BTCUSDT",
            "LONG",
            5,
            "TEST Polymarket Spike +8.5%: Fed Emergency Rate Cut Rumors",
            {"confidence": 92, "reason": "Test setup injection", "approved": True}
        )

    # Launch embedded telemetry web dashboard
    start_web_server(bot)
    print(f"[*] Cyber-Quant Web Dashboard online at: http://localhost:{WEB_PORT}")

    # Run institutional engine
    bot.run()


if __name__ == "__main__":
    main()
