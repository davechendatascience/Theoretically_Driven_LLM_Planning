"""Declarations: axioms, definitions, lemmas, branches, and consistency policies.

Like component-belief, these live in a checked-in consistency.yaml rather than
behind arbitrary tool writes. The server reads them from git HEAD, not the
working tree — so modifying an axiom or branch changes nothing until committed.
Uncommitted edits show as PENDING in status.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .ids import content_hash

DECLARATION_FILE = "consistency.yaml"

_EVIDENCE_ID = re.compile(r"\b(?:CMP|CTR)-[A-Za-z0-9][A-Za-z0-9-]*\b")
COMPONENT_ID = re.compile(r"CMP-[A-Za-z0-9][A-Za-z0-9-]*")
#: An interface (belief.yaml's between components, goals.yaml's between goals) or a goal: the two
#: subjects above a component a design claim can govern.
BOUNDARY_ID = re.compile(r"(?:IFC|GOL)-[A-Za-z0-9][A-Za-z0-9_-]*")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?")

#: The states a policy criterion may require of a cited contract (`evidence:`), as
#: component-belief reports them.
EVIDENCE_STATES = ("supported", "contested", "refuted", "insufficient_evidence", "stale")


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
    goal: Any = None               # the goal(s) in goals.yaml whose requirement this states

    @property
    def ref(self) -> str:
        return f"{self.id}@{content_hash(self.statement, 8)}"

    @property
    def goals(self) -> list[str]:
        """A requirement traces to the need it serves. Not part of a fingerprint: retracing an
        axiom to another goal restates nothing a verifier judged."""
        if not self.goal:
            return []
        return [str(g) for g in self.goal] if isinstance(self.goal, list) else [str(self.goal)]


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
class ComponentImport:
    """A component this file's designs govern, listed at the top of consistency.yaml.

    The id is the whole content: belief.yaml owns the component -- its purpose, code paths,
    contracts and measurements -- and this list says which of them the design ledger speaks for,
    the way an import names what a module uses. The note is for the reader.
    """

    id: str
    note: str = ""


@dataclass
class Policy:
    id: str
    criteria: list[dict[str, Any]] = field(default_factory=list)
    weights: dict[str, float] | None = None


@dataclass
class ComponentRef:
    """A component as component-belief declares it, seen from the design side.

    consistency.yaml says why a design follows; belief.yaml says what is built and whether it
    works. A branch's `subject` is the join between them: it names the component the design
    governs. A component with no `code:` is planned -- declared and designed against before it
    is written -- which is a different thing from a component whose design was never declared.
    """

    id: str
    purpose: str = ""
    code: list[str] = field(default_factory=list)
    contracts: list[str] = field(default_factory=list)
    rules: dict[str, tuple[str, str]] = field(default_factory=dict)   # contract -> (rule, scores)

    @property
    def implemented(self) -> bool:
        return bool(self.code)


@dataclass
class BoundaryRef:
    """An interface or a goal, seen from the design side: a subject a design claim may govern
    besides a component. An interface's design says why a producer's guarantees suffice for its
    consumer; a goal's says why the system meets the outcome. Either is owned where it is declared
    -- belief.yaml for the interfaces between components, goals.yaml for goals and the interfaces
    between them -- and imported here, like a component."""

    id: str
    kind: str                      # interface | goal
    about: str = ""                # semantics, hands_over or outcome
    declared_in: str = ""          # belief.yaml | goals.yaml
    contracts: list[str] = field(default_factory=list)


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
    components: dict[str, ComponentRef] = field(default_factory=dict)
    components_source: str = "none"  # git-HEAD | none | unavailable
    governs: dict[str, ComponentImport] = field(default_factory=dict)
    boundaries: dict[str, BoundaryRef] = field(default_factory=dict)

    @property
    def goal_ids(self) -> set[str]:
        return {bid for bid, b in self.boundaries.items() if b.kind == "goal"}

    def subject_known(self, subject: str) -> bool:
        return subject in self.components or subject in self.boundaries

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

    def branches_for_subject(self, component_id: str) -> list[str]:
        return sorted(bid for bid, b in self.branches.items() if b.subject == component_id)


def _git_show(root: Path, ref: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "show", f"{ref}:{DECLARATION_FILE}"],
            cwd=root, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def git_head(root: Path) -> str:
    """The revision the declarations were read from -- what a decision names as its baseline."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def load(root: Path, revision: str = "HEAD") -> Declarations:
    """Load declarations from git HEAD; report working-tree drift as pending. `revision` pins
    the commit for a reader that must take every declaration from one commit (graph-snapshot)."""
    committed = _git_show(root, revision)
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
    decl.components, decl.boundaries, decl.components_source = import_subjects(root, revision)
    decl.issues.extend(validate_links(decl))
    decl.issues.extend(check_scored_definitions(decl))
    return decl


