"""Declarations: axioms, definitions, lemmas, branches, and consistency policies.

Like component-belief, these live in a checked-in consistency.yaml rather than
behind arbitrary tool writes. The server reads them from git HEAD, not the
working tree — so modifying an axiom or branch changes nothing until committed.
Uncommitted edits show as PENDING in status.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .ids import content_hash

DECLARATION_FILE = "consistency.yaml"


@dataclass(frozen=True)
class Issue:
    code: str
    subject: str
    message: str

    def render(self) -> str:
        return f"{self.code} {self.subject}: {self.message}"


@dataclass
class Axiom:
    id: str
    statement: str = ""
    domain: str = "general"
    rationale: str = ""

    @property
    def ref(self) -> str:
        return f"{self.id}@{content_hash(self.statement, 8)}"


@dataclass
class Definition:
    id: str
    term: str = ""
    meaning: str = ""


@dataclass
class Lemma:
    id: str
    statement: str = ""
    premises: list[str] = field(default_factory=list)
    derivation_rule: str = ""
    sufficiency: dict[str, Any] = field(default_factory=dict)

    @property
    def n_min(self) -> int:
        return int(self.sufficiency.get("n_min", 3))

    @property
    def min_consensus(self) -> float:
        return float(self.sufficiency.get("min_consensus", 0.8))


@dataclass
class Branch:
    id: str
    subject: str = ""
    claim_type: str = "contract"
    statement: str = ""
    premises: list[str] = field(default_factory=list)
    derivation_rule: str = ""
    sufficiency: dict[str, Any] = field(default_factory=dict)

    @property
    def n_min(self) -> int:
        return int(self.sufficiency.get("n_min", 3))

    @property
    def min_consensus(self) -> float:
        return float(self.sufficiency.get("min_consensus", 0.8))


@dataclass
class Policy:
    id: str
    criteria: list[dict[str, Any]] = field(default_factory=list)
    weights: dict[str, float] | None = None


@dataclass
class Declarations:
    axioms: dict[str, Axiom] = field(default_factory=dict)
    definitions: dict[str, Definition] = field(default_factory=dict)
    lemmas: dict[str, Lemma] = field(default_factory=dict)
    branches: dict[str, Branch] = field(default_factory=dict)
    policies: dict[str, Policy] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    source: str = "none"            # git-HEAD | none
    pending: bool = False           # working tree differs from HEAD
    raw_present: bool = False

    def issues_for(self, subject: str) -> list[Issue]:
        return [i for i in self.issues if i.subject == subject]

    def is_valid_node(self, node_id: str) -> bool:
        fatal = {"UNKNOWN_PREMISE", "CIRCULAR_DEPENDENCY", "MALFORMED_DECLARATION"}
        return not any(i.code in fatal for i in self.issues_for(node_id))

    def node(self, node_id: str) -> Axiom | Definition | Lemma | Branch | None:
        return (
            self.axioms.get(node_id)
            or self.definitions.get(node_id)
            or self.lemmas.get(node_id)
            or self.branches.get(node_id)
        )

    def all_node_ids(self) -> set[str]:
        return set(self.axioms) | set(self.definitions) | set(self.lemmas) | set(self.branches)


def _git_show(root: Path, ref: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "show", f"{ref}:{DECLARATION_FILE}"],
            cwd=root, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def load(root: Path) -> Declarations:
    """Load declarations from git HEAD; report working-tree drift as pending."""
    committed = _git_show(root, "HEAD")
    worktree_path = root / DECLARATION_FILE
    worktree = worktree_path.read_text(encoding="utf-8") if worktree_path.exists() else None

    if committed is None:
        decl = Declarations(source="none", raw_present=worktree is not None)
        if worktree is not None:
            decl.issues.append(Issue(
                "UNCOMMITTED", DECLARATION_FILE,
                "consistency.yaml exists but is not committed; declarations take effect "
                "only from git HEAD, so nothing is scorable yet",
            ))
        return decl

    decl = _parse(committed)
    decl.source = "git-HEAD"
    decl.raw_present = True
    decl.pending = worktree is not None and worktree != committed
    if decl.pending:
        decl.issues.append(Issue(
            "PENDING", DECLARATION_FILE,
            "working tree differs from HEAD; the uncommitted edits are not in effect",
        ))
    return decl


def _parse(text: str) -> Declarations:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return Declarations(issues=[Issue("MALFORMED", DECLARATION_FILE, str(exc))])
    if not isinstance(data, dict):
        return Declarations(issues=[Issue("MALFORMED", DECLARATION_FILE, "top level must be a mapping")])

    decl = Declarations()
    for raw in data.get("axioms") or []:
        a = Axiom(**_only(raw, Axiom))
        decl.axioms[a.id] = a
    for raw in data.get("definitions") or []:
        d = Definition(**_only(raw, Definition))
        decl.definitions[d.id] = d
    for raw in data.get("lemmas") or []:
        l = Lemma(**_only(raw, Lemma))
        decl.lemmas[l.id] = l
    for raw in data.get("branches") or []:
        b = Branch(**_only(raw, Branch))
        decl.branches[b.id] = b
    for raw in data.get("policies") or []:
        p = Policy(**_only(raw, Policy))
        decl.policies[p.id] = p

    decl.issues.extend(validate(decl))
    return decl


def _only(raw: dict[str, Any], cls: type) -> dict[str, Any]:
    allowed = set(cls.__dataclass_fields__)
    return {k: v for k, v in (raw or {}).items() if k in allowed}


def validate(decl: Declarations) -> list[Issue]:
    issues: list[Issue] = []
    all_ids = decl.all_node_ids()

    for aid, axm in decl.axioms.items():
        if not axm.statement:
            issues.append(Issue("EMPTY_AXIOM", aid, "axiom has an empty statement"))
        if not axm.rationale:
            issues.append(Issue("MISSING_RATIONALE", aid, "axiom lacks an explanatory rationale"))

    for did, defn in decl.definitions.items():
        if not defn.term or not defn.meaning:
            issues.append(Issue("MALFORMED_DECLARATION", did, "definition must have term and meaning"))

    dep_graph: dict[str, list[str]] = {}

    for lid, lma in decl.lemmas.items():
        if not lma.statement:
            issues.append(Issue("MALFORMED_DECLARATION", lid, "lemma has empty statement"))
        if not lma.derivation_rule:
            issues.append(Issue("MISSING_DERIVATION", lid, "lemma lacks derivation_rule"))
        if not lma.premises:
            issues.append(Issue("UNGROUNDED_DECLARATION", lid, "lemma specifies no premises"))
        for p in lma.premises:
            if p not in all_ids:
                issues.append(Issue("UNKNOWN_PREMISE", lid, f"names unknown premise {p!r}"))
        dep_graph[lid] = list(lma.premises)

    for bid, brn in decl.branches.items():
        if not brn.statement:
            issues.append(Issue("MALFORMED_DECLARATION", bid, "branch has empty statement"))
        if not brn.derivation_rule:
            issues.append(Issue("MISSING_DERIVATION", bid, "branch lacks derivation_rule"))
        if not brn.premises:
            issues.append(Issue("UNGROUNDED_DECLARATION", bid, "branch specifies no premises"))
        for p in brn.premises:
            if p not in all_ids:
                issues.append(Issue("UNKNOWN_PREMISE", bid, f"names unknown premise {p!r}"))
        dep_graph[bid] = list(brn.premises)

    # Detect cycles in declared graph
    visited: dict[str, int] = {}  # 0: visiting, 1: visited

    def has_cycle(node: str, path: list[str]) -> bool:
        visited[node] = 0
        for parent in dep_graph.get(node, []):
            if parent in visited and visited[parent] == 0:
                cycle_str = " -> ".join([*path, parent])
                issues.append(Issue("CIRCULAR_DEPENDENCY", node, f"circular dependency: {cycle_str}"))
                return True
            if parent not in visited and parent in dep_graph:
                if has_cycle(parent, [*path, parent]):
                    return True
        visited[node] = 1
        return False

    for node_id in list(dep_graph):
        if node_id not in visited:
            has_cycle(node_id, [node_id])

    for pid, pol in decl.policies.items():
        for crit in pol.criteria:
            target = crit.get("target") or crit.get("branch")
            if target and target not in all_ids:
                issues.append(Issue("UNKNOWN_TARGET", pid, f"criterion names unknown target {target!r}"))

    return issues
