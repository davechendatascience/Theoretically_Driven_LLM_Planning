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

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from . import readlog
from .declarations import Declarations
from .store import Store

CODE_SUFFIXES = (".py", ".sh", ".js", ".ts", ".rb", ".go", ".rs")
#: A trial cites what it measured by name; a settings string is not a file, however
#: many dots it carries.
_FILENAME = re.compile(r"[\w.-]{1,100}\.[A-Za-z][A-Za-z0-9]{0,7}")


@dataclass
class FileStamps:
    path: str
    tracked: bool
    stamps: list[dict[str, Any]] = field(default_factory=list)
    directory: bool = False

    def kinds(self) -> set[str]:
        return {s["kind"] for s in self.stamps}

    @property
    def is_code(self) -> bool:
        return self.path.endswith(CODE_SUFFIXES)

    def prune_candidate(self) -> bool:
        """Nothing claims it, nothing has run it, no live evidence rests on it."""
        return self.tracked and not self.directory and self.is_code and not (
            self.kinds() & {"invoked", "claimed", "named", "supports", "opened"})

    def artifact_verdict(self) -> str:
        """For generated output: kept, unread, or undecidable because nothing watched it.

        An artifact is prunable when instrumented runs opened it and none of their evidence is
        live -- or when it was written before any run was instrumented and nothing declares it,
        in which case the honest answer is that the ledger cannot tell.
        """
        kinds = self.kinds()
        if "supports" in kinds:
            return "kept: live evidence rests on it"
        if "named" in kinds:
            return "kept: a declared test reads it"
        if "opened" in kinds:
            return "prunable: every run that opened it has superseded evidence"
        return "undecidable: no instrumented run opened it and no test declares it"


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              timeout=120, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL).stdout
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
    """Every file's stamps. `dangling_citations` reports names live evidence cites that
    no longer exist; it is attached to the module-level result for the view to print."""
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

    cited, dangling = _citations(root, store, decl)

    opened: dict[str, list[dict]] = {}
    for run_dir in sorted(store.artifacts_dir.glob("*/")):
        for rel in readlog.read(run_dir):
            opened.setdefault(rel, []).append({"kind": "opened", "source": "read hook",
                                               "run": run_dir.name,
                                               "live": run_dir.name in live_runs})

    named: dict[str, set[str]] = {}
    for test in decl.tests.values():
        for path in set(pattern.findall(test.run or "")) | set(test.reads):
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
        stamps += _opened_stamps(opened.get(path, []))
        if path in supports:
            stamps.append({"kind": "supports", "source": "evidence",
                           "runs": sorted(supports[path])[:4],
                           "note": "belief-eligible evidence came from a run that named it"})
        out.append(FileStamps(path=path, tracked=True, stamps=stamps))

    out += _tracked_directories(out)

    for name in decl.artifacts:
        base = root / name
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")) + [base]:
            out.append(_artifact_record(root, path, opened, named, cited))

    collect.dangling = dangling          # the view prints it; nothing else reads it
    return out


def _citations(root: Path, store: Store, decl: Declarations) -> tuple[dict[str, int], dict[str, int]]:
    """What live trials name in their reproduction data, and which of those no longer exist.

    A trial records the revision of the thing it measured -- a checkpoint, a dataset -- and that
    name is a claim on the file: while the trial is belief-eligible, deleting the file makes its
    slice unauditable for good. The number survives and the thing it measured does not, which is
    the one pruning mistake with no remedy, so it is reported as its own finding.
    """
    names: dict[str, int] = {}
    for trial in store.effective_trials():
        if trial.get("validity") != "valid" or trial.get("provenance") not in ("measured", "imported"):
            continue
        claims = list((trial.get("repro") or {}).values())
        # ingest requires an artifact_uri, and a record's source often names the file it came
        # from: both are claims on a path, and ignoring them made the evidence directory that
        # every imported trial points at read as though nothing wanted it.
        claims += [trial.get("artifact_uri"), trial.get("source")]
        for value in claims:
            if not isinstance(value, str):
                continue
            # `name:revision` cites a revision; a drive letter (C:\...) is not one
            value = re.sub(r"^[A-Za-z]:/", "/", value.replace("\\", "/").strip())
            head = value.split(":")[0].rstrip("/")
            head = head.rsplit("/", 1)[-1] if "/" in head else head
            if _FILENAME.fullmatch(head):
                names[head] = names.get(head, 0) + 1

    present = {p.name for name in decl.artifacts for p in (root / name).glob("**/*")
               if (root / name).exists()}
    present |= {Path(f).name for f in _git(root, "ls-files").split("\n") if f}
    # a symlink's name is not what a trial records: it cites the revision it measured, which is
    # the target. Both names stand for the same bytes, so each answers for the other.
    for name in decl.artifacts:
        base = root / name
        if base.exists():
            for entry in base.iterdir():
                if entry.is_symlink():
                    present.add(os.path.basename(os.path.realpath(entry)))
    dangling = {n: c for n, c in names.items() if n not in present}
    return {n: c for n, c in names.items() if n in present}, dangling


