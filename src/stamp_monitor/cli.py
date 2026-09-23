"""The same three reports from a shell -- for git hooks, CI, and Claude Code hooks.

    stamp-monitor impact [--base REV] [--no-worktree]
    stamp-monitor audit
    stamp-monitor workflow

Exits 1 when audit or workflow has a [block] finding, so a hook can stop on it; impact always
exits 0, because a change touching things is not an error.
"""

from __future__ import annotations

import argparse
import sys

from . import BLOCK, render_findings
from .audit import audit
from .impact import impact, render
from .server import project_root
from .workflow import workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stamp-monitor")
    sub = parser.add_subparsers(dest="command", required=True)
    p_impact = sub.add_parser("impact")
    p_impact.add_argument("--base", default="HEAD~1")
    p_impact.add_argument("--no-worktree", action="store_true")
    sub.add_parser("audit")
    sub.add_parser("workflow")
    args = parser.parse_args(argv)

    root = project_root()
    if args.command == "impact":
        print(render(impact(root, args.base, not args.no_worktree)))
        return 0
    findings = audit(root) if args.command == "audit" else workflow(root)
    empty = "clean" if args.command == "audit" else "nothing to report"
    print(render_findings(args.command, findings, empty))
    return 1 if any(f.severity == BLOCK for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
