"""Proof DAG Kernel.

The deterministic backbone of consistency-belief.
Enforces acyclicity, verifies transitive reachability to axioms,
and computes topological blast-radius when nodes are mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .declarations import Declarations


@dataclass
class ProofNode:
    id: str
    kind: str           # axiom | definition | lemma | branch | change
    statement: str = ""
    premises: list[str] = field(default_factory=list)
    derivation_rule: str = ""
    subject: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ProofDAG:
    def __init__(self) -> None:
        self.nodes: dict[str, ProofNode] = {}
        self.parents: dict[str, set[str]] = {}      # child -> set(premises)
        self.children: dict[str, set[str]] = {}     # parent -> set(dependents)

    @classmethod
    def from_declarations(cls, decl: Declarations) -> ProofDAG:
        dag = cls()
        for axm in decl.axioms.values():
            dag.add_node(ProofNode(
                id=axm.id, kind="axiom", statement=axm.statement,
                derivation_rule="primitive", metadata={"domain": axm.domain, "rationale": axm.rationale}
            ))
        for defn in decl.definitions.values():
            dag.add_node(ProofNode(
                id=defn.id, kind="definition", statement=f"{defn.term}: {defn.meaning}",
                derivation_rule="definition",
            ))
        for lma in decl.lemmas.values():
            dag.add_node(ProofNode(
                id=lma.id, kind="lemma", statement=lma.statement,
                premises=list(lma.premises), derivation_rule=lma.derivation_rule,
                metadata=lma.sufficiency,
            ))
        for brn in decl.branches.values():
            dag.add_node(ProofNode(
                id=brn.id, kind="branch", statement=brn.statement,
                premises=list(brn.premises), derivation_rule=brn.derivation_rule,
                subject=brn.subject, metadata=brn.sufficiency,
            ))
        return dag

    def add_node(self, node: ProofNode) -> list[str]:
        errors: list[str] = []
        for p in node.premises:
            if p not in self.nodes:
                errors.append(f"unknown premise {p!r}")
            elif p == node.id or node.id in self.ancestors(p):
                errors.append(f"cycle detected: premise {p!r} transitively depends on {node.id!r}")

        if errors:
            return errors

        self.nodes[node.id] = node
        self.parents.setdefault(node.id, set())
        self.children.setdefault(node.id, set())

        for p in node.premises:
            self.parents[node.id].add(p)
            self.children.setdefault(p, set()).add(node.id)

        return []

    def get(self, node_id: str) -> ProofNode | None:
        return self.nodes.get(node_id)

    def ancestors(self, node_id: str) -> set[str]:
        """Transitive closure of premises."""
        res: set[str] = set()
        stack = list(self.parents.get(node_id, set()))
        while stack:
            curr = stack.pop()
            if curr not in res:
                res.add(curr)
                stack.extend(self.parents.get(curr, set()) - res)
        return res

    def descendants(self, node_id: str) -> set[str]:
        """Transitive closure of dependents."""
        res: set[str] = set()
        stack = list(self.children.get(node_id, set()))
        while stack:
            curr = stack.pop()
            if curr not in res:
                res.add(curr)
                stack.extend(self.children.get(curr, set()) - res)
        return res

    def roots(self) -> set[str]:
        """Nodes with no premises (should be axioms or definitions)."""
        return {nid for nid, p in self.parents.items() if not p}

    def axiomatic_basis(self, node_id: str) -> set[str]:
        """All ancestor nodes that are declared axioms."""
        return {aid for aid in self.ancestors(node_id) if self.nodes[aid].kind == "axiom"}

    def is_grounded(self, node_id: str) -> tuple[bool, list[str]]:
        """Check if every ancestor path terminates in declared Axioms/Definitions."""
        node = self.nodes.get(node_id)
        if not node:
            return False, [f"unknown node {node_id!r}"]
        if node.kind in ("axiom", "definition"):
            return True, []

        anc = self.ancestors(node_id)
        if not anc:
            return False, ["no premises declared"]

        # Check leaf ancestors
        leaf_ancestors = {a for a in anc if not self.parents.get(a)}
        non_axiomatic = {a for a in leaf_ancestors if self.nodes[a].kind not in ("axiom", "definition")}
        if non_axiomatic:
            return False, [f"leaf ancestor {a!r} is not an axiom" for a in sorted(non_axiomatic)]

        return True, []

    def blast_radius(self, node_id: str) -> list[str]:
        """Topologically sorted list of all downstream dependents affected by modifying node_id."""
        affected = self.descendants(node_id)
        if not affected:
            return []

        # Kahn's topological sort restricted to the affected subgraph
        in_degree: dict[str, int] = {}
        for nid in affected:
            # count parents that are in affected or equal to node_id
            in_degree[nid] = sum(1 for p in self.parents.get(nid, set()) if p in affected or p == node_id)

        queue = [nid for nid in affected if in_degree[nid] == 1 and node_id in self.parents.get(nid, set())]
        ordered: list[str] = []

        while queue:
            curr = queue.pop(0)
            ordered.append(curr)
            for child in self.children.get(curr, set()):
                if child in affected:
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        queue.append(child)

        # Fallback for any remaining nodes if graph has disconnected affected branches
        remaining = [nid for nid in affected if nid not in ordered]
        return ordered + sorted(remaining)

    def topological_sort(self) -> list[str]:
        in_degree = {nid: len(self.parents.get(nid, set())) for nid in self.nodes}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        ordered: list[str] = []

        while queue:
            curr = queue.pop(0)
            ordered.append(curr)
            for child in self.children.get(curr, set()):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        return ordered
