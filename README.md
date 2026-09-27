# SIA-TradeX Pro (v2.0)
### Autonomous AI Quantitative Intelligence & High-Frequency Multi-Source Trading Engine

**SIA-TradeX Pro** is an institutional-grade algorithmic cryptocurrency futures trading system. It fuses technical market microstructure, higher-timeframe trend analysis, prediction market probability shifts (Polymarket), real-time news sentiment (NewsAPI), and Google Gemini AI reasoning into a cohesive, high-confluence execution pipeline.

---

## 🚀 Key Improvements in v2.0 Pro

| Feature | Legacy v1.0 | **SIA-TradeX Pro (v2.0)** |
| :--- | :--- | :--- |
| **Architecture** | 3,146-line monolithic script | **Clean, decoupled modular packages** (`core`, `strategies`, `ai`, `execution`, `ui`, `storage`) |
| **AI Rate Limiting** | Spammed 429 quota errors in tight loops | **Strict Token-Bucket Rate Limiter** pacing calls safely under 14 RPM across all threads |
| **AI Schema** | Brittle regex string scraping | **Pydantic-enforced JSON validation** (`AISignalDecision`) |
| **Directional Bias** | Hardcoded Short bias from small sample (63 trades) | **Dynamic Market Regime Detection** (Bull, Bear, Range, Volatility) via ADX + 200 EMA |
| **Indicators** | Hand-rolled math with only 19 candles lookback | **Warm-up indicator engine** (150+ candles) for accurate Wilder's RSI, ATR, and anchored VWAP |
| **Persistence** | Flat, vulnerable `.json` files | **SQLite Database with Write-Ahead Logging (WAL)** for corruption-free persistence |
| **User Interface** | Console-only text dashboard | **Cyber-Quant Web Dashboard** (FastAPI + WebSockets + Emergency Panic Button) |
| **Risk Defense** | Fixed SL / TP | **Multi-tier Take Profit**, Trailing Stop, Smart Profit Protection, and **Portfolio Heat defense** |

---

## 🏛️ System Architecture

```text
SIA-TradeX/
├── .env                  # API keys and environment variables
├── requirements.txt      # System dependencies
├── run.py                # Main CLI entrypoint
├── engine.py             # Central Quant Engine Orchestrator
├── config/
│   └── settings.py       # Pydantic BaseSettings with typed validation
├── core/
│   ├── models.py         # Signal, Position, Order, TradeRecord, MarketContext
│   └── queue.py          # Multi-source signal queue with deduplication
├── data/
│   ├── market_data.py    # Binance Futures REST + Depth Imbalance & Funding
│   ├── polymarket.py     # Gamma API prediction sentiment feed
│   └── news_client.py    # NewsAPI breaking catalysts feed
├── ai/
│   └── gemini_service.py # Gemini 2.5 Flash with Token Bucket Rate Limiter
├── strategies/
│   ├── indicators.py     # High-precision RSI, VWAP, ATR, ADX, Donchian breakout
│   ├── regime.py         # Dynamic Market Regime Detector
│   └── confluence.py     # Multi-factor confluence scoring engine
├── execution/
│   ├── binance_executor.py # Live Binance Futures order execution with bracket TP/SL
│   ├── paper_account.py    # Realistic paper simulation with fee and slippage modeling
│   ├── risk_manager.py     # Portfolio heat limits, correlation caps, and circuit breakers
│   └── profit_protector.py # Smart Profit Protection (locks early wins)
├── storage/
│   └── database.py       # SQLite WAL database for trades and equity curves
└── ui/
    ├── telegram_service.py # Interactive Telegram Bot remote control
    ├── web_server.py       # FastAPI backend & WebSocket broadcast
    └── static/
        └── index.html      # Cyber-quant dark mode web dashboard
```

---

## ⚡ Quick Start

### 1. Installation
Ensure Python 3.10+ is installed:
```powershell
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Fill in your credentials in `.env`:
```env
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
BINANCE_TESTNET=true
GEMINI_API_KEY=your_gemini_key_here
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
NEWS_API_KEY=your_news_key_here
```

### 3. Run the System

#### Paper Trading with Web Dashboard (Default / Recommended):
```powershell
python run.py --paper
```
Open your browser to: **`http://localhost:8080`** to monitor your live telemetry, positions, and AI evaluations.

#### Live Futures Trading (Real Money):
```powershell
python run.py --live
```

#### Verification / Test Pipeline Mode:
```powershell
python run.py --test
```

---

## 📱 Telegram Remote Commands

| Command | Action |
| :--- | :--- |
| `/status` | View open positions, daily PnL, win rate, and active regime |
| `/balance` | Check current wallet equity and margin commitments |
| `/regime` | Real-time ADX & 200 EMA market regime classification |
| `/long SYMBOL` | Evaluate and enter a Long position via confluence gates |
| `/short SYMBOL` | Evaluate and enter a Short position via confluence gates |
| `/close SYMBOL` | Close a specific open position immediately |
| `/panic` | **Emergency Circuit Breaker:** Market-close all active positions |
| `/pause` / `/resume` | Pause or resume automated entries |
