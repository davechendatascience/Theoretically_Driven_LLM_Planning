"""Is the evidence still what was recorded?

Both ledgers are append-only by convention: plain JSONL that anything with file access can edit.
The stores read past a line they cannot parse, so a damaged record does not fail loudly -- it just
stops existing. This re-checks, mechanically, what the ledgers assume:

  - every ledger line parses, and every evidence id is unique
  - every amendment names a trial that exists
  - every stamp a trial cites exists and still matches the digest the trial recorded
  - every measured or imported trial's artifact exists and still hashes to the value recorded
  - every id a decision cites is in the ledger
  - the declarations in effect are the committed ones
  - every tagged code region's links resolve, and their pins still match the code and the claim
    (warnings: a link is a declared relationship, not evidence, so it never blocks here)

It never repairs anything. A finding names what is wrong and where; what to do about it -- amend,
re-run, restore from git -- is a decision for someone accountable for it. Once that decision is
made and every record resting on a damaged artifact or stamp has been set aside by an amendment,
nothing counts on it any more: the finding stays, as information naming the amendment, and stops
blocking.
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
    line endings since, in either direction, which changes the bytes and not the record: a run on
    Windows hashed CRLF that git stores, and Linux checks out, as LF. So the content with its line
    endings as LF, or as CRLF, counts as the same artifact. Anything else does not."""
    data = path.read_bytes()
    lf = data.replace(b"\r\n", b"\n")
    return recorded in (_digest(data), _digest(lf), _digest(lf.replace(b"\n", b"\r\n")))


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
    design = {name: _parse_ledger(root / DESIGN_DIR / f"{name}.jsonl", findings)
              for name in ("evidence", "events", "decisions")}

    trials = [r for r in ledgers["evidence"] if r.get("kind") == "trial"]
    ids = _ids_and_citations("", ledgers["evidence"], ledgers["decisions"], "evidence_ids", findings)
    # The design ledger is held to the same: its trials are cited by amendments and by the
    # decisions that adopted on them, and a duplicate or a dangling citation there is as silent.
    _ids_and_citations(DESIGN_DIR + "/", design["evidence"], design["decisions"], "trial_ids", findings)

    set_aside = _set_aside(trials, ledgers["evidence"])
    _stamps(root, store, trials, findings, set_aside)
    _artifacts(root, trials, findings, set_aside)

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
    from .links import findings as link_findings
    findings.extend(link_findings(root))
    findings.extend(_cited_measurements(root))
    return findings


def _cited_measurements(root: Path) -> list[Finding]:
    """A pinned cited measurement whose claim was restated since warns; unpinned ones (once the
    project pins any) and contracts no design cites are counted as information."""
    if not (root / "consistency.yaml").exists():
        return []
    try:
        from consistency_belief.declarations import load as load_design
        from consistency_belief.measurements import (NOT_REVIEWED, UNPINNED, adopted,
                                                     cited_measurements, uncited_by_kind)
    except ImportError:
        return []
    decl = load_design(root)
    if decl.source == "none":
        return []
    found = cited_measurements(decl)
    out = [Finding("MEASUREMENT_NOT_REVIEWED", WARN, f"{m.branch} -> {m.contract}", f"{m.why}; {m.fix}")
           for m in found if m.state == NOT_REVIEWED and (m.pin or m.expected is None)]
    unpinned = [m for m in found if m.state == UNPINNED]
    if unpinned and adopted(found):
        out.append(Finding("MEASUREMENT_UNPINNED", INFO, f"{len(unpinned)} cited measurement(s)",
                           "never read against their claims and pinned: "
                           + ", ".join(f"{m.branch} -> {m.contract}" for m in unpinned[:4])
                           + (" ..." if len(unpinned) > 4 else "")))
    groups = uncited_by_kind(decl)
    total = sum(len(v) for v in groups.values())
    if total:
        parts = [f"{len(ids)} on {kind}s ({', '.join(ids[:4])}{' ...' if len(ids) > 4 else ''})"
                 for kind, ids in groups.items() if ids and kind != "goal"]
        if groups.get("goal"):
            parts.append(f"{len(groups['goal'])} goal measure(s), which their goals explain")
        out.append(Finding("UNCITED_CONTRACT", INFO, f"{total} contract(s)",
                           "cited by no declared branch's derivation rule: " + "; ".join(parts)))
    return out


def _ids_and_citations(prefix: str, records: list[dict], decisions: list[dict], cites: str,
                       findings: list[Finding]) -> set[str]:
    """Trial ids are unique, and every amendment and decision cites trials that exist. Returns
    the ids. `prefix` names the ledger in a finding's subject; empty for the evidence ledger."""
    seen: dict[str, int] = {}
    for t in records:
        if t.get("kind") == "trial":
            seen[t.get("id", "")] = seen.get(t.get("id", ""), 0) + 1
    for eid, count in sorted(seen.items()):
        if count > 1:
            findings.append(Finding("DUPLICATE_ID", BLOCK, prefix + eid,
                                    f"{count} trials share this id; amendments and citations "
                                    "cannot tell them apart"))
    ids = set(seen)
    for record in records:
        if record.get("kind") == "amendment" and record.get("target") not in ids:
            findings.append(Finding("AMENDMENT_TARGET_UNKNOWN", WARN, prefix + str(record.get("target")),
                                    "an amendment reclassifies a trial that is not in the ledger"))
    for decision in decisions:
        missing = sorted(set(decision.get(cites) or []) - ids)
        if missing:
            findings.append(Finding(
                "DECISION_EVIDENCE_UNKNOWN", BLOCK, prefix + str(decision.get("id")),
                f"cites {len(missing)} {'trial' if prefix else 'evidence'} id(s) the ledger does "
                f"not hold ({', '.join(missing[:3])})"))
    return ids


