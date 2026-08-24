"""P-0004: the corpus channel — enumerate, resolve provenance, report gaps.

Every expected value is preregistered in P-0004's intervention.description, fixed
before this module was written. The six adversarial strings in particular are named
in plan text precisely so the implementer cannot choose a set the matcher happens
to pass.

All fixtures live under pytest tmp_path: nothing is persisted, so no corpus-prefixed
provenance ever reaches micro_damping's substring matcher (F-0014).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from damped_plan_mcp.services import corpus

# Fixed in P-0004's plan text. Each contains the substring "corpus"; none is
# corpus-scoped under a structural, case-sensitive prefix parse. A substring
# matcher scores 6 here and fails.
ADVERSARIAL = [
    "search:corpus_linguistics",
    "tool:corpusreader",
    "manual_review:corpus",
    "corpusx:a/b",
    "x-corpus:a/b",
    "CORPUS:a/b",
]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A three-entry corpus: two documents and one .url link file."""
    domain = tmp_path / "corpus" / "reflexive-eval"
    domain.mkdir(parents=True)
    (domain / "bda3-ch6.pdf").write_text("stub", encoding="utf-8")
    (domain / "huang-2024-self-correct.pdf").write_text("stub", encoding="utf-8")
    (domain / "awesome-harness-engineering.url").write_text(
        "https://github.com/ai-boost/awesome-harness-engineering", encoding="utf-8"
    )
    return tmp_path


def test_enumerates_entries_including_link_files(data_dir: Path) -> None:
    assert corpus.list_domains(data_dir) == ["reflexive-eval"]
    entries = corpus.list_entries(data_dir, "reflexive-eval")
    assert len(entries) == 3
    assert "awesome-harness-engineering.url" in entries, "a corpus entry may be a link"


def test_absent_domain_enumerates_empty_not_error(tmp_path: Path) -> None:
    """A corpus nobody has filled yields low coverage, never a crash."""
    assert corpus.list_domains(tmp_path) == []
    assert corpus.list_entries(tmp_path, "nonexistent") == []


def test_present_entries_resolve(data_dir: Path) -> None:
    for entry in ("bda3-ch6.pdf", "huang-2024-self-correct.pdf"):
        result = corpus.classify_provenance(
            data_dir, f"corpus:reflexive-eval/{entry}"
        )
        assert result.status == "resolved"
        assert result.entry == entry


def test_absent_entries_are_unresolvable(data_dir: Path) -> None:
    """Citing something not in the corpus is the event this channel exists to detect."""
    for entry in ("never-added.pdf", "imagined-paper.pdf"):
        result = corpus.classify_provenance(
            data_dir, f"corpus:reflexive-eval/{entry}"
        )
        assert result.status == "unresolvable"
        assert "outside the corpus" in result.detail


@pytest.mark.parametrize("provenance", ADVERSARIAL)
def test_adversarial_strings_are_not_corpus_scoped(
    data_dir: Path, provenance: str
) -> None:
    """The plan's primary refuting prediction, one string per case.

    A substring implementation treats all six as corpus-scoped and fails. Note
    CORPUS:a/b in particular — the scheme comparison is case-sensitive.
    """
    result = corpus.classify_provenance(data_dir, provenance)
    assert result.status == "not_corpus_scoped", (
        f"{provenance!r} was classified {result.status!r}; the match is by "
        f"containment rather than structural prefix parse (P-0004 D-overbroad)."
    )


def test_adversarial_misclassification_count_is_zero(data_dir: Path) -> None:
    """PR-adversarial as a single scored metric."""
    misclassified = [
        p
        for p in ADVERSARIAL
        if corpus.classify_provenance(data_dir, p).status != "not_corpus_scoped"
    ]
    assert misclassified == []


def test_malformed_corpus_provenance_is_unresolvable(data_dir: Path) -> None:
    """Right scheme, wrong shape: reported, never treated as resolved."""
    for bad in ("corpus:", "corpus:reflexive-eval", "corpus:/entry.pdf"):
        assert corpus.classify_provenance(data_dir, bad).status == "unresolvable"


def test_coverage_report_names_gaps_not_just_counts(data_dir: Path) -> None:
    """The loop's return path: which document would help, not merely how many."""
    required = ["base_rate", "effect_size", "method", "sample", "replication"]
    covered = ["base_rate", "method", "sample"]
    report = corpus.coverage_report("reflexive-eval", required, covered)

    assert report.gaps == ["effect_size", "replication"], "gap SET, by identity"
    assert len(report.gaps) == 2
    assert report.coverage_ratio == 0.6
    assert "effect_size" in report.detail and "replication" in report.detail


def test_full_coverage_names_no_gaps(data_dir: Path) -> None:
    report = corpus.coverage_report("reflexive-eval", ["a", "b"], ["a", "b", "extra"])
    assert report.gaps == []
    assert report.coverage_ratio == 1.0


def test_no_required_attributes_is_vacuously_covered(data_dir: Path) -> None:
    report = corpus.coverage_report("reflexive-eval", [], [])
    assert report.coverage_ratio == 1.0
    assert report.gaps == []
    assert "nothing to cover" in report.detail


def test_covered_is_the_agents_judgement_not_inferred(data_dir: Path) -> None:
    """The server never reads a document. Coverage of an EMPTY corpus is whatever
    the agent declares, because attribution is the agent's job and set arithmetic
    is the server's. This is what keeps enumeration sufficient (H-0003)."""
    report = corpus.coverage_report("empty-domain", ["x"], ["x"])
    assert report.coverage_ratio == 1.0
    assert report.gaps == []
