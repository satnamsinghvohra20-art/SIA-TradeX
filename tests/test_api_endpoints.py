import pytest
from fastapi.testclient import TestClient
from ui.web_server import app, set_engine


class MockEngine:
    def __init__(self):
        self.live_mode = False
        self.ai_trading_active = True

    def get_dashboard_snapshot(self):
        return {
            "live_mode": self.live_mode,
            "ai_trading_active": self.ai_trading_active,
            "equity": 1000.0,
            "daily_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "positions_count": 0,
            "max_positions": 150,
            "portfolio_heat": 0.0,
            "regime": "RANGING",
            "positions": [],
            "ticker_prices": {"BTCUSDT": 65000.0},
            "recent_liquidations": [],
            "latest_ai_event": None,
            "gemini_rotator": {"total_keys": 1, "active_key_index": 1, "rotations_count": 0},
            "world_time_utc": "2026-10-10 00:00:00 UTC",
            "local_time": "05:30:00",
            "timestamp": "00:00:00 UTC"
        }

    def toggle_ai_trading(self):
        self.ai_trading_active = not self.ai_trading_active
        return self.ai_trading_active

    def set_ai_trading(self, active: bool):
        self.ai_trading_active = active
        return self.ai_trading_active

    def set_live_mode(self, live: bool):
        self.live_mode = live
        return f"Switched to {'LIVE' if live else 'PAPER'} mode."

    def scan_universe_confluence(self):
        return 0

    def force_close_all(self):
        return "All positions closed."

    def stop_ai_and_flatten_all(self):
        self.ai_trading_active = False
        return "AI Stopped & All positions closed."

    def reset_all_trades_and_account(self):
        return "Account reset to $1000."

    def force_close_symbol(self, target: str):
        return f"Closed 1 position for {target}."

    def send_portfolio_summary_to_owner(self):
        return "Portfolio status sent to Owner WhatsApp."

    def inject_manual_trade(self, symbol, direction, size, force):
        pass


@pytest.fixture(autouse=True)
def setup_mock_engine():
    mock = MockEngine()
    set_engine(mock)
    return mock


@pytest.fixture
def client():
    return TestClient(app)


def test_get_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "SIA-TradeX Pro" in res.text


def test_api_state(client):
    res = client.get("/api/state")
    assert res.status_code == 200
    data = res.json()
    assert "equity" in data
    assert data["live_mode"] is False
    assert "gemini_rotator" in data


def test_api_mode_toggle(client):
    res = client.post("/api/mode/toggle")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["live_mode"] is True

    # Toggle back to paper
    res2 = client.post("/api/mode/toggle")
    assert res2.status_code == 200
    assert res2.json()["live_mode"] is False


def test_api_ai_toggle(client):
    res = client.post("/api/ai/toggle")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["ai_trading_active"] is False


def test_api_ai_rotate_key(client):
    res = client.post("/api/ai/rotate-key")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "total_keys" in data


def test_api_ai_scan_now(client):
    res = client.post("/api/ai/scan-now")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "opened" in data


def test_api_panic_and_flatten(client):
    res = client.post("/api/panic")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_stop = client.post("/api/stop-all")
    assert res_stop.status_code == 200
    assert res_stop.json()["ai_trading_active"] is False

    res_reset = client.post("/api/reset")
    assert res_reset.status_code == 200
    assert res_reset.json()["status"] == "ok"


def test_api_manual_trade(client):
    res = client.post("/api/trade", json={
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "size": 25.0,
        "force": False
    })
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_api_status(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "equity" in data
    assert data["equity"] == 1000.0


def test_api_portfolio_notify(client):
    res = client.post("/api/portfolio/notify")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "Portfolio status" in data["message"]
