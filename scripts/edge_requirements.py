#!/usr/bin/env python3
"""Answer the foundational question: how much edge do you need?

Sweeps (win rate x payoff ratio) grids through each firm's rules at the
per-firm optimal risk size, printing P(pass). This tells you the minimum
strategy quality worth paying an eval fee for — and shows that below a
certain edge, NO position sizing can save you (gambler's ruin), while
above it, sizing is most of the game.
"""

from __future__ import annotations

import argparse

from hightrader.firms import ALL_PROFILES
from hightrader.montecarlo import (
    buffer_scaled,
    coast_to_target,
    combined,
    parametric_day_pool,
    sweep_risk,
)

WIN_RATES = [0.35, 0.40, 0.45, 0.50, 0.55]
PAYOFFS = [1.0, 1.5, 2.0, 2.5]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=1500)
    ap.add_argument("--trades-per-day", type=int, default=3)
    args = ap.parse_args()

    policy = combined(buffer_scaled(alpha=1.2), coast_to_target())
    for profile in ALL_PROFILES:
        print(f"=== {profile.name} ===")
        print(
            "P(pass) at per-cell optimal fixed size "
            f"({args.trades_per_day} trades/day):"
        )
        header = "  WR\\payoff " + "".join(f"{p:>8.1f}" for p in PAYOFFS)
        print(header)
        buffer = profile.max_total_drawdown
        for wr in WIN_RATES:
            cells = []
            for payoff in PAYOFFS:
                pool = parametric_day_pool(
                    wr, payoff, trades_per_day=args.trades_per_day
                )
                risks = [buffer * f for f in (0.02, 0.05, 0.10, 0.20)]
                results = sweep_risk(
                    pool, profile, risks, policy=policy, n_sims=args.sims
                )
                cells.append(max(r.p_pass for r in results))
            expectancy_note = ""
            print(
                f"  {wr:>9.0%} "
                + "".join(f"{c:>8.0%}" for c in cells)
                + expectancy_note
            )
        print()


if __name__ == "__main__":
    main()
