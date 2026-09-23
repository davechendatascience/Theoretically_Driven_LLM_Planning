"""What a change touches, across both ledgers.

The chain is declared end to end, so it is followed rather than guessed:

  changed path -> component whose `code:` claims it, test that names it (run line or `reads:`)
               -> contracts on that component or measured by that test
               -> design branches whose subject is the component or whose rule cites the contract
               -> policies whose criteria name the contract or the branch

Everything on the chain is *possibly* affected. Whether a contract's evidence actually went stale
is a separate, measured fact: the slice state at HEAD, computed by component-belief's own code. The
report keeps the two apart, because "this might matter" and "this no longer counts" call for
different actions.

Uncommitted edits are reported but stale nothing: evidence is compared against HEAD, as every
declaration is.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from component_belief.declarations import load as load_components
from component_belief.model import STATE_STALE, compute_slices
from component_belief.staleness import CodeStaleness, LEDGER_DIRS, matches, named_paths
from component_belief.store import Store

_CONTRACT = re.compile(r"\bCTR-[A-Za-z0-9][A-Za-z0-9-]*\b")


def _git_lines(root: Path, *args: str) -> list[str] | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=120,
                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.split("\0") if p]


def _ours(path: str) -> bool:
    return not path.startswith(tuple(d + "/" for d in LEDGER_DIRS))


@dataclass
class Impact:
    base: str
    committed: list[str] = field(default_factory=list)
    uncommitted: list[str] = field(default_factory=list)
    components: dict[str, list[str]] = field(default_factory=dict)   # component -> paths
    tests: dict[str, list[str]] = field(default_factory=dict)        # test -> paths
    contracts: dict[str, str] = field(default_factory=dict)          # contract -> state at HEAD
    branches: dict[str, list[str]] = field(default_factory=dict)     # branch -> why
    policies: dict[str, list[str]] = field(default_factory=dict)     # policy -> what it gates
    reruns: list[str] = field(default_factory=list)
    unclaimed: list[str] = field(default_factory=list)
    error: str = ""


def impact(root: Path, base: str = "HEAD~1", worktree: bool = True) -> Impact:
    result = Impact(base=base)
    committed = _git_lines(root, "diff", "--name-only", "-z", base, "HEAD")
    if committed is None:
        result.error = f"git does not know {base!r} here; pass a revision in this history"
        return result
    result.committed = sorted(p for p in committed if _ours(p))
    if worktree:
        edited = _git_lines(root, "diff", "--name-only", "-z", "HEAD") or []
        result.uncommitted = sorted(p for p in edited if _ours(p) and p not in result.committed)
    changed = result.committed + result.uncommitted
    if not changed:
        return result

    decl = load_components(root)
    for cid, comp in sorted(decl.components.items()):
        hit = [p for p in changed if any(matches(p, e) for e in comp.code)]
        if hit:
            result.components[cid] = hit
    for tid, test in sorted(decl.tests.items()):
        hit = named_paths(test.run, test.reads, set(changed))
        if hit:
            result.tests[tid] = hit
    claimed = {p for paths in result.components.values() for p in paths}
    named = {p for paths in result.tests.values() for p in paths}
    result.unclaimed = [p for p in changed if p not in claimed | named]

    affected = sorted(
        c.id for c in decl.contracts.values()
        if c.subject in result.components or set(c.evaluable_by) & set(result.tests))
    slices = compute_slices(decl, Store(root).effective_trials(), affected,
                            staleness=CodeStaleness(root))
    for cid in affected:
        states = sorted({s.state for s in slices if s.contract_id == cid})
        result.contracts[cid] = "/".join(states) or "no evidence"

    # A stale contract needs its test run again; so does one whose files changed only in the
    # working tree -- it will go stale the moment those edits are committed.
    uncommitted_hits = {p for p in result.uncommitted if p in claimed | named}
    for cid in affected:
        contract = decl.contracts[cid]
        touched_now = (any(p in uncommitted_hits for p in result.components.get(contract.subject, []))
                       or any(p in uncommitted_hits for t in contract.evaluable_by
                              for p in result.tests.get(t, [])))
        if STATE_STALE in result.contracts[cid] or touched_now:
            result.reruns += [t for t in contract.evaluable_by if t not in result.reruns]

    for pid, policy in sorted(decl.policies.items()):
        gated = [c["slice"] for c in policy.criteria if c.get("slice") in result.contracts]
        mandatory = {t.id for t in decl.tests.values() if t.mandatory}
        if any("safety_gates" in c for c in policy.criteria) and any(
                set(decl.contracts[c].evaluable_by) & mandatory for c in result.contracts):
            gated.append("safety_gates")
        if gated:
            result.policies[pid] = gated

    _design(root, result)
    return result


def _design(root: Path, result: Impact) -> None:
    """The consistency ledger's side of the chain, when this project has one."""
    if not (root / "consistency.yaml").exists():
        return
    try:
        from consistency_belief.declarations import load as load_design
    except ImportError:
        return
    design = load_design(root)
    for bid, branch in sorted(design.branches.items()):
        why = []
        if branch.subject in result.components:
            why.append(f"governs {branch.subject}")
        cited = sorted(set(_CONTRACT.findall(branch.derivation_rule)) & set(result.contracts))
        why += [f"cites {c}" for c in cited]
        if why:
            result.branches[bid] = why
    for pid, policy in sorted(design.policies.items()):
        gated = [c["target"] for c in policy.criteria if c.get("target") in result.branches]
        if gated:
            result.policies[pid] = gated


def render(result: Impact) -> str:
    if result.error:
        return result.error
    if not (result.committed or result.uncommitted):
        return f"impact {result.base}..HEAD: no changes outside the ledgers"
    lines = [f"impact {result.base}..HEAD: {len(result.committed)} committed, "
             f"{len(result.uncommitted)} uncommitted path(s)"]
    if result.components or result.tests:
        lines += ["", "touched:"]
        for cid, paths in result.components.items():
            lines.append(f"  {cid} <- {_short(paths)}")
        for tid, paths in result.tests.items():
            lines.append(f"  {tid} (test) <- {_short(paths)}")
    if result.contracts:
        lines += ["", "contracts (state at HEAD -- stale is measured, the rest only possibly affected):"]
        lines += [f"  {cid} [{state}]" for cid, state in result.contracts.items()]
    if result.branches:
        lines += ["", "design branches possibly affected:"]
        lines += [f"  {bid} ({', '.join(why)})" for bid, why in result.branches.items()]
    if result.policies:
        lines += ["", "policies that may need re-evaluation:"]
        lines += [f"  {pid} <- {', '.join(g)}" for pid, g in result.policies.items()]
    if result.uncommitted:
        lines += ["", f"uncommitted (stale nothing until committed): {_short(result.uncommitted)}"]
    if result.unclaimed:
        lines += ["", f"claimed by no component and named by no test: {_short(result.unclaimed)}"]
    lines += ["", "next: " + ("; ".join(f"run_test {t}" for t in result.reruns)
                              if result.reruns else "nothing to re-run")]
    return "\n".join(lines)


def _short(paths: list[str], n: int = 4) -> str:
    return ", ".join(paths[:n]) + (f" +{len(paths) - n} more" if len(paths) > n else "")


def as_dict(result: Impact) -> dict[str, Any]:
    return dict(result.__dict__)
