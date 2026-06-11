"""Opening Range Breakout (ORB).

The most studied intraday futures edge: the first N minutes of the regular
session define a range; a decisive break tends to continue, especially on
trend days. Recent academic work (Zarattini & Aziz 2023 on ORB in US
equities/futures) found persistent edge after costs when filtered by
volatility. This implementation:

- Defines the opening range from the first ``range_bars`` bars of the day.
- Enters on the first close beyond the range, stop at the range midpoint,
  target at ``rr`` times the risk.
- Volatility filter: skips days whose opening range is tiny relative to ATR
  (chop) or huge (blowoff already happened).
- One attempt per direction per day, controlled via ``max_trades_per_day``
  in the engine.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..backtest.engine import Signal, Strategy
from .indicators import atr, session_bar_number


class OpeningRangeBreakout(Strategy):
    def __init__(
        self,
        range_bars: int = 6,  # e.g. 6 x 5-min bars = 30-min opening range
        rr: float = 2.0,
        min_range_atr: float = 0.5,
        max_range_atr: float = 3.0,
        atr_period: int = 14,
    ) -> None:
        self.range_bars = range_bars
        self.rr = rr
        self.min_range_atr = min_range_atr
        self.max_range_atr = max_range_atr
        self.atr_period = atr_period

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df["bar_no"] = session_bar_number(df.index)
        df["atr"] = atr(df, self.atr_period)
        dates = pd.Series(df.index.date, index=df.index)
        in_range = df["bar_no"] < self.range_bars
        df["or_high"] = (
            df["high"].where(in_range).groupby(dates).transform("max")
        )
        df["or_low"] = df["low"].where(in_range).groupby(dates).transform("min")
        return df

    def signal(self, i: int, df: pd.DataFrame) -> Optional[Signal]:
        row = df.iloc[i]
        if row["bar_no"] < self.range_bars:
            return None
        or_h, or_l, a = row["or_high"], row["or_low"], row["atr"]
        if np.isnan(or_h) or np.isnan(a) or a <= 0:
            return None
        rng = or_h - or_l
        if not (self.min_range_atr * a <= rng <= self.max_range_atr * a):
            return None
        mid = (or_h + or_l) / 2
        close = row["close"]
        if close > or_h:
            risk = close - mid
            return Signal(direction=1, stop=mid, target=close + self.rr * risk)
        if close < or_l:
            risk = mid - close
            return Signal(direction=-1, stop=mid, target=close - self.rr * risk)
        return None
