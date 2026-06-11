"""Monte Carlo evaluator sanity: the math must agree with gambler's-ruin logic."""

import pytest

from hightrader.firms import FTMO_100K_PHASE1, TOPSTEP_50K
from hightrader.montecarlo import (
    buffer_scaled,
    parametric_day_pool,
    simulate_eval,
    sweep_risk,
)


def test_no_edge_strategy_rarely_passes():
    # 50% win rate at 1:1 payoff minus nothing = zero edge. With a profit
    # target equal to the drawdown and unlimited time, pass odds hover near
    # the gambler's-ruin boundary; with FTMO's daily limit they must be < 50%.
    pool = parametric_day_pool(win_rate=0.5, payoff=1.0, trades_per_day=3)
    res = simulate_eval(pool, FTMO_100K_PHASE1, base_risk=1000, n_sims=1000)
    assert res.p_pass < 0.55


def test_positive_edge_beats_no_edge():
    edge = parametric_day_pool(win_rate=0.45, payoff=1.8, trades_per_day=3)
    no_edge = parametric_day_pool(win_rate=0.40, payoff=1.5, trades_per_day=3)
    r_edge = simulate_eval(edge, FTMO_100K_PHASE1, base_risk=800, n_sims=1500)
    r_none = simulate_eval(no_edge, FTMO_100K_PHASE1, base_risk=800, n_sims=1500)
    assert r_edge.p_pass > r_none.p_pass + 0.10


def test_oversizing_increases_bust_rate():
    pool = parametric_day_pool(win_rate=0.45, payoff=1.8, trades_per_day=3)
    small = simulate_eval(pool, FTMO_100K_PHASE1, base_risk=500, n_sims=1500)
    huge = simulate_eval(pool, FTMO_100K_PHASE1, base_risk=5000, n_sims=1500)
    bust_small = small.p_fail_drawdown + small.p_fail_daily
    bust_huge = huge.p_fail_drawdown + huge.p_fail_daily
    assert bust_huge > bust_small


def test_sweep_finds_interior_optimum_or_monotone():
    pool = parametric_day_pool(win_rate=0.45, payoff=1.8, trades_per_day=3)
    results = sweep_risk(
        pool, FTMO_100K_PHASE1, risk_levels=[250, 500, 1000, 2000, 4000], n_sims=1000
    )
    p = [r.p_pass for r in results]
    assert max(p) > p[-1]  # the largest size is never optimal here
    # Bust rate (drawdown + daily) must rise with size.
    bust = [r.p_fail_drawdown + r.p_fail_daily for r in results]
    assert bust[-1] > bust[0]


def test_buffer_scaling_reduces_drawdown_busts():
    pool = parametric_day_pool(win_rate=0.42, payoff=1.6, trades_per_day=4)
    fixed = simulate_eval(pool, TOPSTEP_50K, base_risk=400, n_sims=1500)
    scaled = simulate_eval(
        pool, TOPSTEP_50K, base_risk=400, policy=buffer_scaled(alpha=1.5), n_sims=1500
    )
    assert scaled.p_fail_drawdown <= fixed.p_fail_drawdown + 0.02


def test_trailing_eod_is_harsher_than_static_for_same_buffer():
    pool = parametric_day_pool(win_rate=0.45, payoff=1.8, trades_per_day=3)
    # Topstep's $2k trailing buffer vs FTMO's $10k static: risking the same
    # fraction of buffer, the trailing account should bust at least as often.
    topstep = simulate_eval(pool, TOPSTEP_50K, base_risk=200, n_sims=1500)
    ftmo = simulate_eval(pool, FTMO_100K_PHASE1, base_risk=1000, n_sims=1500)
    assert topstep.p_fail_drawdown >= ftmo.p_fail_drawdown - 0.02
