"""Scenario dispatcher: fires the pre-planned order set for the parsed outcome.

PAPER ONLY. Nothing in this module talks to a broker. Every entry signal is
passed through the existing :class:`~hermes_trade.execution.RiskManager`;
rejections are kept with their reasons. A file-based kill switch
(default ``~/.hermes/trade/STOP``) blocks all dispatching when present.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import structlog

from hermes_trade.events.models import (
    BracketLeg,
    EventPlaybook,
    ScenarioName,
    SurpriseDirection,
)
from hermes_trade.events.parser import ParsedDecision
from hermes_trade.execution import RiskManager
from hermes_trade.models import Order, OrderSide, OrderStatus, OrderType, TradeSignal

logger = structlog.get_logger(__name__)

DEFAULT_KILL_SWITCH_PATH = Path("~/.hermes/trade/STOP")


class KillSwitch:
    """File-based kill switch: if the file exists, nothing is dispatched."""

    def __init__(self, path: Path | str = DEFAULT_KILL_SWITCH_PATH) -> None:
        self.path = Path(path).expanduser()

    def is_engaged(self) -> bool:
        return self.path.exists()


@dataclass(frozen=True)
class PaperBracket:
    """A simulated bracket: entry order plus OCO stop-loss / take-profit pair."""

    entry: Order
    stop_price: Decimal
    take_profit_price: Decimal
    oco_group: str


class PaperExecutor:
    """Executor stub that only records and logs orders. Never calls a broker."""

    broker_name = "paper"

    def __init__(self) -> None:
        self.orders: list[Order] = []
        self.brackets: list[PaperBracket] = []

    def _order(self, signal: TradeSignal) -> Order:
        order = Order(
            id=f"paper-{uuid.uuid4().hex[:12]}",
            broker=self.broker_name,
            symbol=signal.symbol,
            side=signal.side,
            order_type=signal.order_type,
            quantity=signal.quantity,
            status=OrderStatus.SUBMITTED,
        )
        self.orders.append(order)
        return order

    def submit_bracket(self, leg: BracketLeg) -> PaperBracket:
        """Record a bracket order (entry + stop + take-profit, OCO)."""
        stop = leg.signal.stop_price
        if stop is None:  # guarded by BracketLeg validation; kept for type safety
            raise ValueError("bracket without stop_price")
        bracket = PaperBracket(
            entry=self._order(leg.signal),
            stop_price=stop,
            take_profit_price=leg.take_profit_price,
            oco_group=f"oco-{uuid.uuid4().hex[:8]}",
        )
        self.brackets.append(bracket)
        logger.info(
            "paper_bracket",
            symbol=leg.signal.symbol,
            side=leg.signal.side,
            qty=str(leg.signal.quantity),
            stop=str(stop),
            take_profit=str(leg.take_profit_price),
        )
        return bracket

    def submit_market(self, signal: TradeSignal) -> Order:
        """Record a plain market order (used for unwinding a pre-position)."""
        order = self._order(signal)
        logger.info(
            "paper_market", symbol=signal.symbol, side=signal.side, qty=str(signal.quantity)
        )
        return order


@dataclass(frozen=True)
class Rejection:
    signal: TradeSignal
    reason: str


@dataclass
class DispatchResult:
    """What the dispatcher did (or refused to do) for one event."""

    event_id: str
    scenario: ScenarioName | None = None
    surprise: SurpriseDirection | None = None
    halted: bool = False
    halt_reason: str = ""
    submitted: list[PaperBracket] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    unwound: list[Order] = field(default_factory=list)


class ScenarioDispatcher:
    """Turns a parsed outcome into paper orders according to a playbook.

    Args:
        risk_manager: Existing risk manager; every entry goes through it.
        executor: Paper executor (the only executor supported).
        kill_switch: File-based kill switch.
        max_delay: How long after ``scheduled_at`` an outcome may still be
            dispatched. Protects against reacting to stale pages.
    """

    def __init__(
        self,
        risk_manager: RiskManager,
        executor: PaperExecutor | None = None,
        kill_switch: KillSwitch | None = None,
        max_delay: timedelta = timedelta(minutes=30),
    ) -> None:
        self.risk = risk_manager
        self.executor = executor or PaperExecutor()
        self.kill_switch = kill_switch or KillSwitch()
        self.max_delay = max_delay
        self._dispatched: set[str] = set()
        self._prepositioned: set[str] = set()

    def _halt(self, result: DispatchResult, reason: str) -> DispatchResult:
        result.halted = True
        result.halt_reason = reason
        logger.warning("event_dispatch_halted", event_id=result.event_id, reason=reason)
        return result

    def _submit_legs(self, legs: list[BracketLeg], result: DispatchResult) -> None:
        for leg in legs:
            check = self.risk.check_signal(leg.signal)
            if not check.approved:
                result.rejected.append(Rejection(leg.signal, check.reason))
                continue
            self.risk.record_trade(leg.signal)
            result.submitted.append(self.executor.submit_bracket(leg))

    def dispatch_prepositioned(
        self, playbook: EventPlaybook, now: datetime | None = None
    ) -> DispatchResult:
        """Open the pre-positioned plan. Only allowed before the event."""
        now = now or datetime.now(UTC)
        event = playbook.event
        result = DispatchResult(event_id=event.id)
        if self.kill_switch.is_engaged():
            return self._halt(result, f"kill switch engaged ({self.kill_switch.path})")
        pre = playbook.prepositioned
        if pre is None:
            return self._halt(result, "playbook has no pre-positioned plan")
        if now >= event.scheduled_at:
            return self._halt(result, "too late to pre-position: event time has passed")
        if event.id in self._prepositioned:
            return self._halt(result, "already pre-positioned for this event")
        self._prepositioned.add(event.id)
        result.scenario = pre.scenario
        result.surprise = playbook.surprise_of(pre.scenario)
        self._submit_legs(pre.legs, result)
        return result

    def dispatch(
        self,
        playbook: EventPlaybook,
        decision: ParsedDecision,
        now: datetime | None = None,
    ) -> DispatchResult:
        """Fire the plan matching ``decision`` (and unwind a wrong pre-position)."""
        now = now or datetime.now(UTC)
        event = playbook.event
        result = DispatchResult(event_id=event.id)
        if self.kill_switch.is_engaged():
            return self._halt(result, f"kill switch engaged ({self.kill_switch.path})")
        if decision.kind != event.kind:
            return self._halt(result, f"decision is for {decision.kind}, event is {event.kind}")
        if decision.previous_rate is not None and decision.previous_rate != event.previous_rate:
            return self._halt(result, "decision parsed against a different previous rate")
        if now < event.scheduled_at:
            return self._halt(result, "announcement time not reached; statement may be stale")
        if now > event.scheduled_at + self.max_delay:
            return self._halt(result, f"more than {self.max_delay} after the event; not reacting")
        if event.id in self._dispatched:
            return self._halt(result, "event already dispatched")
        self._dispatched.add(event.id)

        result.scenario = decision.scenario
        result.surprise = playbook.surprise_of(decision.scenario)
        logger.info(
            "event_outcome",
            event_id=event.id,
            scenario=decision.scenario,
            surprise=result.surprise,
            new_rate=str(decision.new_rate),
        )

        pre = playbook.prepositioned
        if (
            pre is not None
            and event.id in self._prepositioned
            and pre.scenario != decision.scenario
        ):
            for leg in pre.legs:
                exit_signal = TradeSignal(
                    symbol=leg.signal.symbol,
                    side=OrderSide.SELL if leg.signal.side == OrderSide.BUY else OrderSide.BUY,
                    quantity=leg.signal.quantity,
                    order_type=OrderType.MARKET,
                    confidence=1.0,
                    reason=f"unwind pre-position: outcome {decision.scenario} != {pre.scenario}",
                )
                # Risk-reducing exit: not subject to entry checks.
                result.unwound.append(self.executor.submit_market(exit_signal))

        self._submit_legs(playbook.plan_for(decision.scenario).legs, result)
        return result
