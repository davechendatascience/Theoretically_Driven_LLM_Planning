"""MCP server -- four read-only tools.

Note what is absent: no tool registers an artifact, records an event, or writes anywhere. Stamps
come from the runner that executed the command; this server only reads them, beside the ledgers
and git. Tool schemas are standing context in every session, so there are four, not seven: the
fourth, `links`, is the map between tagged code and the claims it relates to, which lives here
and not in consistency-belief because the verifier holds consistency-belief's `status` and must
never be handed a path to the implementation.
"""

from __future__ import annotations

from pathlib import Path

from component_belief.project import project_root as resolve_root
from mcp.server.fastmcp import FastMCP

from . import render_findings
from .audit import audit as run_audit
from .impact import impact as run_impact
from .impact import render as render_impact
from .links import report as links_report
from .workflow import workflow as run_workflow

INSTRUCTIONS = """\
A read-only monitor over the component-belief and consistency-belief ledgers.

impact(base)  -- what a change touches: components, contracts (stale at HEAD or only possibly
                 affected), design branches, policies, and the tests to re-run.
audit()       -- whether the recorded evidence is still what was recorded.
workflow()    -- patterns in the history that route around the loop.
links()       -- tagged code regions (# tdlp:begin CODE-...) and the claims they relate to: each
                 link aligned or not, with why, and the header lines to write once reviewed.

It reports; it never decides, repairs, or re-runs. Call impact after a commit, and audit and
workflow before asking for a decision. A [block] finding is for the human, not for you to fix
by amending evidence.
"""

mcp = FastMCP("stamp-monitor", instructions=INSTRUCTIONS)


def project_root() -> Path:
    return resolve_root("STAMP_MONITOR_ROOT", "BELIEF_PROJECT_ROOT")


@mcp.tool()
def impact(base: str = "HEAD~1", worktree: bool = True) -> str:
    """Trace what changed between `base` and HEAD through both ledgers.

    base:     any revision in this history (default: the previous commit).
    worktree: also list uncommitted edits. They stale nothing until committed, but they name the
              tests that will need re-running when they are.
    """
    return render_impact(run_impact(project_root(), base, worktree))


@mcp.tool()
def audit() -> str:
    """Re-verify the ledgers mechanically: every line parses, ids are unique, amendments and
    decisions cite records that exist, stamps and artifacts still match their recorded digests,
    and the declarations in effect are the committed ones."""
    return render_findings("audit", run_audit(project_root()), "clean")


@mcp.tool()
def workflow() -> str:
    """Check the recorded history for ways around the loop: reclassifications that only remove
    adverse results, adoptions without a human approver, decisions resting on dirty-tree
    evidence, and adoptions whose evidence has since gone stale."""
    return render_findings("workflow", run_workflow(project_root()), "nothing to report")


@mcp.tool()
def links(subject: str | None = None) -> str:
    """Tagged code regions and the claims they relate to, at HEAD.

    Each link is aligned, or reported with why: never pinned, its code changed since it was
    reviewed (with the revision to diff against), its claim -- or a premise upstream of it --
    restated since, or its claim gone. Mentions of a claim id in a comment or docstring that no
    region tracks are listed, and so are those that name nothing.

    subject: a CODE- region id, a claim id (LMA-, BRN-, DEF-, AXM-), or a file path; omit for all.
    """
    return links_report(project_root(), subject)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
