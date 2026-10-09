"""Lean certificates: an optional, additional certificate a node's verifier reads beside the statements.

The services are faked here by a local HTTP server that speaks both APIs -- the Lean prover
server's repository, verify and certificate endpoints, and AXLE's verify_proof -- so nothing leaves
the machine. TDLP_LIVE_LEAN=1 with LEAN_PROVER_URL and LEAN_PROVER_API_KEY set runs the one live
round trip at the bottom against a real server.
"""
# tdlp:foreign-ids the graphs and projects these tests build declare their own node ids

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import git
from consistency_belief.lean import digest
from consistency_belief.server import certify, decide, status, verify_step

DESIGN = """
axioms:
  - id: AXM-energy-budget
    domain: resource
    statement: Total system battery power is bounded at 100W.
    rationale: Battery physical discharge constraint.

lemmas:
  - id: LMA-compute-cap
    statement: Compute power cannot exceed 40W when the motors draw at least 60W.
    premises: [AXM-energy-budget]
    derivation_rule: The budget less the motors' worst case leaves 40W.
    sufficiency: {n_min: 2, min_consensus: 0.8}

policies:
  - id: POL-formal
    criteria:
      - {target: LMA-compute-cap, require: proven, formal: certified}
"""

#: The premise as an axiom about two fixed quantities -- not about every pair of reals, which would be
#: false and prove anything: the reason the probe serves what each axiom states, not only its name.
LEAN = """import Mathlib

namespace TDLP
/-- Power drawn by compute and by the motors, in watts. -/
opaque compute : ℝ
opaque motors : ℝ
/-- AXM-energy-budget -/
axiom energy_budget : compute + motors ≤ 100

theorem compute_cap (h : 60 ≤ motors) : compute ≤ 40 := by
  linarith [energy_budget]
end TDLP
"""
STATEMENT = "60 ≤ TDLP.motors → TDLP.compute ≤ 40"
AXLE_STATEMENT = ("import Mathlib\ntheorem compute_cap (compute motors : ℝ) (budget : compute + motors ≤ 100) "
                  "(h : 60 ≤ motors) : compute ≤ 40 := by sorry")


def lean_prover_certificate(request: dict, *, status_: str = "VERIFIED", custom: list[str] | None = None,
                            matches: bool = True) -> dict:
    """A certificate as the Lean prover server builds one, digest included."""
    custom = ["TDLP.energy_budget"] if custom is None else custom
    cert = {
        "certificate_id": f"cert{abs(hash(request['claim_id'])) % 10**8:08d}",
        "created_at": "2026-10-09T08:00:00+00:00",
        "status": status_,
        "verified": status_ == "VERIFIED" and matches,
        "source": {"repo_url": request["repo_name"], "commit": request["commit"], "workspace_path": "",
                   "target_file": request["target_file"], "declaration": request["declaration"]},
        "statement": {"declaration_name": request["declaration"], "declaration_kind": "theorem",
                      "inferred_type": request["expected_statement"] if matches else "True",
                      "expected_type": request["expected_statement"], "matches_expected": matches,
                      "mismatch_reason": None if matches else "types differ"},
        "assumption_audit": {"axioms_used": ["propext", "Classical.choice", "Quot.sound", *custom],
                             "standard_axioms": ["propext", "Classical.choice", "Quot.sound"],
                             "custom_axioms": custom, "has_sorry": False,
                             "policy_passed": all(a in request["assumption_policy"]["allowed_axioms"] for a in custom),
                             "disallowed_axioms": [], "policy_violations": []},
        "planning_binding": {"claim_id": request["claim_id"], "planning_claim": request["planning_claim"],
                             "binding_note": ""},
        "environment": {"lean_version": "Lean (version 4.34.1, x86_64-unknown-linux-gnu, commit 0, Release)",
                        "lake_version": "", "mathlib_version": "v4.34.1", "physlib_version": "v4.34.1",
                        "platform": "Linux-x86_64", "pinned_env": "physlib-v4.34.1"},
        "reproduction": {"reproduction_command": "", "cli_command": "", "curl_command": ""},
        "diagnostics": {"messages": [], "execution_time_ms": 10, "raw_output": ""},
    }
    cert["signature"] = {"algorithm": "sha256", "hash": digest(cert)}
    return cert


