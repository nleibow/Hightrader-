"""Diversified multi-asset time-series momentum (PROTOCOL_ADDENDUM_2).

One pre-committed configuration of the canonical TSMOM portfolio:
sign of 252-session return per asset, equal-risk vol weights, weekly
rebalance at next open, flat per-side bps costs. Each asset is processed
on its own trading calendar; daily portfolio PnL is accumulated on the
union calendar (a position in a closed market contributes nothing that
day).

Approximations, accepted and documented: account-currency conversion for
non-USD-quoted CFDs is ignored, and costs are a flat bps of traded
notional — both are second-order relative to the signal being tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class PortfolioResult:
    days: pd.DatetimeIndex
    pnl: np.ndarray  # $ per union day, net of costs
    gross_exposure: np.ndarray  # sum |notional| held
    intraday_mae: np.ndarray  # conservative sum of per-asset adverse marks ($)
    costs: np.ndarray

    def traded_mask(self) -> np.ndarray:
        return self.gross_exposure > 0

    def tstat(self) -> float:
        x = self.pnl[self.traded_mask()]
        if len(x) < 3 or x.std(ddof=1) == 0:
            return float("-inf")
        return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x)))


def run_tsmom_portfolio(
    dailies: Dict[str, pd.DataFrame],
    lookback: int = 252,
    rebalance_every: int = 5,
    vol_target: float = 0.10,
    vol_window: int = 60,
    cap_mult: float = 3.0,
    cost_bps_side: float = 3.0,
    notional: float = 100_000.0,
    rebalance_band: float = 0.25,
) -> PortfolioResult:
    n_assets = len(dailies)
    all_days = sorted(set().union(*[set(df.index) for df in dailies.values()]))
    day_pos = {d: i for i, d in enumerate(all_days)}
    T = len(all_days)
    pnl = np.zeros(T)
    mae = np.zeros(T)
    gross = np.zeros(T)
    costs = np.zeros(T)

    for sym, df in dailies.items():
        o = df["open"].to_numpy()
        h = df["high"].to_numpy()
        lo = df["low"].to_numpy()
        c = df["close"].to_numpy()
        n = len(df)
        if n < lookback + vol_window + 2:
            continue
        rets = np.zeros(n)
        rets[1:] = c[1:] / c[:-1] - 1.0
        sigma = (
            pd.Series(rets).rolling(vol_window).std().to_numpy() * np.sqrt(TRADING_DAYS)
        )
        mom = np.full(n, np.nan)
        mom[lookback:] = c[lookback:] / c[:-lookback] - 1.0
        with np.errstate(divide="ignore", invalid="ignore"):
            w_mag = np.minimum(vol_target / (n_assets * sigma), cap_mult / n_assets)
        w = np.sign(mom) * w_mag
        w[~np.isfinite(w)] = 0.0

        held = 0.0  # signed notional dollars
        target = None
        idx = df.index
        for k in range(1, n - 1):
            if (k - 1) % rebalance_every == 0:
                target = w[k - 1] * notional
            if target is not None:
                if (
                    held == 0.0
                    or target == 0.0
                    or abs(target - held) > rebalance_band * abs(held)
                ):
                    t_union = day_pos[idx[k]]
                    cost = abs(target - held) * cost_bps_side / 10_000.0
                    costs[t_union] += cost
                    pnl[t_union] -= cost
                    held = target
                target = None
            if held != 0.0:
                t_union = day_pos[idx[k]]
                pnl[t_union] += held * (o[k + 1] - o[k]) / o[k]
                adverse = (o[k] - lo[k]) / o[k] if held > 0 else (h[k] - o[k]) / o[k]
                mae[t_union] += abs(held) * adverse
                gross[t_union] += abs(held)

    return PortfolioResult(
        days=pd.DatetimeIndex(all_days),
        pnl=pnl,
        gross_exposure=gross,
        intraday_mae=mae,
        costs=costs,
    )
