import pytest
from execution.binance_executor import BinanceExecutor
from execution.smart_router import SmartOrderRouter


class MockBinanceClient:
    def __init__(self):
        self.orders_created = []
        self.orders_canceled = []

    def futures_create_order(self, **kwargs):
        self.orders_created.append(kwargs)
        return {
            "orderId": 12345,
            "status": "NEW",
            "avgPrice": kwargs.get("price", "60000.0"),
            "executedQty": "0.0"
        }

    def futures_get_order(self, symbol, orderId):
        return {
            "orderId": orderId,
            "status": "NEW",
            "executedQty": "0.0"
        }

    def futures_cancel_order(self, symbol, orderId):
        self.orders_canceled.append((symbol, orderId))
        return {"status": "CANCELED", "executedQty": "0.0"}

    def futures_cancel_all_open_orders(self, symbol):
        self.orders_canceled.append((symbol, "ALL"))
        return {"code": 200, "msg": "success"}


def test_executor_precision_rounding():
    executor = BinanceExecutor()
    executor._sym_info = {
        "BTCUSDT": {"step": 0.001, "min_qty": 0.001, "tick": 0.10},
        "ETHUSDT": {"step": 0.01, "min_qty": 0.01, "tick": 0.01},
        "DOGEUSDT": {"step": 1.0, "min_qty": 1.0, "tick": 0.00001},
    }

    assert executor.round_qty("BTCUSDT", 0.123456) == 0.123
    assert executor.round_price("BTCUSDT", 65432.18) == 65432.20

    assert executor.round_qty("ETHUSDT", 1.5678) == 1.56
    assert executor.round_price("ETHUSDT", 3456.789) == 3456.79

    assert executor.round_qty("DOGEUSDT", 253.9) == 253.0
    assert executor.round_price("DOGEUSDT", 0.1234567) == 0.12346


def test_router_partial_fill_calculation():
    executor = BinanceExecutor()
    executor.connected = True
    executor.client = MockBinanceClient()
    executor._sym_info = {"BTCUSDT": {"step": 0.001, "min_qty": 0.001, "tick": 0.10}}

    router = SmartOrderRouter(executor)
    router.post_only_timeout_sec = 0.01  # fast timeout

    # Execute maker-first order
    order, levels = router.execute_maker_first_order(
        symbol="BTCUSDT",
        direction="LONG",
        usdt_size=30.0,
        tp=65000.0,
        tp2=66000.0,
        sl=60000.0
    )

    # Verify orders were created
    assert order is not None
    assert levels is not None
    # Verify bracket orders did NOT include invalid timeInForce="GTE_GTC"
    for o in executor.client.orders_created:
        if o.get("type") in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            assert "timeInForce" not in o
            assert o.get("closePosition") is True


def test_executor_close_cancels_orphan_orders():
    executor = BinanceExecutor()
    executor.client = MockBinanceClient()
    executor._sym_info = {"BTCUSDT": {"step": 0.001, "min_qty": 0.001, "tick": 0.10}}

    ok = executor.close_market_position(symbol="BTCUSDT", direction="LONG", qty=0.01)
    assert ok is True
    # Verify futures_cancel_all_open_orders was called to eliminate orphan orders
    assert ("BTCUSDT", "ALL") in executor.client.orders_canceled
