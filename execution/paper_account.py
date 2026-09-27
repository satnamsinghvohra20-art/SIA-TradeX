"""
SIA-TradeX: High-Fidelity Paper Trading Simulator
Realistic margin reservation, maker/taker fee accounting, and equity tracking.
"""

import threading
from typing import Dict, Optional, Callable
from config.settings import settings
from core.models import Position
from storage.database import db


class PaperAccount:
    def __init__(self, starting_balance: float = settings.PAPER_STARTING_BALANCE):
        self._lock = threading.Lock()
        self.cash = starting_balance
        self.realized_pnl = 0.0
        self.taker_fee_pct = 0.0005  # 0.05% Binance taker fee

    def total_equity(self, open_positions: Dict[str, Position], get_price_fn: Callable[[str], Optional[float]]) -> float:
        with self._lock:
            total = self.cash

        for key, pos in open_positions.items():
            price = get_price_fn(pos.symbol)
            if price is None or price <= 0:
                total += pos.usdt_size
                continue

            mult = pos.leverage * pos.usdt_size
            if pos.direction == "LONG":
                upnl = ((price - pos.entry) / pos.entry) * mult
            else:
                upnl = ((pos.entry - price) / pos.entry) * mult
            total += pos.usdt_size + upnl

        return total

    def reserve_margin(self, usdt_size: float) -> bool:
        with self._lock:
            fee = usdt_size * self.taker_fee_pct * settings.DEFAULT_LEVERAGE
            total_required = usdt_size + fee
            if self.cash < total_required:
                return False
            self.cash -= total_required
            return True

    def release_margin(self, usdt_size: float, pnl: float):
        with self._lock:
            exit_fee = usdt_size * self.taker_fee_pct * settings.DEFAULT_LEVERAGE
            net_pnl = pnl - exit_fee
            self.cash += usdt_size + net_pnl
            self.realized_pnl += net_pnl

    def snapshot(self, open_positions: Dict[str, Position], get_price_fn: Callable[[str], Optional[float]]):
        eq = self.total_equity(open_positions, get_price_fn)
        upnl = eq - (self.cash + sum(p.usdt_size for p in open_positions.values()))
        db.record_equity_snapshot(
            balance=round(self.cash, 2),
            equity=round(eq, 2),
            unrealized_pnl=round(upnl, 2),
            open_positions=len(open_positions)
        )
