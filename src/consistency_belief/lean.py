"""Lean certificates: a formal proof of a node's claim, checked once by a Lean service.

Proving a lemma or branch in Lean is optional, and it is the author's step, taken before a
verifier pass. certify() sends the committed Lean source to a service that runs Lean -- the Lean
prover server (lean-prover) or Axiom's AXLE (axle) -- and keeps the service's answer whole in the
ledger. Every later read uses the stored copy; nothing re-runs Lean.

A certificate is optional, further evidence, and it moves no proof state (DEF-lean-certificate).
Lean proves the Lean statement; whether that statement says what the node's claim says, and
whether the statements are consistent at all, is outside Lean. So the probe serves it to the
verifier -- the statement checked, its axioms and the Lean source -- beside the statements it
always reads, and the verifier's trials judge the step with it in hand, free to find the statements
inconsistent whatever Lean checked. Like a trial, a certificate is bound to its node's fingerprint
and the statements of the premises the node cites, and a restatement of either sets it aside.

Each service answers in its own shape; `Service.read` turns an answer into one `Reading` -- did it
verify, which statement, on which axioms, in which environment -- and every judgement below is
made on that, recomputed from the stored answer on every read.

The services are configured outside git, since a server's address can change with every restart
and a key is a credential: certify(url=...) names the address for one call, as the person directing
the agent gives it; otherwise environment variables (LEAN_PROVER_URL, LEAN_PROVER_API_KEY,
LEAN_PROVER_REPO; AXLE_API_URL, AXLE_API_KEY), or a section per service in a file git does not
track (LEAN_SERVICES_CONFIG, by default .lean-services.yaml in the project). No address is written
to the ledger: a record names the service and the service's own id for the check.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Lean's own axioms, which any Mathlib proof uses; every other axiom must stand for a premise.
STANDARD_AXIOMS = ("propext", "Classical.choice", "Quot.sound")
CONFIG_FILE = ".lean-services.yaml"
DEFAULT_SERVICE = "lean-prover"

CERTIFIED = "certified"
FAILED = "failed"
SET_ASIDE = "set aside"


class LeanError(Exception):
    """A Lean service could not be reached, refused the call, or answered with nonsense."""


@dataclass
class ServiceConfig:
    service: str
    url: str
    key: str = ""
    repo: str = ""

    @property
    def host(self) -> str:
        return urllib.parse.urlparse(self.url).netloc or self.url


@dataclass
class Reading:
    """A service's answer, read the same way whichever service gave it."""

    verified: bool
    status: str                         # the service's own word for the outcome
    statement: str                      # the Lean statement it checked
    axioms: list[str] | None            # every axiom the proof rests on; None when not reported
    custom_axioms: list[str]            # the ones beyond Lean's standard three
    has_sorry: bool | None
    environment: str
    reference: str                      # the service's id for this check
    problems: list[str] = field(default_factory=list)   # why the service says it failed


@dataclass
class Request:
    """What certify() asks a service to check."""

    target_id: str
    claim: str
    fingerprint: str
    declaration: str
    expected_statement: str
    files: dict[str, str]               # hosted path -> Lean source; the first holds the declaration
    premise_axioms: dict[str, str]
    environment: str
    timeout_seconds: int


