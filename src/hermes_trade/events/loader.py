"""Load event playbooks from YAML (see ``config/events.example.yaml``)."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from hermes_trade.events.models import EventPlaybook


def load_playbooks(path: Path | str) -> list[EventPlaybook]:
    """Parse and validate all playbooks in a YAML file with a ``playbooks`` list."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [EventPlaybook.model_validate(item) for item in data.get("playbooks", [])]
