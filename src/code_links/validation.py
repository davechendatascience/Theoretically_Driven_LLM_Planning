"""Checks over a whole index: identity, references, pins, mentions and coverage.

Every link ends in exactly one state, and every state but `aligned` is a diagnostic:

  aligned         both pins present and equal to what is there now
  unpinned        never reviewed: a pin is missing (the diagnostic prints the lines to write)
  body changed    the region's code differs from the body its pin records
  claim restated  the claim, or a node it depends on, was restated since its pin
  unknown claim   the target is not in the premise graph at this revision
  invalid block   the region is malformed, nested, empty or shares its id
  explanatory     a motivated-by relation with no pin: no correspondence asserted, so not a
                  code link at all, and never counted as aligned

A mention is either tracked -- inside a block whose relations cover it, the claim itself or a
node the claim depends on -- or reported: as dangling when it names nothing, which is the stale
mention, and as untracked otherwise, which is the one that will go stale without anyone seeing.
"""

from __future__ import annotations

from typing import Callable, Mapping

from .model import (ERROR, OBSERVATION, REVIEW, Block, ClaimRef, CodeIndex, Diagnostic, Relation)

ALIGNED = "aligned"
UNPINNED = "unpinned"
BODY_CHANGED = "body changed"
CLAIM_RESTATED = "claim restated"
UNKNOWN_CLAIM = "unknown claim"
INVALID_BLOCK = "invalid block"
#: A motivated-by relation with no pin of its own: it asserts no correspondence, so it is not a
#: code link (DEF-code-link) and is neither aligned nor out of date -- only explanatory.
EXPLANATORY = "explanatory"


def link_state(block: Block, relation: Relation, claims: Mapping[str, ClaimRef] | None) -> str:
    if not block.valid:
        return INVALID_BLOCK
    if claims is None or relation.target not in claims:
        return UNKNOWN_CLAIM
    if not relation.needs_pin and relation.pin is None:
        return EXPLANATORY
    if relation.needs_pin and (relation.pin is None or block.pin is None):
        return UNPINNED
    if block.pin is not None and block.pin != block.body_pin:
        return BODY_CHANGED
    if relation.pin is not None and relation.pin != claims[relation.target].pin:
        return CLAIM_RESTATED
    return ALIGNED


def header_lines(block: Block, claims: Mapping[str, ClaimRef]) -> tuple[str, ...]:
    """The begin and relation lines with every pin as it would read once re-reviewed now."""
    lines = [block.header(block.body_pin)]
    for r in block.relations:
        pin = claims[r.target].pin if r.target in claims else r.pin
        lines.append(r.header(pin if (r.needs_pin or r.pin) else None))
    return tuple(lines)


def validate(index: CodeIndex, claims: Mapping[str, ClaimRef] | None, *,
             explain_claim: Callable[[str, str], str | None] | None = None,
             explain_body: Callable[[str, str, str], str | None] | None = None) -> None:
    out = index.diagnostics
    by_id: dict[str, list[Block]] = {}
    for block in index.blocks:
        by_id.setdefault(block.block_id, []).append(block)
    for bid, group in sorted(by_id.items()):
        if len(group) > 1:
            where = ", ".join(b.location for b in group)
            for block in group:
                block.valid = False
            out.append(Diagnostic("DUPLICATE_BLOCK", ERROR, bid,
                                  f"{len(group)} regions share this id ({where}); a block is known by "
                                  "its id, so rename all but one", group[0].path, group[0].start_line))
    if claims is None:
        return
    index.validated = True
    index.claims = dict(claims)
    rev = index.revision[:7]

    for block in index.blocks:
        if not block.valid:
            continue
        for r in block.relations:
            if r.target not in claims:
                out.append(Diagnostic(
                    "UNKNOWN_CLAIM", ERROR, block.block_id,
                    f"{r.kind} {r.target}, which is not in the premise graph at {rev} -- removed, "
                    "renamed, staged but not declared, or declared and not admitted; repoint the "
                    "tag or remove it", block.path, r.line))
        known = [r for r in block.relations if r.target in claims]
        fix = header_lines(block, claims)
        unpinned = ((block.needs_pin and block.pin is None)
                    or any(r.needs_pin and r.pin is None for r in known))
        if unpinned:
            out.append(Diagnostic(
                "UNPINNED", REVIEW, block.block_id,
                f"never reviewed ({block.location}): read the region against "
                f"{', '.join(r.target for r in known) or 'its claims'}, and once it holds, write "
                "these header lines", block.path, block.start_line, fix))
        if block.pin is not None and block.pin != block.body_pin:
            why = explain_body(block.block_id, block.path, block.pin) if explain_body else None
            out.append(Diagnostic(
                "BODY_CHANGED", REVIEW, block.block_id,
                f"its code changed since it was reviewed (pinned @{block.pin}, now @{block.body_pin}); "
                + (why + "; " if why else "")
                + f"re-read it against {', '.join(r.target for r in known) or 'its claims'}, then update the pins",
                block.path, block.start_line, fix))
        for r in known:
            expected = claims[r.target].pin
            if r.pin is not None and r.pin != expected:
                why = explain_claim(r.target, r.pin) if explain_claim else None
                out.append(Diagnostic(
                    "CLAIM_RESTATED", REVIEW, block.block_id,
                    f"{r.kind} {r.target}@{r.pin}, and {r.target} now pins @{expected}: it, or a node it "
                    "depends on, was restated since this link was reviewed"
                    + (f" ({why})" if why else "") + "; re-read the region against the claim as it "
                    "stands, then update the pin", block.path, r.line, fix))

    code_ids = {b.block_id for b in index.blocks}
    blocks = {b.block_id: b for b in index.blocks if b.valid}
    for m in index.mentions:
        where = f"{m.path}:{m.line}"
        if m.target.startswith("CODE-"):
            if m.target not in code_ids and index.scope.paths is None:
                out.append(Diagnostic("DANGLING_MENTION", ERROR, where,
                                      f"names {m.target}, which no region at {rev} carries -- update "
                                      "the text", m.path, m.line))
            continue
        if m.target not in claims:
            out.append(Diagnostic("DANGLING_MENTION", ERROR, where,
                                  f"names {m.target}, which is not in the premise graph at {rev} -- it "
                                  "was removed or renamed; update the text", m.path, m.line))
            continue
        block = blocks.get(m.block or "")
        covered = block is not None and any(
            m.target == t or m.target in claims[t].basis for t in block.targets() if t in claims)
        if not covered:
            inside = f"inside {block.block_id}, which declares no relation covering it" if block else \
                "outside any region"
            out.append(Diagnostic("UNTRACKED_MENTION", OBSERVATION, where,
                                  f"{m.where} names {m.target} {inside}; nothing will notice when it "
                                  "is restated -- wrap the code it describes in a region that declares "
                                  "it, or drop the reference", m.path, m.line))

    if index.scope.paths is not None:
        return                                 # a partial scan cannot judge coverage
    linked = {r.target for b in index.blocks if b.valid for r in b.relations if r.needs_pin}
    for cid, ref in sorted(claims.items()):
        if ref.kind == "branch" and ref.candidates and cid not in linked:
            out.append(Diagnostic(
                "UNLINKED_CLAIM", OBSERVATION, cid,
                f"no region implements, uses or checks it; its subject {ref.subject} claims "
                f"{', '.join(ref.candidates[:4])}" + (" ..." if len(ref.candidates) > 4 else "")))
