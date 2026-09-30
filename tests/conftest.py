from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BASE_YAML = """
components:
  - id: CMP-perception
    purpose: Segment the scene
    outputs: [IFC-perception__grasp]
    testable_capability: Produces a segmented cloud for a visible object
    failure_modes: [{id: FM-miss, observable: no cluster returned}]
    remediation: Retune segmentation thresholds
  - id: CMP-grasp
    purpose: Choose a grasp pose
    inputs: [IFC-perception__grasp]
    testable_capability: Produces a reachable pose
    failure_modes: [{id: FM-unreachable, observable: IK returns nothing}]
    remediation: Retune approach sampling

interfaces:
  - id: IFC-perception__grasp
    producer: CMP-perception
    consumer: CMP-grasp
    units: metres
    producer_guarantees: [points in camera_optical]
    consumer_assumptions: [points in camera_optical, cloud covers full object]

contracts:
  - id: CTR-grasp-reachable
    subject: CMP-grasp
    claim_type: capability
    metrics: [{id: ik_success, unit: bool}]
    acceptance: {rule: "ik_success == true", target_rate: 0.8}
    conditions:
      - {id: normal, when: "lighting == 'normal'"}
      - {id: low, when: "lighting == 'low'"}
    compatibility_key: [model_revision]
    evaluable_by: [TST-grasp-ik]
    sufficiency: {n_min: 4, max_ci_width: 0.9}

tests:
  - id: TST-grasp-ik
    layer: component
    targets: [CMP-grasp]
    run: "echo ok"
    metrics: [ik_success]
    capture: [lighting, model_revision]

policies:
  - id: POL-release
    criteria:
      - {slice: CTR-grasp-reachable, require: supported}
"""


#: The human's goals for the same system: two goals, the hand-over between them, and the contracts,
#: tests and policy that measure them -- all declared here, none in belief.yaml.
GOALS_YAML = """
goals:
  - id: GOL-see
    outcome: The scene is segmented well enough to grasp from
    measure: CTR-see-e2e
  - id: GOL-grasp
    outcome: The arm picks up the object it is asked for
    measure: CTR-pick-success

interfaces:
  - id: IFC-see__grasp
    from: GOL-see
    to: GOL-grasp
    hands_over: segmented clouds in camera_optical, one per object
    measure: CTR-cloud-fits-grasp

contracts:
  - id: CTR-see-e2e
    subject: GOL-see
    kind: gate
    metrics: [{id: passed, unit: bool}]
    acceptance: {rule: "passed == true"}
    evaluable_by: [TST-see]
  - id: CTR-pick-success
    subject: GOL-grasp
    kind: gate
    metrics: [{id: passed, unit: bool}]
    acceptance: {rule: "passed == true"}
    evaluable_by: [TST-pick]
  - id: CTR-cloud-fits-grasp
    subject: IFC-see__grasp
    kind: gate
    metrics: [{id: passed, unit: bool}]
    acceptance: {rule: "passed == true"}
    evaluable_by: [TST-cloud-fits]

tests:
  - id: TST-see
    layer: e2e
    targets: [GOL-see]
    run: python eval/see.py $OUT
    metrics: [passed]
  - id: TST-pick
    layer: e2e
    targets: [GOL-grasp]
    run: python eval/pick.py $OUT
    metrics: [passed]
  - id: TST-cloud-fits
    layer: interface
    targets: [IFC-see__grasp]
    run: python eval/cloud_fits.py $OUT
    metrics: [passed]

policies:
  - id: POL-goals
    criteria:
      - {slice: CTR-see-e2e, require: supported}
      - {slice: CTR-pick-success, require: supported}
      - {slice: CTR-cloud-fits-grasp, require: supported}
"""

#: belief.yaml with each component naming the goal it serves, and CMP-grasp claiming its code.
GOAL_TAGGED_YAML = BASE_YAML.replace(
    "    remediation: Retune segmentation thresholds\n",
    "    remediation: Retune segmentation thresholds\n    goal: GOL-see\n",
).replace(
    "    remediation: Retune approach sampling\n",
    "    remediation: Retune approach sampling\n    goal: GOL-grasp\n    code: [grasp.py]\n",
)

EVAL_PY = "import json, sys\njson.dump({'trials': [{'metrics': {'passed': True}}]}, open(sys.argv[1], 'w'))\n"
AGENT_TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=test", *args],
        cwd=root, capture_output=True, text=True,
    )


@pytest.fixture(autouse=True)
def _not_inside_a_plugin(monkeypatch):
    """A suite launched through the tdlp plugin inherits CLAUDE_PLUGIN_ROOT, which tells the runner
    to drop the server's own interpreter from a test's PATH. A test that runs a declared command
    would then find whatever other `python` the machine has, or none. Each test builds the
    environment it means to test; tests of the plugin case set the variable themselves."""
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with belief.yaml committed — declarations load from HEAD."""
    git(tmp_path, "init", "-q")
    (tmp_path / "belief.yaml").write_text(BASE_YAML, encoding="utf-8")
    git(tmp_path, "add", "belief.yaml")
    git(tmp_path, "commit", "-q", "-m", "declare")
    return tmp_path


@pytest.fixture
def goals_repo(repo: Path) -> Path:
    """The repo after the human committed goals.yaml by hand (no agent trailer) and the agent
    tagged its components with the goals they serve."""
    (repo / "belief.yaml").write_text(GOAL_TAGGED_YAML, encoding="utf-8")
    (repo / "grasp.py").write_text("# v1\n", encoding="utf-8")
    (repo / "eval").mkdir()
    for name in ("see", "pick", "cloud_fits"):
        (repo / "eval" / f"{name}.py").write_text(EVAL_PY, encoding="utf-8")
    (repo / "goals.yaml").write_text(GOALS_YAML, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "my goals")
    return repo


def commit_as_agent(repo: Path, path: str, text: str, message: str = "agent change") -> None:
    """A commit the agent makes: it carries the trailer Claude Code writes on its commits."""
    (repo / path).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--no-verify", "-m", message + AGENT_TRAILER)


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "seed.txt").write_text("seed", encoding="utf-8")
    git(tmp_path, "add", "seed.txt")
    git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


_counter = itertools.count(1)


def trial(
    *,
    contract="CTR-grasp-reachable",
    ik=True,
    lighting="normal",
    model_revision="v3",
    provenance="measured",
    validity="valid",
    outcome="pass",
    run_id="RUN-0001",
    metrics=None,
    id=None,
):
    """A trial as the store hands it back — ids included, since every record
    read by the belief layer has already been through append_trials."""
    return {
        "id": id or f"EV-{next(_counter):04d}",
        "subject": "CMP-grasp",
        "contract_id": contract,
        "test_id": "TST-grasp-ik",
        "test_ref": "TST-grasp-ik@abc",
        "run_id": run_id,
        "provenance": provenance,
        "outcome": outcome,
        "metrics": {"ik_success": ik} if metrics is None else metrics,
        "conditions": {"raw": {"lighting": lighting}},
        "repro": {"model_revision": model_revision, "sw_revision": "abc123"},
        "validity": validity,
        "artifact_uri": "artifacts/RUN-0001/result.json",
    }
