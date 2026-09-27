"""
SIA-TradeX: Quantitative Risk Management & Guardrails
Enforces portfolio heat constraints, correlation clustering limits, and daily loss circuit breakers.
"""

from typing import Dict, Tuple
from config.settings import settings
from core.models import Position


class RiskManager:
    def __init__(self):
        pass

    def check_guardrails(
        self,
        daily_pnl: float,
        consecutive_losses: int,
        current_balance: float
    ) -> Tuple[bool, str]:
        """Validates hard safety stops before opening any position."""
        if daily_pnl <= -settings.DAILY_LOSS_LIMIT:
            return False, f"Daily Loss Limit hit (-${settings.DAILY_LOSS_LIMIT:.2f})"

        if daily_pnl >= settings.DAILY_PROFIT_TARGET:
            return False, f"Daily Profit Target reached (+${settings.DAILY_PROFIT_TARGET:.2f})"

        if consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            return False, f"{settings.MAX_CONSECUTIVE_LOSSES} consecutive losses trigger cooldown"

        if current_balance < settings.MIN_TRADE_USDT * 1.5:
            return False, f"Insufficient balance (${current_balance:.2f}) for minimum risk unit"

        return True, ""

    def check_correlation_exposure(
        self,
        symbol: str,
        direction: str,
        open_positions: Dict[str, Position],
        equity: float
    ) -> Tuple[bool, str]:
        """
        Prevents over-concentration in correlated asset groups (e.g. BTC, ETH L2s, Memes).
        """
        for group_name, group_symbols in settings.CORRELATION_GROUPS.items():
            if symbol not in group_symbols:
                continue

            # Calculate current total margin exposed to this correlation cluster in same direction
            cluster_exposure = sum(
                p.usdt_size for sym, p in open_positions.items()
                if sym in group_symbols and p.direction == direction
            )

            max_allowed = equity * settings.CORRELATION_LIMIT_PCT
            if cluster_exposure + settings.MIN_TRADE_USDT > max_allowed:
                return True, f"Correlation limit for {group_name} exceeded (${cluster_exposure:.1f} >= ${max_allowed:.1f})"

        return False, ""

    def check_portfolio_heat(
        self,
        open_positions: Dict[str, Position],
        new_usdt_size: float,
        equity: float
    ) -> Tuple[bool, str]:
        """
        Ensures total active margin exposure does not exceed MAX_PORTFOLIO_HEAT (50%).
        """
        current_heat = sum(p.usdt_size for p in open_positions.values())
        if (current_heat + new_usdt_size) > (equity * settings.MAX_PORTFOLIO_HEAT):
            return False, f"Portfolio heat cap ({settings.MAX_PORTFOLIO_HEAT*100:.0f}%) reached (${current_heat:.1f}/${equity:.1f})"
        return True, ""


risk_manager = RiskManager()
