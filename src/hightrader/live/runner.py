"""Live/paper trading loop wiring strategy -> governor -> broker.

This is the supervised execution shell: it consumes completed bars, asks the
strategy for a signal, asks the RiskGovernor for permission and size, and
places bracket orders. A heartbeat + kill-switch path is wired so a human
(or watchdog) can flatten instantly — required by firms that mandate
supervision of automation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ..backtest.engine import Instrument, Strategy
from ..firms.rules import AccountTracker, TradeFill
from ..risk.governor import RiskGovernor, Verdict, contracts_for_risk
from .broker import Broker, Order

log = logging.getLogger("hightrader.live")


@dataclass
class LiveRunner:
    strategy: Strategy
    governor: RiskGovernor
    broker: Broker
    instrument: Instrument
    base_risk: float  # desired risk per trade in dollars
    _bars: Optional[pd.DataFrame] = None

    def on_bar(self, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Feed one completed OHLCV bar. Call in chronological order."""
        if self.governor.halted:
            self.broker.flatten_all()
            return
        row = bar.to_frame().T
        row.index = pd.DatetimeIndex([timestamp])
        self._bars = row if self._bars is None else pd.concat([self._bars, row])
        if len(self._bars) < 2:
            return

        df = self.strategy.prepare(self._bars.copy())
        if self.broker.positions():
            return  # brackets manage the open trade
        sig = self.strategy.signal(len(df) - 1, df)
        if sig is None:
            return

        entry_ref = float(df["close"].iloc[-1])
        stop_pts = abs(entry_ref - sig.stop)
        decision = self.governor.check(self.base_risk)
        if decision.verdict in (Verdict.ALLOW, Verdict.REDUCE):
            qty = contracts_for_risk(
                decision.max_risk, stop_pts, self.instrument.point_value
            )
            if qty < 1:
                log.info("signal skipped: approved risk too small for 1 contract")
                return
            self.broker.submit(
                Order(
                    symbol=self.instrument.symbol,
                    direction=sig.direction,
                    quantity=qty,
                    stop=sig.stop,
                    target=sig.target,
                )
            )
            self.governor.record_trade_opened()
            log.info(
                "entered %s x%d stop=%.2f target=%s (%s)",
                "long" if sig.direction > 0 else "short",
                qty,
                sig.stop,
                sig.target,
                decision.verdict.value,
            )
        else:
            log.info("signal blocked: %s", decision.reason)

    def on_trade_closed(self, pnl: float, mae: float = 0.0, mfe: float = 0.0) -> None:
        self.governor.tracker.apply_trade(TradeFill(pnl=pnl, mae=mae, mfe=mfe))

    def on_session_end(self) -> None:
        self.broker.flatten_all()
        self.governor.tracker.end_day()
        self.governor.new_day()
