"""Revision-pinned scans: every byte comes from git at one commit, never from the working tree.

The caller resolves the revision once (`resolve_revision`) and passes the full SHA; the tree is
listed and every blob read at that SHA, so a commit landing mid-scan changes nothing the scan
sees. Uncommitted edits are a separate report (`scan_worktree`), never folded into the index --
the same rule every declaration in this harness follows.

What is scanned, and what is not, is part of the result (`CodeIndex.scope`): Python files are
read; documentation is not; ledger directories, symlinks and submodules are never followed; any
other tracked file that carries a line shaped like a marker is reported as an unsupported
language rather than read by a guess at its comment syntax.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Mapping

from .impact import Changes, compare_indexes
from .model import ERROR, OBSERVATION, ClaimRef, CodeIndex, Diagnostic, Scope
from .parser import decode, parse_python
from .validation import validate

PYTHON = (".py", ".pyi")
DOCUMENTATION = (".md", ".rst", ".txt", ".adoc")
LEDGER_DIRS = (".belief/", ".consistency/")
MAX_BYTES = 1 << 20
#: A line another language would read as a marker. Matched, never parsed: it only says that a
#: tag was written where this release does not read tags.
_FOREIGN_MARKER = (r"^[[:space:]]*(#|//|--|;|%|/[*]|[*]|<!--)[[:space:]]*"
                   r"tdlp:(begin|end|implements|uses|checks|motivated-by)([^a-z-]|$)")


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=300,
                             input=data, stdin=None if data is not None else subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def resolve_revision(root: Path, revision: str = "HEAD") -> str | None:
    """The full SHA a revision names now; None when git does not know it."""
    out = _git(root, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")
    return out.decode().strip() if out else None


def _tree(root: Path, sha: str) -> list[tuple[str, str, str, str]] | None:
    out = _git(root, "ls-tree", "-r", "-z", "--full-tree", sha)
    if out is None:
        return None
    entries = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        meta, _, path = raw.partition(b"\t")
        mode, kind, oid = meta.decode().split()
        entries.append((mode, kind, oid, path.decode("utf-8", errors="surrogateescape")))
    return entries


def read_blobs(root: Path, oids: list[str]) -> dict[str, bytes]:
    """Blob contents by id, in one `git cat-file --batch`."""
    if not oids:
        return {}
    out = _git(root, "cat-file", "--batch", data=("\n".join(oids) + "\n").encode())
    blobs: dict[str, bytes] = {}
    pos = 0
    while out is not None and pos < len(out):
        nl = out.index(b"\n", pos)
        header = out[pos:nl].decode().split()
        pos = nl + 1
        if len(header) != 3:              # "<oid> missing"
            continue
        size = int(header[2])
        blobs[header[0]] = out[pos:pos + size]
        pos += size + 1
    return blobs


def show(root: Path, revision: str, path: str) -> bytes | None:
    return _git(root, "show", f"{revision}:{path}")


def _foreign_markers(root: Path, sha: str) -> list[str]:
    excludes = [f":(exclude)*{ext}" for ext in PYTHON + DOCUMENTATION]
    excludes += [f":(exclude){d.rstrip('/')}" for d in LEDGER_DIRS]
    out = _git(root, "grep", "-I", "-l", "-z", "-E", _FOREIGN_MARKER, sha, "--", ".", *excludes)
    if not out:
        return []
    prefix = sha + ":"
    return sorted(p.decode("utf-8", errors="surrogateescape").removeprefix(prefix)
                  for p in out.split(b"\0") if p)


def build_index(root: Path, revision: str, claims: Mapping[str, ClaimRef] | None = None, *,
                paths: list[str] | None = None,
                explain_claim: Callable[[str, str], str | None] | None = None,
                explain_body: bool = True) -> CodeIndex:
    """Scan the tracked files at `revision` (a full SHA the caller resolved) and, when `claims`
    is given, check every reference and pin against it. `paths` limits the scan to those files,
    for a comparison that only needs what changed; coverage is then not judged."""
    index = CodeIndex(revision=revision, scope=Scope(revision=revision, paths=paths))
    tree = _tree(root, revision)
    if tree is None:
        index.diagnostics.append(Diagnostic("SOURCE_READ_FAILURE", ERROR, revision,
                                            "git cannot list this revision's tree; nothing was scanned"))
        return index
    wanted = set(paths) if paths is not None else None
    python: list[tuple[str, str]] = []
    for mode, kind, oid, path in tree:
        if wanted is not None and path not in wanted:
            continue
        if path.startswith(LEDGER_DIRS):
            index.scope.exclude("ledger")
        elif mode == "120000":
            index.scope.exclude("symlink (not followed)")
        elif kind == "commit":
            index.scope.exclude("submodule")
        elif path.endswith(PYTHON):
            python.append((oid, path))
        elif path.endswith(DOCUMENTATION):
            index.scope.exclude("documentation")
        else:
            index.scope.exclude("other")

    blobs = read_blobs(root, sorted({oid for oid, _ in python}))
    for oid, path in sorted(python, key=lambda e: e[1]):
        data = blobs.get(oid)
        if data is None:
            index.diagnostics.append(Diagnostic("SOURCE_READ_FAILURE", ERROR, path,
                                                f"git could not read blob {oid[:12]}", path))
            continue
        if len(data) > MAX_BYTES:
            index.scope.exclude("too large")
            index.diagnostics.append(Diagnostic(
                "SOURCE_TOO_LARGE", OBSERVATION, path,
                f"{len(data)} bytes, over the {MAX_BYTES}-byte limit; its markers are not read", path))
            continue
        try:
            text = decode(data)
        except (SyntaxError, UnicodeDecodeError, LookupError) as exc:
            index.diagnostics.append(Diagnostic("SOURCE_UNREADABLE", ERROR, path,
                                                f"cannot be decoded as Python source: {exc}", path))
            continue
        scan = parse_python(path, text)
        index.scope.scanned += 1
        if scan.foreign:
            index.scope.foreign.append(path)
        index.blocks += scan.blocks
        index.mentions += scan.mentions
        index.diagnostics += scan.diagnostics

    if paths is None:
        for path in _foreign_markers(root, revision):
            index.diagnostics.append(Diagnostic(
                "UNSUPPORTED_LANGUAGE", ERROR, path,
                "carries a line shaped like a tdlp marker, and this release reads markers in Python "
                "only; the tag links nothing until it moves into Python or is removed", path))

    body = BodyHistory(root, revision).explain if explain_body else None
    validate(index, claims, explain_claim=explain_claim, explain_body=body)
    return index


class BodyHistory:
    """Where a block's body last had the digest its pin records, from the history of its file:
    so a stale body pin can name the revision to diff against instead of only saying 'changed'."""

    LIMIT = 50

    def __init__(self, root: Path, revision: str) -> None:
        self.root, self.revision = root, revision
        self._parsed: dict[tuple[str, str], dict[str, str]] = {}

    def _bodies(self, rev: str, path: str) -> dict[str, str]:
        key = (rev, path)
        if key not in self._parsed:
            data = show(self.root, rev, path)
            bodies: dict[str, str] = {}
            if data is not None:
                try:
                    bodies = {b.block_id: b.body_pin for b in parse_python(path, decode(data)).blocks}
                except (SyntaxError, UnicodeDecodeError, LookupError):
                    pass
            self._parsed[key] = bodies
        return self._parsed[key]

    def explain(self, block_id: str, path: str, pin: str) -> str | None:
        log = _git(self.root, "log", "--format=%H", f"-n{self.LIMIT}", self.revision, "--", path)
        for rev in (log or b"").decode().split():
            if self._bodies(rev, path).get(block_id) == pin:
                return (f"it last read that way at {rev[:7]}: `git diff {rev[:7]} {self.revision[:7]} "
                        f"-- {path}` shows what changed")
        return (f"no revision among the last {self.LIMIT} of {path} has this body; it was pinned "
                "against an uncommitted draft, or moved here from another file")


def scan_worktree(root: Path, index: CodeIndex) -> tuple[Changes, list[str], CodeIndex]:
    """The tagged blocks uncommitted edits would change, against the committed index -- reported,
    never merged into it. Returns the changes, the paths that differ from the revision, and the
    working tree's blocks checked against the committed index's claims: so the pins a region
    would need once committed as it stands can be written before the commit, and tagging a region
    takes one commit, not two. Nothing in it is in effect."""
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = (out or b"").split(b"\0")
    paths: list[str] = []
    skip = False
    for raw in entries:
        if skip:                              # the source path of a rename
            skip = False
            continue
        if len(raw) < 4:
            continue
        status, path = raw[:2].decode(), raw[3:].decode("utf-8", errors="surrogateescape")
        skip = "R" in status or "C" in status
        if path.endswith(PYTHON) and not path.startswith(LEDGER_DIRS):
            paths.append(path)
    paths = sorted(set(paths))
    committed = CodeIndex(revision=index.revision, scope=Scope(revision=index.revision, paths=paths))
    committed.blocks = [b for b in index.blocks if b.path in paths]
    working = CodeIndex(revision="working tree", scope=Scope(revision="working tree", paths=paths))
    for path in paths:
        file = root / path
        if not file.is_file():
            continue
        try:
            scan = parse_python(path, decode(file.read_bytes()))
        except (OSError, SyntaxError, UnicodeDecodeError, LookupError):
            continue
        working.blocks += scan.blocks
    validate(working, index.claims)
    return compare_indexes(committed, working), paths, working
