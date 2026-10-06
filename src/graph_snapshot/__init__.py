"""graph-snapshot: the design graph at one revision, drawn as one page.

consistency-belief says whether a design follows, component-belief whether the built thing works,
stamp-monitor whether the evidence is still current. None of them shows the whole graph a person
reasons about: every component, the theory it rests on, each claim's proof tree, and the gaps
between the three declaration files. This package joins them at one commit and draws that.

It holds no belief and writes no ledger (DEF-snapshot). Every proof state it shows is computed by
consistency-belief's own Context at the same commit; it adds only the edges between the files and
the gaps the join makes visible. It reads no evidence record: contracts appear by name, and
whether their evidence holds is component-belief's to say.
"""

from __future__ import annotations

from pathlib import Path

from .page import write
from .snapshot import NoRevision, summary, take


def take_snapshot(root: Path, focus: str | None = None) -> str:
    """Take a snapshot of the project at `root`, write its page, and say what it shows."""
    try:
        snap = take(root)
    except NoRevision as exc:
        return f"graph snapshot: {exc}"
    if focus and focus not in snap["nodes"]:
        note = f"focus {focus!r} is not in the graph at {snap['revision']}; the page opens on its default"
        focus = None
    else:
        note = ""
    written = write(root, snap, focus)
    lines = summary(snap)
    if note:
        lines.append(note)
    lines.append(written)
    return "\n".join(lines)
