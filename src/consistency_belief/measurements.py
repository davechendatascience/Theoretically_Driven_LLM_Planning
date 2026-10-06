"""Cited measurements: the contracts a branch's derivation rule names, and whether each was read
against the claim as it now stands (DEF-cited-measurement).

A branch is proven of its statement, and the contract it cites measures something. Nothing else
held the two together: a claim restated to say more kept citing the contract that measured the
old one, and the gate read that contract as supported. A pin written after the contract id --
`evidence: CTR-x@7c41d0e2` -- records the branch's claim digest when someone read the contract's
acceptance rule and tests against the claim, the same digest a code link's claim pin records.
Restate the claim, or anything it rests on, and the digest moves on without the pin: the
measurement reads unreviewed until someone reads it again and writes the new pin.

The pin sits in the derivation rule, which no fingerprint covers, so writing one restates
nothing and sets no trial aside. Nothing here is a proof state or an evidence state; it is a
report, and like a code link it blocks nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .declarations import Declarations
from .graph import ProofDAG
from .links import claim_pin

#: A contract id in a derivation rule, with the pin written directly after it, if any.
CITED = re.compile(r"\b(CTR-[A-Za-z0-9][A-Za-z0-9_-]*)(?:@([0-9a-f]{8})\b)?")

REVIEWED, UNPINNED, NOT_REVIEWED = "reviewed", "unpinned", "not reviewed"


@dataclass(frozen=True)
class CitedMeasurement:
    """A (declared branch, contract) pair. `expected` is the branch's claim digest now, or None
    when the branch is not in the declared graph and so has no digest (DEF-cited-measurement)."""

    branch: str
    contract: str
    pin: str | None
    expected: str | None

    @property
    def state(self) -> str:
        if self.expected is None:
            return NOT_REVIEWED
        if self.pin is None:
            return UNPINNED
        return REVIEWED if self.pin == self.expected else NOT_REVIEWED

    @property
    def why(self) -> str:
        if self.expected is None:
            return (f"{self.branch} is not in the declared graph -- a premise it cites is unknown, "
                    "staged only, or on a cycle -- so it has no claim digest a pin could equal")
        if self.pin is None:
            return "never read against the claim and pinned"
        if self.pin != self.expected:
            return f"pinned @{self.pin}; the claim, or a node it rests on, was restated since"
        return "reviewed against the claim as it stands"

    @property
    def fix(self) -> str:
        if self.expected is None:
            return f"repair {self.branch}'s premises; until it is in the declared graph no pin can review it"
        return (f"once {self.contract}'s acceptance rule and tests are read against {self.branch} "
                f"as it now stands, write evidence: {self.contract}@{self.expected} in its derivation rule")


def cited_measurements(decl: Declarations) -> list[CitedMeasurement]:
    """Every contract each declared branch cites, judged against the declared graph -- the one
    DEF-code-link names: the declarations at the head revision, no staged proposal."""
    dag = ProofDAG.from_declarations(decl)
    out: list[CitedMeasurement] = []
    for bid in sorted(decl.branches):
        # a branch the declared graph does not admit has no claim digest: its measurements are
        # reported, not reviewed -- never skipped
        expected = claim_pin(dag, bid) if bid in dag.nodes else None
        pins: dict[str, str | None] = {}
        for m in CITED.finditer(decl.branches[bid].derivation_rule or ""):
            pins[m.group(1)] = pins.get(m.group(1)) or m.group(2)   # any mention may carry it
        out += [CitedMeasurement(bid, cid, pin, expected) for cid, pin in sorted(pins.items())]
    return out


def uncited_contracts(decl: Declarations) -> list[str]:
    """Contracts declared beside the design -- on a component, an interface or a goal -- that no
    branch's derivation rule names: something is measured, and no design says why it matters."""
    declared = {c for ref in decl.components.values() for c in ref.contracts}
    declared |= {c for ref in decl.boundaries.values() for c in ref.contracts}
    cited = {m.group(1) for b in decl.branches.values() for m in CITED.finditer(b.derivation_rule or "")}
    return sorted(declared - cited)


#: What an uncited contract measures, in the order a reader acts on them: a component's contract
#: no design cites is the one to look at; a goal's measure is explained by the goal's outcome.
KINDS = ("component", "interface", "goal")


def uncited_by_kind(decl: Declarations) -> dict[str, list[str]]:
    """uncited_contracts, grouped by the subject each contract measures."""
    kind: dict[str, str] = {}
    for ref in decl.components.values():
        kind.update(dict.fromkeys(ref.contracts, "component"))
    for ref in decl.boundaries.values():
        kind.update(dict.fromkeys(ref.contracts, ref.kind))
    groups: dict[str, list[str]] = {k: [] for k in KINDS}
    for cid in uncited_contracts(decl):
        groups.setdefault(kind.get(cid, "component"), []).append(cid)
    return groups


def adopted(found: list[CitedMeasurement]) -> bool:
    """A project that pins one cited measurement has opted in, and its unpinned ones are worth
    listing; one that pins none still hears of every pin gone stale -- of which it has none."""
    return any(c.pin for c in found)
