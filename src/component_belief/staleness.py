"""Configuration control for evidence: a trial measured one state of the code, and it stops
speaking for the current one once that code has changed.

consistency-belief marks a node STALE when a premise upstream is restated, and it knows a
restatement by content: the hash of the statement. This is the empirical counterpart, and it
binds evidence the same way. When a test runs, the runner stamps the exact content of every file
the evidence depends on -- the components' claimed `code:`, the files the test itself names, and
what the run opened -- as git blob ids, taken from the working tree as it actually stood. A trial
is current while those blobs match HEAD and stale the moment one does not.

Content, not revision, because a revision says which commit was checked out and not what was
measured:

  - a run on a dirty tree measured edits HEAD may never receive; discard them and a revision
    check would still vouch for the run, while the blobs no longer match
  - an amend, rebase or squash-merge renames the commit and keeps the bytes; the blobs still
    match, where a revision check would call the evidence foreign
  - a test is part of what was measured: gut the test file and the evidence it produced was
    produced by a different test

Trials recorded before stamps existed, and imported trials, carry no stamp and fall back to the
revision check: one `git diff --name-only <revision> HEAD` per distinct revision.

Nothing here decides what to do about staleness: the model reports the slice as stale, the policy
refuses to adopt on it, and the plan schedules the re-run. A component that claims no code
cannot go stale through its code -- one more reason to claim it.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .ids import content_hash
from .store import STORE_DIR

STAMP_FILE = "stamp.json"
STAMP_VERSION = 1
#: Recording a run dirties the ledgers by construction; they are never part of what was measured.
LEDGER_DIRS = (".belief", ".consistency")
_EXCLUDE = [f":(exclude){d}" for d in LEDGER_DIRS]


def _git(root: Path, *args: str, stdin_text: str | None = None) -> str | None:
    """stdout, or None when git fails. stdin is closed unless fed: an inherited MCP stdio pipe
    hangs any child that reads it."""
    feed: dict[str, Any] = ({"input": stdin_text} if stdin_text is not None
                            else {"stdin": subprocess.DEVNULL})
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                             timeout=120, encoding="utf-8", errors="replace", **feed)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _split0(text: str | None) -> list[str]:
    return [p for p in (text or "").split("\0") if p]


def matches(path: str, entry: str) -> bool:
    """A `code:` or `reads:` entry names a file, a glob, or a directory."""
    return path == entry or fnmatch(path, entry) or path.startswith(entry.rstrip("/") + "/")


def head_blobs(root: Path) -> dict[str, str] | None:
    """Every tracked file at HEAD and its blob id; None when there is no HEAD to compare with."""
    listing = _git(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    if listing is None:
        return None
    blobs: dict[str, str] = {}
    for entry in _split0(listing):
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob":
            blobs[path] = parts[2]
    return blobs


def _hash_files(root: Path, paths: list[str]) -> dict[str, str]:
    """Blob ids of working-tree files, through git's own filters -- so a CRLF checkout of an LF
    blob hashes to the committed id rather than reading as an edit."""
    if not paths:
        return {}
    out = _git(root, "hash-object", "--stdin-paths", stdin_text="\n".join(paths) + "\n")
    ids = (out or "").split()
    return dict(zip(paths, ids)) if len(ids) == len(paths) else {}


def named_paths(command: str, reads: list[str], known: set[str]) -> list[str]:
    """The files a test names: paths on its run line, and its declared `reads:`.

    A test is part of what its evidence measured. `python tools/pytest_trials.py $OUT --
    tests/test_x.py::TestA` names the adapter and the test module, and an edit to either changes
    what a pass means.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    entries = []
    for token in tokens + list(reads):
        token = token.split("::", 1)[0].replace("\\", "/").removeprefix("./").rstrip("/")
        if token and not token.startswith("-") and "$" not in token and "%" not in token:
            entries.append(token)
    return sorted({p for p in known for e in entries if matches(p, e)})


class Snapshot:
    """The content of the tree a run is about to measure, taken before the command starts."""

    def __init__(self, root: Path, head: str, blobs: dict[str, str | None], dirty: list[str],
                 claimed: list[str], named: list[str]) -> None:
        self.root, self.head, self.blobs = root, head, blobs
        self.dirty, self.claimed, self.named = dirty, claimed, named

    @classmethod
    def take(cls, root: Path, claimed: list[str], command: str, reads: list[str]) -> "Snapshot | None":
        head = (_git(root, "rev-parse", "HEAD") or "").strip()
        committed = head_blobs(root) if head else None
        if committed is None:
            return None
        blobs: dict[str, str | None] = dict(committed)
        edited = _split0(_git(root, "diff", "--name-only", "-z", "HEAD", "--", ".", *_EXCLUDE))
        untracked = _split0(_git(root, "ls-files", "--others", "--exclude-standard", "-z",
                                 "--", ".", *_EXCLUDE))
        # An untracked file matters only if the evidence could rest on it; hashing every stray
        # file in a large checkout would cost more than the run.
        named_untracked = set(named_paths(command, reads, set(untracked)))
        untracked = [p for p in untracked
                     if p in named_untracked or any(matches(p, e) for e in claimed)]
        present = [p for p in edited + untracked if (root / p).is_file()]
        hashed = _hash_files(root, present)
        for path in edited + untracked:
            blobs[path] = hashed.get(path)          # None: deleted in the working tree
        named = named_paths(command, reads, set(blobs))
        return cls(root, head, blobs, sorted(set(edited + untracked)), list(claimed), named)

    def stamp(self, opened: list[str]) -> dict[str, Any]:
        """The record to keep: only the files some evidence could rest on."""
        keep = set(self.named) | {p for p in opened if p in self.blobs}
        keep |= {p for p in self.blobs if any(matches(p, e) for e in self.claimed)}
        return {
            "version": STAMP_VERSION,
            "head": self.head,
            "claimed": sorted(set(self.claimed)),
            "named": self.named,
            "opened": sorted(p for p in opened if p in self.blobs),
            "dirty": sorted(p for p in self.dirty if p in keep),
            "files": {p: self.blobs.get(p) for p in sorted(keep)},
        }


