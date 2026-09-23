"""Configuration control for evidence: a trial measured one revision, and it stops speaking for
the current one once the code it measured has changed.

consistency-belief marks a node STALE when a premise upstream is restated. This is the empirical
counterpart. Every measured trial carries the `sw_revision` the runner captured, every component
claims its `code:` paths, and one `git diff --name-only <revision> HEAD` per distinct revision
says whether any claimed path changed since. Evidence for a baseline that no longer exists must
not read as current -- and nothing here decides what to do about it: the model reports the slice
as stale, the policy refuses to adopt on it, and the plan schedules the re-run.

A component that claims no code cannot go stale this way: there is nothing to diff against.
That is one more reason to claim it.
"""

from __future__ import annotations

import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


class CodeStaleness:
    """One git call per distinct revision, cached for the life of the context."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._changed: dict[str, set[str] | None] = {}

    def changed_since(self, revision: str) -> set[str] | None:
        """Paths changed between `revision` and HEAD. None when git does not know the revision --
        a rebase or a different clone -- which is itself a fact about the evidence."""
        if revision in self._changed:
            return self._changed[revision]
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", revision, "HEAD"],
                cwd=self.root, capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.SubprocessError):
            self._changed[revision] = None
            return None
        result = None if out.returncode != 0 else {
            line.strip() for line in out.stdout.splitlines() if line.strip()}
        self._changed[revision] = result
        return result

    def stale_reason(self, code_paths: list[str], trial: dict[str, Any]) -> str | None:
        """Why this trial no longer speaks for the current revision, or None if it still does."""
        repro = trial.get("repro") or {}
        revision = str(repro.get("sw_revision") or trial.get("system_version") or "")
        if not revision or not code_paths:
            return None
        changed = self.changed_since(revision)
        if changed is None:
            return f"revision {revision} is not in this repository's history"
        hit = sorted(path for path in changed
                     if any(path == entry or fnmatch(path, entry) for entry in code_paths))
        if not hit:
            return None
        shown = ", ".join(hit[:3]) + (f" +{len(hit) - 3} more" if len(hit) > 3 else "")
        return f"{shown} changed since {revision}"
