"""Subprocess tests for hooks/damped_plan_reviewer_gate.py (stdlib-only hook)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = (
    Path(__file__).resolve().parents[2] / "hooks" / "damped_plan_reviewer_gate.py"
)


def run_hook(event: dict, **env_extra: str) -> tuple[int, dict | None]:
    env = {"PATH": "/usr/bin:/bin", **env_extra}
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    output = None
    if proc.stdout.strip():
        output = json.loads(proc.stdout)
    return proc.returncode, output


def bash_event(command: str, agent_type: str | None = "plan-reviewer") -> dict:
    event: dict = {"tool_name": "Bash", "tool_input": {"command": command}}
    if agent_type is not None:
        event["agent_type"] = agent_type
    return event


def permission(output: dict | None) -> str | None:
    if output is None:
        return None
    return output["hookSpecificOutput"]["permissionDecision"]


# --- pass-through: everything that is not a gated agent's Bash call ---------


def test_non_bash_tool_ignored():
    event = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/x"},
        "agent_type": "plan-reviewer",
    }
    code, output = run_hook(event)
    assert code == 0 and output is None


def test_main_session_unaffected():
    code, output = run_hook(bash_event("uv run pytest -q", agent_type="main"))
    assert code == 0 and output is None


def test_other_subagent_unaffected():
    code, output = run_hook(bash_event("uv run pytest -q", agent_type="Explore"))
    assert code == 0 and output is None


def test_missing_agent_type_ignored():
    code, output = run_hook(bash_event("uv run pytest -q", agent_type=None))
    assert code == 0 and output is None


def test_malformed_stdin_allows():
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        timeout=10,
    )
    assert proc.returncode == 0 and proc.stdout.strip() == ""


# --- execution is denied for the reviewer ----------------------------------


def test_reviewer_denied_test_run():
    code, output = run_hook(bash_event("uv run pytest -q"))
    assert code == 0
    assert permission(output) == "deny"
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert ".damped-plan/artifacts/" in reason
    assert "uv run pytest -q" in reason


def test_reviewer_denied_arbitrary_script():
    code, output = run_hook(bash_event("python3 scripts/demo_end_to_end.py"))
    assert permission(output) == "deny"


def test_reviewer_denied_chaining_past_allowlist():
    code, output = run_hook(bash_event("cat README.md && uv run pytest -q"))
    assert permission(output) == "deny"


def test_reviewer_denied_redirect():
    code, output = run_hook(bash_event("cat README.md > /tmp/steal.txt"))
    assert permission(output) == "deny"


def test_reviewer_denied_command_substitution():
    code, output = run_hook(bash_event("echo $(uv run pytest -q)"))
    assert permission(output) == "deny"


def test_reviewer_denied_git_write_subcommand():
    code, output = run_hook(bash_event("git push origin main"))
    assert permission(output) == "deny"


def test_reviewer_denied_find_exec():
    code, output = run_hook(bash_event("find . -name '*.py' -exec rm {} +"))
    assert permission(output) == "deny"


def test_reviewer_denied_empty_command():
    code, output = run_hook(bash_event(""))
    assert permission(output) == "deny"


def test_reviewer_denied_unbalanced_quotes():
    code, output = run_hook(bash_event("cat 'README.md"))
    assert permission(output) == "deny"


# --- read-only inspection stays available ----------------------------------


def test_reviewer_allowed_git_diff():
    code, output = run_hook(bash_event("git diff --stat HEAD~1"))
    assert code == 0 and output is None


def test_reviewer_allowed_git_with_value_option():
    code, output = run_hook(bash_event("git -C /repo --no-pager log --oneline -5"))
    assert code == 0 and output is None


def test_reviewer_allowed_reading_an_artifact():
    code, output = run_hook(
        bash_event("cat .damped-plan/artifacts/20260817T080034-unit_tests.json")
    )
    assert code == 0 and output is None


def test_reviewer_allowed_plain_find():
    code, output = run_hook(bash_event("find .damped-plan/evidence -name 'EV-*.json'"))
    assert code == 0 and output is None


# --- configuration ---------------------------------------------------------


def test_warn_mode_escalates_instead_of_denying():
    code, output = run_hook(
        bash_event("uv run pytest -q"), DAMPED_PLAN_REVIEWER_HOOK_MODE="warn"
    )
    assert permission(output) == "escalate"


def test_gated_agents_configurable():
    code, output = run_hook(
        bash_event("uv run pytest -q", agent_type="my-reviewer"),
        DAMPED_PLAN_REVIEWER_AGENTS="my-reviewer, another-reviewer",
    )
    assert permission(output) == "deny"


def test_empty_agent_list_makes_hook_inert():
    code, output = run_hook(
        bash_event("uv run pytest -q"), DAMPED_PLAN_REVIEWER_AGENTS=""
    )
    assert code == 0 and output is None
