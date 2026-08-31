"""P-0010: the two halves composed — a target carries what would close it.

research_targets said WHICH FIELD was unsourced. coverage_report said WHICH
ATTRIBUTE the corpus lacked. Nothing called one from the other, so the loop's
answer to 58 open targets on the real ledger was "go read something".

The join needs no schema and no agent declaration: the contract's own fields ARE
the required-attributes set. What must be true is that the gap set EQUALS the
target set — two lists in one object would be the same non-join with extra
fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plan_auto.services import corpus
from plan_auto.services.normalize import normalize_plan

REPO = Path(__file__).resolve().parents[2]
from plan_auto.config import resolve_data_dir
LIVE = resolve_data_dir(REPO)
SEEDED = "corpus:reflexive-eval/scheel-2021-excess-of-positive-results.url"


@pytest.fixture
def tmp_corpus(tmp_path: Path) -> Path:
    dom = tmp_path / "corpus" / "reflexive-eval"
    dom.mkdir(parents=True)
    (dom / "scheel-2021-excess-of-positive-results.url").write_text("x", encoding="utf-8")
    return tmp_path


def make(basis_map: dict[str, list[str]]):
    from tests.conftest import make_project

    payload = {
        "context_fixed": ["fixed"],
        "predictions": [
            {"id": "PR-a", "metric_id": "a", "direction": "decrease",
             "expected_range": [1, 2], "basis": basis_map.get("PR-a", [])},
            {"id": "PR-b", "metric_id": "b", "direction": "no_change",
             "expected_range": [3, 4], "basis": basis_map.get("PR-b", [])},
        ],
        "disconfirming_patterns": [
            {"id": "D-a", "description": "regresses", "suggested_model_expansion": "w",
             "basis": basis_map.get("D-a", [])},
        ],
    }
    plan, _ = normalize_plan(
        {"id": "P-j", "title": "t", "kind": "implementation",
         "goal_ids": ["G-0001"], "addresses_failure_ids": ["F-placement"],
         "predictive_contract": payload},
        make_project(), set(),
    )
    return plan


def test_gap_set_equals_target_set(tmp_corpus: Path) -> None:
    """THE JOIN. Not overlap, not containment — equality.

    Both derive from the same resolution pass, so divergence is structurally
    impossible rather than merely unlikely.
    """
    r = corpus.research_targets(make({"PR-a": [SEEDED]}), tmp_corpus)
    assert r.coverage is not None
    target_ids = {t.field_path.split("[")[1].rstrip("]") for t in r.targets}
    assert set(r.coverage.gaps) == target_ids == {"PR-b", "D-a"}


def test_coverage_ratio_is_sourced_over_total_fields(tmp_corpus: Path) -> None:
    """3 fields, 1 sourced -> 0.33. Derived from the contract; nothing declared."""
    r = corpus.research_targets(make({"PR-a": [SEEDED]}), tmp_corpus)
    assert r.coverage.coverage_ratio == pytest.approx(0.3333, abs=1e-3)
    assert sorted(r.coverage.required) == ["D-a", "PR-a", "PR-b"]
    assert r.coverage.covered == ["PR-a"]


def test_full_coverage_agrees_with_complete(tmp_corpus: Path) -> None:
    """Coverage and completeness are two views of one fact."""
    r = corpus.research_targets(
        make({"PR-a": [SEEDED], "PR-b": [SEEDED], "D-a": [SEEDED]}), tmp_corpus
    )
    assert r.complete is True
    assert r.coverage.coverage_ratio == 1.0
    assert r.coverage.gaps == []


def test_no_coverage_agrees_with_all_targets_open(tmp_corpus: Path) -> None:
    r = corpus.research_targets(make({}), tmp_corpus)
    assert r.complete is False
    assert r.coverage.coverage_ratio == 0.0
    assert len(r.coverage.gaps) == len(r.targets) == 3


def test_candidates_offer_the_reading_list(tmp_corpus: Path) -> None:
    """What turns 'this is unsourced' into 'and here is what you could read'."""
    r = corpus.research_targets(make({}), tmp_corpus, domain="reflexive-eval")
    assert r.candidates == {
        "reflexive-eval": ["scheel-2021-excess-of-positive-results.url"]
    }


def test_candidates_without_a_domain_list_every_domain(tmp_corpus: Path) -> None:
    """A caller with nothing in mind still learns what exists."""
    r = corpus.research_targets(make({}), tmp_corpus)
    assert "reflexive-eval" in r.candidates


def test_contract_without_predictions_is_vacuously_covered(tmp_corpus: Path) -> None:
    from plan_auto.models import Plan, PlanKind
    from datetime import UTC, datetime

    stamp = datetime.now(UTC)
    plan = Plan(id="P-n", project_id="x", title="t", kind=PlanKind.MEASUREMENT,
                created_at=stamp, updated_at=stamp)
    r = corpus.research_targets(plan, tmp_corpus)
    assert r.complete is True
    assert r.coverage.coverage_ratio == 1.0


# --- against the real seeded corpus ------------------------------------------


@pytest.mark.skipif(not (LIVE / "corpus" / "reflexive-eval").is_dir(),
                    reason="live corpus not seeded")
def test_candidates_from_the_real_corpus() -> None:
    """Reads the 9 real sources seeded by P-0008, not a tmp_path stub."""
    r = corpus.research_targets(make({}), LIVE, domain="reflexive-eval")
    entries = r.candidates["reflexive-eval"]
    assert len(entries) == 9
    assert "scheel-2021-excess-of-positive-results.url" in entries
    assert "awesome-harness-engineering.url" in entries
