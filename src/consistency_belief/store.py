"""Append-only ledger for consistency-belief: evidence, events, and decisions.

Stored in .consistency/ as plain JSONL. Immutable trial records,
where amendments fold over trials rather than editing them in-place.
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

STORE_DIR = ".consistency"
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

    # ---------- evidence / trials ----------

    def raw_records(self) -> list[dict[str, Any]]:
        return list(self._read(self.evidence_path))

    def next_trial_id(self) -> str:
        n = sum(1 for r in self.raw_records() if r.get("kind") == "trial")
        return sequential_id("TRL", n + 1)

    def append_trial(self, record: dict[str, Any]) -> str:
        rec = dict(record)
        rec["kind"] = "trial"
        rec.setdefault("id", self.next_trial_id())
        rec.setdefault("timestamp", utc_now())
        rec.setdefault("validity", "valid")
        self._append(self.evidence_path, rec)
        return rec["id"]

    def append_amendment(
        self,
        target: str,
        *,
        validity: str | None = None,
        reason: str = "",
        actor: str = "agent",
    ) -> dict[str, Any]:
        record = {
            "kind": "amendment",
            "target": target,
            "validity": validity,
            "reason": reason,
            "actor": actor,
            "timestamp": utc_now(),
        }
        self._append(self.evidence_path, record)
        return record

    def effective_trials(self) -> list[dict[str, Any]]:
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
        return list(trials.values())

    # ---------- notes ----------

    def append_note(self, subject: str, text: str, actor: str = "agent") -> dict[str, Any]:
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
            "session": os.environ.get("CONSISTENCY_SESSION", ""),
            "tool": tool,
            "payload": payload,
        })

    def events(self) -> list[dict[str, Any]]:
        return list(self._read(self.events_path))

    def staged_proposals(self) -> list[dict[str, Any]]:
        """Every branch proposed through propose_branch and not since withdrawn, latest proposal
        per id, in the order the ids were first proposed. They persist here until a declaration
        at git HEAD with the same id takes their place, or until withdraw retires one."""
        proposals: dict[str, dict[str, Any]] = {}
        for event in self.events():
            payload = event.get("payload", {})
            node_id = payload.get("id")
            if not node_id:
                continue
            if event.get("tool") == "propose_branch":
                proposals[node_id] = payload          # re-proposing revives a withdrawn id
            elif event.get("tool") == "withdraw":
                proposals.pop(node_id, None)
        return list(proposals.values())

    def withdrawn(self) -> dict[str, str]:
        """Staged proposals retired by withdraw, with the reason -- the event stays in the ledger,
        and so do the trials recorded against it."""
        out: dict[str, str] = {}
        for event in self.events():
            payload = event.get("payload", {})
            node_id = payload.get("id")
            if not node_id:
                continue
            if event.get("tool") == "withdraw":
                out[node_id] = payload.get("reason", "")
            elif event.get("tool") == "propose_branch":
                out.pop(node_id, None)
        return out

    # ---------- decisions ----------

    def append_decision(self, record: dict[str, Any]) -> dict[str, Any]:
        rec = dict(record)
        rec.setdefault("timestamp", utc_now())
        rec.setdefault("id", sequential_id("DEC", len(self.decisions()) + 1))
        self._append(self.decisions_path, rec)
        return rec

    def decisions(self) -> list[dict[str, Any]]:
        return list(self._read(self.decisions_path))
