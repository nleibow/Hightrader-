"""Rule engine correctness: each firm's drawdown mechanics, exactly."""

import pytest

from hightrader.firms import (
    APEX_50K,
    FTMO_100K_PHASE1,
    TOPSTEP_50K,
    AccountTracker,
    DrawdownMode,
    FirmProfile,
    Status,
    TradeFill,
)


def make_profile(**kw) -> FirmProfile:
    base = dict(
        name="test",
        account_size=100_000,
        profit_target=10_000,
        max_total_drawdown=10_000,
        drawdown_mode=DrawdownMode.STATIC,
        max_daily_loss=5_000,
        min_trading_days=0,
    )
    base.update(kw)
    return FirmProfile(**base)


class TestDailyLoss:
    def test_realized_daily_loss_breach(self):
        t = AccountTracker(make_profile())
        t.apply_trade(TradeFill(pnl=-3000))
        assert t.status is Status.ACTIVE
        t.apply_trade(TradeFill(pnl=-2000))
        assert t.status is Status.FAILED_DAILY_LOSS

    def test_floating_loss_counts_toward_daily(self):
        # FTMO counts open P&L: -3000 realized then a trade whose MAE is 2000
        # touches -5000 intraday even though it closes green.
        t = AccountTracker(make_profile())
        t.apply_trade(TradeFill(pnl=-3000))
        t.apply_trade(TradeFill(pnl=+500, mae=2000))
        assert t.status is Status.FAILED_DAILY_LOSS

    def test_daily_resets_at_end_of_day(self):
        t = AccountTracker(make_profile())
        t.apply_trade(TradeFill(pnl=-4000))
        t.end_day()
        t.apply_trade(TradeFill(pnl=-4000))
        assert t.status is Status.ACTIVE  # only -4000 today


class TestStaticDrawdown:
    def test_static_floor_breach(self):
        t = AccountTracker(make_profile(max_daily_loss=None))
        for _ in range(3):
            t.apply_trade(TradeFill(pnl=-3000))
            t.end_day()
        assert t.status is Status.ACTIVE  # at 91k, floor 90k
        t.apply_trade(TradeFill(pnl=-1000))
        assert t.status is Status.FAILED_DRAWDOWN

    def test_static_floor_does_not_trail(self):
        t = AccountTracker(make_profile(max_daily_loss=None))
        t.apply_trade(TradeFill(pnl=+8000))
        t.end_day()
        assert t.loss_floor == 90_000  # still based on initial


class TestTrailingEOD:
    def test_floor_trails_eod_high_and_locks_at_initial(self):
        p = make_profile(
            account_size=50_000,
            profit_target=3_000,
            max_total_drawdown=2_000,
            drawdown_mode=DrawdownMode.TRAILING_EOD,
            max_daily_loss=None,
        )
        t = AccountTracker(p)
        assert t.loss_floor == 48_000
        t.apply_trade(TradeFill(pnl=+1000))
        assert t.loss_floor == 48_000  # intraday gain doesn't move EOD floor
        t.end_day()
        assert t.loss_floor == 49_000
        t.apply_trade(TradeFill(pnl=+2500))
        t.end_day()
        assert t.loss_floor == 50_000  # locked at initial balance
        t.apply_trade(TradeFill(pnl=+5000))
        t.end_day()
        assert t.loss_floor == 50_000

    def test_intraday_dip_below_eod_floor_breaches(self):
        p = make_profile(
            account_size=50_000,
            max_total_drawdown=2_000,
            drawdown_mode=DrawdownMode.TRAILING_EOD,
            max_daily_loss=None,
        )
        t = AccountTracker(p)
        t.apply_trade(TradeFill(pnl=-1500, mae=2100))
        assert t.status is Status.FAILED_DRAWDOWN


class TestTrailingIntraday:
    def test_floor_trails_intraday_high(self):
        p = make_profile(
            account_size=50_000,
            profit_target=3_000,
            max_total_drawdown=2_500,
            drawdown_mode=DrawdownMode.TRAILING_INTRADAY,
            max_daily_loss=None,
            trailing_lock_offset=100.0,
        )
        t = AccountTracker(p)
        # Trade runs +2000 in our favor (mfe) but closes flat: the threshold
        # trailed up with the intraday high.
        t.apply_trade(TradeFill(pnl=0, mfe=2000))
        assert t.loss_floor == pytest.approx(49_500)
        # Lock: high water 53_000 -> floor capped at initial + 100.
        t.apply_trade(TradeFill(pnl=+3000))
        assert t.loss_floor == pytest.approx(50_100)


class TestPassing:
    def test_pass_requires_min_days(self):
        t = AccountTracker(make_profile(min_trading_days=4))
        t.apply_trade(TradeFill(pnl=+10_000))
        t.end_day()
        assert t.status is Status.ACTIVE  # target hit, days not met
        for _ in range(3):
            t.apply_trade(TradeFill(pnl=+10))
            t.end_day()
        assert t.status is Status.PASSED

    def test_consistency_rule_blocks_pass(self):
        t = AccountTracker(
            make_profile(min_trading_days=0, consistency_max_day_fraction=0.5)
        )
        t.apply_trade(TradeFill(pnl=+9_000))
        t.end_day()
        t.apply_trade(TradeFill(pnl=+1_500))
        t.end_day()
        # best day 9000 > 50% of 10500 -> not passed yet
        assert t.status is Status.ACTIVE
        t.apply_trade(TradeFill(pnl=+8_000))
        t.end_day()
        # total 18500, best day 9000 < 9250 -> passes
        assert t.status is Status.PASSED

    def test_preset_profiles_instantiate(self):
        for p in (FTMO_100K_PHASE1, TOPSTEP_50K, APEX_50K):
            t = AccountTracker(p)
            assert t.status is Status.ACTIVE
            assert t.drawdown_buffer > 0