def _artifact_record(root: Path, path: Path, opened: dict[str, list[dict]],
                     named: dict[str, set[str]], cited: dict[str, int]) -> FileStamps:
    """One generated file or directory, with everything that keeps it.

    A directory answers to its contents as well as its own name: trials cite the trial file, runs
    open the shard, and a folder is not unwanted because nothing names the folder.
    """
    rel = path.relative_to(root).as_posix()
    files = [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else [path]
    newest = max((p.stat().st_mtime for p in files), default=path.stat().st_mtime)
    stamps: list[dict[str, Any]] = [{"kind": "generated", "source": "mtime", "at": _iso(newest),
                                     "bytes": sum(p.stat().st_size for p in files),
                                     "files": len(files)}]

    hits = [h for r, hh in opened.items() if r == rel or r.startswith(rel + "/") for h in hh]
    stamps += _opened_stamps(hits)
    for tid in sorted({t for r, ids in named.items()
                       if r == rel or r.startswith(rel + "/") for t in ids}):
        stamps.append({"kind": "named", "source": "declared test", "by": tid})

    aliases = [path.name]
    if path.is_symlink():                       # a trial cites the revision, not the alias
        aliases.append(os.path.basename(os.path.realpath(path)))
    if path.is_dir():
        aliases += [f.name for f in files]
    hit = next((a for a in aliases if a in cited), None)
    if hit:
        stamps.append({"kind": "cited", "source": "evidence", "trials": cited[hit], "as": hit,
                       "note": "belief-eligible trials name it in their reproduction data"})
        stamps.append({"kind": "supports", "source": "evidence", "runs": [],
                       "note": f"{cited[hit]} live trials cite it"})
    elif any(h.get("live") for h in hits):
        stamps.append({"kind": "supports", "source": "evidence",
                       "runs": sorted({h["run"] for h in hits if h.get("live")})[:4],
                       "note": "a run whose evidence is still belief-eligible opened it"})
    return FileStamps(path=rel, tracked=False, stamps=stamps, directory=path.is_dir())


def _tracked_directories(files: list[FileStamps]) -> list[FileStamps]:
    """Every directory holding tracked files, stamped by what its files carry.

    The question "is this folder justified" is asked of folders, so a folder is a record rather
    than something a reader has to assemble from the files inside it.
    """
    rolled: dict[str, list[FileStamps]] = {}
    for record in files:
        parts = record.path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            rolled.setdefault("/".join(parts[:depth]), []).append(record)

    out = []
    for path, members in sorted(rolled.items()):
        kinds: dict[str, set[str]] = {}
        for member in members:
            for stamp in member.stamps:
                if stamp["kind"] in ("claimed", "named", "invoked", "cited", "supports", "opened"):
                    kinds.setdefault(stamp["kind"], set()).add(str(stamp.get("by") or stamp.get("run")
                                                                   or stamp.get("as") or ""))
        stamps = [{"kind": "contains", "source": "git", "files": len(members)}]
        stamps += [{"kind": kind, "source": "rolled up from its files",
                    "by": sorted(x for x in who if x)[:4]} for kind, who in sorted(kinds.items())]
        out.append(FileStamps(path=path, tracked=True, stamps=stamps, directory=True))
    return out


def _opened_stamps(hits: list[dict]) -> list[dict]:
    """One stamp per file, naming the runs that opened it and whether any is still live."""
    if not hits:
        return []
    runs = sorted({h["run"] for h in hits})
    return [{"kind": "opened", "source": "read hook", "runs": runs[:4], "n_runs": len(runs),
             "live_runs": sorted({h["run"] for h in hits if h.get("live")})[:4]}]
