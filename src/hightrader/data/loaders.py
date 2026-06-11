"""Data loaders: CSV, yfinance (optional), and a synthetic generator.

The synthetic generator exists to test PLUMBING (engine, rules, Monte Carlo),
and to demo the pipeline end-to-end. It must never be used to claim a
strategy has edge — validate on real intraday data (Databento, Polygon, or
your broker's history) before risking an eval fee.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def load_csv(path: str, tz: Optional[str] = None) -> pd.DataFrame:
    """Load OHLCV bars from CSV with a timestamp column or index."""
    df = pd.read_csv(path)
    ts_col = next(
        (c for c in df.columns if c.lower() in ("timestamp", "datetime", "date", "time")),
        df.columns[0],
    )
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    df.columns = [c.lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLS if c not in df.columns and c != "volume"]
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")
    if "volume" not in df.columns:
        df["volume"] = 0
    if tz:
        df.index = df.index.tz_localize(tz) if df.index.tz is None else df.index.tz_convert(tz)
    return df[REQUIRED_COLS]


def load_yfinance(symbol: str, period: str = "60d", interval: str = "5m") -> pd.DataFrame:
    """Fetch intraday bars via yfinance (pip install yfinance). Note yfinance
    intraday history is short (60d at 5m) — fine for smoke tests only."""
    import yfinance as yf  # lazy: optional dependency

    df = yf.download(symbol, period=period, interval=interval, progress=False)
    if df.empty:
        raise RuntimeError(f"yfinance returned no data for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df[REQUIRED_COLS]


def synthetic_intraday(
    n_days: int = 250,
    bars_per_day: int = 78,  # 6.5h of 5-min bars
    start_price: float = 5000.0,
    daily_vol: float = 0.012,
    trend_day_prob: float = 0.30,
    trend_strength: float = 1.2,
    seed: int = 42,
    start: str = "2024-01-02 09:30",
) -> pd.DataFrame:
    """Regime-switching intraday OHLCV: a mix of trend days and chop days.

    Trend days drift persistently in one direction; chop days mean-revert.
    This creates data where breakout strategies *can* show their mechanics
    working without implying real-market edge.
    """
    rng = np.random.default_rng(seed)
    bar_vol = daily_vol / np.sqrt(bars_per_day)
    sessions = pd.bdate_range(start=start.split()[0], periods=n_days)
    open_time = pd.Timestamp(start).time()

    all_idx, opens, highs, lows, closes, vols = [], [], [], [], [], []
    price = start_price
    for day in sessions:
        is_trend = rng.random() < trend_day_prob
        direction = rng.choice([-1.0, 1.0])
        drift = (
            direction * trend_strength * daily_vol / bars_per_day if is_trend else 0.0
        )
        kappa = 0.0 if is_trend else 0.12  # mean reversion pull on chop days
        day_open = price * (1 + rng.normal(0, 0.2 * daily_vol))  # overnight gap
        p = day_open
        anchor = day_open
        t0 = pd.Timestamp.combine(day.date(), open_time)
        for b in range(bars_per_day):
            shock = rng.normal(0, bar_vol)
            ret = drift + shock - kappa * (p - anchor) / anchor / bars_per_day * 10
            new_p = p * (1 + ret)
            o, c = p, new_p
            wick = abs(rng.normal(0, bar_vol * 0.7)) * p
            all_idx.append(t0 + pd.Timedelta(minutes=5 * b))
            opens.append(o)
            closes.append(c)
            highs.append(max(o, c) + wick)
            lows.append(min(o, c) - wick)
            vols.append(int(rng.lognormal(8, 0.5)))
            p = new_p
        price = p

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=pd.DatetimeIndex(all_idx, name="timestamp"),
    )
    return df.round(2)
