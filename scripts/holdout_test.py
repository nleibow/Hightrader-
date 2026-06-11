#!/usr/bin/env python3
"""Run ONCE: plateau check + single holdout evaluation for protocol passers.

Written and committed before the protocol results were inspected. For each
strategy-instrument cell that passed the six-part bar in
results/protocol_report.json:

1. Final config = the modal best_params across walk-forward windows.
2. Plateau check (bar #6): every grid neighbor of the final config must
   reach >= 50% of its full-dev-period expectancy (from the PBO runs'
   config order). Neighbors differ by one step on one axis.
3. If the plateau holds, run the final config exactly once on the untouched
   holdout (final 15% of sessions) and report.

Whatever the holdout says is the answer. No re-runs, no tweaks after.
"""

from __future__ import annotations

import json
import pickle
import warnings
from collections import Counter

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from hightrader.backtest import compute_stats, run_backtest
from hightrader.firms import ALL_PROFILES
from hightrader.montecarlo import (
    buffer_scaled,
    coast_to_target,
    combined,
    normalize_days,
    optimal_risk,
    sweep_risk,
)
from validate_protocol import DATASETS, GRIDS, HOLDOUT_FRACTION, dev_slice


def holdout_slice(df: pd.DataFrame) -> pd.DataFrame:
    days = sorted({d for d in df.index.normalize()})
    cut = days[int(len(days) * (1 - HOLDOUT_FRACTION))]
    return df[df.index >= cut]


def neighbors(grid: list, config: dict) -> list:
    """Configs differing from `config` in exactly one parameter."""
    out = []
    for other in grid:
        if other == config:
            continue
        diffs = sum(1 for k in config if other.get(k) != config[k])
        if diffs == 1:
            out.append(other)
    return out


def main() -> None:
    report = json.load(open("results/protocol_report.json"))
    passers = {k: v for k, v in report.items() if v["passes_pre_plateau"]}
    if not passers:
        print("No cells passed the pre-plateau bar. Holdout remains untouched.")
        return

    for key in passers:
        ds_name, strat_name = key.split("/")
        path, instrument = DATASETS[ds_name]
        cls, grid = GRIDS[strat_name]
        wf = pickle.load(open(f"results/wf_{ds_name}_{strat_name}.pkl", "rb"))

        chosen = Counter(
            tuple(sorted(w.best_params.items())) for w in wf.windows if w.best_params
        )
        final_config = dict(chosen.most_common(1)[0][0])
        print(f"\n=== {key}: final config {final_config} "
              f"(chosen in {chosen.most_common(1)[0][1]}/{len(wf.windows)} windows) ===")

        # Plateau check on full-dev-period expectancies.
        df_full = pd.read_parquet(path)
        dev = dev_slice(df_full)
        exp = {}
        for p in [final_config] + neighbors(grid, final_config):
            trades = run_backtest(dev, cls(**p), instrument, max_trades_per_day=3)
            s = compute_stats(trades)
            exp[tuple(sorted(p.items()))] = s.expectancy
        own = exp[tuple(sorted(final_config.items()))]
        nbr = [v for k, v in exp.items() if k != tuple(sorted(final_config.items()))]
        plateau_ok = own > 0 and all(v >= 0.5 * own for v in nbr)
        print(f"dev expectancy own=${own:.2f}, neighbors={[f'{v:.2f}' for v in nbr]} "
              f"-> plateau {'OK' if plateau_ok else 'FAIL (spike)'}")
        if not plateau_ok:
            print("Holdout NOT consumed for this cell.")
            continue

        hold = holdout_slice(df_full)
        trades = run_backtest(hold, cls(**final_config), instrument, max_trades_per_day=3)
        s = compute_stats(trades)
        print(f"HOLDOUT {hold.index[0].date()} .. {hold.index[-1].date()}: {s.summary()}")

        if s.expectancy <= 0 or s.n_trades < 30:
            print("VERDICT: holdout does not confirm edge.")
            continue
        print("VERDICT: edge confirmed on holdout. Monte Carlo eval analysis:")
        base_risk = s.avg_loss
        pool = normalize_days(trades, base_risk)
        policy = combined(buffer_scaled(alpha=1.2), coast_to_target())
        for profile in ALL_PROFILES:
            buffer = profile.max_total_drawdown
            risks = [buffer * f for f in (0.02, 0.05, 0.08, 0.12, 0.20)]
            results = sweep_risk(pool, profile, risks, policy=policy, n_sims=3000)
            best, ev = optimal_risk(results)
            print(f"  {profile.name}: best {best.summary()}  EV=${ev:,.0f}")


if __name__ == "__main__":
    main()
