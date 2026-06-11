"""Trade-list statistics: the inputs the Monte Carlo evaluator needs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import numpy as np

from .engine import Trade


@dataclass
class TradeStats:
    n_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float  # positive number
    expectancy: float  # avg $ per trade
    profit_factor: float
    max_consecutive_losses: int
    avg_trades_per_day: float
    pnl_per_day_std: float
    total_pnl: float

    def summary(self) -> str:
        return (
            f"trades={self.n_trades}  win%={self.win_rate:.1%}  "
            f"avgW=${self.avg_win:,.0f}  avgL=${self.avg_loss:,.0f}  "
            f"expectancy=${self.expectancy:,.2f}/trade  PF={self.profit_factor:.2f}  "
            f"maxConsecL={self.max_consecutive_losses}  "
            f"trades/day={self.avg_trades_per_day:.1f}  total=${self.total_pnl:,.0f}"
        )


def compute_stats(trades: Sequence[Trade]) -> TradeStats:
    if not trades:
        return TradeStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    pnls = np.array([t.pnl for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    days = {t.exit_time.date() for t in trades}

    streak = max_streak = 0
    for p in pnls:
        streak = streak + 1 if p <= 0 else 0
        max_streak = max(max_streak, streak)

    day_pnls: dict = {}
    for t in trades:
        day_pnls[t.exit_time.date()] = day_pnls.get(t.exit_time.date(), 0.0) + t.pnl

    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0

    return TradeStats(
        n_trades=len(pnls),
        win_rate=len(wins) / len(pnls),
        avg_win=float(wins.mean()) if len(wins) else 0.0,
        avg_loss=float(-losses.mean()) if len(losses) else 0.0,
        expectancy=float(pnls.mean()),
        profit_factor=float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        max_consecutive_losses=max_streak,
        avg_trades_per_day=len(pnls) / len(days),
        pnl_per_day_std=float(np.std(list(day_pnls.values()))),
        total_pnl=float(pnls.sum()),
    )


def trades_by_day(trades: Sequence[Trade]) -> List[List[Trade]]:
    """Group trades into per-day lists, preserving order."""
    out: List[List[Trade]] = []
    cur_day = None
    for t in sorted(trades, key=lambda t: t.exit_time):
        d = t.exit_time.date()
        if d != cur_day:
            out.append([])
            cur_day = d
        out[-1].append(t)
    return out
