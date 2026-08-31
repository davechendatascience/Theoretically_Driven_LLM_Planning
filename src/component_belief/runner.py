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
from pathlib import Path
from typing import Any

from .declarations import Declarations, Test
from .store import Store, utc_now

RESULT_FILENAME = "result.json"


def _git_revision(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


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


def _parse_result(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, dict) and isinstance(data.get("trials"), list):
        return data["trials"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "metrics" in data:
        return [data]
    return None


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

    env = dict(os.environ)
    env["OUT"] = str(out_path)
    env["BELIEF_RUN_ID"] = run_id
    command = _substitute_out(test.run, out_path)

    try:
        completed = subprocess.run(
            command, cwd=root, env=env, shell=True,
            capture_output=True, text=True, timeout=test.timeout_s,
            encoding="utf-8", errors="replace",
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

    raw_trials = _parse_result(out_path)
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

    artifact_uri = str(out_path.relative_to(root)) if out_path.exists() else str(
        (artifact_dir / "stdout.txt").relative_to(root)
    )
    artifact_hash = _sha256(out_path if out_path.exists() else artifact_dir / "stdout.txt")

    base_repro = {
        "sw_revision": _git_revision(root),
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
        "synthesized_from_exit_code": synthesized,
        "stdout_tail": (stdout or "")[-800:],
    }
