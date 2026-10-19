"""Tests that run in the background: run_test(..., wait=False).

A run of hours outlives any tool call a client waits on -- Codex gives a call an hour unless told
otherwise, and a training run takes nine -- and it should outlive the server as well, since a client
reload restarts it. So a background run is a process of its own. The server reserves the run's id
and artifact directory, starts the worker detached from itself, and answers at once. The worker
runs the test exactly as a waited run_test does and records its trials when it ends, under the
ledger's lock. Nothing is recorded early, and nobody settles a run afterwards: a run's evidence is
what its own process captured, recorded when its run ended, as DEF-research-ledger has it.

job.json, beside the run's other artifacts, says what was started, by which process, and when it
ended; status(view="runs") reads it to tell a run still going from one whose process died before
recording anything.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .store import Store, utc_now

JOB_FILE = "job.json"
RUNNING, RECORDED, LOST, FAILED = "running", "recorded", "lost", "failed"


def _write(path: Path, job: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _alive(pid: int) -> bool:
    """Whether a process is still running. Never os.kill on Windows: there it terminates."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32                        # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def start(root: Path, test_id: str, test_ref: str, conditions: dict[str, Any] | None,
          repro: dict[str, Any] | None, actor: str) -> tuple[str, int]:
    """Reserve a run and start its worker; returns the run id and the worker's pid."""
    store = Store(root)
    run_id, artifact_dir = store.reserve_run_id()
    job_path = artifact_dir / JOB_FILE
    job: dict[str, Any] = {"run_id": run_id, "test": test_ref, "started": utc_now(), "pid": 0, "actor": actor}
    _write(job_path, job)

    env = dict(os.environ)
    # the worker imports this same code, wherever the server was installed from
    package_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join([package_root] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    command = [sys.executable, "-m", "component_belief.jobs", str(root), run_id, test_id,
               json.dumps(conditions or {}), json.dumps(repro or {}), actor]
    log = (artifact_dir / "job.log").open("ab")
    detach: dict[str, Any] = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
        if os.name == "nt" else {"start_new_session": True})
    try:
        process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, **detach)
    finally:
        log.close()
    # the worker is this server's child until it ends: reap it, or it lingers as a zombie that
    # reads as alive
    threading.Thread(target=process.wait, daemon=True).start()
    job["pid"] = process.pid
    _write(job_path, job)
    return run_id, process.pid


def work(argv: list[str]) -> int:
    """The worker: run one test into its reserved run, record it, and say so in job.json."""
    from .declarations import load
    from .runner import run_test

    root, run_id, test_id = Path(argv[0]), argv[1], argv[2]
    conditions, repro, actor = json.loads(argv[3]), json.loads(argv[4]), argv[5]
    store = Store(root)
    artifact_dir = store.artifacts_dir / run_id
    job_path = artifact_dir / JOB_FILE
    job = _read(job_path) or {"run_id": run_id}
    try:
        decl = load(root)
        test = decl.tests.get(test_id)
        if test is None:
            raise LookupError(f"{test_id} is no longer declared at HEAD")
        result = run_test(root, store, decl, test, conditions or None, repro or None, actor=actor,
                          reserved=(run_id, artifact_dir))
    except Exception as exc:       # whatever stopped it, job.json says so: a silent death reads as lost
        job.update({"ended": utc_now(), "error": f"{type(exc).__name__}: {exc}"})
        _write(job_path, job)
        return 1
    job.update({"ended": utc_now(), "exit_code": result["exit_code"], "n_records": result["n_records"],
                "outcomes": result["outcome_counts"]})
    _write(job_path, job)
    return 0


def jobs(root: Path) -> list[dict[str, Any]]:
    """Every background run, newest last, with its state now."""
    out = []
    directory = Store(root).artifacts_dir
    for path in sorted(directory.glob(f"RUN-*/{JOB_FILE}")) if directory.is_dir() else []:
        job = _read(path)
        if job is None:
            continue
        if job.get("error"):
            job["state"] = FAILED
        elif job.get("ended"):
            job["state"] = RECORDED
        elif _alive(int(job.get("pid") or 0)):
            job["state"] = RUNNING
        else:
            job["state"] = LOST
        out.append(job)
    return out


def view_runs(root: Path) -> str:
    listing = jobs(root)
    if not listing:
        return "runs: none in the background -- run_test(test_id, wait=False) starts one"
    running = sum(1 for j in listing if j["state"] == RUNNING)
    lines = [f"runs in the background: {running} running, {len(listing)} started in all"]
    for job in listing:
        line = f"- {job['run_id']} · {job.get('test')} · {job['state']} · started {job.get('started')}"
        if job["state"] == RUNNING:
            line += f" · pid {job.get('pid')}"
        elif job["state"] == RECORDED:
            line += f" · ended {job.get('ended')} · exit {job.get('exit_code')} · {job.get('n_records')} records"
        elif job["state"] == FAILED:
            line += f" · {job.get('error')}"
        else:
            line += " · its process is gone and it recorded nothing: run it again"
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(work(sys.argv[1:]))
