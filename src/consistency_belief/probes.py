"""Verification Probes: LLM-driven consistency measurement protocols.

Provides prompt builders, parser logic, and reproducible trial synthesis
for adversarial falsification (counterexample search), deductive entailment,
and negation/symmetry checks.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .graph import ProofDAG
from .ids import content_hash


#: A path to a source file, with or without a line number. Deliberately narrow: a bare function
#: name is too common in prose to flag, and an axiom naming a third-party file is citing the fact
#: it records rather than making a claim about our code.
SOURCE_CITATION = re.compile(
    r"\b[\w./-]+\.(?:py|pyx|cpp|cc|c|h|hpp|rs|go|ts|tsx|js|java)\b(?::\d+(?:-\d+)?)?")

#: An identifier out of the implementation: a CamelCase class, a call, a dotted attribute. A claim
#: built around one describes what the code does, which is exactly what a verifier must not be
#: asked to judge (rule 3), and the file check above misses it because no file is named.
CODE_IDENTIFIER = re.compile(
    r"\b[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+\b"            # ProofDAG, ProofNode
    r"|\b[A-Za-z_][A-Za-z0-9_]*\(\)"                        # append_event()
    r"|\b[A-Za-z_][A-Za-z0-9_]+\.[a-z_][a-z0-9_]+\b")       # store.append_event, Store.withdrawn
_DATA_FILE = re.compile(r"\.(?:yaml|yml|json|jsonl|md|txt|csv|log|html)$")


def source_citations(text: str) -> list[str]:
    """Source files a piece of prose names, in order, without duplicates."""
    seen: dict[str, None] = {}
    for m in SOURCE_CITATION.findall(text or ""):
        seen.setdefault(m, None)
    return list(seen)


def code_identifiers(text: str) -> list[str]:
    """Implementation identifiers a piece of prose names: classes, calls, dotted attributes.
    Data files (belief.yaml, a .json artifact) are declarations or evidence, not code."""
    seen: dict[str, None] = {}
    for m in CODE_IDENTIFIER.findall(text or ""):
        if _DATA_FILE.search(m):
            continue
        seen.setdefault(m, None)
    return list(seen)

STRATEGY_COUNTEREXAMPLE = "counterexample"
STRATEGY_ENTAILMENT = "entailment"
STRATEGY_NEGATION = "negation"
STRATEGY_CONTRADICTION = "contradiction"

STRATEGIES = (
    STRATEGY_COUNTEREXAMPLE,
    STRATEGY_ENTAILMENT,
    STRATEGY_NEGATION,
    STRATEGY_CONTRADICTION,
)

#: The three probes one verification pass runs. Each is a different attack on the same step, so
#: together they are what "independent trials" means for one actor.
PROBE_STRATEGIES = (STRATEGY_COUNTEREXAMPLE, STRATEGY_ENTAILMENT, STRATEGY_NEGATION)


def premises_block(dag: ProofDAG, node: Any) -> str:
    """Each direct premise with its statement -- what a step is judged from, and all of it."""
    premises_text = []
    for pid in sorted(node.premises):
        pnode = dag.get(pid)
        p_stmt = pnode.statement if pnode else "(unknown)"
        p_kind = pnode.kind if pnode else "unknown"
        premises_text.append(f"- [{p_kind.upper()} {pid}]: {p_stmt}")
    return "\n".join(premises_text) or "(No premises declared — root or isolated node)"


def probe_text(dag: ProofDAG, target_id: str, status: str = "") -> str:
    """Everything a verifier needs for one node, and nothing else: the premises with their
    statements, the claim, the derivation rule, the three strategies, and the one call that
    records them. Served by status(view="probe") so the verifier assembles nothing by hand and
    has no reason to open a file."""
    node = dag.get(target_id)
    if not node:
        raise ValueError(f"unknown node {target_id!r}")
    head = f"PROBE {target_id} [{node.kind.upper()}]" + (f" {status}" if status else "")
    lines = [
        head,
        "Judge from the premises alone: no source files, no runs, no benchmarks. A clause you "
        "cannot judge without the code is a gap -- name the premise the claim would need.",
        "",
        "PREMISES:",
        premises_block(dag, node),
        "",
        f"DERIVED CLAIM [{target_id}]:",
        node.statement,
        "",
        "DERIVATION RULE:",
        node.derivation_rule or "direct deduction",
        "",
        "STRATEGIES (one trial each; the same strategy repeated by the same actor adds nothing):",
        "  counterexample  a realizable scenario where every premise holds and the claim fails"
        " -> falsified (with the scenario), else sound",
        "  entailment      the claim follows with no unstated assumption -> sound, else gap"
        " (name the assumption)",
        "  negation        NOT(claim) is not also derivable from the same premises -> sound,"
        " else inconclusive",
        "",
        "RECORD, one call:",
        f'  verify_step("{target_id}", trials=[',
        '    {"strategy": "counterexample", "outcome": "sound" | "falsified", '
        '"rationale": "the attack, and why it failed or succeeded", '
        '"counterexample": null | "the scenario"},',
        '    {"strategy": "entailment", "outcome": "sound" | "gap", "rationale": "...", '
        '"counterexample": null | "the unstated assumption"},',
        '    {"strategy": "negation", "outcome": "sound" | "inconclusive", "rationale": "..."}])',
    ]
    return "\n".join(lines)


def build_probe_prompt(dag: ProofDAG, target_id: str, strategy: str = STRATEGY_COUNTEREXAMPLE) -> dict[str, str]:
    node = dag.get(target_id)
    if not node:
        raise ValueError(f"unknown node {target_id!r}")

    premises_block_text = premises_block(dag, node)

    if strategy == STRATEGY_COUNTEREXAMPLE:
        system = (
            "You are an adversarial formal proof checker. Your task is to falsify the derived claim "
            "by finding a concrete, realizable counterexample where ALL given premises are strictly true, "
            "but the derived claim fails. If no counterexample is logically possible, certify it as sound."
        )
        task = (
            f"PREMISES:\n{premises_block_text}\n\n"
            f"DERIVED CLAIM [{target_id}]:\n{node.statement}\n\n"
            f"RATIONALE / DERIVATION RULE:\n{node.derivation_rule or 'direct deduction'}\n\n"
            "Respond with a JSON object:\n"
            "{\n"
            '  "outcome": "sound" | "falsified",\n'
            '  "counterexample": "<concrete scenario or null>",\n'
            '  "reasoning": "<formal explanation>"\n'
            "}"
        )
    elif strategy == STRATEGY_ENTAILMENT:
        system = (
            "You are a deductive proof verifier. Verify whether the derived claim follows strictly "
            "from the premises without introducing unstated assumptions or logical leaps."
        )
        task = (
            f"PREMISES:\n{premises_block_text}\n\n"
            f"DERIVED CLAIM [{target_id}]:\n{node.statement}\n\n"
            f"RATIONALE / DERIVATION RULE:\n{node.derivation_rule or 'direct deduction'}\n\n"
            "Respond with a JSON object:\n"
            "{\n"
            '  "outcome": "sound" | "gap",\n'
            '  "gap": "<unstated assumption or null>",\n'
            '  "reasoning": "<formal explanation>"\n'
            "}"
        )
    elif strategy == STRATEGY_NEGATION:
        system = (
            "You are a symmetry/invariance verifier. Evaluate whether the NEGATION of the derived claim "
            "could also be deduced or supported by the premises."
        )
        task = (
            f"PREMISES:\n{premises_block_text}\n\n"
            f"ORIGINAL CLAIM [{target_id}]:\n{node.statement}\n\n"
            f"NEGATED CLAIM:\nNOT ({node.statement})\n\n"
            "Respond with a JSON object:\n"
            "{\n"
            '  "outcome": "consistent" | "inconclusive",\n'
            '  "negation_possible": true | false,\n'
            '  "reasoning": "<formal explanation>"\n'
            "}"
        )
    else:
        system = "You are a logical consistency verifier."
        task = f"Verify consistency of {target_id}."

    full_text = f"{system}\n\n{task}"
    return {
        "system": system,
        "prompt": task,
        "full_text": full_text,
        "prompt_hash": content_hash(full_text, 12),
        "target_id": target_id,
        "strategy": strategy,
    }


def parse_probe_result(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        data = raw
    else:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            text = raw.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {"outcome": "inconclusive", "reasoning": raw.strip()}

    outcome = str(data.get("outcome", "inconclusive")).lower()
    counterexample = data.get("counterexample") or data.get("gap")
    reasoning = str(data.get("reasoning", ""))

    passed = outcome in ("sound", "consistent") and not counterexample

    return {
        "outcome": outcome,
        "passed": passed,
        "counterexample": counterexample,
        "reasoning": reasoning,
    }
