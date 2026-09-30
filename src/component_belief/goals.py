"""Your goals, the interfaces between them, and how each is measured: the declarations only you commit.

belief.yaml is the agent's -- its components, contracts and thresholds, committed as it works.
goals.yaml is yours: each goal's outcome and the contract that says it is met, each interface
between goals and the contract its hand-over must pass, and the tests those run. The agent may
change anything below your goals; only you change what a goal is and how it is measured.

What holds that line is aimed at drift -- an agent that, stuck, relaxes a measure and sincerely
reports progress -- not at an agent working around you on purpose, which only credentials it does
not hold can stop:

  - the guard: a git commit-msg hook that refuses a commit carrying the agent's trailer
    (Co-Authored-By: Claude) when it changes the goal set, goals.yaml and every file its tests
    name. You commit goal changes yourself; the agent drafts them and leaves a note on the goal.
  - the record: every agent commit to the goal set since your last one, shown in the goals view
    and by stamp-monitor's workflow. Your next commit to the goal set takes them in.
  - the decision rule: an adoption under a policy in goals.yaml needs no approver, because you
    approved its criteria by committing them -- unless the agent has changed the goal set since.

The trailer is a convention the agent keeps, not a credential; a commit you type yourself carries
none, so it passes.
"""

from __future__ import annotations

import argparse
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .declarations import GOALS_FILE, Declarations
from .model import (STATE_CONTESTED, STATE_INSUFFICIENT, STATE_REFUTED, STATE_STALE,
                    STATE_SUPPORTED, Slice)
from .render import basis_line, bullet, envelope, slice_line
from .staleness import named_paths

#: Where released versions of this harness install from; a release is tagged tdlp--v<version>.
RELEASES = "git+https://github.com/davechendatascience/Theoretically_Driven_LLM_Planning"
AGENT_MARK = re.compile(r"(?im)^co-authored-by:\s*claude\b")
GUARD_MARK = "# tdlp goal guard"
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60,
                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _split0(text: str | None) -> list[str]:
    return [p for p in (text or "").split("\0") if p]


def is_agent_commit(message: str) -> bool:
    return bool(AGENT_MARK.search(message or ""))


# ---------- the goal set ----------

