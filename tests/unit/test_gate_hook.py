"""Subprocess tests for hooks/plan_auto_gate.py (stdlib-only hook)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "plan_auto_gate.py"


def run_hook(event: dict, env_mode: str | None = None) -> tuple[int, dict | None]:
    env = {"PATH": "/usr/bin:/bin"}
    if env_mode:
        env["PLAN_AUTO_HOOK_MODE"] = env_mode
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


def write_gate(
    tmp_path: Path,
    open_plans: list[dict],
    always: list[str] | None = None,
    human: list[str] | None = None,
):
    gate_dir = tmp_path / ".plan-auto"
    gate_dir.mkdir(parents=True, exist_ok=True)
    (gate_dir / "gate.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate_open": bool(open_plans),
                "open_plans": open_plans,
                "always_allowed": always if always is not None else [".plan-auto/**", "docs/**", "*.md"],
                "deny_message": "No approved plan covers this file.",
                **({} if human is None else {"human_supervised": human}),
            }
        )
    )


HUMAN_SUPERVISED = [
    ".plan-auto/corpus/**",
    ".plan-auto/commands.json",
    ".plan-auto/objective.md",
    ".plan-auto/artifacts/**",
]


def edit_event(tmp_path: Path, rel_path: str, tool: str = "Edit") -> dict:
    return {
        "tool_name": tool,
        "tool_input": {"file_path": str(tmp_path / rel_path)},
        "cwd": str(tmp_path),
    }


def test_no_gate_file_allows(tmp_path):
    code, output = run_hook(edit_event(tmp_path, "src/x.py"))
    assert code == 0 and output is None


def test_non_edit_tool_ignored(tmp_path):
    write_gate(tmp_path, [])
    event = edit_event(tmp_path, "src/x.py", tool="Bash")
    code, output = run_hook(event)
    assert code == 0 and output is None


def test_uncovered_file_denied(tmp_path):
    write_gate(tmp_path, [])
    code, output = run_hook(edit_event(tmp_path, "src/x.py"))
    assert code == 0
    hook_output = output["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "deny"
    assert "src/x.py" in hook_output["permissionDecisionReason"]


def test_covered_file_allowed(tmp_path):
    write_gate(
        tmp_path,
        [{"plan_id": "P-1", "allowed_files": ["src/policy/*.py", "tests/**"]}],
    )
    code, output = run_hook(edit_event(tmp_path, "src/policy/head.py"))
    assert code == 0 and output is None
    code, output = run_hook(edit_event(tmp_path, "tests/unit/test_head.py"))
    assert code == 0 and output is None


def test_sibling_file_still_denied(tmp_path):
    write_gate(tmp_path, [{"plan_id": "P-1", "allowed_files": ["src/policy/*.py"]}])
    code, output = run_hook(edit_event(tmp_path, "src/other/module.py"))
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "P-1" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_always_allowed_paths(tmp_path):
    write_gate(tmp_path, [])
    code, output = run_hook(edit_event(tmp_path, "README.md"))
    assert code == 0 and output is None
    code, output = run_hook(edit_event(tmp_path, "docs/notes.md"))
    assert code == 0 and output is None


def test_warn_mode_escalates_to_human(tmp_path):
    write_gate(tmp_path, [])
    code, output = run_hook(edit_event(tmp_path, "src/x.py"), env_mode="warn")
    assert output["hookSpecificOutput"]["permissionDecision"] == "escalate"


def test_corrupt_gate_strict_denies(tmp_path):
    gate_dir = tmp_path / ".plan-auto"
    gate_dir.mkdir(parents=True)
    (gate_dir / "gate.json").write_text("{not json")
    code, output = run_hook(edit_event(tmp_path, "src/x.py"), env_mode="strict")
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    # default mode fails open on corruption
    code, output = run_hook(edit_event(tmp_path, "src/x.py"))
    assert code == 0 and output is None


def test_relative_path_resolved_against_cwd(tmp_path):
    write_gate(tmp_path, [{"plan_id": "P-1", "allowed_files": ["src/ok.py"]}])
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": "src/ok.py"},
        "cwd": str(tmp_path),
    }
    code, output = run_hook(event)
    assert code == 0 and output is None


# --- cross-platform payload handling ---------------------------------------


def run_hook_bytes(payload: bytes) -> tuple[int, dict | None]:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
        timeout=10,
    )
    output = None
    if proc.stdout.strip():
        output = json.loads(proc.stdout)
    return proc.returncode, output


def test_utf8_bom_payload_still_denies(tmp_path):
    """PowerShell prepends a BOM when piping to a native exe.

    Parsed as plain utf-8 the BOM raises JSONDecodeError, which this hook
    treats as fail-open -- so the gate would silently allow every edit on
    Windows while still looking installed.
    """
    write_gate(tmp_path, [])
    payload = b"\xef\xbb\xbf" + json.dumps(edit_event(tmp_path, "src/x.py")).encode()
    code, output = run_hook_bytes(payload)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_unparsable_payload_still_fails_open():
    code, output = run_hook_bytes(b"not json at all")
    assert code == 0 and output is None


# --- human-supervised paths (P-0011) ----------------------------------------
#
# always_allowed contains ".plan-auto/**", which matches every protected path.
# So these deny only if the check runs BEFORE it. A deny list placed after the
# always_allowed exit is dead code and every test below would fail.


@pytest.mark.parametrize(
    "rel",
    [
        ".plan-auto/corpus/x.pdf",
        ".plan-auto/corpus/reflexive-eval/deep/nested.url",
        ".plan-auto/commands.json",
        ".plan-auto/objective.md",
        ".plan-auto/artifacts/x.json",
        ".plan-auto/artifacts/run/out.txt",
    ],
)
def test_human_supervised_denied_despite_always_allowed(tmp_path, rel):
    write_gate(tmp_path, [], human=HUMAN_SUPERVISED)
    code, out = run_hook(edit_event(tmp_path, rel))
    assert code == 0
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "HUMAN-SUPERVISED" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_human_supervised_denied_even_under_a_covering_plan(tmp_path):
    """Not even an approved plan may authorise it — this is the point."""
    write_gate(
        tmp_path,
        [{"plan_id": "P-x", "allowed_files": [".plan-auto/corpus/**"]}],
        human=HUMAN_SUPERVISED,
    )
    code, out = run_hook(edit_event(tmp_path, ".plan-auto/corpus/x.pdf"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "rel",
    [
        ".plan-auto/plans/P-1.json",
        ".plan-auto/evidence/EV-1.json",
        ".plan-auto/events.jsonl",
        ".plan-auto/gate.json",
        ".plan-auto/project.json",
        ".plan-auto/corpus-notes.md",
    ],
)
def test_ordinary_ledger_writes_still_allowed(tmp_path, rel):
    """Over-denial control. A pattern that swallowed the store would block every
    agent edit to the ledger — note the server itself writes in-process and never
    passes through this hook, so the hazard is agent-side, not server-side."""
    write_gate(tmp_path, [], human=HUMAN_SUPERVISED)
    code, out = run_hook(edit_event(tmp_path, rel))
    assert code == 0 and out is None, f"{rel} should be permitted, got {out}"


def test_gate_without_the_key_behaves_as_before(tmp_path):
    """Backward compatibility for every gate.json written before this existed."""
    write_gate(tmp_path, [], human=None)
    code, out = run_hook(edit_event(tmp_path, ".plan-auto/corpus/x.pdf"))
    assert code == 0 and out is None


def test_bash_still_bypasses_the_boundary(tmp_path):
    """DOCUMENTS A HOLE rather than asserting a guarantee.

    The hook gates Edit/Write/NotebookEdit only. An agent with shell access can
    still author every protected path. If this test ever starts failing, the Bash
    surface has been gated and the ledger conclusion in P-0011 can be widened.
    """
    write_gate(tmp_path, [], human=HUMAN_SUPERVISED)
    code, out = run_hook(
        edit_event(tmp_path, ".plan-auto/commands.json", tool="Bash")
    )
    assert code == 0 and out is None
