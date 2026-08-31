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
from pathlib import Path
from typing import Any

import yaml

from .expr import ExprError, looks_like_implementation_detail, referenced_names
from .ids import content_hash

DECLARATION_FILE = "belief.yaml"


@dataclass(frozen=True)
class Issue:
    code: str
    subject: str
    message: str

    def render(self) -> str:
        return f"{self.code} {self.subject}: {self.message}"


@dataclass
class Component:
    id: str
    purpose: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    testable_capability: str = ""
    failure_modes: list[dict[str, Any]] = field(default_factory=list)
    remediation: str = ""


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
class Contract:
    id: str
    subject: str = ""
    claim_type: str = "capability"
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
    metrics: list[str] = field(default_factory=list)
    capture: list[str] = field(default_factory=list)
    mandatory: bool = False
    cost: float = 1.0
    timeout_s: int = 900

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
                "belief.yaml exists but is not committed; declarations take effect "
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

    decl.issues.extend(validate(decl))
    return decl


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

    for cid, contract in decl.contracts.items():
        if contract.subject not in decl.components and contract.subject not in decl.interfaces:
            issues.append(Issue("UNKNOWN_REF", cid, f"subject {contract.subject} is not declared"))

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
            if target not in decl.components and target not in decl.interfaces:
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
