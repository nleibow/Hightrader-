"""Walk-forward validation: the honesty machine.

For each rolling window, pick strategy parameters on the TRAIN slice only
(by trade-PnL t-statistic, which rewards consistency over lucky outliers),
then run them untouched on the following TEST slice. Concatenated test
trades are the only numbers that matter: they approximate what you would
actually have experienced running the system live and re-tuning
periodically.

If OOS expectancy is negative or unstable across windows, the strategy
does not have edge, no matter how good any single backtest looks.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .engine import Instrument, Strategy, Trade, run_backtest
from .stats import TradeStats, compute_stats

StrategyFactory = Callable[..., Strategy]


def tstat_objective(trades: List[Trade], min_trades: int = 30) -> float:
    """t-statistic of per-trade PnL. -inf below the trade-count floor."""
    if len(trades) < min_trades:
        return float("-inf")
    pnls = np.array([t.pnl for t in trades])
    sd = pnls.std(ddof=1)
    if sd == 0:
        return float("-inf")
    return float(pnls.mean() / sd * np.sqrt(len(pnls)))


def param_grid(**axes: Sequence) -> List[Dict]:
    keys = list(axes)
    return [dict(zip(keys, combo)) for combo in itertools.product(*axes.values())]


@dataclass
class WindowResult:
    train_start: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_params: Optional[Dict]
    train_score: float
    test_trades: List[Trade] = field(default_factory=list)

    @property
    def test_pnl(self) -> float:
        return sum(t.pnl for t in self.test_trades)


@dataclass
class WalkForwardResult:
    windows: List[WindowResult]
    instrument: Instrument

    @property
    def oos_trades(self) -> List[Trade]:
        return [t for w in self.windows for t in w.test_trades]

    @property
    def oos_stats(self) -> TradeStats:
        return compute_stats(self.oos_trades)

    @property
    def positive_window_fraction(self) -> float:
        scored = [w for w in self.windows if w.test_trades]
        if not scored:
            return 0.0
        return sum(1 for w in scored if w.test_pnl > 0) / len(scored)

    def summary(self) -> str:
        s = self.oos_stats
        lines = [
            f"OOS ({len(self.windows)} windows, "
            f"{self.positive_window_fraction:.0%} profitable): {s.summary()}"
        ]
        for w in self.windows:
            n = len(w.test_trades)
            lines.append(
                f"  {w.test_start.date()} -> {w.test_end.date()}  "
                f"params={w.best_params}  trades={n}  pnl=${w.test_pnl:,.0f}"
            )
        return "\n".join(lines)


def walk_forward(
    df: pd.DataFrame,
    factory: StrategyFactory,
    grid: List[Dict],
    instrument: Instrument,
    train_days: int = 504,  # ~2 years of sessions
    test_days: int = 126,  # ~6 months
    contracts: int = 1,
    max_trades_per_day: Optional[int] = 3,
    objective: Callable[[List[Trade]], float] = tstat_objective,
) -> WalkForwardResult:
    """Rolling anchored-train walk-forward over session days."""
    days = pd.Series(sorted({d for d in df.index.normalize()}))
    windows: List[WindowResult] = []

    start = 0
    while start + train_days + test_days <= len(days):
        train_slice = df[
            (df.index >= days[start]) & (df.index < days[start + train_days])
        ]
        test_slice = df[
            (df.index >= days[start + train_days])
            & (df.index < days[min(start + train_days + test_days, len(days) - 1)])
        ]

        best_score, best_params = float("-inf"), None
        for params in grid:
            trades = run_backtest(
                train_slice,
                factory(**params),
                instrument,
                contracts=contracts,
                max_trades_per_day=max_trades_per_day,
            )
            score = objective(trades)
            if score > best_score:
                best_score, best_params = score, params

        test_trades: List[Trade] = []
        if best_params is not None and best_score > float("-inf"):
            test_trades = run_backtest(
                test_slice,
                factory(**best_params),
                instrument,
                contracts=contracts,
                max_trades_per_day=max_trades_per_day,
            )

        windows.append(
            WindowResult(
                train_start=days[start],
                test_start=days[start + train_days],
                test_end=days[min(start + train_days + test_days, len(days) - 1)],
                best_params=best_params,
                train_score=best_score,
                test_trades=test_trades,
            )
        )
        start += test_days

    return WalkForwardResult(windows=windows, instrument=instrument)
