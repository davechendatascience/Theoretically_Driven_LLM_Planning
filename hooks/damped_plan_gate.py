#!/usr/bin/env python3
"""Claude Code PreToolUse hook: deny Edit/Write when no approved plan covers
the file. Stdlib-only; reads the precomputed .damped-plan/gate.json and never
starts the MCP server.

Opt-in per project via .claude/settings.json (see hooks/README.md).

Modes via DAMPED_PLAN_HOOK_MODE:
  enforce (default)  uncovered file -> permissionDecision "deny"
  warn               uncovered file -> permissionDecision "escalate"
                     (surfaces the gate verdict to the human instead of denying)
  strict             like enforce, but a corrupt/unreadable gate.json also denies

Fail-open by design: no gate.json found (project doesn't use damped-plan)
-> silent allow, so the hook never bricks unrelated projects.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}


def find_gate(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / ".damped-plan" / "gate.json"
        if candidate.is_file():
            return candidate
    return None


def matches(rel_path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        # `**/`-style and bare-name patterns should match any depth.
        if pattern.startswith("**/") and fnmatch.fnmatch(
            rel_path, pattern.removeprefix("**/")
        ):
            return True
        if "/" not in pattern and fnmatch.fnmatch(Path(rel_path).name, pattern):
            return True
        # A directory glob like "src/**" should also cover "src/x/y.py".
        if pattern.endswith("/**") and (
            rel_path == pattern.removesuffix("/**")
            or rel_path.startswith(pattern.removesuffix("**"))
        ):
            return True
    return False


def decision(permission: str, reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": permission,
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def main() -> None:
    mode = os.environ.get("DAMPED_PLAN_HOOK_MODE", "enforce").strip().lower()
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    if event.get("tool_name") not in EDIT_TOOLS:
        sys.exit(0)

    tool_input = event.get("tool_input") or {}
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw_path:
        sys.exit(0)

    cwd = Path(event.get("cwd") or os.getcwd())
    target = Path(raw_path)
    if not target.is_absolute():
        target = cwd / target
    target = Path(os.path.normpath(target))

    gate_path = find_gate(target.parent)
    if gate_path is None:
        gate_path_from_cwd = find_gate(cwd)
        if gate_path_from_cwd is None:
            sys.exit(0)  # project does not use damped-plan: fail open
        gate_path = gate_path_from_cwd

    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if mode == "strict":
            decision(
                "deny",
                f"damped-plan gate file {gate_path} is unreadable and "
                f"DAMPED_PLAN_HOOK_MODE=strict; refusing to edit.",
            )
        sys.exit(0)

    project_root = gate_path.parent.parent
    try:
        rel_path = target.relative_to(project_root).as_posix()
    except ValueError:
        sys.exit(0)  # outside the gated project: not our concern

    if matches(rel_path, gate.get("always_allowed") or []):
        sys.exit(0)

    covering = [
        plan.get("plan_id")
        for plan in gate.get("open_plans") or []
        if matches(rel_path, plan.get("allowed_files") or [])
    ]
    if covering:
        sys.exit(0)

    permission = "escalate" if mode == "warn" else "deny"
    open_ids = [p.get("plan_id") for p in gate.get("open_plans") or []]
    reason = (
        f"damped-plan gate: '{rel_path}' is not covered. "
        f"{gate.get('deny_message', '')} "
        f"(open plans: {open_ids or 'none'})"
    )
    decision(permission, reason)


if __name__ == "__main__":
    main()
