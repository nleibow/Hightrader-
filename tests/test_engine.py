"""Backtest engine fill mechanics on hand-built bars."""

from typing import Optional

import pandas as pd
import pytest

from hightrader.backtest import Instrument, Signal, Strategy, run_backtest

INST = Instrument("TEST", point_value=10.0, tick_size=0.25, commission_per_side=1.0,
                  slippage_ticks=0.0)


def bars(rows, start="2024-01-02 09:30", freq="5min"):
    idx = pd.date_range(start, periods=len(rows), freq=freq)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=100)


class EnterOnceLong(Strategy):
    """Enter long on the first bar with a fixed stop/target."""

    def __init__(self, stop: float, target: Optional[float]):
        self.stop, self.target, self.fired = stop, target, False

    def signal(self, i, df):
        if not self.fired:
            self.fired = True
            return Signal(1, stop=self.stop, target=self.target)
        return None


def test_entry_fills_next_bar_open():
    df = bars([
        [100, 101, 99, 100],
        [102, 103, 101, 102],  # entry here at open=102
        [102, 102, 101, 101.5],
    ])
    trades = run_backtest(df, EnterOnceLong(stop=90, target=None), INST)
    assert len(trades) == 1
    assert trades[0].entry_price == 102


def test_stop_beats_target_when_both_in_bar():
    df = bars([
        [100, 101, 99, 100],
        [100, 100.5, 99.5, 100],          # entry at 100
        [100, 110, 95, 100],              # bar spans stop (98) and target (104)
    ])
    trades = run_backtest(df, EnterOnceLong(stop=98, target=104), INST)
    assert trades[0].exit_reason == "stop"
    assert trades[0].exit_price == 98


def test_target_fill_and_pnl():
    df = bars([
        [100, 101, 99, 100],
        [100, 100.5, 99.5, 100],  # entry at 100
        [100, 105, 99.9, 104],    # target 104 hit, stop 98 not
    ])
    trades = run_backtest(df, EnterOnceLong(stop=98, target=104), INST)
    t = trades[0]
    assert t.exit_reason == "target"
    # (104-100) * $10 - 2 sides * $1 commission
    assert t.pnl == pytest.approx(4 * 10 - 2)


def test_eod_flat():
    df = pd.concat([
        bars([[100, 101, 99, 100], [100, 101, 99, 100.5], [100.5, 101, 100, 100.8]],
             start="2024-01-02 09:30"),
        bars([[101, 102, 100, 101]], start="2024-01-03 09:30"),
    ])
    trades = run_backtest(df, EnterOnceLong(stop=90, target=200), INST)
    assert trades[0].exit_reason == "eod"
    assert trades[0].exit_time.date().isoformat() == "2024-01-02"


def test_mae_mfe_recorded():
    df = bars([
        [100, 101, 99, 100],
        [100, 100, 100, 100],   # entry at 100, flat bar
        [100, 106, 97, 104],    # target 104 (worst dip 97 first per conservatism)
    ])
    trades = run_backtest(df, EnterOnceLong(stop=95, target=104), INST)
    t = trades[0]
    assert t.mae == pytest.approx(3 * 10)   # 100 -> 97 = 3 pts * $10
    assert t.mfe >= 4 * 10


def test_short_side():
    class EnterOnceShort(Strategy):
        fired = False
        def signal(self, i, df):
            if not self.fired:
                self.fired = True
                return Signal(-1, stop=103, target=96)
            return None

    df = bars([
        [100, 101, 99, 100],
        [100, 100.5, 99.5, 100],  # short entry at 100
        [99, 99.5, 95, 96],       # target 96 hit
    ])
    trades = run_backtest(df, EnterOnceShort(), INST)
    t = trades[0]
    assert t.exit_reason == "target"
    assert t.pnl == pytest.approx((100 - 96) * 10 - 2)
