"""code_links: tagged code regions and the theory nodes they relate to.

A shared library, not a server. It reads tracked source at one revision, finds the regions
marked with `# tdlp:begin` / `# tdlp:end` or declared by a docstring (`Implements: BRN-x`), the
relations each declares to a node in consistency.yaml, and the ids named in comments and
docstrings; and it says, for each link, whether its latest review -- a ledger record bound to a
commit, or the pins an older header carries -- still matches the code and the claim. The servers decide what to
show: stamp-monitor reports, consistency-belief supplies what a claim pin must be. Nothing here
changes a proof state, an evidence record, a declaration or a policy, and nothing here writes.

A link is a declared relationship, not a proof: `implements` means its author asserts the
correspondence, and an aligned review means someone said they read this code against this
claim, at that commit. Neither establishes conformance.
"""

from __future__ import annotations

from .impact import BlockChange, Changes, compare_indexes
from .index import build_index, resolve_revision, scan_worktree
from .model import (CONFORMANCE_KINDS, ERROR, GRAMMAR_VERSION, LEGACY_GRAMMAR, OBSERVATION, RELATION_KINDS,
                    REVIEW, Block, ClaimRef, CodeIndex, Diagnostic, Mention, Relation, Scope, display)
from .parser import parse_python
from .validation import (ALIGNED, BODY_CHANGED, CLAIM_RESTATED, EXPLANATORY, INVALID_BLOCK, REVIEW_FAILED,
                         UNKNOWN_CLAIM, UNPINNED, UNREVIEWED, header_lines, link_state, review_call, review_of)

__all__ = [
    "ALIGNED", "BODY_CHANGED", "CLAIM_RESTATED", "CONFORMANCE_KINDS", "ERROR", "EXPLANATORY", "GRAMMAR_VERSION",
    "INVALID_BLOCK", "LEGACY_GRAMMAR", "OBSERVATION", "RELATION_KINDS", "REVIEW", "REVIEW_FAILED",
    "UNKNOWN_CLAIM", "UNPINNED", "UNREVIEWED",
    "Block", "BlockChange", "Changes", "ClaimRef", "CodeIndex", "Diagnostic", "Mention",
    "Relation", "Scope", "build_index", "compare_indexes", "display", "header_lines",
    "link_state", "parse_python", "resolve_revision", "review_call", "review_of", "scan_worktree",
]
