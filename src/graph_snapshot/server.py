"""MCP server -- one tool.

A server's tool schemas are standing context in every session, so there is one: it takes the
snapshot, writes the page and says what the page shows. It registers nothing that records, amends
or decides; there is no path from here into either ledger.
"""

from __future__ import annotations

from pathlib import Path

from component_belief.project import project_root as resolve_root
from mcp.server.fastmcp import FastMCP

from . import take_snapshot

INSTRUCTIONS = """\
The design graph at one revision, drawn as one page a person can read: every component, the theory
it rests on, each claim's proof tree, and the gaps between consistency.yaml, belief.yaml and
goals.yaml.

snapshot(focus) resolves HEAD to one commit, reads the declarations committed there and the proof
state consistency-belief computes for each lemma and branch, and writes .graph-snapshot/snapshot.html.
It reads no evidence and records nothing: a snapshot is a picture, not a verdict, and it does not
update. Take one when a person wants to see the design, or after a change to the theory.

Open the page in a browser. To share it, publish that file as an Artifact only when the person
asks -- it carries their design.
"""

mcp = FastMCP("graph-snapshot", instructions=INSTRUCTIONS)


def project_root() -> Path:
    return resolve_root("GRAPH_SNAPSHOT_ROOT", "BELIEF_PROJECT_ROOT")


@mcp.tool()
def snapshot(focus: str | None = None) -> str:
    """Take a snapshot of the design graph at HEAD and write it as one page.

    focus: the id the page opens on -- a component, interface, branch, lemma, axiom, definition or
           goal. Without it, the page opens on the first component a declared branch governs.

    Returns the revision, the state counts, the issues and gaps, and where the page was written.
    """
    return take_snapshot(project_root(), focus)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
