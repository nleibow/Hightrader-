#!/usr/bin/env python3
"""End-to-end pipeline: data -> backtest -> stats -> eval pass-probability.

Usage:
    python scripts/run_pipeline.py                      # synthetic demo data
    python scripts/run_pipeline.py --csv path/to.csv    # your real intraday bars
    python scripts/run_pipeline.py --yf ES=F            # yfinance smoke test

With real data this answers: "with this strategy at this size, what is my
probability of passing each firm's eval, and what size maximizes it?"
"""

from __future__ import annotations

import argparse

from hightrader.backtest import MES, compute_stats, run_backtest
from hightrader.data import load_csv, synthetic_intraday
from hightrader.firms import ALL_PROFILES
from hightrader.montecarlo import (
    buffer_scaled,
    coast_to_target,
    combined,
    normalize_days,
    optimal_risk,
    sweep_risk,
)
from hightrader.strategies import MeanReversion, OpeningRangeBreakout, TrendMomentum

STRATEGIES = {
    "orb": OpeningRangeBreakout,
    "momentum": TrendMomentum,
    "meanrev": MeanReversion,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="intraday OHLCV csv")
    ap.add_argument("--yf", help="yfinance symbol (e.g. ES=F)")
    ap.add_argument("--strategy", choices=STRATEGIES, default="orb")
    ap.add_argument("--contracts", type=int, default=2)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--eval-fee", type=float, default=165.0)
    ap.add_argument("--funded-value", type=float, default=4000.0,
                    help="realistic expected total payout from one funded account")
    args = ap.parse_args()

    if args.csv:
        df = load_csv(args.csv)
        source = args.csv
    elif args.yf:
        from hightrader.data import load_yfinance

        df = load_yfinance(args.yf)
        source = f"yfinance:{args.yf}"
    else:
        df = synthetic_intraday(n_days=250)
        source = "SYNTHETIC (plumbing demo only — conclusions do not transfer to live)"

    print(f"data: {source}  bars={len(df)}  {df.index[0]} .. {df.index[-1]}\n")

    strategy = STRATEGIES[args.strategy]()
    trades = run_backtest(df, strategy, MES, contracts=args.contracts,
                          max_trades_per_day=3)
    stats = compute_stats(trades)
    print(f"strategy: {args.strategy}  instrument: MES x{args.contracts}")
    print(f"backtest: {stats.summary()}\n")

    if stats.n_trades < 30:
        print("WARNING: <30 trades — statistics are meaningless. Get more data.")
        return
    base_risk = stats.avg_loss
    pool = normalize_days(trades, base_risk)

    policy = combined(buffer_scaled(alpha=1.2), coast_to_target())
    for profile in ALL_PROFILES:
        print(f"=== {profile.name} ===")
        buffer = profile.max_total_drawdown
        risks = [buffer * f for f in (0.02, 0.04, 0.07, 0.10, 0.15, 0.25)]
        results = sweep_risk(pool, profile, risks, policy=policy, n_sims=args.sims)
        for r in results:
            print("  " + r.summary())
        best, ev = optimal_risk(results, eval_fee=args.eval_fee,
                                funded_value=args.funded_value)
        print(
            f"  >> optimal: ${best.base_risk:,.0f}/trade, P(pass)={best.p_pass:.1%}, "
            f"EV/attempt=${ev:,.0f} (fee ${args.eval_fee:.0f}, "
            f"funded value ${args.funded_value:,.0f})\n"
        )


if __name__ == "__main__":
    main()
