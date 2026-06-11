"""End-to-end: synthetic data -> backtest -> stats -> Monte Carlo -> governor."""

from hightrader.backtest import MES, compute_stats, run_backtest
from hightrader.data import synthetic_intraday
from hightrader.firms import TOPSTEP_50K, AccountTracker, Status, TradeFill
from hightrader.montecarlo import normalize_days, simulate_eval
from hightrader.risk import RiskGovernor, Verdict, contracts_for_risk
from hightrader.strategies import MeanReversion, OpeningRangeBreakout


def test_full_pipeline_runs():
    df = synthetic_intraday(n_days=120, seed=3)
    trades = run_backtest(df, OpeningRangeBreakout(), MES, contracts=2,
                          max_trades_per_day=2)
    assert len(trades) > 20
    stats = compute_stats(trades)
    assert stats.n_trades == len(trades)
    base_risk = stats.avg_loss if stats.avg_loss > 0 else 100.0
    pool = normalize_days(trades, base_risk)
    res = simulate_eval(pool, TOPSTEP_50K, base_risk=200, n_sims=300)
    total = res.p_pass + res.p_fail_drawdown + res.p_fail_daily + res.p_timeout
    assert abs(total - 1.0) < 1e-9


def test_strategies_emit_trades_on_synthetic_data():
    df = synthetic_intraday(n_days=60, seed=9)
    for strat in (OpeningRangeBreakout(), MeanReversion()):
        trades = run_backtest(df, strat, MES, max_trades_per_day=3)
        assert len(trades) > 0, type(strat).__name__


def test_governor_blocks_after_soft_daily_stop():
    tracker = AccountTracker(
        __import__("hightrader.firms", fromlist=["FTMO_100K_PHASE1"]).FTMO_100K_PHASE1
    )
    gov = RiskGovernor(tracker.profile, tracker, soft_daily_stop_fraction=0.6)
    assert gov.check(500).verdict is Verdict.ALLOW
    tracker.apply_trade(TradeFill(pnl=-3100))  # past 60% of the 5k daily allowance
    assert gov.check(500).verdict is Verdict.BLOCK_DAILY


def test_governor_caps_oversized_risk():
    from hightrader.firms import FTMO_100K_PHASE1

    tracker = AccountTracker(FTMO_100K_PHASE1)
    gov = RiskGovernor(tracker.profile, tracker, max_risk_per_trade_fraction=0.10)
    d = gov.check(5000)  # 10% of 10k buffer = 1000 max
    assert d.verdict is Verdict.REDUCE
    assert d.max_risk == 1000


def test_kill_switch_blocks_everything():
    from hightrader.firms import FTMO_100K_PHASE1

    tracker = AccountTracker(FTMO_100K_PHASE1)
    gov = RiskGovernor(tracker.profile, tracker)
    gov.kill_switch("test")
    assert gov.check(10).verdict is Verdict.BLOCK_HALTED


def test_contracts_for_risk_floors_to_zero():
    assert contracts_for_risk(100, stop_distance_points=10, point_value=50) == 0
    assert contracts_for_risk(1000, stop_distance_points=4, point_value=50) == 5