def _set_aside(trials: list[dict], records: list[dict]) -> dict[str, str]:
    """Each trial no longer counted as evidence, by id, with why: its validity after the
    amendments appended to it (folded as the store folds them) is not valid."""
    validity = {str(t.get("id")): (str(t.get("validity") or "valid"), "") for t in trials}
    for record in records:
        target = str(record.get("target") or "")
        if record.get("kind") != "amendment" or target not in validity:
            continue
        if record.get("validity"):
            validity[target] = (str(record["validity"]), str(record.get("reason") or ""))
        if record.get("supersede_with"):
            validity[target] = ("superseded", str(record.get("reason") or ""))
    return {tid: (f"{state}: {reason}" if reason else state)
            for tid, (state, reason) in validity.items() if state != "valid"}


def _settled(records: list[dict], set_aside: dict[str, str]) -> str | None:
    """Why nothing counts on these records any more, or None while one of them still does."""
    if not records or any(str(r.get("id")) not in set_aside for r in records):
        return None
    reasons = sorted({set_aside[str(r.get("id"))] for r in records})
    return (f"all {len(records)} of its records are set aside ({reasons[0]}"
            + (f", and {len(reasons) - 1} other reason(s)" if len(reasons) > 1 else "") + ")")


def _stamps(root: Path, store: Store, trials: list[dict], findings: list[Finding],
            set_aside: dict[str, str]) -> None:
    staleness = CodeStaleness(root)
    bad: dict[str, str] = {}
    by_run: dict[str, list[dict]] = {}
    unstamped = 0
    for t in trials:
        if t.get("provenance") != "measured":
            continue
        stamp = staleness.stamp_for(t)
        if stamp is None:
            unstamped += 1
        elif isinstance(stamp, str):
            bad.setdefault(str(t.get("run_id")), stamp)
            by_run.setdefault(str(t.get("run_id")), []).append(t)
    for run_id, reason in sorted(bad.items()):
        settled = _settled(by_run[run_id], set_aside)
        findings.append(Finding("STAMP_UNTRUSTED", INFO if settled else BLOCK, run_id,
                                f"{reason}; {settled}" if settled else reason))
    if unstamped:
        findings.append(Finding(
            "UNSTAMPED_EVIDENCE", INFO, f"{unstamped} trial(s)",
            "recorded before content stamps; their staleness is judged by revision, which cannot "
            "see discarded uncommitted edits or tell a rewritten history from changed code"))


def _artifacts(root: Path, trials: list[dict], findings: list[Finding],
               set_aside: dict[str, str] | None = None) -> None:
    """One finding per artifact, not per trial: a run's trials share one file.

    Imported trials are held to the same check. Since `ingest` copies and hashes the artifact
    itself, an import is as auditable as a run; one recorded before that, with no hash, rests on
    whatever the caller said the file was, and is reported as such."""
    set_aside = set_aside or {}
    by_key: dict[tuple[str, str], list[dict]] = {}
    unhashed: dict[str, list[dict]] = {}
    for t in trials:
        if t.get("provenance") not in ("measured", "imported") or not t.get("artifact_uri"):
            continue
        key = (str(t["artifact_uri"]), str(t.get("artifact_hash") or ""))
        by_key.setdefault(key, []).append(t)
        if t.get("provenance") == "imported" and not key[1]:
            unhashed.setdefault(str(t.get("run_id")), []).append(t)
    for key, records in by_key.items():
        first = records[0]
        # a run recorded on Windows wrote its path with backslashes, which name no file elsewhere:
        # 43 present artifacts in this repository read as gone on Linux until the separator was read
        path = root / key[0].replace("\\", "/")
        if not path.exists():
            code, message = "ARTIFACT_MISSING", (
                f"{key[0]} is gone; its trials can no longer be audited"
                if first.get("provenance") == "measured" else
                f"{key[0]} is not a file here; this import cannot be audited")
        elif key[1] and not _artifact_matches(path, key[1]):
            code, message = "ARTIFACT_HASH_MISMATCH", (
                f"{key[0]} no longer hashes to {key[1]}, the value recorded when the run wrote it")
        else:
            continue
        settled = _settled(records, set_aside)
        findings.append(Finding(code, INFO if settled else BLOCK, str(first.get("run_id")),
                                f"{message}; {settled}" if settled else message))
    settled_runs = []
    for run_id, records in sorted(unhashed.items()):
        if _settled(records, set_aside):
            settled_runs.append(run_id)
            continue
        findings.append(Finding("IMPORT_UNHASHED", WARN, run_id,
                                "imported with no artifact hash, before ingest hashed what it "
                                "imports; nothing shows the file is the one the records came from"))
    if settled_runs:
        findings.append(Finding("IMPORT_UNHASHED", INFO, f"{len(settled_runs)} run(s)",
                                "imported with no artifact hash, and every record of each is set "
                                f"aside: {', '.join(settled_runs[:6])}"
                                + (" ..." if len(settled_runs) > 6 else "")))
