"""P-0006: the research trigger — a finite work list with a reachable done-state.

Every expected value is preregistered in P-0006, which survived two adversarial
review rounds. The convergence test (`test_fully_sourced_contract_is_complete`)
and its round-trip twin are the point: a loop whose terminal state is unreachable
is a resource sink with a progress bar on it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from plan_auto.models import Plan, PlanKind
from plan_auto.services import corpus
from plan_auto.services.normalize import normalize_plan

RESOLVES = "corpus:reflexive-eval/bda3-ch6.pdf"
ABSENT = "corpus:reflexive-eval/never-added.pdf"
NOT_SCOPED = "paper:smith2020"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    dom = tmp_path / "corpus" / "reflexive-eval"
    dom.mkdir(parents=True)
    (dom / "bda3-ch6.pdf").write_text("stub", encoding="utf-8")
    return tmp_path


def contract_payload(pred_basis=None, pattern_basis=None) -> dict:
    """Two predictions and one disconfirming pattern — three sourceable fields."""
    pred_basis = pred_basis if pred_basis is not None else []
    pattern_basis = pattern_basis if pattern_basis is not None else []
    return {
        "context_fixed": ["fixed"],
        "predictions": [
            {"id": "PR-a", "metric_id": "a_ms", "direction": "decrease",
             "expected_range": [1, 2], "basis": list(pred_basis)},
            {"id": "PR-b", "metric_id": "b_ms", "direction": "no_change",
             "expected_range": [3, 4], "basis": list(pred_basis)},
        ],
        "disconfirming_patterns": [
            {"id": "D-a", "description": "the thing regresses",
             "suggested_model_expansion": "widen", "basis": list(pattern_basis)},
        ],
    }


def make_plan(payload: dict, plan_id: str = "P-t") -> Plan:
    """Author dict -> normalize_plan: the identical path create_plan takes.

    Verified on review that create_plan hands its raw payload straight here
    (server.py takes an untyped dict; workspace.py:217), so this exercises the
    real authoring path rather than simulating it.
    """
    from tests.conftest import make_project

    plan, _ = normalize_plan(
        {"id": plan_id, "title": "t", "kind": "implementation",
         "goal_ids": ["G-0001"], "addresses_failure_ids": ["F-placement"],
         "predictive_contract": payload},
        make_project(),
        set(),
    )
    return plan


def test_unsourced_contract_yields_one_target_per_field(data_dir: Path) -> None:
    plan = make_plan(contract_payload())
    result = corpus.research_targets(plan, data_dir)
    assert len(result.targets) == 3
    assert result.complete is False
    assert {t.field_path for t in result.targets} == {
        "predictive_contract.predictions[PR-a]",
        "predictive_contract.predictions[PR-b]",
        "predictive_contract.disconfirming_patterns[D-a]",
    }


def test_fully_sourced_contract_is_complete(data_dir: Path) -> None:
    """THE CONVERGENCE TEST. An unreachable terminal state means no convergence."""
    plan = make_plan(contract_payload([RESOLVES], [RESOLVES]))
    result = corpus.research_targets(plan, data_dir)
    assert result.targets == []
    assert result.complete is True


def test_basis_survives_the_normalize_roundtrip(data_dir: Path) -> None:
    """_normalize_contract rebuilds predictions field-by-field; a basis it fails
    to copy is silently dropped, and a hand-built fixture would never show it."""
    plan = make_plan(contract_payload([RESOLVES], [RESOLVES]))
    assert plan.predictive_contract is not None
    assert plan.predictive_contract.predictions[0].basis == [RESOLVES]
    assert plan.predictive_contract.disconfirming_patterns[0].basis == [RESOLVES]
    assert corpus.research_targets(plan, data_dir).complete is True


def test_absent_entry_leaves_the_field_unsourced(data_dir: Path) -> None:
    plan = make_plan(contract_payload([ABSENT], [ABSENT]))
    result = corpus.research_targets(plan, data_dir)
    assert len(result.targets) == 3
    assert result.complete is False


def test_not_corpus_scoped_basis_leaves_the_field_unsourced(data_dir: Path) -> None:
    """paper:smith2020 is the THIRD status. Only 'resolved' closes a target —
    an allowlist, else any string would close every target with no corpus."""
    plan = make_plan(contract_payload([NOT_SCOPED], [NOT_SCOPED]))
    result = corpus.research_targets(plan, data_dir)
    assert len(result.targets) == 3
    assert result.complete is False
    assert "not_corpus_scoped" in result.targets[0].detail


def test_one_resolving_basis_among_several_closes_the_field(data_dir: Path) -> None:
    plan = make_plan(contract_payload([NOT_SCOPED, RESOLVES], [ABSENT, RESOLVES]))
    assert corpus.research_targets(plan, data_dir).complete is True


def test_no_contract_is_vacuously_complete(data_dir: Path) -> None:
    stamp = datetime.now(UTC)
    plan = Plan(id="P-n", project_id="x", title="t", kind=PlanKind.MEASUREMENT,
                created_at=stamp, updated_at=stamp)
    result = corpus.research_targets(plan, data_dir)
    assert result.complete is True
    assert result.targets == []


# --- the automatic trigger, and its measured blindness ----------------------


def _evaluate(plan: Plan):
    from plan_auto.services.evaluation import evaluate_plan
    from tests.conftest import make_project
    return evaluate_plan(plan, make_project(), [plan], [])


def _research_warnings(evaluation) -> list[str]:
    return [w for w in evaluation.warnings if "carry no basis" in w]


def test_unsourced_plan_emits_one_warning(data_dir: Path) -> None:
    assert len(_research_warnings(_evaluate(make_plan(contract_payload())))) == 1


def test_sourced_plan_emits_no_warning(data_dir: Path) -> None:
    plan = make_plan(contract_payload([RESOLVES], [RESOLVES]))
    assert _research_warnings(_evaluate(plan)) == []


def test_fabricated_basis_silences_the_automatic_trigger(data_dir: Path) -> None:
    """A MEASURED WEAKNESS, not a bug. evaluate_plan has no data_dir, so it
    detects absence only — any plausible string quiets it. This is exactly why
    research_targets must be reachable; see the MCP test below."""
    plan = make_plan(contract_payload([ABSENT], [ABSENT]))
    assert _research_warnings(_evaluate(plan)) == []
    # ...while the strong check still sees straight through it.
    assert corpus.research_targets(plan, data_dir).complete is False


def test_warning_does_not_gate(data_dir: Path) -> None:
    """D-gating: the warning reports, it never changes what the gate decides."""
    unsourced = _evaluate(make_plan(contract_payload()))
    sourced = _evaluate(make_plan(contract_payload([RESOLVES], [RESOLVES])))
    assert unsourced.plan_status == sourced.plan_status
    assert unsourced.executable == sourced.executable
    assert [b.code for b in unsourced.blockers] == [b.code for b in sourced.blockers]
    assert unsourced.recommended_next_action == sourced.recommended_next_action


# --- PR-reachable: the strong check must have a caller ----------------------
#
# Scored THROUGH THE MCP CLIENT with NO domain argument, never by calling
# Workspace.survey_corpus directly. Two traps make a direct call a false pass:
# survey_corpus returns early when domain is None (so a plan_id branch placed
# after it yields nothing while appearing to work), and server.py forwarded
# arguments positionally (where a new parameter gets misordered). P-0005
# shipped a channel whose strong half had no caller; this is the test that
# would have caught it.


async def test_research_targets_reachable_through_the_mcp_tool(tmp_path) -> None:
    from mcp import Client

    from plan_auto.server import build_server
    from tests.integration.test_mcp_tools import payload

    data_dir = tmp_path / ".plan-auto"
    dom = data_dir / "corpus" / "reflexive-eval"
    dom.mkdir(parents=True)
    (dom / "bda3-ch6.pdf").write_text("stub", encoding="utf-8")

    server = build_server(data_dir)
    async with Client(server) as client:
        await client.call_tool("register_project", {"project": {
            "name": "p",
            "goals": [{"id": "G-1", "statement": "g", "metric_name": "m",
                       "target": ">= 1"}],
            "failure_modes": [{"id": "F-1", "symptom": "s"}],
        }})
        await client.call_tool("create_plan", {"plan": {
            "id": "P-r", "title": "t", "kind": "implementation",
            "goal_ids": ["G-1"], "addresses_failure_ids": ["F-1"],
            "predictive_contract": contract_payload([RESOLVES], []),
        }})

        # NO domain argument — the natural research call, and the one the
        # domain-is-None early return would silently defeat.
        out = payload(await client.call_tool("survey_corpus", {"plan_id": "P-r"}))

        assert "research" in out, (
            "survey_corpus(plan_id=...) returned no research block — the plan_id "
            "branch is unreachable, most likely placed after the domain-is-None "
            "early return, or the parameter was dropped in forwarding."
        )
        research = out["research"]
        assert research["plan_id"] == "P-r"
        # Two predictions are sourced; the disconfirming pattern is not.
        assert research["complete"] is False
        assert len(research["targets"]) == 1
        assert research["targets"][0]["kind"] == "disconfirming_pattern"

        tools = await client.list_tools()
        assert len(tools.tools) == 12, "a parameter was added, not a tool"
