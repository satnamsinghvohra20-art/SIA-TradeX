#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  AI CRYPTO TRADING BOT  v11.1  |  LIVE TRADING EDITION
  Polymarket + NewsAPI + Telegram + Gemini AI + Binance Futures

  CHANGES v11.1 vs v11.0:
  ─────────────────────────────────────────────────────────────────────────
  [FIX-LIVE-1]  PAPER_MODE now defaults to True for safety.
                Use --live flag OR set PAPER_MODE=false in .env to go live.
                This prevents accidental live trading.

  [FIX-LIVE-2]  USE_TESTNET now defaults to FALSE when .env sets it.
                v11.0 had `os.getenv("BINANCE_TESTNET","true")` — the
                "true" default meant even with BINANCE_TESTNET=false in
                .env, you'd end up on testnet if the env var wasn't read
                correctly. Now explicit and verified at startup.

  [FIX-LIVE-3]  Binance connection now shows EXACT error + fix instructions
                instead of silently falling back to paper mode.
                Also validates API key format before attempting connection.

  [FIX-LIVE-4]  Added /balance Telegram command to check live wallet.

  [FIX-LIVE-5]  Dashboard now shows REAL Binance balance when live,
                not the simulated paper cash.

  [FIX-LIVE-6]  Added startup balance check — refuses to start live
                trading if USDT futures balance < MIN_TRADE_USDT.

  [FIX-LIVE-7]  Smart profit protection now works in both paper and live.

  [FIX-LIVE-8]  Live mode confirmation is clearer and shows exact balance.
=============================================================================
  SETUP FOR LIVE TRADING
  ─────────────────────────────────────────────────────────────────────────
  1. pip install python-binance requests python-dotenv colorama google-generativeai

  2. Create .env file in same folder as this script:
     BINANCE_API_KEY=your_key_here
     BINANCE_API_SECRET=your_secret_here
     BINANCE_TESTNET=false
     GEMINI_API_KEY=your_gemini_key_here
     NEWS_API_KEY=your_news_api_key_here
     TELEGRAM_BOT_TOKEN=your_telegram_token_here
     TELEGRAM_CHAT_ID=your_chat_id_here

  3. Run:
     python bot.py --live          <- live trading with confirmation
     python bot.py                 <- paper mode (safe default)
     python bot.py --test          <- inject test signals
     python bot.py --debug         <- verbose logging

  BINANCE API SETUP:
  ─────────────────────────────────────────────────────────────────────────
  binance.com -> Profile (top right) -> API Management -> Create API
  Name: anything (e.g. "tradingbot")
  Permissions: CHECK "Enable Futures" ONLY
               DO NOT check "Enable Withdrawals" (security risk)
  IP restriction: optionally whitelist your IP for extra security
  Copy BOTH the API Key AND Secret Key immediately (secret shown once)
=============================================================================
"""

import os
import sys

# ── UTF-8 fix for Windows Python 3.13 ────────────────────────────────────
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import json
import re
import signal as signal_module
import threading
import hashlib
import copy
import math
import argparse
from datetime import datetime, timezone
from collections import defaultdict, deque
from typing import Optional


# ── Auto-install missing packages ────────────────────────────────────────
def _install(pkg):
    os.system(f'"{sys.executable}" -m pip install {pkg} --quiet')

for _pkg, _imp in [
    ("python-binance",      "binance"),
    ("requests",            "requests"),
    ("python-dotenv",       "dotenv"),
    ("colorama",            "colorama"),
    ("google-generativeai", "google.generativeai"),
]:
    try:
        __import__(_imp)
    except ImportError:
        print(f"Installing {_pkg}...")
        _install(_pkg)

import requests
import google.generativeai as genai
from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
from colorama import init, Fore, Style

init(autoreset=True)
load_dotenv()

G = Fore.GREEN;  R = Fore.RED;    Y = Fore.YELLOW
B = Fore.CYAN;   M = Fore.MAGENTA; W = Fore.WHITE
DIM = Style.DIM; BRIGHT = Style.BRIGHT; RST = Style.RESET_ALL


# =============================================================================
#  CONFIG  —  edit these or override with .env
# =============================================================================

# [FIX-LIVE-1] Default PAPER for safety. Use --live flag to go live.
PAPER_MODE             = True    # overridden by --live flag or PAPER_MODE=false in .env

PAPER_STARTING_BALANCE = 1000.0

# Polymarket
POLY_SCAN_INTERVAL     = 3
SPIKE_THRESHOLD        = 0.03
SPIKE_WINDOW_SEC       = 120
POLY_FETCH_LIMIT       = 500

# NewsAPI
NEWS_SCAN_INTERVAL     = 60
NEWS_LOOKBACK_MIN      = 10
NEWS_SIGNAL_COOLDOWN   = 300

BULLISH_KEYWORDS = [
    "etf approved","etf approval","etf launch","rate cut","rate cuts",
    "fed cut","dovish","sec approves","sec approval","grayscale",
    "institutional buy","whale accumulation","bitcoin reserve",
    "strategic reserve","halving","bullish","all-time high","ath",
    "adoption","partnership","listing",
]
BEARISH_KEYWORDS = [
    "hack","hacked","exploit","ban","banned","crackdown","seized",
    "sec sues","sec charges","lawsuit","rate hike","hawkish","tightening",
    "bankruptcy","bankrupt","insolvent","bearish","crash","collapse","dump",
    "exchange down","exchange halted","fdic","bank run",
]

# Telegram
TG_POLL_INTERVAL       = 2

# =============================================================================
#  v13.0 AGGRESSIVE CONFIG — data-proven, not random aggression
#
#  FROM 63 REAL TRADES THE DATA SAYS:
#  ─────────────────────────────────
#  SHORT WR = 62.5%  PnL = +$8.38   ← YOUR EDGE
#  LONG  WR = 39.1%  PnL = -$0.41   ← YOUR WEAKNESS
#
#  AGGRESSIVE = exploit the SHORT edge harder:
#    • 3x leverage (was 2x)  → same trade, 50% more money
#    • Bigger position size: 1.5% risk per trade (was 1.0%)
#    • 6 max trades (was 4) → more concurrent SHORTs running
#    • SHORT-first symbols: LINK, DOGE, SOL, ETH — proven winners
#    • Faster scan: 12s (was 18s) → catch moves earlier
#    • Lower PP threshold: $0.15 → lock profit even faster
#    • Tighter trail: 0.25% distance → squeeze out every cent
#    • Score cap 8 (was 9) → sweet spot is 6-8, stay there
#    • LONG ban extended: BNBUSDT + XRPUSDT + NEARUSDT
#    • Daily target: $150 (was $80) → push for real gains
#
#  WHAT WE DON'T DO:
#    • Lower score threshold (same WR at 3 vs 5, no benefit)
#    • Add more symbols (dilutes edge, adds noise)
#    • Remove Gemini veto (blind trades = -$0.74 net in your data)
#    • Disable stop loss (not aggressive, just suicide)
# =============================================================================

DEFAULT_LEVERAGE       = 3        # AGGRESSIVE: 3x (data supports this — SHORTs
                                   # have 62.5% WR and positive expectancy)
RISK_PER_TRADE_PCT     = 1.5      # AGGRESSIVE: 1.5% per trade (was 1.0%)
                                   # At $1000 balance: ~$15/trade risked
MIN_TRADE_USDT         = 10.0     # floor raised — tiny trades don't move needle
MAX_TRADE_USDT         = 60.0     # cap raised proportionally
MAX_OPEN_TRADES        = 6        # AGGRESSIVE: 6 concurrent (was 4)
                                   # More SHORTs running = more edge captured
MAX_PORTFOLIO_HEAT     = 0.50     # 50% max exposure (was 35%) — we have edge,
                                   # use it; but never go full-port on one bet

# TP/SL — let winners absolutely run, cut losers hard and fast
USE_ATR_EXITS          = True
ATR_PERIOD             = 14
ATR_TP1_MULT           = 1.2      # AGGRESSIVE: take partial profit earlier
ATR_TP2_MULT           = 4.0      # AGGRESSIVE: let the rest run much further
ATR_SL_MULT            = 0.7      # AGGRESSIVE: tighter SL (was 0.8)
                                   # Lose less on each bad trade
FIXED_TP1_PCT          = 1.2
FIXED_TP2_PCT          = 4.0
FIXED_SL_PCT           = 0.7
TRAILING_STOP          = True
TRAILING_TRIGGER_PCT   = 0.6      # AGGRESSIVE: trail kicks in at 0.6% (was 0.8)
TRAILING_DISTANCE_PCT  = 0.25     # AGGRESSIVE: ultra-tight trail (was 0.35)
                                   # Trailing Stop had 100% WR — maximise it

# Smart Profit Protection — 100% WR in your data, make it fire more
PROFIT_PROTECT_ENABLED        = True
PROFIT_PROTECT_MIN_PNL_USD    = 0.15  # AGGRESSIVE: trigger at $0.15 (was $0.20)
PROFIT_PROTECT_GIVEBACK_PCT   = 0.25  # AGGRESSIVE: exit on 25% giveback (was 30%)
PROFIT_PROTECT_REVERSAL_SCORE = 2
PROFIT_PROTECT_RSI_SWING      = 4     # AGGRESSIVE: detect reversal FAST (was 5)
PROFIT_PROTECT_INDICATOR_TTL  = 4     # AGGRESSIVE: fresher reads (was 6)

# ── DIRECTION BIAS — SHORT IS YOUR EDGE ───────────────────────────────────
LONG_EXTRA_SCORE_REQUIRED = 3     # AGGRESSIVE: LONGs need 3 extra pts (was 2)
                                   # Data: LONG 39% WR. Filter them hard.
BANNED_LONG_SYMBOLS = {
    "BNBUSDT",    # 4 trades, 25% WR, -$1.74 — worst performer
    "XRPUSDT",    # LONG PnL -$1.06
    "NEARUSDT",   # 1 trade, 0% WR, -$0.14 — adding to ban
}

# Strategy filters — LOOSENED slightly to allow more SHORT trades
# (aggressive = more trades with edge, not fewer)
RSI_PERIOD             = 14
RSI_OVERBOUGHT         = 68       # slightly looser for SHORTs (RSI can be higher
                                   # when we're shorting an overbought market)
RSI_OVERSOLD           = 30       # stay strict on SHORT protection
RSI_FILTER_ENABLED     = True
VWAP_FILTER_ENABLED    = True
VWAP_BLOCK_PCT         = 0.02     # slightly looser VWAP for more SHORT entries
MTF_FILTER_ENABLED     = True
MTF_INTERVAL           = "4h"
SESSION_FILTER_ENABLED = True
ALLOWED_SESSIONS = {
    "london":    (7,  12),        # best volume, most reliable signals
    "ny_overlap":(12, 17),        # highest volume of all — AGGRESSIVE target
    "ny":        (17, 21),        # still strong
    # Asia still excluded — your data showed weaker setups
}
VOL_FILTER_ENABLED     = True
VOL_ATR_LOOKBACK       = 20
VOL_MIN_RATIO          = 0.28     # FIX: was 0.65 — killed 49 real signals!
                                   # Log shows all blocked trades had ratio 0.30-0.54
                                   # Market is just in a lower-vol regime right now
                                   # 0.28 lets those through while still blocking dead flat
BREAKOUT_ENABLED       = True
BREAKOUT_PERIOD        = 15       # AGGRESSIVE: 15-period breakout (was 20)
                                   # detects breakouts slightly earlier
VOLUME_CONFIRM_ENABLED = True
VOLUME_SPIKE_MULT      = 1.15     # slightly easier volume bar (was 1.3)

# Correlation — allow more exposure since SHORTs are diversified
CORRELATION_LIMIT_PCT  = 0.50     # 50% per group (was 40%) for more SHORT slots
CORRELATION_GROUPS = {
    "btc_group":  {"BTCUSDT"},
    "eth_group":  {"ETHUSDT","ARBUSDT","OPUSDT"},
    "l1_group":   {"SOLUSDT","AVAXUSDT","NEARUSDT","SUIUSDT"},
    "meme_group": {"DOGEUSDT","PEPEUSDT"},
}

# Risk management — AGGRESSIVE but not reckless
DAILY_LOSS_LIMIT       = 50       # $50 max daily loss (was $35)
                                   # bigger size = need slightly more room
DAILY_PROFIT_TARGET    = 150      # AGGRESSIVE: target $150/day (was $80)
                                   # then stop — don't give back the gains
MAX_CONSECUTIVE_LOSSES = 3        # still stop after 3 — protect capital
COOLDOWN_MINUTES       = 15       # AGGRESSIVE: shorter cooldown (was 25)
                                   # don't stay out too long with an edge

# Signal score — keep the proven sweet spot
MIN_SIGNAL_SCORE       = 5        # same entry bar
MAX_SIGNAL_SCORE       = 8        # AGGRESSIVE: tighter cap (was 9)
                                   # 6-8 is the sweet spot, stay there

# Gemini — AGGRESSIVE but keep quality gate
GEMINI_MODEL           = "gemini-2.5-flash"
GEMINI_HIGH_CONF       = 72       # slightly lower bar for high-conf bonus
GEMINI_MID_CONF        = 58
GEMINI_VETO            = True     # KEEP: blind trades cost -$0.74 in your data
GEMINI_AUTO_TRADE      = True
GEMINI_AUTO_SCAN_SEC   = 25       # FIX: was 12s — caused 2939 rate limit hits!
                                   # Free Gemini = 15 req/min max.
                                   # 7 symbols × 25s = ~17 req/min = just under limit
GEMINI_AUTO_MIN_CONF   = 65       # keep 65%
GEMINI_AUTO_SYMBOLS    = [
    # 7 proven symbols — rotated 3 per cycle to stay within rate limits
    "LINKUSDT",   # BEST: 100% WR, +$3.87
    "SOLUSDT",    # 83% WR, +$1.17
    "ETHUSDT",    # 62% WR, +$0.98
    "DOGEUSDT",   # +$2.60 total
    "BTCUSDT",    # volatile, big moves
    "AVAXUSDT",   # 56% WR, +$0.49
    "ADAUSDT",    # 50% WR, positive
]
GEMINI_SYMBOL_COOLDOWN = 90
GEMINI_MIN_CALL_GAP    = 3.0      # FIX: was 1.2s — increase to 3s between calls
                                   # = max 20 calls/min, safely under free tier limit

# Smart exit — AGGRESSIVE: check more frequently
SMART_EXIT_ENABLED     = True
SMART_EXIT_INTERVAL    = 15       # AGGRESSIVE: check every 15s (was 20s)
SMART_EXIT_MIN_AGE     = 90       # AGGRESSIVE: AI can exit after 90s (was 120s)

# Cache
PRICE_CACHE_TTL        = 2
KLINE_CACHE_TTL        = 30
STATE_FILE             = "bot_state.json"
EQUITY_FILE            = "paper_equity.json"

SYMBOL_MAP = {
    "bitcoin":"BTCUSDT","btc":"BTCUSDT","ethereum":"ETHUSDT","eth":"ETHUSDT",
    "solana":"SOLUSDT","sol":"SOLUSDT","bnb":"BNBUSDT","xrp":"XRPUSDT",
    "ripple":"XRPUSDT","doge":"DOGEUSDT","dogecoin":"DOGEUSDT","ada":"ADAUSDT",
    "cardano":"ADAUSDT","avax":"AVAXUSDT","avalanche":"AVAXUSDT",
    "link":"LINKUSDT","chainlink":"LINKUSDT","matic":"MATICUSDT",
    "polygon":"MATICUSDT","dot":"DOTUSDT","polkadot":"DOTUSDT",
    "atom":"ATOMUSDT","cosmos":"ATOMUSDT","near":"NEARUSDT",
    "arb":"ARBUSDT","arbitrum":"ARBUSDT","op":"OPUSDT","optimism":"OPUSDT",
    "sui":"SUIUSDT","pepe":"PEPEUSDT","ton":"TONUSDT",
}

BINANCE_FAPI_MAIN = "https://fapi.binance.com"
BINANCE_FAPI_TEST = "https://testnet.binancefuture.com"
GAMMA_API         = "https://gamma-api.polymarket.com"
NEWS_API_BASE     = "https://newsapi.org/v2"

# ── Keys from .env ────────────────────────────────────────────────────────
BINANCE_KEY    = os.getenv("BINANCE_API_KEY",    "")
BINANCE_SECRET = os.getenv("BINANCE_API_SECRET", "")

# [FIX-LIVE-2] Explicit testnet check — default False (live) if .env says false
_testnet_env   = os.getenv("BINANCE_TESTNET", "true").strip().lower()
USE_TESTNET    = _testnet_env not in ("false", "0", "no", "live")

TG_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID",   "")
NEWS_API_KEY   = os.getenv("NEWS_API_KEY",        "")
GEMINI_KEY     = os.getenv("GEMINI_API_KEY",      "")

# Paper mode can also be disabled via .env
if os.getenv("PAPER_MODE", "").strip().lower() in ("false", "0", "no", "live"):
    PAPER_MODE = False


# =============================================================================
#  UTILITIES
# =============================================================================

def ts():       return datetime.now().strftime("%H:%M:%S")
def ts_full():  return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def utc_hour(): return datetime.now(timezone.utc).hour
def clamp(v, lo, hi): return max(lo, min(hi, v))

def log(msg, color=W, level="INFO", save=True):
    if level == "DEBUG" and os.getenv("BOT_LOG_LEVEL", "INFO") != "DEBUG":
        return
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    print(f"{DIM}[{ts()}]{RST}  {color}{safe}{RST}")
    if save:
        try:
            with open("signal_bot.log", "a", encoding="utf-8") as f:
                f.write(f"[{ts_full()}] [{level}] {msg}\n")
        except Exception:
            pass

def pct_bar(pct, width=20, color=G):
    filled = int(clamp(pct, 0, 100) / 100 * width)
    return color + "#" * filled + RST + DIM + "-" * (width - filled) + RST

def in_trading_session():
    if not SESSION_FILTER_ENABLED:
        return True, "24/7"
    h = utc_hour()
    for name, (s, e) in ALLOWED_SESSIONS.items():
        if s <= h < e:
            return True, name.upper()
    return False, "OFF-HOURS"


def banner(live_mode: bool, live_balance: float = 0.0, test_mode: bool = False):
    mode = f"{R}{BRIGHT}LIVE FUTURES{RST}" if live_mode else f"{G}PAPER (safe){RST}"
    net  = f"{Y}TESTNET{RST}" if USE_TESTNET else f"{R}MAINNET{RST}"
    ai   = f"{G}active{RST}" if GEMINI_KEY else f"{R}NO KEY{RST}"
    tg   = f"{G}active{RST}" if (TG_TOKEN and TG_CHAT_ID) else f"{Y}not set{RST}"
    pp   = f"{G}ON{RST}" if PROFIT_PROTECT_ENABLED else f"{R}OFF{RST}"
    bal  = (f"\n  Live balance : {G}{BRIGHT}${live_balance:,.2f} USDT{RST}"
            if live_mode else f"\n  Paper balance: ${PAPER_STARTING_BALANCE:,.2f}")
    test = f"\n  {R}*** TEST MODE ***{RST}" if test_mode else ""
    print(f"""
{B}+===============================================================+
|  AI CRYPTO TRADING BOT  v13.0  |  AGGRESSIVE EDITION        |
|  3x Lev | SHORT-first | Score 5-8 | 7 proven symbols        |
+===============================================================+{RST}
{test}
  Mode    : {mode}  |  Network : {net}{bal}
  Gemini  : {ai}  ({GEMINI_MODEL})
  Telegram: {tg}
  Leverage: {R}{DEFAULT_LEVERAGE}x{RST}  Risk/trade: {RISK_PER_TRADE_PCT}%  Score {MIN_SIGNAL_SCORE}-{MAX_SIGNAL_SCORE}
  TP1/TP2 : {ATR_TP1_MULT}x/{ATR_TP2_MULT}x ATR  SL: {ATR_SL_MULT}x  Trail: {TRAILING_TRIGGER_PCT}%/{TRAILING_DISTANCE_PCT}%

  {R}AGGRESSIVE RULES (all data-proven):{RST}
  [1] 3x leverage — 50% more gain/loss vs v12
  [2] 1.5% risk/trade — bigger size on your 62.5% SHORT edge
  [3] LONGs need score {MIN_SIGNAL_SCORE + LONG_EXTRA_SCORE_REQUIRED} | SHORTs need {MIN_SIGNAL_SCORE} — HEAVY SHORT BIAS
  [4] Banned LONG: {', '.join(sorted(BANNED_LONG_SYMBOLS))}
  [5] 7 PROVEN symbols only — losers (XRP/BNB/NEAR) excluded
  [6] Scan every {GEMINI_AUTO_SCAN_SEC}s | Trail at {TRAILING_TRIGGER_PCT}% | PP at ${PROFIT_PROTECT_MIN_PNL_USD}
  [7] Daily target ${DAILY_PROFIT_TARGET} — STOP when hit, don't give back

  {G}YOUR EDGE: Trailing Stop + Profit Protect = 100% WR in data{RST}
  {Y}RULE: LET EVERY TRADE RUN — no manual closes, no restarts{RST}

  Ctrl+C : graceful exit  |  Ctrl+C x2 : force close all
