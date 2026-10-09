"""Rendering utilities for consistency-belief: ASCII proof trees, basis lines, and envelopes."""

from __future__ import annotations

from typing import Iterable

from .graph import ProofDAG
from .ids import set_hash
from .model import CONDITIONAL, PROVEN, REFUTED, OBLIGATION, STALE, UNGROUNDED, ConsistencySlice


def bullet(lines: Iterable[str], indent: int = 2) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}• {line}" for line in lines)


def basis_line(slices: Iterable[ConsistencySlice]) -> str:
    slice_list = list(slices)
    all_trials = []
    proven_count = 0
    obligation_count = 0
    refuted_count = 0
    conditional_count = 0

    for s in slice_list:
        all_trials.extend(s.trial_ids)
        if s.state == PROVEN:
            proven_count += 1
        elif s.state == REFUTED:
            refuted_count += 1
        elif s.state == CONDITIONAL:
            conditional_count += 1          # its own step needs no verifier; it waits on another
        else:
            obligation_count += 1

    handle = set_hash(all_trials)
    summary = f"proven={proven_count} obligations={obligation_count} refuted={refuted_count}"
    if conditional_count:
        summary += f" conditional={conditional_count}"
    return f"basis: verification_trials×{len(all_trials)} set={handle} · {summary}"


def envelope(body: str, basis: str) -> str:
    body = body.rstrip()
    if not basis:
        return body
    return f"{body}\n\n{basis}"


def slice_badge(s: ConsistencySlice | None) -> str:
    if s is None:
        return "[UNKNOWN]"
    badge = _state_badge(s)
    if s.certified_by:
        badge = badge[:-1] + " · LEAN]"
    return badge[:-1] + " · STAGED]" if s.staged else badge


def _state_badge(s: ConsistencySlice) -> str:
    if s.state == PROVEN:
        return f"[PROVEN {s.n_passed}/{s.n_trials}]"
    if s.state == REFUTED:
        return "[REFUTED]"
    if s.state == OBLIGATION:
        # progress toward closing it: independent trials, not raw ones
        return f"[OBLIGATION {s.n_independent}/{s.n_min}]"
    if s.state == STALE:
        return "[STALE]"
    if s.state == UNGROUNDED:
        return "[UNGROUNDED]"
    if s.state == CONDITIONAL:
        # The proof is modulo the steps beneath it that are not verified; the worst one is named.
        first, state = s.waiting_on[0] if s.waiting_on else ("?", "?")
        more = f" +{len(s.waiting_on) - 1}" if len(s.waiting_on) > 1 else ""
        return f"[CONDITIONAL {s.n_passed}/{s.n_trials} · rests on {state.upper()} {first}{more}]"
    return f"[{s.state.upper()}]"


HEADLINE_CHARS = 110


def headline(statement: str, limit: int = HEADLINE_CHARS) -> str:
    """A statement's first line, cut to fit a tree row; status(view="branches") has it in full."""
    text = " ".join(statement.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_ascii_dag(dag: ProofDAG, slices: list[ConsistencySlice]) -> str:
    """Render the proof DAG as an ASCII tree starting from root axioms."""
    slice_map = {s.target_id: s for s in slices}
    lines: list[str] = []
    roots = sorted(dag.roots())

    visited: set[str] = set()

    def print_subtree(nid: str, prefix: str, is_last: bool):
        node = dag.get(nid)
        if not node:
            return

        connector = "└── " if is_last else "├── "
        badge = "[AXIOM]" if node.kind == "axiom" else ("[DEF]" if node.kind == "definition" else slice_badge(slice_map.get(nid)))

        if nid in visited:
            # A node with several premises hangs under each of them; its statement and subtree
            # are printed once, so the tree grows with the graph, not with its paths.
            lines.append(f"{prefix}{connector}{nid} {badge} (shown above)")
            return
        lines.append(f"{prefix}{connector}{nid} {badge}: {headline(node.statement)}")
        visited.add(nid)

        children = sorted(dag.children.get(nid, set()))
        sub_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            print_subtree(child, sub_prefix, i == len(children) - 1)

    for i, root in enumerate(roots):
        node = dag.get(root)
        if not node:
            continue
        badge = "[AXIOM]" if node.kind == "axiom" else "[DEF]"
        lines.append(f"{root} {badge}: {headline(node.statement)}")
        children = sorted(dag.children.get(root, set()))
        for j, child in enumerate(children):
            print_subtree(child, "", j == len(children) - 1)
        if i < len(roots) - 1:
            lines.append("")

    return "\n".join(lines) if lines else "(empty proof DAG)"


def _badge(dag: ProofDAG, slice_map: dict[str, ConsistencySlice], nid: str) -> str:
    node = dag.get(nid)
    if node is not None and node.kind == "axiom":
        return "[AXIOM]"
    if node is not None and node.kind == "definition":
        return "[DEF]"
    return slice_badge(slice_map.get(nid))


def render_lineage(dag: ProofDAG, slices: list[ConsistencySlice], node_id: str) -> str:
    """One node's lineage, drawn from the node up: the premises it rests on, theirs beneath them,
    each statement once; then every node that rests on it, by id and badge. It grows with the
    node's ancestry, not with the graph, so it fits where the whole tree of a large ledger does not."""
    slice_map = {s.target_id: s for s in slices}
    node = dag.get(node_id)
    if node is None:
        return f"unknown node {node_id!r}"
    lines = [f"{node_id} {_badge(dag, slice_map, node_id)}: {headline(node.statement)}"]
    visited = {node_id}

    def premises_of(nid: str, prefix: str) -> None:
        parents = sorted(dag.parents.get(nid, set()))
        for i, pid in enumerate(parents):
            last = i == len(parents) - 1
            connector = "└── " if last else "├── "
            pnode = dag.get(pid)
            if pid in visited or pnode is None:
                lines.append(f"{prefix}{connector}{pid} {_badge(dag, slice_map, pid)} (shown above)")
                continue
            visited.add(pid)
            lines.append(f"{prefix}{connector}{pid} {_badge(dag, slice_map, pid)}: {headline(pnode.statement)}")
            premises_of(pid, prefix + ("    " if last else "│   "))

    premises_of(node_id, "")
    dependents = sorted(dag.descendants(node_id))
    lines.append("")
    lines.append(f"rests on it ({len(dependents)}): "
                 + (", ".join(f"{d} {_badge(dag, slice_map, d)}" for d in dependents) or "nothing"))
    return "\n".join(lines)

