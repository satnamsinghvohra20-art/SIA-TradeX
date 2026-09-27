"""
SIA-TradeX: Web Telemetry Server & WebSocket API
FastAPI backend powering the real-time cyber-quant dashboard.
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from config.settings import settings
from storage.database import db

app = FastAPI(title="SIA-TradeX Pro Telemetry API")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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


class ManualTradeRequest(BaseModel):
    symbol: str
    direction: str
    size: Optional[float] = 20.0
    force: bool = False


@app.get("/")
async def get_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
async def start_broadcaster():
    async def _broadcaster():
        while True:
            try:
                if engine_ref and manager.active_connections:
                    snap = engine_ref.get_dashboard_snapshot()
                    await manager.broadcast(snap)
            except Exception:
                pass
            await asyncio.sleep(0.5)

    asyncio.create_task(_broadcaster())


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


def set_engine(engine_instance: Any):
    global engine_ref
    engine_ref = engine_instance


async def broadcast_state(data: Dict[str, Any]):
    await manager.broadcast(data)
