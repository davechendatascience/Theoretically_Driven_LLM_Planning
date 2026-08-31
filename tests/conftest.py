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


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=test", *args],
        cwd=root, capture_output=True, text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with belief.yaml committed — declarations load from HEAD."""
    git(tmp_path, "init", "-q")
    (tmp_path / "belief.yaml").write_text(BASE_YAML, encoding="utf-8")
    git(tmp_path, "add", "belief.yaml")
    git(tmp_path, "commit", "-q", "-m", "declare")
    return tmp_path


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
