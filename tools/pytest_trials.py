"""Adapter: run pytest, emit one trial per test case to $OUT.

Trial-level granularity is rule 3.1 — storing "the suite passed" as the only
record throws away the per-case evidence that every later question needs. The
JUnit XML pytest already knows how to write happens to be exactly the
trial-level shape this server wants.

Usage (from a belief.yaml `run:` line):
    python tools/pytest_trials.py $OUT -- tests/test_beliefs.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: pytest_trials.py <out.json> [-- <pytest args>]", file=sys.stderr)
        return 2

    out_path = Path(argv[0])
    pytest_args = argv[2:] if len(argv) > 1 and argv[1] == "--" else argv[1:]

    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", f"--junit-xml={junit}", *pytest_args],
            capture_output=True, text=True,
        )
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)

        trials = _parse(junit) if junit.exists() else []

    if not trials:
        # No parseable cases: emit nothing rather than a synthetic pass. An
        # empty trial list is honest; a fabricated one is not.
        out_path.write_text(json.dumps({"trials": []}), encoding="utf-8")
        return completed.returncode

    out_path.write_text(json.dumps({"trials": trials}, indent=2), encoding="utf-8")
    return completed.returncode


def _parse(junit: Path) -> list[dict]:
    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError:
        return []

    trials: list[dict] = []
    for case in root.iter("testcase"):
        failed = any(case.find(tag) is not None for tag in ("failure", "error"))
        skipped = case.find("skipped") is not None
        name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        trials.append({
            "metrics": {"passed": not failed and not skipped},
            "conditions": {"case": name},
            "outcome": "not_applicable" if skipped else ("fail" if failed else "pass"),
        })
    return trials


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
