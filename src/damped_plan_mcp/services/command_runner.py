"""Allowlisted command runner (blueprint §17).

Plans reference registered command ids, never shell strings. The registry
lives in the target project's `.damped-plan/commands.json`:

    {
      "unit_tests": {
        "allowed": true,
        "argv": ["uv", "run", "pytest", "-q"],
        "timeout_s": 300,
        "source_type": "test",
        "description": "full unit suite"
      }
    }

Safety properties:
- argv arrays executed with shell=False; no interpolation, no templating in v0
- timeout enforced (per-command, capped)
- working directory pinned to the project root (parent of the data dir)
- full output captured to an immutable artifact under .damped-plan/artifacts/

Honest limit: the registry file is plain JSON in the data dir, so it is
allowlist-by-convention, not a security boundary against an actor who can
write files. Its job is to keep validation provenance mechanical and to make
"what may run" an explicit, reviewable artifact.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 600.0
MAX_TIMEOUT_S = 3600.0
TAIL_CHARS = 4000
MAX_ARTIFACT_CHARS = 200_000

VALID_SOURCE_TYPES = {
    "test", "benchmark", "simulation", "log", "manual_review",
    "paper", "commit", "profiling", "solver",
}


class CommandRunnerError(ValueError):
    """Refused execution; the message tells the caller how to proceed."""


def registry_path(data_dir: Path) -> Path:
    return Path(data_dir) / "commands.json"


def load_registry(data_dir: Path) -> dict[str, dict[str, Any]]:
    path = registry_path(data_dir)
    if not path.exists():
        raise CommandRunnerError(
            f"No command registry at {path}. Create it with entries like "
            f'{{"unit_tests": {{"allowed": true, "argv": ["uv", "run", "pytest", '
            f'"-q"]}}}} — only registered argv commands can run; shell strings are '
            f"never accepted."
        )
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandRunnerError(
            f"Command registry {path} is unreadable ({exc}); fix the JSON."
        ) from exc
    if not isinstance(registry, dict):
        raise CommandRunnerError(
            f"Command registry {path} must be a JSON object mapping command ids "
            f"to entries."
        )
    return registry


def resolve_command(data_dir: Path, command_id: str) -> dict[str, Any]:
    registry = load_registry(data_dir)
    entry = registry.get(command_id)
    if entry is None:
        raise CommandRunnerError(
            f"Command {command_id!r} is not registered. Registered commands: "
            f"{sorted(registry)}. Add it to {registry_path(data_dir)} with "
            f'"allowed": true and an argv array.'
        )
    if not entry.get("allowed", False):
        raise CommandRunnerError(
            f"Command {command_id!r} is registered but not allowed. A human must "
            f'set "allowed": true in {registry_path(data_dir)} to enable it.'
        )
    argv = entry.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) for item in argv)
    ):
        raise CommandRunnerError(
            f"Command {command_id!r} must define argv as a non-empty list of "
            f"strings (no shell strings, no interpolation)."
        )
    return entry


def run_command(data_dir: Path, command_id: str) -> dict[str, Any]:
    data_dir = Path(data_dir)
    entry = resolve_command(data_dir, command_id)
    argv: list[str] = entry["argv"]
    timeout = min(float(entry.get("timeout_s", DEFAULT_TIMEOUT_S)), MAX_TIMEOUT_S)
    project_root = data_dir.parent

    started = datetime.now(UTC).isoformat()
    clock = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            argv,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        exit_code: int | None = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    except FileNotFoundError as exc:
        raise CommandRunnerError(
            f"Command {command_id!r} failed to start: {exc}. Check the argv "
            f"executable exists in this environment."
        ) from exc
    duration_s = round(time.monotonic() - clock, 3)

    artifacts_dir = data_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    artifact = artifacts_dir / f"{stamp}-{command_id}.json"
    counter = 1
    while artifact.exists():
        counter += 1
        artifact = artifacts_dir / f"{stamp}-{command_id}-{counter}.json"
    artifact.write_text(
        json.dumps(
            {
                "command_id": command_id,
                "argv": argv,
                "started_at": started,
                "duration_s": duration_s,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "stdout": stdout[:MAX_ARTIFACT_CHARS],
                "stderr": stderr[:MAX_ARTIFACT_CHARS],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    source_type = str(entry.get("source_type", "test"))
    if source_type not in VALID_SOURCE_TYPES:
        source_type = "test"

    return {
        "command_id": command_id,
        "argv": argv,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "stdout_tail": stdout[-TAIL_CHARS:],
        "stderr_tail": stderr[-TAIL_CHARS:],
        "artifact_uri": str(artifact.relative_to(data_dir.parent)),
        "source_type": source_type,
    }
