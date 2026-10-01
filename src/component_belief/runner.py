"""Test execution — the only path by which a number becomes belief-eligible.

The server runs the declared command itself and records what came back. That is
the whole difference between `measured` and an agent's summary: nobody
transcribes anything, and the artifact is on disk with its hash before any
belief moves.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import readlog
from .declarations import Declarations, Test
from .staleness import Snapshot, write_stamp
from .store import Store, utc_now

RESULT_FILENAME = "result.json"


def _git_revision(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_dirty(root: Path) -> bool:
    """Whether tracked files other than the ledgers differ from HEAD when the test runs.

    A run on a dirty tree measured HEAD plus whatever was uncommitted, and the record says so:
    once those edits are committed, the evidence goes stale through the ordinary code-path
    check, and until then a reader can see the revision is not the whole story. The ledgers are
    excluded because recording a run dirties them by construction.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no", "--",
             ".", ":(exclude).belief", ":(exclude).consistency"],
            cwd=root, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
        return bool(out.stdout.strip()) if out.returncode == 0 else False
    except (OSError, subprocess.SubprocessError):
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _same_dir(entry: str, directory: Path) -> bool:
    try:
        return Path(entry).resolve() == directory.resolve()
    except OSError:
        return False


def project_environment(root: Path, env: dict[str, str]) -> dict[str, str]:
    """The environment a declared test runs in: the project's, not the harness's.

    Installed as a plugin, the server runs from an isolated tool environment (`uvx`) whose
    interpreter leads PATH, so `python` on a run line would be the harness's own -- no pytest and
    none of the project's packages -- and every gate would fail for a reason that is not the
    project's. Claude Code names a plugin server's install in CLAUDE_PLUGIN_ROOT; then, and only
    then, the harness's interpreter directory is dropped from the test's PATH. Outside a plugin
    the server runs from whatever environment its user chose, and that is left alone. Either way
    a project `.venv`, if there is one, leads PATH, and the rest is as the client inherited it.
    """
    env = dict(env)
    path_key = next((k for k in env if k.upper() == "PATH"), "PATH")
    entries = [e for e in env.get(path_key, "").split(os.pathsep) if e]
    own = Path(sys.executable).parent
    if env.get("CLAUDE_PLUGIN_ROOT") and not _inside(own, root):
        entries = [e for e in entries if not _same_dir(e, own)]
        if env.get("VIRTUAL_ENV") and _same_dir(env["VIRTUAL_ENV"], own.parent):
            del env["VIRTUAL_ENV"]
    venv = root / ".venv"
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    if bindir.is_dir():
        entries = [str(bindir)] + [e for e in entries if not _same_dir(e, bindir)]
        env["VIRTUAL_ENV"] = str(venv)
    env[path_key] = os.pathsep.join(entries)
    return env


def _substitute_out(command: str, out_path: Path) -> str:
    """Expand the $OUT placeholder ourselves.

    The declaration file is cross-platform but the shell under it is not —
    `$OUT` is meaningless to cmd.exe and `%OUT%` is meaningless to sh. Doing
    the substitution here means one `run:` line works on every platform.
    """
    target = str(out_path)
    for token in ("${OUT}", "$OUT", "%OUT%"):
        command = command.replace(token, target)
    return command


def _parse_result(path: Path) -> tuple[list[dict[str, Any]] | None, str]:
    """The trials a test wrote to $OUT, or None and what was wrong with it.

    $OUT is one JSON file: {"trials": [...]}, a list of trials, or one {"metrics": ...}. The
    reason goes back to the caller, because a missing file, a directory and malformed JSON are
    three different fixes -- and a directory once crashed the run before anything was recorded.
    """
    if not path.exists():
        return None, "the test wrote no $OUT file"
    if not path.is_file():
        return None, "$OUT is a directory, not a file"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, "$OUT is not valid JSON"
    if isinstance(data, dict) and isinstance(data.get("trials"), list):
        return data["trials"], ""
    if isinstance(data, list):
        return data, ""
    if isinstance(data, dict) and "metrics" in data:
        return [data], ""
    return None, "$OUT is JSON in none of the accepted shapes"


