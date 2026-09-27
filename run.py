"""
SIA-TradeX Pro: Autonomous AI Trading Engine
Main executable CLI with support for Paper/Live modes, Web Dashboard, and pipeline verification.
"""

import sys
import time
import argparse
import threading
import uvicorn
from colorama import init, Fore, Style

from config.settings import settings
from engine import QuantEngine
from ui.web_server import app, broadcast_state

init(autoreset=True)
G = Fore.GREEN; R = Fore.RED; Y = Fore.YELLOW; C = Fore.CYAN; W = Fore.WHITE; RST = Style.RESET_ALL; BR = Style.BRIGHT


def print_banner(live_mode: bool, web_enabled: bool, port: int):
    mode_text = f"{R}{BR}LIVE BINANCE FUTURES{RST}" if live_mode else f"{G}{BR}PAPER SIMULATOR (Risk-Free){RST}"
    net_text = f"{Y}TESTNET{RST}" if settings.BINANCE_TESTNET else f"{R}MAINNET{RST}"
    ai_status = f"{G}ONLINE ({settings.GEMINI_MODEL}){RST}" if settings.GEMINI_API_KEY else f"{R}NO KEY{RST}"
    web_status = f"{C}http://localhost:{port}{RST}" if web_enabled else f"{Y}Disabled{RST}"

    print(f"""
{C}======================================================================{RST}
  {C}{BR}SIA-TradeX Pro{RST}  |  Autonomous Quantitative Intelligence Engine
  Institutional-Grade Multi-Source Fusion & Regime Detection
{C}======================================================================{RST}
  Execution Mode  : {mode_text}
  Binance Network : {net_text}
  AI Engine       : {ai_status}
  Web Dashboard   : {web_status}
  Leverage / Sizing: {settings.DEFAULT_LEVERAGE}x  |  {settings.RISK_PER_TRADE_PCT}% risk/trade
  Circuit Breaker : -${settings.DAILY_LOSS_LIMIT:.2f} max daily loss  |  +${settings.DAILY_PROFIT_TARGET:.2f} target
{C}======================================================================{RST}
""")


def main():
    parser = argparse.ArgumentParser(description="SIA-TradeX Pro Quant Trading System")
    parser.add_argument("--live", action="store_true", help="Enable Live Binance Futures execution (Real Money)")
    parser.add_argument("--web", action="store_true", default=True, help="Launch real-time Web Dashboard (default: True)")
    parser.add_argument("--no-web", action="store_true", help="Disable Web Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Web dashboard port (default: 8080)")
    parser.add_argument("--test", action="store_true", help="Inject test signal to verify end-to-end pipeline")
    args = parser.parse_args()

    live_mode = bool(args.live)
    web_enabled = not args.no_web

    print_banner(live_mode, web_enabled, args.port)

    if live_mode:
        print(f"{R}{BR}CAUTION: LIVE EXECUTION SELECTED WITH REAL FUNDS.{RST}")
        confirm = input("Type 'YES I UNDERSTAND' to proceed with real orders: ").strip()
        if confirm != "YES I UNDERSTAND":
            print(f"{Y}Live execution aborted by user.{RST}")
            sys.exit(0)

    # Initialize Engine
    engine = QuantEngine(live_mode=live_mode)

    # Launch Web Server if requested
    if web_enabled:
        def _run_web():
            uvicorn.run(app, host=settings.WEB_HOST, port=args.port, log_level="warning")

        web_thread = threading.Thread(target=_run_web, daemon=True, name="web_server")
        web_thread.start()
        print(f"🚀 {G}Cyber-Quant Web Dashboard available at: {C}http://localhost:{args.port}{RST}\n")

    # Start engine in background thread
    engine_thread = threading.Thread(target=engine.run, daemon=True, name="quant_engine")
    engine_thread.start()

    if args.test:
        print(f"{Y}[TEST] Injecting pipeline test signal on BTCUSDT in 3 seconds...{RST}")
        time.sleep(3)
        engine.inject_manual_trade("BTCUSDT", "LONG", size=25.0, force=True)

    print(f"{W}Engine running. Press {Y}Ctrl+C{W} to gracefully shut down.{RST}\n")

    try:
        while True:
            # Console status tick
            time.sleep(2)
    except KeyboardInterrupt:
        print(f"\n{Y}Shutting down SIA-TradeX Pro cleanly...{RST}")
        engine.stop()
        print(f"{G}All subsystems terminated.{RST}")


if __name__ == "__main__":
    main()
