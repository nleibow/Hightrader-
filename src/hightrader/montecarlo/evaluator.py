"""Monte Carlo evaluation-pass engine.

The core insight of this system: a prop eval is a stochastic control problem.
Given a strategy's per-trade outcome distribution, the probability of hitting
the profit target before breaching the drawdown rules is a function of how
much you risk per trade — and that function has a maximum. Risk too little
and variance never carries you to target (or it takes forever); risk too
much and gambler's ruin eats you via the trailing drawdown.

This module:
1. Bootstraps trading DAYS (not individual trades, preserving the intraday
   correlation that makes daily-loss rules bite) from a backtest.
2. Replays them through the exact firm rule engine at a chosen risk scale
   and sizing policy.
3. Reports P(pass), P(fail), time-to-outcome, and the expected cost in eval
   fees per funded account.
4. Sweeps risk levels to find the sizing that maximizes pass probability or
   fee-adjusted EV.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

import numpy as np

from ..backtest.engine import Trade
from ..backtest.stats import trades_by_day
from ..firms.rules import AccountTracker, FirmProfile, Status, TradeFill

# One trade outcome normalized per $1 of base risk: (pnl, mae, mfe).
DayOutcomes = List[tuple]

SizingPolicy = Callable[[AccountTracker, float], float]
"""Maps (account state, base_risk_dollars) -> risk dollars for the next trade."""


def fixed_risk(tracker: AccountTracker, base: float) -> float:
    return base


def buffer_scaled(alpha: float = 1.0, floor_fraction: float = 0.25) -> SizingPolicy:
    """Risk shrinks as the drawdown buffer shrinks: survive losing streaks.

    risk = base * (buffer_now / buffer_initial) ** alpha, floored.
    """

    def policy(tracker: AccountTracker, base: float) -> float:
        initial_buffer = tracker.profile.max_total_drawdown
        frac = max(tracker.drawdown_buffer, 0.0) / initial_buffer
        return base * max(frac**alpha, floor_fraction)

    return policy


def coast_to_target(near_fraction: float = 0.25, cut_to: float = 0.5) -> SizingPolicy:
    """Cut risk once most of the target is banked: protect the pass.

    When remaining distance to target < near_fraction * profit_target,
    risk drops to cut_to * base.
    """

    def policy(tracker: AccountTracker, base: float) -> float:
        if tracker.to_target < near_fraction * tracker.profile.profit_target:
            return base * cut_to
        return base

    return policy


def combined(*policies: SizingPolicy) -> SizingPolicy:
    def policy(tracker: AccountTracker, base: float) -> float:
        risk = base
        for p in policies:
            risk = min(risk, p(tracker, base) if p is not fixed_risk else risk)
        return risk

    return policy


@dataclass
class EvalResult:
    profile_name: str
    base_risk: float
    n_sims: int
    p_pass: float
    p_fail_drawdown: float
    p_fail_daily: float
    p_timeout: float  # still active at sim horizon
    median_days_to_pass: Optional[float]
    expected_attempts_per_pass: Optional[float]

    def summary(self) -> str:
        med = f"{self.median_days_to_pass:.0f}d" if self.median_days_to_pass else "n/a"
        att = (
            f"{self.expected_attempts_per_pass:.1f}"
            if self.expected_attempts_per_pass
            else "inf"
        )
        return (
            f"risk=${self.base_risk:,.0f}/trade  P(pass)={self.p_pass:.1%}  "
            f"P(dd)={self.p_fail_drawdown:.1%}  P(daily)={self.p_fail_daily:.1%}  "
            f"P(timeout)={self.p_timeout:.1%}  median pass={med}  "
            f"attempts/pass={att}"
        )


def normalize_days(trades: Sequence[Trade], base_risk: float) -> List[DayOutcomes]:
    """Convert backtest trades into per-$1-risk day blocks for bootstrapping.

    base_risk: the dollar risk per trade the backtest was run at (e.g. the
    average losing trade, or stop distance * point value * contracts).
    """
    days = trades_by_day(trades)
    return [
        [(t.pnl / base_risk, t.mae / base_risk, t.mfe / base_risk) for t in day]
        for day in days
    ]


def simulate_eval(
    day_pool: List[DayOutcomes],
    profile: FirmProfile,
    base_risk: float,
    policy: SizingPolicy = fixed_risk,
    n_sims: int = 2000,
    max_days: int = 250,
    seed: int = 7,
) -> EvalResult:
    """Bootstrap days through the firm rule engine at a given risk scale."""
    rng = np.random.default_rng(seed)
    n_pool = len(day_pool)
    outcomes = {s: 0 for s in Status}
    pass_days: List[int] = []

    for _ in range(n_sims):
        tracker = AccountTracker(profile)
        day_idx = rng.integers(0, n_pool, size=max_days)
        for d in range(max_days):
            for pnl_r, mae_r, mfe_r in day_pool[day_idx[d]]:
                risk = policy(tracker, base_risk)
                tracker.apply_trade(
                    TradeFill(pnl=pnl_r * risk, mae=mae_r * risk, mfe=mfe_r * risk)
                )
                if tracker.status is not Status.ACTIVE:
                    break
            tracker.end_day()
            if tracker.status is not Status.ACTIVE:
                if tracker.status is Status.PASSED:
                    pass_days.append(d + 1)
                break
        outcomes[tracker.status] += 1

    p_pass = outcomes[Status.PASSED] / n_sims
    return EvalResult(
        profile_name=profile.name,
        base_risk=base_risk,
        n_sims=n_sims,
        p_pass=p_pass,
        p_fail_drawdown=outcomes[Status.FAILED_DRAWDOWN] / n_sims,
        p_fail_daily=outcomes[Status.FAILED_DAILY_LOSS] / n_sims,
        p_timeout=outcomes[Status.ACTIVE] / n_sims,
        median_days_to_pass=float(np.median(pass_days)) if pass_days else None,
        expected_attempts_per_pass=(1.0 / p_pass) if p_pass > 0 else None,
    )


def sweep_risk(
    day_pool: List[DayOutcomes],
    profile: FirmProfile,
    risk_levels: Sequence[float],
    policy: SizingPolicy = fixed_risk,
    n_sims: int = 2000,
    **kw,
) -> List[EvalResult]:
    return [
        simulate_eval(day_pool, profile, r, policy=policy, n_sims=n_sims, **kw)
        for r in risk_levels
    ]


def optimal_risk(
    results: Sequence[EvalResult],
    eval_fee: float = 150.0,
    funded_value: float = 4000.0,
) -> tuple:
    """Pick the risk level maximizing fee-adjusted EV.

    EV per attempt = P(pass) * funded_value - eval_fee, where funded_value is
    your realistic expected payout from one funded account (most funded
    accounts also bust — be honest with this number).
    """
    best = max(results, key=lambda r: r.p_pass * funded_value - eval_fee)
    ev = best.p_pass * funded_value - eval_fee
    return best, ev


def parametric_day_pool(
    win_rate: float,
    payoff: float,
    trades_per_day: int = 3,
    n_days: int = 500,
    seed: int = 11,
) -> List[DayOutcomes]:
    """Generate a synthetic day pool from (win rate, payoff ratio) instead of
    a backtest — useful for 'what edge do I need?' analysis. Losses are -1R.

    The pool contains EXACTLY round(win_rate * total) wins, shuffled: a
    randomly sampled pool would carry sampling error in its realized win
    rate, which the bootstrap would then amplify into a biased P(pass).
    """
    rng = np.random.default_rng(seed)
    total = n_days * trades_per_day
    n_wins = round(win_rate * total)
    win = (payoff, 0.25, payoff)
    loss = (-1.0, 1.0, 0.1)
    outcomes = [win] * n_wins + [loss] * (total - n_wins)
    rng.shuffle(outcomes)
    return [
        list(outcomes[d * trades_per_day : (d + 1) * trades_per_day])
        for d in range(n_days)
    ]
