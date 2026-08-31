"""Append-only evidence, event, and decision log.

Nothing here mutates a record. A correction appends an *amendment* that later
folds over the original (3.3), so the ledger read back at any point still
contains the trial as first recorded and the reason it was reclassified.

Plain JSONL on purpose: reviewable with `git diff`, and the belief cache is
always regenerable from it (4.6, 10.2).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .ids import sequential_id

STORE_DIR = ".belief"
VALIDITY = ("valid", "invalid", "quarantined", "superseded")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Store:
    root: Path

    @property
    def dir(self) -> Path:
        return self.root / STORE_DIR

    @property
    def evidence_path(self) -> Path:
        return self.dir / "evidence.jsonl"

    @property
    def events_path(self) -> Path:
        return self.dir / "events.jsonl"

    @property
    def decisions_path(self) -> Path:
        return self.dir / "decisions.jsonl"

    @property
    def artifacts_dir(self) -> Path:
        return self.dir / "artifacts"

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "cache").mkdir(parents=True, exist_ok=True)

    # ---------- raw io ----------

    def _read(self, path: Path) -> Iterator[dict[str, Any]]:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        self.ensure()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    # ---------- evidence ----------

    def raw_records(self) -> list[dict[str, Any]]:
        return list(self._read(self.evidence_path))

    def next_evidence_id(self) -> str:
        n = sum(1 for r in self.raw_records() if r.get("kind") == "trial")
        return sequential_id("EV", n + 1)

    def append_trial(self, record: dict[str, Any]) -> str:
        record = dict(record)
        record["kind"] = "trial"
        record.setdefault("id", self.next_evidence_id())
        record.setdefault("timestamp", utc_now())
        record.setdefault("validity", "valid")
        self._append(self.evidence_path, record)
        return record["id"]

    def append_trials(self, records: list[dict[str, Any]]) -> list[str]:
        """Allocate ids in one pass — one re-scan of the ledger, not N."""
        n = sum(1 for r in self.raw_records() if r.get("kind") == "trial")
        ids: list[str] = []
        for offset, record in enumerate(records, start=1):
            record = dict(record)
            record["kind"] = "trial"
            record["id"] = sequential_id("EV", n + offset)
            record.setdefault("timestamp", utc_now())
            record.setdefault("validity", "valid")
            self._append(self.evidence_path, record)
            ids.append(record["id"])
        return ids

    def append_amendment(
        self,
        target: str,
        *,
        validity: str | None = None,
        supersede_with: str | None = None,
        reason: str = "",
        actor: str = "agent",
    ) -> dict[str, Any]:
        record = {
            "kind": "amendment",
            "target": target,
            "validity": validity,
            "supersede_with": supersede_with,
            "reason": reason,
            "actor": actor,
            "timestamp": utc_now(),
        }
        self._append(self.evidence_path, record)
        return record

    def effective_trials(self) -> list[dict[str, Any]]:
        """Trials with amendments folded in — the view every belief reads."""
        trials: dict[str, dict[str, Any]] = {}
        amendments: list[dict[str, Any]] = []
        for record in self.raw_records():
            if record.get("kind") == "trial":
                trials[record["id"]] = dict(record)
            elif record.get("kind") == "amendment":
                amendments.append(record)

        for amendment in amendments:
            target = trials.get(amendment.get("target", ""))
            if target is None:
                continue
            if amendment.get("validity"):
                target["validity"] = amendment["validity"]
                target["validity_reason"] = amendment.get("reason", "")
            if amendment.get("supersede_with"):
                target["validity"] = "superseded"
                target["superseded_by"] = amendment["supersede_with"]
                target["validity_reason"] = amendment.get("reason", "")
        return list(trials.values())

    # ---------- notes (the inert channel) ----------

    def append_note(self, subject: str, text: str, actor: str = "agent") -> dict[str, Any]:
        """An annotation is not evidence. It is stored beside evidence so it
        shows up in reports, and it carries provenance=asserted so no belief
        model can ever read it (4.5, 10.4)."""
        record = {
            "kind": "note",
            "subject": subject,
            "text": text,
            "provenance": "asserted",
            "actor": actor,
            "timestamp": utc_now(),
        }
        self._append(self.evidence_path, record)
        return record

    def notes(self, subject: str | None = None) -> list[dict[str, Any]]:
        out = [r for r in self.raw_records() if r.get("kind") == "note"]
        return [r for r in out if subject is None or r.get("subject") == subject]

    # ---------- events ----------

    def append_event(self, tool: str, payload: dict[str, Any], actor: str = "agent") -> None:
        self._append(self.events_path, {
            "timestamp": utc_now(),
            "actor": actor,
            "session": os.environ.get("BELIEF_SESSION", ""),
            "tool": tool,
            "payload": payload,
        })

    def events(self) -> list[dict[str, Any]]:
        return list(self._read(self.events_path))

    # ---------- decisions ----------

    def append_decision(self, record: dict[str, Any]) -> dict[str, Any]:
        record = dict(record)
        record.setdefault("timestamp", utc_now())
        record.setdefault("id", sequential_id("DEC", len(self.decisions()) + 1))
        self._append(self.decisions_path, record)
        return record

    def decisions(self) -> list[dict[str, Any]]:
        return list(self._read(self.decisions_path))

    # ---------- runs ----------

    def next_run_id(self) -> str:
        seen = {r.get("run_id") for r in self.raw_records()}
        seen |= {e.get("payload", {}).get("run_id") for e in self.events()}
        highest = 0
        for value in seen:
            if isinstance(value, str):
                match = re.fullmatch(r"RUN-(\d+)", value)
                if match:
                    highest = max(highest, int(match.group(1)))
        return sequential_id("RUN", highest + 1)

    def artifact_dir(self, run_id: str) -> Path:
        path = self.artifacts_dir / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path
