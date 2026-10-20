"""Parser accuracy evaluation on historical statements.

Usage::

    python -m hermes_trade.events.evaluation tests/fixtures/central_bank_statements.yaml
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from hermes_trade.events.models import EventKind, ScenarioName
from hermes_trade.events.parser import StatementParseError, parse_statement


@dataclass(frozen=True)
class HistoricalCase:
    """One historical statement with its known outcome."""

    label: str
    kind: EventKind
    text: str
    expected: ScenarioName
    previous_rate: Decimal | None = None
    expected_rate: Decimal | None = None


@dataclass(frozen=True)
class CaseResult:
    case: HistoricalCase
    predicted: ScenarioName | None
    rate: Decimal | None
    error: str = ""

    @property
    def correct(self) -> bool:
        if self.predicted != self.case.expected:
            return False
        return self.case.expected_rate is None or self.rate == self.case.expected_rate


@dataclass
class EvalReport:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(r.correct for r in self.results)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def failures(self) -> list[CaseResult]:
        return [r for r in self.results if not r.correct]

    def by_kind(self) -> dict[EventKind, tuple[int, int]]:
        """(correct, total) per event kind."""
        out: dict[EventKind, tuple[int, int]] = {}
        for r in self.results:
            c, t = out.get(r.case.kind, (0, 0))
            out[r.case.kind] = (c + int(r.correct), t + 1)
        return out

    def summary(self) -> str:
        lines = [f"overall: {self.correct}/{self.total} ({self.accuracy:.0%})"]
        for kind, (c, t) in sorted(self.by_kind().items()):
            lines.append(f"{kind}: {c}/{t}")
        for f in self.failures:
            lines.append(
                f"FAIL {f.case.label}: expected {f.case.expected} "
                f"{f.case.expected_rate}, got {f.predicted} {f.rate} {f.error}"
            )
        return "\n".join(lines)


def evaluate(cases: list[HistoricalCase]) -> EvalReport:
    """Run the fast-path parser on every case and collect results."""
    report = EvalReport()
    for case in cases:
        try:
            parsed = parse_statement(case.kind, case.text, case.previous_rate)
        except StatementParseError as exc:
            report.results.append(CaseResult(case, None, None, str(exc)))
            continue
        report.results.append(CaseResult(case, parsed.scenario, parsed.new_rate))
    return report


def _opt_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def load_cases(path: Path | str) -> list[HistoricalCase]:
    """Load historical cases from a YAML file with a top-level ``cases`` list."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [
        HistoricalCase(
            label=str(item["label"]),
            kind=EventKind(item["kind"]),
            text=str(item["text"]),
            expected=ScenarioName(item["expected"]),
            previous_rate=_opt_decimal(item.get("previous_rate")),
            expected_rate=_opt_decimal(item.get("expected_rate")),
        )
        for item in data["cases"]
    ]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m hermes_trade.events.evaluation CASES.yaml")
        return 2
    report = evaluate(load_cases(args[0]))
    print(report.summary())
    return 0 if not report.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