def goal_set(root: Path, *goal_texts: str | None) -> set[str]:
    """goals.yaml and every file its tests name on a run line or in `reads:` -- the files that
    decide what your goals mean and how they are measured."""
    known = set(_split0(_git(root, "ls-files", "-z")))
    known |= set(_split0(_git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD")))
    paths = {GOALS_FILE}
    for text in goal_texts:
        try:
            data = yaml.safe_load(text or "") or {}
        except yaml.YAMLError:
            continue
        for raw in (data.get("tests") or []) if isinstance(data, dict) else []:
            if isinstance(raw, dict):
                reads = [str(r) for r in raw.get("reads") or []]
                paths |= set(named_paths(str(raw.get("run", "")), reads, known))
    return paths


def goal_history(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The agent's commits to the goal set since your last one (newest first), and your last one."""
    paths = sorted(goal_set(root, _git(root, "show", f"HEAD:{GOALS_FILE}")))
    changes: list[dict[str, Any]] = []
    for sha in (_git(root, "log", "--format=%H", "--", *paths) or "").split():
        message = (_git(root, "show", "-s", "--format=%B", sha) or "").strip()
        entry = {"sha": sha[:7], "subject": message.splitlines()[0] if message else ""}
        if not is_agent_commit(message):
            return changes, entry
        entry["files"] = _split0(_git(root, "diff-tree", "--root", "--no-commit-id", "--name-only",
                                      "-r", "-z", sha, "--", *paths))
        changes.append(entry)
    return changes, None


def ratification_gap(root: Path, decl: Declarations, policy_id: str) -> str | None:
    """Why an adoption under this policy still needs a human approver, or None when your commit
    of goals.yaml already approved its criteria."""
    gap = decl.goal_policy_gap(policy_id)
    if gap:
        return gap
    changes, _ = goal_history(root)
    if changes:
        latest = changes[0]
        return (f"the agent changed your goal set in {latest['sha']} "
                f"({', '.join(latest['files'][:3])}) since you last committed it")
    return None


# ---------- the guard ----------

def _staged(root: Path) -> list[str]:
    base = "HEAD" if _git(root, "rev-parse", "--verify", "-q", "HEAD") is not None else _EMPTY_TREE
    return _split0(_git(root, "diff", "--cached", "--name-only", "-z", base))


def check_commit(root: Path, message: str) -> list[str]:
    """The goal-set paths this commit would change if the agent is making it; [] lets it through.

    Read from the index being committed (git points GIT_INDEX_FILE at it for `commit -a`), and
    against goals.yaml both as staged and at HEAD, so removing a test from goals.yaml does not
    free the file it named in the same commit."""
    if not is_agent_commit(message):
        return []
    protected = goal_set(root, _git(root, "show", f":{GOALS_FILE}"), _git(root, "show", f"HEAD:{GOALS_FILE}"))
    return sorted(set(_staged(root)) & protected)


def hooks_dir(root: Path) -> Path | None:
    out = _git(root, "rev-parse", "--git-path", "hooks")
    if out is None:
        return None
    path = Path(out.strip())
    return path if path.is_absolute() else root / path


def guard_installed(root: Path) -> bool:
    directory = hooks_dir(root)
    hook = directory / "commit-msg" if directory else None
    return bool(hook and hook.is_file()
                and GUARD_MARK in hook.read_text(encoding="utf-8", errors="replace"))


def release_command() -> str:
    """The guard as this version released it: installs once with uvx, then runs from its cache."""
    return f'uvx --quiet --from "{RELEASES}@tdlp--v{__version__}" tdlp-guard check'


class GuardError(Exception):
    pass


def install(root: Path, command: str | None = None, force: bool = False) -> Path:
    directory = hooks_dir(root)
    if directory is None:
        raise GuardError(f"{root} is not a git repository")
    hook = directory / "commit-msg"
    if hook.exists() and not force and GUARD_MARK not in hook.read_text(encoding="utf-8", errors="replace"):
        raise GuardError(f"{hook} exists and is not the tdlp guard; rerun with --force to replace it")
    directory.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        f"{GUARD_MARK}: refuses an agent's commit that changes your goal set.\n"
        "# Installed by `tdlp-guard install`; delete this file to remove it.\n"
        "export UV_LINK_MODE=copy\n"
        f'exec {command or release_command()} "$1"\n',
        encoding="utf-8", newline="\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook


def _refusal(paths: list[str]) -> str:
    return (
        "tdlp guard: refused. This commit carries the agent's trailer (Co-Authored-By: Claude) and "
        f"changes your goal set: {', '.join(paths)}.\n"
        "Goals, their measures and the tests those run are committed by the human.\n"
        "  agent: unstage them (git restore --staged <paths>), commit the rest, and leave the proposal\n"
        "         as note(subject=\"GOL-...\", text=...) on the goal it concerns.\n"
        "  human: commit these paths yourself; a commit you type carries no trailer.")


def guard_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tdlp-guard", description="Keep the goal set -- goals.yaml and the tests it runs -- yours.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="the commit-msg hook: refuse an agent's commit to the goal set")
    check.add_argument("message_file")
    add = sub.add_parser("install", help="install the commit-msg hook in this clone")
    add.add_argument("--force", action="store_true", help="replace a commit-msg hook that is not this one")
    add.add_argument("--command", help="what the hook runs instead of this release's pinned guard, "
                                       "e.g. a dev checkout's 'python -m component_belief.goals check'")
    args = parser.parse_args(argv)
    top = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    root = Path(top.strip()) if top else Path.cwd()

    if args.command == "check":
        message = Path(args.message_file).read_text(encoding="utf-8", errors="replace")
        paths = check_commit(root, message)
        if paths:
            print(_refusal(paths), file=sys.stderr)
            return 1
        return 0
    try:
        hook = install(root, args.command, args.force)
    except GuardError as exc:
        print(f"tdlp-guard: {exc}", file=sys.stderr)
        return 1
    print(f"installed {hook}: an agent's commit that changes {GOALS_FILE} or a file its tests name "
          "is refused; yours pass")
    return 0


# ---------- the view ----------

_WORST_FIRST = (STATE_REFUTED, STATE_STALE, STATE_CONTESTED, STATE_INSUFFICIENT, STATE_SUPPORTED)
_WORDS = {STATE_REFUTED: "NOT MET", STATE_STALE: "STALE", STATE_CONTESTED: "UNDECIDED",
          STATE_INSUFFICIENT: "INSUFFICIENT", STATE_SUPPORTED: "MET"}


def _headline(slices: list[Slice]) -> str:
    """One word per goal, the worst of its slices; an envelope that holds in some conditions says so."""
    if not slices:
        return "UNMEASURED"
    states = {s.state for s in slices}
    worst = next((s for s in _WORST_FIRST if s in states), sorted(states)[0])
    word = _WORDS.get(worst, worst.upper())
    return word + (" (met in some conditions)" if worst != STATE_SUPPORTED and STATE_SUPPORTED in states else "")


def _measure_lines(decl: Declarations, measure: str, slices: list[Slice]) -> list[str]:
    if slices:
        return [f"  {slice_line(s)}" for s in slices]
    if not measure:
        return ["  no measure declared"]
    tests = ", ".join(t.id for t in decl.tests_for(measure)) or "its test"
    return [f"  {measure}: no evidence yet -- run {tests}"]


def view_goals(ctx: Any) -> str:
    """The one read for checking in: is each goal met, is each hand-over sound, what does the agent
    propose, and has it touched what is yours."""
    decl: Declarations = ctx.decl
    install_hint = f'uvx --from "{RELEASES}@tdlp--v{__version__}" tdlp-guard install'
    if not decl.goals and not decl.goal_interfaces:
        issues = [i for i in decl.issues if i.subject == GOALS_FILE]
        body = [f"no goals in effect: {GOALS_FILE} is not committed at HEAD.",
                "Write your goals there -- each an outcome and the contract that says it is met, in "
                "belief.yaml's schema -- and commit it yourself."]
        if issues:
            body += ["", "issues:", bullet(i.render() for i in issues)]
        return envelope("\n".join(body), f"basis: declarations · {GOALS_FILE} absent at HEAD")

    measures = [g.measure for g in decl.goals.values()] + [b.measure for b in decl.goal_interfaces.values()]
    slices = ctx.slices(contract_ids=[m for m in measures if m in decl.contracts])
    by_contract: dict[str, list[Slice]] = {}
    for sl in slices:
        by_contract.setdefault(sl.contract_id, []).append(sl)
    changes, yours = goal_history(ctx.root)

    lines = [f"goals: {GOALS_FILE} at HEAD (blob {decl.goals_blob[:7]}) -- {len(decl.goals)} goal(s), "
             f"{len(decl.goal_interfaces)} interface(s)"]
    if yours:
        lines.append(f"  you last committed the goal set in {yours['sha']}: {yours['subject']}")
    for gid, goal in sorted(decl.goals.items()):
        own = by_contract.get(goal.measure, [])
        lines += ["", f"{gid}  {_headline(own)} -- {goal.outcome}"]
        lines += _measure_lines(decl, goal.measure, own)
        served = decl.components_of_subject(gid)
        lines.append(f"  served by: {', '.join(served) if served else 'no component names this goal'}")
    if decl.goal_interfaces:
        lines += ["", "interfaces between goals:"]
        for iid, between in sorted(decl.goal_interfaces.items()):
            own = by_contract.get(between.measure, [])
            lines.append(f"{iid}  {between.from_goal} -> {between.to_goal}  {_headline(own)} "
                         f"-- {between.hands_over}")
            lines += _measure_lines(decl, between.measure, own)

    yours_ids = set(decl.goals) | set(decl.goal_interfaces)
    notes = [n for n in ctx.store.notes() if n.get("subject") in yours_ids]
    lines += ["", f"proposals on your goals ({len(notes)}):"]
    lines += [f"  {n.get('subject')}  {str(n.get('timestamp', ''))[:10]}  {n.get('actor', '?')}: "
              f"{str(n.get('text', ''))[:200]}" for n in notes[-10:]] or ["  (none)"]
    lines += ["", "changes to your goal set by the agent since you last committed it:"]
    lines += [f"  {c['sha']}  {', '.join(c['files'][:4])} -- {c['subject'][:80]}" for c in changes] \
        or ["  (none)"]
    lines += ["", "guard: " + ("installed in this clone" if guard_installed(ctx.root)
                               else f"NOT INSTALLED in this clone -- run: {install_hint}")]
    mine = yours_ids | decl.goal_owned | {GOALS_FILE}
    issues = [i for i in decl.issues if i.subject in mine or i.code == "UNKNOWN_GOAL"]
    if issues:
        lines += ["", "issues:", bullet(i.render() for i in issues)]
    return envelope("\n".join(lines), basis_line(slices) + f" · {GOALS_FILE}@{decl.goals_blob[:7]}")


if __name__ == "__main__":
    sys.exit(guard_main())
