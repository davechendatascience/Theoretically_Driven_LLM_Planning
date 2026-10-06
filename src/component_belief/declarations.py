"""Declarations: components, interfaces, contracts, tests, priors, policies.

These live in a checked-in `belief.yaml` rather than behind tools, because they
change rarely and need human review (10.5). The server reads them from **git
HEAD, not the working tree** — so an agent editing the file changes nothing
until a human commits. That is the whole approval gate, and it costs no tools
and no roundtrips.

Validation runs once on load and is reported through `status`; it never raises
into a tool call, because a half-valid declaration file should still let you
see what is wrong with it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from .expr import ExprError, looks_like_implementation_detail, referenced_names
from .ids import content_hash

DECLARATION_FILE = "belief.yaml"
#: The declarations the human owns: goals, the interfaces between them, and what measures each.
#: Loaded from git HEAD beside belief.yaml, which the agent writes; see goals.py for the guard.
GOALS_FILE = "goals.yaml"


@dataclass(frozen=True)
class Issue:
    code: str
    subject: str
    message: str

    def render(self) -> str:
        return f"{self.code} {self.subject}: {self.message}"


FAILURE_MODE_KEYS = ("id", "observable", "observed_by", "case")


@dataclass
class Component:
    id: str
    purpose: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    testable_capability: str = ""
    failure_modes: list[dict[str, Any]] = field(default_factory=list)
    remediation: str = ""
    code: list[str] = field(default_factory=list)
    goal: str = ""                  # the GOL- this component serves, if goals.yaml declares one

    @property
    def implemented(self) -> bool:
        """A component with no code is a planned one: declared, designed against, not built.

        The distinction is what lets the design ledger tell a component whose design was never
        declared (prune it or declare it) from one whose design runs ahead of its code.
        """
        return bool(self.code)


@dataclass
class Interface:
    id: str
    producer: str = ""
    consumer: str = ""
    semantics: str = ""
    units: str = ""
    frame: str = ""
    timing: dict[str, Any] = field(default_factory=dict)
    producer_guarantees: list[str] = field(default_factory=list)
    consumer_assumptions: list[str] = field(default_factory=list)


@dataclass
class Goal:
    """An outcome the human wants, and the contract that says when it is met."""
    id: str
    outcome: str = ""
    measure: str = ""


@dataclass
class GoalInterface:
    """What one goal's system hands another, and the contract that checks the hand-over."""
    id: str
    from_goal: str = ""
    to_goal: str = ""
    hands_over: str = ""
    measure: str = ""


CONTRACT_KINDS = ("rate", "gate")


@dataclass
class Contract:
    id: str
    subject: str = ""
    claim_type: str = "capability"
    kind: str = "rate"              # rate: a pass rate with an interval | gate: the latest run passes or fails
    scores: str = ""                # the consistency-belief definition this rule measures, if any
    metrics: list[dict[str, Any]] = field(default_factory=list)
    acceptance: dict[str, Any] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)
    conditions: list[dict[str, Any]] = field(default_factory=list)
    compatibility_key: list[str] = field(default_factory=list)
    evaluable_by: list[str] = field(default_factory=list)
    sufficiency: dict[str, Any] = field(default_factory=dict)

    @property
    def rule(self) -> str:
        return str(self.acceptance.get("rule", ""))

    @property
    def target_rate(self) -> float:
        """Pass-rate threshold the posterior interval is compared against.

        The acceptance rule decides whether a single *trial* passed; the belief
        is over the rate. Those are different thresholds and the design doc
        only specified the first, so this fills the gap with an explicit,
        overridable field rather than an implicit 0.5.
        """
        return float(self.acceptance.get("target_rate", 0.9))

    @property
    def n_min(self) -> int:
        return int(self.sufficiency.get("n_min", 8))

    @property
    def max_ci_width(self) -> float:
        return float(self.sufficiency.get("max_ci_width", 0.35))


