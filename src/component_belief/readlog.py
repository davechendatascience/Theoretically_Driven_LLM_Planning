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
import re
from pathlib import Path

HOOK = '''"""Written by component-belief: record what this process opens, under the project root."""
import atexit, os, sys

_ROOT = os.environ.get("BELIEF_READ_ROOT", "")
_OUT = os.environ.get("BELIEF_READS", "")
_seen = set()


_WRITES = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _writes(mode, flags):
    """A file the run writes is its output, not something it needed."""
    if isinstance(mode, str):
        return any(c in mode for c in "wax+")
    return isinstance(flags, int) and bool(flags & _WRITES)


def _audit(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        if _writes(args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None):
            return
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


def _chain():
    """Run the sitecustomize this one shadows. Python imports only the first on the path, so
    without this an environment that relies on its own (coverage, a conda activation) silently
    loses it for every instrumented run."""
    import importlib.machinery, importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    rest = [p for p in sys.path if os.path.abspath(p or os.curdir) != here]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", rest)
    if spec is None or spec.loader is None:
        return
    try:
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    except Exception as exc:   # site.py reports a failing sitecustomize and carries on; so do we
        sys.stderr.write(f"Error in sitecustomize {spec.origin}: {exc!r}\\n")


if _ROOT and _OUT:
    sys.addaudithook(_audit)
    atexit.register(_flush)

_chain()
'''


def instrument(env: dict[str, str], root: Path, log: Path,
               hook_dir: Path | None = None) -> tuple[dict[str, str], Path]:
    """Return env with the read hook installed, and the hook directory the command must see.

    The hook goes in the ledger's cache, not beside the run's artifacts: the artifacts directory
    is checked in, and a generated sitecustomize landing there becomes repository source -- which
    is how the project's own lint gate came to be checking it.
    """
    hook_dir = hook_dir or (log.parent.parent.parent / "cache" / "readhook")
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "sitecustomize.py").write_text(HOOK, encoding="utf-8")
    log.write_text("", encoding="utf-8")

    out = dict(env)
    out["BELIEF_READ_ROOT"] = str(root.resolve())
    out["BELIEF_READS"] = str(log)
    existing = out.get("PYTHONPATH", "")
    out["PYTHONPATH"] = f"{hook_dir}{os.pathsep}{existing}" if existing else str(hook_dir)
    return out, hook_dir


def weave(command: str, hook_dir: Path) -> str:
    """Keep the hook on PYTHONPATH through a command that sets PYTHONPATH itself.

    A declared command of the form `env PYTHONPATH=third_party:. python ...` replaces the
    environment the runner prepared, and the hook silently records nothing -- which reads exactly
    like a run that opened no files. Each assignment in the command gets the hook directory
    prepended instead, the same rewriting the runner already does for $OUT.
    """
    hook = str(hook_dir)

    def _prepend(match: "re.Match[str]") -> str:
        quote, value = match.group("q") or "", match.group("v")
        if hook in value:
            return match.group(0)
        return f"PYTHONPATH={quote}{hook}{os.pathsep}{value}{quote}"

    return _ASSIGNMENT.sub(_prepend, command)


_ASSIGNMENT = re.compile(r"PYTHONPATH=(?P<q>['\"]?)(?P<v>[^'\"\s]*)(?P=q)")


#: Not the project's own files: the interpreter's environment, its caches, and the ledger itself.
#: A run opens hundreds of these and they say nothing about what the repository needs, so leaving
#: them in would crowd out the handful of paths the question is actually about.
ENVIRONMENT = ("__pycache__/", "site-packages/", "dist-packages/", "node_modules/",
               ".git/", ".belief/", ".stamps/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/")


def _is_environment(rel: str) -> bool:
    head = rel.split("/", 1)[0]
    if head.startswith((".venv", "venv", "env-")) or head in ("site-packages", "node_modules"):
        return True
    return any(part in rel for part in ENVIRONMENT) or rel.endswith("sitecustomize.py")


def harvest(root: Path, log: Path, limit: int = 400) -> list[str]:
    """The distinct project-relative paths the run opened, the environment's own files aside.

    A virtualenv's library, the bytecode caches and the ledger's own directory are dropped: the
    question this answers is which of the project's files a run needed, and an interpreter reading
    its own standard library is not evidence about that.
    """
    if not log.exists():
        return []
    base = str(root.resolve())
    seen: dict[str, None] = {}
    for line in log.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line.startswith(base):
            continue
        # posix form: everything downstream -- git paths, stamps, the environment filter -- uses `/`
        rel = Path(os.path.relpath(line, base)).as_posix()
        if _is_environment(rel):
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
