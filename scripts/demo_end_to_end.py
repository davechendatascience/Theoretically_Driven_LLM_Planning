#!/usr/bin/env python3
"""End-to-end demo of the plan-auto gate (blueprint §19.1).

Drives the MCP server through an in-memory client session against a scratch
data dir, then pipes synthetic PreToolUse payloads into the hook. Exits
non-zero if any step's status deviates from the expected flow.

Run: uv run python scripts/demo_end_to_end.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plan_auto.server import build_server  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "plan_auto_gate.py"
EXAMPLES = REPO / "examples" / "robotics_project"

STEP = 0


def step(title: str) -> None:
    global STEP
    STEP += 1
    print(f"\n=== Step {STEP}: {title} ===")


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  {label}: {actual!r} {'OK' if ok else f'!= expected {expected!r}'}")
    if not ok:
        sys.exit(1)


def payload(result):
    if result.is_error:
        print(f"  TOOL ERROR: {result.content[0].text}")
        sys.exit(1)
    data = result.structured_content
    if isinstance(data, dict):
        return data.get("result", data)
    return json.loads(result.content[0].text)


def run_hook(project_root: Path, rel_path: str) -> dict | None:
    event = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(project_root / rel_path)},
        "cwd": str(project_root),
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


async def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="plan-auto-demo-"))
    data_dir = scratch / ".plan-auto"
    print(f"Scratch project: {scratch}")

    project = json.loads((EXAMPLES / "project.json").read_text())
    impl_plan = json.loads((EXAMPLES / "plan_implementation.json").read_text())
    measure_plan = json.loads((EXAMPLES / "plan_measurement.json").read_text())

    server = build_server(data_dir)
    async with Client(server) as client:
        step("Register project (C-compute-budget is UNKNOWN)")
        summary = payload(
            await client.call_tool("register_project", {"project": project})
        )
        print(f"  {summary['human_summary']}")

        step("Resolve the review-type constraints with one manual-review record")
        # One evidence record may back several constraints; each SAT transition
        # still gets its own rationale in the audit trail.
        ev = payload(
            await client.call_tool(
                "record_evidence",
                {"evidence": {"summary": "Design review: sim-only repo, recorded "
                              "demos only, pick/place API and frozen eval preserved",
                              "source_type": "manual_review",
                              "polarity": "supports",
                              "linked_constraint_ids": [
                                  "C-hardware-safety", "C-no-new-real-labels",
                                  "C-action-api", "C-frozen-evaluation"]}},
            )
        )
        for constraint_id, rationale in [
            ("C-hardware-safety", "Simulation-only training and evaluation"),
            ("C-no-new-real-labels", "Uses recorded demonstrations only"),
            ("C-action-api", "Pick/place output contract unchanged"),
            ("C-frozen-evaluation", "Evaluation pinned to configs/eval_frozen.yaml"),
        ]:
            payload(
                await client.call_tool(
                    "update_constraint_status",
                    {"constraint_id": constraint_id, "status": "sat",
                     "rationale": rationale,
                     "evidence_ids": [ev["evidence"]["id"]]},
                )
            )

        step("Implementation plan is BLOCKED on the unknown compute budget")
        impl_eval = payload(
            await client.call_tool("create_plan", {"plan": impl_plan})
        )
        check("plan_status", impl_eval["plan_status"], "blocked")
        check("next_action", impl_eval["recommended_next_action"], "escalate")
        print(f"  {impl_eval['human_summary'].splitlines()[0]}")

        step("Hook denies edits while the gate is closed")
        verdict = run_hook(scratch, "src/policy/placement_head.py")
        check(
            "permissionDecision",
            verdict["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

        step("Measurement plan targeting the unknown is permitted")
        measure_eval = payload(
            await client.call_tool("create_plan", {"plan": measure_plan})
        )
        check("plan_status", measure_eval["plan_status"], "ready_for_review")
        check("next_action", measure_eval["recommended_next_action"], "measure")

        step("Human approves the measurement plan")
        approval = payload(
            await client.call_tool(
                "approve_plan",
                {"plan_id": measure_plan["id"], "approver": "demo-human",
                 "approval_note": "safe profiling only"},
            )
        )
        check("gate_open", approval["gate_open"], True)

        step("Hook now allows the measurement's files, still denies others")
        check("profiling script", run_hook(scratch, "scripts/profile_placement_head.py"), None)
        verdict = run_hook(scratch, "src/policy/placement_head.py")
        check(
            "other file",
            verdict["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

        step("Record profiling evidence; constraint becomes SAT; plan unblocks")
        profile_ev = payload(
            await client.call_tool(
                "record_evidence",
                {"evidence": {"summary": "Peak allocated VRAM 18.6 GB at target batch",
                              "source_type": "profiling",
                              "polarity": "supports",
                              "linked_constraint_ids": ["C-compute-budget"],
                              "linked_plan_id": measure_plan["id"]}},
            )
        )
        update = payload(
            await client.call_tool(
                "update_constraint_status",
                {"constraint_id": "C-compute-budget", "status": "sat",
                 "rationale": "18.6 GB peak < 20 GB budget",
                 "evidence_ids": [profile_ev["evidence"]["id"]]},
            )
        )
        check(
            "auto-transition",
            any(
                t["plan_id"] == impl_plan["id"] and t["to"] == "ready_for_review"
                for t in update["plan_transitions"]
            ),
            True,
        )

        step("Close out the measurement plan")
        payload(
            await client.call_tool(
                "record_plan_outcome",
                {"plan_id": measure_plan["id"], "outcome": "validated",
                 "summary": "Budget confirmed",
                 "evidence_ids": [profile_ev["evidence"]["id"]]},
            )
        )

        step("Approve the implementation plan -> EXECUTABLE")
        approval = payload(
            await client.call_tool(
                "approve_plan",
                {"plan_id": impl_plan["id"], "approver": "demo-human"},
            )
        )
        check("status", approval["plan"]["status"], "executable")

        step("Hook allows exactly the implementation plan's files")
        check("allowed file", run_hook(scratch, "src/policy/placement_head.py"), None)
        verdict = run_hook(scratch, "src/unrelated/module.py")
        check(
            "unrelated file",
            verdict["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    events = (data_dir / "events.jsonl").read_text().splitlines()
    print(f"\nAll steps passed. {len(events)} events in the audit log at {data_dir}.")


if __name__ == "__main__":
    asyncio.run(main())
