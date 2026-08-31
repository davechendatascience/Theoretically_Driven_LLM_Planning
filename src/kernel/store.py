"""Append-only JSON store. Plain files, human-diffable, git-friendly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel

from .models import Change, Constraint, Expectation, FailureMode, Given, Goal, Intent, Objective, Outcome

T = TypeVar("T", bound=BaseModel)

_COLLECTIONS: dict[str, type[BaseModel]] = {
    "objectives": Objective, "goals": Goal, "constraints": Constraint,
    "givens": Given, "failure_modes": FailureMode, "changes": Change,
    "expectations": Expectation, "intents": Intent, "outcomes": Outcome,
}


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def load(self, name: str) -> list[Any]:
        cls = _COLLECTIONS[name]
        p = self._path(name)
        if not p.exists():
            return []
        return [cls.model_validate(r) for r in json.loads(p.read_text())]

    def save(self, name: str, items: Iterable[BaseModel]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(name).write_text(
            json.dumps([i.model_dump(mode="json") for i in items], indent=2) + "\n"
        )

    def append_event(self, event: str, subject: str, data: dict[str, Any] | None = None) -> int:
        """Strictly increasing seq; a rewrite shows as a break under I4."""
        self.root.mkdir(parents=True, exist_ok=True)
        log = self.root / "events.jsonl"
        seq = sum(1 for _ in log.open()) + 1 if log.exists() else 1
        with log.open("a") as fh:
            fh.write(json.dumps({"seq": seq, "event": event, "subject": subject, "data": data or {}}) + "\n")
        return seq

    def event_seqs(self) -> list[int]:
        log = self.root / "events.jsonl"
        if not log.exists():
            return []
        return [json.loads(line)["seq"] for line in log.open() if line.strip()]
