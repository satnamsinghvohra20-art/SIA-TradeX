"""
SIA-TradeX: Web Telemetry Server & WebSocket API
FastAPI backend powering the real-time cyber-quant dashboard.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from config.settings import settings
from storage.database import db

# Shared state reference injected from main engine
engine_ref: Optional[Any] = None


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    async def _broadcaster():
        while True:
            try:
                if engine_ref and manager.active_connections:
                    snap = engine_ref.get_dashboard_snapshot()
                    await manager.broadcast(snap)
            except Exception:
                pass
            await asyncio.sleep(0.5)

    task = asyncio.create_task(_broadcaster())
    yield
    task.cancel()


app = FastAPI(title="SIA-TradeX Pro Telemetry API", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

class ManualTradeRequest(BaseModel):
    symbol: str
    direction: str
    size: Optional[float] = 20.0
    force: bool = False


@app.get("/")
async def get_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def get_status_api():
    """Returns the current engine dashboard snapshot."""
    if engine_ref:
        return engine_ref.get_dashboard_snapshot()
    return {"status": "starting", "message": "Engine initializing"}


@app.get("/api/portfolio/notify")
@app.post("/api/portfolio/notify")
async def notify_portfolio_api():
    """Triggers an instant WhatsApp portfolio & balance summary to Owner."""
    if engine_ref:
        msg = engine_ref.send_portfolio_summary_to_owner()
        return {"status": "ok", "message": msg}
    return {"status": "error", "message": "Engine not attached"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial snapshot immediately upon connection
        if engine_ref:
            await websocket.send_json(engine_ref.get_dashboard_snapshot())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


@app.post("/api/ai/toggle")
async def toggle_ai():
    """Toggles AI autonomous trading on or off."""
    if engine_ref:
        active = engine_ref.toggle_ai_trading()
        # Broadcast immediately to all connected web clients
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {"status": "ok", "ai_trading_active": active, "message": f"AI Autonomous Trading is now {'ACTIVE' if active else 'PAUSED'}"}
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/ai/start")
async def start_ai():
    """Activates AI autonomous trading."""
    if engine_ref:
        active = engine_ref.set_ai_trading(True)
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {"status": "ok", "ai_trading_active": True, "message": "AI Autonomous Trading activated"}
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/ai/stop")
async def stop_ai():
    """Pauses AI autonomous trading."""
    if engine_ref:
        active = engine_ref.set_ai_trading(False)
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {"status": "ok", "ai_trading_active": False, "message": "AI Autonomous Trading paused"}
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/mode/toggle")
async def toggle_trading_mode():
    """Toggles between LIVE Binance Futures mode and PAPER simulation mode."""
    if engine_ref:
        current_live = engine_ref.live_mode
        target_live = not current_live
        msg = engine_ref.set_live_mode(target_live)
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {
            "status": "ok",
            "live_mode": engine_ref.live_mode,
            "message": msg
        }
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/ai/rotate-key")
async def force_rotate_key():
    """Manually rotates to next Google Gemini API key in pool."""
    from ai.gemini_service import gemini_service
    new_key = gemini_service.rotator.rotate("Manual User Request")
    gemini_service._configure_active_key()
    st = gemini_service.rotator.get_status()
    if engine_ref:
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
    return {
        "status": "ok",
        "active_key_index": st["active_key_index"],
        "total_keys": st["total_keys"],
        "message": f"Rotated to Gemini Key #{st['active_key_index']} of {st['total_keys']}"
    }


@app.post("/api/ai/scan-now")
async def force_scan():
    """Triggers an immediate multi-asset universe confluence scan and auto-execution."""
    if engine_ref:
        opened = engine_ref.scan_universe_confluence()
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {
            "status": "ok",
            "opened": opened,
            "message": f"Universe Confluence Scan complete. Opened {opened} position(s)."
        }
    return {"status": "error", "message": "Engine not attached"}


@app.get("/api/ai/status")
async def get_ai_status():
    """Returns whether AI autonomous trading is currently active."""
    if engine_ref:
        return {"status": "ok", "ai_trading_active": engine_ref.ai_trading_active}
    return {"status": "error", "message": "Engine not attached"}


class ClosePositionRequest(BaseModel):
    symbol: Optional[str] = None
    id: Optional[str] = None


@app.get("/api/state")
async def get_current_state():
    """Returns instantaneous engine state snapshot."""
    if engine_ref:
        return engine_ref.get_dashboard_snapshot()
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/panic")
async def panic_close_all():
    """Emergency circuit breaker: market closes all positions immediately."""
    if engine_ref:
        msg = engine_ref.force_close_all()
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {"status": "ok", "message": msg}
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/stop-all")
async def stop_all_and_flatten():
    """Pauses AI trading AND immediately market-closes all open positions."""
    if engine_ref:
        msg = engine_ref.stop_ai_and_flatten_all()
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {"status": "ok", "ai_trading_active": False, "message": msg}
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/reset")
async def reset_journal_and_account():
    """Wipes historical trade journal and resets paper account balance to clean $1,000.00."""
    if engine_ref:
        msg = engine_ref.reset_all_trades_and_account()
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {"status": "ok", "message": msg}
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/close")
async def close_position(req: Optional[ClosePositionRequest] = None, symbol: Optional[str] = None, id: Optional[str] = None):
    """Closes a specific position at market price by position ID or symbol."""
    if engine_ref:
        target = ""
        if req:
            target = req.id or req.symbol or ""
        if not target and id:
            target = id
        if not target and symbol:
            target = symbol
        target = target.strip()
        if not target:
            return {"status": "error", "message": "No symbol or position ID provided"}
        msg = engine_ref.force_close_symbol(target)
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {"status": "ok", "message": msg}
    return {"status": "error", "message": "Engine not attached"}


@app.post("/api/trade")
async def manual_trade(req: ManualTradeRequest):
    """Injects a candidate trade into confluence evaluation."""
    if engine_ref:
        engine_ref.inject_manual_trade(req.symbol.upper(), req.direction.upper(), req.size, req.force)
        await manager.broadcast(engine_ref.get_dashboard_snapshot())
        return {"status": "ok", "message": f"Queued {req.direction} {req.symbol}"}
    return {"status": "error", "message": "Engine not attached"}



@app.get("/api/trades")
async def get_recent_trades():
    return db.get_recent_trades(limit=50)


@app.get("/api/equity")
async def get_equity_curve():
    return db.get_equity_history(limit=500)


@app.get("/api/daily-income")
async def get_daily_income():
    """Returns all daily income ledger records from database."""
    return db.get_all_daily_income()


@app.get("/api/excel/download")
async def download_excel_ledger():
    """Serves the generated multi-tab Excel ledger file for download."""
    from storage.excel_ledger import excel_ledger
    db.sync_excel_ledger()
    if excel_ledger.primary_file.exists():
        return FileResponse(
            excel_ledger.primary_file,
            filename="SIA_TradeX_Income_Ledger.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    return {"status": "error", "message": "Excel ledger not yet generated"}


@app.post("/api/excel/sync")
async def trigger_excel_sync():
    """Forces synchronization of SQLite database to Excel ledger."""
    ok = db.sync_excel_ledger()
    return {"status": "ok" if ok else "error", "synced": ok}


def set_engine(engine_instance: Any):
    global engine_ref
    engine_ref = engine_instance


async def broadcast_state(data: Dict[str, Any]):
    await manager.broadcast(data)
