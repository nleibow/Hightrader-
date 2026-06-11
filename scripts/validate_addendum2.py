#!/usr/bin/env python3
"""Execute PROTOCOL_ADDENDUM_2: diversified TSMOM, single config, dev set.

Holdout (final 15% of union sessions) is NOT touched here unless the dev
bar passes — in which case the single shot fires at the end, exactly once,
as registered.
"""

from __future__ import annotations

import glob
import json
import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from hightrader.firms import FTMO_100K_PHASE1, FTMO_100K_PHASE2
from hightrader.montecarlo import (
    buffer_scaled,
    coast_to_target,
    combined,
    optimal_risk,
    sweep_risk,
)
from hightrader.strategies.tsmom_portfolio import run_tsmom_portfolio

CACHE = "data/cache/oanda_daily"
HOLDOUT_FRACTION = 0.15
NOTIONAL = 100_000.0


def load_universe() -> dict:
    out = {}
    for p in sorted(glob.glob(os.path.join(CACHE, "*.parquet"))):
        sym = os.path.basename(p).replace(".parquet", "")
        out[sym] = pd.read_parquet(p)
    return out


def slice_universe(dailies: dict, lo, hi) -> dict:
    return {s: df[(df.index >= lo) & (df.index < hi)] for s, df in dailies.items()}


def describe(tag: str, res, scale=1.0) -> dict:
    m = res.traded_mask()
    x = res.pnl[m] * scale
    eq = np.cumsum(res.pnl * scale)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    half = len(res.pnl) // 2
    halves = (float(res.pnl[:half].sum() * scale), float(res.pnl[half:].sum() * scale))
    out = {
        "traded_days": int(m.sum()),
        "mean_daily": float(x.mean()),
        "tstat": round(res.tstat(), 2),
        "total": float(x.sum()),
        "ann_vol_$": float(x.std(ddof=1) * np.sqrt(252)),
        "max_dd_$": dd,
        "halves": halves,
        "total_costs": float(res.costs.sum() * scale),
    }
    print(
        f"{tag}: {out['traded_days']}d  mean=${out['mean_daily']:.2f}/d  "
        f"t={out['tstat']}  total=${out['total']:,.0f}  "
        f"maxDD=${out['max_dd_$']:,.0f}  halves=(${halves[0]:,.0f}, ${halves[1]:,.0f})  "
        f"costs=${out['total_costs']:,.0f}"
    )
    return out


def main() -> None:
    dailies = load_universe()
    print(f"universe: {len(dailies)} instruments")
    union = sorted(set().union(*[set(df.index) for df in dailies.values()]))
    cut = union[int(len(union) * (1 - HOLDOUT_FRACTION))]
    print(f"dev: {union[0].date()} .. {cut.date()}  | holdout: .. {union[-1].date()}")

    dev = slice_universe(dailies, union[0], cut)

    # THE config.
    res = run_tsmom_portfolio(dev, lookback=252, rebalance_every=5)
    primary = describe("PRIMARY lookback=252 wk-rebal", res)

    # Sensitivity (context only, not selectable).
    describe("  sens lookback=126", run_tsmom_portfolio(dev, lookback=126))
    describe("  sens monthly rebal", run_tsmom_portfolio(dev, lookback=252, rebalance_every=21))

    checks = {
        "mean_daily>0": primary["mean_daily"] > 0,
        "tstat>=2": primary["tstat"] >= 2.0,
        "halves_both_positive": min(primary["halves"]) > 0,
        "maxDD<=20%notional": primary["max_dd_$"] <= 0.20 * NOTIONAL,
    }
    print(f"bar: {checks} -> {'PASS' if all(checks.values()) else 'FAIL'}")
    report = {"primary_dev": primary, "checks": {k: bool(v) for k, v in checks.items()}}

    if all(checks.values()):
        # ---- The single holdout shot (includes COVID 2020). ----
        warm = union[max(0, int(len(union) * (1 - HOLDOUT_FRACTION)) - 400)]
        hold_u = slice_universe(dailies, warm, union[-1] + pd.Timedelta(days=1))
        rh = run_tsmom_portfolio(hold_u, lookback=252, rebalance_every=5)
        hmask = rh.days >= cut
        x = rh.pnl[hmask]
        traded = x[rh.gross_exposure[hmask] > 0]
        t = (traded.mean() / traded.std(ddof=1) * np.sqrt(len(traded))
             if len(traded) > 2 else float("-inf"))
        print(f"\nHOLDOUT {cut.date()} .. {union[-1].date()}: "
              f"{len(traded)} traded days, total=${x.sum():,.0f}, "
              f"mean=${traded.mean():.2f}/d, t={t:.2f}, "
              f"worst=${x.min():,.0f}")
        confirmed = traded.mean() > 0
        print(f"VERDICT: {'CONFIRMED' if confirmed else 'NOT confirmed'} on COVID-era holdout")
        report["holdout"] = {
            "total": float(x.sum()), "mean_daily": float(traded.mean()),
            "tstat": float(t), "confirmed": bool(confirmed),
        }

        if confirmed:
            # ---- Monte Carlo vs FTMO swing, using dev+holdout day pool. ----
            pool = []
            for pnl_d, mae_d, g in zip(res.pnl, res.intraday_mae, res.gross_exposure):
                pool.append([(pnl_d, mae_d, max(pnl_d, 0.0))] if g > 0 else [])
            for pnl_d, mae_d, g in zip(rh.pnl[hmask], rh.intraday_mae[hmask],
                                       rh.gross_exposure[hmask]):
                pool.append([(pnl_d, mae_d, max(pnl_d, 0.0))] if g > 0 else [])
            losses = [-d[0][0] for d in pool if d and d[0][0] < 0]
            base_risk = float(np.mean(losses))
            print(f"\nday pool {len(pool)} days; avg losing day ${base_risk:,.0f} "
                  f"at $100k notional, 10% vol target")
            policy = combined(buffer_scaled(alpha=1.2), coast_to_target())
            mc = {}
            for profile in (FTMO_100K_PHASE1, FTMO_100K_PHASE2):
                print(f"=== {profile.name} (Swing account) ===")
                buf = profile.max_total_drawdown
                risks = [buf * f for f in (0.02, 0.04, 0.06, 0.10, 0.15, 0.22)]
                rs = sweep_risk(pool, profile, risks, policy=policy,
                                n_sims=4000, block_len=10, max_days=300)
                for r in rs:
                    print("  " + r.summary())
                best, ev = optimal_risk(rs, eval_fee=550, funded_value=8000)
                print(f"  >> optimal {best.summary()}\n  >> EV/attempt=${ev:,.0f}")
                mc[profile.name] = {"best_risk": best.base_risk,
                                    "p_pass": best.p_pass, "ev": ev}
            report["montecarlo"] = mc

    os.makedirs("results", exist_ok=True)
    with open("results/addendum2_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)


if __name__ == "__main__":
    main()
