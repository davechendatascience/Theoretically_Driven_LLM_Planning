"""MCP-level tests via the SDK's in-memory client transport."""

from __future__ import annotations

import json

import pytest
from mcp import Client

from damped_plan_mcp.server import build_server


@pytest.fixture
def server(tmp_path):
    return build_server(tmp_path / ".damped-plan")


def payload(result):
    """Extract the structured payload from a CallToolResult."""
    if getattr(result, "structured_content", None):
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) else data
    return json.loads(result.content[0].text)


async def test_list_tools(server):
    async with Client(server) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert names == {
            "register_project",
            "get_project_snapshot",
            "get_plan",
            "create_plan",
            "evaluate_plan",
            "approve_plan",
            "record_evidence",
            "update_constraint_status",
            "record_plan_outcome",
        }


async def test_tools_before_registration_instruct(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "create_plan", {"plan": {"title": "x", "kind": "repair"}}
        )
        assert result.is_error
        assert "register_project" in result.content[0].text


async def test_register_and_snapshot(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "register_project",
            {
                "project": {
                    "name": "demo",
                    "goals": [
                        {
                            "statement": "fast inference",
                            "metric_name": "p95_latency",
                            "target": "< 100ms",
                        }
                    ],
                    "constraints": ["No new GPUs"],
                    "failure_modes": ["p95 latency regressions under load"],
                }
            },
        )
        assert not result.is_error
        summary = payload(result)
        assert summary["goal_count"] == 1
        snapshot = payload(
            await client.call_tool("get_project_snapshot", {})
        )
        assert snapshot["open_unknowns"] == ["C-0001"]
        assert snapshot["gate_open"] is False


async def test_partial_plan_gets_repair_instructions(server):
    async with Client(server) as client:
        await client.call_tool(
            "register_project", {"project": {"name": "demo", "goals": ["g"]}}
        )
        evaluation = payload(
            await client.call_tool(
                "create_plan", {"plan": {"title": "try", "kind": "implementation"}}
            )
        )
        assert evaluation["plan_status"] == "under_specified"
        codes = {b["code"] for b in evaluation["blockers"]}
        assert "MISSING_HYPOTHESIS" in codes
        assert "MISSING_DECISION_RULE" in codes


async def test_approve_rejects_ai_approver(server):
    async with Client(server) as client:
        await client.call_tool(
            "register_project", {"project": {"name": "demo"}}
        )
        result = await client.call_tool(
            "approve_plan", {"plan_id": "P-0001", "approver": "Claude"}
        )
        assert result.is_error
        assert "human" in result.content[0].text


async def test_resources_readable(server):
    async with Client(server) as client:
        await client.call_tool("register_project", {"project": {"name": "demo"}})
        resources = await client.list_resources()
        uris = {str(r.uri) for r in resources.resources}
        assert "damped://project/current/state" in uris
        gate = await client.read_resource("damped://project/current/gate")
        data = json.loads(gate.contents[0].text)
        assert data["gate_open"] is False


async def test_prompts_listed(server):
    async with Client(server) as client:
        prompts = await client.list_prompts()
        names = {p.name for p in prompts.prompts}
        assert "draft_feasible_plan" in names
