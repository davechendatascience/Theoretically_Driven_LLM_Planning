"""Phase 4 runner tests: allowlist enforcement, argv-only execution, capture,
timeout, and validation-to-evidence conversion through the Workspace."""

from __future__ import annotations

import json
import sys

import pytest

from plan_auto.models import PlanStatus
from plan_auto.services import command_runner
from plan_auto.services.command_runner import CommandRunnerError
from plan_auto.workspace import Workspace, WorkspaceError


def write_registry(data_dir, entries):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "commands.json").write_text(json.dumps(entries))


# -- registry ----------------------------------------------------------------


def test_missing_registry_instructs(tmp_path):
    with pytest.raises(CommandRunnerError, match="commands.json"):
        command_runner.resolve_command(tmp_path, "unit_tests")


def test_unregistered_command_refused(tmp_path):
    write_registry(tmp_path, {"other": {"allowed": True, "argv": ["true"]}})
    with pytest.raises(CommandRunnerError, match="not registered"):
        command_runner.resolve_command(tmp_path, "unit_tests")


def test_disallowed_command_refused(tmp_path):
    write_registry(tmp_path, {"x": {"allowed": False, "argv": ["true"]}})
    with pytest.raises(CommandRunnerError, match="not allowed"):
        command_runner.resolve_command(tmp_path, "x")


def test_shell_string_argv_refused(tmp_path):
    write_registry(tmp_path, {"x": {"allowed": True, "argv": "echo hi && rm -rf /"}})
    with pytest.raises(CommandRunnerError, match="list of strings"):
        command_runner.resolve_command(tmp_path, "x")


# -- execution ---------------------------------------------------------------


def test_run_captures_output_and_artifact(tmp_path):
    data_dir = tmp_path / ".plan-auto"
    write_registry(
        data_dir,
        {"hello": {"allowed": True,
                   "argv": [sys.executable, "-c", "print('hi'); import sys; sys.exit(0)"]}},
    )
    result = command_runner.run_command(data_dir, "hello")
    assert result["exit_code"] == 0
    assert result["timed_out"] is False
    assert "hi" in result["stdout_tail"]
    artifact = tmp_path / result["artifact_uri"]
    assert artifact.exists()
    saved = json.loads(artifact.read_text())
    assert saved["command_id"] == "hello"
    assert "hi" in saved["stdout"]


def test_run_executes_in_project_root(tmp_path):
    data_dir = tmp_path / ".plan-auto"
    write_registry(
        data_dir,
        {"pwd": {"allowed": True,
                 "argv": [sys.executable, "-c", "import os; print(os.getcwd())"]}},
    )
    result = command_runner.run_command(data_dir, "pwd")
    assert result["stdout_tail"].strip() == str(tmp_path)


def test_timeout_enforced(tmp_path):
    data_dir = tmp_path / ".plan-auto"
    write_registry(
        data_dir,
        {"sleepy": {"allowed": True, "timeout_s": 1,
                    "argv": [sys.executable, "-c", "import time; time.sleep(30)"]}},
    )
    result = command_runner.run_command(data_dir, "sleepy")
    assert result["timed_out"] is True
    assert result["exit_code"] is None
    assert result["duration_s"] < 10


def test_missing_executable_instructs(tmp_path):
    data_dir = tmp_path / ".plan-auto"
    write_registry(data_dir, {"ghost": {"allowed": True, "argv": ["no-such-bin-xyz"]}})
    with pytest.raises(CommandRunnerError, match="failed to start"):
        command_runner.run_command(data_dir, "ghost")


# -- workspace integration ---------------------------------------------------


def make_approved_plan(ws: Workspace, command: str | None = "check") -> str:
    ws.register_project(
        {"name": "demo",
         "goals": [{"statement": "g", "metric_name": "m", "target": "t"}]}
    )
    evaluation = ws.create_plan(
        {
            "title": "measure",
            "kind": "measurement",
            "hypothesis": "h",
            "intervention": {"description": "probe", "allowed_files": ["probe.py"]},
            "validation_steps": [
                {"id": "V-1", "description": "run check", "kind": "command",
                 "command": command, "expected_result": "exit 0", "required": True}
            ],
            "decision_rule": {"adopt_if": ["ok"], "reject_if": ["bad"]},
        }
    )
    assert evaluation.plan_status == PlanStatus.READY_FOR_REVIEW
    ws.approve_plan(evaluation.plan_id, "Dana")
    return evaluation.plan_id


def test_run_validation_records_evidence_and_promotes(tmp_path):
    ws = Workspace(tmp_path)
    write_registry(
        tmp_path,
        {"check": {"allowed": True, "argv": [sys.executable, "-c", "print('ok')"]}},
    )
    plan_id = make_approved_plan(ws)
    outcome = ws.run_validation(plan_id, "V-1")
    assert outcome["passed"] is True
    assert outcome["evidence"]["polarity"] == "supports"
    assert outcome["evidence"]["linked_plan_id"] == plan_id
    assert ws.store.load_plan(plan_id).status == PlanStatus.EXECUTING
    events = [json.loads(l) for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert any(e["event"] == "validation_run" for e in events)


def test_run_validation_failure_records_refuting_evidence(tmp_path):
    ws = Workspace(tmp_path)
    write_registry(
        tmp_path,
        {"check": {"allowed": True,
                   "argv": [sys.executable, "-c", "import sys; sys.exit(3)"]}},
    )
    plan_id = make_approved_plan(ws)
    outcome = ws.run_validation(plan_id, "V-1")
    assert outcome["passed"] is False
    assert outcome["evidence"]["polarity"] == "refutes"
    assert "do not record 'validated'" in outcome["human_summary"]


def test_run_validation_requires_approval(tmp_path):
    ws = Workspace(tmp_path)
    write_registry(
        tmp_path,
        {"check": {"allowed": True, "argv": [sys.executable, "-c", "print(1)"]}},
    )
    ws.register_project(
        {"name": "demo",
         "goals": [{"statement": "g", "metric_name": "m", "target": "t"}]}
    )
    evaluation = ws.create_plan(
        {"title": "draft only", "kind": "measurement",
         "validation_steps": [{"id": "V-1", "description": "d", "command": "check"}]}
    )
    with pytest.raises(WorkspaceError, match="approved"):
        ws.run_validation(evaluation.plan_id, "V-1")


def test_run_validation_manual_step_instructs(tmp_path):
    ws = Workspace(tmp_path)
    write_registry(tmp_path, {})
    plan_id = make_approved_plan(ws, command=None)
    with pytest.raises(WorkspaceError, match="no command id"):
        ws.run_validation(plan_id, "V-1")


def test_run_validation_unknown_step_lists_steps(tmp_path):
    ws = Workspace(tmp_path)
    write_registry(
        tmp_path,
        {"check": {"allowed": True, "argv": [sys.executable, "-c", "print(1)"]}},
    )
    plan_id = make_approved_plan(ws)
    with pytest.raises(WorkspaceError, match="V-1"):
        ws.run_validation(plan_id, "V-nope")
