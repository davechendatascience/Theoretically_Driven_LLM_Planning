"""stamp-monitor: a read-only view across both ledgers.

component-belief says whether the built thing works; consistency-belief says whether the design
follows. Each can see its own ledger. This package sees the joins -- a changed file, the component
that claims it, the contract that measured it, the design branch that cites the contract, the
policy that gates the branch -- and the ledgers' integrity and conformance.

It writes nothing. Stamps are made by the runner that ran the command, because the one who ran it
is the only party that can say what was measured; a monitor that accepted registrations would be
an agent-writable path into the evidence, which is the thing both ledgers exist to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass

BLOCK, WARN, INFO = "block", "warn", "info"
_ORDER = {BLOCK: 0, WARN: 1, INFO: 2}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    subject: str
    message: str

    def render(self) -> str:
        return f"[{self.severity}] {self.code} {self.subject}: {self.message}"


def render_findings(title: str, findings: list[Finding], empty: str) -> str:
    if not findings:
        return f"{title}: {empty}"
    ordered = sorted(findings, key=lambda f: (_ORDER[f.severity], f.code, f.subject))
    counts = {s: sum(1 for f in findings if f.severity == s) for s in (BLOCK, WARN, INFO)}
    head = f"{title}: " + ", ".join(f"{n} {s}" for s, n in counts.items() if n)
    return "\n".join([head, *(f.render() for f in ordered)])