""")


# =============================================================================
#  PAPER ACCOUNT
# =============================================================================

class PaperAccount:
    def __init__(self):
        self._lock          = threading.Lock()
        self.cash           = PAPER_STARTING_BALANCE
        self.realized_pnl   = 0.0
        self.equity_history = []

    def total_equity(self, open_positions: dict, get_price_fn) -> float:
        with self._lock:
            total = self.cash
        for sym, pos in open_positions.items():
            price = get_price_fn(sym)
            if price is None:
                total += pos["usdt_size"]
                continue
            mult = DEFAULT_LEVERAGE * pos["usdt_size"]
            upnl = ((price - pos["entry"]) / pos["entry"] * mult
                    if pos["direction"] == "LONG"
                    else (pos["entry"] - price) / pos["entry"] * mult)
            total += pos["usdt_size"] + upnl
        return total

    def reserve_margin(self, usdt_size: float) -> bool:
        with self._lock:
            if self.cash < usdt_size:
                return False
            self.cash -= usdt_size
            return True

    def release(self, usdt_size: float, pnl: float):
        with self._lock:
            self.cash         += usdt_size + pnl
            self.realized_pnl += pnl

    def save_equity_curve(self, equity: float):
        self.equity_history.append({"ts": ts_full(), "equity": round(equity, 4)})
        if len(self.equity_history) > 5000:
            self.equity_history = self.equity_history[-2500:]
        try:
            with open(EQUITY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.equity_history, f, indent=2)
        except Exception:
            pass


# =============================================================================
#  DAILY STATE
# =============================================================================

class DailyState:
    def __init__(self, paper_account: PaperAccount):
        self.today         = datetime.now().strftime("%Y-%m-%d")
        self.pnl           = 0.0
        self.wins          = 0
        self.losses        = 0
        self.paper_account = paper_account
        self._load()

    def _load(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("date") != self.today:
                return
            self.pnl    = float(d.get("pnl",    0.0))
            self.wins   = int(d.get("wins",     0))
            self.losses = int(d.get("losses",   0))
            if PAPER_MODE:
                cash = d.get("paper_cash")
                if cash is not None:
                    with self.paper_account._lock:
                        self.paper_account.cash         = float(cash)
                        self.paper_account.realized_pnl = float(d.get("paper_realized", 0.0))
            log(f"Restored: P&L=${self.pnl:+.2f} W:{self.wins}/L:{self.losses}", Y)
        except Exception:
            pass

    def save(self):
        try:
            d = {
                "date":    self.today,
                "pnl":     round(self.pnl, 4),
                "wins":    self.wins,
                "losses":  self.losses,
            }
            if PAPER_MODE:
                d["paper_cash"]     = round(self.paper_account.cash, 4)
                d["paper_realized"] = round(self.paper_account.realized_pnl, 4)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f)
        except Exception:
            pass

    def record(self, pnl_usd: float):
        self.pnl += pnl_usd
        if pnl_usd >= 0:
            self.wins   += 1
        else:
            self.losses += 1
        self.save()


# =============================================================================
#  SIGNAL
# =============================================================================

class Signal:
    SOURCE_POLYMARKET = "polymarket"
    SOURCE_NEWS       = "newsapi"
    SOURCE_TELEGRAM   = "telegram"
    SOURCE_GEMINI     = "gemini_auto"

    def __init__(self, symbol, direction, source, reason,
                 score=1, manual=False, size_override=None,
                 raw_event=None, force=False):
        self.symbol        = symbol
        self.direction     = direction
        self.source        = source
        self.reason        = reason
        self.score         = score
        self.manual        = manual
        self.size_override = size_override
        self.raw_event     = raw_event or {}
        self.force         = force
        self.ts            = time.time()
        self.id            = hashlib.md5(
            f"{symbol}{direction}{source}{self.ts}".encode()
        ).hexdigest()[:12]


# =============================================================================
#  SIGNAL QUEUE
# =============================================================================

class SignalQueue:
    STALE_SEC = 600

    def __init__(self):
        self._lock    = threading.Lock()
        self._pending = defaultdict(list)
        self._manual  = []

    def add(self, sig: Signal):
        with self._lock:
            if sig.manual:
                self._manual.append(sig)
            else:
                self._pending[sig.symbol].append(sig)

    def pop_manual(self) -> list:
        with self._lock:
            items = list(self._manual)
            self._manual.clear()
            return items

    def flush_merged(self) -> list:
        results = []
        now = time.time()
        with self._lock:
            for symbol, signals in list(self._pending.items()):
                signals = [s for s in signals if now - s.ts < self.STALE_SEC]
                self._pending[symbol] = signals
                if not signals:
                    continue
                for direction in ("LONG", "SHORT"):
                    group = [s for s in signals if s.direction == direction]
                    if not group:
                        continue
                    results.append({
                        "symbol":     symbol,
                        "direction":  direction,
                        "score":      sum(s.score for s in group),
                        "reasons":    [s.reason for s in group],
                        "sources":    list({s.source for s in group}),
                        "raw_events": [s.raw_event for s in group if s.raw_event],
                    })
                    self._pending[symbol] = [
                        s for s in signals if s.direction != direction
                    ]
        return results

    def pending_count(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._pending.values())


# =============================================================================
#  MARKET DATA
# =============================================================================

class MarketData:
    def __init__(self):
        self._session    = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})
        self._cache_lock = threading.Lock()
        self._cache      = {}
        self._base       = BINANCE_FAPI_TEST if USE_TESTNET else BINANCE_FAPI_MAIN

    def _get(self, path, params=None, timeout=6, cache_ttl=5):
        key = path + str(sorted((params or {}).items()))
        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and now - hit[1] < cache_ttl:
                return hit[0]
        try:
            r = self._session.get(
                f"{self._base}{path}", params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            with self._cache_lock:
                self._cache[key] = (data, now)
            return data
        except Exception as e:
            log(f"[MarketData] {path}: {e}", R, "DEBUG")
            with self._cache_lock:
                hit = self._cache.get(key)
                if hit:
                    return hit[0]
            return None

    def mark_price(self, symbol) -> Optional[float]:
        d = self._get("/fapi/v1/premiumIndex", {"symbol": symbol},
                      cache_ttl=PRICE_CACHE_TTL)
        if d:
            try:
                return float(d["markPrice"])
            except Exception:
                pass
        d2 = self._get("/fapi/v1/ticker/price", {"symbol": symbol},
                       cache_ttl=PRICE_CACHE_TTL)
        try:
            return float(d2["price"])
        except Exception:
            return None

    def klines(self, symbol, interval="1h", limit=50) -> list:
        data = self._get("/fapi/v1/klines",
                         {"symbol": symbol, "interval": interval, "limit": limit},
                         cache_ttl=KLINE_CACHE_TTL)
        if not data:
            return []
        return [{"open": float(k[1]), "high": float(k[2]),
                 "low":  float(k[3]), "close": float(k[4]),
                 "volume": float(k[5])} for k in data]

    def funding_rate(self, symbol) -> Optional[float]:
        d = self._get("/fapi/v1/premiumIndex", {"symbol": symbol},
                      cache_ttl=PRICE_CACHE_TTL)
        try:
            return float(d["lastFundingRate"])
        except Exception:
            return None

    def order_book_imbalance(self, symbol, depth=10) -> Optional[float]:
        d = self._get("/fapi/v1/depth", {"symbol": symbol, "limit": depth},
                      cache_ttl=5)
        try:
            bids  = sum(float(b[1]) for b in d["bids"])
            asks  = sum(float(a[1]) for a in d["asks"])
            total = bids + asks
            return (bids - asks) / total if total > 0 else None
        except Exception:
            return None

    def ema(self, closes, period=20) -> float:
        if not closes or len(closes) < period:
            return closes[-1] if closes else 0.0
        k = 2 / (period + 1)
        e = closes[0]
        for c in closes[1:]:
            e = c * k + e * (1 - k)
        return e

    def momentum_direction(self, symbol, interval="1h") -> Optional[str]:
        candles = self.klines(symbol, interval, 30)
        if len(candles) < 22:
            return None
        closes  = [c["close"] for c in candles]
        ema_val = self.ema(closes, 20)
        last    = closes[-1]
        if last > ema_val * 1.001:
            return "LONG"
        if last < ema_val * 0.999:
            return "SHORT"
        return None

    def atr(self, symbol, period=ATR_PERIOD) -> Optional[float]:
        candles = self.klines(symbol, "1h", period + 5)
        if len(candles) < period + 1:
            return None
        trs = []
        for i in range(1, len(candles)):
            hi = candles[i]["high"]
            lo = candles[i]["low"]
            pc = candles[i - 1]["close"]
            trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
        return sum(trs[-period:]) / period

    def rsi(self, symbol, period=RSI_PERIOD) -> Optional[float]:
        return self._rsi_calc(symbol, "1h", period)

    def rsi_fast(self, symbol, period=RSI_PERIOD) -> Optional[float]:
        return self._rsi_calc(symbol, "5m", period)

    def _rsi_calc(self, symbol, interval, period) -> Optional[float]:
        candles = self.klines(symbol, interval, period + 5)
        if len(candles) < period + 2:
            return None
        closes = [c["close"] for c in candles]
        gains  = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
        losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
        ag = sum(gains[:period])  / period
        al = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            ag = (ag * (period - 1) + gains[i])  / period
            al = (al * (period - 1) + losses[i]) / period
        if al == 0:
            return 100.0
        return 100 - (100 / (1 + ag / al))

    def vwap(self, symbol) -> Optional[float]:
        candles = self.klines(symbol, "1h", 24)
        if not candles:
            return None
        pv = sum(((c["high"] + c["low"] + c["close"]) / 3) * c["volume"]
                 for c in candles)
        vv = sum(c["volume"] for c in candles)
        return pv / vv if vv > 0 else None

    def volatility_ratio(self, symbol) -> Optional[float]:
        candles = self.klines(symbol, "1h", VOL_ATR_LOOKBACK + ATR_PERIOD + 5)
        if len(candles) < VOL_ATR_LOOKBACK + ATR_PERIOD:
            return None
        atrs = []
        for i in range(ATR_PERIOD, len(candles)):
            window = candles[i - ATR_PERIOD:i]
            prev   = candles[i - ATR_PERIOD - 1] if i > ATR_PERIOD else window[0]
            trs    = [max(w["high"] - w["low"],
                          abs(w["high"] - prev["close"]),
                          abs(w["low"]  - prev["close"])) for w in window]
            atrs.append(sum(trs) / ATR_PERIOD)
        if not atrs:
            return None
        avg = sum(atrs[-VOL_ATR_LOOKBACK:]) / min(len(atrs), VOL_ATR_LOOKBACK)
        return atrs[-1] / avg if avg > 0 else 1.0

    def breakout_direction(self, symbol) -> Optional[str]:
        candles = self.klines(symbol, "1h", BREAKOUT_PERIOD + 1)
        if len(candles) < BREAKOUT_PERIOD + 1:
            return None
        highs = [c["high"] for c in candles[:-1]]
        lows  = [c["low"]  for c in candles[:-1]]
        last  = candles[-1]["close"]
        if last > max(highs[-BREAKOUT_PERIOD:]):
            return "LONG"
        if last < min(lows[-BREAKOUT_PERIOD:]):
            return "SHORT"
        return None

    def volume_confirmed(self, symbol) -> bool:
        candles = self.klines(symbol, "1h", 22)
        if len(candles) < 22:
            return True
        vols    = [c["volume"] for c in candles]
        avg_vol = sum(vols[-20:]) / 20
        return vols[-1] >= avg_vol * VOLUME_SPIKE_MULT

    def get_market_context(self, symbol) -> dict:
        return {
            "symbol":               symbol,
            "price":                self.mark_price(symbol) or 0.0,
            "momentum":             self.momentum_direction(symbol),
            "funding_rate":         self.funding_rate(symbol),
            "order_book_imbalance": self.order_book_imbalance(symbol),
            "rsi":                  self.rsi(symbol),
            "vwap":                 self.vwap(symbol),
            "volatility_ratio":     self.volatility_ratio(symbol),
            "breakout":             self.breakout_direction(symbol),
        }

    def confluence_bonus(self, symbol, direction) -> int:
        bonus = 0
        try:
            if self.momentum_direction(symbol) == direction:
                bonus += 1
        except Exception:
            pass
        try:
            fr = self.funding_rate(symbol)
            if fr is not None:
                if direction == "LONG"  and fr < -0.0008: bonus += 1
                if direction == "SHORT" and fr >  0.0008: bonus += 1
        except Exception:
            pass
        try:
            obi = self.order_book_imbalance(symbol)
            if obi is not None:
                if direction == "LONG"  and obi >  0.10: bonus += 1
                if direction == "SHORT" and obi < -0.10: bonus += 1
        except Exception:
            pass
        return bonus


# =============================================================================
#  STRATEGY ENGINE
# =============================================================================

class StrategyEngine:
    def __init__(self, mkt: MarketData):
        self.mkt = mkt

    def evaluate(self, symbol, direction, equity) -> dict:
        score_bonus  = 0
        blocked      = False
        block_reason = ""
        filters      = {}

        # RSI
        if RSI_FILTER_ENABLED:
            rsi = self.mkt.rsi(symbol)
            filters["rsi"] = round(rsi, 1) if rsi is not None else None
            if rsi is not None:
                if direction == "LONG"  and rsi > RSI_OVERBOUGHT:
                    blocked = True; block_reason = f"RSI {rsi:.0f} overbought"
                elif direction == "SHORT" and rsi < RSI_OVERSOLD:
                    blocked = True; block_reason = f"RSI {rsi:.0f} oversold"
                elif direction == "LONG"  and rsi < 55: score_bonus += 1
                elif direction == "SHORT" and rsi > 45: score_bonus += 1

        if blocked:
            return {"score_bonus": 0, "blocked": True, "block_reason": block_reason,
                    "filters": filters, "position_size": MIN_TRADE_USDT}

        # VWAP
        if VWAP_FILTER_ENABLED:
            price  = self.mkt.mark_price(symbol) or 0.0
            vwap_v = self.mkt.vwap(symbol)
            filters["vwap"] = round(vwap_v, 4) if vwap_v else None
            if vwap_v and price > 0:
                if direction == "LONG":
                    if price > vwap_v:                     score_bonus += 1
                    elif price < vwap_v * (1 - VWAP_BLOCK_PCT): score_bonus -= 1
                else:
                    if price < vwap_v:                     score_bonus += 1
                    elif price > vwap_v * (1 + VWAP_BLOCK_PCT): score_bonus -= 1

        # 4h MTF
        if MTF_FILTER_ENABLED:
            mom_4h = self.mkt.momentum_direction(symbol, MTF_INTERVAL)
            filters["mtf_4h"] = mom_4h
            if mom_4h is not None:
                if mom_4h == direction:   score_bonus += 2
                else:                     score_bonus -= 1

        # Session
        sess_ok, sess_name = in_trading_session()
        filters["session"] = sess_name
        if sess_ok:
            score_bonus += 1

        # Volatility
        if VOL_FILTER_ENABLED:
            vol_r = self.mkt.volatility_ratio(symbol)
            filters["vol_ratio"] = round(vol_r, 2) if vol_r else None
            if vol_r is not None:
                if vol_r < VOL_MIN_RATIO:
                    blocked = True
                    block_reason = f"Volatility too low ({vol_r:.2f})"
                elif vol_r > 1.5:
                    score_bonus += 1

        if blocked:
            return {"score_bonus": 0, "blocked": True, "block_reason": block_reason,
                    "filters": filters, "position_size": MIN_TRADE_USDT}

        # Breakout
        if BREAKOUT_ENABLED:
            brk = self.mkt.breakout_direction(symbol)
            filters["breakout"] = brk
            if brk is not None:
                if brk == direction:   score_bonus += 2
                else:                  score_bonus -= 1

        # Volume
        if VOLUME_CONFIRM_ENABLED:
            vol_ok = self.mkt.volume_confirmed(symbol)
            filters["vol_spike"] = vol_ok
            if vol_ok:
                score_bonus += 1

        # Momentum 1h
        mom = self.mkt.momentum_direction(symbol)
        filters["momentum_1h"] = mom
        if mom is not None and mom == direction:
            score_bonus += 1

        # Dynamic sizing: risk 1% of equity
        sl_pct        = FIXED_SL_PCT / 100
        risk_usdt     = equity * (RISK_PER_TRADE_PCT / 100)
        size          = risk_usdt / (DEFAULT_LEVERAGE * sl_pct)
        position_size = round(clamp(size, MIN_TRADE_USDT, MAX_TRADE_USDT), 2)
        filters["position_size"] = position_size

        return {
            "score_bonus":   max(0, score_bonus),
            "blocked":       False,
            "block_reason":  "",
            "filters":       filters,
            "position_size": position_size,
        }

    def correlation_blocked(self, symbol, direction, open_positions, equity) -> tuple:
        if direction == "SHORT":
            return False, ""
        for grp_name, grp_syms in CORRELATION_GROUPS.items():
            if symbol not in grp_syms:
                continue
            exposure = sum(p["usdt_size"] for sym, p in open_positions.items()
                           if sym in grp_syms and p["direction"] == "LONG")
            limit = equity * CORRELATION_LIMIT_PCT
            if exposure >= limit:
                return True, f"{grp_name}: ${exposure:.0f} >= ${limit:.0f}"
        return False, ""


# =============================================================================
#  GEMINI ENGINE
# =============================================================================

class GeminiEngine:
    def __init__(self):
        self.ok          = bool(GEMINI_KEY)
        self.model       = None
        self._cache_lock = threading.Lock()
        self._cache      = {}
        self._rate_lock  = threading.Lock()
        self._last_call  = 0.0

        if not self.ok:
            log("[Gemini] No key — get free at aistudio.google.com", R)
        else:
            try:
                genai.configure(api_key=GEMINI_KEY)
                self.model = genai.GenerativeModel(GEMINI_MODEL)
                log(f"[Gemini] Ready ({GEMINI_MODEL})", G)
            except Exception as e:
                log(f"[Gemini] Init error: {e}", R)
                self.ok = False

    def _rate_wait(self):
        with self._rate_lock:
            gap = time.time() - self._last_call
            if gap < GEMINI_MIN_CALL_GAP:
                time.sleep(GEMINI_MIN_CALL_GAP - gap)
            self._last_call = time.time()

    def _score_bonus(self, signal, confidence) -> int:
        if signal == "IGNORE":
            return 0
        if confidence >= GEMINI_HIGH_CONF:
            return 3
        if confidence >= GEMINI_MID_CONF:
            return 1
        return 0

    def _call_api(self, prompt) -> Optional[str]:
        if not self.ok or not self.model:
            return None
        self._rate_wait()
        try:
            resp = self.model.generate_content(prompt)
            return resp.text.strip() if resp.text else None
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                # FIX: was sleeping 30s (frozen the whole bot 2939 times!)
                # Now: increment backoff, log once, return None immediately
                # The _rate_wait() will space out the next call automatically
                with self._rate_lock:
                    self._last_call = time.time() + 45  # push next call 45s forward
                log("[Gemini] Rate limit — next call in 45s (bot continues running)", Y)
            else:
                log(f"[Gemini] API error: {e}", R, "DEBUG")
            return None

    def _parse_json(self, raw) -> Optional[dict]:
        if not raw:
            return None
        try:
            raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
            m   = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            if m:
                raw = m.group(0)
            return json.loads(raw)
        except Exception:
            return None

    def analyse(self, symbol, direction, ctx, raw_events, reasons,
                skip_if_source=None) -> dict:
        fallback = {"signal": direction, "confidence": 50,
                    "reason": "Gemini unavailable", "score_bonus": 0}
        if not self.ok:
            return fallback

        # Reuse cached Gemini auto result if source is Gemini
        if skip_if_source == Signal.SOURCE_GEMINI:
            for ev in raw_events:
                if ev.get("type") == "gemini_auto":
                    conf = int(ev.get("confidence", 50))
                    sig  = direction
                    return {"signal": sig, "confidence": conf,
                            "reason": ev.get("reason", "Gemini auto"),
                            "score_bonus": self._score_bonus(sig, conf)}

        rsi    = ctx.get("rsi")
        fr     = ctx.get("funding_rate")
        obi    = ctx.get("order_book_imbalance")
        vwap_v = ctx.get("vwap")
        price  = ctx.get("price", 0)

        events_txt = ""
        for ev in raw_events[:2]:
            if ev.get("type") == "polymarket":
                events_txt += f"POLY: {ev.get('question','')[:55]} {ev.get('prob_change',0):+.1%}\n"
            elif ev.get("type") == "news":
                events_txt += f"NEWS: {ev.get('keyword','')} {ev.get('title','')[:55]}\n"

        cache_key = hashlib.md5(
            f"{symbol}{direction}{reasons[0] if reasons else ''}".encode()
        ).hexdigest()

        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached:
                result, expiry = cached
                if time.time() < expiry:
                    return result

        prompt = f"""Crypto futures signal. Evaluate then pick LONG/SHORT/IGNORE.
{symbol} {direction} @ ${price:,.2f}
{events_txt if events_txt else 'Technical analysis'}
RSI:{f'{rsi:.0f}' if rsi else 'N/A'} Fund:{f'{fr:.4f}' if fr else 'N/A'} OB:{f'{obi:.2f}' if obi else 'N/A'}
VWAP:{'above' if price>(vwap_v or 0) else 'below'} Trend:{ctx.get('momentum') or 'neutral'}
IGNORE only if RSI extreme OR very strong contradiction. Otherwise lean toward direction.
JSON only: {{"signal":"LONG","confidence":75,"reason":"<60 chars"}}"""

        raw  = self._call_api(prompt)
        data = self._parse_json(raw)

        if not data:
            return fallback

        signal_out = str(data.get("signal", direction)).upper()
        confidence = int(data.get("confidence", 50))
        reason     = str(data.get("reason", ""))[:120]
        if signal_out not in ("LONG", "SHORT", "IGNORE"):
            signal_out = direction

        result = {"signal": signal_out, "confidence": confidence,
                  "reason": reason, "score_bonus": self._score_bonus(signal_out, confidence)}
        log(f"[Gemini] {symbol} {signal_out} conf={confidence}% | {reason}", M)

        with self._cache_lock:
            self._cache[cache_key] = (result, time.time() + 120)
        return result

    def autonomous_scan(self, symbol, ctx, news_headlines, poly_sent) -> dict:
        if not self.ok:
            return {"signal": "IGNORE", "confidence": 0, "reason": "no key"}

        cache_key = hashlib.md5(
            f"auto_{symbol}_{int(time.time()//GEMINI_AUTO_SCAN_SEC)}".encode()
        ).hexdigest()

        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached:
                result, expiry = cached
                if time.time() < expiry:
                    return result

        rsi    = ctx.get("rsi")
        price  = ctx.get("price", 0)
        vwap_v = ctx.get("vwap")
        fr     = ctx.get("funding_rate")
        obi    = ctx.get("order_book_imbalance")
        mom    = ctx.get("momentum")
        vol_r  = ctx.get("volatility_ratio")
        brk    = ctx.get("breakout")
        news_txt = "\n".join(
            f"  [{a.get('title','')[:60]}]" for a in news_headlines[:2])

        prompt = f"""Autonomous crypto AI. Scan {symbol}. Pick LONG/SHORT/IGNORE.
