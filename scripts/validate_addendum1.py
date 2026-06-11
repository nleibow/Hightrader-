#!/usr/bin/env python3
"""Execute PROTOCOL_ADDENDUM_1: daily TSMOM + vol targeting, walk-forward.

Same discipline as the intraday protocol: frozen 12-config grid, selection
on train by daily-PnL t-stat, OOS concatenation, PBO, regime-honesty split,
plateau — holdout untouched here.
"""

from __future__ import annotations

import json
import os
import warnings
from collections import Counter

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from hightrader.backtest import ES, NQ
from hightrader.backtest.pbo import cscv_pbo
from hightrader.strategies.tsmom import daily_bars, run_tsmom

HOLDOUT_FRACTION = 0.15

GRID = [
    dict(lookback=lb, long_short=ls, vol_target=vt)
    for lb in (63, 126, 252)
    for ls in (False, True)
    for vt in (0.15, None)
]

DATASETS = {
    "NAS100": ("data/cache/nas100_5m.parquet", NQ),
    "SPX": ("data/cache/spx_5m.parquet", ES),
}


def run_config(daily: pd.DataFrame, instrument, params) -> "np.ndarray":
    return run_tsmom(daily, instrument, **params)


def main() -> None:
    os.makedirs("results", exist_ok=True)
    report = {}
    for ds_name, (path, instrument) in DATASETS.items():
        df5 = pd.read_parquet(path)
        daily_full = daily_bars(df5)
        cut = int(len(daily_full) * (1 - HOLDOUT_FRACTION))
        daily = daily_full.iloc[:cut]
        n = len(daily)
        print(f"\n##### {ds_name} daily: dev {daily.index[0].date()} .. "
              f"{daily.index[-1].date()} ({n} sessions) #####")

        # Full-dev per-config daily PnL (for PBO and plateau).
        full_runs = {tuple(sorted(p.items())): run_config(daily, instrument, p)
                     for p in GRID}
        mat = np.column_stack([r.pnl for r in full_runs.values()])
        pbo = cscv_pbo(mat, n_blocks=16)

        # Walk-forward.
        train_d, test_d = 504, 126
        start, oos_pnl, oos_pos, windows = 0, [], [], []
        while start + train_d + test_d <= n:
            best_t, best_p = float("-inf"), None
            for p in GRID:
                res = run_config(daily.iloc[start : start + train_d], instrument, p)
                t = res.tstat()
                if t > best_t:
                    best_t, best_p = t, p
            seg = daily.iloc[start + train_d - 300 : start + train_d + test_d]
            res = run_config(seg, instrument, best_p)  # warmup tail included
            tail = res.pnl[-test_d:]
            tail_pos = res.position[-test_d:]
            oos_pnl.append(tail)
            oos_pos.append(tail_pos)
            windows.append((daily.index[start + train_d].date(), best_p, tail.sum()))
            start += test_d

        pnl = np.concatenate(oos_pnl)
        pos = np.concatenate(oos_pos)
        traded = pnl[pos != 0]
        mean_daily = traded.mean() if len(traded) else 0.0
        tstat = (traded.mean() / traded.std(ddof=1) * np.sqrt(len(traded))
                 if len(traded) > 2 and traded.std(ddof=1) > 0 else float("-inf"))
        win_frac = np.mean([1 if w[2] > 0 else 0 for w in windows])
        half = len(pnl) // 2
        regime_ok = pnl[:half].sum() > 0 or pnl[half:].sum() > 0
        both_halves = (pnl[:half].sum(), pnl[half:].sum())

        for w in windows:
            print(f"  {w[0]}  params={w[1]}  oos=${w[2]:,.0f}")
        print(f"OOS: {len(traded)} traded days, mean=${mean_daily:.2f}/day, "
              f"t={tstat:.2f}, windows+={win_frac:.0%}, halves=({both_halves[0]:,.0f}, "
              f"{both_halves[1]:,.0f})")
        print(pbo.summary())

        modal = Counter(tuple(sorted(w[1].items())) for w in windows).most_common(1)[0]
        checks = {
            "mean_daily>0": mean_daily > 0,
            "tstat>=2": tstat >= 2.0,
            "windows>=55%": win_frac >= 0.55,
            "PBO<=35%": pbo.pbo <= 0.35,
            "regime_halves": regime_ok and min(both_halves) > -0.5 * abs(max(both_halves)),
        }
        print(f"modal config: {dict(modal[0])} ({modal[1]}/{len(windows)} windows)")
        print(f"bar: {checks} -> {'CANDIDATE' if all(checks.values()) else 'FAIL'}")
        report[ds_name] = {
            "mean_daily": float(mean_daily),
            "tstat": float(tstat),
            "win_frac": float(win_frac),
            "pbo": pbo.pbo,
            "halves": [float(h) for h in both_halves],
            "modal_config": dict(modal[0]),
            "checks": {k: bool(v) for k, v in checks.items()},
            "passes": all(checks.values()),
        }

    with open("results/addendum1_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print("\n#####", {k: v["passes"] for k, v in report.items()}, "#####")


if __name__ == "__main__":
    main()
