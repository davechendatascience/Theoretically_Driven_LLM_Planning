"""The design ledger's side of code links: what a pin on a relation to a node must be.

A relation pin binds a review to the same thing a verification trial binds to (DEF-current-trial):
the node's fingerprint -- its statement and the premises it cites -- and the fingerprint of every
node it depends on. So "stale" has one meaning across the harness: a link goes stale exactly when
a trial of its claim would, and restating a definition three levels up reaches the code that
implements a branch resting on it, as it reaches the branch's trials.

This module is read by stamp-monitor and by audit_change. It is never part of the probe: the
verifier judges a claim from its premises, and a list of the files that implement it is exactly
what it must not be handed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from code_links import ClaimRef, CodeIndex, build_index, resolve_revision

from .declarations import DECLARATION_FILE, Declarations, _git_show, _parse, import_subjects
from .graph import ProofDAG
from .ids import content_hash

_CONTRACT = re.compile(r"\bCTR-[A-Za-z0-9][A-Za-z0-9_-]*\b")


def claim_pin(dag: ProofDAG, node_id: str) -> str:
    return content_hash({"node": dag.nodes[node_id].fingerprint(),
                         "basis": dag.basis_fingerprints(node_id)}, 8)


def _dag_at(root: Path, revision: str) -> ProofDAG | None:
    text = _git_show(root, revision)
    return None if text is None else ProofDAG.from_declarations(_parse(text) if text else Declarations())


def claim_refs(root: Path, revision: str) -> dict[str, ClaimRef] | None:
    """Every node in the premise graph at `revision`, with the pin a relation to it must carry;
    None when that revision has no consistency.yaml. Declared nodes only: a staged proposal takes
    no effect as a declaration, and a link to one would vouch for a draft. The candidate files a
    branch's coverage hint names come from belief.yaml at the same revision."""
    dag = _dag_at(root, revision)
    if dag is None:
        return None
    components, _boundaries, _source = import_subjects(root, revision)
    refs = {}
    for nid, node in dag.nodes.items():
        comp = components.get(node.subject)
        refs[nid] = ClaimRef(pin=claim_pin(dag, nid), kind=node.kind,
                             basis=frozenset(dag.ancestors(nid)), subject=node.subject,
                             candidates=tuple(comp.code) if comp else (),
                             cites=tuple(sorted(set(_CONTRACT.findall(node.derivation_rule or "")))))
    return refs


class PinHistory:
    """Explains a stale relation pin: the latest revision of consistency.yaml at which the node
    pinned that way, and which nodes were restated since -- the node itself, or which premises
    upstream."""

    LIMIT = 100

    def __init__(self, root: Path, revision: str) -> None:
        self.root, self.revision = root, revision
        self._revs: list[str] | None = None
        self._dags: dict[str, ProofDAG | None] = {}

    def _dag(self, rev: str) -> ProofDAG | None:
        if rev not in self._dags:
            self._dags[rev] = _dag_at(self.root, rev)
        return self._dags[rev]

    def _revisions(self) -> list[str]:
        if self._revs is None:
            try:
                out = subprocess.run(
                    ["git", "log", "--format=%H", f"-n{self.LIMIT}", self.revision, "--", DECLARATION_FILE],
                    cwd=self.root, capture_output=True, text=True, timeout=60,
                    stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
                self._revs = out.stdout.split() if out.returncode == 0 else []
            except (OSError, subprocess.SubprocessError):
                self._revs = []
        return self._revs

    def explain(self, node_id: str, pin: str) -> str | None:
        now = self._dag(self.revision)
        for rev in self._revisions():
            then = self._dag(rev)
            if then is None or node_id not in then.nodes or claim_pin(then, node_id) != pin:
                continue
            if now is None or node_id not in now.nodes:
                return f"pinned against {rev[:7]}"
            # A node counts on a side only where the claim depended on it there: one cited now
            # and not then is a change as much as one restated.
            was = {i: then.nodes[i].fingerprint() for i in {node_id} | then.ancestors(node_id)}
            is_ = {i: now.nodes[i].fingerprint() for i in {node_id} | now.ancestors(node_id)}
            moved = sorted(i for i in set(was) | set(is_) if was.get(i) != is_.get(i))
            own = node_id in moved
            upstream = [i for i in moved if i != node_id]
            parts = ([f"{node_id} itself"] if own else []) + (
                [f"upstream {', '.join(upstream[:5])}" + (" ..." if len(upstream) > 5 else "")]
                if upstream else [])
            return f"pinned against {rev[:7]}; restated since: {'; '.join(parts) or 'nothing it cites'}"
        return (f"no revision among the last {self.LIMIT} of {DECLARATION_FILE} gives it that pin -- "
                "it was pinned against an uncommitted draft")


def scan(root: Path, revision: str = "HEAD", *, paths: list[str] | None = None,
         explain: bool = True) -> CodeIndex | None:
    """The code links at `revision`, checked against the declarations at that same revision --
    code and claims are read from one commit, so a scan never pairs one revision's code with
    another's claims. None when git does not know the revision."""
    sha = resolve_revision(root, revision)
    if sha is None:
        return None
    claims = claim_refs(root, sha)
    return build_index(root, sha, claims, paths=paths,
                       explain_claim=PinHistory(root, sha).explain if explain and claims else None,
                       explain_body=explain)


def links_reached(index: CodeIndex, node_ids: set[str]) -> list[tuple[str, str, str]]:
    """(block id, relation kind, target) for every link to one of `node_ids`: ids only, no paths,
    so a report on a restatement can name what it unpins without pointing anyone at the source."""
    return sorted({(b.block_id, r.kind, r.target) for b in index.blocks if b.valid
                   for r in b.relations if r.target in node_ids})
