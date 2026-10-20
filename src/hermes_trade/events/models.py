"""Domain models for scheduled-event scenario playbooks (paper trading only).

A playbook is prepared *before* a scheduled event such as an FOMC or NBP RPP
rate decision. It lists the three possible outcomes (CUT / HOLD / HIKE) with
market-implied probabilities, and for each outcome a pre-planned set of
bracket orders (entry + mandatory stop-loss + take-profit, OCO semantics).

Surprise is always measured relative to the *market expectation* (the
scenario with the highest implied probability), not relative to the previous
rate: a HOLD when a CUT was priced is a hawkish surprise.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from hermes_trade.models import OrderSide, TradeSignal


class EventKind(StrEnum):
    """Supported scheduled central-bank events."""

    FOMC = "FOMC"
    NBP_RPP = "NBP_RPP"


class ScenarioName(StrEnum):
    """Possible rate-decision outcomes, ordered dovish -> hawkish."""

    CUT = "CUT"
    HOLD = "HOLD"
    HIKE = "HIKE"


_ORDINAL: dict[ScenarioName, int] = {
    ScenarioName.CUT: -1,
    ScenarioName.HOLD: 0,
    ScenarioName.HIKE: 1,
}


class SurpriseDirection(StrEnum):
    """Direction of the outcome relative to what the market priced."""

    DOVISH = "DOVISH"
    NONE = "NONE"
    HAWKISH = "HAWKISH"


def classify_surprise(actual: ScenarioName, expected: ScenarioName) -> SurpriseDirection:
    """Classify the surprise of ``actual`` relative to the market-``expected`` scenario."""
    diff = _ORDINAL[actual] - _ORDINAL[expected]
    if diff > 0:
        return SurpriseDirection.HAWKISH
    if diff < 0:
        return SurpriseDirection.DOVISH
    return SurpriseDirection.NONE


def surprise_steps(actual: ScenarioName, expected: ScenarioName) -> int:
    """Signed number of scenario steps between actual and expected (+ = hawkish)."""
    return _ORDINAL[actual] - _ORDINAL[expected]


class ScheduledEvent(BaseModel):
    """A scheduled event with a known announcement time."""

    id: str = Field(..., min_length=1)
    kind: EventKind
    scheduled_at: datetime
    source_url: str = Field(..., min_length=1)
    previous_rate: Decimal = Field(
        ...,
        ge=0,
        description="FOMC: upper bound of the current target range; NBP: reference rate.",
    )

    @field_validator("scheduled_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if offset is None:
            raise ValueError("scheduled_at must be timezone-aware (UTC)")
        if offset.total_seconds() != 0:
            raise ValueError("scheduled_at must be expressed in UTC")
        return value


class Scenario(BaseModel):
    """One possible outcome with its market-implied probability."""

    name: ScenarioName
    expected_probability: float = Field(..., ge=0.0, le=1.0)
    description: str = ""


class BracketLeg(BaseModel):
    """An entry signal plus its protective stop and take-profit (OCO pair).

    ``signal.stop_price`` is the stop-loss trigger and is mandatory.
    ``take_profit_price`` is the profit target; whichever fills first cancels
    the other.
    """

    signal: TradeSignal
    take_profit_price: Decimal = Field(..., gt=0)

    @model_validator(mode="after")
    def _check_bracket(self) -> BracketLeg:
        stop = self.signal.stop_price
        if stop is None:
            raise ValueError(f"{self.signal.symbol}: stop_price is mandatory for event trades")
        if stop <= 0:
            raise ValueError(f"{self.signal.symbol}: stop_price must be positive")
        tp = self.take_profit_price
        entry = self.signal.limit_price
        if self.signal.side == OrderSide.BUY:
            if not stop < tp:
                raise ValueError(f"{self.signal.symbol}: BUY bracket needs stop < take-profit")
            if entry is not None and not stop < entry < tp:
                raise ValueError(f"{self.signal.symbol}: BUY bracket needs stop < limit < TP")
        else:
            if not stop > tp:
                raise ValueError(f"{self.signal.symbol}: SELL bracket needs stop > take-profit")
            if entry is not None and not stop > entry > tp:
                raise ValueError(f"{self.signal.symbol}: SELL bracket needs stop > limit > TP")
        return self


class ScenarioPlan(BaseModel):
    """The pre-planned order set fired when a scenario materialises.

    An empty ``legs`` list is valid and means "do nothing" (typical for the
    no-surprise scenario).
    """

    scenario: ScenarioName
    legs: list[BracketLeg] = Field(default_factory=list)
    notes: str = ""

    @property
    def signals(self) -> list[TradeSignal]:
        """The entry signals of this plan."""
        return [leg.signal for leg in self.legs]


class PrepositionedPlan(BaseModel):
    """A position opened *before* the event on the scenario we expect.

    Sized below its own cap (sum of leg quantities). If a different scenario
    materialises, the dispatcher unwinds these legs at market.
    """

    scenario: ScenarioName
    legs: list[BracketLeg] = Field(..., min_length=1)
    max_total_quantity: Decimal = Field(..., gt=0)
    notes: str = ""

    @model_validator(mode="after")
    def _check_cap(self) -> PrepositionedPlan:
        total = sum((leg.signal.quantity for leg in self.legs), Decimal("0"))
        if total > self.max_total_quantity:
            raise ValueError(
                f"pre-positioned quantity {total} exceeds cap {self.max_total_quantity}"
            )
        return self


class EventPlaybook(BaseModel):
    """Everything prepared before an event: scenarios, plans, optional pre-position."""

    event: ScheduledEvent
    scenarios: list[Scenario] = Field(..., min_length=3, max_length=3)
    plans: dict[ScenarioName, ScenarioPlan]
    prepositioned: PrepositionedPlan | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> EventPlaybook:
        names = {s.name for s in self.scenarios}
        if names != set(ScenarioName):
            raise ValueError("scenarios must be exactly CUT, HOLD and HIKE")
        total = sum(s.expected_probability for s in self.scenarios)
        if abs(total - 1.0) > 0.02:
            raise ValueError(f"scenario probabilities must sum to 1 (got {total:.3f})")
        probs = sorted((s.expected_probability for s in self.scenarios), reverse=True)
        if probs[0] == probs[1]:
            raise ValueError("market expectation is ambiguous: two scenarios tie for max")
        if set(self.plans) != set(ScenarioName):
            raise ValueError("plans must define CUT, HOLD and HIKE (legs may be empty)")
        for key, plan in self.plans.items():
            if plan.scenario != key:
                raise ValueError(f"plan under key {key} is for scenario {plan.scenario}")
        return self

    @property
    def expected_scenario(self) -> ScenarioName:
        """The scenario the market prices as most likely."""
        return max(self.scenarios, key=lambda s: s.expected_probability).name

    def surprise_of(self, actual: ScenarioName) -> SurpriseDirection:
        """Surprise direction of ``actual`` relative to the market expectation."""
        return classify_surprise(actual, self.expected_scenario)

    def plan_for(self, actual: ScenarioName) -> ScenarioPlan:
        """The pre-planned order set for ``actual``."""
        return self.plans[actual]
