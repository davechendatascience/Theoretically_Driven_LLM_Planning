#!/usr/bin/env python3
"""Wire plan-auto into a target project, on Linux, macOS, or Windows.

The four integration pieces (MCP server, skill, reviewer agent, PreToolUse
hooks) are all configured with host-specific absolute paths and an interpreter
name that is not the same everywhere: Windows has no `python3`, and many Linux
distributions have no `python`. Hand-editing the JSON from the README means
getting both right by hand, per machine. This script derives them.

    uv run python scripts/install_integration.py --target /path/to/project
    uv run python scripts/install_integration.py --dry-run

Stdlib-only and version-tolerant on purpose: it must be runnable by whatever
interpreter the host happens to have, before the project venv exists.

What it writes into the target project:
  .mcp.json                    MCP server registration
  .claude/skills/plan-auto/  the /plan-auto skill
  .claude/agents/plan-reviewer.md
  .claude/settings.local.json  the two PreToolUse hook registrations

Existing JSON is merged, never clobbered: unrelated keys, servers, and hooks
survive, and re-running is idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

GATE_HOOK = REPO_ROOT / "hooks" / "plan_auto_gate.py"
REVIEWER_HOOK = REPO_ROOT / "hooks" / "plan_auto_reviewer_gate.py"
SKILL_SRC = REPO_ROOT / "skills" / "plan-auto"
AGENT_SRC = REPO_ROOT / "agents" / "plan-reviewer.md"

# The implementer gate matches the edit tools; the reviewer gate matches the
# execution tools, which on Windows means PowerShell as well as Bash.
GATE_MATCHER = "Edit|Write|NotebookEdit"
REVIEWER_MATCHER = "Bash|PowerShell"


# --- interpreter discovery --------------------------------------------------


def find_interpreter() -> str:
    """Return a command that runs the stdlib-only hooks in any shell.

    Prefers a bare name found on PATH over an absolute path, because a bare
    name needs no quoting and therefore behaves identically under sh, Git Bash,
    cmd.exe, and PowerShell. An absolute fallback path is quoted, which
    PowerShell would treat as a string literal rather than a command unless
    prefixed with `&` -- so it is a last resort, and reported as such.
    """
    for name in ("python3", "python"):
        path = shutil.which(name)
        if path is None:
            continue
        try:
            proc = subprocess.run(
                [path, "-c", "import sys; print(sys.version_info[0])"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0 and proc.stdout.strip() == "3":
            return name
    return quote(sys.executable)


def quote(path: str) -> str:
    return path if " " not in path else '"{}"'.format(path)


def hook_command(interpreter: str, script: Path) -> str:
    return "{} {}".format(interpreter, quote(script.as_posix()))


# --- JSON merge helpers -----------------------------------------------------


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        # utf-8-sig: a settings file previously written by a Windows editor may
        # carry a BOM, which json.loads rejects.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            "Refusing to touch {}: it is not readable JSON ({}). Fix or move "
            "it, then re-run.".format(path, exc)
        )
    if not isinstance(data, dict):
        raise SystemExit(
            "Refusing to touch {}: expected a JSON object.".format(path)
        )
    return data


def write_json(path: Path, data: dict, dry_run: bool) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if dry_run:
        print("--- would write {} ---".format(path))
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print("wrote {}".format(path))


def upsert_hook(settings: dict, matcher: str, command: str, script: Path) -> None:
    """Add or refresh one PreToolUse entry, leaving unrelated hooks alone."""
    pre = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    entry = {"type": "command", "command": command}
    marker = script.name

    for group in pre:
        if not isinstance(group, dict):
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            continue
        for index, existing in enumerate(hooks):
            # Identify our own prior registration by the script filename, so a
            # moved checkout or a changed interpreter updates in place instead
            # of stacking a second copy.
            if isinstance(existing, dict) and marker in str(existing.get("command", "")):
                hooks[index] = entry
                group["matcher"] = matcher
                return

    pre.append({"matcher": matcher, "hooks": [entry]})


# --- install steps ----------------------------------------------------------


def install_mcp(target: Path, data_dir: Path | None, dry_run: bool) -> None:
    config = load_json(target / ".mcp.json")
    servers = config.setdefault("mcpServers", {})

    if target == REPO_ROOT:
        # Dogfooding this repo: `uv --directory .` resolves against the cwd the
        # client launches the server in, which is the project root, and the
        # server's own fallback then puts the data dir alongside it. Relative
        # keeps the committed file valid on every machine.
        directory = "."
        env = {}
    else:
        directory = str(REPO_ROOT)
        resolved = data_dir if data_dir is not None else target / ".plan-auto"
        env = {"PLAN_AUTO_DATA_DIR": str(resolved)}

    server = {
        "command": "uv",
        "args": ["--directory", directory, "run", "plan-auto"],
    }
    if env:
        server["env"] = env
    servers["plan-auto"] = server
    write_json(target / ".mcp.json", config, dry_run)


def install_tree(src: Path, dest: Path, dry_run: bool) -> None:
    if not src.exists():
        print("skip: {} is missing".format(src))
        return
    if dry_run:
        print("would copy {} -> {}".format(src, dest))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    print("installed {}".format(dest))


def install_hooks(target: Path, shared: bool, interpreter: str, dry_run: bool) -> None:
    name = "settings.json" if shared else "settings.local.json"
    path = target / ".claude" / name
    settings = load_json(path)
    upsert_hook(settings, GATE_MATCHER, hook_command(interpreter, GATE_HOOK), GATE_HOOK)
    upsert_hook(
        settings,
        REVIEWER_MATCHER,
        hook_command(interpreter, REVIEWER_HOOK),
        REVIEWER_HOOK,
    )
    write_json(path, settings, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=os.getcwd(),
        help="project to gate (default: current directory)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="where plans/evidence live (default: <target>/.plan-auto)",
    )
    parser.add_argument("--no-hooks", action="store_true", help="skip the PreToolUse hooks")
    parser.add_argument("--no-skill", action="store_true", help="skip the /plan-auto skill")
    parser.add_argument(
        "--no-reviewer", action="store_true", help="skip the plan-reviewer agent"
    )
    parser.add_argument(
        "--shared-settings",
        action="store_true",
        help="write hooks to .claude/settings.json (committed) instead of settings.local.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="print instead of writing")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not target.is_dir():
        raise SystemExit("--target {} is not a directory".format(target))
    data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else None

    interpreter = find_interpreter()
    print("repo:        {}".format(REPO_ROOT))
    print("target:      {}".format(target))
    print("interpreter: {}".format(interpreter))
    if interpreter.startswith('"'):
        print(
            "  note: no bare python/python3 on PATH, so the hook command uses a\n"
            "  quoted absolute path. That works in sh, Git Bash, and cmd.exe; if\n"
            "  your hooks run through PowerShell, prefix the command with '& '."
        )
    print("")

    install_mcp(target, data_dir, args.dry_run)
    if not args.no_skill:
        install_tree(SKILL_SRC, target / ".claude" / "skills" / "plan-auto", args.dry_run)
    if not args.no_reviewer:
        install_tree(AGENT_SRC, target / ".claude" / "agents" / "plan-reviewer.md", args.dry_run)
    if not args.no_hooks:
        install_hooks(target, args.shared_settings, interpreter, args.dry_run)

    print("\nDone. Restart Claude Code in {} and check /mcp.".format(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
