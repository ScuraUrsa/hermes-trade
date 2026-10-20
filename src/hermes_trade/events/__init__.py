"""Scheduled-event scenario machine (PAPER ONLY).

Prepare CUT / HOLD / HIKE plans before a central-bank decision, parse the
official statement with a fast regex path, and fire the matching plan through
the RiskManager into a paper executor. See ``docs/events.md``.
"""

from hermes_trade.events.dispatcher import (
    DEFAULT_KILL_SWITCH_PATH,
    DispatchResult,
    KillSwitch,
    PaperBracket,
    PaperExecutor,
    Rejection,
    ScenarioDispatcher,
)
from hermes_trade.events.loader import load_playbooks
from hermes_trade.events.models import (
    BracketLeg,
    EventKind,
    EventPlaybook,
    PrepositionedPlan,
    Scenario,
    ScenarioName,
    ScenarioPlan,
    ScheduledEvent,
    SurpriseDirection,
    classify_surprise,
    surprise_steps,
)
from hermes_trade.events.parser import (
    ParsedDecision,
    StatementParseError,
    parse_fomc_statement,
    parse_nbp_communique,
    parse_statement,
)

__all__ = [
    "DEFAULT_KILL_SWITCH_PATH",
    "BracketLeg",
    "DispatchResult",
    "EventKind",
    "EventPlaybook",
    "KillSwitch",
    "PaperBracket",
    "PaperExecutor",
    "ParsedDecision",
    "PrepositionedPlan",
    "Rejection",
    "Scenario",
    "ScenarioDispatcher",
    "ScenarioName",
    "ScenarioPlan",
    "ScheduledEvent",
    "StatementParseError",
    "SurpriseDirection",
    "classify_surprise",
    "load_playbooks",
    "parse_fomc_statement",
    "parse_nbp_communique",
    "parse_statement",
    "surprise_steps",
]