@dataclass
class Test:
    id: str
    layer: str = "component"
    targets: list[str] = field(default_factory=list)
    run: str = ""
    reads: list[str] = field(default_factory=list)   # inputs a non-Python child opens; the audit
    #                                                  hook records the rest by itself
    metrics: list[str] = field(default_factory=list)
    capture: list[str] = field(default_factory=list)
    mandatory: bool = False
    cost: float = 1.0
    timeout_s: int = 900
    same_as: list[str] = field(default_factory=list)  # earlier versions mapped to this one (3.5)

    def measures_as(self, ref: str) -> bool:
        """Whether a trial recorded under `ref` is evidence from this test as it stands: this
        version, or an earlier one the declaration maps to it explicitly -- an edit that left the
        procedure the same, said so where the reviewer of the edit reads it."""
        version = ref.rsplit("@", 1)[-1]
        return version == self.version or version in {v.rsplit("@", 1)[-1] for v in self.same_as}

    @property
    def version(self) -> str:
        """Derived from the command and metric spec (3.5), so editing a test
        mints a new version without anyone remembering to bump it."""
        return content_hash({"run": self.run, "metrics": sorted(self.metrics)}, 8)

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


@dataclass
class Prior:
    contract: str
    alpha: float = 1.0
    beta: float = 1.0
    rationale: str = ""

    @property
    def id(self) -> str:
        return f"PRI-{self.contract}"


@dataclass
class Policy:
    id: str
    criteria: list[dict[str, Any]] = field(default_factory=list)
    weights: dict[str, float] | None = None


@dataclass
class Declarations:
    components: dict[str, Component] = field(default_factory=dict)
    interfaces: dict[str, Interface] = field(default_factory=dict)
    contracts: dict[str, Contract] = field(default_factory=dict)
    tests: dict[str, Test] = field(default_factory=dict)
    priors: dict[str, Prior] = field(default_factory=dict)
    policies: dict[str, Policy] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)   # roots holding generated, untracked output
    goals: dict[str, Goal] = field(default_factory=dict)
    goal_interfaces: dict[str, GoalInterface] = field(default_factory=dict)
    goal_owned: set[str] = field(default_factory=set)   # contract, test and policy ids from goals.yaml
    goals_blob: str = ""            # goals.yaml's blob at HEAD, when it is committed
    issues: list[Issue] = field(default_factory=list)
    source: str = "none"            # git-HEAD | none
    pending: bool = False           # working tree differs from HEAD
    raw_present: bool = False

    def issues_for(self, subject: str) -> list[Issue]:
        return [i for i in self.issues if i.subject == subject]

    def is_scorable(self, contract_id: str) -> bool:
        """A contract accepts evidence only if nothing fatal was found."""
        fatal = {"NOT_EVALUABLE", "CAPABILITY_REFERENCES_IMPLEMENTATION", "UNKNOWN_REF"}
        return contract_id in self.contracts and not any(
            i.code in fatal for i in self.issues_for(contract_id)
        )

    def active_components(self) -> dict[str, Component]:
        dropped = {i.subject for i in self.issues if i.code == "NOT_A_NODE"}
        return {k: v for k, v in self.components.items() if k not in dropped}

    def tests_for(self, contract_id: str) -> list[Test]:
        contract = self.contracts.get(contract_id)
        if not contract:
            return []
        return [self.tests[t] for t in contract.evaluable_by if t in self.tests]

    def contracts_for_subject(self, subject_id: str) -> list[Contract]:
        return [c for c in self.contracts.values() if c.subject == subject_id]

    def components_for_path(self, path: str) -> list[str]:
        """Which components claim this file (by exact path or by a glob they declare)."""
        return sorted(
            cid for cid, comp in self.components.items()
            if any(path == entry or fnmatch(path, entry) for entry in comp.code)
        )

    def failure_mode_observers(self) -> dict[tuple[str, str], list[str]]:
        """Each declared failure mode, by (component, failure mode id), and the declared contracts
        it names in `observed_by:` -- the risk register's link from what can go wrong to what
        would see it. A failure mode with none is one nothing is declared to watch."""
        out: dict[tuple[str, str], list[str]] = {}
        for cid, comp in self.components.items():
            for fm in comp.failure_modes:
                if not isinstance(fm, dict) or not fm.get("id"):
                    continue
                named = fm.get("observed_by") or []
                named = [named] if isinstance(named, str) else [str(n) for n in named]
                out[(cid, str(fm["id"]))] = [n for n in named if n in self.contracts]
        return out

    def subject_declared(self, subject_id: str) -> bool:
        return any(subject_id in nodes for nodes in
                   (self.components, self.interfaces, self.goals, self.goal_interfaces))

    def components_of_subject(self, subject_id: str) -> list[str]:
        """The components a subject's evidence rests on: a component itself; both ends of an
        interface; every component that names a goal; both goals' components for the interface
        between them. A change to any of them can change what the evidence measured."""
        if subject_id in self.components:
            return [subject_id]
        iface = self.interfaces.get(subject_id)
        if iface is not None:
            return [c for c in (iface.producer, iface.consumer) if c in self.components]
        if subject_id in self.goals:
            return sorted(cid for cid, comp in self.components.items() if comp.goal == subject_id)
        between = self.goal_interfaces.get(subject_id)
        if between is not None:
            return sorted(set(self.components_of_subject(between.from_goal))
                          | set(self.components_of_subject(between.to_goal)))
        return []

    def code_paths_for_subject(self, subject_id: str) -> list[str]:
        """The code a contract's evidence measured: the claims of every component it rests on."""
        return [p for cid in self.components_of_subject(subject_id) for p in self.components[cid].code]

    def goal_policy_gap(self, policy_id: str) -> str | None:
        """Why a decision under this policy is not covered by the human's commit of goals.yaml,
        or None when it is: the policy, every contract it names and every test measuring those
        are declared in goals.yaml, so none of them is something the agent wrote."""
        if policy_id not in self.goal_owned:
            return f"{policy_id} is declared in {DECLARATION_FILE}, not {GOALS_FILE}"
        for criterion in self.policies[policy_id].criteria:
            contract_id = criterion.get("slice")
            if not contract_id:
                continue
            if contract_id not in self.goal_owned:
                return f"its criterion {contract_id} is declared in {DECLARATION_FILE}"
            for tid in self.contracts[contract_id].evaluable_by if contract_id in self.contracts else []:
                if tid not in self.goal_owned:
                    return f"{contract_id} is measured by {tid}, declared in {DECLARATION_FILE}"
        return None


