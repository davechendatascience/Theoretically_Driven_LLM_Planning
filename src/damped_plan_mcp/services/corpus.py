"""Corpus channel: a human-filled directory the loop reads (P-0004).

The corpus is `<data_dir>/corpus/<domain>/`. A human drops documents and `.url`
link files in; nothing here writes to it. That asymmetry is the point, and it is
NOT the `commands.json` pattern: `commands.json` gates *execution* and needs a
human author because argv can act. A corpus gates *reading*, and a document in a
folder cannot act — so there is no admission ceremony, no request queue, and no
approval step. The human's only lever is how much is in the directory.

Three operations, none of which requires the server to understand a document:

- **enumerate** — what is in scope
- **classify provenance** — is a claim citing something that is actually there
- **report coverage** — which required attributes the corpus did not answer

The third is the loop's return path. `covered` comes from the AGENT, which read
the documents; `required` comes from the question. The server does set arithmetic
and NAMES the gaps, because a bare ratio tells a human nothing about which
document would help. Gaps are reported, never requested: nothing blocks on anyone.

Deliberately absent: any stopping rule. Under the damping/inflow separation,
`micro_damping` decides when confusion about one subtask is resolved; a corpus
read is inflow and is not trying to converge. This module imports nothing from it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

# Exact, case-sensitive. `CORPUS:`, `corpusx:` and `x-corpus:` are NOT this scheme.
CORPUS_SCHEME = "corpus"

ProvenanceStatus = Literal["not_corpus_scoped", "resolved", "unresolvable"]


class ProvenanceClassification(BaseModel):
    provenance: str
    status: ProvenanceStatus
    domain: str | None = None
    entry: str | None = None
    detail: str = ""


class CoverageReport(BaseModel):
    domain: str
    required: list[str] = Field(default_factory=list)
    covered: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    coverage_ratio: float = 1.0
    detail: str = ""


def corpus_root(data_dir: Path | str) -> Path:
    return Path(data_dir) / "corpus"


def list_domains(data_dir: Path | str) -> list[str]:
    root = corpus_root(data_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def list_entries(data_dir: Path | str, domain: str) -> list[str]:
    """Every file in the domain directory, documents and .url links alike."""
    domain_dir = corpus_root(data_dir) / domain
    if not domain_dir.is_dir():
        return []
    return sorted(p.name for p in domain_dir.iterdir() if p.is_file())


def classify_provenance(
    data_dir: Path | str, provenance: str
) -> ProvenanceClassification:
    """Resolve `corpus:<domain>/<entry>` against the directory's actual contents.

    Parsed STRUCTURALLY — split on the first colon, compare the scheme exactly and
    case-sensitively — never by substring containment. A provenance that merely
    contains the word "corpus" (`search:corpus_linguistics`, `tool:corpusreader`)
    is not corpus-scoped and must pass through untouched.
    """
    text = provenance.strip()
    scheme, sep, remainder = text.partition(":")
    if not sep or scheme != CORPUS_SCHEME:
        return ProvenanceClassification(
            provenance=provenance,
            status="not_corpus_scoped",
            detail="no 'corpus:' scheme; outside this channel",
        )

    domain, slash, entry = remainder.partition("/")
    domain, entry = domain.strip(), entry.strip()
    if not slash or not domain or not entry:
        return ProvenanceClassification(
            provenance=provenance,
            status="unresolvable",
            domain=domain or None,
            detail="expected corpus:<domain>/<entry>",
        )

    if entry in list_entries(data_dir, domain):
        return ProvenanceClassification(
            provenance=provenance,
            status="resolved",
            domain=domain,
            entry=entry,
            detail=f"{entry} present in corpus/{domain}/",
        )
    return ProvenanceClassification(
        provenance=provenance,
        status="unresolvable",
        domain=domain,
        entry=entry,
        detail=(
            f"{entry} is not in corpus/{domain}/ — the claim cites something "
            f"outside the corpus"
        ),
    )


def coverage_report(
    domain: str,
    required_attributes: Iterable[str],
    covered_attributes: Iterable[str],
) -> CoverageReport:
    """Which required attributes the corpus did not answer, named rather than counted.

    `covered_attributes` is the agent's judgement after reading; the server never
    infers it. An empty `required` set yields ratio 1.0 by vacuity — nothing was
    asked, so nothing is missing.
    """
    required = {a.strip() for a in required_attributes if a and a.strip()}
    covered = {a.strip() for a in covered_attributes if a and a.strip()}
    matched = required & covered
    gaps = sorted(required - covered)
    ratio = len(matched) / len(required) if required else 1.0

    if not required:
        detail = "no required attributes declared; nothing to cover"
    elif gaps:
        detail = (
            f"corpus/{domain}/ did not cover: {', '.join(gaps)}. "
            f"Adding documents on these would raise coverage."
        )
    else:
        detail = f"corpus/{domain}/ covered every required attribute"

    return CoverageReport(
        domain=domain,
        required=sorted(required),
        covered=sorted(matched),
        gaps=gaps,
        coverage_ratio=round(ratio, 4),
        detail=detail,
    )


# --- research trigger (P-0006) ---------------------------------------------


class ResearchTarget(BaseModel):
    """One contract field with no basis that resolves to the corpus."""

    field_path: str
    kind: Literal["prediction", "disconfirming_pattern"]
    basis: list[str] = Field(default_factory=list)
    detail: str = ""


class ResearchTargets(BaseModel):
    plan_id: str
    targets: list[ResearchTarget] = Field(default_factory=list)
    complete: bool = True
    # The coverage the targets imply, and the corpus material available to close
    # them. Composed rather than bundled: `coverage.gaps` equals the target field
    # ids exactly, because both derive from the same resolution pass.
    coverage: CoverageReport | None = None
    candidates: dict[str, list[str]] = Field(default_factory=dict)
    detail: str = ""


def _basis_resolves(data_dir: Path | str, basis: list[str]) -> tuple[bool, str]:
    """ONLY status == 'resolved' closes a target.

    `classify_provenance` returns three statuses and BOTH `unresolvable` and
    `not_corpus_scoped` leave a field unsourced. An allowlist, not a denylist:
    treating "anything but unresolvable" as sourced would let a basis of
    `paper:smith2020` close every target with no corpus in existence.

    One resolving entry suffices — a field citing a real source alongside a
    dead one did come from somewhere real.
    """
    if not basis:
        return False, "no basis declared"
    statuses = [classify_provenance(data_dir, b) for b in basis]
    if any(s.status == "resolved" for s in statuses):
        return True, ""
    parts = [f"{s.provenance} ({s.status})" for s in statuses]
    return False, "no basis resolves to the corpus: " + "; ".join(parts)


def research_targets(
    plan: Any, data_dir: Path | str, domain: str | None = None
) -> ResearchTargets:
    """Contract fields a corpus could fill — the research loop's finite work list.

    INITIATIVE and CONVERGENCE, which the corpus channel lacked on its own.
    The list is derived from the contract's own predictions and disconfirming
    patterns, so it is finite and cannot be inflated by adding documents:
    per-plan targets = |predictions| + |patterns|.

    `complete` is True exactly when the list is empty. That is the terminal
    state, and it is the point — a loop with no reachable done-state is a
    resource sink with a progress bar on it.
    """
    contract = getattr(plan, "predictive_contract", None)
    plan_id = getattr(plan, "id", "")
    if contract is None:
        return ResearchTargets(
            plan_id=plan_id,
            complete=True,
            coverage=coverage_report(domain or "*", [], []),
            candidates=_candidates(data_dir, domain),
            detail="no predictive_contract: nothing to source",
        )

    targets: list[ResearchTarget] = []
    # required and sourced are accumulated in the SAME pass that builds targets,
    # so coverage.gaps cannot drift from the target list (D-bundled).
    required: list[str] = []
    sourced: list[str] = []
    for prediction in contract.predictions:
        ok, why = _basis_resolves(data_dir, list(prediction.basis))
        required.append(prediction.id)
        if ok:
            sourced.append(prediction.id)
        else:
            targets.append(
                ResearchTarget(
                    field_path=f"predictive_contract.predictions[{prediction.id}]",
                    kind="prediction",
                    basis=list(prediction.basis),
                    detail=f"{prediction.metric_id}: {why}",
                )
            )
    for pattern in contract.disconfirming_patterns:
        ok, why = _basis_resolves(data_dir, list(pattern.basis))
        required.append(pattern.id)
        if ok:
            sourced.append(pattern.id)
        else:
            targets.append(
                ResearchTarget(
                    field_path=(
                        f"predictive_contract.disconfirming_patterns[{pattern.id}]"
                    ),
                    kind="disconfirming_pattern",
                    basis=list(pattern.basis),
                    detail=why,
                )
            )

    complete = not targets
    if complete:
        detail = "research complete: every contract field resolves to the corpus"
    else:
        detail = (
            f"{len(targets)} contract field(s) need a source: "
            + ", ".join(t.field_path for t in targets)
        )
    return ResearchTargets(
        plan_id=plan_id,
        targets=targets,
        complete=complete,
        coverage=coverage_report(domain or "*", required, sourced),
        candidates=_candidates(data_dir, domain),
        detail=detail,
    )


def _candidates(data_dir: Path | str, domain: str | None) -> dict[str, list[str]]:
    """Corpus material available to close a target — the reading list.

    With a domain, that domain's entries. Without one, every domain, so a caller
    with nothing in mind still learns what exists rather than being told only
    that a field is unsourced.
    """
    if domain is not None:
        return {domain: list_entries(data_dir, domain)}
    return {d: list_entries(data_dir, d) for d in list_domains(data_dir)}
