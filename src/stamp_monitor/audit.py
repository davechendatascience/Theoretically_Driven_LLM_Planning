"""Is the evidence still what was recorded?

Both ledgers are append-only by convention: plain JSONL that anything with file access can edit.
The stores read past a line they cannot parse, so a damaged record does not fail loudly -- it just
stops existing. This re-checks, mechanically, what the ledgers assume:

  - every ledger line parses, and every evidence id is unique
  - every amendment names a trial that exists
  - every stamp a trial cites exists and still matches the digest the trial recorded
  - every measured trial's artifact exists and still hashes to the value recorded at run time
  - every id a decision cites is in the ledger
  - the declarations in effect are the committed ones

It never repairs anything. A finding names what is wrong and where; what to do about it -- amend,
re-run, restore from git -- is a decision for someone accountable for it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from component_belief.declarations import load as load_components
from component_belief.staleness import CodeStaleness
from component_belief.store import STORE_DIR, Store

from . import BLOCK, INFO, WARN, Finding

DESIGN_DIR = ".consistency"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _artifact_matches(path: Path, recorded: str) -> bool:
    """The runner hashed the bytes it wrote. A checkout on another platform may have rewritten
    line endings since, which changes the bytes and not the record -- so LF-normalised content
    counts as the same artifact. Anything else does not."""
    data = path.read_bytes()
    return recorded in (_digest(data), _digest(data.replace(b"\r\n", b"\n")))


def _parse_ledger(path: Path, findings: list[Finding]) -> list[dict]:
    records = []
    if not path.exists():
        return records
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            findings.append(Finding(
                "LEDGER_UNPARSABLE", BLOCK, f"{path.parent.name}/{path.name}:{n}",
                "this line does not parse; the store skips it silently, so whatever it recorded "
                "no longer exists as far as any belief is concerned"))
    return records


def audit(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    store = Store(root)
    ledgers = {name: _parse_ledger(root / STORE_DIR / f"{name}.jsonl", findings)
               for name in ("evidence", "events", "decisions")}
    for name in ("evidence", "events", "decisions"):
        _parse_ledger(root / DESIGN_DIR / f"{name}.jsonl", findings)

    trials = [r for r in ledgers["evidence"] if r.get("kind") == "trial"]
    seen: dict[str, int] = {}
    for t in trials:
        seen[t.get("id", "")] = seen.get(t.get("id", ""), 0) + 1
    for eid, count in sorted(seen.items()):
        if count > 1:
            findings.append(Finding("DUPLICATE_ID", BLOCK, eid,
                                    f"{count} trials share this id; amendments and citations "
                                    "cannot tell them apart"))
    ids = set(seen)
    for record in ledgers["evidence"]:
        if record.get("kind") == "amendment" and record.get("target") not in ids:
            findings.append(Finding("AMENDMENT_TARGET_UNKNOWN", WARN, str(record.get("target")),
                                    "an amendment reclassifies a trial that is not in the ledger"))

    _stamps(root, store, trials, findings)
    _artifacts(root, trials, findings)

    for decision in ledgers["decisions"]:
        missing = sorted(set(decision.get("evidence_ids") or []) - ids)
        if missing:
            findings.append(Finding(
                "DECISION_EVIDENCE_UNKNOWN", BLOCK, str(decision.get("id")),
                f"cites {len(missing)} evidence id(s) the ledger does not hold "
                f"({', '.join(missing[:3])})"))

    for issue in load_components(root).issues:
        if issue.code in ("PENDING", "UNCOMMITTED"):
            findings.append(Finding("DECLARATIONS_" + issue.code, WARN, issue.subject, issue.message))
    if (root / "consistency.yaml").exists():
        try:
            from consistency_belief.declarations import load as load_design
            for issue in load_design(root).issues:
                if issue.code in ("PENDING", "UNCOMMITTED"):
                    findings.append(Finding("DECLARATIONS_" + issue.code, WARN, issue.subject,
                                            issue.message))
        except ImportError:
            pass
    return findings


def _stamps(root: Path, store: Store, trials: list[dict], findings: list[Finding]) -> None:
    staleness = CodeStaleness(root)
    bad: dict[str, str] = {}
    unstamped = 0
    for t in trials:
        if t.get("provenance") != "measured":
            continue
        stamp = staleness.stamp_for(t)
        if stamp is None:
            unstamped += 1
        elif isinstance(stamp, str):
            bad.setdefault(str(t.get("run_id")), stamp)
    for run_id, reason in sorted(bad.items()):
        findings.append(Finding("STAMP_UNTRUSTED", BLOCK, run_id, reason))
    if unstamped:
        findings.append(Finding(
            "UNSTAMPED_EVIDENCE", INFO, f"{unstamped} trial(s)",
            "recorded before content stamps; their staleness is judged by revision, which cannot "
            "see discarded uncommitted edits or tell a rewritten history from changed code"))


def _artifacts(root: Path, trials: list[dict], findings: list[Finding]) -> None:
    """One finding per artifact, not per trial: a run's trials share one file."""
    checked: dict[tuple[str, str], str] = {}
    for t in trials:
        if t.get("provenance") != "measured" or not t.get("artifact_uri"):
            continue
        key = (str(t["artifact_uri"]), str(t.get("artifact_hash") or ""))
        if key in checked:
            continue
        path = root / key[0]
        if not path.exists():
            checked[key] = "missing"
            findings.append(Finding("ARTIFACT_MISSING", BLOCK, str(t.get("run_id")),
                                    f"{key[0]} is gone; its trials can no longer be audited"))
        elif key[1] and not _artifact_matches(path, key[1]):
            checked[key] = "mismatch"
            findings.append(Finding("ARTIFACT_HASH_MISMATCH", BLOCK, str(t.get("run_id")),
                                    f"{key[0]} no longer hashes to {key[1]}, the value recorded "
                                    "when the run wrote it"))
        else:
            checked[key] = "ok"
