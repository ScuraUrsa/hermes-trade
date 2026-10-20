"""Tests for event playbook models, dispatcher, kill switch and risk integration."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hermes_trade.events import (
    BracketLeg,
    EventKind,
    EventPlaybook,
    KillSwitch,
    PaperExecutor,
    ScenarioDispatcher,
    ScenarioName,
    SurpriseDirection,
    classify_surprise,
    load_playbooks,
    parse_fomc_statement,
    surprise_steps,
)
from hermes_trade.execution import RiskManager
from hermes_trade.models import OrderSide, RiskLimits, TradeSignal

EVENT_TIME = datetime(2026, 10, 28, 18, 0, tzinfo=UTC)
EXAMPLE_CONFIG = Path(__file__).resolve().parents[2] / "config" / "events.example.yaml"

HOLD_TEXT = (
    "the Committee decided to maintain the target range for the federal funds rate "
    "at 3-1/2 to 3-3/4 percent."
)
CUT_TEXT = (
    "the Committee decided to lower the target range for the federal funds rate by "
    "1/4 percentage point to 3-1/4 to 3-1/2 percent."
)


def leg(
    symbol: str,
    side: OrderSide,
    qty: str,
    stop: str,
    tp: str,
    confidence: float = 0.8,
) -> dict[str, Any]:
    return {
        "signal": {
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "stop_price": stop,
            "confidence": confidence,
            "reason": "test",
        },
        "take_profit_price": tp,
    }


def playbook_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "event": {
            "id": "fomc-test",
            "kind": "FOMC",
            "scheduled_at": EVENT_TIME,
            "source_url": "https://www.federalreserve.gov/",
            "previous_rate": "3.75",
        },
        "scenarios": [
            {"name": "CUT", "expected_probability": 0.8},
            {"name": "HOLD", "expected_probability": 0.18},
            {"name": "HIKE", "expected_probability": 0.02},
        ],
        "plans": {
            "CUT": {"scenario": "CUT", "legs": []},
            "HOLD": {
                "scenario": "HOLD",
                "legs": [
                    leg("TLT", OrderSide.SELL, "5", "92", "87"),
                    leg("SPY", OrderSide.SELL, "2", "690", "660"),
                ],
            },
            "HIKE": {
                "scenario": "HIKE",
                "legs": [leg("TLT", OrderSide.SELL, "8", "92", "85")],
            },
        },
        "prepositioned": {
            "scenario": "CUT",
            "max_total_quantity": "3",
            "legs": [leg("TLT", OrderSide.BUY, "3", "87", "93")],
        },
    }
    data.update(overrides)
    return data


@pytest.fixture
def playbook() -> EventPlaybook:
    return EventPlaybook.model_validate(playbook_data())


@pytest.fixture
def limits() -> RiskLimits:
    return RiskLimits(
        max_position_size=Decimal("10"),
        max_daily_loss=Decimal("500"),
        max_drawdown_pct=20.0,
        max_trades_per_day=10,
        stop_loss_pct=2.0,
    )


@pytest.fixture
def stop_file(tmp_path: Path) -> Path:
    return tmp_path / "STOP"


@pytest.fixture
def dispatcher(limits: RiskLimits, stop_file: Path) -> ScenarioDispatcher:
    return ScenarioDispatcher(RiskManager(limits), PaperExecutor(), KillSwitch(stop_file))


AFTER = EVENT_TIME + timedelta(seconds=5)
BEFORE = EVENT_TIME - timedelta(hours=1)


class TestSurprise:
    def test_hold_when_cut_priced_is_hawkish(self, playbook: EventPlaybook) -> None:
        assert playbook.expected_scenario == ScenarioName.CUT
        assert playbook.surprise_of(ScenarioName.HOLD) == SurpriseDirection.HAWKISH
        assert playbook.surprise_of(ScenarioName.CUT) == SurpriseDirection.NONE

    def test_cut_when_hold_priced_is_dovish(self) -> None:
        assert classify_surprise(ScenarioName.CUT, ScenarioName.HOLD) == SurpriseDirection.DOVISH
        assert surprise_steps(ScenarioName.HIKE, ScenarioName.CUT) == 2


class TestModels:
    def test_stop_is_mandatory(self) -> None:
        bad = leg("SPY", OrderSide.BUY, "1", "1", "2")
        bad["signal"]["stop_price"] = None
        with pytest.raises(ValidationError, match="stop_price is mandatory"):
            BracketLeg.model_validate(bad)

    def test_bracket_orientation(self) -> None:
        with pytest.raises(ValidationError, match="BUY bracket"):
            BracketLeg.model_validate(leg("SPY", OrderSide.BUY, "1", "110", "100"))
        with pytest.raises(ValidationError, match="SELL bracket"):
            BracketLeg.model_validate(leg("SPY", OrderSide.SELL, "1", "100", "110"))

    def test_bracket_with_limit_between(self) -> None:
        data = leg("SPY", OrderSide.BUY, "1", "90", "110")
        data["signal"]["limit_price"] = "120"
        with pytest.raises(ValidationError, match="stop < limit < TP"):
            BracketLeg.model_validate(data)

    def test_prepositioned_cap(self) -> None:
        data = playbook_data()
        data["prepositioned"]["max_total_quantity"] = "2"
        with pytest.raises(ValidationError, match="exceeds cap"):
            EventPlaybook.model_validate(data)

    def test_probabilities_must_sum_to_one(self) -> None:
        data = playbook_data()
        data["scenarios"][0]["expected_probability"] = 0.5
        with pytest.raises(ValidationError, match="sum to 1"):
            EventPlaybook.model_validate(data)

    def test_tied_expectation_rejected(self) -> None:
        data = playbook_data()
        data["scenarios"][0]["expected_probability"] = 0.49
        data["scenarios"][1]["expected_probability"] = 0.49
        with pytest.raises(ValidationError, match="ambiguous"):
            EventPlaybook.model_validate(data)

    def test_all_plans_required(self) -> None:
        data = playbook_data()
        del data["plans"]["HIKE"]
        with pytest.raises(ValidationError, match="plans must define"):
            EventPlaybook.model_validate(data)

    def test_naive_datetime_rejected(self) -> None:
        data = playbook_data()
        data["event"]["scheduled_at"] = datetime(2026, 10, 28, 18, 0)
        with pytest.raises(ValidationError, match="timezone-aware"):
            EventPlaybook.model_validate(data)

    def test_example_config_loads(self) -> None:
        books = load_playbooks(EXAMPLE_CONFIG)
        assert {b.event.kind for b in books} == {EventKind.FOMC, EventKind.NBP_RPP}
        for book in books:
            for plan in book.plans.values():
                assert all(s.stop_price is not None for s in plan.signals)


class TestDispatcher:
    def test_fires_matching_plan(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        decision = parse_fomc_statement(HOLD_TEXT, playbook.event.previous_rate)
        result = dispatcher.dispatch(playbook, decision, now=AFTER)
        assert not result.halted
        assert result.scenario == ScenarioName.HOLD
        assert result.surprise == SurpriseDirection.HAWKISH
        assert [b.entry.symbol for b in result.submitted] == ["TLT", "SPY"]
        assert all(b.entry.broker == "paper" for b in result.submitted)
        assert result.submitted[0].stop_price == Decimal("92")
        assert result.submitted[0].take_profit_price == Decimal("87")
        assert result.rejected == []

    def test_no_surprise_plan_does_nothing(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        decision = parse_fomc_statement(CUT_TEXT, playbook.event.previous_rate)
        result = dispatcher.dispatch(playbook, decision, now=AFTER)
        assert result.surprise == SurpriseDirection.NONE
        assert result.submitted == []

    def test_risk_rejections_kept_with_reason(self, limits: RiskLimits, stop_file: Path) -> None:
        data = playbook_data()
        data["plans"]["HOLD"]["legs"] = [
            leg("TLT", OrderSide.SELL, "50", "92", "87"),
            leg("SPY", OrderSide.SELL, "2", "690", "660", confidence=0.3),
            leg("IEF", OrderSide.SELL, "1", "100", "90"),
        ]
        book = EventPlaybook.model_validate(data)
        executor = PaperExecutor()
        disp = ScenarioDispatcher(RiskManager(limits), executor, KillSwitch(stop_file))
        result = disp.dispatch(book, parse_fomc_statement(HOLD_TEXT), now=AFTER)
        reasons = {r.signal.symbol: r.reason for r in result.rejected}
        assert "exceeds max" in reasons["TLT"]
        assert "confidence too low" in reasons["SPY"]
        assert [b.entry.symbol for b in result.submitted] == ["IEF"]
        assert len(executor.orders) == 1

    def test_daily_trade_limit_respected(self, stop_file: Path) -> None:
        limits = RiskLimits(
            max_position_size=Decimal("10"),
            max_daily_loss=Decimal("500"),
            max_drawdown_pct=20.0,
            max_trades_per_day=1,
            stop_loss_pct=2.0,
        )
        disp = ScenarioDispatcher(RiskManager(limits), PaperExecutor(), KillSwitch(stop_file))
        book = EventPlaybook.model_validate(playbook_data())
        result = disp.dispatch(book, parse_fomc_statement(HOLD_TEXT), now=AFTER)
        assert len(result.submitted) == 1
        assert "trade limit" in result.rejected[0].reason

    def test_refuses_before_event_time(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        result = dispatcher.dispatch(playbook, parse_fomc_statement(HOLD_TEXT), now=BEFORE)
        assert result.halted
        assert "stale" in result.halt_reason
        assert dispatcher.executor.orders == []

    def test_refuses_too_late(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        late = EVENT_TIME + timedelta(hours=2)
        result = dispatcher.dispatch(playbook, parse_fomc_statement(HOLD_TEXT), now=late)
        assert result.halted

    def test_refuses_wrong_bank(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        from hermes_trade.events import parse_nbp_communique

        nbp = parse_nbp_communique(
            "Rada postanowiła pozostawić stopy NBP bez zmian: stopa referencyjna 3,75%."
        )
        result = dispatcher.dispatch(playbook, nbp, now=AFTER)
        assert result.halted
        assert "NBP_RPP" in result.halt_reason

    def test_refuses_mismatched_previous_rate(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        decision = parse_fomc_statement(
            HOLD_TEXT.replace("3-1/2 to 3-3/4", "4 to 4-1/4"), Decimal("4.25")
        )
        result = dispatcher.dispatch(playbook, decision, now=AFTER)
        assert result.halted
        assert "previous rate" in result.halt_reason

    def test_dispatches_only_once(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        decision = parse_fomc_statement(HOLD_TEXT)
        dispatcher.dispatch(playbook, decision, now=AFTER)
        second = dispatcher.dispatch(playbook, decision, now=AFTER)
        assert second.halted
        assert len(dispatcher.executor.orders) == 2


class TestPrepositioned:
    def test_preposition_then_matching_outcome_keeps_it(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        pre = dispatcher.dispatch_prepositioned(playbook, now=BEFORE)
        assert [b.entry.symbol for b in pre.submitted] == ["TLT"]
        result = dispatcher.dispatch(playbook, parse_fomc_statement(CUT_TEXT), now=AFTER)
        assert result.unwound == []

    def test_wrong_outcome_unwinds_preposition(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        dispatcher.dispatch_prepositioned(playbook, now=BEFORE)
        result = dispatcher.dispatch(playbook, parse_fomc_statement(HOLD_TEXT), now=AFTER)
        assert len(result.unwound) == 1
        assert result.unwound[0].side == OrderSide.SELL
        assert result.unwound[0].quantity == Decimal("3")
        assert len(result.submitted) == 2

    def test_no_preposition_after_event(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        result = dispatcher.dispatch_prepositioned(playbook, now=AFTER)
        assert result.halted
        assert result.submitted == []

    def test_preposition_once(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook
    ) -> None:
        dispatcher.dispatch_prepositioned(playbook, now=BEFORE)
        assert dispatcher.dispatch_prepositioned(playbook, now=BEFORE).halted

    def test_missing_preposition_plan(self, dispatcher: ScenarioDispatcher) -> None:
        book = EventPlaybook.model_validate(playbook_data(prepositioned=None))
        assert dispatcher.dispatch_prepositioned(book, now=BEFORE).halted


class TestKillSwitch:
    def test_default_path(self) -> None:
        assert KillSwitch().path == Path("~/.hermes/trade/STOP").expanduser()

    def test_engaged_blocks_dispatch(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook, stop_file: Path
    ) -> None:
        stop_file.touch()
        result = dispatcher.dispatch(playbook, parse_fomc_statement(HOLD_TEXT), now=AFTER)
        assert result.halted
        assert "kill switch" in result.halt_reason
        assert result.submitted == []
        assert dispatcher.executor.orders == []

    def test_engaged_blocks_preposition(
        self, dispatcher: ScenarioDispatcher, playbook: EventPlaybook, stop_file: Path
    ) -> None:
        stop_file.touch()
        assert dispatcher.dispatch_prepositioned(playbook, now=BEFORE).halted
        assert dispatcher.executor.orders == []

    def test_disengaged_after_removal(self, stop_file: Path) -> None:
        ks = KillSwitch(stop_file)
        stop_file.touch()
        assert ks.is_engaged()
        stop_file.unlink()
        assert not ks.is_engaged()

    def test_paper_executor_direct(self) -> None:
        ex = PaperExecutor()
        sig = TradeSignal(
            symbol="SPY", side=OrderSide.BUY, quantity=Decimal("1"), confidence=0.9, reason="x"
        )
        order = ex.submit_market(sig)
        assert order.broker == "paper"
        assert ex.orders == [order]