def load_components(root: Path) -> tuple[dict[str, ComponentRef], str]:
    components, _boundaries, source = import_subjects(root)
    return components, source


def import_subjects(root: Path, revision: str = "HEAD",
                    ) -> tuple[dict[str, ComponentRef], dict[str, BoundaryRef], str]:
    """Read what component-belief declares in the same repository, at git HEAD: the components,
    and the interfaces and goals a design may govern beside them.

    One-way and read-only: the design ledger needs to know which subjects exist and which are
    built, and it asks the ledger that owns that fact. A project with no belief.yaml keeps working
    -- the subject of a branch is then simply unchecked.
    """
    try:
        from component_belief import declarations as components
    except ImportError:                                     # component-belief not installed
        return {}, {}, "unavailable"

    decl = components.load(root, revision)
    if decl.source == "none":
        return {}, {}, "none"
    boundaries: dict[str, BoundaryRef] = {}
    for iid, iface in decl.interfaces.items():
        boundaries[iid] = BoundaryRef(iid, "interface", iface.semantics, "belief.yaml")
    for iid, between in decl.goal_interfaces.items():
        boundaries[iid] = BoundaryRef(iid, "interface", between.hands_over, "goals.yaml")
    for gid, goal in decl.goals.items():
        boundaries[gid] = BoundaryRef(gid, "goal", goal.outcome, "goals.yaml")
    for ref in boundaries.values():
        ref.contracts = sorted(c.id for c in decl.contracts_for_subject(ref.id))
    refs = {
        cid: ComponentRef(
            id=cid,
            purpose=comp.purpose,
            code=list(comp.code),
            contracts=sorted(c.id for c in decl.contracts_for_subject(cid)),
            rules={c.id: (c.rule, c.scores) for c in decl.contracts_for_subject(cid)},
        )
        for cid, comp in decl.components.items()
    }
    return refs, boundaries, decl.source


def check_scored_definitions(decl: Declarations) -> list[Issue]:
    """A contract may name the definition its acceptance rule measures. Where it does, the
    definition must exist and the rule's thresholds must be the definition's.

    This is the drift a number invites once it lives in two files: the definition is restated and
    the rule that scores it keeps the old bar, or the other way round, and both ledgers go on
    reporting confidently. Structural constants 0 and 1 are ignored -- they are how a rule says
    'none' and 'all', not thresholds.
    """
    issues: list[Issue] = []
    for ref in decl.components.values():
        for cid, (rule, scores) in sorted(ref.rules.items()):
            if not scores:
                continue
            defn = decl.definitions.get(scores)
            if defn is None:
                issues.append(Issue(
                    "UNKNOWN_DEFINITION", cid,
                    f"scores {scores!r}, which consistency.yaml does not declare",
                ))
                continue
            in_rule = {float(n) for n in _NUMBER.findall(rule or "")} - {0.0, 1.0}
            in_def = {float(n) for n in _NUMBER.findall(defn.meaning or "")}
            drifted = sorted(in_rule - in_def)
            if drifted:
                issues.append(Issue(
                    "THRESHOLD_DRIFT", cid,
                    f"rule {rule!r} scores {scores} at {drifted}, which that definition does not "
                    "state -- one of the two was restated and the other was not",
                ))
    return issues


