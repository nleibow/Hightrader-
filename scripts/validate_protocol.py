#!/usr/bin/env python3
"""Execute the pre-registered protocol in PROTOCOL.md. Run once.

Steps per (strategy, instrument) on the DEVELOPMENT set only:
  1. Walk-forward (train 504 / test 126 sessions) with the frozen grid.
  2. Full-dev-period run of every grid config -> CSCV PBO.
  3. Check the six-part success bar.

The holdout is NOT touched by this script (see holdout_test.py, which may
be run exactly once on whatever passes).
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from hightrader.backtest import ES, NQ, compute_stats, run_backtest
from hightrader.backtest.pbo import cscv_pbo, daily_pnl_matrix
from hightrader.backtest.walkforward import param_grid, walk_forward
from hightrader.strategies import MeanReversion, OpeningRangeBreakout, TrendMomentum

HOLDOUT_FRACTION = 0.15

GRIDS = {
    "orb": (
        OpeningRangeBreakout,
        param_grid(range_bars=[3, 6, 12], rr=[1.5, 2.5]),
    ),
    "momentum": (
        TrendMomentum,
        [
            dict(fast=f, slow=s, atr_mult=a, rr=r)
            for (f, s) in [(9, 21), (20, 50)]
            for a in [1.5, 2.5]
            for r in [1.5, 2.5]
        ],
    ),
    "meanrev": (
        MeanReversion,
        [
            dict(bb_std=b, rsi_low=lo, rsi_high=hi)
            for b in [2.0, 2.5]
            for (lo, hi) in [(25, 75), (20, 80)]
        ],
    ),
}

DATASETS = {
    "NAS100": ("data/cache/nas100_5m.parquet", NQ),
    "SPX": ("data/cache/spx_5m.parquet", ES),
}


def dev_slice(df: pd.DataFrame) -> pd.DataFrame:
    days = sorted({d for d in df.index.normalize()})
    cut = days[int(len(days) * (1 - HOLDOUT_FRACTION))]
    return df[df.index < cut]


def check_bar(wf, pbo_result) -> dict:
    s = wf.oos_stats
    pnls = np.array([t.pnl for t in wf.oos_trades])
    tstat = (
        float(pnls.mean() / pnls.std(ddof=1) * np.sqrt(len(pnls)))
        if len(pnls) > 2 and pnls.std(ddof=1) > 0
        else float("-inf")
    )
    checks = {
        "expectancy>0": s.expectancy > 0,
        "tstat>=2": tstat >= 2.0,
        "windows>=55%": wf.positive_window_fraction >= 0.55,
        "PF>=1.10": s.profit_factor >= 1.10,
        "PBO<=35%": pbo_result.pbo <= 0.35,
    }
    return {
        "tstat": round(tstat, 2),
        "checks": checks,
        "passes_pre_plateau": all(checks.values()),
    }


def main() -> None:
    os.makedirs("results", exist_ok=True)
    report = {}
    for ds_name, (path, instrument) in DATASETS.items():
        df_full = pd.read_parquet(path)
        df = dev_slice(df_full)
        days = sorted({d.date() for d in df.index.normalize()})
        print(
            f"\n##### {ds_name}: dev set {df.index[0].date()} .. {df.index[-1].date()} "
            f"({len(days)} sessions; holdout untouched) #####"
        )
        for strat_name, (cls, grid) in GRIDS.items():
            key = f"{ds_name}/{strat_name}"
            print(f"\n=== {key}  (grid={len(grid)}) ===")

            wf = walk_forward(
                df, cls, grid, instrument, train_days=504, test_days=126,
                max_trades_per_day=3,
            )
            print(wf.summary())

            # PBO over full-dev-period config runs.
            trade_lists = [
                run_backtest(df, cls(**p), instrument, max_trades_per_day=3)
                for p in grid
            ]
            mat = daily_pnl_matrix(trade_lists, days)
            pbo = cscv_pbo(mat, n_blocks=16)
            print(pbo.summary())

            verdict = check_bar(wf, pbo)
            print(f"bar: {verdict['checks']}  -> "
                  f"{'CANDIDATE' if verdict['passes_pre_plateau'] else 'FAIL'}")
            report[key] = {
                "oos": wf.oos_stats.summary(),
                "pbo": pbo.pbo,
                **verdict,
            }
            with open(f"results/wf_{ds_name}_{strat_name}.pkl", "wb") as f:
                pickle.dump(wf, f)

    with open("results/protocol_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    n_pass = sum(1 for v in report.values() if v["passes_pre_plateau"])
    print(f"\n##### SUMMARY: {n_pass}/{len(report)} strategy-instrument cells "
          f"pass the pre-plateau bar #####")


if __name__ == "__main__":
    sys.exit(main())