class FakeServices(BaseHTTPRequestHandler):
    """Both services on one port. `behaviour` decides the next answer; `seen` keeps every request."""

    behaviour: dict = {}
    seen: list = []
    held: dict = {}

    def log_message(self, *args):
        pass

    def _send(self, code: int, body) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.seen.append(("GET", self.path, None, self.headers.get("Authorization")))
        if self.path.startswith("/api/v1/verify/"):
            cid = self.path.rsplit("/", 1)[1]
            return self._send(200, self.held[cid]) if cid in self.held else self._send(404, {"detail": "no"})
        if self.path == "/api/v1/certificates":
            return self._send(200, list(self.held.values()))
        if self.path == "/v1/environments":
            return self._send(200, [{"name": "lean-4.34.0"}, {"name": "lean-4.33.1"}])
        self._send(404, {"detail": "unknown"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
        self.seen.append(("POST", self.path, body, self.headers.get("Authorization")))
        if self.path.endswith("/files"):
            return self._send(200, {"status": "committed", "commit": "a" * 40})
        if self.path == "/api/v1/verify":
            cert = lean_prover_certificate(body, **self.behaviour.get("cert", {}))
            self.held[cert["certificate_id"]] = cert
            if self.behaviour.get("gateway_timeout"):
                return self._send(524, {"detail": "timeout"})
            return self._send(200, cert)
        if self.path == "/api/v1/verify_proof":
            okay = self.behaviour.get("axle_okay", True)
            return self._send(200, {"okay": okay, "content": body["content"], "failed_declarations": [] if okay else ["t"],
                                    "lean_messages": {"errors": [], "warnings": [], "infos": []},
                                    "tool_messages": {"errors": [] if okay else ["Declaration 't' is incomplete"],
                                                      "warnings": [], "infos": []},
                                    "info": {"request_id": "req-1", "environment": body["environment"]}})
        self._send(404, {"detail": "unknown"})


@pytest.fixture
def services(monkeypatch):
    FakeServices.behaviour, FakeServices.seen, FakeServices.held = {}, [], {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServices)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    for name in ("LEAN_PROVER_URL", "LEAN_PROVER_REPO", "AXLE_API_URL", "AXLE_API_KEY", "LEAN_SERVICES_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LEAN_PROVER_API_KEY", "lps_key_test")
    yield url
    server.shutdown()


@pytest.fixture
def project(empty_repo: Path, monkeypatch) -> Path:
    (empty_repo / "consistency.yaml").write_text(DESIGN, encoding="utf-8")
    (empty_repo / "lean" / "TDLP").mkdir(parents=True)
    (empty_repo / "lean" / "TDLP" / "ComputeCap.lean").write_text(LEAN, encoding="utf-8")
    git(empty_repo, "add", "-A")
    git(empty_repo, "commit", "-q", "-m", "design and its Lean")
    monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(empty_repo))
    return empty_repo


def certify_lean_prover(url: str, **kw) -> str:
    args = dict(declaration="TDLP.compute_cap", expected_statement=STATEMENT, files=["lean/TDLP/ComputeCap.lean"],
                workspace="lean", premise_axioms={"AXM-energy-budget": "TDLP.energy_budget"}, url=url)
    args.update(kw)
    return certify("LMA-compute-cap", **args)


def evidence(root: Path) -> list[dict]:
    path = root / ".consistency" / "evidence.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.exists() else []


def restate(root: Path, old: str, new: str) -> None:
    text = (root / "consistency.yaml").read_text(encoding="utf-8")
    (root / "consistency.yaml").write_text(text.replace(old, new), encoding="utf-8")
    git(root, "commit", "-qam", "restate")


def test_the_verifier_reads_the_statements_and_a_certificate_beside_them(project: Path, services: str):
    """The probe keeps everything it served before and adds the Lean statement that was checked, the
    axioms it rests on, which premise each custom one stands for and what it states, and the Lean
    source the service checked. The certificate moves no proof state: the node is as open as it was."""
    before = status("probe", subject="LMA-compute-cap")
    out = certify_lean_prover(services)
    assert "CRT-0001 recorded for LMA-compute-cap: lean-prover VERIFIED -- CERTIFIED" in out

    probe = status("probe", subject="LMA-compute-cap")
    for part in ("PREMISES:", "[AXIOM AXM-energy-budget]: Total system battery power is bounded at 100W.",
                 "DERIVED CLAIM [LMA-compute-cap]:", "DERIVATION RULE:", "STRATEGIES"):
        assert part in before and part in probe
    assert "LEAN CERTIFICATE (additional evidence: CRT-0001, checked by Lean via lean-prover)" in probe
    assert f"proves:      {STATEMENT}" in probe
    assert ("TDLP.energy_budget -- stands for AXM-energy-budget, and states: "
            "TDLP.energy_budget : compute + motors ≤ 100") in probe
    assert "LEAN SOURCE TDLP/ComputeCap.lean:" in probe and "    linarith [energy_budget]" in probe
    assert "judge the statements above as you would without it" in probe
    assert services not in probe

    tree = status("tree")
    assert "LMA-compute-cap [OBLIGATION 0/2 · LEAN]" in tree
    assert "lean: CRT-0001 via lean-prover certifies TDLP.compute_cap" in status("branches")

    # What the service was asked: the committed source under the workspace, the node's statement,
    # and an assumption policy admitting only Lean's axioms and the stand-in for the cited premise.
    uploaded = next(b for m, p, b, _ in FakeServices.seen if p.endswith("/files"))
    assert uploaded["files"] == {"TDLP/ComputeCap.lean": LEAN}
    verify = next(b for m, p, b, _ in FakeServices.seen if p == "/api/v1/verify")
    assert verify["claim_id"].startswith("LMA-compute-cap@")
    assert verify["assumption_policy"]["allowed_axioms"][-1] == "TDLP.energy_budget"


def test_a_certificate_does_not_stop_the_verifier_refuting_the_statements(project: Path, services: str):
    """Further evidence, never a verdict: a counterexample found in the statements refutes the claim
    whatever Lean checked, and the certificate stays beside it."""
    certify_lean_prover(services)
    out = verify_step("LMA-compute-cap", trials=[
        {"strategy": "counterexample", "outcome": "falsified",
         "rationale": "the budget bounds total power, and nothing says compute and motors are all of it",
         "counterexample": "a third load draws 20W: motors 60W, compute 20W is within budget and so is 40W"}])
    assert "[REFUTED" in out
    assert "LMA-compute-cap [REFUTED · LEAN]" in status("tree")


def test_the_address_given_for_a_call_is_never_recorded(project: Path, services: str):
    certify_lean_prover(services)
    ledger = (project / ".consistency" / "evidence.jsonl").read_text(encoding="utf-8") \
        + (project / ".consistency" / "events.jsonl").read_text(encoding="utf-8")
    assert "127.0.0.1" not in ledger and "lps_key_test" not in ledger
    assert all(auth == "Bearer lps_key_test" for m, p, _, auth in FakeServices.seen if p != "/v1/environments"
               and not p.startswith("/api/v1/verify/"))


def test_a_restatement_sets_the_certificate_aside(project: Path, services: str):
    """Bound like a trial: to its node's fingerprint and the statements of the premises it cites."""
    certify_lean_prover(services)
    restate(project, "bounded at 100W", "bounded at 120W")
    assert "LEAN CERTIFICATE" not in status("probe", subject="LMA-compute-cap")
    assert "CRT-0001" in status("certificates") and "SET ASIDE" in status("certificates")
    assert "AXM-energy-budget was restated since" in status("certificates")

    certify_lean_prover(services)
    assert "LEAN CERTIFICATE (additional evidence: CRT-0002" in status("probe", subject="LMA-compute-cap")
    restate(project, "cannot exceed 40W", "stays at or below 40W")
    assert "LEAN CERTIFICATE" not in status("probe", subject="LMA-compute-cap")
    assert "LMA-compute-cap was restated since" in status("certificates", subject="LMA-compute-cap")


@pytest.mark.parametrize("cert, why", [
    ({"status_": "PROOF_FAILED"}, "Lean did not verify it (PROOF_FAILED)"),
    ({"matches": False}, "the declaration's statement is not the expected one"),
    ({"custom": ["TDLP.energy_budget", "TDLP.anything_goes"]}, "no premise stands for: TDLP.anything_goes"),
])
def test_a_certificate_that_does_not_certify_is_recorded_and_never_served(project: Path, services: str, cert, why):
    FakeServices.behaviour = {"cert": cert}
    out = certify_lean_prover(services)
    assert "-- FAILED" in out and why in out
    assert len([r for r in evidence(project) if r.get("kind") == "certificate"]) == 1
    assert "LEAN CERTIFICATE" not in status("probe", subject="LMA-compute-cap")
    assert "· LEAN" not in status("tree")


def test_a_stored_certificate_edited_after_the_fact_stops_certifying(project: Path, services: str):
    certify_lean_prover(services)
    path = project / ".consistency" / "evidence.jsonl"
    records = evidence(project)
    for r in records:
        if r.get("kind") == "certificate":
            r["certificate"]["statement"]["inferred_type"] = STATEMENT.replace("≤ 40", "≤ 30")
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    assert "LEAN CERTIFICATE" not in status("probe", subject="LMA-compute-cap")
    assert "the stored copy was edited" in status("certificates")


@pytest.mark.parametrize("kw, refusal", [
    ({"premise_axioms": {"AXM-elsewhere": "TDLP.x"}}, "a Lean axiom may stand only for a premise the step cites"),
    ({"expected_statement": ""}, "expected_statement is required"),
    ({"files": ["TDLP/ComputeCap.lean"]}, "is not under the workspace lean/"),
    ({"service": "coq"}, "unknown service 'coq'"),
])
def test_a_request_that_cannot_bind_is_refused_before_anything_is_sent(project: Path, services: str, kw, refusal):
    assert refusal in certify_lean_prover(services, **kw)
    assert not [r for r in evidence(project) if r.get("kind") == "certificate"]
    assert not [s for s in FakeServices.seen if s[0] == "POST"]


def test_lean_source_must_be_committed_as_it_stands(project: Path, services: str):
    (project / "lean" / "TDLP" / "ComputeCap.lean").write_text(LEAN.replace("linarith", "nlinarith"), encoding="utf-8")
    out = certify_lean_prover(services)
    assert "is not committed as it stands" in out and "Nothing was recorded" in out
    assert not FakeServices.seen


def test_a_certificate_the_gateway_lost_is_found_by_its_claim_id(project: Path, services: str):
    FakeServices.behaviour = {"gateway_timeout": True}
    out = certify_lean_prover(services)
    assert "-- CERTIFIED" in out
    assert any(p == "/api/v1/certificates" for _, p, _, _ in FakeServices.seen)


def test_a_held_certificate_is_adopted_by_id_and_binds_to_the_statement_it_was_requested_for(project: Path,
                                                                                               services: str):
    certify_lean_prover(services)
    cid = next(iter(FakeServices.held))
    out = certify_lean_prover(services, certificate_id=cid, files=None, expected_statement="")
    assert "CRT-0002 recorded" in out and "-- CERTIFIED" in out
    # No source came with it, so neither the source nor what its axiom states is on record, and
    # the probe says so.
    probe = status("probe", subject="LMA-compute-cap")
    assert "(not recorded -- a step resting on an axiom you cannot read is a gap)" in probe
    assert "LEAN SOURCE: not recorded with this certificate (adopted by id)." in probe
    # Two certify the node; the probe carries exactly one, the latest.
    assert probe.count("LEAN CERTIFICATE") == 1 and "CRT-0002" in probe and "CRT-0001" not in probe
    restate(project, "cannot exceed 40W", "stays at or below 40W")
    out = certify_lean_prover(services, certificate_id=cid, files=None, expected_statement="")
    assert "-- SET ASIDE" in out and "LMA-compute-cap was restated since" in out


def test_axle_is_a_service_too(project: Path, services: str, monkeypatch):
    """AXLE checks a proof against a sorried formal statement and admits Lean's standard axioms only:
    a premise enters as a hypothesis, and its certificate says no other axiom was admitted."""
    monkeypatch.setenv("AXLE_API_URL", services)
    (project / "lean" / "Axle.lean").write_text(AXLE_STATEMENT.replace("by sorry", "by linarith"), encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "axle form")
    args = dict(declaration="compute_cap", expected_statement=AXLE_STATEMENT, files=["lean/Axle.lean"],
                service="axle")
    assert "axle admits Lean's standard axioms only" in certify(
        "LMA-compute-cap", premise_axioms={"AXM-energy-budget": "TDLP.energy_budget"}, **args)

    out = certify("LMA-compute-cap", **args)
    assert "CRT-0001 recorded for LMA-compute-cap: axle OKAY -- CERTIFIED" in out
    probe = status("probe", subject="LMA-compute-cap")
    assert "checked by Lean via axle" in probe
    assert ("proves:      theorem compute_cap (compute motors : ℝ) (budget : compute + motors ≤ 100) "
            "(h : 60 ≤ motors) : compute ≤ 40\n") in probe
    assert "Lean's standard axioms at most (the service admits no other)" in probe
    sent = next(b for m, p, b, _ in FakeServices.seen if p == "/api/v1/verify_proof")
    assert sent["environment"] == "lean-4.34.0" and sent["formal_statement"] == AXLE_STATEMENT

    FakeServices.behaviour = {"axle_okay": False}
    out = certify("LMA-compute-cap", **args)
    assert "axle NOT OKAY -- FAILED" in out and "Declaration 't' is incomplete" in out
    assert "CRT-0001" in status("probe", subject="LMA-compute-cap")        # the earlier one still certifies


def test_the_default_service_is_lean_prover_and_needs_an_address(project: Path, services: str):
    out = certify("LMA-compute-cap", declaration="TDLP.compute_cap", expected_statement=STATEMENT,
                  files=["lean/TDLP/ComputeCap.lean"], workspace="lean")
    assert "lean-prover has no address: pass url=" in out


def test_a_key_is_never_read_from_a_file_git_tracks(project: Path, services: str, monkeypatch):
    monkeypatch.delenv("LEAN_PROVER_API_KEY")
    (project / ".lean-services.yaml").write_text(f"lean-prover: {{url: {services}, key: lps_key_file}}\n",
                                                 encoding="utf-8")
    assert "-- CERTIFIED" in certify_lean_prover("")
    git(project, "add", ".lean-services.yaml")
    git(project, "commit", "-qm", "oops")
    out = certify_lean_prover("")
    assert "holds an API key and git tracks it" in out and "Nothing was recorded" in out


def test_a_policy_may_require_a_certificate_beside_proven(project: Path, services: str):
    trials = [{"strategy": s, "outcome": "sound", "rationale": "attacked"} for s in ("counterexample", "entailment")]
    verify_step("LMA-compute-cap", trials=trials)
    verdict = decide("LMA-compute-cap", policy_id="POL-formal")
    assert "MORE_TESTING" in verdict and "has no Lean certificate certifying its claim" in verdict

    certify_lean_prover(services)
    assert "LMA-compute-cap [PROVEN 2/2 · LEAN]" in status("tree")
    verdict = decide("LMA-compute-cap", policy_id="POL-formal")
    assert "ADOPT" in verdict and "has no Lean certificate" not in verdict


@pytest.mark.skipif(not (os.environ.get("TDLP_LIVE_LEAN") and os.environ.get("LEAN_PROVER_URL")
                         and os.environ.get("LEAN_PROVER_API_KEY")),
                    reason="live: set TDLP_LIVE_LEAN=1, LEAN_PROVER_URL and LEAN_PROVER_API_KEY")
def test_live_round_trip_against_a_lean_prover_server(project: Path, monkeypatch):
    monkeypatch.setenv("LEAN_PROVER_REPO", "tdlp-test")
    out = certify("LMA-compute-cap", declaration="TDLP.compute_cap", expected_statement=STATEMENT,
                  files=["lean/TDLP/ComputeCap.lean"], workspace="lean",
                  premise_axioms={"AXM-energy-budget": "TDLP.energy_budget"}, environment="mathlib")
    assert "-- CERTIFIED" in out, out
    assert "LEAN CERTIFICATE" in status("probe", subject="LMA-compute-cap")