def validate_links(decl: Declarations) -> list[Issue]:
    """Check each branch against the component ledger: the subject names a component, and every
    component, contract or test id the derivation_rule cites is one that exists.

    Advisory, never fatal. A design may be declared before belief.yaml catches up; what must not
    happen silently is a branch governing a component that no longer exists.
    """
    if not decl.components:
        return []
    issues: list[Issue] = []
    known = set(decl.components) | {c for ref in decl.components.values() for c in ref.contracts}
    known |= set(decl.boundaries) | {c for ref in decl.boundaries.values() for c in ref.contracts}
    if decl.goal_ids:
        for aid, axm in decl.axioms.items():
            for goal in axm.goals:
                if goal not in decl.goal_ids:
                    issues.append(Issue("UNKNOWN_GOAL", aid,
                                        f"states a requirement of {goal}, which goals.yaml does not declare"))

    for cid in decl.governs:
        if cid not in decl.components:
            issues.append(Issue(
                "REMOVED_COMPONENT", cid,
                "listed under components: here, but belief.yaml does not declare it -- the component "
                "was removed or renamed; drop it from the list, or re-declare it there",
            ))
    for bid, brn in decl.branches.items():
        if decl.governs and brn.subject in decl.components and brn.subject not in decl.governs:
            issues.append(Issue(
                "UNLISTED_SUBJECT", bid,
                f"subject {brn.subject!r} is a declared component but is missing from this file's "
                "components: list; add it, so the file says which components its designs govern",
            ))
        if not brn.subject:
            issues.append(Issue("UNATTACHED_SUBJECT", bid, "branch declares no subject component"))
        elif brn.subject in decl.boundaries:
            pass                     # an interface or a goal: a subject above a component
        elif BOUNDARY_ID.fullmatch(brn.subject):
            issues.append(Issue(
                "REMOVED_SUBJECT", bid,
                f"subject {brn.subject!r} is not declared in belief.yaml or goals.yaml any more -- "
                "the interface or goal was removed or renamed, so this design governs nothing; "
                "repoint it, re-declare it, or prune the branch",
            ))
        elif brn.subject not in decl.components:
            if COMPONENT_ID.fullmatch(brn.subject):
                # It was a component id once. Say so loudly: the design now governs nothing.
                issues.append(Issue(
                    "REMOVED_SUBJECT", bid,
                    f"subject {brn.subject!r} is not declared in belief.yaml any more -- the "
                    "component was removed or renamed, so this design governs nothing; repoint it, "
                    "re-declare the component, or prune the branch",
                ))
            else:
                issues.append(Issue(
                    "UNATTACHED_SUBJECT", bid,
                    f"subject {brn.subject!r} is prose, not a component, interface or goal id; name "
                    "what this design governs, or declare it in belief.yaml (a component with no "
                    "code: is planned)",
                ))
        cited = {m for m in _EVIDENCE_ID.findall(brn.derivation_rule or "")}
        for ref in sorted(cited - known):
            issues.append(Issue(
                "UNKNOWN_EVIDENCE", bid,
                f"derivation_rule cites {ref!r}, which belief.yaml does not declare",
            ))
        if not any(ref.startswith("CTR-") for ref in cited):
            issues.append(Issue(
                "MISSING_EVIDENCE", bid,
                "derivation_rule names no CTR- contract; a design claim states what must hold and "
                "cites where the measurement lives, and is worth nothing while nothing measures it",
            ))
    return issues


_BELIEF_RANK = {"unsupported": 0, "refuted": 0, "stale": 1, "contested": 2,
                "insufficient_evidence": 3, "insufficient": 3, "supported": 4}


def _contract_summaries(root: Path) -> dict[str, tuple[str, str]] | None:
    """Each contract's weakest belief slice from component-belief: (state, phrase).

    Read on demand, because it means loading the evidence ledger. None when that ledger is not
    readable from here (component-belief not installed, or a store this server cannot parse);
    a contract with no slice at all reads as "no evidence".
    """
    try:
        from component_belief.declarations import load as load_components
        from component_belief.model import compute_slices
        from component_belief.staleness import CodeStaleness
        from component_belief.store import Store
    except ImportError:
        return None
    try:
        decl = load_components(root)
        if not decl.contracts:
            return {}
        slices = compute_slices(decl, Store(root).effective_trials(), staleness=CodeStaleness(root))
    except Exception:                                   # a ledger this server does not own
        return None

    out: dict[str, tuple[int, str, str]] = {}
    counts: dict[str, int] = {}
    for sl in slices:
        counts[sl.contract_id] = counts.get(sl.contract_id, 0) + 1
        rank = _BELIEF_RANK.get(sl.state, 3)
        seen = out.get(sl.contract_id)
        if seen is None or rank < seen[0]:
            # the weakest slice, named: a contract supported at one revision and thin at another
            # reads as thin, and a reader must be able to see which one that is
            n = sl.n_stale if sl.state == "stale" else sl.n_valid
            out[sl.contract_id] = (rank, sl.state, f"{sl.state} n={n} [{sl.condition_label()}]")
    summary = {cid: (state, text if counts[cid] == 1 else f"{text}, weakest of {counts[cid]} slices")
               for cid, (_, state, text) in out.items()}
    for cid in decl.contracts:
        summary.setdefault(cid, ("no evidence", "no evidence"))
    return summary


