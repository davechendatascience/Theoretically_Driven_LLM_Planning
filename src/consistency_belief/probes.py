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


def source_citations(text: str) -> list[str]:
    """Source files a piece of prose names, in order, without duplicates."""
    seen: dict[str, None] = {}
    for m in SOURCE_CITATION.findall(text or ""):
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


def build_probe_prompt(dag: ProofDAG, target_id: str, strategy: str = STRATEGY_COUNTEREXAMPLE) -> dict[str, str]:
    node = dag.get(target_id)
    if not node:
        raise ValueError(f"unknown node {target_id!r}")

    premises_text = []
    for pid in sorted(node.premises):
        pnode = dag.get(pid)
        p_stmt = pnode.statement if pnode else "(unknown)"
        p_kind = pnode.kind if pnode else "unknown"
        premises_text.append(f"- [{p_kind.upper()} {pid}]: {p_stmt}")

    premises_block = "\n".join(premises_text) or "(No premises declared — root or isolated node)"

    if strategy == STRATEGY_COUNTEREXAMPLE:
        system = (
            "You are an adversarial formal proof checker. Your task is to falsify the derived claim "
            "by finding a concrete, realizable counterexample where ALL given premises are strictly true, "
            "but the derived claim fails. If no counterexample is logically possible, certify it as sound."
        )
        task = (
            f"PREMISES:\n{premises_block}\n\n"
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
            f"PREMISES:\n{premises_block}\n\n"
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
            f"PREMISES:\n{premises_block}\n\n"
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
