"""Blueprint §19.1 end-to-end flow through the MCP interface:

implementation plan blocked on an UNKNOWN hard constraint -> safe measurement
plan permitted -> human approval -> evidence recorded -> constraint SAT ->
implementation plan auto-unblocks -> approval -> EXECUTABLE, gate open.
"""

from __future__ import annotations

import json

import pytest
from mcp import Client

from damped_plan_mcp.server import build_server

PROJECT = {
    "name": "lehome",
    "goals": [
        {
            "id": "G-fold",
            "statement": "Robust placement under perturbation",
            "metric_name": "placement_success_rate",
            "target": ">= 0.8 on frozen eval",
        }
    ],
    "constraints": [
        {"id": "C-compute", "statement": "Peak VRAM below 20 GB", "kind": "hard"},
        {
            "id": "C-safety",
            "statement": "Simulation only, no robot actuation",
            "kind": "hard",
            "severity": "critical",
        },
    ],
    "failure_modes": [
        {"id": "F-placement", "symptom": "Placement fails under perturbation"}
    ],
}

IMPLEMENTATION_PLAN = {
    "id": "P-impl",
    "title": "Add pick-conditioned placement head",
    "kind": "implementation",
    "goal_ids": ["G-fold"],
    "addresses_failure_ids": ["F-placement"],
    "hypothesis": "Placement prediction lacks dependence on the selected pick point",
    "intervention": {
        "description": "Condition placement head on pick coordinates",
        "allowed_files": ["src/policy/placement_head.py", "tests/test_head.py"],
        "reversible": True,
    },
    "validation_steps": [
        {
            "description": "Frozen eval by perturbation bin",
            "kind": "command",
            "command": "frozen_eval",
            "expected_result": "metrics artifact",
            "required": True,
        }
    ],
    "decision_rule": {
        "adopt_if": ["robustness improves >= 5pp"],
        "reject_if": ["no improvement under matched initial states"],
    },
    "predictive_contract": {
        "context_fixed": ["frozen eval protocol", "pinned scenes"],
        "context_varied": ["placement head conditioning"],
        "predictions": [
            {"metric_id": "placement_success_rate", "direction": "increase",
             "expected_range": [0.47, 0.60]}
        ],
        "disconfirming_patterns": [
            {"description": "Gain disappears on the frozen held-out split",
             "suggested_model_expansion": "test visual ambiguity with oracle pick"}
        ],
    },
    "rollback_description": "Disable conditioned head via config",
}

MEASUREMENT_PLAN = {
    "id": "P-measure",
    "title": "Profile placement head memory use",
    "kind": "measurement",
    "goal_ids": ["G-fold"],
    "addresses_failure_ids": ["F-placement"],
    "hypothesis": "The head fits within the existing memory budget",
    "intervention": {
        "description": "Three-step training smoke profile",
        "allowed_files": ["scripts/profile_head.py"],
        "reversible": True,
    },
    "constraint_audit": [
        {
            "constraint_id": "C-compute",
            "status": "unknown",
            "evidence": "This plan exists to measure peak VRAM.",
        }
    ],
    "validation_steps": [
        {
            "description": "Run fixed-batch memory profile",
            "kind": "command",
            "command": "profile_head",
            "expected_result": "Peak VRAM artifact recorded",
            "required": True,
        }
    ],
    "decision_rule": {
        "adopt_if": ["peak allocated < 20 GB"],
        "reject_if": ["OOM or peak > 22 GB"],
    },
}


def payload(result):
    assert not result.is_error, result.content[0].text
    data = result.structured_content
    if isinstance(data, dict):
        return data.get("result", data)
    return json.loads(result.content[0].text)


@pytest.fixture
def server(tmp_path):
    return build_server(tmp_path / ".damped-plan")


