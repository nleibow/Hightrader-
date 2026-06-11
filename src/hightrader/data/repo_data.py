"""Loaders for the FutureSharks/financial-data repo formats.

Two real intraday datasets used for validation:

- histdata.com 1-minute index data (SPXUSD): semicolon CSV, fixed EST
  (UTC-5, no DST). 2010-2018.
- Oanda 1-minute CFD data (NAS100_USD, SPX500_USD): comma CSV with header,
  UTC timestamps. 2005-2020.

Both are converted to America/New_York, filtered to the regular session
(09:30-16:00), and resampled to N-minute bars. Index/CFD prices track the
futures (ES/NQ) closely enough for strategy research; final validation
must use the broker's own feed.
"""

from __future__ import annotations

import glob
import os
from typing import Optional

import pandas as pd

NY = "America/New_York"


def load_histdata_m1(directory: str, tz_fixed_offset_hours: int = -5) -> pd.DataFrame:
    """Load all DAT_ASCII_*_M1_*.csv files from a histdata directory."""
    files = sorted(glob.glob(os.path.join(directory, "DAT_ASCII_*_M1_*.csv")))
    if not files:
        raise FileNotFoundError(f"no histdata csvs in {directory}")
    frames = []
    for f in files:
        df = pd.read_csv(
            f,
            sep=";",
            header=None,
            names=["ts", "open", "high", "low", "close", "volume"],
        )
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    idx = pd.to_datetime(df.pop("ts"), format="%Y%m%d %H%M%S")
    # histdata is fixed EST (UTC-5) year-round; convert to true NY time.
    idx = idx.dt.tz_localize(f"Etc/GMT+{-tz_fixed_offset_hours}").dt.tz_convert(NY)
    df.index = pd.DatetimeIndex(idx, name="timestamp")
    return df.sort_index()


def load_oanda_m1(directory: str) -> pd.DataFrame:
    """Load all oanda-*.csv files (recursively, by year subdir)."""
    files = sorted(glob.glob(os.path.join(directory, "**", "oanda-*.csv"), recursive=True))
    if not files:
        raise FileNotFoundError(f"no oanda csvs in {directory}")
    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    idx = pd.to_datetime(df.pop("time"))
    df.index = pd.DatetimeIndex(idx, name="timestamp").tz_localize("UTC").tz_convert(NY)
    df = df[["open", "high", "low", "close", "volume"]]
    return df.sort_index()


def to_session_bars(
    df: pd.DataFrame,
    minutes: int = 5,
    session_start: str = "09:30",
    session_end: str = "16:00",
) -> pd.DataFrame:
    """Filter to the NY regular session and resample to N-minute bars.

    Resampling happens within the session only; bars with no trades are
    dropped. The index is made tz-naive NY time afterward (the engine
    groups sessions by calendar date).
    """
    df = df.between_time(session_start, session_end, inclusive="left")
    out = (
        df.resample(f"{minutes}min")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["open"])
    )
    out = out.between_time(session_start, session_end, inclusive="left")
    out.index = out.index.tz_localize(None)
    # Drop near-empty sessions (holidays / data gaps).
    counts = out.groupby(out.index.date).size()
    expected = (pd.Timedelta(session_end + ":00") - pd.Timedelta(session_start + ":00")) / pd.Timedelta(minutes=minutes)
    good_days = counts[counts >= 0.7 * float(expected)].index
    return out[pd.Series(out.index.date, index=out.index).isin(set(good_days)).values]


def load_cached(
    cache_path: str,
    loader,
    *args,
    minutes: int = 5,
    **kwargs,
) -> pd.DataFrame:
    """Parquet-cache wrapper: raw load + session bars is slow on 2M rows."""
    if os.path.exists(cache_path):
        return pd.read_parquet(cache_path)
    df = to_session_bars(loader(*args, **kwargs), minutes=minutes)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    df.to_parquet(cache_path)
    return df
