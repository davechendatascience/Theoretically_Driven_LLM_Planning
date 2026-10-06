"""The records a scan produces: blocks, the relations they declare, mentions, and diagnostics.

A block is a delimited region of a tracked source file that declares a relation to a node in
consistency.yaml. Its identity is its CODE- id, never its location: line numbers are where it was
found at one revision, and a block that moves keeps its id. What it is at that revision is its
body digest -- its code with comments and layout set aside -- and that digest is what a review
of the correspondence vouches for.

Two pins carry that review into the source itself, in the `ID@pin` form Axiom.ref already uses:

    # tdlp:begin CODE-<name>@<8 hex>     the body the reviewer read
    # tdlp:implements BRN-<id>@<8 hex>   the claim as it stood then

A pin is an assertion, committed with the code it describes: whoever writes it says "I read this
body against this claim". The scan never writes one. It compares each pin with what is there now
and reports every link whose pins no longer match -- at every revision until someone re-reviews
it, not only in the commit that changed it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Bumped when the marker grammar or the body digest changes: a pin made under another version
#: is reported as such rather than as an edit.
GRAMMAR_VERSION = 1

#: What a relation asserts. `motivated-by` asserts no correspondence, so it needs no pins.
RELATION_KINDS = ("implements", "uses", "checks", "motivated-by")
CONFORMANCE_KINDS = ("implements", "uses", "checks")

# Severities. An error is a tag that is malformed or resolves to nothing; a review is a link whose
# pins no longer match what is there, or were never written; an observation is about coverage --
# true, worth seeing, and not a defect (a lemma may be purely mathematical).
ERROR, REVIEW, OBSERVATION = "error", "review", "observation"
_ORDER = {ERROR: 0, REVIEW: 1, OBSERVATION: 2}


@dataclass(frozen=True)
class Relation:
    kind: str
    target: str
    pin: str | None = None
    line: int = 0

    @property
    def needs_pin(self) -> bool:
        return self.kind in CONFORMANCE_KINDS

    def header(self, pin: str | None) -> str:
        return f"# tdlp:{self.kind} {self.target}" + (f"@{pin}" if pin else "")


@dataclass
class Block:
    block_id: str
    path: str
    start_line: int
    end_line: int
    pin: str | None = None                 # the body pin as written on the begin line
    relations: list[Relation] = field(default_factory=list)
    body_hash: str = ""                    # code tokens, comments and layout set aside
    source_hash: str = ""                  # the region's exact text, line endings normalised
    valid: bool = True                     # closed, not nested, its id unique in the revision
    n_code_lines: int = 0

    @property
    def body_pin(self) -> str:
        return self.body_hash[:8]

    @property
    def needs_pin(self) -> bool:
        return any(r.needs_pin for r in self.relations)

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def targets(self) -> set[str]:
        return {r.target for r in self.relations}

    def relation_set(self) -> set[tuple[str, str]]:
        return {(r.kind, r.target) for r in self.relations}

    def header(self, pin: str | None) -> str:
        return f"# tdlp:begin {self.block_id}" + (f"@{pin}" if pin else "")


@dataclass(frozen=True)
class Mention:
    """An id named in a comment or a docstring, outside any marker. Tracked when the block it
    sits in declares a relation that covers it; otherwise nothing will notice when it rots."""

    target: str
    path: str
    line: int
    where: str                  # comment | docstring
    block: str | None = None    # the enclosing block, if any


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    subject: str                # a CODE- id, a claim id, or path:line
    message: str
    path: str = ""
    line: int = 0
    fix: tuple[str, ...] = ()   # lines to write, when the remedy is mechanical once reviewed

    def render(self) -> str:
        return f"[{self.severity}] {self.code} {self.subject}: {self.message}"


@dataclass(frozen=True)
class ClaimRef:
    """A declared node as a scan needs it, supplied by whoever owns the declarations.

    `pin` is what a relation to the node must carry to be aligned; `basis` is every node it
    depends on, so a mention of a premise inside a block that implements the claim is covered by
    the claim's pin; `candidates` are files a link to it would be expected in (its subject's
    claimed code), for the coverage observation only."""

    pin: str
    kind: str                                   # axiom | definition | lemma | branch
    basis: frozenset[str] = frozenset()
    subject: str = ""
    candidates: tuple[str, ...] = ()


@dataclass
class Scope:
    """What the scan read, so a reader knows what 'no finding' covers."""

    revision: str = ""
    scanned: int = 0
    paths: list[str] | None = None              # None: the whole tree; else only these
    excluded: dict[str, int] = field(default_factory=dict)   # reason -> file count
    foreign: list[str] = field(default_factory=list)        # files whose mentions are set aside

    def exclude(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1

    def describe(self) -> str:
        where = "every tracked file" if self.paths is None else f"{len(self.paths)} named path(s)"
        out = f"{self.scanned} Python file(s) scanned at {self.revision[:7] or '?'} ({where})"
        if self.excluded:
            out += "; not scanned: " + ", ".join(f"{n} {r}" for r, n in sorted(self.excluded.items()))
        if self.foreign:
            out += (f"; mentions not checked in {len(self.foreign)} file(s) marked tdlp:foreign-ids ("
                    + ", ".join(self.foreign[:4]) + (" ..." if len(self.foreign) > 4 else "") + ")")
        return out


@dataclass
class CodeIndex:
    revision: str
    blocks: list[Block] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    scope: Scope = field(default_factory=Scope)
    grammar: int = GRAMMAR_VERSION
    validated: bool = False                     # references checked against declared claims
    claims: dict[str, ClaimRef] | None = None   # what they were checked against

    def get_block(self, block_id: str) -> Block | None:
        found = [b for b in self.blocks if b.block_id == block_id]
        return found[0] if len(found) == 1 else None

    def for_claim(self, claim_id: str) -> list[tuple[Block, Relation]]:
        return [(b, r) for b in self.blocks if b.valid for r in b.relations if r.target == claim_id]

    def for_path(self, path: str) -> list[Block]:
        return [b for b in self.blocks if b.path == path]

    def diagnostics_for(self, subject: str) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.subject == subject]

    def by_severity(self, severity: str) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == severity]

    def sorted_diagnostics(self) -> list[Diagnostic]:
        return sorted(self.diagnostics, key=lambda d: (_ORDER[d.severity], d.code, d.subject, d.line))


def display(text: str, limit: int = 160) -> str:
    """Tag and source text is untrusted: control characters and escape sequences are shown, not
    sent to a terminal, and a long line is cut."""
    clean = "".join(ch if ch.isprintable() else repr(ch)[1:-1] for ch in str(text))
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."
