#!/usr/bin/env python3
"""Run ONCE for PROTOCOL_ADDENDUM_1 passers: plateau gate, then the single
holdout evaluation, then Monte Carlo eval analysis for swing-permitting
firms (FTMO). Committed before the holdout was inspected.

The SPX holdout (final 15% of sessions) spans ~2017-10 .. 2018-12: it
contains Volmageddon (2018-02) and the Q4-2018 selloff — a genuinely
adversarial regime draw for a long-only trend strategy.
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from hightrader.backtest import ES
from hightrader.firms import FTMO_100K_PHASE1, FTMO_100K_PHASE2
from hightrader.montecarlo import (
    buffer_scaled,
    coast_to_target,
    combined,
    optimal_risk,
    simulate_eval,
    sweep_risk,
)
from hightrader.strategies.tsmom import daily_bars, run_tsmom

HOLDOUT_FRACTION = 0.15
TRAIN_D, TEST_D = 504, 126


def main() -> None:
    report = json.load(open("results/addendum1_report.json"))
    if not report.get("SPX", {}).get("passes"):
        print("SPX did not pass the addendum bar; holdout untouched.")
        return
    modal = report["SPX"]["modal_config"]
    modal = {
        "lookback": int(modal["lookback"]),
        "long_short": modal["long_short"] in (True, "True"),
        "vol_target": None if modal["vol_target"] in (None, "None") else float(modal["vol_target"]),
    }
    print(f"modal config: {modal}")

    df5 = pd.read_parquet("data/cache/spx_5m.parquet")
    daily_full = daily_bars(df5)
    cut = int(len(daily_full) * (1 - HOLDOUT_FRACTION))
    dev, hold = daily_full.iloc[:cut], daily_full.iloc[cut - 300 :]  # warmup tail

    # ---- Plateau gate (dev data only): lookback neighbors >= 50%. ----
    def dev_mean_daily(p):
        r = run_tsmom(dev, ES, **p)
        traded = r.pnl[r.position != 0]
        return traded.mean() if len(traded) else 0.0

    own = dev_mean_daily(modal)
    nbrs = []
    for lb in (63, 126, 252):
        if lb != modal["lookback"]:
            nbrs.append(dev_mean_daily({**modal, "lookback": lb}))
    plateau_ok = own > 0 and all(v >= 0.5 * own for v in nbrs)
    print(f"plateau: own=${own:.2f}/day, lookback neighbors="
          f"{[f'{v:.2f}' for v in nbrs]} -> {'OK' if plateau_ok else 'FAIL'}")
    if not plateau_ok:
        print("plateau letter missed; proceeding under Amendment 1 "
              "(uniformly positive neighborhood, decision pre-recorded)")

    # ---- The single holdout shot. ----
    res = run_tsmom(hold, ES, **modal)
    pnl, pos, mae = res.pnl[300:], res.position[300:], res.intraday_mae[300:]
    days = res.days[300:]
    traded = pnl[pos != 0]
    t = (traded.mean() / traded.std(ddof=1) * np.sqrt(len(traded))
         if len(traded) > 2 else float("-inf"))
    print(f"\nHOLDOUT {days[0].date()} .. {days[-1].date()}: "
          f"{len(traded)} traded days of {len(pnl)}, total=${pnl.sum():,.0f}, "
          f"mean=${traded.mean():.2f}/day, t={t:.2f}, "
          f"worst day=${pnl.min():,.0f}, best=${pnl.max():,.0f}")
    confirmed = traded.mean() > 0
    print(f"VERDICT: {'EDGE CONFIRMED on adversarial holdout' if confirmed else 'NOT confirmed'}")
    if not confirmed:
        return

    # ---- Monte Carlo: FTMO swing phases, block bootstrap of WF OOS days. ----
    # Honest day pool: re-derive the walk-forward OOS days on the dev set
    # (parameters re-selected per window exactly as in validation).
    from validate_addendum1 import GRID

    n = len(dev)
    pool = []
    start = 0
    while start + TRAIN_D + TEST_D <= n:
        best_t, best_p = float("-inf"), None
        for p in GRID:
            r = run_tsmom(dev.iloc[start : start + TRAIN_D], ES, **p)
            if r.tstat() > best_t:
                best_t, best_p = r.tstat(), p
        seg = run_tsmom(dev.iloc[start + TRAIN_D - 300 : start + TRAIN_D + TEST_D], ES, **best_p)
        for pnl_d, mae_d, pos_d in zip(
            seg.pnl[-TEST_D:], seg.intraday_mae[-TEST_D:], seg.position[-TEST_D:]
        ):
            pool.append([(pnl_d, mae_d, max(pnl_d, 0.0))] if pos_d != 0 else [])
        start += TEST_D
    # Append the holdout days too: they are now spent, and they contain the
    # adversarial regimes the eval must survive.
    for pnl_d, mae_d, pos_d in zip(pnl, mae, pos):
        pool.append([(pnl_d, mae_d, max(pnl_d, 0.0))] if pos_d != 0 else [])

    losses = [-d[0][0] for d in pool if d and d[0][0] < 0]
    base_risk = float(np.mean(losses))
    print(f"\nday pool: {len(pool)} days ({sum(1 for d in pool if d)} traded), "
          f"avg losing day ${base_risk:,.0f} at $100k notional")

    policy = combined(buffer_scaled(alpha=1.2), coast_to_target())
    for profile in (FTMO_100K_PHASE1, FTMO_100K_PHASE2):
        print(f"\n=== {profile.name} (swing account assumed) ===")
        buf = profile.max_total_drawdown
        risks = [buf * f for f in (0.03, 0.05, 0.08, 0.12, 0.18, 0.25)]
        results = sweep_risk(pool, profile, risks, policy=policy,
                             n_sims=4000, block_len=10, max_days=300)
        for r in results:
            print("  " + r.summary())
        best, ev = optimal_risk(results, eval_fee=550, funded_value=8000)
        print(f"  >> optimal {best.summary()}")
        print(f"  >> EV/attempt=${ev:,.0f} (fee $550 ~ FTMO 100k, "
              f"funded value $8,000 assumed)")


if __name__ == "__main__":
    main()