${price:,.2f} trend:{mom or 'neutral'} RSI:{f'{rsi:.0f}' if rsi else 'N/A'}
VWAP:{'above' if price>(vwap_v or 0) else 'below'} fund:{f'{fr:.4f}' if fr else 'N/A'}
OB:{f'{obi:.2f}' if obi else 'N/A'} vol:{f'{vol_r:.1f}' if vol_r else 'N/A'}x break:{brk or 'none'}
Poly:{poly_sent or 'neutral'} News:{news_txt if news_txt else 'none'}
2+ indicators same direction -> confidence>=60. IGNORE only for RSI>80(L) or RSI<20(S).
JSON: {{"signal":"LONG","confidence":72,"reason":"<60 chars"}}"""

        raw  = self._call_api(prompt)
        data = self._parse_json(raw)

        if not data:
            return {"signal": "IGNORE", "confidence": 0, "reason": "parse error"}

        result = {"signal":     str(data.get("signal", "IGNORE")).upper(),
                  "confidence": int(data.get("confidence", 0)),
                  "reason":     str(data.get("reason", ""))[:120]}

        with self._cache_lock:
            self._cache[cache_key] = (result, time.time() + GEMINI_AUTO_SCAN_SEC)
        return result

    def smart_exit_check(self, pos, price, ctx, recent_news, poly_sent) -> str:
        if not self.ok:
            return "HOLD"
        direction = pos["direction"]
        entry     = pos["entry"]
        pnl_pct   = ((price - entry) / entry * 100 if direction == "LONG"
                     else (entry - price) / entry * 100)
        age_min   = (time.time() - pos["ts"]) / 60
        rsi       = ctx.get("rsi")
        mom       = ctx.get("momentum")
        news_txt  = "; ".join(a.get("title", "")[:40] for a in recent_news[:2])

        prompt = f"""Open position check. {pos['symbol']} {direction}
