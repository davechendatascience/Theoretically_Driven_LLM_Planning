"""Where each record of the evidence ledger sits, so a reader that needs a few contracts reads only
their lines.

The evidence ledger is append-only (DEF-ledger) and can run to gigabytes, and most readers want a
small part of it: the trials of the contracts a research board's spends name, an impact report's
affected contracts, one run, a count to allocate the next id. Reading and parsing every line for
that took most of a board build.

The index keeps, per process and in memory only, the byte offset of each record under the keys
those readers select on. It is built by one scan on first use and extended by the whole lines
appended since it last looked. It scans in full again when the file is not the one it indexed: a
new inode, a file shorter than what was indexed, the same size with a new modification time (an
edit in place), different bytes at the start or just before the indexed end, or a line read back
that is not what was indexed. It writes nothing and takes no lock across processes, so a reader
stays a reader.

Exactness: every answer equals the one the full read gives, because both read lines with
`read_records` and fold amendments with `apply_amendment`. A final line with no newline yet is read
as the full read reads it -- included when it parses -- and kept apart, provisionally, until its
newline arrives.

`TDLP_EVIDENCE_INDEX=off` makes every reader take the full read instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from array import array
from collections import OrderedDict
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import Any

WINDOW = 4096          # bytes compared at the start of the file and just before the indexed end
KEEP = 16              # ledgers indexed at once in one process
RUN = re.compile(r"RUN-(\d+)")


class LedgerError(ValueError):
    """A ledger line no reader can take: JSON that is not an object, or a trial without an id."""


def parse_line(raw: bytes, path: Path, offset: int) -> dict[str, Any] | None:
    """One ledger line as a record; None for a blank line or one that is not JSON, as the ledger
    has always been read. Invalid UTF-8 raises, as reading the file as text did."""
    text = raw.decode("utf-8").strip()
    if not text:
        return None
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        raise LedgerError(f"{path}: the line at byte {offset} is JSON but not an object")
    return record


def read_records(path: Path, start: int = 0) -> Iterator[tuple[int, dict[str, Any], bool]]:
    """Each record from byte `start`, with its offset and whether its line ends in a newline.
    Lines are split on newlines alone, so every reader of the ledger sees the same lines."""
    try:
        fh = path.open("rb")
    except FileNotFoundError:
        return
    with fh:
        fh.seek(start)
        offset = start
        for raw in fh:
            record = parse_line(raw, path, offset)
            if record is not None:
                yield offset, record, raw.endswith(b"\n")
            offset += len(raw)


def apply_amendment(trial: dict[str, Any], amendment: dict[str, Any]) -> None:
    """Fold one amendment into the trial it targets. It changes validity only -- never what the
    trial was recorded against -- so selecting trials by contract or run before folding is exact."""
    if amendment.get("validity"):
        trial["validity"] = amendment["validity"]
        trial["validity_reason"] = amendment.get("reason", "")
    if amendment.get("supersede_with"):
        trial["validity"] = "superseded"
        trial["superseded_by"] = amendment["supersede_with"]
        trial["validity_reason"] = amendment.get("reason", "")


def no_id(path: Path, offset: int) -> LedgerError:
    return LedgerError(f"{path}: the trial record at byte {offset} has no id")


def enabled() -> bool:
    return os.environ.get("TDLP_EVIDENCE_INDEX", "").strip().lower() not in ("off", "0", "false", "no")


class _Moved(Exception):
    """A line read back is not the record the index holds at its offset."""


class EvidenceIndex:
    """The offsets of one evidence ledger's records, by the keys its readers select on."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.scans = 0
        self._clear(None)

    def _clear(self, identity: tuple[int, int] | None) -> None:
        self.identity = identity                       # (device, inode) of the file indexed
        self.offset = 0                                # bytes indexed, whole lines only
        self.seen: tuple[int, int] | None = None       # (size, mtime) at the last look
        self.start = b""                               # digest of the first WINDOW bytes indexed
        self.before = b""                              # digest of the WINDOW bytes before `offset`
        self.by_contract: dict[Any, array] = {}       # trial lines, by contract_id
        self.by_run: dict[Any, array] = {}            # trial lines, by run_id
        self.by_target: dict[Any, array] = {}         # amendment lines, by target
        self.notes = array("Q")
        self.ids: dict[Any, tuple[int, int]] = {}     # trial id -> offsets of its first and last line
        self.duplicates = 0                            # trial lines repeating an id
        self.latest_run: dict[Any, Any] = {}          # test_id -> run_id of the last trial line naming both
        self.trials = 0                                # trial lines
        self.top_run = 0                               # highest RUN-n any record names
        self.idless: int | None = None                 # first trial line without an id
        self.tail: tuple[int, dict[str, Any]] | None = None   # a final line with no newline, parsed

    # ---------- keeping it current ----------

    @staticmethod
    def _digest(fh: Any, start: int, end: int) -> bytes:
        fh.seek(start)
        return hashlib.sha256(fh.read(max(0, end - start))).digest()

    def _same_file(self, fh: Any, identity: tuple[int, int], size: int, mtime: int) -> bool:
        if self.seen is None or identity != self.identity or size < self.offset:
            return False
        if size == self.seen[0] and mtime != self.seen[1]:
            return False                               # rewritten in place: an append always grows it
        return (self._digest(fh, 0, min(WINDOW, self.offset)) == self.start
                and self._digest(fh, max(0, self.offset - WINDOW), self.offset) == self.before)

    def _add(self, offset: int, record: dict[str, Any]) -> None:
        run = record.get("run_id")
        if isinstance(run, str) and (match := RUN.fullmatch(run)):
            self.top_run = max(self.top_run, int(match.group(1)))
        kind = record.get("kind")
        if kind == "trial":
            self.trials += 1
            if "id" not in record:
                if self.idless is None:
                    self.idless = offset
                return
            rid = record["id"]
            span = self.ids.get(rid)
            if span is None:
                self.ids[rid] = (offset, offset)
            else:
                self.ids[rid] = (span[0], offset)
                self.duplicates += 1
            self.by_contract.setdefault(record.get("contract_id"), array("Q")).append(offset)
            if run:
                self.by_run.setdefault(run, array("Q")).append(offset)
                if record.get("test_id"):
                    self.latest_run[record["test_id"]] = run
        elif kind == "amendment":
            self.by_target.setdefault(record.get("target", ""), array("Q")).append(offset)
        elif kind == "note":
            self.notes.append(offset)

    def refresh(self) -> None:
        """Index the lines appended since the last look, or everything again if the file moved."""
        with self._lock:
            try:
                st = os.stat(self.path)
            except FileNotFoundError:
                self._clear(None)
                return
            identity, size, mtime = (st.st_dev, st.st_ino), st.st_size, st.st_mtime_ns
            if identity == self.identity and self.seen == (size, mtime):
                return
            with self.path.open("rb") as fh:
                if not self._same_file(fh, identity, size, mtime):
                    self._clear(identity)
                    self.scans += 1
                self.tail = None
                fh.seek(self.offset)
                offset = self.offset
                try:
                    for raw in fh:
                        if not raw.endswith(b"\n"):    # still being written, or never ended
                            record = parse_line(raw, self.path, offset)
                            if record is not None:
                                self.tail = (offset, record)
                            break
                        record = parse_line(raw, self.path, offset)
                        if record is not None:
                            self._add(offset, record)
                        offset += len(raw)
                except BaseException:
                    self._clear(None)                  # half-read: the next look scans in full
                    raise
                self.offset = offset
                self.start = self._digest(fh, 0, min(WINDOW, offset))
                self.before = self._digest(fh, max(0, offset - WINDOW), offset)
                self.seen = (size, mtime)

    def rescan(self) -> None:
        with self._lock:
            self._clear(None)
            self.refresh()

    # ---------- what readers ask ----------

    def _tail(self, kind: str) -> tuple[int, dict[str, Any]] | None:
        return self.tail if self.tail is not None and self.tail[1].get("kind") == kind else None

    def trial_count(self) -> int:
        with self._lock:
            self.refresh()
            return self.trials + (1 if self._tail("trial") else 0)

    def has_trial_id(self, trial_id: Any) -> bool:
        with self._lock:
            self.refresh()
            tail = self._tail("trial")
            return trial_id in self.ids or (tail is not None and tail[1].get("id") == trial_id)

    def highest_run(self) -> int:
        with self._lock:
            self.refresh()
            top = self.top_run
            run = self.tail[1].get("run_id") if self.tail else None
            if isinstance(run, str) and (match := RUN.fullmatch(run)):
                top = max(top, int(match.group(1)))
            return top

    def latest_runs(self) -> dict[Any, Any] | None:
        """test_id -> the run of the last trial naming both, in the ledger's order; None when a trial
        id repeats, where the fold's order is not the lines' and the caller reads in full."""
        with self._lock:
            self.refresh()
            tail = self._tail("trial")
            if self.idless is not None:
                raise no_id(self.path, self.idless)
            if self.duplicates or (tail and tail[1].get("id") in self.ids):
                return None
            out = dict(self.latest_run)
            if tail and tail[1].get("test_id") and tail[1].get("run_id"):
                out[tail[1]["test_id"]] = tail[1]["run_id"]
            return out

    def _read_at(self, fh: Any, offset: int) -> dict[str, Any]:
        fh.seek(offset)
        raw = fh.readline()
        record = parse_line(raw, self.path, offset) if raw.endswith(b"\n") else None
        if record is None:
            raise _Moved
        return record

    def notes_read(self) -> list[dict[str, Any]] | None:
        with self._lock:
            for _ in range(2):
                self.refresh()
                if self.identity is None:
                    return []
                try:
                    with self.path.open("rb") as fh:
                        out = []
                        for offset in self.notes:
                            record = self._read_at(fh, offset)
                            if record.get("kind") != "note":
                                raise _Moved
                            out.append(record)
                except (_Moved, FileNotFoundError):
                    self.rescan()
                    continue
                tail = self._tail("note")
                return out + ([tail[1]] if tail else [])
            return None

    def trials_for(self, contracts: Collection[Any], runs: Collection[Any] = ()) -> list[dict[str, Any]] | None:
        """The effective trials -- amendments folded in, a repeated id read from its last line at
        the place of its first -- whose contract is in `contracts` or whose run is in `runs`, in the
        ledger's order. None when the index cannot vouch for its answer twice running."""
        with self._lock:
            for _ in range(2):
                self.refresh()
                if self.idless is not None:
                    raise no_id(self.path, self.idless)
                if self.identity is None:
                    return []
                tail = self._tail("trial")
                if tail and "id" not in tail[1]:
                    raise no_id(self.path, tail[0])
                try:
                    return self._select(set(contracts), set(runs), tail)
                except (_Moved, FileNotFoundError):
                    self.rescan()
            return None

    def _select(self, contracts: set[Any], runs: set[Any],
                tail: tuple[int, dict[str, Any]] | None) -> list[dict[str, Any]]:
        offsets: set[int] = set()
        for cid in contracts:
            offsets.update(self.by_contract.get(cid, ()))
        for run in runs:
            offsets.update(self.by_run.get(run, ()))
        tail_id = tail[1].get("id") if tail else object()
        chosen: dict[Any, tuple[int, dict[str, Any]]] = {}
        with self.path.open("rb") as fh:
            for offset in sorted(offsets):
                record = self._read_at(fh, offset)
                if (record.get("kind") != "trial" or "id" not in record
                        or (record.get("contract_id") not in contracts and record.get("run_id") not in runs)):
                    raise _Moved
                rid = record["id"]
                span = self.ids.get(rid)
                if span is None or (offset not in span and not self.duplicates):
                    raise _Moved                   # with no repeated id, a line is its id's only one
                if rid == tail_id or offset != span[1]:
                    continue                       # a later line of this id stands
                chosen[rid] = (span[0], record)
            if tail and (tail[1].get("contract_id") in contracts or tail[1].get("run_id") in runs):
                span = self.ids.get(tail_id)
                chosen[tail_id] = (span[0] if span else tail[0], tail[1])
            amendment_tail = self._tail("amendment")
            out = []
            for rid, (_, record) in sorted(chosen.items(), key=lambda item: item[1][0]):
                trial = dict(record)
                for offset in self.by_target.get(rid, ()):
                    amendment = self._read_at(fh, offset)
                    if amendment.get("kind") != "amendment" or amendment.get("target", "") != rid:
                        raise _Moved
                    apply_amendment(trial, amendment)
                if amendment_tail and amendment_tail[1].get("target", "") == rid:
                    apply_amendment(trial, amendment_tail[1])
                out.append(trial)
        return out


_INDEXES: OrderedDict[str, EvidenceIndex] = OrderedDict()
_REGISTRY = threading.Lock()


def index_for(path: Path) -> EvidenceIndex:
    """The index of the ledger at `path`, shared by every reader in this process."""
    key = os.path.abspath(path)
    with _REGISTRY:
        index = _INDEXES.get(key)
        if index is None:
            index = _INDEXES[key] = EvidenceIndex(Path(key))
            while len(_INDEXES) > KEEP:
                _INDEXES.popitem(last=False)
        else:
            _INDEXES.move_to_end(key)
        return index
