#!/usr/bin/env python3
"""Claude Code PreToolUse hook: keep the advisory plan-reviewer from executing.

The damped-plan reviewer is an *evidence consumer*. Evidence enters the ledger
through `run_validation` (mechanical: allowlisted argv, immutable artifact,
polarity from the exit code) or `record_evidence` (narrated, by the
implementing session) — never through a reviewer's own shell. A reviewer that
re-runs the suite produces a number with no `artifact_uri` and no event, which
is precisely the hand-narrated evidence its own depth policy distrusts.

So this hook denies `Bash` for reviewer agents, *except* read-only inspection
(`git diff`, `cat`, `grep`, ...) — the reviewer still needs to read the diff
its predictive-contract review compares against `context_fixed`.

Opt-in per project via .claude/settings.json (see hooks/README.md).

Configuration:
  DAMPED_PLAN_REVIEWER_AGENTS       comma-separated agent types to gate
                                    (default: "plan-reviewer")
  DAMPED_PLAN_REVIEWER_HOOK_MODE
      enforce (default)  disallowed command -> permissionDecision "deny"
      warn               disallowed command -> permissionDecision "escalate"

Fail-open by design: any other agent_type — the main session included — passes
through untouched, so the hook never interferes with ordinary work. Like
.damped-plan/commands.json, this is an allowlist for reviewable provenance and
a discipline boundary, not a security sandbox.
"""

from __future__ import annotations

import json
import os
import shlex
import sys

DEFAULT_REVIEWER_AGENTS = ("plan-reviewer",)

# Windows hosts expose a second execution tool alongside Bash. Gating only
# "Bash" there would leave an unguarded execution path open the moment anyone
# widens the reviewer's tool allowlist, so both names are matched. Register the
# hook with matcher "Bash|PowerShell" to match.
GATED_TOOLS = frozenset({"Bash", "PowerShell"})

# Anything that could chain, substitute, or redirect past the argv check.
CHAINING_CHARS = frozenset(";|&`$><\n")

READ_ONLY_COMMANDS = frozenset(
    {"cat", "head", "tail", "ls", "wc", "grep", "rg", "jq", "find"}
)
GIT_READ_ONLY_SUBCOMMANDS = frozenset(
    {"diff", "status", "log", "show", "rev-parse", "ls-files"}
)
# `git -C <path>` / `git -c <k>=<v>` take a value; other leading options do not.
GIT_VALUE_OPTIONS = frozenset({"-C", "-c"})
# find(1) can execute and delete; those subvert the whole point of the hook.
FIND_EXECUTING_OPTIONS = frozenset(
    {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprintf", "-fprint"}
)

DENY_REASON = (
    "damped-plan: the plan-reviewer is advisory and does not execute — "
    "`{command}` is denied. Evidence reaches the ledger through run_validation "
    "(artifact under .damped-plan/artifacts/) or the implementing session's "
    "record_evidence, never through a reviewer's shell: a number you produce "
    "here has no artifact_uri and no event, and is exactly the hand-narrated "
    "evidence your depth policy tells you to distrust. Cite the recorded "
    "artifact instead — and if no artifact backs the claim, that absence IS "
    "your finding. Read-only inspection (git diff/status/log/show, cat, grep, "
    "ls, wc, jq, find) is still available."
)


def read_event() -> dict | None:
    """Parse the PreToolUse payload from stdin, or None if it is unusable.

    Decoded as utf-8-sig, not utf-8: PowerShell prepends a UTF-8 BOM when it
    pipes to a native executable, and a leading BOM raises JSONDecodeError.
    Because an unparsable payload exits 0 (fail-open), that would silently
    disable the hook on Windows rather than announce itself.
    """
    try:
        raw = sys.stdin.buffer.read()
    except AttributeError:  # stdin replaced by a text-only object
        raw = sys.stdin.read().encode("utf-8", "replace")
    try:
        event = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return event if isinstance(event, dict) else None


def gated_agents() -> frozenset[str]:
    raw = os.environ.get("DAMPED_PLAN_REVIEWER_AGENTS")
    if raw is None:
        return frozenset(DEFAULT_REVIEWER_AGENTS)
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def git_is_read_only(argv: list[str]) -> bool:
    rest = argv[1:]
    while rest:
        token = rest[0]
        if not token.startswith("-"):
            return token in GIT_READ_ONLY_SUBCOMMANDS
        rest = rest[2:] if token in GIT_VALUE_OPTIONS else rest[1:]
    return False  # bare `git` with no subcommand


def is_read_only(command: str) -> bool:
    if CHAINING_CHARS & set(command):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False  # unbalanced quoting: we cannot tell what would run
    if not argv:
        return False
    if argv[0] == "git":
        return git_is_read_only(argv)
    if argv[0] == "find":
        return not (FIND_EXECUTING_OPTIONS & set(argv[1:]))
    return argv[0] in READ_ONLY_COMMANDS


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
    event = read_event()
    if event is None:
        sys.exit(0)

    if event.get("tool_name") not in GATED_TOOLS:
        sys.exit(0)

    if event.get("agent_type") not in gated_agents():
        sys.exit(0)  # main session and every other agent: not our concern

    command = (event.get("tool_input") or {}).get("command") or ""
    if is_read_only(command):
        sys.exit(0)

    mode = (
        os.environ.get("DAMPED_PLAN_REVIEWER_HOOK_MODE", "enforce").strip().lower()
    )
    permission = "escalate" if mode == "warn" else "deny"
    decision(permission, DENY_REASON.format(command=command.strip() or "(empty)"))


if __name__ == "__main__":
    main()
