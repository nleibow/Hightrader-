"""Live risk governor: the layer that keeps an eval alive.

Wraps every order decision with hard limits derived from the firm profile,
with safety margins INSIDE the firm's limits — you never want to be within
slippage distance of a breach. Most eval failures are not strategy failures;
they are risk failures (revenge sizing, trading through the daily stop).
This module makes those failures structurally impossible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..firms.rules import AccountTracker, FirmProfile, Status


class Verdict(Enum):
    ALLOW = "allow"
    REDUCE = "reduce"  # allowed at reduced size (see max_risk)
    BLOCK_DAILY = "block_daily_stop"
    BLOCK_BUFFER = "block_drawdown_buffer"
    BLOCK_HALTED = "block_halted"


@dataclass
class Decision:
    verdict: Verdict
    max_risk: float  # max dollars of risk approved for this trade
    reason: str = ""


@dataclass
class RiskGovernor:
    """Pre-trade gatekeeper. Ask it before every order.

    soft_daily_stop_fraction: stop trading for the day after losing this
      fraction of the firm's daily allowance (default trade no closer than
      60% of the way to a daily breach).
    buffer_margin_fraction: keep this fraction of the total drawdown buffer
      untouchable (slippage / gap insurance).
    max_risk_per_trade_fraction: risk per trade as a fraction of the
      *remaining* drawdown buffer — this is what prevents gambler's ruin.
    """

    profile: FirmProfile
    tracker: AccountTracker
    soft_daily_stop_fraction: float = 0.60
    buffer_margin_fraction: float = 0.15
    max_risk_per_trade_fraction: float = 0.10
    max_trades_per_day: int = 6
    halted: bool = field(default=False, init=False)
    trades_today: int = field(default=0, init=False)

    def kill_switch(self, reason: str = "manual") -> None:
        """Permanent halt: flatten everything and stop. Manual reset only."""
        self.halted = True
        self._halt_reason = reason

    def new_day(self) -> None:
        self.trades_today = 0

    def check(self, proposed_risk: float) -> Decision:
        if self.halted or self.tracker.status is not Status.ACTIVE:
            return Decision(Verdict.BLOCK_HALTED, 0.0, "governor halted / eval over")

        if self.trades_today >= self.max_trades_per_day:
            return Decision(Verdict.BLOCK_DAILY, 0.0, "max trades per day reached")

        # Daily soft stop: leave room so an open position's drawdown cannot
        # take us through the firm's daily limit.
        daily_allow = self.tracker.daily_buffer
        if daily_allow != float("inf"):
            soft_remaining = (
                self.soft_daily_stop_fraction * self.profile.max_daily_loss
                + self.tracker.day_realized
            )
            if soft_remaining <= 0:
                return Decision(Verdict.BLOCK_DAILY, 0.0, "soft daily stop hit")
        else:
            soft_remaining = float("inf")

        # Total buffer: keep a reserved margin below us at all times.
        buffer = self.tracker.drawdown_buffer
        reserved = self.buffer_margin_fraction * self.profile.max_total_drawdown
        usable = buffer - reserved
        if usable <= 0:
            return Decision(Verdict.BLOCK_BUFFER, 0.0, "drawdown buffer reserve hit")

        cap = min(
            self.max_risk_per_trade_fraction * buffer,
            soft_remaining,
            usable,
        )
        if proposed_risk <= cap:
            return Decision(Verdict.ALLOW, proposed_risk)
        if cap > 0:
            return Decision(Verdict.REDUCE, cap, f"risk capped {proposed_risk:.0f}->{cap:.0f}")
        return Decision(Verdict.BLOCK_BUFFER, 0.0, "no risk capacity")

    def record_trade_opened(self) -> None:
        self.trades_today += 1


def contracts_for_risk(
    risk_dollars: float, stop_distance_points: float, point_value: float
) -> int:
    """Position size from approved risk and stop distance. Floors at 0 —
    if even 1 contract risks more than approved, do not trade."""
    if stop_distance_points <= 0:
        return 0
    per_contract = stop_distance_points * point_value
    return int(risk_dollars // per_contract)
