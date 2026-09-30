"""The acceptance suite: how this project's goals are measured, owned with goals.yaml.

It drives only the public surface -- the three servers' tools and the goal guard -- in throwaway
git projects, and shares no fixture with tests/. A test's name is the criterion it checks, so
reading the names is reading what "met" means for each goal.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

AGENT_TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"

#: A small system: one component claiming its code, a gate contract and a rate contract measured
#: by one test that reads the code and a checkpoint git ignores.
BELIEF_YAML = """
components:
  - id: CMP-planner
    purpose: Plan a grasp
    testable_capability: Returns a reachable pose
    failure_modes: [{id: FM-unreachable, observable: no pose returned}]
    remediation: Retune sampling
    code: [planner.py]

contracts:
  - id: CTR-planner-works
    subject: CMP-planner
    kind: gate
    metrics: [{id: passed, unit: bool}]
    acceptance: {rule: "passed == true"}
    evaluable_by: [TST-planner]
  - id: CTR-planner-rate
    subject: CMP-planner
    metrics: [{id: passed, unit: bool}]
    acceptance: {rule: "passed == true", target_rate: 0.8}
    sufficiency: {n_min: 10}
    evaluable_by: [TST-planner]

tests:
  - id: TST-planner
    layer: component
    targets: [CMP-planner]
    run: python check.py $OUT ckpt/model.pt
    metrics: [passed]

policies:
  - id: POL-release
    criteria:
      - {slice: CTR-planner-works, require: supported}
"""

CHECK_PY = ("import json, sys\n"
            "open('planner.py').read(); open(sys.argv[2], 'rb').read()\n"
            "json.dump([{'metrics': {'passed': True}}], open(sys.argv[1], 'w'))\n")


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=test", *args],
                          cwd=root, capture_output=True, text=True)


def commit(root: Path, message: str = "change", *, as_agent: bool = False) -> subprocess.CompletedProcess:
    """Commit everything; as the agent, with the trailer its commits carry (hooks skipped, as a
    commit that got past the guard would have)."""
    git(root, "add", "-A")
    if as_agent:
        return git(root, "commit", "-q", "--no-verify", "-m", message + AGENT_TRAILER)
    return git(root, "commit", "-q", "-m", message)


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("ckpt/\n", encoding="utf-8")
    (tmp_path / "ckpt").mkdir()
    (tmp_path / "ckpt" / "model.pt").write_bytes(b"weights-v1")
    (tmp_path / "planner.py").write_text("# v1\n", encoding="utf-8")
    (tmp_path / "check.py").write_text(CHECK_PY, encoding="utf-8")
    (tmp_path / "belief.yaml").write_text(BELIEF_YAML, encoding="utf-8")
    commit(tmp_path, "a planner and its test")
    for var in ("BELIEF_PROJECT_ROOT", "CONSISTENCY_PROJECT_ROOT", "STAMP_MONITOR_ROOT"):
        monkeypatch.setenv(var, str(tmp_path))
    # measured as a plain process, whatever launched the suite
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    return tmp_path
