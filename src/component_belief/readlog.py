"""Which files a run actually opened, recorded by the run itself.

The ledger knows the command a run executed, so it can see the paths written on that command line.
It cannot see the cache a program opened because a config pointed at it, and that is exactly the
artifact nobody can decide to delete: tens of gigabytes whose only claim to life is that somebody
remembers training on them.

A Python process can say so itself. `sys.addaudithook` sees every `open` before it happens, so a
hook installed through `sitecustomize` records each path under the project root and writes them at
exit. Subprocesses inherit it through the environment, and a run that opens nothing writes an
empty log rather than nothing at all, which is the difference between "read no artifacts" and "was
never instrumented".

What it does not see: files opened by a non-Python child (a shell script's `cp`, a CUDA kernel
loading weights through its own loader). Those still need a declared `reads:` on the test. The
hook narrows the gap; it does not close it, and the view says which of the two it is reporting.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HOOK = '''"""Written by component-belief: record what this process opens, under the project root."""
import atexit, os, sys

_ROOT = os.environ.get("BELIEF_READ_ROOT", "")
_OUT = os.environ.get("BELIEF_READS", "")
_seen = set()


def _audit(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        try:
            path = os.path.realpath(os.fspath(args[0]))
        except (TypeError, ValueError):
            return
        if _ROOT and path.startswith(_ROOT):
            _seen.add(path)


def _flush():
    try:
        with open(_OUT, "a", encoding="utf-8") as fh:
            for path in sorted(_seen):
                fh.write(path + "\\n")
    except OSError:
        pass


if _ROOT and _OUT:
    sys.addaudithook(_audit)
    atexit.register(_flush)

try:                              # keep any sitecustomize the environment already had
    import sitecustomize_original  # noqa: F401
except ImportError:
    pass
'''


def instrument(env: dict[str, str], root: Path, log: Path) -> dict[str, str]:
    """Return env with the read hook installed, the log emptied and ready to append to."""
    hook_dir = log.parent / "readhook"
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "sitecustomize.py").write_text(HOOK, encoding="utf-8")
    log.write_text("", encoding="utf-8")

    out = dict(env)
    out["BELIEF_READ_ROOT"] = str(root.resolve())
    out["BELIEF_READS"] = str(log)
    existing = out.get("PYTHONPATH", "")
    out["PYTHONPATH"] = f"{hook_dir}{os.pathsep}{existing}" if existing else str(hook_dir)
    return out


def harvest(root: Path, log: Path, limit: int = 400) -> list[str]:
    """The distinct project-relative paths the run opened, newest-first by nothing in particular.

    Paths under the ledger's own directory are dropped: a run reading its own artifact directory
    says nothing about what the project needs.
    """
    if not log.exists():
        return []
    base = str(root.resolve())
    seen: dict[str, None] = {}
    for line in log.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line.startswith(base):
            continue
        rel = os.path.relpath(line, base)
        if rel.startswith((".belief/", ".git/")) or rel.endswith("sitecustomize.py"):
            continue
        seen.setdefault(rel, None)
    return list(seen)[:limit]


def write(artifact_dir: Path, reads: list[str]) -> None:
    (artifact_dir / "reads.json").write_text(json.dumps(reads, indent=1), encoding="utf-8")


def read(artifact_dir: Path) -> list[str]:
    path = artifact_dir / "reads.json"
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return []
