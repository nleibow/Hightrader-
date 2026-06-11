"""Intraday trend momentum: EMA alignment + pullback entry, ATR stop."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..backtest.engine import Signal, Strategy
from .indicators import atr, ema, session_bar_number


class TrendMomentum(Strategy):
    """Trade with the intraday trend after a pullback.

    Long when fast EMA > slow EMA, price pulls back to touch the fast EMA,
    then closes back above it. Stop = entry - atr_mult * ATR, target = rr * R.
    Mirror for shorts. Skips the first bars of the session (no trend yet)
    and the last bars (no time to work).
    """

    def __init__(
        self,
        fast: int = 9,
        slow: int = 21,
        atr_mult: float = 1.5,
        rr: float = 2.0,
        atr_period: int = 14,
        warmup_bars: int = 12,
        cutoff_bars_before_close: int = 6,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.atr_mult = atr_mult
        self.rr = rr
        self.atr_period = atr_period
        self.warmup_bars = warmup_bars
        self.cutoff = cutoff_bars_before_close

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df["bar_no"] = session_bar_number(df.index)
        dates = pd.Series(df.index.date, index=df.index)
        df["bars_in_day"] = dates.groupby(dates).transform("count")
        df["ema_f"] = ema(df["close"], self.fast)
        df["ema_s"] = ema(df["close"], self.slow)
        df["atr"] = atr(df, self.atr_period)
        return df

    def signal(self, i: int, rows: list) -> Optional[Signal]:
        row = rows[i]
        if row["bar_no"] < self.warmup_bars:
            return None
        if row["bar_no"] >= row["bars_in_day"] - self.cutoff:
            return None
        a = row["atr"]
        if np.isnan(a) or a <= 0:
            return None
        c, ef, es = row["close"], row["ema_f"], row["ema_s"]
        touched_low = row["low"] <= ef
        touched_high = row["high"] >= ef
        if ef > es and touched_low and c > ef:
            return Signal(1, stop=c - self.atr_mult * a, target=c + self.rr * self.atr_mult * a)
        if ef < es and touched_high and c < ef:
            return Signal(-1, stop=c + self.atr_mult * a, target=c - self.rr * self.atr_mult * a)
        return None
