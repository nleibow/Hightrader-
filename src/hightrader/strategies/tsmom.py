"""Daily-frequency time-series momentum with vol-targeted sizing.

Structural candidate (PROTOCOL_ADDENDUM_1): signal = sign of trailing
L-session total return; size = min(cap, vol_target / realized_vol). This is
a vectorized daily backtester, separate from the intraday bar engine,
because swing positions have no intraday stop management — exits are
signal flips and vol-target rebalances only.

Execution model: signal from close[t], position changes at open[t+1],
daily PnL measured open[t+1] -> open[t+2] (next-open fills; no same-bar
leak). Costs charged per side on |position change| in notional contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..backtest.engine import Instrument

TRADING_DAYS = 252


@dataclass
class DailyResult:
    """Per-session results of a daily strategy run."""

    days: pd.DatetimeIndex
    pnl: np.ndarray  # dollars per session, net of costs
    position: np.ndarray  # contracts held during each session
    intraday_mae: np.ndarray  # worst open-equity dip within each session ($)

    @property
    def total(self) -> float:
        return float(self.pnl.sum())

    def tstat(self) -> float:
        traded = self.pnl[self.position != 0]
        if len(traded) < 3 or traded.std(ddof=1) == 0:
            return float("-inf")
        return float(traded.mean() / traded.std(ddof=1) * np.sqrt(len(traded)))


def daily_bars(df_5m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate session bars to one OHLC row per session."""
    g = df_5m.groupby(df_5m.index.normalize())
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
        }
    )
    out.index = pd.DatetimeIndex(out.index)
    return out


def run_tsmom(
    daily: pd.DataFrame,
    instrument: Instrument,
    lookback: int = 126,
    long_short: bool = False,
    vol_target: Optional[float] = 0.15,
    base_notional: float = 100_000.0,
    weight_cap: float = 1.0,
    rebalance_band: float = 0.10,
) -> DailyResult:
    """Run TSMOM on daily OHLC. base_notional sets contract counts:
    contracts = weight * base_notional / (price * point_value)."""
    px = daily["close"].to_numpy()
    opens = daily["open"].to_numpy()
    lows = daily["low"].to_numpy()
    highs = daily["high"].to_numpy()
    n = len(daily)

    rets = np.zeros(n)
    rets[1:] = px[1:] / px[:-1] - 1.0
    sig = np.zeros(n)
    for t in range(lookback, n):
        mom = px[t] / px[t - lookback] - 1.0
        sig[t] = np.sign(mom) if (long_short or mom > 0) else 0.0

    if vol_target is not None:
        vol = pd.Series(rets).rolling(20).std().to_numpy() * np.sqrt(TRADING_DAYS)
        with np.errstate(divide="ignore", invalid="ignore"):
            w = np.where(vol > 0, np.minimum(weight_cap, vol_target / vol), 0.0)
    else:
        w = np.full(n, weight_cap)
    weight = sig * w  # desired weight decided at close[t]

    pnl = np.zeros(n)
    mae = np.zeros(n)
    pos_contracts = np.zeros(n)
    held = 0.0
    cost_side = instrument.commission_per_side + instrument.slippage_points * instrument.point_value
    for t in range(1, n - 1):
        # Rebalance at open[t] toward weight[t-1] (decided at prior close).
        target_contracts = weight[t - 1] * base_notional / (opens[t] * instrument.point_value)
        target_contracts = float(np.round(target_contracts))
        if held == 0 or target_contracts == 0 or (
            abs(target_contracts - held) > rebalance_band * max(abs(held), 1.0)
        ):
            pnl[t] -= abs(target_contracts - held) * cost_side
            held = target_contracts
        # Session PnL open[t] -> open[t+1]; MAE vs session extreme.
        pnl[t] += held * (opens[t + 1] - opens[t]) * instrument.point_value
        adverse = (opens[t] - lows[t]) if held > 0 else (highs[t] - opens[t])
        mae[t] = abs(held) * adverse * instrument.point_value
        pos_contracts[t] = held

    return DailyResult(
        days=daily.index, pnl=pnl, position=pos_contracts, intraday_mae=mae
    )
