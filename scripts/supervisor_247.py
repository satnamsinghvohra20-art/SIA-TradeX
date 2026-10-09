#!/usr/bin/env python3
"""
SIA-TradeX: 24/7 Autonomous Supervisor & Resilient Engine Runner
Guarantees 24/7 continuous operation without crashing or terminating:
- Infinite auto-healing supervisor loop
- Multi-Key Gemini API failover & auto-rotation on HTTP 429 quota exhaustion
- Continuous live Binance Futures WebSocket and REST market streams
- Real-time paper trade execution and profit protection (TP1, TP2, Trailing Stop, Profit Protector)
- Direct WhatsApp alerts to Owner (+91 84210 77613) on every key trade event
"""

import os
import sys
import time
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn
from config.settings import settings
from engine import QuantEngine
from ui.web_server import app
from ui.whatsapp_service import whatsapp_service
from ai.gemini_service import gemini_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("SIA-TradeX.24-7-Supervisor")


class AutonomousSupervisor:
    def __init__(self, port: int = 8080):
        self.port = port
        self.engine = None
        self.running = True
        self.restart_count = 0

    def start_web_server(self):
        """Starts the FastAPI Web Dashboard in a daemon thread."""
        def _run():
            try:
                uvicorn.run(app, host=settings.WEB_HOST, port=self.port, log_level="warning")
            except Exception as e:
                logger.error(f"Web server error: {e}")

        t = threading.Thread(target=_run, daemon=True, name="web_server_thread")
        t.start()
        print(f"[*] Cyber-Quant Web Dashboard active at: http://localhost:{self.port}")

    def start_periodic_portfolio_reporter(self, interval_seconds: int = 7200):
        """Dispatches full portfolio, invested capital, remaining balance, and PnL breakdown to owner periodically."""
        def _run():
            time.sleep(60)  # Wait 1 minute after boot
            while self.running:
                try:
                    if self.engine and self.engine.running:
                        logger.info("Sending periodic portfolio ledger update to Owner WhatsApp...")
                        self.engine.send_portfolio_summary_to_owner()
                except Exception as e:
                    logger.warning(f"Periodic portfolio reporter error: {e}")
                time.sleep(interval_seconds)

        t = threading.Thread(target=_run, daemon=True, name="periodic_portfolio_reporter")
        t.start()

    def run_forever(self):
        print("=================================================================")
        print("SIA-TradeX: STARTING 24/7 AUTONOMOUS RESILIENT TRADING SUPERVISOR")
        print("Mode: PAPER SIMULATOR (Risk-Free Fake Money Trading)")
        print("Live Feed: 100% Real Live Binance Futures Mainnet")
        print(f"Owner Phone: +{whatsapp_service.owner_phone} (Owner Alerts Only)")
        rot_status = gemini_service.rotator.get_status()
        print(f"Gemini Key Pool: {rot_status['total_keys']} key(s) loaded (Auto-Rotating on 429)")
        print("=================================================================\n")

        self.start_web_server()
        self.start_periodic_portfolio_reporter(interval_seconds=7200)

        while self.running:
            try:
                self.restart_count += 1
                logger.info(f"Starting QuantEngine instance (Lifecycle cycle #{self.restart_count})...")
                self.engine = QuantEngine(live_mode=False)

                # Send 24/7 startup heartbeat to Owner on first boot
                if self.restart_count == 1:
                    now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")
                    whatsapp_service.send_owner_alert(
                        f"🛡️ *SIA-TradeX: 24/7 AI System Active!* 💖\n\n"
                        f"Satnam ji, Namaste! Main Sia hoon. Aapka autonomous quantitative trading engine ab **24/7 continuous live monitoring mode** me start ho chuka hai ({now_str}).\n\n"
                        f"• Execution Mode: *Paper Simulator ($1,000 USDT)*\n"
                        f"• Market Feed: *100% Real Live Binance Futures*\n"
                        f"• Gemini Key Pool: *{rot_status['total_keys']} Key(s) (Auto-Failover Active)*\n"
                        f"• Multi-Tier Targets: *TP1 (Lock 50% & BE) + TP2 + Profit Protector*\n\n"
                        f"Main lagatar real-time market scan kar rahi hoon aur jaise hi profit hits honge, aapko instant update doongi! 💖✨"
                    )

                # Run the continuous engine
                self.engine.run()

            except KeyboardInterrupt:
                print("\n[SUPERVISOR] Graceful shutdown requested by user.")
                self.running = False
                if self.engine:
                    self.engine.stop()
                break
            except Exception as e:
                logger.error(f"[SUPERVISOR] Engine encountered error: {e}. Auto-recovering in 5 seconds...")
                time.sleep(5.0)


if __name__ == "__main__":
    supervisor = AutonomousSupervisor(port=settings.WEB_PORT)
    supervisor.run_forever()
