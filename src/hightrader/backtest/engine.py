"""Bar-driven backtest engine with conservative execution assumptions.

Fill model:
- Entries fill at next bar open plus slippage.
- Stops/targets are evaluated intrabar; if a bar's range contains both the
  stop and the target, the STOP is assumed to fill (worst case).
- Commission and slippage are charged on every side.

These pessimistic assumptions matter: a strategy that only works with
optimistic fills will not survive a prop eval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Instrument:
    symbol: str
    point_value: float  # dollars per 1.0 price point per contract
    tick_size: float
    commission_per_side: float  # dollars per contract per side
    slippage_ticks: float = 1.0

    @property
    def slippage_points(self) -> float:
        return self.slippage_ticks * self.tick_size


# Common futures specs (verify with your broker).
ES = Instrument("ES", point_value=50.0, tick_size=0.25, commission_per_side=2.25)
MES = Instrument("MES", point_value=5.0, tick_size=0.25, commission_per_side=0.62)
NQ = Instrument("NQ", point_value=20.0, tick_size=0.25, commission_per_side=2.25)
MNQ = Instrument("MNQ", point_value=2.0, tick_size=0.25, commission_per_side=0.62)


@dataclass(frozen=True)
class Signal:
    """Emitted by a strategy: enter on the NEXT bar open."""

    direction: int  # +1 long, -1 short
    stop: float  # absolute price
    target: Optional[float] = None  # absolute price; None = exit on flat rule


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int
    entry_price: float
    exit_price: float
    contracts: int
    pnl: float  # dollars, net of costs
    mae: float  # dollars, max adverse excursion while open (positive)
    mfe: float  # dollars, max favorable excursion while open (positive)
    exit_reason: str

    @property
    def r_multiple(self) -> Optional[float]:
        return None  # filled in by engine when risk is known

    day = property(lambda self: self.exit_time.date())


class Strategy:
    """Subclass and implement prepare() and signal()."""

    #: flatten any open position at the last bar of each session
    flat_eod: bool = True

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Precompute indicator columns. Must not look ahead."""
        return df

    def signal(self, i: int, df: pd.DataFrame) -> Optional[Signal]:
        """Return a Signal to enter on bar i+1's open, or None."""
        raise NotImplementedError


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    instrument: Instrument,
    contracts: int = 1,
    max_trades_per_day: Optional[int] = None,
) -> List[Trade]:
    """Run a strategy over OHLCV bars (DatetimeIndex; columns open/high/low/close).

    One position at a time. Returns the list of closed trades.
    """
    df = strategy.prepare(df.copy())
    idx = df.index
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    low = df["low"].to_numpy()
    c = df["close"].to_numpy()
    dates = np.array([t.date() for t in idx])
    n = len(df)
    slip = instrument.slippage_points
    cost_per_trade = 2 * (
        instrument.commission_per_side * contracts
    )  # both sides; slippage applied in price

    trades: List[Trade] = []
    pos_dir = 0
    entry_px = stop_px = 0.0
    target_px: Optional[float] = None
    entry_i = -1
    pending: Optional[Signal] = None
    day_trades = 0
    cur_day = None

    def close_position(i: int, price: float, reason: str) -> None:
        nonlocal pos_dir
        raw = (price - entry_px) * pos_dir * instrument.point_value * contracts
        pnl = raw - cost_per_trade
        span_h = h[entry_i : i + 1]
        span_l = low[entry_i : i + 1]
        if pos_dir > 0:
            mae = max((entry_px - span_l.min()), 0.0)
            mfe = max((span_h.max() - entry_px), 0.0)
        else:
            mae = max((span_h.max() - entry_px), 0.0)
            mfe = max((entry_px - span_l.min()), 0.0)
        trades.append(
            Trade(
                entry_time=idx[entry_i],
                exit_time=idx[i],
                direction=pos_dir,
                entry_price=entry_px,
                exit_price=price,
                contracts=contracts,
                pnl=pnl,
                mae=mae * instrument.point_value * contracts,
                mfe=mfe * instrument.point_value * contracts,
                exit_reason=reason,
            )
        )
        pos_dir = 0

    for i in range(n):
        if dates[i] != cur_day:
            cur_day = dates[i]
            day_trades = 0
        last_bar_of_day = i == n - 1 or dates[i + 1] != cur_day

        # 1. Fill pending entry at this bar's open.
        if pending is not None and pos_dir == 0:
            pos_dir = pending.direction
            entry_px = o[i] + slip * pos_dir
            stop_px = pending.stop
            target_px = pending.target
            entry_i = i
            day_trades += 1
            pending = None
            # Entry beyond the stop already (gap) -> immediate exit.
            if (pos_dir > 0 and entry_px <= stop_px) or (
                pos_dir < 0 and entry_px >= stop_px
            ):
                close_position(i, entry_px, "gap_stop")

        # 2. Manage open position intrabar: stop first (conservative).
        if pos_dir != 0:
            if pos_dir > 0:
                if low[i] <= stop_px:
                    close_position(i, stop_px - slip, "stop")
                elif target_px is not None and h[i] >= target_px:
                    close_position(i, target_px - slip, "target")
            else:
                if h[i] >= stop_px:
                    close_position(i, stop_px + slip, "stop")
                elif target_px is not None and low[i] <= target_px:
                    close_position(i, target_px + slip, "target")

        # 3. End-of-session flat.
        if pos_dir != 0 and last_bar_of_day and strategy.flat_eod:
            close_position(i, c[i] - slip * pos_dir, "eod")

        # 4. Ask strategy for a new signal (enters next bar).
        if pos_dir == 0 and not last_bar_of_day:
            if max_trades_per_day is None or day_trades < max_trades_per_day:
                pending = strategy.signal(i, df)

    return trades