Entry:${entry:,.2f} Now:${price:,.2f} P&L:{pnl_pct:+.2f}% Age:{age_min:.0f}m
Trend:{mom} RSI:{f'{rsi:.0f}' if rsi else 'N/A'} Poly:{poly_sent or 'neutral'}
News:{news_txt or 'none'}
EXIT only if momentum strongly flipped and losing money. Otherwise HOLD.
JSON: {{"action":"HOLD","confidence":70,"reason":"<50 chars"}}"""

        cache_key = hashlib.md5(
            f"exit_{pos['symbol']}_{int(time.time()//SMART_EXIT_INTERVAL)}".encode()
        ).hexdigest()

        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached:
                result, expiry = cached
                if time.time() < expiry:
                    action = str(result.get("action", "HOLD")).upper()
                    return action if result.get("confidence", 0) >= 65 else "HOLD"

        raw  = self._call_api(prompt)
        data = self._parse_json(raw)

        if not data:
            return "HOLD"

        action = str(data.get("action", "HOLD")).upper()
        conf   = int(data.get("confidence", 0))
        reason = str(data.get("reason", ""))[:60]
        log(f"[SmartExit] {pos['symbol']}: {action} {conf}% | {reason}", M)

        with self._cache_lock:
            self._cache[cache_key] = (data, time.time() + SMART_EXIT_INTERVAL)

        return action if (action == "EXIT" and conf >= 65) else "HOLD"


# =============================================================================
#  GEMINI AUTO TRADER
# =============================================================================

class GeminiAutoTrader:
    def __init__(self, queue, gemini, mkt_data, poly, news):
        self.queue    = queue
        self.gemini   = gemini
        self.mkt      = mkt_data
        self.poly     = poly
        self.news     = news
        self._fired   = {}
        self._running = False
        self._sym_idx = 0

    def run_loop(self):
        if not GEMINI_AUTO_TRADE or not self.gemini.ok:
            log("[GeminiAuto] Disabled", Y)
            return
        self._running = True
        log(f"[GeminiAuto] Started — rotating symbols every {GEMINI_AUTO_SCAN_SEC}s "
            f"min_conf={GEMINI_AUTO_MIN_CONF}%", G)

        while self._running:
            try:
                all_news = self.news.get_all_recent() if self.news.ok else []
                # FIX: rotate 3 symbols per cycle (was 4)
                # 7 symbols ÷ 3 per cycle = full rotation every ~58s
                # Each scan = 1 Gemini call + 3s gap = safe under free tier
                for _ in range(3):
                    if not self._running:
                        break
                    symbol = GEMINI_AUTO_SYMBOLS[self._sym_idx % len(GEMINI_AUTO_SYMBOLS)]
                    self._sym_idx += 1
                    try:
                        self._scan_one(symbol, all_news)
                    except Exception as e:
                        log(f"[GeminiAuto] {symbol}: {e}", R, "DEBUG")
            except Exception as e:
                log(f"[GeminiAuto] Loop: {e}", R)
            time.sleep(GEMINI_AUTO_SCAN_SEC)

    def _scan_one(self, symbol, all_news):
        now       = time.time()
        ctx       = self.mkt.get_market_context(symbol)
        poly_sent = self.poly.get_sentiment_for_symbol(symbol)
        sym_kw    = {
            "BTCUSDT":  ["bitcoin", "btc"],
            "ETHUSDT":  ["ethereum", "eth"],
            "SOLUSDT":  ["solana", "sol"],
            "XRPUSDT":  ["xrp", "ripple"],
            "DOGEUSDT": ["dogecoin", "doge"],
            "BNBUSDT":  ["bnb"],
            "AVAXUSDT": ["avalanche", "avax"],
            "LINKUSDT": ["chainlink", "link"],
        }
        kws      = sym_kw.get(symbol, [symbol.replace("USDT", "").lower()])
        sym_news = [a for a in all_news
                    if any(k in (a.get("title","") + a.get("description","")).lower()
                           for k in kws)]

        result     = self.gemini.autonomous_scan(symbol, ctx, sym_news, poly_sent)
        signal_out = result.get("signal", "IGNORE")
        confidence = result.get("confidence", 0)
        reason     = result.get("reason", "")

        if signal_out == "IGNORE" or confidence < GEMINI_AUTO_MIN_CONF:
            return

        fire_key = f"{symbol}_{signal_out}"
        if now - self._fired.get(fire_key, 0) < GEMINI_SYMBOL_COOLDOWN:
            return

        score = 3 if confidence >= 75 else 2
        log(f"[GeminiAuto] SIGNAL: {symbol} {signal_out} {confidence}% "
            f"score={score} | {reason}", M)

        self.queue.add(Signal(
            symbol    = symbol,
            direction = signal_out,
            source    = Signal.SOURCE_GEMINI,
            reason    = f"Gemini Auto [{confidence}%]: {reason}",
            score     = score,
            raw_event = {"type": "gemini_auto", "confidence": confidence,
                         "reason": reason, "direction": signal_out,
                         "momentum": ctx.get("momentum"), "rsi": ctx.get("rsi")},
        ))
        self._fired[fire_key] = now

    def stop(self):
        self._running = False


# =============================================================================
#  POLYMARKET SOURCE
# =============================================================================

class PolymarketSource:
    def __init__(self, queue: SignalQueue):
        self.queue    = queue
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        self._price_history = defaultdict(lambda: deque(maxlen=120))
        self._known_markets = {}
        self._fired         = {}
        self._lock          = threading.Lock()
        self._markets       = []
        self._running       = False

    def _fetch_markets(self) -> list:
        try:
            r = self._session.get(f"{GAMMA_API}/markets",
                params={"limit": POLY_FETCH_LIMIT, "active": "true",
                        "closed": "false", "archived": "false"},
                timeout=15)
            r.raise_for_status()
            raw = r.json()
            markets = raw if isinstance(raw, list) else (
                raw.get("data") or raw.get("markets") or [])
            markets = [m for m in markets if isinstance(m, dict)]
        except Exception as e:
            log(f"[Polymarket] Fetch: {e}", R)
            return []
        crypto_kw = set(SYMBOL_MAP.keys()) | {
            "fed", "rate", "inflation", "etf", "approve", "crypto",
            "interest", "cpi", "gdp", "bitcoin", "ethereum", "halving", "sec"}
        return [m for m in markets
                if any(k in str(m.get("question", "")).lower() for k in crypto_kw)]

    def get_sentiment_for_symbol(self, symbol) -> Optional[str]:
        now = time.time()
        ls = ss = 0
        with self._lock:
            for cid, history in self._price_history.items():
                m = self._known_markets.get(cid)
                if not m:
                    continue
                sym = self._extract_symbol(str(m.get("question", "")).lower())
                if sym != symbol:
                    continue
                window = [(t, p) for t, p in history if now - t <= SPIKE_WINDOW_SEC * 2]
                if len(window) < 2:
                    continue
                chg = window[-1][1] - window[0][1]
                if chg > 0.02:   ls += 1
                elif chg < -0.02: ss += 1
        if ls > ss:  return "LONG"
        if ss > ls:  return "SHORT"
        return None

    def _update_prices(self):
        now = time.time()
        for m in self._markets:
            cid = m.get("conditionId") or m.get("id", "")
            if not cid:
                continue
            try:
                op = m.get("outcomePrices", [])
                if not op:
                    continue
                with self._lock:
                    self._known_markets[cid] = m
                    self._price_history[cid].append((now, float(op[0])))
            except Exception:
                pass

    def _detect_and_queue(self):
        now    = time.time()
        spikes = []
        with self._lock:
            for cid, history in self._price_history.items():
                if len(history) < 2:
                    continue
                window = [(t, p) for t, p in history if now - t <= SPIKE_WINDOW_SEC]
                if len(window) < 2:
                    continue
                chg    = window[-1][1] - window[0][1]
                abs_c  = abs(chg)
                if abs_c < SPIKE_THRESHOLD:
                    continue
                latest = window[-1][1]
                if latest > 0.93 or latest < 0.07:
                    continue
                m = self._known_markets.get(cid)
                if not m:
                    continue
                symbol = self._extract_symbol(str(m.get("question", "")).lower())
                if not symbol:
                    continue
                key = hashlib.md5(f"{cid}{'L' if chg>0 else 'S'}".encode()).hexdigest()
                if self._fired.get(key, 0) > now:
                    continue
                direction = "LONG" if chg > 0 else "SHORT"
                score = 3 if abs_c / 0.20 >= 0.5 else 2
                spikes.append((key, Signal(
                    symbol    = symbol,
                    direction = direction,
                    source    = Signal.SOURCE_POLYMARKET,
                    reason    = f"Polymarket {abs_c:+.1%} ({str(m.get('question',''))[:50]})",
                    score     = score,
                    raw_event = {"type": "polymarket", "question": m.get("question",""),
                                 "probability": latest, "prob_change": chg, "symbol": symbol},
                )))
        for key, sig in spikes:
            self.queue.add(sig)
            self._fired[key] = now + 300
            log(f"[Polymarket] {sig.symbol} {sig.direction} score={sig.score}", Y)

    def inject_test_spike(self, symbol="BTCUSDT", direction="LONG"):
        now      = time.time()
        cid      = f"TEST_{symbol}"
        new_p    = 0.55 if direction == "LONG" else 0.22
        fake     = {"conditionId": cid, "id": cid,
                    "question": "Will Bitcoin ETF be approved this month?",
                    "outcomePrices": [str(new_p), str(1-new_p)], "volume": "2500000"}
        with self._lock:
            self._known_markets[cid] = fake
            self._price_history[cid].append((now - SPIKE_WINDOW_SEC + 5, 0.38))
            self._price_history[cid].append((now, new_p))
        log(f"[Polymarket] TEST spike: {symbol} {direction}", Y)

    def _extract_symbol(self, question) -> Optional[str]:
        for kw, sym in SYMBOL_MAP.items():
            if kw in question:
                return sym
        return None

    def run_loop(self):
        self._running = True
        last_fetch    = 0.0
        log("[Polymarket] Started", G)
        while self._running:
            try:
                now = time.time()
                if now - last_fetch > 120:
                    fresh = self._fetch_markets()
                    if fresh:
                        self._markets = fresh
                        if last_fetch == 0:
                            log(f"[Polymarket] {len(fresh)} markets", G)
                    last_fetch = now
                if self._markets:
                    self._update_prices()
                    self._detect_and_queue()
            except Exception as e:
                log(f"[Polymarket] Loop: {e}", R)
            time.sleep(POLY_SCAN_INTERVAL)

    def stop(self):
        self._running = False


# =============================================================================
#  NEWSAPI SOURCE
# =============================================================================

class NewsSource:
    NEWS_QUERY = ("bitcoin OR ethereum OR crypto OR solana OR "
                  "SEC crypto OR Fed rate OR crypto ETF OR crypto hack OR crypto ban")

    def __init__(self, queue: SignalQueue):
        self.queue        = queue
        self.ok           = bool(NEWS_API_KEY)
        self._fired       = {}
        self._running     = False
        self._recent      = []
        self._recent_lock = threading.Lock()
        if not self.ok:
            log("[NewsAPI] No key — disabled.", Y)
        else:
            log("[NewsAPI] Ready.", G)

    def get_all_recent(self) -> list:
        with self._recent_lock:
            return list(self._recent)

    def get_sentiment_for_symbol(self, symbol) -> tuple:
        sym_kw = {
            "BTCUSDT":  ["bitcoin", "btc"],
            "ETHUSDT":  ["ethereum", "eth"],
            "SOLUSDT":  ["solana", "sol"],
            "XRPUSDT":  ["xrp", "ripple"],
            "DOGEUSDT": ["dogecoin", "doge"],
            "BNBUSDT":  ["bnb"],
            "ADAUSDT":  ["cardano", "ada"],
            "AVAXUSDT": ["avalanche", "avax"],
        }
        kws = sym_kw.get(symbol, [symbol.replace("USDT", "").lower()])
        with self._recent_lock:
            snap = list(self._recent)
        for a in snap:
            title = (a.get("title") or "").lower()
            if not any(k in title for k in kws):
                continue
            r = self._classify(title, (a.get("description") or "").lower())
            if r:
                return r[0], r[1], a.get("title", "")[:80]
        return None, 0, ""

    def _fetch_headlines(self) -> list:
        if not self.ok:
            return []
        try:
            r = requests.get(f"{NEWS_API_BASE}/everything",
                params={"q": self.NEWS_QUERY, "language": "en",
                        "sortBy": "publishedAt", "pageSize": 20,
                        "apiKey": NEWS_API_KEY},
                timeout=8)
            r.raise_for_status()
            articles = r.json().get("articles", [])
            cutoff   = time.time() - NEWS_LOOKBACK_MIN * 60
            fresh    = []
            for a in articles:
                pub = a.get("publishedAt", "")
                try:
                    dt = datetime.strptime(pub[:19], "%Y-%m-%dT%H:%M:%S")
                    if dt.replace(tzinfo=timezone.utc).timestamp() >= cutoff:
                        fresh.append(a)
                except Exception:
                    pass
            return fresh
        except Exception as e:
            log(f"[NewsAPI] Fetch: {e}", R, "DEBUG")
            return []

    def _classify(self, title, description) -> Optional[tuple]:
        text = title + " " + (description or "")
        for kw in BEARISH_KEYWORDS:
            if kw in text:
                s = 3 if any(x in text for x in
                             ["hack","ban","sec sues","bankruptcy","crash"]) else 2
                return "SHORT", s, kw
        for kw in BULLISH_KEYWORDS:
            if kw in text:
                s = 3 if any(x in text for x in
                             ["etf approved","rate cut","sec approves","bitcoin reserve"]) else 2
                return "LONG", s, kw
        return None

    def _symbol_from_headline(self, title) -> str:
        text = title.lower()
        priority = [("solana","sol","SOLUSDT"),("ethereum","eth","ETHUSDT"),
                    ("bitcoin","btc","BTCUSDT"),("ripple","xrp","XRPUSDT"),
                    ("dogecoin","doge","DOGEUSDT"),("cardano","ada","ADAUSDT"),
                    ("avalanche","avax","AVAXUSDT"),("chainlink","link","LINKUSDT")]
        for *kws, sym in priority:
            if any(k in text for k in kws):
                return sym
        return "BTCUSDT"

    def _scan_and_queue(self) -> int:
        articles = self._fetch_headlines()
        now = time.time()
        with self._recent_lock:
            self._recent = articles[:20]
        count = 0
        for a in articles:
            title = a.get("title") or ""
            if not title:
                continue
            r = self._classify(title.lower(), (a.get("description") or "").lower())
            if not r:
                continue
            direction, score, keyword = r
            symbol = self._symbol_from_headline(title)
            h_key  = hashlib.md5(title.encode()).hexdigest()
            if self._fired.get(h_key, 0) > now:
                continue
            self.queue.add(Signal(
                symbol    = symbol,
                direction = direction,
                source    = Signal.SOURCE_NEWS,
                reason    = f"NewsAPI [{keyword}]: {title[:75]}",
                score     = score,
                raw_event = {"type": "news", "title": title,
                             "keyword": keyword, "direction": direction},
            ))
            self._fired[h_key] = now + NEWS_SIGNAL_COOLDOWN
            count += 1
            log(f"[NewsAPI] {symbol} {direction} score={score} | {title[:50]}", B)
        return count

    def run_loop(self):
        self._running = True
        log("[NewsAPI] Started.", G)
        while self._running:
            try:
                c = self._scan_and_queue()
                if c:
                    log(f"[NewsAPI] {c} signal(s) queued", G)
            except Exception as e:
                log(f"[NewsAPI] Loop: {e}", R)
            time.sleep(NEWS_SCAN_INTERVAL)

    def stop(self):
        self._running = False


# =============================================================================
#  BINANCE FUTURES EXECUTOR  (FIX-LIVE-3: clear error messages)
# =============================================================================

class BinanceFutures:
    def __init__(self, mkt_data: MarketData, paper_account: PaperAccount):
        self.paper         = PAPER_MODE
        self.testnet       = USE_TESTNET
        self.client        = None
        self.md            = mkt_data
        self.paper_account = paper_account
        self._sym_info     = {}
        self._live_balance = 0.0
        self._connect()

    def _connect(self):
        if self.paper:
            log("[Binance] Running in PAPER mode — no real orders.", Y)
            return

        # [FIX-LIVE-3] Validate keys before connecting
        if not BINANCE_KEY or BINANCE_KEY == "YOUR_BINANCE_API_KEY_HERE":
            log("[Binance] ERROR: BINANCE_API_KEY not set in .env", R)
            log("[Binance] Get your key from binance.com -> Profile -> API Management", Y)
            log("[Binance] The bot will run in PAPER mode until keys are set.", Y)
            self.paper = True
            return

        if not BINANCE_SECRET or BINANCE_SECRET == "YOUR_BINANCE_API_SECRET_HERE":
            log("[Binance] ERROR: BINANCE_API_SECRET not set in .env", R)
            self.paper = True
            return

        try:
            log(f"[Binance] Connecting to {'TESTNET' if self.testnet else 'MAINNET'}...", B)
            self.client = BinanceClient(
                BINANCE_KEY, BINANCE_SECRET, testnet=self.testnet)
            self.client.futures_ping()
            net = "TESTNET" if self.testnet else "MAINNET"
            log(f"[Binance] Connected! ({net})", G)

            # Get and display real balance
            self._live_balance = self._fetch_live_balance()
            log(f"[Binance] Futures USDT balance: {G}{BRIGHT}${self._live_balance:,.2f}{RST}", G)

            if self._live_balance < MIN_TRADE_USDT:
                log(f"[Binance] WARNING: Balance ${self._live_balance:.2f} is very low "
                    f"(min trade size ${MIN_TRADE_USDT})", Y)

            self._prefetch_info()

        except BinanceAPIException as e:
            log(f"[Binance] API Error: {e}", R)
            log("[Binance] Common fixes:", Y)
            log("  1. Check your API key has 'Futures Trading' enabled", Y)
            log("  2. Check your IP is whitelisted (if you set IP restrictions)", Y)
            log("  3. Make sure BINANCE_TESTNET=false in .env for live trading", Y)
            log("[Binance] Falling back to PAPER mode.", R)
            self.paper = True
        except Exception as e:
            err = str(e).encode("ascii", errors="replace").decode("ascii")
            log(f"[Binance] Connection error: {err}", R)
            log("[Binance] Falling back to PAPER mode.", R)
            self.paper = True

    def _fetch_live_balance(self) -> float:
        if not self.client:
            return 0.0
        try:
            for b in self.client.futures_account_balance():
                if b["asset"] == "USDT":
                    return float(b["availableBalance"])
        except Exception as e:
            log(f"[Binance] Balance check error: {e}", R)
        return 0.0

    def _prefetch_info(self):
        try:
            info = self.client.futures_exchange_info()
            for s in info.get("symbols", []):
                sym = s["symbol"]
                if sym not in SYMBOL_MAP.values():
                    continue
                entry = {"step": 1.0, "min_qty": 0.0, "tick": 0.01}
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        entry["step"]    = float(f["stepSize"])
                        entry["min_qty"] = float(f["minQty"])
                    if f["filterType"] == "PRICE_FILTER":
                        entry["tick"]    = float(f["tickSize"])
                self._sym_info[sym] = entry
            log(f"[Binance] Prefetched {len(self._sym_info)} symbols", G)
        except Exception as e:
            log(f"[Binance] Symbol info error: {e}", Y)

    def get_price(self, symbol) -> Optional[float]:
        return self.md.mark_price(symbol)

    def get_balance(self) -> float:
        if self.paper:
            return self.paper_account.cash
        # [FIX-LIVE-5] Return real live balance
        return self._fetch_live_balance()

    def refresh_live_balance(self):
        if not self.paper:
            self._live_balance = self._fetch_live_balance()

    def _round_qty(self, symbol, raw) -> float:
        info = self._sym_info.get(symbol)
        if info:
            step = info["step"]
            qty  = math.floor(raw / step) * step
            dec  = len(f"{step:.10f}".rstrip("0").split(".")[-1])
            return max(round(qty, dec), info["min_qty"])
        if "BTC" in symbol: return round(raw, 3)
        if "ETH" in symbol: return round(raw, 2)
        if "SOL" in symbol: return round(raw, 1)
        return round(raw, 0)

    def _round_price(self, symbol, price) -> float:
        info = self._sym_info.get(symbol)
        if info:
            tick = info["tick"]
            dec  = len(f"{tick:.10f}".rstrip("0").split(".")[-1])
            return round(round(price / tick) * tick, dec)
        return round(price, 2)

    def _calc_tp_sl(self, symbol, price, direction):
        atr = self.md.atr(symbol) if USE_ATR_EXITS else None
        if atr and atr > 0:
            if direction == "LONG":
                tp1 = price + atr * ATR_TP1_MULT
                tp2 = price + atr * ATR_TP2_MULT
                sl  = price - atr * ATR_SL_MULT
            else:
                tp1 = price - atr * ATR_TP1_MULT
                tp2 = price - atr * ATR_TP2_MULT
                sl  = price + atr * ATR_SL_MULT
        else:
            if direction == "LONG":
                tp1 = price * (1 + FIXED_TP1_PCT / 100)
                tp2 = price * (1 + FIXED_TP2_PCT / 100)
                sl  = price * (1 - FIXED_SL_PCT / 100)
            else:
                tp1 = price * (1 - FIXED_TP1_PCT / 100)
                tp2 = price * (1 - FIXED_TP2_PCT / 100)
                sl  = price * (1 + FIXED_SL_PCT / 100)
        return (self._round_price(symbol, tp1),
                self._round_price(symbol, tp2),
                self._round_price(symbol, sl), atr)

    def open_position(self, symbol, direction, usdt_size):
        price = self.get_price(symbol)
        if not price:
            return None, None

        tp1, tp2, sl, atr = self._calc_tp_sl(symbol, price, direction)
        qty = self._round_qty(symbol, (usdt_size * DEFAULT_LEVERAGE) / price)
        if qty <= 0:
            log(f"[Binance] qty=0 for {symbol}", R)
            return None, None

        if self.paper:
            if not self.paper_account.reserve_margin(usdt_size):
                log(f"[Paper] Low balance: need ${usdt_size:.0f}, "
                    f"have ${self.paper_account.cash:.2f}", R)
                return None, None
            return ({"status": "PAPER_FILLED", "side": direction,
                     "qty": qty, "price": price, "symbol": symbol},
                    {"entry": price, "tp": tp1, "tp2": tp2,
                     "sl": sl, "atr": atr, "tp1_done": False})

        # LIVE ORDER
        try:
            self.client.futures_change_leverage(
                symbol=symbol, leverage=DEFAULT_LEVERAGE)
            side  = "BUY" if direction == "LONG" else "SELL"
            order = self.client.futures_create_order(
                symbol=symbol, side=side, type="MARKET", quantity=qty)
            actual_price = float(order.get("avgPrice", price) or price)
            tp1_a, tp2_a, sl_a, _ = self._calc_tp_sl(symbol, actual_price, direction)
            tp_side = "SELL" if direction == "LONG" else "BUY"
            # TP2 — close full position at target
            self.client.futures_create_order(
                symbol=symbol, side=tp_side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp2_a, closePosition=True, timeInForce="GTE_GTC")
            # SL — always on
            self.client.futures_create_order(
                symbol=symbol, side=tp_side,
                type="STOP_MARKET",
                stopPrice=sl_a, closePosition=True, timeInForce="GTE_GTC")
            log(f"[Binance] LIVE ORDER: {symbol} {direction} "
                f"qty={qty} @ ${actual_price:,.4f}  "
                f"TP2:${tp2_a:,.4f}  SL:${sl_a:,.4f}", G)
            return (order,
                    {"entry": actual_price, "tp": tp1_a, "tp2": tp2_a,
                     "sl": sl_a, "atr": atr, "tp1_done": False})
        except BinanceAPIException as e:
            log(f"[Binance] Order error [{symbol}]: {e}", R)
            return None, None

    def close_position(self, symbol, direction, qty,
                       usdt_size=0.0, pnl=0.0):
        if self.paper:
            self.paper_account.release(usdt_size, pnl)
            return True
        try:
            side = "SELL" if direction == "LONG" else "BUY"
            self.client.futures_create_order(
                symbol=symbol, side=side, type="MARKET",
                quantity=qty, reduceOnly=True)
            log(f"[Binance] LIVE CLOSE: {symbol} {direction} qty={qty}", G)
            return True
        except Exception as e:
            log(f"[Binance] Close error [{symbol}]: {e}", R)
            return False


# =============================================================================
#  POSITION TRACKER  (with Smart Profit Protection)
# =============================================================================

class PositionTracker:
    def __init__(self, binance: BinanceFutures, mkt_data: MarketData):
        self.binance        = binance
        self.mkt            = mkt_data
        self.positions      = {}
        self._lock          = threading.Lock()
        self._pending_exits = []
        self._pending_lock  = threading.Lock()
        self._pp_cache      = {}
        self._pp_cache_lock = threading.Lock()
        self.on_closed      = None

    def queue_smart_exit(self, symbol, action):
        with self._pending_lock:
            self._pending_exits.append((symbol, action))

    def pop_pending_exits(self) -> list:
        with self._pending_lock:
            items = list(self._pending_exits)
            self._pending_exits.clear()
        return items

    def add(self, symbol, direction, entry, tp, tp2, sl, atr,
            qty, usdt_size, reason, sources, score, ai_reason=""):
        with self._lock:
            self.positions[symbol] = {
                "symbol":    symbol, "direction": direction,
                "entry":     entry,  "tp":        tp,
                "tp2":       tp2,    "sl":         sl,
                "atr":       atr,    "qty":        qty,
                "usdt_size": usdt_size, "reason":  reason,
                "sources":   sources, "score":     score,
                "ai_reason": ai_reason, "ts":      time.time(),
                "peak_pnl":  0.0, "tp1_done":      False,
                "last_rsi5": None,
            }

    def _pnl(self, pos, price) -> float:
        mult = DEFAULT_LEVERAGE * pos["usdt_size"]
        if pos["direction"] == "LONG":
            return (price - pos["entry"]) / pos["entry"] * mult
        return (pos["entry"] - price) / pos["entry"] * mult

    def total_unrealized_pnl(self) -> float:
        total = 0.0
        with self._lock:
            snap = dict(self.positions)
        for sym, pos in snap.items():
            price = self.binance.get_price(sym)
            if price:
                total += self._pnl(pos, price)
        return total

    def get_open_positions(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.positions)

    def _get_pp_indicators(self, symbol) -> dict:
        now = time.time()
        with self._pp_cache_lock:
            hit = self._pp_cache.get(symbol)
            if hit and now - hit["ts"] < PROFIT_PROTECT_INDICATOR_TTL:
                return hit
        data = {"ts":  now,
                "mom": self.mkt.momentum_direction(symbol),
                "rsi5":self.mkt.rsi_fast(symbol),
                "obi": self.mkt.order_book_imbalance(symbol)}
        with self._pp_cache_lock:
            self._pp_cache[symbol] = data
        return data

    def _profit_protect_check(self, sym, pos_live, price, pnl_usd):
        """Returns (exit_reason, [reasons]) or (None, [])."""
        if not PROFIT_PROTECT_ENABLED:
            return None, []
        if pnl_usd < PROFIT_PROTECT_MIN_PNL_USD:
            return None, []

        direction = pos_live["direction"]
        peak      = pos_live["peak_pnl"]
        reasons   = []
        rev_score = 0

        # Giveback check
        if peak > 0:
            giveback = (peak - pnl_usd) / peak
            if giveback >= PROFIT_PROTECT_GIVEBACK_PCT:
                reasons.append(f"Gave back {giveback*100:.0f}% from peak "
                                f"(${peak:+.2f} -> ${pnl_usd:+.2f})")
                return "PROFIT PROTECT (giveback)", reasons

        # Indicator reversal
        ind  = self._get_pp_indicators(sym)
        mom  = ind["mom"]
        rsi5 = ind["rsi5"]
        obi  = ind["obi"]

        if mom is not None and mom != direction:
            rev_score += 1
            reasons.append(f"1h momentum flipped to {mom}")

        prev_rsi5 = pos_live.get("last_rsi5")
        if rsi5 is not None:
            if direction == "LONG":
                if prev_rsi5 and prev_rsi5 - rsi5 >= PROFIT_PROTECT_RSI_SWING and prev_rsi5 >= 60:
                    rev_score += 1
                    reasons.append(f"5m RSI rolling over {prev_rsi5:.0f}->{rsi5:.0f}")
            else:
                if prev_rsi5 and rsi5 - prev_rsi5 >= PROFIT_PROTECT_RSI_SWING and prev_rsi5 <= 40:
                    rev_score += 1
                    reasons.append(f"5m RSI bouncing {prev_rsi5:.0f}->{rsi5:.0f}")
            pos_live["last_rsi5"] = rsi5

        if obi is not None:
            if direction == "LONG"  and obi < -0.15:
                rev_score += 1
                reasons.append(f"Order book turned ask-heavy ({obi:.2f})")
            elif direction == "SHORT" and obi > 0.15:
                rev_score += 1
                reasons.append(f"Order book turned bid-heavy ({obi:.2f})")

        if rev_score >= PROFIT_PROTECT_REVERSAL_SCORE:
            reasons.insert(0, f"Reversal score {rev_score} while +${pnl_usd:.2f}")
            return "PROFIT PROTECT (reversal)", reasons

        return None, []

    def _close_one(self, symbol, exit_reason, daily_state: DailyState,
                   paper_account: PaperAccount, tg, journal_list, sym_perf,
                   protect_reasons=None, peak_pnl_at_close=None):
        with self._lock:
            pos = self.positions.get(symbol)
        if not pos:
            return None
        price   = self.binance.get_price(symbol) or pos["entry"]
        pnl_usd = self._pnl(pos, price)
        self.binance.close_position(symbol, pos["direction"], pos["qty"],
                                    usdt_size=pos["usdt_size"], pnl=pnl_usd)
        with self._lock:
            self.positions.pop(symbol, None)
        daily_state.record(pnl_usd)

        # Get equity for display (paper or live)
        if PAPER_MODE:
            open_pos = self.get_open_positions()
            equity   = paper_account.total_equity(open_pos, self.binance.get_price)
        else:
            self.binance.refresh_live_balance()
            equity = self.binance.get_balance()

        col = G if pnl_usd >= 0 else R
        log(f"  CLOSED {symbol} [{pos['direction']}]  "
            f"P&L:{col}${pnl_usd:+.2f}{RST}  "
            f"[{exit_reason}]  Balance:${equity:,.2f}", col)

        if tg:
            if protect_reasons:
                tg.notify_profit_protect(
                    symbol, pos["direction"], pnl_usd,
                    peak_pnl_at_close or pos["peak_pnl"],
                    protect_reasons, daily_state.pnl, equity)
            else:
                tg.notify_close(
                    symbol, pos["direction"], pnl_usd,
                    exit_reason, daily_state.pnl, equity)

        sym_perf[symbol]["wins" if pnl_usd >= 0 else "losses"] += 1
        sym_perf[symbol]["pnl"] += pnl_usd
        journal_list.append({
            "time":             ts_full(),
            "symbol":           symbol,
            "direction":        pos["direction"],
            "entry":            pos["entry"],
            "exit":             price,
            "pnl":              round(pnl_usd, 2),
            "reason":           exit_reason,
            "sources":          pos.get("sources", []),
            "score":            pos.get("score", 0),
            "ai_reason":        pos.get("ai_reason", ""),
            "equity":           round(equity, 2),
            "profit_protected": bool(protect_reasons),
            "live":             not PAPER_MODE,
        })
        if self.on_closed:
            self.on_closed(pnl_usd)
        return pnl_usd

    def check_all(self, daily_state, tg, paper_account,
                  journal_list, sym_perf) -> list:
        closed = []
        with self._lock:
            snap = copy.deepcopy(self.positions)

        for sym, pos in snap.items():
            price = self.binance.get_price(sym)
            if price is None:
                continue
            pnl_usd = self._pnl(pos, price)
            age_min = (time.time() - pos["ts"]) / 60

            with self._lock:
                if sym in self.positions and pnl_usd > self.positions[sym]["peak_pnl"]:
                    self.positions[sym]["peak_pnl"] = pnl_usd

            peak = max(pos["peak_pnl"], pnl_usd)

            # Smart Profit Protection (checked before TP/SL)
            if pnl_usd > 0:
                live_pos = self.positions.get(sym, pos)
                protect_reason, protect_reasons = self._profit_protect_check(
                    sym, live_pos, price, pnl_usd)
                if protect_reason:
                    r = self._close_one(sym, protect_reason, daily_state,
                                        paper_account, tg, journal_list, sym_perf,
                                        protect_reasons=protect_reasons,
                                        peak_pnl_at_close=peak)
                    if r is not None:
                        closed.append(sym)
                    continue

            # Partial TP1 (paper mode)
            if PAPER_MODE and not pos["tp1_done"]:
                tp1_hit = ((pos["direction"] == "LONG"  and price >= pos["tp"]) or
                           (pos["direction"] == "SHORT" and price <= pos["tp"]))
                if tp1_hit:
                    half_pnl = pnl_usd * 0.5
                    paper_account.release(pos["usdt_size"] * 0.5, half_pnl)
                    daily_state.pnl    += half_pnl
                    daily_state.wins   += 1
                    daily_state.save()
                    with self._lock:
                        if sym in self.positions:
                            self.positions[sym]["tp1_done"]   = True
                            self.positions[sym]["tp"]         = pos["tp2"]
                            self.positions[sym]["usdt_size"] *= 0.5
                            self.positions[sym]["qty"]       *= 0.5
                    log(f"  PARTIAL TP1 {sym} +${half_pnl:.2f}  TP2:${pos['tp2']:,.4f}", G)
                    if tg:
                        tg.send(f"[TP1] {sym} 50% closed +${half_pnl:.2f}  "
                                f"TP2:${pos['tp2']:,.4f}")
                    continue

            # Regular TP/SL/trailing
            exit_reason = None
            tp_val = pos.get("tp2", pos["tp"]) if pos.get("tp1_done") else pos["tp"]
            if pos["direction"] == "LONG"  and price >= tp_val:  exit_reason = "TAKE PROFIT"
            if pos["direction"] == "SHORT" and price <= tp_val:  exit_reason = "TAKE PROFIT"
            if pos["direction"] == "LONG"  and price <= pos["sl"]: exit_reason = "STOP LOSS"
            if pos["direction"] == "SHORT" and price >= pos["sl"]: exit_reason = "STOP LOSS"
            trig = pos["usdt_size"] * TRAILING_TRIGGER_PCT  / 100
            dist = pos["usdt_size"] * TRAILING_DISTANCE_PCT / 100
            if TRAILING_STOP and peak >= trig and pnl_usd <= peak - dist:
                exit_reason = "TRAILING STOP"
            if age_min > 240:
                exit_reason = "TIME EXIT (4h)"

            if exit_reason:
                r = self._close_one(sym, exit_reason, daily_state,
                                    paper_account, tg, journal_list, sym_perf)
                if r is not None:
                    closed.append(sym)
        return closed

    def force_close(self, symbol, paper_account, daily_state,
                    journal_list, sym_perf) -> str:
        pnl = self._close_one(symbol, "MANUAL CLOSE", daily_state,
                               paper_account, None, journal_list, sym_perf)
        bal = self.binance.get_balance()
        return (f"Closed {symbol}  P&L:${pnl:+.2f}  Balance:${bal:,.2f}"
                if pnl is not None else f"No position: {symbol}")

    def is_open(self, symbol) -> bool:
        with self._lock:
            return symbol in self.positions

    def count(self) -> int:
        with self._lock:
            return len(self.positions)

    def status_text(self, binance: BinanceFutures, daily_state: DailyState,
                    paper_account: PaperAccount) -> str:
        unrealized = self.total_unrealized_pnl()
        if PAPER_MODE:
            equity = paper_account.total_equity(
                self.get_open_positions(), binance.get_price)
            bal_line = (f"Cash: ${paper_account.cash:,.2f}  "
                        f"Float: ${unrealized:+.2f}  Equity: ${equity:,.2f}")
        else:
            bal = binance.get_balance()
            bal_line = f"Live USDT balance: ${bal:,.2f}  Float: ${unrealized:+.2f}"

        with self._lock:
            snap = copy.deepcopy(self.positions)

        lines = [
            f"Day P&L: ${daily_state.pnl:+.2f}  "
            f"W:{daily_state.wins}/L:{daily_state.losses}",
            bal_line,
        ]
        if snap:
            lines.append(f"\nOpen ({len(snap)}):")
            for sym, p in snap.items():
                price   = binance.get_price(sym) or p["entry"]
                pnl_usd = self._pnl(p, price)
                age     = int((time.time() - p["ts"]) / 60)
                peak    = p.get("peak_pnl", 0.0)
                pp_tag  = f"  [PP peak:${peak:+.2f}]" if (PROFIT_PROTECT_ENABLED and pnl_usd > 0) else ""
                lines.append(f"  {sym} {p['direction']}  "
                              f"in:${p['entry']:,.4f}  now:${price:,.4f}  "
                              f"P&L:${pnl_usd:+.2f}  {age}m{pp_tag}")
        else:
            lines.append("No open positions.")
        return "\n".join(lines)


# =============================================================================
#  SMART EXIT MONITOR
# =============================================================================

class SmartExitMonitor:
    def __init__(self, tracker: PositionTracker, gemini: GeminiEngine,
                 mkt_data: MarketData, news: NewsSource, poly: PolymarketSource):
        self.tracker  = tracker
        self.gemini   = gemini
        self.mkt      = mkt_data
        self.news     = news
        self.poly     = poly
        self._running = False

    def run_loop(self):
        if not SMART_EXIT_ENABLED or not self.gemini.ok:
            log("[SmartExit] Disabled", Y)
            return
        self._running = True
        log(f"[SmartExit] Monitoring every {SMART_EXIT_INTERVAL}s", G)
        while self._running:
            try:
                self._check_all()
            except Exception as e:
                log(f"[SmartExit] Error: {e}", R, "DEBUG")
            time.sleep(SMART_EXIT_INTERVAL)

    def _check_all(self):
        with self.tracker._lock:
            snap = copy.deepcopy(self.tracker.positions)
        if not snap:
            return
        all_news = self.news.get_all_recent() if self.news.ok else []
        now      = time.time()
        sym_kw   = {"BTCUSDT": ["bitcoin","btc"], "ETHUSDT": ["ethereum","eth"],
                    "SOLUSDT": ["solana","sol"],  "XRPUSDT": ["xrp","ripple"]}
        for sym, pos in snap.items():
            if now - pos["ts"] < SMART_EXIT_MIN_AGE:
                continue
            price = self.mkt.mark_price(sym)
            if not price:
                continue
            ctx       = self.mkt.get_market_context(sym)
            poly_sent = self.poly.get_sentiment_for_symbol(sym)
            kws       = sym_kw.get(sym, [sym.replace("USDT", "").lower()])
            sym_news  = [a for a in all_news
                         if any(k in (a.get("title","") + a.get("description","")).lower()
                                for k in kws)]
            action = self.gemini.smart_exit_check(pos, price, ctx, sym_news, poly_sent)
            if action == "EXIT":
                log(f"[SmartExit] {sym}: EXIT queued", Y)
                self.tracker.queue_smart_exit(sym, action)

    def stop(self):
        self._running = False


# =============================================================================
#  TELEGRAM
# =============================================================================

class TelegramSource:
    def __init__(self, queue: SignalQueue):
        self.queue         = queue
        self.ok            = bool(TG_TOKEN and TG_CHAT_ID)
        self._base         = f"https://api.telegram.org/bot{TG_TOKEN}"
        self._offset       = 0
        self._running      = False
        self.paused        = False
        self._cb_status    = None
        self._cb_close     = None
        self._cb_cancel    = None
        self._cb_check_sig = None
        self._cb_balance   = None  # [FIX-LIVE-4]

        if not self.ok:
            log("[Telegram] TG_TOKEN or TG_CHAT_ID not set.", Y)
        else:
            log("[Telegram] Ready.", G)
            mode = "LIVE" if not PAPER_MODE else "PAPER"
            net  = "TESTNET" if USE_TESTNET else "MAINNET"
            self.send(
                f"<b>Bot v11.1 STARTED ({mode}/{net})</b>\n"
                f"Smart Profit Protection: {'ON' if PROFIT_PROTECT_ENABLED else 'OFF'}\n"
                f"Score >= {MIN_SIGNAL_SCORE} | Lev {DEFAULT_LEVERAGE}x | "
                f"Risk {RISK_PER_TRADE_PCT}%/trade\n\n"
                f"/long BTCUSDT | /short ETHUSDT\n"
                f"/balance | /status | /pause | /help"
            )

    def send(self, text, parse_mode="HTML"):
        if not self.ok:
            return
        try:
            requests.post(
                f"{self._base}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": text[:4000],
                      "parse_mode": parse_mode},
                timeout=5)
        except Exception:
            pass

    def notify_open(self, sym, direction, entry, tp, tp2, sl,
                    size, score, sources, ai_reason="", filters=None):
        tag  = "PAPER" if PAPER_MODE else f"{R}LIVE{RST}"
        side = "LONG  ^" if direction == "LONG" else "SHORT v"
        src  = "+".join(sources)
        flt  = ""
        if filters:
            flt = (f"\nRSI:{filters.get('rsi','?')}  "
                   f"4h:{filters.get('mtf_4h','?')}  "
                   f"Brk:{filters.get('breakout','none')}")
        self.send(
            f"[{tag}] {side} <b>{sym}</b>  score:{score}\n"
            f"Entry:${entry:,.4f}  TP1:${tp:,.4f}  TP2:${tp2:,.4f}  SL:${sl:,.4f}\n"
            f"${size:.0f}x{DEFAULT_LEVERAGE}={size*DEFAULT_LEVERAGE:.0f}  [{src}]\n"
            f"AI: {ai_reason[:70]}{flt}")

    def notify_close(self, sym, direction, pnl, reason, daily_pnl, equity=0.0):
        tag = "WIN" if pnl >= 0 else "LOSS"
        mode_label = "" if PAPER_MODE else " [LIVE]"
        bal = f"\nBalance: ${equity:,.2f}{mode_label}"
        self.send(
            f"[{tag}] CLOSED <b>{sym}</b> {direction}\n"
            f"P&L: <b>${pnl:+.2f}</b>  Day: ${daily_pnl:+.2f}{bal}\n"
            f"Reason: {reason}")

    def notify_profit_protect(self, sym, direction, pnl, peak_pnl,
                               reasons, daily_pnl, equity=0.0):
        self.send(
            f"[PROFIT PROTECTED] <b>{sym}</b> {direction}\n"
            f"Locked: <b>${pnl:+.2f}</b>  (peak was ${peak_pnl:+.2f})\n"
            f"Day: ${daily_pnl:+.2f}  Balance: ${equity:,.2f}\n"
            f"Signals:\n" + "\n".join(f"  - {r}" for r in reasons[:3]) +
            "\nExited EARLY before stop loss — win locked.")

    def notify_daily(self, pnl, trades, wins, losses, wr, equity=0.0):
        net  = equity - PAPER_STARTING_BALANCE if PAPER_MODE else pnl
        mode = "Paper equity" if PAPER_MODE else "Live balance"
        self.send(
            f"<b>DAILY SUMMARY</b>\n"
            f"P&L: ${pnl:+.2f}  W:{wins}/L:{losses}  WR:{wr:.1f}%\n"
            f"{mode}: ${equity:,.2f} (net {net:+.2f})")

    def alert(self, msg: str):
        self.send(f"ALERT: {msg[:280]}")

    def register_status_cb(self,  fn): self._cb_status    = fn
    def register_close_cb(self,   fn): self._cb_close     = fn
    def register_cancel_cb(self,  fn): self._cb_cancel    = fn
    def register_check_sig_cb(self,fn):self._cb_check_sig = fn
    def register_balance_cb(self, fn): self._cb_balance   = fn  # [FIX-LIVE-4]

    def _parse_symbol(self, raw) -> Optional[str]:
        s = raw.upper()
        if not s.endswith("USDT"):
            s += "USDT"
        return s if s in SYMBOL_MAP.values() else None

    def _handle_update(self, update: dict):
        msg  = update.get("message") or update.get("channel_post") or {}
        text = (msg.get("text") or "").strip()
        if not text:
            return
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if TG_CHAT_ID and chat_id != str(TG_CHAT_ID):
            return
        parts = text.lower().split()
        cmd   = parts[0] if parts else ""
        log(f"[Telegram] {text}", M)

        def sym():
            if len(parts) < 2: return None
            return self._parse_symbol(parts[1])

        def sz():
            try: return float(parts[2]) if len(parts) >= 3 else None
            except: return None

        if cmd in ("/long", "/short"):
            direction = "LONG" if cmd == "/long" else "SHORT"
            s = sym()
            if not s: self.send(f"Usage: {cmd} BTCUSDT [size]"); return
            self.send(f"Checking {direction} {s}...")
            if self._cb_check_sig:
                self._cb_check_sig(s, direction, sz(), force=False)

        elif cmd in ("/forcelong", "/forceshort"):
            direction = "LONG" if "long" in cmd else "SHORT"
            s = sym()
            if not s: self.send(f"Usage: {cmd} BTCUSDT"); return
            self.send(f"FORCE {direction} {s}")
            if self._cb_check_sig:
                self._cb_check_sig(s, direction, sz(), force=True)

        elif cmd == "/close":
            s = sym() or ""
            if self._cb_close: self.send(self._cb_close(s))
            else: self.send("Not registered.")

        elif cmd == "/cancel":
            s = (parts[1].upper() if len(parts) >= 2 else "ALL")
            if s != "ALL" and not s.endswith("USDT"): s += "USDT"
            if self._cb_cancel: self.send(self._cb_cancel(s))
            else: self.send("Not registered.")

        elif cmd in ("/status", "/pnl"):
            if self._cb_status: self.send(self._cb_status())
            else: self.send("Not registered.")

        # [FIX-LIVE-4] New /balance command
        elif cmd == "/balance":
            if self._cb_balance: self.send(self._cb_balance())
            else: self.send("Balance callback not registered.")

        elif cmd == "/pause":
            self.paused = True
            self.send("Auto-trading PAUSED. /resume to restart.")

        elif cmd == "/resume":
            self.paused = False
            self.send("Auto-trading RESUMED.")

        elif cmd in ("/help", "/start"):
            mode = "LIVE" if not PAPER_MODE else "PAPER"
            self.send(
                f"<b>Commands v11.1 ({mode})</b>\n"
                "/long BTCUSDT [size]   — check signals, then trade\n"
                "/short ETHUSDT [size]  — check signals, then trade\n"
                "/forcelong BTCUSDT     — trade immediately\n"
                "/forceshort BTCUSDT    — trade immediately\n"
                "/close BTCUSDT         — close position now\n"
                "/cancel ALL            — cancel pending signals\n"
                "/balance               — show live wallet balance\n"
                "/status                — all positions + P&L\n"
                "/pause / /resume       — pause/resume auto-trading\n\n"
                "<b>Smart Profit Protection</b>\n"
                "Watches every profitable position every tick.\n"
                "If reversal detected, exits IMMEDIATELY to lock the win.")
        else:
            self.send(f"Unknown: {cmd}. /help")

    def run_loop(self):
        if not self.ok:
            return
        self._running = True
        log("[Telegram] Polling...", G)
        while self._running:
            try:
                r = requests.get(
                    f"{self._base}/getUpdates",
                    params={"offset": self._offset, "timeout": 2,
                            "allowed_updates": ["message", "channel_post"]},
                    timeout=8)
                data = r.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        self._offset = update["update_id"] + 1
                        self._handle_update(update)
            except Exception as e:
                log(f"[Telegram] Poll: {e}", R, "DEBUG")
            time.sleep(TG_POLL_INTERVAL)

    def stop(self):
        self._running = False


# =============================================================================
#  SIGNAL CHECKER  (for /long /short Telegram commands)
# =============================================================================

class SignalChecker:
    def __init__(self, mkt, gemini, strategy, poly, news):
        self.mkt      = mkt
        self.ai       = gemini
        self.strategy = strategy
        self.poly     = poly
        self.news     = news

    def check(self, symbol, direction) -> dict:
        reasons = []; raw_events = []; score = 0; conflicts = []
        ctx   = self.mkt.get_market_context(symbol)
        price = ctx.get("price", 0)
        score += 3  # manual baseline

        mom = ctx.get("momentum")
        if mom == direction:      score += 1; reasons.append(f"1h Momentum: {mom}")
        elif mom and mom != direction: conflicts.append(f"1h Momentum: {mom}")

        rsi = ctx.get("rsi")
        if rsi:
            if direction == "LONG"  and rsi > RSI_OVERBOUGHT:
                conflicts.append(f"RSI {rsi:.0f} overbought (>{RSI_OVERBOUGHT})")
            elif direction == "SHORT" and rsi < RSI_OVERSOLD:
                conflicts.append(f"RSI {rsi:.0f} oversold (<{RSI_OVERSOLD})")
            elif direction == "LONG"  and rsi < 55: score += 1; reasons.append(f"RSI {rsi:.0f}")
            elif direction == "SHORT" and rsi > 45: score += 1; reasons.append(f"RSI {rsi:.0f}")

        mtf = self.mkt.momentum_direction(symbol, "4h")
        if mtf == direction:    score += 2; reasons.append(f"4h trend: {mtf}")
        elif mtf and mtf != direction: conflicts.append(f"4h trend: {mtf}")

        brk = ctx.get("breakout")
        if brk == direction:    score += 2; reasons.append(f"Breakout: {direction}")
        elif brk and brk != direction: conflicts.append(f"Breakout: {brk}")

        poly_sent = self.poly.get_sentiment_for_symbol(symbol)
        if poly_sent == direction:
            score += 2; reasons.append(f"Polymarket: {poly_sent}")
        elif poly_sent and poly_sent != direction:
            conflicts.append(f"Polymarket: {poly_sent}")

        news_dir, news_score, news_title = self.news.get_sentiment_for_symbol(symbol)
        if news_dir == direction:
            score += news_score; reasons.append(f"News: {news_title[:50]}")
        elif news_dir and news_dir != direction:
            conflicts.append(f"News: {news_dir}")

        ai_result = self.ai.analyse(
            symbol, direction, ctx, raw_events,
            reasons if reasons else [f"Manual {direction}"])
        if ai_result["signal"] == "IGNORE":
            conflicts.append(f"Gemini: IGNORE ({ai_result['reason']})")
        elif ai_result["signal"] == direction:
            score += ai_result["score_bonus"]
            reasons.append(f"Gemini: {direction} {ai_result['confidence']}%")
        else:
            conflicts.append(f"Gemini: suggests {ai_result['signal']}")

        supported  = score >= MIN_SIGNAL_SCORE
        sym_short  = symbol.replace("USDT", "")
        arrow      = "^" if direction == "LONG" else "v"

        lines = [
            f"<b>Signal Check: {arrow} {direction} {sym_short}</b>",
            f"${price:,.4f}  Score: <b>{score}</b> (need {MIN_SIGNAL_SCORE})", "",
        ]
        if reasons:
            lines.append("<b>Supporting:</b>")
            for r in reasons: lines.append(f"  + {r}")
        if conflicts:
            lines += ["", "<b>Conflicts:</b>"]
            for c in conflicts: lines.append(f"  - {c}")
        lines.append("")
        lines.append(
            f"<b>{'EXECUTING ' + direction if supported else 'NOT TRADING'}</b>" +
            ("" if supported else f"\n/force{direction.lower()} {symbol} to override"))

        return {"supported": supported, "score": score,
                "report": "\n".join(lines),
                "reasons": reasons, "raw_events": raw_events,
                "market_ctx": ctx, "ai_result": ai_result}


# =============================================================================
#  MAIN BOT
# =============================================================================

class SignalAggregatorBot:
    def __init__(self, test_mode: bool = False):
        self.test_mode     = test_mode
        self.queue         = SignalQueue()
        self.mkt_data      = MarketData()
        self.paper_account = PaperAccount()
        self.state         = DailyState(self.paper_account)

        self.poly        = PolymarketSource(self.queue)
        self.news        = NewsSource(self.queue)
        self.gemini      = GeminiEngine()
        self.strategy    = StrategyEngine(self.mkt_data)
        self.binance     = BinanceFutures(self.mkt_data, self.paper_account)
        self.tracker     = PositionTracker(self.binance, self.mkt_data)
        self.gemini_auto = GeminiAutoTrader(
            self.queue, self.gemini, self.mkt_data, self.poly, self.news)
        self.sig_checker = SignalChecker(
            self.mkt_data, self.gemini, self.strategy, self.poly, self.news)
        self.smart_exit  = SmartExitMonitor(
            self.tracker, self.gemini, self.mkt_data, self.news, self.poly)
        self.tg = TelegramSource(self.queue)

        self.journal       = []
        self.trades        = 0
        self.consec_losses = 0
        self.cycle         = 0
        self.running       = False
        self._shutdown_mode = False
        self.sym_perf      = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})

        def _on_closed(pnl_usd):
            if pnl_usd < 0: self.consec_losses += 1
            else:            self.consec_losses  = 0
        self.tracker.on_closed = _on_closed

        # Register Telegram callbacks
        self.tg.register_status_cb(
            lambda: self.tracker.status_text(
                self.binance, self.state, self.paper_account))
        self.tg.register_close_cb(self._handle_force_close)
        self.tg.register_cancel_cb(self._handle_cancel)
        self.tg.register_check_sig_cb(self._handle_check_signal)
        self.tg.register_balance_cb(self._handle_balance)  # [FIX-LIVE-4]

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _handle_check_signal(self, symbol, direction, size, force):
        def _run():
            if force:
                self.queue.add(Signal(symbol=symbol, direction=direction,
                    source=Signal.SOURCE_TELEGRAM,
                    reason=f"Force {direction} {symbol}",
                    score=10, manual=True, size_override=size, force=True))
                return
            result = self.sig_checker.check(symbol, direction)
            self.tg.send(result["report"])
            if result["supported"]:
                sig = Signal(symbol=symbol, direction=direction,
                    source=Signal.SOURCE_TELEGRAM,
                    reason=f"Checked {direction} {symbol}",
                    score=result["score"], manual=True, size_override=size)
                sig.raw_event = result["raw_events"][0] if result["raw_events"] else {}
                self.queue.add(sig)
        threading.Thread(target=_run, daemon=True).start()

    def _handle_force_close(self, symbol) -> str:
        return self.tracker.force_close(symbol, self.paper_account,
                                        self.state, self.journal, self.sym_perf)

    def _handle_cancel(self, symbol) -> str:
        with self.queue._lock:
            if symbol == "ALL":
                self.queue._pending.clear()
                return "All pending signals cancelled."
            removed = self.queue._pending.pop(symbol, [])
        return (f"Cancelled {len(removed)} signal(s) for {symbol}."
                if removed else f"No pending signals for {symbol}.")

    def _handle_balance(self) -> str:
        """[FIX-LIVE-4] Show real Binance balance."""
        if PAPER_MODE:
            open_pos = self.tracker.get_open_positions()
            equity   = self.paper_account.total_equity(
                open_pos, self.binance.get_price)
            return (f"PAPER MODE\n"
                    f"Cash: ${self.paper_account.cash:,.2f}\n"
                    f"Unrealized: ${self.tracker.total_unrealized_pnl():+.2f}\n"
                    f"Total equity: ${equity:,.2f}")
        else:
            bal = self.binance.get_balance()
            unrealized = self.tracker.total_unrealized_pnl()
            return (f"LIVE BINANCE FUTURES\n"
                    f"Available USDT: ${bal:,.2f}\n"
                    f"Unrealized P&L: ${unrealized:+.2f}\n"
                    f"Network: {'TESTNET' if USE_TESTNET else 'MAINNET'}")

    # ── Guard rails ───────────────────────────────────────────────────────────

    def _guard_rails(self, balance) -> tuple:
        if self.state.pnl <= -DAILY_LOSS_LIMIT:
            return False, f"Daily loss -${DAILY_LOSS_LIMIT} hit"
        if self.state.pnl >= DAILY_PROFIT_TARGET:
            return False, f"Daily target +${DAILY_PROFIT_TARGET} hit"
        if self.consec_losses >= MAX_CONSECUTIVE_LOSSES:
            return False, f"{MAX_CONSECUTIVE_LOSSES} consecutive losses"
        if balance < MIN_TRADE_USDT * 1.5:
            return False, f"Low balance (${balance:.0f})"
        return True, ""

    def _do_cooldown(self):
        log(f"Pausing {COOLDOWN_MINUTES}min after losses", Y)
        self.tg.alert(f"Cooldown {COOLDOWN_MINUTES}min after consecutive losses")
        end = time.time() + COOLDOWN_MINUTES * 60
        while self.running and time.time() < end:
            time.sleep(5)
        self.consec_losses = 0

    # ── Execute signal ────────────────────────────────────────────────────────

    def _execute_signal(self, symbol, direction, base_score,
                        reasons, sources, usdt_size_hint, balance,
                        manual=False, raw_events=None, force=False):

        def skip(r):
            log(f"[Bot] SKIP {symbol} {direction} — {r}", DIM)
            if manual: self.tg.send(f"SKIP: {r}")

        if self.tracker.is_open(symbol):        skip("position already open"); return
        if self.tracker.count() >= MAX_OPEN_TRADES: skip(f"max {MAX_OPEN_TRADES} trades"); return

        # ── v12.0: DATA-DRIVEN GUARDS ─────────────────────────────────────
        # 1. Banned LONG symbols (consistent losers from trading history)
        if not force and direction == "LONG" and symbol in BANNED_LONG_SYMBOLS:
            skip(f"BANNED LONG: {symbol} has poor LONG history — SHORTs only")
            return

        if not manual and not force:
            ok, reason = self._guard_rails(balance)
            if not ok:
                if "consecutive" in reason.lower(): self._do_cooldown()
                skip(f"guard: {reason}"); return
            if self.tg.paused: skip("bot is paused"); return

        # Get equity for sizing
        open_pos = self.tracker.get_open_positions()
        if PAPER_MODE:
            equity = self.paper_account.total_equity(open_pos, self.binance.get_price)
        else:
            equity = balance

        if not force:
            corr_blocked, corr_reason = self.strategy.correlation_blocked(
                symbol, direction, open_pos, equity)
            if corr_blocked: skip(f"correlation: {corr_reason}"); return

        # Strategy filters
        if not force and not manual:
            strat = self.strategy.evaluate(symbol, direction, equity)
            if strat["blocked"]:
                skip(f"strategy: {strat['block_reason']}"); return
            usdt_size     = strat["position_size"]
            strat_bonus   = strat["score_bonus"]
            strat_filters = strat["filters"]
        else:
            usdt_size     = usdt_size_hint or MIN_TRADE_USDT
            strat_bonus   = 0
            strat_filters = {}

        # Gemini analysis
        source    = sources[0] if sources else ""
        ai_result = {"signal": direction, "confidence": 50,
                     "reason": "Manual/force", "score_bonus": 0}
        if not manual and not force and self.gemini.ok:
            ctx       = self.mkt_data.get_market_context(symbol)
            ai_result = self.gemini.analyse(
                symbol, direction, ctx, raw_events or [], reasons,
                skip_if_source=source)
            if ai_result["reason"] == "Gemini unavailable":
                skip("Gemini unavailable — refusing to trade blind")
                return
            if GEMINI_VETO and ai_result["signal"] == "IGNORE":
                log(f"[Bot] Gemini VETO | {ai_result['reason']}", Y)
                return
            if ai_result["signal"] not in ("LONG", "SHORT", "IGNORE"):
                ai_result["signal"] = direction
        elif not manual and not force and not self.gemini.ok:
            skip("Gemini not configured — auto-trading requires AI confirmation")
            return

        mkt_bonus   = self.mkt_data.confluence_bonus(symbol, direction) if (force or manual) else 0
        ai_bonus    = ai_result["score_bonus"] if not manual else 0
        raw_score   = base_score + strat_bonus + mkt_bonus + ai_bonus

        # ── v12.0: SCORE CAP ──────────────────────────────────────────────
        # Data shows score 9 = 44% WR and score 10 = 0% WR.
        # Over-high scores indicate all sources fired simultaneously —
        # which often means the signal is STALE (market already moved).
        # Cap final score to prevent chasing "too perfect" setups.
        final_score = min(raw_score, MAX_SIGNAL_SCORE) if not (manual or force) else raw_score
        if raw_score > MAX_SIGNAL_SCORE and not (manual or force):
            log(f"  [v12] Score capped: {raw_score} -> {final_score} "
                f"(scores >{MAX_SIGNAL_SCORE} historically 0-44% WR)", Y)

        # ── v12.0: DIRECTION BIAS ─────────────────────────────────────────
        # Data: SHORT 62.5% WR vs LONG 39.1% WR.
        # LONGs require 2 extra score points to compensate for lower WR.
        effective_min = MIN_SIGNAL_SCORE
        if not (manual or force) and direction == "LONG":
            effective_min = MIN_SIGNAL_SCORE + LONG_EXTRA_SCORE_REQUIRED
            if final_score < effective_min:
                skip(f"LONG needs score>={effective_min} "
                     f"(got {final_score}) — data shows LONGs need stronger confluence")
                return

        decision = ("EXECUTE" if (manual or force or final_score >= effective_min)
                    else "SKIP")
        col = G if decision == "EXECUTE" else Y

        log(f"\n{'─'*60}", B)
        log(f"  {symbol} {direction} -> {decision}  "
            f"score={final_score} (raw={raw_score}) "
            f"(base={base_score}+strat={strat_bonus}+mkt={mkt_bonus}+ai={ai_bonus}) "
            f"need>={effective_min}", col)
        log(f"  Gemini: {ai_result['signal']} "
            f"conf={ai_result['confidence']}% | {ai_result['reason'][:60]}", M)

        if not manual and not force and final_score < effective_min:
            skip(f"score {final_score} < {effective_min}")
            return

        order, levels = self.binance.open_position(symbol, direction, usdt_size)
        if not order or not levels:
            log(f"[Bot] Order failed: {symbol}", R)
            return

        entry = levels["entry"]
        tp    = levels["tp"]
        tp2   = levels.get("tp2", tp)
        sl    = levels["sl"]
        atr   = levels.get("atr")
        qty   = order.get("qty", usdt_size / max(entry, 0.0001))

        self.tracker.add(symbol, direction, entry, tp, tp2, sl, atr, qty,
                         usdt_size, " | ".join(reasons[:2])[:100],
                         sources, final_score, ai_result["reason"])
        self.trades += 1

        self.tg.notify_open(symbol, direction, entry, tp, tp2, sl,
                            usdt_size, final_score, sources,
                            ai_result["reason"], strat_filters)

    # ── Process queue ─────────────────────────────────────────────────────────

    def _process_queue(self, balance):
        for sig in self.queue.pop_manual():
            usdt_sz = sig.size_override or MIN_TRADE_USDT
            self._execute_signal(
                symbol=sig.symbol, direction=sig.direction,
                base_score=sig.score, reasons=[sig.reason],
                sources=[sig.source], usdt_size_hint=usdt_sz,
                balance=balance, manual=True,
                raw_events=[sig.raw_event] if sig.raw_event else [],
                force=sig.force)

        for m in self.queue.flush_merged():
            self._execute_signal(
                symbol=m["symbol"], direction=m["direction"],
                base_score=m["score"], reasons=m["reasons"],
                sources=m["sources"], usdt_size_hint=None,
                balance=balance, manual=False,
                raw_events=m.get("raw_events", []))

    def _process_smart_exits(self):
        for sym, action in self.tracker.pop_pending_exits():
            if not self.tracker.is_open(sym):
                continue
            if action == "EXIT":
                self.tracker.force_close(sym, self.paper_account,
                                         self.state, self.journal, self.sym_perf)

    # ── Dashboard ─────────────────────────────────────────────────────────────

    def _print_dashboard(self, balance):
        open_pos   = self.tracker.get_open_positions()
        unrealized = self.tracker.total_unrealized_pnl()

        if PAPER_MODE:
            equity = self.paper_account.total_equity(open_pos, self.binance.get_price)
            bal_line = (f"  Cash      : ${self.paper_account.cash:,.2f}  "
                        f"Float: {G if unrealized>=0 else R}${unrealized:+.2f}{RST}  "
                        f"Equity: {G}{BRIGHT}${equity:,.2f}{RST}")
        else:
            equity = balance
            bal_line = (f"  Balance   : {G}{BRIGHT}${balance:,.2f} USDT{RST}  "
                        f"Float: {G if unrealized>=0 else R}${unrealized:+.2f}{RST}")

        net        = equity - PAPER_STARTING_BALANCE if PAPER_MODE else self.state.pnl
        total      = self.state.wins + self.state.losses
        wr         = self.state.wins / max(1, total) * 100
        pnl_c      = G if self.state.pnl >= 0 else R
        ai_tag     = f"{G}Gemini ON{RST}" if self.gemini.ok else f"{R}OFF{RST}"
        pp_tag     = f"{G}PP:ON{RST}" if PROFIT_PROTECT_ENABLED else f"{DIM}PP:OFF{RST}"
        paused_tag = f" {R}[PAUSED]{RST}" if self.tg.paused else ""
        mode_tag   = f"{R}[LIVE]{RST}" if not PAPER_MODE else f"{G}[PAPER]{RST}"
        net_tag    = f"{Y}TESTNET{RST}" if USE_TESTNET else f"{R}MAINNET{RST}"
        ok, reason = self._guard_rails(balance)
        auto_s     = (f"{G}AUTO:ON{RST}" if (ok and not self.tg.paused)
                      else f"{R}AUTO:OFF ({reason}){RST}")
        sess_ok, sess_name = in_trading_session()
        sess_tag = f"{G}{sess_name}{RST}" if sess_ok else f"{Y}{sess_name}{RST}"

        # [FIX-LIVE-5] Use plain separator (no ANSI clear on Windows)
        sep = "=" * 70
        print(f"\n{B}{sep}{RST}")
        print(f"  Bot v11.1  {mode_tag}  {net_tag}  {ai_tag}  {pp_tag}  "
              f"Session:{sess_tag}  {ts_full()}{paused_tag}")
        print(bal_line)
        print(f"  Day P&L   : {pnl_c}${self.state.pnl:+.2f}{RST}  "
              f"W:{G}{self.state.wins}{RST}/L:{R}{self.state.losses}{RST}  "
              f"WR:{G if wr>=55 else Y}{wr:.1f}%{RST}  "
              f"Positions:{self.tracker.count()}/{MAX_OPEN_TRADES}  {auto_s}")

        tpct = min(100, max(0,  self.state.pnl / DAILY_PROFIT_TARGET * 100))
        lpct = min(100, max(0, -min(0, self.state.pnl) / DAILY_LOSS_LIMIT * 100))
        print(f"  Target    [{pct_bar(tpct)}] {tpct:.0f}%  "
              f"Risk [{pct_bar(lpct, 10, R)}] {lpct:.0f}%  "
              f"Pending:{self.queue.pending_count()}")

        if open_pos:
            print(f"{B}{'-'*70}{RST}")
            print(f"  {Y}OPEN POSITIONS:{RST}")
            for sym, p in open_pos.items():
                price   = self.binance.get_price(sym) or p["entry"]
                pnl_usd = self.tracker._pnl(p, price)
                age     = int((time.time() - p["ts"]) / 60)
                col     = G if pnl_usd >= 0 else R
                arrow   = "^" if p["direction"] == "LONG" else "v"
                tp1_tag = f"  {G}[TP1]{RST}" if p.get("tp1_done") else ""
                pp_arm  = f"  {M}[PP armed]{RST}" if (PROFIT_PROTECT_ENABLED and pnl_usd > 0) else ""
                to_tp = ((p["tp"]-price)/price*100 if p["direction"]=="LONG"
                         else (price-p["tp"])/price*100)
                to_sl = ((price-p["sl"])/price*100 if p["direction"]=="LONG"
                         else (p["sl"]-price)/price*100)
                print(f"    {arrow} {sym:12s}  "
                      f"{col}{BRIGHT}${pnl_usd:+.2f}{RST}  "
                      f"in:${p['entry']:,.4f}->now:${price:,.4f}  "
                      f"TP:{G}{to_tp:+.1f}%{RST}  SL:{R}{to_sl:+.1f}%{RST}  "
                      f"{age}m{tp1_tag}{pp_arm}")
        else:
            print(f"{B}{'-'*70}{RST}")
            print(f"  {DIM}No open positions — scanning for signals...{RST}")

        if self.journal:
            print(f"{B}{'-'*70}{RST}")
            print(f"  {Y}LAST 5 TRADES:{RST}")
            for j in self.journal[-5:]:
                col   = G if j["pnl"] >= 0 else R
                arrow = "^" if j["direction"] == "LONG" else "v"
                tag   = "WIN " if j["pnl"] >= 0 else "LOSS"
                pp    = f" {M}[PP]{RST}" if j.get("profit_protected") else ""
                live  = f" {R}[LIVE]{RST}" if j.get("live") else ""
                print(f"    {arrow} {col}{tag}  {j['symbol']:12s}  "
                      f"${j['pnl']:+.2f}  bal:${j.get('equity',0):,.0f}"
                      f"  [{j['reason'][:22]}]{pp}{live}{RST}")

        if self.sym_perf:
            print(f"{B}{'-'*70}{RST}")
            parts = []
            for sym, p in sorted(self.sym_perf.items(),
                                  key=lambda x: x[1]["pnl"], reverse=True):
                t = p["wins"] + p["losses"]
                swr = p["wins"] / max(1, t) * 100
                c   = G if swr >= 55 else (Y if swr >= 40 else R)
                parts.append(f"{c}{sym.replace('USDT','')}:{swr:.0f}%"
                              f"(${p['pnl']:+.1f}){RST}")
            print(f"  {Y}SYMBOLS:{RST} " + "  ".join(parts))

        print(f"{B}{sep}{RST}")
        sys.stdout.flush()

    # ── Save journal ──────────────────────────────────────────────────────────

    def _save_journal(self):
        if not self.journal:
            return
        fname = f"journal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(self.journal, f, indent=2)
            log(f"Journal saved -> {fname}", G)
        except Exception:
            pass
        if PAPER_MODE:
            open_pos = self.tracker.get_open_positions()
            equity   = self.paper_account.total_equity(
                open_pos, self.binance.get_price)
            self.paper_account.save_equity_curve(equity)

    # ── Shutdown helpers ──────────────────────────────────────────────────────

    def _force_close_all(self):
        with self.tracker._lock:
            syms = list(self.tracker.positions.keys())
        if not syms:
            log("No open positions.", G)
            return
        log(f"Force-closing {len(syms)} position(s)...", R)
        self.tg.alert(f"FORCE CLOSE: {len(syms)} position(s) at market price.")
        for sym in syms:
            try:
                self.tracker.force_close(sym, self.paper_account,
                                         self.state, self.journal, self.sym_perf)
            except Exception as e:
                log(f"  ERROR closing {sym}: {e}", R)
                if not PAPER_MODE:
                    self.tg.alert(f"FAILED to close {sym} — close manually on Binance!")

    def _graceful_wait(self, balance):
        with self.tracker._lock:
            remaining = list(self.tracker.positions.keys())
        if not remaining:
            log("No open positions — clean exit.", G)
            return
        log(f"GRACEFUL: {len(remaining)} open. Ctrl+C again to force.", Y)
        self.tg.alert(f"Graceful shutdown: {len(remaining)} position(s) open. "
                      f"Waiting for TP/SL. /close SYMBOL to close manually.")

        def _force(sig, frame):
            log("\nSecond Ctrl+C — force closing!", R)
            self._shutdown_mode = "force"
        signal_module.signal(signal_module.SIGINT, _force)

        last_print = 0.0
        while True:
            if self._shutdown_mode == "force":
                self._force_close_all()
                return
            with self.tracker._lock:
                remaining = list(self.tracker.positions.keys())
            if not remaining:
                log("All positions closed — clean exit.", G)
                self.tg.alert("All positions closed. Bot shut down cleanly.")
                return
            self.tracker.check_all(self.state, self.tg, self.paper_account,
                                   self.journal, self.sym_perf)
            if time.time() - last_print > 30:
                with self.tracker._lock:
                    snap = copy.deepcopy(self.tracker.positions)
                log(f"Waiting... {len(snap)} open:", Y)
                for sym, pos in snap.items():
                    price   = self.binance.get_price(sym) or pos["entry"]
                    pnl_usd = self.tracker._pnl(pos, price)
                    col     = G if pnl_usd >= 0 else R
                    log(f"  {sym} [{pos['direction']}]  "
                        f"P&L:{col}${pnl_usd:+.2f}{RST}  "
                        f"price:${price:,.4f}  "
                        f"TP:${pos['tp']:,.4f}  SL:${pos['sl']:,.4f}", W)
                last_print = time.time()
            time.sleep(2)

    # ── Main run loop ─────────────────────────────────────────────────────────

    def run(self):
        live_mode = not PAPER_MODE

        # [FIX-LIVE-6] Check keys BEFORE showing banner
        if live_mode and (not BINANCE_KEY or BINANCE_KEY == "YOUR_BINANCE_API_KEY_HERE"):
            print(f"\n{R}ERROR: BINANCE_API_KEY not set in .env file!{RST}")
            print(f"\nCreate a .env file with:")
            print(f"  BINANCE_API_KEY=your_key_here")
            print(f"  BINANCE_API_SECRET=your_secret_here")
            print(f"  BINANCE_TESTNET=false")
            print(f"\nGet your keys at: binance.com -> Profile -> API Management")
            return

        # Get live balance BEFORE banner to display it
        live_balance = 0.0
        if live_mode and self.binance.client:
            live_balance = self.binance.get_balance()

        banner(live_mode=live_mode, live_balance=live_balance,
               test_mode=self.test_mode)

        # If Binance fell back to paper due to key/connection error
        if live_mode and self.binance.paper:
            print(f"\n{R}LIVE MODE REQUESTED but Binance connection failed.{RST}")
            print(f"The bot is now running in PAPER mode.")
            print(f"Fix the errors above and restart with --live to go live.\n")
            # Continue in paper mode rather than crash

        # [FIX-LIVE-8] Live mode confirmation with balance shown
        if live_mode and not self.binance.paper:
            net = "TESTNET" if USE_TESTNET else f"{R}MAINNET — THIS IS REAL MONEY{RST}"
            print(f"\n{R}{'='*60}{RST}")
            print(f"  LIVE FUTURES TRADING ON {net}")
            print(f"  Balance : {G}{BRIGHT}${live_balance:,.2f} USDT{RST}")
            print(f"  Per trade: ${MIN_TRADE_USDT} - ${MAX_TRADE_USDT} "
                  f"(1% risk at ${live_balance:.0f} = "
                  f"${live_balance*RISK_PER_TRADE_PCT/100:.2f}/trade)")
            print(f"  Daily loss limit: -${DAILY_LOSS_LIMIT}")
            print(f"  Daily profit target: +${DAILY_PROFIT_TARGET}")
            print(f"{R}{'='*60}{RST}")
            confirm = input(f"\n  Type  YES I UNDERSTAND  to trade with real money: ").strip()
            if confirm != "YES I UNDERSTAND":
                log("Aborted by user.", Y)
                return

        # Start background threads
        threads = [
            ("polymarket",  self.poly.run_loop),
            ("newsapi",     self.news.run_loop),
            ("telegram",    self.tg.run_loop),
            ("gemini_auto", self.gemini_auto.run_loop),
            ("smart_exit",  self.smart_exit.run_loop),
        ]
        for name, target in threads:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            log(f"Thread: {name}", G)

        if self.test_mode:
            log("TEST MODE: injecting signals in 5s...", Y)
            def _inject():
                time.sleep(5)
                self.poly.inject_test_spike("BTCUSDT", "LONG")
                self.queue.add(Signal(
                    symbol="BTCUSDT", direction="LONG",
                    source=Signal.SOURCE_NEWS,
                    reason="[TEST] Bitcoin ETF approved by SEC",
                    score=3,
                    raw_event={"type": "news", "title": "Bitcoin ETF approved",
                               "keyword": "etf approved", "direction": "LONG"}))
                log("TEST: signals injected. Should trigger a LONG on BTCUSDT.", Y)
            threading.Thread(target=_inject, daemon=True).start()

        self.running = True

        def _first_ctrlc(sig, frame):
            log("\nCtrl+C — graceful shutdown. Ctrl+C again to force close.", Y)
            self._shutdown_mode = "graceful"
            self.running = False

        signal_module.signal(signal_module.SIGINT,  _first_ctrlc)
        signal_module.signal(signal_module.SIGTERM, _first_ctrlc)

        last_dashboard  = 0.0
        last_state_save = 0.0
        last_bal_refresh = 0.0

        try:
            while self.running:
                self.cycle += 1
                now = time.time()

                # Get current balance
                if PAPER_MODE:
                    open_pos = self.tracker.get_open_positions()
                    balance  = self.paper_account.total_equity(
                        open_pos, self.binance.get_price)
                else:
                    # Refresh live balance every 60s
                    if now - last_bal_refresh > 60:
                        self.binance.refresh_live_balance()
                        last_bal_refresh = now
                    balance = self.binance.get_balance()

                ok, stop_reason = self._guard_rails(balance)
                if not ok and "hit" in stop_reason.lower():
                    log(f"STOP: {stop_reason}", R)
                    self.tg.alert(f"STOP: {stop_reason}")
                    break

                # Check TP/SL/Profit Protection
                self.tracker.check_all(self.state, self.tg, self.paper_account,
                                       self.journal, self.sym_perf)
                self._process_smart_exits()

                # Process new signals
                if not self._shutdown_mode:
                    self._process_queue(balance)

                # Dashboard every 2s
                if now - last_dashboard >= 2.0:
                    self._print_dashboard(balance)
                    last_dashboard = now

                # Save state every 60s
                if now - last_state_save > 60:
                    if PAPER_MODE:
                        self.paper_account.save_equity_curve(balance)
                    self.state.save()
                    last_state_save = now

                time.sleep(1)

        finally:
            self.running = False
            for src in (self.poly, self.news, self.tg,
                        self.gemini_auto, self.smart_exit):
                src.stop()

            if self._shutdown_mode == "graceful":
                self._graceful_wait(balance)
            else:
                self._force_close_all()

            total    = self.state.wins + self.state.losses
            wr       = self.state.wins / max(1, total) * 100
            final_eq = (self.paper_account.total_equity({}, self.binance.get_price)
                        if PAPER_MODE else self.binance.get_balance())
            self._save_journal()

            print(f"\n{B}{'='*65}{RST}")
            log(f"  Day P&L     : ${self.state.pnl:+.2f}",
                G if self.state.pnl >= 0 else R)
            log(f"  Final bal   : ${final_eq:,.2f}",
                G if final_eq >= PAPER_STARTING_BALANCE else R)
            log(f"  Trades      : {self.trades}  "
                f"(W:{self.state.wins}/L:{self.state.losses})", W)
            log(f"  Win Rate    : {wr:.1f}%", G if wr >= 55 else Y)
            pp_wins = sum(1 for j in self.journal
                          if j.get("profit_protected") and j["pnl"] >= 0)
            if pp_wins:
                log(f"  PP Wins     : {pp_wins} (early exits that avoided SL)", M)
            print(f"{B}{'='*65}{RST}\n")
            self.tg.notify_daily(self.state.pnl, self.trades,
                                 self.state.wins, self.state.losses,
                                 wr, final_eq)


# =============================================================================
#  ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="AI Crypto Trading Bot v11.1 — Live Trading Edition")
    parser.add_argument("--live",  action="store_true",
                        help="Enable live Binance Futures trading")
    parser.add_argument("--test",  action="store_true",
                        help="Inject test signals to verify pipeline")
    parser.add_argument("--debug", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    global PAPER_MODE
    if args.live:
        PAPER_MODE = False
    if args.debug:
        os.environ["BOT_LOG_LEVEL"] = "DEBUG"

    bot = SignalAggregatorBot(test_mode=args.test)
    bot.run()


if __name__ == "__main__":
    main()
    