def _git_show(root: Path, ref: str, name: str = DECLARATION_FILE) -> str | None:
    try:
        out = subprocess.run(
            ["git", "show", f"{ref}:{name}"],
            cwd=root, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def load(root: Path, revision: str = "HEAD") -> Declarations:
    """Load declarations from git HEAD; report working-tree drift as pending.

    `revision` pins the commit for a reader that must take every declaration from one commit
    while HEAD may move under it (graph-snapshot passes the sha it resolved); the servers read HEAD.
    """
    committed = _git_show(root, revision)
    worktree_path = root / DECLARATION_FILE
    worktree = worktree_path.read_text(encoding="utf-8") if worktree_path.exists() else None

    if committed is None:
        decl = Declarations(source="none", raw_present=worktree is not None)
        if worktree is not None:
            decl.issues.append(Issue(
                "UNCOMMITTED", DECLARATION_FILE,
                "belief.yaml exists but is not committed; declarations take effect "
                "only from git HEAD, so nothing is scorable yet",
            ))
        return decl

    goals_committed = _git_show(root, revision, GOALS_FILE)
    goals_path = root / GOALS_FILE
    goals_worktree = goals_path.read_text(encoding="utf-8") if goals_path.exists() else None

    decl = _parse(committed, goals_committed)
    decl.source = "git-HEAD"
    decl.raw_present = True
    if goals_committed is not None:
        decl.goals_blob = (_git_rev(root, f"{revision}:{GOALS_FILE}") or "")[:12]
    elif goals_worktree is not None:
        decl.issues.append(Issue(
            "UNCOMMITTED", GOALS_FILE,
            "goals.yaml exists but is not committed; your goals take effect only once you commit it",
        ))
    for name, head, tree in ((DECLARATION_FILE, committed, worktree),
                             (GOALS_FILE, goals_committed, goals_worktree)):
        if head is not None and tree is not None and tree != head:
            decl.pending = True
            decl.issues.append(Issue(
                "PENDING", name, "working tree differs from HEAD; the uncommitted edits are not in effect",
            ))
    decl.issues.extend(check_code_paths(decl, root))
    return decl


def _git_rev(root: Path, spec: str) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", spec], cwd=root, capture_output=True, text=True,
                             timeout=15, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def check_code_paths(decl: Declarations, root: Path) -> list[Issue]:
    """A component's `code:` entries name files in this repository. Advisory: a path that has
    moved or been pruned is worth reporting, never a reason to stop scoring the component."""
    issues: list[Issue] = []
    for cid, comp in decl.components.items():
        for entry in comp.code:
            if any(ch in entry for ch in "*?["):
                if not list(root.glob(entry)):
                    issues.append(Issue("MISSING_CODE_PATH", cid, f"code pattern {entry!r} matches no file"))
            elif not (root / entry).exists():
                issues.append(Issue("MISSING_CODE_PATH", cid, f"code path {entry!r} does not exist"))
    return issues


def _parse(text: str, goals_text: str | None = None) -> Declarations:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return Declarations(issues=[Issue("MALFORMED", DECLARATION_FILE, str(exc))])
    if not isinstance(data, dict):
        return Declarations(issues=[Issue("MALFORMED", DECLARATION_FILE, "top level must be a mapping")])

    decl = Declarations()
    for raw in data.get("components") or []:
        c = Component(**_only(raw, Component))
        decl.components[c.id] = c
    for raw in data.get("interfaces") or []:
        i = Interface(**_only(raw, Interface))
        decl.interfaces[i.id] = i
    for raw in data.get("contracts") or []:
        c = Contract(**_only(raw, Contract))
        decl.contracts[c.id] = c
    for raw in data.get("tests") or []:
        t = Test(**_only(raw, Test))
        decl.tests[t.id] = t
    for raw in data.get("priors") or []:
        p = Prior(**_only(raw, Prior))
        decl.priors[p.contract] = p
    for raw in data.get("policies") or []:
        p = Policy(**_only(raw, Policy))
        decl.policies[p.id] = p
    decl.artifacts = [str(a) for a in (data.get("artifacts") or [])]

    if goals_text is not None:
        _merge_goals(decl, goals_text)
    decl.issues.extend(validate(decl))
    return decl


def _merge_goals(decl: Declarations, text: str) -> None:
    """goals.yaml joins the same declarations, and every id it declares is marked as the human's.

    Its contracts, tests and policies use belief.yaml's schema; its policies come first, so the
    goals are what a decision, a diagnosis and a plan answer to unless another policy is named.
    """
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        decl.issues.append(Issue("MALFORMED", GOALS_FILE, str(exc)))
        return
    if not isinstance(data, dict):
        decl.issues.append(Issue("MALFORMED", GOALS_FILE, "top level must be a mapping"))
        return
    for raw in data.get("goals") or []:
        goal = Goal(**_only(raw, Goal))
        decl.goals[goal.id] = goal
    for raw in data.get("interfaces") or []:
        raw = raw or {}
        between = GoalInterface(id=str(raw.get("id", "")), from_goal=str(raw.get("from", "")),
                                to_goal=str(raw.get("to", "")), hands_over=str(raw.get("hands_over", "")),
                                measure=str(raw.get("measure", "")))
        if between.id in decl.interfaces:
            decl.issues.append(Issue("DUPLICATE_ID", between.id,
                                     f"declared in both {DECLARATION_FILE} and {GOALS_FILE}"))
        decl.goal_interfaces[between.id] = between
    policies: dict[str, Policy] = {}
    for section, cls, target in (("contracts", Contract, decl.contracts), ("tests", Test, decl.tests),
                                 ("policies", Policy, policies)):
        for raw in data.get(section) or []:
            node = cls(**_only(raw, cls))
            if node.id in target or (section == "policies" and node.id in decl.policies):
                decl.issues.append(Issue("DUPLICATE_ID", node.id,
                                         f"declared in both {DECLARATION_FILE} and {GOALS_FILE}; "
                                         f"the one in {GOALS_FILE} is in effect"))
            target[node.id] = node
            decl.goal_owned.add(node.id)
    decl.policies = {**policies, **{k: v for k, v in decl.policies.items() if k not in policies}}


def _only(raw: dict[str, Any], cls: type) -> dict[str, Any]:
    """Drop unknown keys rather than crashing — an unrecognised field is a
    typo to report, not a reason to refuse the whole file."""
    allowed = set(cls.__dataclass_fields__)
    return {k: v for k, v in (raw or {}).items() if k in allowed}


def validate(decl: Declarations) -> list[Issue]:
    issues: list[Issue] = []

    for cid, comp in decl.components.items():
        missing = [
            name for name, value in (
                ("testable_capability", comp.testable_capability),
                ("failure_modes", comp.failure_modes),
                ("remediation", comp.remediation),
            ) if not value
        ]
        if missing:
            # Rule 1.4 — the only defence against graphing every function in
            # the repo. A node earns its place with a testable capability, a
            # failure mode, and somewhere to go when it fails.
            issues.append(Issue(
                "NOT_A_NODE", cid,
                f"missing {', '.join(missing)}; not an independently testable node",
            ))

    for iid, iface in decl.interfaces.items():
        for role, ref in (("producer", iface.producer), ("consumer", iface.consumer)):
            if ref and ref not in decl.components:
                issues.append(Issue("UNKNOWN_REF", iid, f"{role} {ref} is not a declared component"))
        unbacked = [a for a in iface.consumer_assumptions if a not in iface.producer_guarantees]
        for assumption in unbacked:
            # Advisory, not fatal: the most common integration bug, free to
            # find by set difference (2.5).
            issues.append(Issue("UNBACKED_ASSUMPTION", iid, f"consumer assumes {assumption!r}, producer does not guarantee it"))

    for cid, comp in decl.components.items():
        for fm in comp.failure_modes:
            stray = sorted(k for k, v in fm.items() if v is None and k not in FAILURE_MODE_KEYS) \
                if isinstance(fm, dict) else []
            if stray:
                # `{id: FM-x, observable: a, b}` parses as observable "a" plus a key "b": the
                # sentence was cut at its comma, and nothing else says so
                issues.append(Issue("SPLIT_VALUE", cid, f"failure mode {fm.get('id')} has stray "
                                    f"key(s) {stray}: an unquoted comma in a flow mapping cut a "
                                    "value short; quote it"))
            named = fm.get("observed_by") if isinstance(fm, dict) else None
            for ref in ([named] if isinstance(named, str) else named or []):
                if ref not in decl.contracts:
                    issues.append(Issue("UNKNOWN_REF", cid, f"failure mode {fm.get('id')} is "
                                        f"observed_by {ref}, which is not a declared contract"))

    for cid, comp in decl.components.items():
        if comp.goal and comp.goal not in decl.goals:
            issues.append(Issue("UNKNOWN_GOAL", cid, f"serves {comp.goal}, which {GOALS_FILE} does not declare"))

    issues.extend(_validate_goals(decl))

    for cid, contract in decl.contracts.items():
        if not decl.subject_declared(contract.subject):
            issues.append(Issue("UNKNOWN_REF", cid, f"subject {contract.subject} is not declared"))
        if contract.kind not in CONTRACT_KINDS:
            issues.append(Issue("BAD_KIND", cid, f"kind {contract.kind!r} must be one of {', '.join(CONTRACT_KINDS)}"))

        rule = contract.rule
        if not rule:
            issues.append(Issue("NOT_EVALUABLE", cid, "acceptance.rule is empty"))
            continue
        try:
            needed = referenced_names(rule)
        except ExprError as exc:
            issues.append(Issue("NOT_EVALUABLE", cid, str(exc)))
            continue

        if contract.claim_type == "capability":
            offender = looks_like_implementation_detail(rule)
            if offender:
                issues.append(Issue(
                    "CAPABILITY_REFERENCES_IMPLEMENTATION", cid,
                    f"capability claim references implementation detail {offender!r}",
                ))

        if not contract.evaluable_by:
            issues.append(Issue("NOT_EVALUABLE", cid, "evaluable_by is empty; nothing can measure this contract"))
            continue

        produced: set[str] = set()
        for tid in contract.evaluable_by:
            test = decl.tests.get(tid)
            if test is None:
                issues.append(Issue("NOT_EVALUABLE", cid, f"evaluable_by names unknown test {tid}"))
                continue
            produced |= set(test.metrics)
        unmet = needed - produced
        if unmet:
            issues.append(Issue(
                "NOT_EVALUABLE", cid,
                f"acceptance rule needs {sorted(unmet)} which no registered test produces",
            ))

        for cond in contract.conditions:
            when = cond.get("when")
            if when:
                try:
                    referenced_names(when)
                except ExprError as exc:
                    issues.append(Issue("BAD_CONDITION", cid, f"bucket {cond.get('id')}: {exc}"))

    for tid, test in decl.tests.items():
        if test.layer not in ("component", "interface", "e2e"):
            issues.append(Issue("BAD_LAYER", tid, f"layer {test.layer!r} must be component, interface, or e2e"))
        if not test.run:
            issues.append(Issue("NOT_RUNNABLE", tid, "no run command"))
        for target in test.targets:
            if not decl.subject_declared(target):
                issues.append(Issue("UNKNOWN_REF", tid, f"target {target} is not declared"))

    for contract_id in decl.priors:
        if contract_id not in decl.contracts:
            issues.append(Issue("UNKNOWN_REF", f"PRI-{contract_id}", f"prior names unknown contract {contract_id}"))

    for pid, policy in decl.policies.items():
        for crit in policy.criteria:
            slice_ref = crit.get("slice")
            if slice_ref and slice_ref not in decl.contracts:
                issues.append(Issue("UNKNOWN_REF", pid, f"criterion names unknown contract {slice_ref}"))

    return issues


def _validate_goals(decl: Declarations) -> list[Issue]:
    """What the human declares must be measured by what the human declares.

    A goal whose measure lives in belief.yaml, or is scored by a test declared there, can be met
    by an edit the agent makes; so can a goals policy that names such a contract. Each is reported
    against the goal, where the human reads it. Advisory, like every declaration issue that is
    not about scoring evidence: the decision rule is where it bites (decide asks for an approver).
    """
    issues: list[Issue] = []
    measured = [(gid, g.measure, "UNMEASURED_GOAL") for gid, g in decl.goals.items()]
    measured += [(iid, i.measure, "UNMEASURED_INTERFACE") for iid, i in decl.goal_interfaces.items()]
    for owner, measure, code in measured:
        if not measure:
            issues.append(Issue(code, owner, "declares no measure; nothing says when it is met"))
        elif measure not in decl.contracts:
            issues.append(Issue(code, owner, f"measure {measure} is not a declared contract"))
        elif measure not in decl.goal_owned:
            issues.append(Issue(code, owner, f"measure {measure} is declared in {DECLARATION_FILE}, "
                                f"which the agent writes; declare it in {GOALS_FILE}"))
        elif decl.contracts[measure].subject != owner:
            issues.append(Issue(code, owner, f"measure {measure} is a contract on "
                                f"{decl.contracts[measure].subject}, not on {owner}"))
    for iid, between in decl.goal_interfaces.items():
        for end in (between.from_goal, between.to_goal):
            if end not in decl.goals:
                issues.append(Issue("UNKNOWN_REF", iid, f"end {end or '(none)'} is not a declared goal"))
    for cid in sorted(decl.goal_owned & set(decl.contracts)):
        outside = [t for t in decl.contracts[cid].evaluable_by if t not in decl.goal_owned]
        if outside:
            issues.append(Issue("MEASURE_OUTSIDE_GOALS", cid, f"measured by {', '.join(outside)}, "
                                f"declared in {DECLARATION_FILE}: the agent could change how "
                                "your goal is measured"))
    for pid in sorted(decl.goal_owned & set(decl.policies)):
        gap = decl.goal_policy_gap(pid)
        if gap:
            issues.append(Issue("POLICY_OUTSIDE_GOALS", pid, gap))
    return issues
