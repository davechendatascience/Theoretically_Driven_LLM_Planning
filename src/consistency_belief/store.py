"""Append-only ledger for consistency-belief: evidence, events, and decisions.

Stored in .consistency/ as plain JSONL. Immutable trial records,
where amendments fold over trials rather than editing them in-place.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .ids import sequential_id

STORE_DIR = ".consistency"
#: Reviews of code links and cited measurements (DEF-review) live in a file of their own, meant
#: to be tracked even where a repository keeps its event ledgers local: which code realizes which
#: claim, and who read it at which commit, travels with the code. One JSON object per line.
REVIEWS_FILE = "reviews.yaml"
_REVIEWS_HEADER = (
    "# Reviews of code links and cited measurements (DEF-review): appended by review(), never edited.\n"
    "# Track this file in git -- it is what makes a review travel with the code. One review a line.\n")
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

    # ---------- Lean certificates ----------

    def append_certificate(self, record: dict[str, Any]) -> str:
        """Keep a Lean certificate whole, beside the trials (DEF-lean-certificate): the evidence
        travels with the ledger, and no later read runs Lean again."""
        n = sum(1 for r in self.raw_records() if r.get("kind") == "certificate")
        rec = {**record, "kind": "certificate", "id": sequential_id("CRT", n + 1), "timestamp": utc_now()}
        self._append(self.evidence_path, rec)
        return rec["id"]

    def certificates(self) -> list[dict[str, Any]]:
        """Every certificate record, oldest first."""
        return [r for r in self.raw_records() if r.get("kind") == "certificate"]

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

    def staged_proposals(self, until: str | None = None) -> list[dict[str, Any]]:
        """Every branch proposed through propose_branch and not since withdrawn, latest proposal
        per id, in the order the ids were first proposed. They persist here until a declaration
        at git HEAD with the same id takes their place, or until withdraw retires one.

        `until` (an ISO timestamp) gives the proposals as they stood at that moment instead."""
        proposals: dict[str, dict[str, Any]] = {}
        for event in self.events():
            if until is not None and str(event.get("timestamp") or "") > until:
                continue
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

    # ---------- reviews ----------

    @property
    def reviews_path(self) -> Path:
        return self.dir / REVIEWS_FILE

    def _events_reviews(self) -> list[dict[str, Any]]:
        """Reviews 0.8.0 recorded as events in events.jsonl, before they had a file of their own."""
        return [{**e.get("payload", {}), "actor": e.get("actor", ""), "timestamp": e.get("timestamp", "")}
                for e in self.events() if e.get("tool") == "review"]

    def _file_reviews(self) -> list[dict[str, Any]]:
        if not self.reviews_path.exists():
            return []
        out = []
        for line in self.reviews_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("- {"):
                try:
                    out.append(json.loads(line[2:]))
                except json.JSONDecodeError:
                    continue
        return out

    def append_review(self, payload: dict[str, Any], actor: str = "agent") -> dict[str, Any]:
        """Record that `actor` read a code link or a cited measurement at one commit (DEF-review):
        appended, never edited; the latest one for a link wins. The first review written to the
        reviews file carries over those recorded in events.jsonl before it existed."""
        self.ensure()
        if not self.reviews_path.exists():
            carried = [{**r, "carried_from": "events.jsonl"} for r in self._events_reviews()]
            self.reviews_path.write_text(_REVIEWS_HEADER + "".join(
                "- " + json.dumps(r, sort_keys=True) + "\n" for r in carried), encoding="utf-8")
        rec = {**payload, "id": sequential_id("REV", len(self.reviews()) + 1), "actor": actor,
               "timestamp": utc_now()}
        with self.reviews_path.open("a", encoding="utf-8") as f:
            f.write("- " + json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def reviews(self) -> list[dict[str, Any]]:
        """Every review, oldest first: those in events.jsonl not yet carried into the reviews file,
        then the file's."""
        filed = self._file_reviews()
        ids = {r.get("id") for r in filed}
        return [r for r in self._events_reviews() if r.get("id") not in ids] + filed

    def reviews_ignored(self) -> str | None:
        """The .gitignore rule that keeps the reviews file out of git, or None when git would
        track it (or there is no git to ask)."""
        try:
            out = subprocess.run(["git", "check-ignore", "-v", "--no-index", f"{STORE_DIR}/{REVIEWS_FILE}"],
                                 cwd=self.root, capture_output=True, text=True, timeout=30,
                                 stdin=subprocess.DEVNULL, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0 or not out.stdout.strip():
            return None
        source = out.stdout.split("\t", 1)[0]
        return None if source.split(":")[-1].startswith("!") else source

    def reviews_where(self) -> str:
        """Where reviews are kept, and what to do so they travel with the code."""
        rule = self.reviews_ignored()
        where = f"{STORE_DIR}/{REVIEWS_FILE}"
        if rule:
            return (f"{where} is ignored by git ({rule}), so reviews stay on this machine: add the line "
                    f"`!{where}` to .gitignore (and un-ignore {STORE_DIR}/ if a rule ignores the "
                    "directory), then commit it")
        return f"commit {where} with your change: reviews travel with the code"

    def link_reviews(self) -> dict[tuple[str, str], dict[str, Any]]:
        """The latest review of each code link, by (region id, node id)."""
        return {(r.get("region"), r.get("target")): r for r in self.reviews() if r.get("kind") == "link"}

    def measurement_reviews(self) -> dict[tuple[str, str], dict[str, Any]]:
        """The latest review of each cited measurement, by (branch id, contract id)."""
        return {(r.get("branch"), r.get("contract")): r for r in self.reviews() if r.get("kind") == "measurement"}

    # ---------- decisions ----------

    def append_decision(self, record: dict[str, Any]) -> dict[str, Any]:
        rec = dict(record)
        rec.setdefault("timestamp", utc_now())
        rec.setdefault("id", sequential_id("DEC", len(self.decisions()) + 1))
        self._append(self.decisions_path, rec)
        return rec

    def decisions(self) -> list[dict[str, Any]]:
        return list(self._read(self.decisions_path))
