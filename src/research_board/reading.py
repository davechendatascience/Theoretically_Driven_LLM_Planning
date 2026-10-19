"""ledger(): the records of all three ledgers, and what a run captured, for a reader who opens no file.

A scout reads the project through its records, never its code: what each run measured and printed,
what each contract declares and has recorded, and what each design claim's verifiers tried. The
evidence ledger keeps only the metrics a contract declares, so a run's captured output -- stdout,
stderr, result.json, the command -- is served beside its records: most questions about a number
are answered there, with no one's paraphrase between. Paths are never taken from the caller: a
run id must look like one, and only files inside that run's own artifact directory are read.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from . import board as B

RUN_ID = re.compile(r"^RUN-\d+$")
EVIDENCE_ID = re.compile(r"^EVD-\d+$")
FIELDS = ("metrics", "conditions", "output")
LINE_LIMIT = 2000          # characters served of one record
NODE_ID = re.compile(r"^(AXM|DEF|LMA|BRN)-[A-Za-z0-9][A-Za-z0-9_-]*$")
FILE_LIMIT = 6000          # characters served of each captured file
RECORD_LIMIT = 50


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _clip(text: str, limit: int = FILE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 2] + f"\n… [{len(text) - limit} characters cut] …\n" + text[-limit // 2:]


def _trial_line(record: dict[str, Any], fields: Collection[str] = FIELDS) -> str:
    line = (f"- {record.get('id')} · {record.get('timestamp', '')} · {record.get('contract_id')} · "
            f"{record.get('run_id', '')} · {record.get('outcome')} · {record.get('validity', 'valid')}")
    if "metrics" in fields:
        line += f" · metrics {json.dumps(record.get('metrics', {}), sort_keys=True)}"
    if "conditions" in fields:
        conditions = record.get("conditions", {})
        raw = conditions.get("raw", conditions) if isinstance(conditions, dict) else conditions
        line += f" · conditions {json.dumps(raw, sort_keys=True)}"
    if len(line) > LINE_LIMIT:
        line = line[:LINE_LIMIT] + f" … [{len(line) - LINE_LIMIT} characters cut; fields=\"metrics\" reads less]"
    return line


def _trials(root: Path) -> list[dict[str, Any]]:
    from component_belief.store import Store

    return Store(root).effective_trials()


def serve_run(root: Path, run_id: str, limit: int = RECORD_LIMIT, fields: Collection[str] = FIELDS) -> str:
    if not RUN_ID.match(run_id):
        return f"{run_id!r} is not a run id (RUN-<digits>)"
    records = [t for t in _trials(root) if t.get("run_id") == run_id]
    lines = [f"{run_id}: {len(records)} record(s) in the evidence ledger"]
    lines += [_trial_line(r, fields) for r in records[:limit]]
    if len(records) > limit:
        lines.append(f"… and {len(records) - limit} more (limit=)")
    for event in _jsonl(root / ".belief" / "events.jsonl"):
        payload = event.get("payload") or {}
        if event.get("tool") == "run_test" and payload.get("run_id") == run_id:
            lines.append(f"run: {payload.get('test')} · exit {payload.get('exit_code')} · {event.get('timestamp')}")
    if "output" not in fields:
        return "\n".join(lines)
    artifacts = (root / ".belief" / "artifacts").resolve()
    directory = (artifacts / run_id).resolve()
    if directory.parent != artifacts or not directory.is_dir():
        lines.append("no captured output is kept for this run")
        return "\n".join(lines)
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.resolve().parent == directory:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines += ["", f"--- {path.name} ({len(text)} characters) ---", _clip(text)]
    return "\n".join(lines)


def serve_contract(root: Path, contract_id: str, limit: int, fields: Collection[str] = FIELDS) -> str:
    from component_belief.declarations import load

    decl = load(root)
    contract = decl.contracts.get(contract_id)
    if contract is None:
        return f"no contract {contract_id!r} at HEAD"
    lines = [f"{contract_id} · subject {contract.subject} · kind {contract.kind}",
             f"acceptance: {json.dumps(contract.acceptance, sort_keys=True)}",
             f"metrics: {', '.join(str(m.get('id')) for m in contract.metrics)}",
             f"measured by: {', '.join(contract.evaluable_by) or 'no test'}"]
    for tid in contract.evaluable_by:
        test = decl.tests.get(tid)
        if test is not None:
            lines.append(f"  {tid}: {test.run}")
    records = [t for t in _trials(root) if t.get("contract_id") == contract_id]
    lines.append(f"{len(records)} record(s); the latest {min(limit, len(records))}, newest last:")
    lines += [_trial_line(r, fields) for r in records[-limit:]]
    return "\n".join(lines)


def serve_evidence(root: Path, evidence_id: str) -> str:
    """A measured finding as the board kept it: its own copy, checked against the digest it took."""
    if not EVIDENCE_ID.match(evidence_id):
        return f"{evidence_id!r} is not an evidence id (EVD-<digits>)"
    item = next((r for r in B.read_ledger(root) if r.get("kind") == "evidence" and r.get("id") == evidence_id), None)
    if item is None:
        return f"no evidence {evidence_id!r} on the board"
    lines = [(f"{evidence_id} on {item.get('direction')} · by {item.get('by')} · {item.get('artifact')} at "
              f"{item.get('commit') or '?'} · {item.get('bytes')} bytes · sha256 {item.get('sha256')}"),
             f"summary: {item.get('summary')}"]
    kept = B.evidence_dir(root, evidence_id).resolve()
    path = (root / str(item.get("copy", ""))).resolve()
    if path.parent != kept or not path.is_file():
        lines.append("the board's copy is missing; the summary is all that is left")
        return "\n".join(lines)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest()[:16] != item.get("sha256"):
        lines.append("the board's copy no longer matches the digest it took: not served")
        return "\n".join(lines)
    text = data.decode("utf-8", errors="replace")
    lines += ["", f"--- {path.name} ({len(text)} characters) ---", _clip(text, 12000)]
    return "\n".join(lines)


def serve_node(root: Path, node_id: str, limit: int) -> str:
    if not NODE_ID.match(node_id):
        return f"{node_id!r} is not an axiom, definition, lemma or branch id"
    from consistency_belief.declarations import load

    decl = load(root)
    node = next((n for table in (decl.axioms, decl.definitions, decl.lemmas, decl.branches)
                 for nid, n in table.items() if nid == node_id), None)
    lines = []
    if node is not None:
        statement = getattr(node, "statement", "") or getattr(node, "meaning", "")
        lines += [f"{node_id}: {statement}"]
        premises = getattr(node, "premises", None)
        if premises:
            lines.append(f"premises: {', '.join(premises)}")
    else:
        lines.append(f"{node_id} is not declared at HEAD; its records follow, if any")
    records = _jsonl(root / ".consistency" / "evidence.jsonl")
    trials = [r for r in records if r.get("kind") == "trial" and r.get("target_id") == node_id]
    notes = [r for r in records if r.get("kind") == "note" and r.get("subject") == node_id]
    lines.append(f"{len(trials)} trial(s); the latest {min(limit, len(trials))}, newest last:")
    for t in trials[-limit:]:
        lines.append(f"- {t.get('id')} · {t.get('timestamp', '')} · {t.get('strategy')} · {t.get('outcome')} · "
                     f"{t.get('actor')} · {t.get('validity', 'valid')}")
        for key in ("counterexample", "reasoning"):
            if t.get(key):
                lines.append(f"    {key}: {_clip(str(t[key]), 600)}")
    for n in notes[-limit:]:
        lines.append(f"- note {n.get('timestamp', '')} · {n.get('actor')}: {_clip(str(n.get('text')), 600)}")
    return "\n".join(lines)


def serve_overview(root: Path, limit: int) -> str:
    belief = _jsonl(root / ".belief" / "evidence.jsonl")
    consistency = _jsonl(root / ".consistency" / "evidence.jsonl")
    research = B.read_ledger(root)
    lines = [f"evidence ledger (.belief): {sum(1 for r in belief if r.get('kind') == 'trial')} records",
             f"design ledger (.consistency): {sum(1 for r in consistency if r.get('kind') == 'trial')} trials",
             f"research ledger (.research): {len(research)} records",
             f"the latest {limit} runs, newest last:"]
    runs = [e for e in _jsonl(root / ".belief" / "events.jsonl") if e.get("tool") == "run_test"]
    for event in runs[-limit:]:
        p = event.get("payload") or {}
        lines.append(f"- {p.get('run_id')} · {p.get('test')} · exit {p.get('exit_code')} · "
                     f"{p.get('n_records')} records · {event.get('timestamp')}")
    lines.append("ledger(run=...), ledger(contract=...) and ledger(node=...) read one in full.")
    return "\n".join(lines)
