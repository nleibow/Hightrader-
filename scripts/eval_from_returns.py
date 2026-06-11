#!/usr/bin/env python3
"""Prop-eval feasibility from an EXTERNAL strategy's daily returns.

This is the bridge for a strategy validated elsewhere (e.g. the L2T2
vol-targeted system): export its daily P&L and ask "which prop firm, at
what size, with what pass probability and EV?"

Input CSV: columns `date` and one of `pnl` (dollars) or `return`
(fractional, applied to --notional). Optional `mae` column (intraday
adverse excursion, same units as pnl) — without it, daily-loss checks use
close-to-close P&L only, which UNDERSTATES breach risk for fat intraday
paths; pass --mae-factor to scale |pnl| as a proxy.

Usage:
    python scripts/eval_from_returns.py returns.csv --notional 100000 \
        --eval-fee 550 --funded-value 8000 [--swing-only]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from hightrader.firms import ALL_PROFILES, FTMO_100K_PHASE1, FTMO_100K_PHASE2
from hightrader.montecarlo import (
    buffer_scaled,
    coast_to_target,
    combined,
    optimal_risk,
    sweep_risk,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--notional", type=float, default=100_000.0,
                    help="notional that `return` column applies to")
    ap.add_argument("--eval-fee", type=float, default=550.0)
    ap.add_argument("--funded-value", type=float, default=8_000.0,
                    help="honest expected total payout per funded account")
    ap.add_argument("--mae-factor", type=float, default=1.3,
                    help="intraday MAE proxy = factor * |pnl| when no mae column")
    ap.add_argument("--swing-only", action="store_true",
                    help="only firms that allow overnight holding (FTMO)")
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--block-len", type=int, default=10,
                    help="bootstrap block length in days (autocorrelated PnL)")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df.columns = [c.lower() for c in df.columns]
    if "pnl" in df.columns:
        pnl = df["pnl"].to_numpy(dtype=float)
    elif "return" in df.columns:
        pnl = df["return"].to_numpy(dtype=float) * args.notional
    else:
        raise SystemExit("CSV needs a `pnl` or `return` column")
    if "mae" in df.columns:
        mae = df["mae"].to_numpy(dtype=float)
    else:
        mae = np.where(pnl < 0, args.mae_factor * np.abs(pnl), 0.3 * np.abs(pnl))

    mean, sd = pnl.mean(), pnl.std(ddof=1)
    t = mean / sd * np.sqrt(len(pnl))
    print(f"{len(pnl)} days  mean=${mean:,.2f}/d  vol=${sd:,.0f}/d  t={t:.2f}  "
          f"ann Sharpe~{mean / sd * np.sqrt(252):.2f}")
    if t < 2:
        print("WARNING: this return stream is not statistically distinguishable "
              "from luck — eval fees on it are gambling, not investing.")

    losses = [-p for p in pnl if p < 0]
    base = float(np.mean(losses)) if losses else sd
    # Pool entries are normalized per $1 of base risk (simulate_eval rescales).
    pool = [[(p / base, m / base, max(p, 0.0) / base)] for p, m in zip(pnl, mae)]

    profiles = (
        (FTMO_100K_PHASE1, FTMO_100K_PHASE2) if args.swing_only else tuple(ALL_PROFILES)
    )
    policy = combined(buffer_scaled(alpha=1.2), coast_to_target())
    print(f"\nbase unit = avg losing day at source scale: ${base:,.0f}")
    for profile in profiles:
        print(f"\n=== {profile.name} ===")
        buf = profile.max_total_drawdown
        risks = [buf * f for f in (0.02, 0.04, 0.07, 0.10, 0.15, 0.22)]
        rs = sweep_risk(pool, profile, risks, policy=policy, n_sims=args.sims,
                        block_len=args.block_len, max_days=300)
        for r in rs:
            scale = r.base_risk / base
            print(f"  scale x{scale:.2f}  " + r.summary())
        best, ev = optimal_risk(rs, eval_fee=args.eval_fee,
                                funded_value=args.funded_value)
        print(f"  >> optimal: scale x{best.base_risk / base:.2f} of source size, "
              f"P(pass)={best.p_pass:.1%}, EV/attempt=${ev:,.0f}")
        if ev <= 0:
            print("  >> NEGATIVE EV at the stated fee/funded-value: do not buy this eval.")


if __name__ == "__main__":
    main()
