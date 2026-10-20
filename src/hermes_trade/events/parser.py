"""Fast-path (no LLM) parsers for central-bank rate decision statements.

Pure regex/string processing. Each parser extracts the decision verb and the
new rate from the *decision sentence only* (dissent sentences such as
"... who preferred to lower the target range ..." are ignored), then
classifies CUT / HOLD / HIKE against the previous rate. If the verb and the
rate change disagree, :class:`StatementParseError` is raised: when in doubt,
nothing is fired.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from hermes_trade.events.models import EventKind, ScenarioName


class StatementParseError(ValueError):
    """The statement could not be parsed unambiguously."""


@dataclass(frozen=True)
class ParsedDecision:
    """Outcome extracted from an official statement."""

    kind: EventKind
    scenario: ScenarioName
    new_rate: Decimal
    """FOMC: upper bound of the target range; NBP: reference rate."""
    previous_rate: Decimal | None
    range_low: Decimal | None
    change_bp: int | None
    evidence: str


_HYPHENS = re.compile("[‐‑‒–—―−]")
_UNICODE_FRACTIONS = {"¼": "-1/4", "½": "-1/2", "¾": "-3/4"}


def _normalize(text: str) -> str:
    """Lowercase, unify hyphens/whitespace, fold diacritics (ł -> l, ż -> z ...)."""
    text = _HYPHENS.sub("-", text)
    for frac, repl in _UNICODE_FRACTIONS.items():
        text = re.sub(rf"(\d)-?{frac}", rf"\1{repl}", text).replace(frac, repl[1:])
    text = text.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).strip().lower()
    # "4 1/4" -> "4-1/4"; "4 -1/4" -> "4-1/4"
    text = re.sub(r"(\d) ?- ?(\d/\d)", r"\1-\2", text)
    text = re.sub(r"(\d) (\d/\d)", r"\1-\2", text)
    return text


def _classify_change(new: Decimal, previous: Decimal) -> ScenarioName:
    if new < previous:
        return ScenarioName.CUT
    if new > previous:
        return ScenarioName.HIKE
    return ScenarioName.HOLD


def _resolve(
    kind: EventKind,
    verb_scenario: ScenarioName,
    new_rate: Decimal,
    previous_rate: Decimal | None,
    range_low: Decimal | None,
    evidence: str,
) -> ParsedDecision:
    change_bp: int | None = None
    if previous_rate is not None:
        rate_scenario = _classify_change(new_rate, previous_rate)
        if rate_scenario != verb_scenario:
            raise StatementParseError(
                f"verb says {verb_scenario} but rate {previous_rate} -> {new_rate} "
                f"says {rate_scenario}; refusing to classify"
            )
        change_bp = int((new_rate - previous_rate) * 100)
    return ParsedDecision(
        kind=kind,
        scenario=verb_scenario,
        new_rate=new_rate,
        previous_rate=previous_rate,
        range_low=range_low,
        change_bp=change_bp,
        evidence=evidence,
    )


# --------------------------------------------------------------------------- Fed

_FED_NUM = r"\d+-\d/\d|\d/\d|\d+(?:\.\d+)?"
_FED_DECISION = re.compile(
    r"committee decided to (?P<verb>lower|reduce|cut|maintain|keep|leave|raise|increase)"
    r" the target range for the federal funds rate"
    r"(?: by (?P<by>[^,;]*?) (?:percentage points?|basis points?))?"
    rf" (?:at|to) (?P<low>{_FED_NUM}) to (?P<high>{_FED_NUM}) percent"
)
_FED_VERBS: dict[str, ScenarioName] = {
    "lower": ScenarioName.CUT,
    "reduce": ScenarioName.CUT,
    "cut": ScenarioName.CUT,
    "maintain": ScenarioName.HOLD,
    "keep": ScenarioName.HOLD,
    "leave": ScenarioName.HOLD,
    "raise": ScenarioName.HIKE,
    "increase": ScenarioName.HIKE,
}


def parse_fed_number(token: str) -> Decimal:
    """Parse Fed notation such as ``4``, ``1/4``, ``4-3/4`` or ``4.25`` into a Decimal."""
    token = token.strip()
    m = re.fullmatch(r"(\d+)-(\d)/(\d)", token)
    if m:
        whole, num, den = (int(g) for g in m.groups())
        return Decimal(whole) + Decimal(num) / Decimal(den)
    m = re.fullmatch(r"(\d)/(\d)", token)
    if m:
        return Decimal(int(m.group(1))) / Decimal(int(m.group(2)))
    try:
        return Decimal(token)
    except InvalidOperation as exc:
        raise StatementParseError(f"unrecognised Fed number {token!r}") from exc


def parse_fomc_statement(text: str, previous_upper: Decimal | None = None) -> ParsedDecision:
    """Parse an FOMC statement (federalreserve.gov) into a decision.

    Args:
        text: Statement text (HTML already stripped).
        previous_upper: Upper bound of the target range before the meeting.
    """
    norm = _normalize(text)
    matches = list(_FED_DECISION.finditer(norm))
    if not matches:
        raise StatementParseError("no FOMC decision sentence found")
    if len({(m.group("verb"), m.group("low"), m.group("high")) for m in matches}) > 1:
        raise StatementParseError("multiple conflicting FOMC decision sentences")
    m = matches[0]
    low = parse_fed_number(m.group("low"))
    high = parse_fed_number(m.group("high"))
    if not low < high:
        raise StatementParseError(f"invalid target range {low} to {high}")
    return _resolve(
        EventKind.FOMC, _FED_VERBS[m.group("verb")], high, previous_upper, low, m.group(0)
    )


# --------------------------------------------------------------------------- NBP

_NBP_DECISION = re.compile(
    r"(?:rada|rpp)\b[^.]{0,60}?postanowil\w*\s+"
    r"(?P<verb>obnizyc|pozostawic|utrzymac|podwyzszyc|podniesc)"
    r"(?P<tail>[^:;]{0,120})"
)
_NBP_REFERENCE = re.compile(
    r"stopa referencyjna(?: nbp)?(?: w wysokosci| na poziomie| wynosi)?:? ?"
    r"(?P<rate>\d+(?:[.,]\d+)?) ?%"
)
_NBP_VERBS: dict[str, ScenarioName] = {
    "obnizyc": ScenarioName.CUT,
    "pozostawic": ScenarioName.HOLD,
    "utrzymac": ScenarioName.HOLD,
    "podwyzszyc": ScenarioName.HIKE,
    "podniesc": ScenarioName.HIKE,
}


def parse_nbp_communique(text: str, previous_reference: Decimal | None = None) -> ParsedDecision:
    """Parse an NBP "Komunikat po posiedzeniu RPP" into a decision.

    Args:
        text: Communiqué text in Polish (diacritics optional).
        previous_reference: NBP reference rate before the meeting.
    """
    norm = _normalize(text)
    m = _NBP_DECISION.search(norm)
    if m is None:
        raise StatementParseError("no RPP decision sentence found")
    verb = m.group("verb")
    scenario = _NBP_VERBS[verb]
    if "stop" not in m.group("tail"):
        raise StatementParseError("RPP decision sentence does not refer to interest rates")
    if scenario == ScenarioName.HOLD and not re.search(r"bez zmian|niezmienion", m.group("tail")):
        raise StatementParseError("RPP 'pozostawic' without 'bez zmian'; ambiguous")
    ref = _NBP_REFERENCE.search(norm, m.end())
    if ref is None:
        raise StatementParseError("no reference rate found after the RPP decision")
    rate = Decimal(ref.group("rate").replace(",", "."))
    evidence = norm[m.start() : ref.end()]
    return _resolve(EventKind.NBP_RPP, scenario, rate, previous_reference, None, evidence)


def parse_statement(
    kind: EventKind, text: str, previous_rate: Decimal | None = None
) -> ParsedDecision:
    """Dispatch to the parser for ``kind``."""
    if kind == EventKind.FOMC:
        return parse_fomc_statement(text, previous_rate)
    return parse_nbp_communique(text, previous_rate)