def run_test(
    root: Path,
    store: Store,
    decl: Declarations,
    test: Test,
    conditions: dict[str, Any] | None = None,
    repro: dict[str, Any] | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    run_id = store.next_run_id()
    artifact_dir = store.artifact_dir(run_id)
    out_path = artifact_dir / RESULT_FILENAME

    env = project_environment(root, dict(os.environ))
    env["OUT"] = str(out_path)
    env["BELIEF_RUN_ID"] = run_id
    env, hook_dir = readlog.instrument(env, root, artifact_dir / "reads.log",
                                       store.dir / "cache" / "readhook")
    command = readlog.weave(_substitute_out(test.run, out_path), hook_dir)
    # Before the command starts: the stamp is of what the run measured, not what it left behind.
    claimed = sorted({entry for comp in decl.components.values() for entry in comp.code})
    snapshot = Snapshot.take(root, claimed, test.run, test.reads)

    try:
        completed = subprocess.run(
            command, cwd=root, env=env, shell=True,
            capture_output=True, text=True, timeout=test.timeout_s,
            encoding="utf-8", errors="replace",
            # stdin MUST be closed. `capture_output` redirects stdout/stderr but leaves stdin
            # inherited -- which, when this server runs over MCP stdio, is the JSON-RPC pipe the
            # client holds open. Any child that touches stdin then blocks until the timeout.
            stdin=subprocess.DEVNULL,
        )
        exit_code: int | None = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code, timed_out = None, True
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")

    (artifact_dir / "stdout.txt").write_text(stdout or "", encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(stderr or "", encoding="utf-8")
    (artifact_dir / "command.txt").write_text(
        f"{command}\nexit={exit_code}\ntest={test.ref}\nat={utc_now()}\n", encoding="utf-8"
    )
    opened = readlog.harvest(root, artifact_dir / "reads.log")
    readlog.write(artifact_dir, opened)
    stamp = write_stamp(artifact_dir, snapshot.stamp(opened)) if snapshot else ""

    raw_trials, result_problem = _parse_result(out_path)
    synthesized = raw_trials is None
    if synthesized:
        # No structured result: fall back to a single trial whose outcome is
        # the exit code. `passed` is synthesised only if the test declared it,
        # so a contract that wants a real metric still comes back excluded
        # rather than quietly scored off an exit status.
        metrics: dict[str, Any] = {}
        if "passed" in test.metrics:
            metrics["passed"] = exit_code == 0
        raw_trials = [{"metrics": metrics, "conditions": {}}]

    # a directory at $OUT is not an artifact the server can hash: stdout stands in, as for no file
    artifact = out_path if out_path.is_file() else artifact_dir / "stdout.txt"
    artifact_uri = artifact.relative_to(root).as_posix()    # the same path on every platform
    artifact_hash = _sha256(artifact)

    base_repro = {
        "sw_revision": _git_revision(root),
        "sw_dirty": _git_dirty(root),
        "model_revision": "",
        "hw_id": "",
        "calibration_state": "",
        "environment": "",
        "dataset_revision": "",
        "seed": None,
    }
    base_repro.update(repro or {})

    contracts = [
        c for c in decl.contracts.values()
        if test.id in c.evaluable_by and decl.is_scorable(c.id)
    ]

    records: list[dict[str, Any]] = []
    for trial in raw_trials:
        trial_metrics = dict(trial.get("metrics") or {})
        trial_conditions = dict(conditions or {})
        trial_conditions.update(trial.get("conditions") or {})
        trial_repro = dict(base_repro)
        trial_repro.update(trial.get("repro") or {})

        if timed_out:
            outcome = "error"
        elif "outcome" in trial:
            outcome = str(trial["outcome"])
        elif synthesized:
            outcome = "pass" if exit_code == 0 else "fail"
        else:
            outcome = "pass"

        for contract in contracts:
            records.append({
                "subject": contract.subject,
                "contract_id": contract.id,
                "test_id": test.id,
                "test_version": test.version,
                "test_ref": test.ref,
                "run_id": run_id,
                "system_version": base_repro.get("sw_revision", ""),
                "provenance": "measured",
                "outcome": outcome,
                "metrics": trial_metrics,
                "conditions": {"raw": trial_conditions},
                "repro": trial_repro,
                "validity": "valid",
                "artifact_uri": artifact_uri,
                "artifact_hash": artifact_hash,
                "stamp": stamp,
            })

    ids = store.append_trials(records)
    store.append_event("run_test", {
        "run_id": run_id, "test": test.ref, "exit_code": exit_code,
        "n_records": len(ids), "synthesized": synthesized,
    }, actor=actor)

    outcome_counts: dict[str, int] = {}
    for record in records:
        outcome_counts[record["outcome"]] = outcome_counts.get(record["outcome"], 0) + 1

    return {
        "run_id": run_id,
        "test": test.ref,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "n_trials": len(raw_trials),
        "n_records": len(ids),
        "evidence_ids": ids,
        "contracts": [c.id for c in contracts],
        "outcome_counts": outcome_counts,
        "artifact_uri": artifact_uri,
        "artifact_hash": artifact_hash,
        "stamp": stamp,
        "synthesized_from_exit_code": synthesized,
        "result_problem": result_problem,
        "stdout_tail": (stdout or "")[-800:],
    }