async def test_full_gate_flow(server, tmp_path):
    data_dir = tmp_path / ".damped-plan"
    async with Client(server) as client:
        # C-safety is registered UNSAT-free but UNKNOWN; mark it SAT via evidence
        # so only C-compute stays unknown.
        payload(await client.call_tool("register_project", {"project": PROJECT}))
        safety_ev = payload(
            await client.call_tool(
                "record_evidence",
                {"evidence": {"summary": "Training pipeline is simulation-only",
                              "source_type": "manual_review",
                              "polarity": "supports",
                              "linked_constraint_ids": ["C-safety"]}},
            )
        )
        payload(
            await client.call_tool(
                "update_constraint_status",
                {"constraint_id": "C-safety", "status": "sat",
                 "rationale": "No actuation path exists in this repo",
                 "evidence_ids": [safety_ev["evidence"]["id"]]},
            )
        )

        # 1. Implementation plan is BLOCKED on the unknown compute budget.
        impl_eval = payload(
            await client.call_tool("create_plan", {"plan": IMPLEMENTATION_PLAN})
        )
        assert impl_eval["plan_status"] == "blocked"
        assert impl_eval["recommended_next_action"] == "escalate"
        assert any(
            b["code"] == "UNRESOLVED_HARD_CONSTRAINT"
            and b["constraint_id"] == "C-compute"
            for b in impl_eval["blockers"]
        )

        # 2. Measurement plan targeting the unknown is permitted.
        measure_eval = payload(
            await client.call_tool("create_plan", {"plan": MEASUREMENT_PLAN})
        )
        assert measure_eval["plan_status"] == "ready_for_review"
        assert measure_eval["recommended_next_action"] == "measure"

        # 3. Human approves the measurement; gate opens for its files only.
        approval = payload(
            await client.call_tool(
                "approve_plan",
                {"plan_id": "P-measure", "approver": "David",
                 "approval_note": "run the profile"},
            )
        )
        assert approval["gate_open"] is True
        gate = json.loads((data_dir / "gate.json").read_text())
        assert gate["open_plans"][0]["plan_id"] == "P-measure"
        assert gate["open_plans"][0]["allowed_files"] == ["scripts/profile_head.py"]

        # 4. Evidence from the measurement resolves the constraint...
        profile_ev = payload(
            await client.call_tool(
                "record_evidence",
                {"evidence": {"summary": "Peak allocated VRAM 18.6 GB",
                              "source_type": "profiling",
                              "polarity": "supports",
                              "linked_constraint_ids": ["C-compute"],
                              "linked_plan_id": "P-measure"}},
            )
        )
        update = payload(
            await client.call_tool(
                "update_constraint_status",
                {"constraint_id": "C-compute", "status": "sat",
                 "rationale": "Profile shows 18.6 GB peak, below the 20 GB budget",
                 "evidence_ids": [profile_ev["evidence"]["id"]]},
            )
        )
        # ...and the blocked implementation plan auto-transitions.
        assert {"plan_id": "P-impl", "from": "blocked",
                "to": "ready_for_review"} in update["plan_transitions"]

        # 5. Close out the measurement with its outcome.
        payload(
            await client.call_tool(
                "record_plan_outcome",
                {"plan_id": "P-measure", "outcome": "validated",
                 "summary": "Budget confirmed: 18.6 GB < 20 GB",
                 "evidence_ids": [profile_ev["evidence"]["id"]]},
            )
        )

        # 6. Approve the implementation plan; it becomes EXECUTABLE.
        approval = payload(
            await client.call_tool(
                "approve_plan", {"plan_id": "P-impl", "approver": "David"}
            )
        )
        assert approval["plan"]["status"] == "executable"
        assert approval["gate_open"] is True
        gate = json.loads((data_dir / "gate.json").read_text())
        open_ids = {p["plan_id"] for p in gate["open_plans"]}
        assert open_ids == {"P-impl"}

        # 7. The audit trail records the whole path.
        events = [
            json.loads(line)
            for line in (data_dir / "events.jsonl").read_text().splitlines()
        ]
        kinds = [e["event"] for e in events]
        for expected in [
            "project_registered", "plan_created", "plan_status_changed",
            "evidence_recorded", "constraint_status_changed", "plan_approved",
            "plan_outcome_recorded",
        ]:
            assert expected in kinds
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(seqs)


async def test_validated_outcome_requires_evidence(server):
    async with Client(server) as client:
        payload(await client.call_tool("register_project", {"project": PROJECT}))
        result = await client.call_tool(
            "record_plan_outcome",
            {"plan_id": "P-none", "outcome": "validated", "summary": "trust me"},
        )
        assert result.is_error  # nonexistent plan
        payload(await client.call_tool("create_plan", {"plan": MEASUREMENT_PLAN}))
        result = await client.call_tool(
            "record_plan_outcome",
            {"plan_id": "P-measure", "outcome": "validated", "summary": "trust me"},
        )
        assert result.is_error
        assert "record_evidence" in result.content[0].text
