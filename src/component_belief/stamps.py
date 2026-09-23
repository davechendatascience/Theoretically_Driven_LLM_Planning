"""What made each file, what ran it, and whether any live belief still rests on it.

Pruning a repository is otherwise a memory exercise, and memory deletes the wrong file eventually.
Every fact needed is already recorded somewhere:

  git            when a path was added and last changed, and by which revision
  the run ledger which runs invoked it, when, and what evidence those runs produced
  belief.yaml    which component claims it as code, and which declared test names it
  the filesystem for generated artifacts nobody tracks, the newest mtime beneath them

The join that matters is the last one in the ledger rather than on disk: an artifact is still
needed when evidence that is still belief-eligible came from a run that named it. A file that
nothing claims, nothing has run, and no live evidence depends on is a candidate -- and a candidate
is all it is, because these sources are not equally strong. Each stamp carries the source it came
from so a reader can tell "RUN-0140 invoked it at 04:44" from "its mtime is three weeks old".

Roots are declared, never guessed: code roots come from the components' `code:` entries, and
generated roots from belief.yaml's optional top-level `artifacts:` list.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .declarations import Declarations
from .store import Store

CODE_SUFFIXES = (".py", ".sh", ".js", ".ts", ".rb", ".go", ".rs")


@dataclass
class FileStamps:
    path: str
    tracked: bool
    stamps: list[dict[str, Any]] = field(default_factory=list)

    def kinds(self) -> set[str]:
        return {s["kind"] for s in self.stamps}

    @property
    def is_code(self) -> bool:
        return self.path.endswith(CODE_SUFFIXES)

    def prune_candidate(self) -> bool:
        """Nothing claims it, nothing has run it, no live evidence rests on it."""
        return self.tracked and self.is_code and not (
            self.kinds() & {"invoked", "claimed", "named", "supports"})


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _iso(ts: float | str) -> str:
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat(timespec="seconds")


def code_roots(decl: Declarations) -> tuple[str, ...]:
    """The directories the declarations say code lives in, so paths are matched, not guessed."""
    roots = {entry.split("/", 1)[0] for comp in decl.components.values() for entry in comp.code
             if "/" in entry}
    return tuple(sorted(roots)) or ("src", "tools", "tests")


def collect(root: Path, decl: Declarations, store: Store) -> list[FileStamps]:
    pattern = re.compile(r"(?<![\w/.])((?:" + "|".join(map(re.escape, code_roots(decl)))
                         + r")/[\w./-]+)")
    tracked = [f for f in _git(root, "ls-files").split("\n")
               if f and not f.startswith((".belief/", "third_party/"))]

    history: dict[str, dict] = {}
    commit = when = ""
    for line in _git(root, "log", "--reverse", "--name-only", "--format=%x00%H %ct").split("\n"):
        if line.startswith("\0"):
            commit, when = line[1:].split(" ", 1)
        elif line.strip():
            e = history.setdefault(line.strip(), {"added": when, "added_rev": commit})
            e["changed"], e["changed_rev"] = when, commit

    live_runs = {t.get("run_id") for t in store.effective_trials()
                 if t.get("validity") == "valid" and t.get("provenance") in ("measured", "imported")}
    invoked: dict[str, list[dict]] = {}
    supports: dict[str, set[str]] = {}
    for command in sorted(store.artifacts_dir.glob("*/command.txt")):
        text = command.read_text(errors="replace")
        at = re.search(r"^at=(\S+)", text, re.M)
        run_id = command.parent.name
        for path in set(pattern.findall(text)):
            invoked.setdefault(path, []).append(
                {"kind": "invoked", "source": "run-ledger", "run": run_id,
                 "at": at.group(1) if at else None})
            if run_id in live_runs:
                supports.setdefault(path, set()).add(run_id)

    named: dict[str, set[str]] = {}
    for test in decl.tests.values():
        for path in set(pattern.findall(test.run or "")):
            named.setdefault(path, set()).add(test.id)

    out: list[FileStamps] = []
    for path in tracked:
        stamps: list[dict[str, Any]] = []
        h = history.get(path)
        if h:
            stamps += [{"kind": "added", "source": "git", "at": _iso(h["added"]),
                        "revision": h["added_rev"][:8]},
                       {"kind": "changed", "source": "git", "at": _iso(h["changed"]),
                        "revision": h["changed_rev"][:8]}]
        stamps += sorted(invoked.get(path, []), key=lambda s: s["at"] or "")[-3:]
        for cid, comp in sorted(decl.components.items()):
            if any(path == e or path.startswith(e.rstrip("/") + "/") or fnmatch(path, e)
                   for e in comp.code):
                stamps.append({"kind": "claimed", "source": "belief.yaml", "by": cid})
        for tid in sorted(named.get(path, ())):
            stamps.append({"kind": "named", "source": "declared test", "by": tid})
        if path in supports:
            stamps.append({"kind": "supports", "source": "evidence",
                           "runs": sorted(supports[path])[:4],
                           "note": "belief-eligible evidence came from a run that named it"})
        out.append(FileStamps(path=path, tracked=True, stamps=stamps))

    for name in decl.artifacts:
        base = root / name
        if not base.exists():
            continue
        for entry in sorted(base.iterdir()):
            files = [p for p in entry.rglob("*") if p.is_file()] if entry.is_dir() else [entry]
            newest = max((p.stat().st_mtime for p in files), default=entry.stat().st_mtime)
            out.append(FileStamps(path=f"{name}/{entry.name}", tracked=False, stamps=[
                {"kind": "generated", "source": "mtime", "at": _iso(newest),
                 "bytes": sum(p.stat().st_size for p in files)}]))
    return out