def write_stamp(artifact_dir: Path, stamp: dict[str, Any]) -> str:
    """Persist a run's stamp and return the digest every trial of the run carries."""
    (artifact_dir / STAMP_FILE).write_text(json.dumps(stamp, indent=1, sort_keys=True),
                                           encoding="utf-8")
    return content_hash(stamp, 16)


class CodeStaleness:
    """Compares each trial's stamp with HEAD. HEAD's tree is listed once, stamps are read once
    per run, and the revision fallback runs one git call per distinct revision."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._head: dict[str, str] | None | bool = False
        self._stamps: dict[str, dict[str, Any] | str] = {}
        self._changed: dict[str, set[str] | None] = {}

    def head(self) -> dict[str, str] | None:
        if self._head is False:
            self._head = head_blobs(self.root)
        return self._head  # type: ignore[return-value]

    def stamp_for(self, trial: dict[str, Any]) -> dict[str, Any] | str | None:
        """The run's stamp; a string when the trial claims one that cannot be trusted; None for a
        trial recorded without one."""
        digest = trial.get("stamp")
        if not digest:
            return None
        run_id = str(trial.get("run_id") or "")
        key = f"{run_id}:{digest}"
        if key not in self._stamps:
            path = self.root / STORE_DIR / "artifacts" / run_id / STAMP_FILE
            try:
                stamp = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._stamps[key] = f"its stamp {run_id}/{STAMP_FILE} is missing or unreadable"
            else:
                self._stamps[key] = stamp if content_hash(stamp, 16) == digest else (
                    f"{run_id}/{STAMP_FILE} no longer matches the digest its trials recorded")
        return self._stamps[key]

    def stale_reason(self, code_paths: list[str], trial: dict[str, Any]) -> str | None:
        """Why this trial no longer speaks for HEAD, or None if it still does."""
        stamp = self.stamp_for(trial)
        if stamp is None:
            return self._revision_reason(code_paths, trial)
        if isinstance(stamp, str):
            return stamp
        head = self.head()
        if head is None:
            return None

        files: dict[str, str | None] = stamp.get("files") or {}
        covered = [e for e in code_paths if e in (stamp.get("claimed") or [])]
        watch = set(stamp.get("named") or [])
        watch |= {p for p in set(files) | set(head) if any(matches(p, e) for e in covered)}
        # a path absent from the stamp did not exist when the run looked
        changed = sorted(p for p in watch if files.get(p) != head.get(p))
        if changed:
            dirty = [p for p in changed if p in (stamp.get("dirty") or [])]
            if dirty:
                return (f"{_shown(dirty)} was measured with uncommitted edits HEAD does not have "
                        f"({trial.get('run_id')})")
            return f"{_shown(changed)} changed since {trial.get('run_id')} ({stamp.get('head', '')[:7]})"

        # A path claimed after the run was stamped has no recorded content: judge it by revision.
        uncovered = [e for e in code_paths if e not in covered]
        return self._revision_reason(uncovered, trial) if uncovered else None

    # ---------- the fallback for unstamped trials ----------

    def changed_since(self, revision: str) -> set[str] | None:
        """Paths changed between `revision` and HEAD. None when git does not know the revision --
        a rebase or a different clone -- which is itself a fact about the evidence."""
        if revision not in self._changed:
            out = _git(self.root, "diff", "--name-only", revision, "HEAD")
            self._changed[revision] = None if out is None else {
                line.strip() for line in out.splitlines() if line.strip()}
        return self._changed[revision]

    def _revision_reason(self, code_paths: list[str], trial: dict[str, Any]) -> str | None:
        repro = trial.get("repro") or {}
        revision = str(repro.get("sw_revision") or trial.get("system_version") or "")
        if not revision or not code_paths:
            return None
        changed = self.changed_since(revision)
        if changed is None:
            return f"revision {revision} is not in this repository's history"
        hit = sorted(path for path in changed
                     if any(path == entry or fnmatch(path, entry) for entry in code_paths))
        return f"{_shown(hit)} changed since {revision}" if hit else None


def _shown(paths: list[str]) -> str:
    return ", ".join(paths[:3]) + (f" +{len(paths) - 3} more" if len(paths) > 3 else "")
