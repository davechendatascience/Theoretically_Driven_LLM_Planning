"""The same three reports from a shell -- for git hooks, CI, and Claude Code hooks.

    stamp-monitor impact [--base REV] [--no-worktree]
    stamp-monitor audit
    stamp-monitor workflow
    stamp-monitor links [--subject ID] [--strict]

Exits 1 when audit or workflow has a [block] finding, so a hook can stop on it; impact always
exits 0, because a change touching things is not an error. links exits 0 unless --strict, and
then 1 on any broken tag, dangling mention or link that needs review -- the switch a CI job or a
pre-push hook uses to make "every tagged region was reviewed against its claim as both stand
now" a condition of landing.
"""

from __future__ import annotations

import argparse
import sys

from . import BLOCK, render_findings
from .audit import audit
from .impact import impact, render
from .links import report as links_report
from .links import scan as links_scan
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
    p_links = sub.add_parser("links")
    p_links.add_argument("--subject", default=None)
    p_links.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    root = project_root()
    if args.command == "links":
        index = links_scan(root)
        print(links_report(root, args.subject, index=index))
        if not args.strict:
            return 0
        return 1 if index is None or any(d.severity in ("error", "review") for d in index.diagnostics) else 0
    if args.command == "impact":
        print(render(impact(root, args.base, not args.no_worktree)))
        return 0
    findings = audit(root) if args.command == "audit" else workflow(root)
    empty = "clean" if args.command == "audit" else "nothing to report"
    print(render_findings(args.command, findings, empty))
    return 1 if any(f.severity == BLOCK for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
