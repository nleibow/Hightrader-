"""Broker abstraction + paper broker for dry runs.

Real adapters (MT5 for FTMO-style firms, Tradovate/Rithmic for futures
firms) implement the same interface, so the strategy/risk stack is
identical in backtest, paper, and live.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Order:
    symbol: str
    direction: int  # +1 / -1
    quantity: int
    stop: Optional[float] = None
    target: Optional[float] = None


@dataclass
class Position:
    symbol: str
    direction: int
    quantity: int
    entry_price: float


class Broker(abc.ABC):
    @abc.abstractmethod
    def submit(self, order: Order) -> str: ...

    @abc.abstractmethod
    def flatten_all(self) -> None:
        """Emergency exit — must be reliable above all else."""

    @abc.abstractmethod
    def positions(self) -> List[Position]: ...

    @abc.abstractmethod
    def equity(self) -> float: ...


@dataclass
class PaperBroker(Broker):
    """In-memory fills at the provided mark price. For dry runs and tests."""

    starting_cash: float = 100_000.0
    point_values: Dict[str, float] = field(default_factory=dict)
    _cash: float = field(init=False)
    _positions: Dict[str, Position] = field(default_factory=dict, init=False)
    _marks: Dict[str, float] = field(default_factory=dict, init=False)
    _next_id: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._cash = self.starting_cash

    def mark(self, symbol: str, price: float) -> None:
        self._marks[symbol] = price

    def submit(self, order: Order) -> str:
        px = self._marks.get(order.symbol)
        if px is None:
            raise RuntimeError(f"no mark price for {order.symbol}")
        existing = self._positions.get(order.symbol)
        if existing and existing.direction != order.direction:
            self._close(order.symbol, px)
        if order.symbol not in self._positions:
            self._positions[order.symbol] = Position(
                order.symbol, order.direction, order.quantity, px
            )
        self._next_id += 1
        return str(self._next_id)

    def _close(self, symbol: str, px: float) -> None:
        pos = self._positions.pop(symbol)
        pv = self.point_values.get(symbol, 1.0)
        self._cash += (px - pos.entry_price) * pos.direction * pos.quantity * pv

    def flatten_all(self) -> None:
        for symbol in list(self._positions):
            self._close(symbol, self._marks[symbol])

    def positions(self) -> List[Position]:
        return list(self._positions.values())

    def equity(self) -> float:
        eq = self._cash
        for pos in self._positions.values():
            pv = self.point_values.get(pos.symbol, 1.0)
            px = self._marks.get(pos.symbol, pos.entry_price)
            eq += (px - pos.entry_price) * pos.direction * pos.quantity * pv
        return eq
