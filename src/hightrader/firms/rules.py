"""Prop firm evaluation rule engine.

Models the account-level constraints that decide whether an evaluation is
passed or failed, independent of any strategy. The three drawdown mechanics
used across the industry are all supported:

- ``static``: hard floor at ``initial_balance - max_total_drawdown`` (FTMO).
- ``trailing_eod``: floor trails the end-of-day balance high-water mark and
  locks once it reaches the initial balance (Topstep).
- ``trailing_intraday``: floor trails the *intraday* equity high-water mark
  and locks at ``initial_balance + lock_offset`` (Apex).

Daily loss is measured the FTMO way: the day's realized P&L plus the worst
open floating P&L may not reach ``-max_daily_loss``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Status(Enum):
    ACTIVE = "active"
    PASSED = "passed"
    FAILED_DAILY_LOSS = "failed_daily_loss"
    FAILED_DRAWDOWN = "failed_drawdown"
    FAILED_TIME = "failed_time"


class DrawdownMode(Enum):
    STATIC = "static"
    TRAILING_EOD = "trailing_eod"
    TRAILING_INTRADAY = "trailing_intraday"


@dataclass(frozen=True)
class FirmProfile:
    """Parameters of one evaluation phase. All money amounts in account currency."""

    name: str
    account_size: float
    profit_target: float
    max_total_drawdown: float
    drawdown_mode: DrawdownMode
    max_daily_loss: Optional[float] = None
    min_trading_days: int = 0
    max_calendar_days: Optional[int] = None
    # Best single day's profit may be at most this fraction of total profit
    # at the time the target is checked (None = no consistency rule).
    consistency_max_day_fraction: Optional[float] = None
    # For TRAILING_INTRADAY: the floor locks once it reaches
    # initial_balance + trailing_lock_offset (Apex locks at +$100).
    trailing_lock_offset: float = 0.0
    notes: str = ""


@dataclass
class TradeFill:
    """One closed trade with its intratrade excursions.

    mae: maximum adverse excursion while open (positive dollars).
    mfe: maximum favorable excursion while open (positive dollars).
    Both default to the trade's own P&L bounds when unknown.
    """

    pnl: float
    mae: float = 0.0
    mfe: float = 0.0

    def __post_init__(self) -> None:
        self.mae = max(self.mae, -min(self.pnl, 0.0))
        self.mfe = max(self.mfe, max(self.pnl, 0.0))


@dataclass
class AccountTracker:
    """Stateful simulator of one evaluation account.

    Drive it with ``apply_trade`` for each closed trade and ``end_day`` at
    each session close. ``status`` flips to a terminal state the moment a
    rule is breached or the target (plus min days / consistency) is met.
    """

    profile: FirmProfile
    balance: float = field(init=False)
    status: Status = field(init=False, default=Status.ACTIVE)
    trading_days: int = field(init=False, default=0)
    calendar_days: int = field(init=False, default=0)
    day_realized: float = field(init=False, default=0.0)
    day_traded: bool = field(init=False, default=False)
    best_day: float = field(init=False, default=0.0)
    _eod_high: float = field(init=False)
    _intraday_high: float = field(init=False)
    _floor: float = field(init=False)

    def __post_init__(self) -> None:
        p = self.profile
        self.balance = p.account_size
        self._eod_high = p.account_size
        self._intraday_high = p.account_size
        self._floor = self._compute_floor()

    # ------------------------------------------------------------------ #

    def _compute_floor(self) -> float:
        p = self.profile
        if p.drawdown_mode is DrawdownMode.STATIC:
            return p.account_size - p.max_total_drawdown
        if p.drawdown_mode is DrawdownMode.TRAILING_EOD:
            return min(self._eod_high - p.max_total_drawdown, p.account_size)
        # TRAILING_INTRADAY
        return min(
            self._intraday_high - p.max_total_drawdown,
            p.account_size + p.trailing_lock_offset,
        )

    @property
    def loss_floor(self) -> float:
        """Equity level at which the account is breached."""
        return self._floor

    @property
    def drawdown_buffer(self) -> float:
        """Dollars of room between current balance and the breach floor."""
        return self.balance - self._floor

    @property
    def daily_buffer(self) -> float:
        """Dollars of further loss allowed today before a daily-loss breach."""
        if self.profile.max_daily_loss is None:
            return float("inf")
        return self.profile.max_daily_loss + self.day_realized

    @property
    def target_balance(self) -> float:
        return self.profile.account_size + self.profile.profit_target

    @property
    def to_target(self) -> float:
        return max(self.target_balance - self.balance, 0.0)

    # ------------------------------------------------------------------ #

    def apply_trade(self, trade: TradeFill) -> Status:
        if self.status is not Status.ACTIVE:
            return self.status
        p = self.profile
        self.day_traded = True

        worst_equity = self.balance - trade.mae
        best_equity = self.balance + trade.mfe

        # Daily loss check at the worst open mark of the trade.
        if p.max_daily_loss is not None:
            if self.day_realized - trade.mae <= -p.max_daily_loss:
                self.status = Status.FAILED_DAILY_LOSS
                return self.status

        # Intraday trailing accounts mark the floor against live equity, and
        # the high-water mark also updates intraday. Check breach at the
        # worst mark using the floor as of trade entry (conservative: the
        # favorable excursion could have come first and raised the floor,
        # but we cannot know the order, so breach is checked first).
        if p.drawdown_mode is DrawdownMode.TRAILING_INTRADAY:
            if worst_equity <= self._floor:
                self.status = Status.FAILED_DRAWDOWN
                return self.status
            self._intraday_high = max(self._intraday_high, best_equity)
        else:
            if worst_equity <= self._floor:
                self.status = Status.FAILED_DRAWDOWN
                return self.status

        self.balance += trade.pnl
        self.day_realized += trade.pnl

        if p.drawdown_mode is DrawdownMode.TRAILING_INTRADAY:
            self._intraday_high = max(self._intraday_high, self.balance)
            self._floor = self._compute_floor()

        # Closed-balance breach (e.g. realized loss through the floor).
        if self.balance <= self._floor:
            self.status = Status.FAILED_DRAWDOWN
            return self.status
        if p.max_daily_loss is not None and self.day_realized <= -p.max_daily_loss:
            self.status = Status.FAILED_DAILY_LOSS
            return self.status

        return self.status

    def end_day(self) -> Status:
        if self.status is not Status.ACTIVE:
            return self.status
        p = self.profile
        self.calendar_days += 1
        if self.day_traded:
            self.trading_days += 1
            self.best_day = max(self.best_day, self.day_realized)
        self.day_realized = 0.0
        self.day_traded = False

        if p.drawdown_mode is DrawdownMode.TRAILING_EOD:
            self._eod_high = max(self._eod_high, self.balance)
            self._floor = self._compute_floor()

        if self._target_met():
            self.status = Status.PASSED
        elif p.max_calendar_days is not None and self.calendar_days >= p.max_calendar_days:
            self.status = Status.FAILED_TIME
        return self.status

    def _target_met(self) -> bool:
        p = self.profile
        profit = self.balance - p.account_size
        if profit < p.profit_target:
            return False
        if self.trading_days < p.min_trading_days:
            return False
        if p.consistency_max_day_fraction is not None and profit > 0:
            if self.best_day > p.consistency_max_day_fraction * profit:
                return False
        return True
