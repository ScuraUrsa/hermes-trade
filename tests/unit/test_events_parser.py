"""Tests for the fast-path central-bank statement parsers and the evaluator."""

from decimal import Decimal
from pathlib import Path

import pytest

from hermes_trade.events import (
    EventKind,
    ScenarioName,
    StatementParseError,
    parse_fomc_statement,
    parse_nbp_communique,
    parse_statement,
)
from hermes_trade.events.evaluation import evaluate, load_cases, main
from hermes_trade.events.parser import parse_fed_number

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "central_bank_statements.yaml"


class TestFedNumbers:
    @pytest.mark.parametrize(
        ("token", "value"),
        [
            ("4", "4"),
            ("1/4", "0.25"),
            ("4-1/4", "4.25"),
            ("4-3/4", "4.75"),
            ("5-1/2", "5.5"),
            ("0", "0"),
            ("4.25", "4.25"),
        ],
    )
    def test_parses(self, token: str, value: str) -> None:
        assert parse_fed_number(token) == Decimal(value)

    def test_rejects_garbage(self) -> None:
        with pytest.raises(StatementParseError):
            parse_fed_number("four")


class TestFomcParser:
    def test_cut(self) -> None:
        text = (
            "the Committee decided to lower the target range for the federal funds rate "
            "by 1/4 percentage point to 4 to 4-1/4 percent."
        )
        d = parse_fomc_statement(text, Decimal("4.50"))
        assert d.scenario == ScenarioName.CUT
        assert d.new_rate == Decimal("4.25")
        assert d.range_low == Decimal("4")
        assert d.change_bp == -25

    def test_hold(self) -> None:
        text = (
            "the Committee decided to maintain the target range for the federal funds "
            "rate at 5-1/4 to 5-1/2 percent."
        )
        d = parse_fomc_statement(text, Decimal("5.50"))
        assert d.scenario == ScenarioName.HOLD
        assert d.change_bp == 0

    def test_hike(self) -> None:
        text = (
            "the Committee decided to raise the target range for the federal funds rate "
            "to 5-1/4 to 5-1/2 percent."
        )
        assert parse_fomc_statement(text, Decimal("5.25")).scenario == ScenarioName.HIKE

    def test_unicode_hyphens_fractions_and_line_breaks(self) -> None:
        text = (
            "the Committee\ndecided to lower the target range for the federal funds rate "
            "by 1/4 percentage point to 4¼ to 4‑½\npercent."
        )
        d = parse_fomc_statement(text, Decimal("4.75"))
        assert d.new_rate == Decimal("4.5")
        assert d.range_low == Decimal("4.25")

    def test_ignores_dissent_sentence(self) -> None:
        text = (
            "the Committee decided to maintain the target range for the federal funds rate "
            "at 4-1/4 to 4-1/2 percent. Voting against were A and B, who preferred to lower "
            "the target range for the federal funds rate by 1/4 percentage point."
        )
        assert parse_fomc_statement(text, Decimal("4.50")).scenario == ScenarioName.HOLD

    def test_without_previous_rate_uses_verb(self) -> None:
        text = (
            "the Committee decided to raise the target range for the federal funds rate "
            "to 1/4 to 1/2 percent."
        )
        d = parse_fomc_statement(text)
        assert d.scenario == ScenarioName.HIKE
        assert d.change_bp is None

    def test_inconsistent_verb_and_rate_raises(self) -> None:
        text = (
            "the Committee decided to lower the target range for the federal funds rate "
            "to 4 to 4-1/4 percent."
        )
        with pytest.raises(StatementParseError, match="refusing"):
            parse_fomc_statement(text, Decimal("4.00"))

    def test_no_decision_sentence_raises(self) -> None:
        with pytest.raises(StatementParseError):
            parse_fomc_statement("Recent indicators suggest that growth has moderated.")

    def test_dissent_only_is_not_a_decision(self) -> None:
        text = "B preferred to lower the target range for the federal funds rate by 1/4 point."
        with pytest.raises(StatementParseError):
            parse_fomc_statement(text)


