"""Append-only evidence, event, and decision log.

Nothing here mutates a record. A correction appends an *amendment* that later
folds over the original (3.3), so the ledger read back at any point still
contains the trial as first recorded and the reason it was reclassified.

Plain JSONL on purpose: reviewable with `git diff`, and the belief cache is
always regenerable from it (4.6, 10.2).
"""

from __future__ import annotations

import json
import threading
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .ids import sequential_id
from .ledger_index import apply_amendment, enabled as index_enabled, index_for, no_id, read_records

#: One writer at a time. Ids are taken from the ledger as it stands, so a run that appends while
#: another counts would hand out the same EV- id twice. Runs execute in parallel; only taking an id
#: and appending hold this. Within a process the lock is this RLock; across processes -- a test run
#: in the background, recording when it ends while the server records another, or two sessions on
#: one project -- it is also a lock on a file in the ledger's cache, taken by the outermost holder.
_LEDGER = threading.RLock()
_HELD = threading.local()


def _lock(fh: Any) -> None:
    if os.name == "nt":
        import msvcrt
        import time
        while True:
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:            # LK_LOCK gives up after ten tries; keep waiting
                time.sleep(0.05)
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _unlock(fh: Any) -> None:
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def ledger_lock(directory: Path) -> Iterator[None]:
    """Hold the ledger in `directory` against every other writer, in this process or another."""
    with _LEDGER:
        depth = getattr(_HELD, "depth", 0)
        if depth:
            _HELD.depth = depth + 1
            try:
                yield
            finally:
                _HELD.depth = depth
            return
        path = directory / "cache" / "ledger.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as fh:
            _lock(fh)
            _HELD.depth = 1
            try:
                yield
            finally:
                _HELD.depth = 0
                _unlock(fh)

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
        """Every record, line by line: the one reading the evidence index shares, so the two never
        disagree on what a line holds (ledger_index.read_records)."""
        for _, record, _ in read_records(path):
            yield record

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True, default=str) + "\n"
        with ledger_lock(self.dir):
            self.ensure()
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    # ---------- evidence ----------

    def raw_records(self) -> list[dict[str, Any]]:
        return list(self._read(self.evidence_path))

    def _index(self) -> Any:
        return index_for(self.evidence_path) if index_enabled() else None

    def _new_evidence_ids(self, k: int) -> list[str]:
        """The next `k` evidence ids: counted from the trials the ledger holds, as they always were,
        and never one the ledger already holds -- a count can fall behind ids recorded out of
        sequence, and an id handed out twice would let one record's fold drop the other's. Read
        through the index, so allocating an id does not read the whole ledger."""
        index = self._index()
        if index is not None:                      # current: it rescans whenever the file moved
            count, taken = index.trial_count(), index.has_trial_id
        else:
            records = self.raw_records()
            count = sum(1 for r in records if r.get("kind") == "trial")
            ids = {r.get("id") for r in records if r.get("kind") == "trial"}
            taken = ids.__contains__
        out: list[str] = []
        n = count
        while len(out) < k:
            n += 1
            candidate = sequential_id("EV", n)
            if not taken(candidate):
                out.append(candidate)
        return out

    def next_evidence_id(self) -> str:
        return self._new_evidence_ids(1)[0]

    def trial_count(self) -> int:
        """Trial records in the ledger, counted line by line (a repeated id counts each time)."""
        index = self._index()
        if index is not None:
            return index.trial_count()
        return sum(1 for r in self.raw_records() if r.get("kind") == "trial")

    def append_trial(self, record: dict[str, Any]) -> str:
        with ledger_lock(self.dir):
            return self._append_trial(record)

    def _append_trial(self, record: dict[str, Any]) -> str:
        record = dict(record)
        record["kind"] = "trial"
        record.setdefault("id", self.next_evidence_id())
        record.setdefault("timestamp", utc_now())
        record.setdefault("validity", "valid")
        self._append(self.evidence_path, record)
        return record["id"]

    def append_trials(self, records: list[dict[str, Any]]) -> list[str]:
        """Allocate ids in one pass — one re-scan of the ledger, not N — and append them before
        anyone else counts."""
        with ledger_lock(self.dir):
            return self._append_trials(records)

    def _append_trials(self, records: list[dict[str, Any]]) -> list[str]:
        fresh = self._new_evidence_ids(len(records))
        ids: list[str] = []
        for new_id, record in zip(fresh, records):
            record = dict(record)
            record["kind"] = "trial"
            record["id"] = new_id
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
        for offset, record, _ in read_records(self.evidence_path):
            if record.get("kind") == "trial":
                if "id" not in record:
                    raise no_id(self.evidence_path, offset)
                trials[record["id"]] = dict(record)
            elif record.get("kind") == "amendment":
                amendments.append(record)

        for amendment in amendments:
            target = trials.get(amendment.get("target", ""))
            if target is not None:
                apply_amendment(target, amendment)
        return list(trials.values())

    def trials_for(self, contracts: Any = (), runs: Any = ()) -> list[dict[str, Any]]:
        """The trials effective_trials() returns whose contract is in `contracts` or whose run is in
        `runs`, in the same order and with the same amendments folded in -- reading only their lines
        (DEF-evidence-record: a record enters the slices of its own contract and no other's)."""
        contracts, runs = set(contracts), set(runs)
        index = self._index()
        if index is not None:
            found = index.trials_for(contracts, runs)
            if found is not None:
                return found
        return [t for t in self.effective_trials()
                if t.get("contract_id") in contracts or t.get("run_id") in runs]

    def latest_runs(self) -> dict[Any, Any]:
        """test_id -> the run of the last trial naming both, in the order effective_trials() gives."""
        index = self._index()
        found = index.latest_runs() if index is not None else None
        if found is None:
            found = {}
            for t in self.effective_trials():
                if t.get("test_id") and t.get("run_id"):
                    found[t["test_id"]] = t["run_id"]
        return found

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
        index = self._index()
        out = index.notes_read() if index is not None else None
        if out is None:
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
        with ledger_lock(self.dir):
            record.setdefault("id", sequential_id("DEC", len(self.decisions()) + 1))
            self._append(self.decisions_path, record)
        return record

    def decisions(self) -> list[dict[str, Any]]:
        return list(self._read(self.decisions_path))

    # ---------- runs ----------

    def next_run_id(self) -> str:
        index = self._index()
        if index is not None:
            seen = {sequential_id("RUN", index.highest_run())}
        else:
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

    def reserve_run_id(self) -> tuple[str, Path]:
        """A run id no other run holds, with its artifact directory made. The directory is the
        reservation: it is created with exist_ok=False, so two runs at once -- in this server or
        in another process on the same project -- never share an id, and an id whose directory
        exists from a run that recorded nothing is skipped rather than written into."""
        with ledger_lock(self.dir):
            n = int(self.next_run_id().split("-", 1)[1])
            while True:
                run_id = sequential_id("RUN", n)
                path = self.artifacts_dir / run_id
                try:
                    path.mkdir(parents=True, exist_ok=False)
                    return run_id, path
                except FileExistsError:
                    n += 1