def contract_beliefs(root: Path) -> dict[str, str]:
    """Each contract's belief state from component-belief, as one short phrase per contract.
    A design claim that cites a contract with no evidence is argued and unmeasured, and the
    coverage view says so."""
    summaries = _contract_summaries(root)
    return {} if summaries is None else {cid: phrase for cid, (_state, phrase) in summaries.items()}


def contract_states(root: Path) -> dict[str, str] | None:
    """Each contract's weakest belief state, for the joint gate in decide(); None when the
    component ledger cannot be read, which decide() reports rather than treating as supported."""
    summaries = _contract_summaries(root)
    return None if summaries is None else {cid: state for cid, (state, _phrase) in summaries.items()}


def _parse(text: str) -> Declarations:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return Declarations(issues=[Issue("MALFORMED", DECLARATION_FILE, str(exc))])
    if not isinstance(data, dict):
        return Declarations(issues=[Issue("MALFORMED", DECLARATION_FILE, "top level must be a mapping")])

    decl = Declarations()
    for a in _entries(data, "axioms", Axiom, decl.issues):
        decl.axioms[a.id] = a
    for d in _entries(data, "definitions", Definition, decl.issues):
        decl.definitions[d.id] = d
    for l in _entries(data, "lemmas", Lemma, decl.issues):
        decl.lemmas[l.id] = l
    for b in _entries(data, "branches", Branch, decl.issues):
        decl.branches[b.id] = b
    for raw in data.get("components") or []:
        if not isinstance(raw, (str, dict)) or (isinstance(raw, dict) and not raw.get("id")):
            decl.issues.append(Issue("MALFORMED", DECLARATION_FILE, "an entry under components: is "
                                     f"neither an id nor a mapping with one: {str(raw)[:80]!r}"))
            continue
        c = ComponentImport(id=raw, note="") if isinstance(raw, str) else ComponentImport(**_only(raw, ComponentImport))
        decl.governs[c.id] = c
        stray = sorted(k for k, v in raw.items() if v is None and k not in ComponentImport.__dataclass_fields__) \
            if isinstance(raw, dict) else []
        if stray:
            decl.issues.append(Issue("SPLIT_VALUE", c.id, f"stray key(s) {stray}: an unquoted comma "
                                     "in a flow mapping cut the note short; quote it"))
    for p in _entries(data, "policies", Policy, decl.issues):
        decl.policies[p.id] = p

    decl.issues.extend(validate(decl))
    return decl


def _entries(data: dict[str, Any], section: str, cls: type, issues: list[Issue]) -> list[Any]:
    """A section's entries, built; one that is not a mapping with an id, or does not fit the
    schema, is reported (MALFORMED) and left out rather than raising into every tool. Neither
    kind could take a place in the premise graph, so this drops nothing a build could admit."""
    out = []
    for raw in data.get(section) or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            issues.append(Issue("MALFORMED", DECLARATION_FILE, f"an entry under {section}: is not a "
                                f"mapping with an id, and is left out: {str(raw)[:80]!r}"))
            continue
        try:
            node = cls(**_only(raw, cls))
        except (TypeError, ValueError) as exc:
            issues.append(Issue("MALFORMED", str(raw["id"]), f"does not fit the {section} schema: {exc}"))
            continue
        criteria = getattr(node, "criteria", None)
        if isinstance(criteria, list) and not all(isinstance(c, dict) for c in criteria):
            issues.append(Issue("MALFORMED", node.id, "a criterion that is not a mapping is left out"))
            node.criteria = [c for c in criteria if isinstance(c, dict)]
        out.append(node)
    return out


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
            required = crit.get("evidence")
            if required and required not in EVIDENCE_STATES:
                issues.append(Issue(
                    "BAD_CRITERION", pid,
                    f"evidence must be one of {', '.join(EVIDENCE_STATES)}, not {required!r}"))

    return issues
