#!/usr/bin/env python3
"""Aggregate every Oanda 1m instrument to NY-calendar daily OHLC parquet."""

from __future__ import annotations

import glob
import os
import sys

import pandas as pd

SRC = "/tmp/mkt/financial-data/pyfinancialdata/data/currencies/oanda"
OUT = "data/cache/oanda_daily"
NY = "America/New_York"


def build(symbol: str) -> str:
    files = sorted(glob.glob(os.path.join(SRC, symbol, "**", "oanda-*.csv"), recursive=True))
    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    idx = pd.to_datetime(df.pop("time"))
    df.index = pd.DatetimeIndex(idx).tz_localize("UTC").tz_convert(NY)
    df = df.sort_index()
    g = df.groupby(df.index.normalize())
    daily = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "bars": g["close"].size(),
        }
    )
    daily = daily[daily["bars"] >= 100]  # drop holiday slivers
    daily.index = pd.DatetimeIndex([d.date() for d in daily.index])
    path = os.path.join(OUT, f"{symbol}.parquet")
    daily.drop(columns="bars").to_parquet(path)
    return f"{symbol}: {len(daily)} sessions {daily.index[0].date()} .. {daily.index[-1].date()}"


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    symbols = sorted(os.path.basename(p) for p in glob.glob(os.path.join(SRC, "*")))
    for s in symbols:
        try:
            print(build(s), flush=True)
        except Exception as e:
            print(f"{s}: FAILED {e}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
