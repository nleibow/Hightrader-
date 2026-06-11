"""Intraday mean reversion: fade RSI extremes at Bollinger band touches."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..backtest.engine import Signal, Strategy
from .indicators import atr, rsi, session_bar_number


class MeanReversion(Strategy):
    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 7,
        rsi_low: float = 25.0,
        rsi_high: float = 75.0,
        atr_mult: float = 1.5,
        atr_period: int = 14,
        warmup_bars: int = 21,
    ) -> None:
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high
        self.atr_mult = atr_mult
        self.atr_period = atr_period
        self.warmup_bars = warmup_bars

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df["bar_no"] = session_bar_number(df.index)
        ma = df["close"].rolling(self.bb_period).mean()
        sd = df["close"].rolling(self.bb_period).std()
        df["bb_mid"] = ma
        df["bb_up"] = ma + self.bb_std * sd
        df["bb_dn"] = ma - self.bb_std * sd
        df["rsi"] = rsi(df["close"], self.rsi_period)
        df["atr"] = atr(df, self.atr_period)
        return df

    def signal(self, i: int, rows: list) -> Optional[Signal]:
        row = rows[i]
        if row["bar_no"] < self.warmup_bars:
            return None
        a = row["atr"]
        if np.isnan(row["bb_up"]) or np.isnan(a) or a <= 0:
            return None
        c = row["close"]
        # Target is the band midpoint: mean reversion, not trend.
        if c <= row["bb_dn"] and row["rsi"] <= self.rsi_low:
            return Signal(1, stop=c - self.atr_mult * a, target=row["bb_mid"])
        if c >= row["bb_up"] and row["rsi"] >= self.rsi_high:
            return Signal(-1, stop=c + self.atr_mult * a, target=row["bb_mid"])
        return None