class TestNbpParser:
    def test_cut(self) -> None:
        text = (
            "Rada postanowiła obniżyć stopy procentowe NBP o 0,25 pkt proc., ustalając je "
            "na poziomie: stopa referencyjna 5,75% w skali rocznej; stopa lombardowa 6,25%."
        )
        d = parse_nbp_communique(text, Decimal("6.00"))
        assert d.scenario == ScenarioName.CUT
        assert d.new_rate == Decimal("5.75")
        assert d.change_bp == -25

    def test_hold(self) -> None:
        text = (
            "Rada postanowiła pozostawić stopy procentowe NBP bez zmian: "
            "stopa referencyjna 5,75% w skali rocznej."
        )
        assert parse_nbp_communique(text, Decimal("5.75")).scenario == ScenarioName.HOLD

    def test_hike_with_full_council_name_and_nbsp(self) -> None:
        text = (
            "Rada Polityki Pieniężnej postanowiła podwyższyć stopy procentowe NBP o 0,25 "
            "pkt proc., ustalając je na poziomie: stopa referencyjna 6,75 % w skali rocznej."
        )
        d = parse_nbp_communique(text, Decimal("6.50"))
        assert d.scenario == ScenarioName.HIKE
        assert d.new_rate == Decimal("6.75")

    def test_skips_lombard_and_deposit_rates(self) -> None:
        text = (
            "Rada postanowiła obniżyć stopy procentowe NBP: stopa lombardowa 4,50%; "
            "stopa depozytowa 3,50%; stopa referencyjna 4,00% w skali rocznej."
        )
        assert parse_nbp_communique(text, Decimal("4.25")).new_rate == Decimal("4.00")

    def test_pozostawic_without_bez_zmian_raises(self) -> None:
        text = "Rada postanowiła pozostawić stopy procentowe NBP: stopa referencyjna 5,75%."
        with pytest.raises(StatementParseError):
            parse_nbp_communique(text)

    def test_inconsistent_raises(self) -> None:
        text = (
            "Rada postanowiła podwyższyć stopy procentowe NBP, ustalając je na poziomie: "
            "stopa referencyjna 5,00%."
        )
        with pytest.raises(StatementParseError):
            parse_nbp_communique(text, Decimal("5.25"))

    def test_missing_reference_rate_raises(self) -> None:
        with pytest.raises(StatementParseError):
            parse_nbp_communique("Rada postanowiła obniżyć stopy procentowe NBP o 0,25 pkt proc.")

    def test_unrelated_text_raises(self) -> None:
        with pytest.raises(StatementParseError):
            parse_nbp_communique("Inflacja w Polsce obniżyła się w ostatnich miesiącach.")


class TestDispatchByKind:
    def test_parse_statement_routes(self) -> None:
        text = "Rada postanowiła pozostawić stopy NBP bez zmian: stopa referencyjna 5,75%."
        assert parse_statement(EventKind.NBP_RPP, text).kind == EventKind.NBP_RPP


class TestHistoricalAccuracy:
    def test_fixture_counts(self) -> None:
        cases = load_cases(FIXTURES)
        fed = [c for c in cases if c.kind == EventKind.FOMC]
        nbp = [c for c in cases if c.kind == EventKind.NBP_RPP]
        assert len(fed) >= 6
        assert len(nbp) >= 6
        assert {c.expected for c in fed} == set(ScenarioName)
        assert {c.expected for c in nbp} == set(ScenarioName)

    def test_full_accuracy_on_fixtures(self) -> None:
        report = evaluate(load_cases(FIXTURES))
        assert report.failures == [], report.summary()
        assert report.accuracy == 1.0

    def test_report_counts_parse_errors_as_failures(self) -> None:
        cases = load_cases(FIXTURES)[:1]
        broken = [type(cases[0])(**{**cases[0].__dict__, "text": "nothing here"})]
        report = evaluate(broken)
        assert report.accuracy == 0.0
        assert "FAIL" in report.summary()

    def test_cli(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([str(FIXTURES)]) == 0
        assert "overall" in capsys.readouterr().out