def _tracked(root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False                                    # outside the project: not its git's to track
    try:
        out = subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel.as_posix()], cwd=root,
                             capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def _http(config: ServiceConfig, method: str, path: str, body: dict[str, Any] | None = None, *,
          auth: bool = True, timeout: float = 60.0) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "tdlp-consistency-belief"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth and config.key:
        headers["Authorization"] = f"Bearer {config.key}"
    request = urllib.request.Request(config.url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise LeanError(f"{method} {path} answered {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LeanError(f"{method} {path} could not reach {config.host}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeanError(f"{method} {path} answered with something that is not JSON") from exc


def _strings(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


class LeanProver:
    """The Lean prover server (leanProverServer): hosts the sources in a git repository of its own,
    runs the kernel at an exact commit, audits every axiom the proof uses, and keeps a certificate
    that anyone holding its id can fetch again."""

    name = "lean-prover"
    #: Cloudflare answers 524 when a request has run 100 s; the server finishes it and keeps the
    #: certificate, which is then found again by its claim id.
    gateway_timeouts = (502, 504, 522, 524)

    def __init__(self, config: ServiceConfig, poll_seconds: float = 10.0) -> None:
        self.config = config
        self.poll_seconds = poll_seconds

    @staticmethod
    def configure(section: dict[str, Any], url: str = "") -> tuple[ServiceConfig | None, str]:
        url = url or (os.environ.get("LEAN_PROVER_URL") or str(section.get("url") or "")).strip().rstrip("/")
        key = (os.environ.get("LEAN_PROVER_API_KEY") or str(section.get("key") or "")).strip()
        repo = (os.environ.get("LEAN_PROVER_REPO") or str(section.get("repo") or "") or "tdlp-proofs").strip()
        if not url:
            return None, ("lean-prover has no address: pass url= with the server you were given, or set "
                          f"LEAN_PROVER_URL, or url: under lean-prover: in {CONFIG_FILE}, kept out of git")
        if not key:
            return None, "lean-prover needs an API key: LEAN_PROVER_API_KEY, or key: under lean-prover:"
        return ServiceConfig(LeanProver.name, url, key, repo), ""

    def check(self, req: Request) -> dict[str, Any]:
        quoted = urllib.parse.quote(self.config.repo)
        committed = _http(self.config, "POST", f"/api/v1/repos/{quoted}/files",
                          {"files": req.files, "commit_message": f"{req.target_id}: {req.declaration}"})
        commit = str(committed.get("commit") or "") if isinstance(committed, dict) else ""
        if not commit:
            raise LeanError(f"committing to {self.config.repo} returned no commit: {str(committed)[:200]}")
        body = {
            "repo_name": self.config.repo, "commit": commit, "target_file": next(iter(req.files)),
            "declaration": req.declaration, "expected_statement": req.expected_statement,
            "claim_id": claim_id(req), "planning_claim": req.claim, "pinned_env": req.environment or "default",
            "assumption_policy": {"allowed_axioms": [*STANDARD_AXIOMS, *req.premise_axioms.values()],
                                  "allow_custom_axioms": False},
            "timeout_seconds": max(5, min(300, req.timeout_seconds)),
        }
        try:
            return self._certificate(_http(self.config, "POST", "/api/v1/verify", body,
                                           timeout=body["timeout_seconds"] + 30))
        except LeanError as exc:
            if not any(f"answered {code}" in str(exc) for code in self.gateway_timeouts) and "timed out" not in str(exc):
                raise
        deadline = time.monotonic() + body["timeout_seconds"] + 60
        while time.monotonic() < deadline:
            listed = _http(self.config, "GET", "/api/v1/certificates")
            for cert in listed if isinstance(listed, list) else []:
                if isinstance(cert, dict) and (cert.get("planning_binding") or {}).get("claim_id") == body["claim_id"]:
                    return cert
            time.sleep(self.poll_seconds)
        raise LeanError(f"the gateway timed out and no certificate for {body['claim_id']} appeared; adopt it "
                        "later with certificate_id once GET /api/v1/certificates lists it")

    def fetch(self, reference: str) -> dict[str, Any]:
        """A certificate by id; no key needed, the id is the capability."""
        return self._certificate(_http(self.config, "GET", f"/api/v1/verify/{urllib.parse.quote(reference)}",
                                       auth=False))

    @staticmethod
    def _certificate(out: Any) -> dict[str, Any]:
        if not isinstance(out, dict) or not out.get("certificate_id"):
            raise LeanError(f"the server answered without a certificate: {str(out)[:200]}")
        return out

    @staticmethod
    def read(answer: dict[str, Any], record: dict[str, Any]) -> Reading:
        statement = answer.get("statement") or {}
        audit = answer.get("assumption_audit") or {}
        env = answer.get("environment") or {}
        lean = str(env.get("lean_version") or "")
        lean = lean.split("version ", 1)[1].split(",", 1)[0] if "version " in lean else lean
        environment = " · ".join([f"Lean {lean}" if lean else ""] + [
            f"{name} {env[key]}" for name, key in (("Mathlib", "mathlib_version"), ("Physlib", "physlib_version"))
            if env.get(key)]).strip(" ·")
        problems = []
        if statement.get("matches_expected") is not True:
            problems.append("the declaration's statement is not the expected one"
                            + (f": {statement['mismatch_reason']}" if statement.get("mismatch_reason") else ""))
        if audit.get("policy_passed") is not True:
            problems.append("the assumption policy failed: " + "; ".join(_strings(audit.get("policy_violations")) or ["?"]))
        cid = str((answer.get("planning_binding") or {}).get("claim_id") or "")
        target = str(record.get("target_id") or "")
        if not (cid == target or cid.startswith(f"{target}@")):
            problems.append(f"it was requested for {cid or 'no claim'}, not {target}")
        checked = str((answer.get("source") or {}).get("declaration") or "")
        if checked != str(record.get("declaration") or ""):
            problems.append(f"it checked {checked or 'no declaration'}, not {record.get('declaration')}")
        if str((answer.get("signature") or {}).get("hash") or "") != digest(answer):
            problems.append("its digest does not match its content: the stored copy was edited")
        return Reading(
            verified=answer.get("status") == "VERIFIED" and answer.get("verified") is True,
            status=str(answer.get("status") or "?"),
            statement=str(statement.get("inferred_type") or ""),
            axioms=_strings(audit.get("axioms_used")),
            custom_axioms=_strings(audit.get("custom_axioms")),
            has_sorry=audit.get("has_sorry") if isinstance(audit.get("has_sorry"), bool) else None,
            environment=environment or "(not recorded)",
            reference=str(answer.get("certificate_id") or ""),
            problems=problems,
        )


class Axle:
    """Axiom's AXLE (axle.axiommath.ai): checks a proof against a formal statement -- a theorem
    with its proof sorried out -- in a Mathlib environment. It admits Lean's standard axioms and no
    other, so a premise enters the theorem as a hypothesis, never as an axiom. It keeps nothing: the
    answer, with its request id, is the record."""

    name = "axle"

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config

    @staticmethod
    def configure(section: dict[str, Any], url: str = "") -> tuple[ServiceConfig | None, str]:
        url = url or (os.environ.get("AXLE_API_URL") or str(section.get("url") or "")
                      or "https://axle.axiommath.ai").strip().rstrip("/")
        key = (os.environ.get("AXLE_API_KEY") or str(section.get("key") or "")).strip()
        return ServiceConfig(Axle.name, url, key), ""          # a key only raises AXLE's rate limit

    def check(self, req: Request) -> dict[str, Any]:
        if req.premise_axioms:
            raise LeanError("axle admits Lean's standard axioms only: state each premise as a hypothesis of the "
                            "theorem instead of an axiom, and leave premise_axioms empty")
        if len(req.files) != 1:
            raise LeanError("axle checks one self-contained file, which imports Mathlib at most; name one file")
        environment = req.environment or self._newest()
        answer = _http(self.config, "POST", "/api/v1/verify_proof", {
            "content": next(iter(req.files.values())), "formal_statement": req.expected_statement,
            "environment": environment, "timeout_seconds": max(5, min(900, req.timeout_seconds)),
        }, timeout=req.timeout_seconds + 30)
        if not isinstance(answer, dict) or "okay" not in answer:
            raise LeanError(f"axle answered without a verdict: {str(answer)[:300]}")
        return answer

    def fetch(self, reference: str) -> dict[str, Any]:
        raise LeanError("axle keeps no certificate to fetch again; certify with files")

    def _newest(self) -> str:
        listed = _http(self.config, "GET", "/v1/environments")
        names = [str(e.get("name")) for e in listed if isinstance(e, dict) and e.get("name")] \
            if isinstance(listed, list) else []
        if not names:
            raise LeanError("axle listed no environments; name one, e.g. lean-4.34.0")
        return names[0]

    @staticmethod
    def read(answer: dict[str, Any], record: dict[str, Any]) -> Reading:
        tool = answer.get("tool_messages") or {}
        lean = answer.get("lean_messages") or {}
        errors = _strings(tool.get("errors")) + _strings(lean.get("errors"))
        info = answer.get("info") or {}
        sorried = any("sorry" in e for e in errors)
        return Reading(
            verified=answer.get("okay") is True,
            status="OKAY" if answer.get("okay") is True else "NOT OKAY",
            statement=formal_statement(str(record.get("expected_statement") or "")),
            axioms=None,                # not reported; okay means the standard three at most
            custom_axioms=[],
            has_sorry=True if sorried else (False if answer.get("okay") is True else None),
            environment=str(info.get("environment") or record.get("environment") or "(not recorded)"),
            reference=str(info.get("request_id") or ""),
            problems=errors[:3],
        )


SERVICES: dict[str, type] = {LeanProver.name: LeanProver, Axle.name: Axle}


def load_service(root: Path, name: str, url: str = "") -> tuple[Any | None, str]:
    """The named service, configured, or None and why not. An address given for the call wins, then
    the environment, then the file; a key is never read from a file git tracks, since a committed
    key is a published one."""
    if name not in SERVICES:
        return None, f"unknown service {name!r}; expected one of {', '.join(SERVICES)}"
    path = Path(os.environ.get("LEAN_SERVICES_CONFIG") or root / CONFIG_FILE)
    if not path.is_absolute():
        path = root / path
    section: dict[str, Any] = {}
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            return None, f"{path.name} does not parse: {exc}"
        if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
            return None, f"{path.name} maps each service ({', '.join(SERVICES)}) to its url:, key: and repo:"
        if any(v.get("key") for v in data.values()) and _tracked(root, path):
            return None, (f"{path.name} holds an API key and git tracks it: remove it from the index "
                          f"(git rm --cached {path.name}), add it to .gitignore, and rotate the key")
        section = data.get(name) or {}
    cls = SERVICES[name]
    config, why = cls.configure(section, url.strip().rstrip("/"))
    return (cls(config), "") if config is not None else (None, why)


#: Where a declaration that is not the axiom begins: the axiom's statement ends there.
_NEXT_COMMAND = (r"^\s*(?:@\[|/-|--|(?:private\s+|protected\s+|noncomputable\s+)*(?:theorem|lemma|def|axiom|opaque|"
                 r"abbrev|instance|structure|class|inductive|namespace|section|end|open|variable|example|#))")


def axiom_statements(files: dict[str, str], names: list[str]) -> dict[str, str]:
    """What each named Lean axiom states, read from the sources: `<name> <binders> : <type>`. A proof
    resting on an axiom is only as faithful as the axiom, so the verifier is served what each one
    says, not only its name. Found by the name's last component; one not found is left out, and the
    probe says it could not be read."""
    out: dict[str, str] = {}
    for name in names:
        short = re.escape(name.rsplit(".", 1)[-1])
        pattern = re.compile(rf"^\s*(?:private\s+|protected\s+)?axiom\s+({short}\b.*?)(?={_NEXT_COMMAND}|\Z)",
                             re.M | re.S)
        for text in files.values():
            found = pattern.search(text)
            if found:
                out[name] = " ".join(found.group(1).split())
                break
    return out


def formal_statement(text: str) -> str:
    """An AXLE formal statement as a reader needs it: without its imports and without the sorried
    proof, which say nothing about what is stated."""
    kept = "\n".join(line for line in text.splitlines() if not line.strip().startswith("import "))
    return re.sub(r"\s*:=\s*(?:by\s+)?sorry\s*$", "", kept.strip())


def claim_id(req: Request) -> str:
    """Names the node and the statement a check was requested for, unique per request so a
    certificate the gateway lost can be found again: `<id>@<fingerprint>#<nonce>`."""
    return f"{req.target_id}@{req.fingerprint}#{os.urandom(4).hex()}"


def digest(cert: dict[str, Any]) -> str:
    """SHA-256 of the lean-prover certificate's canonical JSON without its signature, as that server
    computes it (VerificationCertificate.compute_hash). A digest, not a signature: it shows a stored
    copy was not edited without recomputing it, and nothing more."""
    body = {k: v for k, v in cert.items() if k != "signature"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def reading(record: dict[str, Any]) -> Reading:
    service = SERVICES.get(str(record.get("service") or DEFAULT_SERVICE))
    if service is None:
        return Reading(False, "?", "", None, [], None, "(not recorded)", "",
                       [f"recorded by an unknown service {record.get('service')!r}"])
    return service.read(record.get("certificate") or {}, record)


def failures(record: dict[str, Any]) -> list[str]:
    """Why a certificate does not certify its node; empty when it does. Every condition is read off
    the stored answer, so a stored copy is judged the same way on every read."""
    r = reading(record)
    out = [] if r.verified else [f"Lean did not verify it ({r.status})"]
    out += r.problems
    if r.has_sorry is not False:
        out.append("the proof uses sorry" if r.has_sorry else "the service did not say the proof is free of sorry")
    stand_ins = set((record.get("premise_axioms") or {}).values())
    extra = sorted(set(r.custom_axioms) - stand_ins)
    if extra:
        out.append(f"it rests on axiom(s) no premise stands for: {', '.join(extra)}")
    return list(dict.fromkeys(out))


@dataclass
class Certificate:
    """One certificate record, read against the graph as it stands."""

    id: str
    target_id: str
    record: dict[str, Any]
    state: str                        # certified | failed | set aside
    why: list[str] = field(default_factory=list)

    @property
    def reading(self) -> Reading:
        return reading(self.record)

    @property
    def service(self) -> str:
        return str(self.record.get("service") or DEFAULT_SERVICE)

    @property
    def declaration(self) -> str:
        return str(self.record.get("declaration") or "")


def judge(dag: Any, record: dict[str, Any]) -> Certificate:
    """A certificate record as it reads now: set aside once its node, or a premise its node cites, is
    restated (as DEF-current-trial reads a trial), else certified or failed on the stored answer."""
    target = str(record.get("target_id") or "")
    node = dag.get(target)
    rid = str(record.get("id") or "")
    if node is None:
        return Certificate(rid, target, record, SET_ASIDE, [f"{target} is not in the premise graph"])
    if record.get("statement_sha") != node.fingerprint():
        return Certificate(rid, target, record, SET_ASIDE, [f"{target} was restated since"])
    read = dag.premise_statements(target)
    moved = sorted(pid for pid in read if (record.get("read") or {}).get(pid) != read[pid])
    if moved:
        return Certificate(rid, target, record, SET_ASIDE, [f"{', '.join(moved)} was restated since"])
    why = failures(record)
    return Certificate(rid, target, record, FAILED if why else CERTIFIED, why)


def current_certificates(dag: Any, records: list[dict[str, Any]]) -> dict[str, Certificate]:
    """The latest certifying certificate of each node, by node id. A later failed attempt does not
    take a certified one's place: a proof that checked is not unchecked by a failed retry."""
    out: dict[str, Certificate] = {}
    for record in records:
        c = judge(dag, record)
        if c.state == CERTIFIED:
            out[c.target_id] = c
    return out


def probe_block(c: Certificate) -> list[str]:
    """What the verifier is served of a certificate, beside the statements: the Lean statement that
    was checked, the axioms it rests on and the Lean source itself. It is further evidence about the
    claim, never a verdict: the verifier still judges the statements, and whether the Lean is about
    this claim."""
    r = c.reading
    stands_for = {lean: tdlp for tdlp, lean in (c.record.get("premise_axioms") or {}).items()}
    stated = c.record.get("axiom_statements") or {}
    if r.axioms is None:
        axioms = ["Lean's standard axioms at most (the service admits no other)"]
    else:
        standard = [a for a in r.axioms if a not in stands_for]
        axioms = ([", ".join(standard)] if standard else []) + [
            f"{a} -- stands for {stands_for[a]}, and states: "
            + (f"{a.rsplit('.', 1)[0] + '.' if '.' in a else ''}{stated[a]}" if a in stated else
               "(not recorded -- a step resting on an axiom you cannot read is a gap)")
            for a in r.axioms if a in stands_for] or ["(none)"]
    return [
        f"LEAN CERTIFICATE (additional evidence: {c.id}, checked by Lean via {c.service}):",
        f"  theorem:     {c.declaration}",
        "  proves:      " + "\n               ".join(r.statement.strip().splitlines() or ["(no statement)"]),
        "  axioms:      " + "\n               ".join(axioms),
        f"  environment: {r.environment}",
        "  Lean checked that this statement holds from these axioms and the library's theorems. That is",
        "  further evidence, not a verdict: judge the statements above as you would without it. Lean did",
        "  not check that its statement says what the claim says, nor that the premises are consistent.",
        "  Look for where the two differ: a condition the claim states that the Lean statement drops, a",
        "  hypothesis or axiom it adds that no premise states, an axiom that says more than its premise, a",
        "  different quantifier or domain -- each is a gap, named. A counterexample in the statements",
        "  refutes the claim whatever Lean checked.",
        *_source_lines(c),
    ]


def _source_lines(c: Certificate) -> list[str]:
    """The Lean source the service checked, which the verifier may read: formal evidence, not the
    implementation."""
    files = c.record.get("lean_files") or {}
    if not files:
        return ["  LEAN SOURCE: not recorded with this certificate (adopted by id)."]
    out: list[str] = []
    for path, text in files.items():
        out.append(f"  LEAN SOURCE {path}:")
        out += [f"    {line}" for line in str(text).rstrip().splitlines()]
    return out
