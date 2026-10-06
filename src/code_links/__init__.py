"""code_links: tagged code regions and the theory nodes they relate to.

A shared library, not a server. It reads tracked source at one revision, finds the regions
marked with `# tdlp:begin` / `# tdlp:end`, the relations each declares to a node in
consistency.yaml, and the ids named in comments and docstrings; and it says, for each link,
whether the pins written into it still match the code and the claim. The servers decide what to
show: stamp-monitor reports, consistency-belief supplies what a claim pin must be. Nothing here
changes a proof state, an evidence record, a declaration or a policy, and nothing here writes.

A link is a declared relationship, not a proof: `implements` means its author asserts the
correspondence, and an aligned pin means someone said they reviewed it against this code and
this claim. Neither establishes conformance.
"""

from __future__ import annotations

from .impact import BlockChange, Changes, compare_indexes
from .index import build_index, resolve_revision, scan_worktree
from .model import (CONFORMANCE_KINDS, ERROR, GRAMMAR_VERSION, OBSERVATION, RELATION_KINDS, REVIEW,
                    Block, ClaimRef, CodeIndex, Diagnostic, Mention, Relation, Scope, display)
from .parser import parse_python
from .validation import (ALIGNED, BODY_CHANGED, CLAIM_RESTATED, EXPLANATORY, INVALID_BLOCK,
                         UNKNOWN_CLAIM, UNPINNED, header_lines, link_state)

__all__ = [
    "ALIGNED", "BODY_CHANGED", "CLAIM_RESTATED", "CONFORMANCE_KINDS", "ERROR", "EXPLANATORY", "GRAMMAR_VERSION",
    "INVALID_BLOCK", "OBSERVATION", "RELATION_KINDS", "REVIEW", "UNKNOWN_CLAIM", "UNPINNED",
    "Block", "BlockChange", "Changes", "ClaimRef", "CodeIndex", "Diagnostic", "Mention",
    "Relation", "Scope", "build_index", "compare_indexes", "display", "header_lines",
    "link_state", "parse_python", "resolve_revision", "scan_worktree",
]
