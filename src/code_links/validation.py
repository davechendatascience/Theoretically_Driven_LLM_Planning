"""Checks over a whole index: identity, references, pins, mentions and coverage.

Every link ends in exactly one state, and every state but `aligned` is a diagnostic. A link's
review is its latest review in the ledger (DEF-review), or, if it has none, the pins written in
its header before reviews were records:

  aligned         its review found it aligned, and both digests it recorded are what is there now
  unreviewed      no review in the ledger and no pins in the header: never read against its claim
  review failed   its latest review found it not aligned, and nothing has changed since
  body changed    the region's code differs from the body its review recorded
  claim restated  the claim, or a node it depends on, was restated since its review
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
UNREVIEWED = "unreviewed"
UNPINNED = UNREVIEWED                   # the name before reviews were ledger records
REVIEW_FAILED = "review failed"
BODY_CHANGED = "body changed"
CLAIM_RESTATED = "claim restated"
UNKNOWN_CLAIM = "unknown claim"
INVALID_BLOCK = "invalid block"
#: A motivated-by relation with no pin of its own: it asserts no correspondence, so it is not a
#: code link (DEF-code-link) and is neither aligned nor out of date -- only explanatory.
EXPLANATORY = "explanatory"


def review_of(block: Block, relation: Relation) -> dict | None:
    """The link's review: its latest in the ledger, a moved region's, or else the pins its header
    carries, read as an aligned review under grammar 1 (DEF-review). None: never reviewed."""
    found = block.reviews.get(relation.target)
    if found is not None:
        return found
    if block.pin is not None and relation.pin is not None:
        return {"body": block.pin, "claim": relation.pin, "grammar": 1, "outcome": "aligned", "legacy": True}
    return None


def _moved(block: Block, review: dict, claims: Mapping[str, ClaimRef], target: str) -> tuple[bool, bool]:
    body_now = block.body_pin if int(review.get("grammar", 2)) >= 2 else block.legacy_body_pin
    return review.get("body") != body_now, review.get("claim") != claims[target].pin


def link_state(block: Block, relation: Relation, claims: Mapping[str, ClaimRef] | None) -> str:
    if not block.valid:
        return INVALID_BLOCK
    if claims is None or relation.target not in claims:
        return UNKNOWN_CLAIM
    if not relation.needs_pin and relation.pin is None:
        return EXPLANATORY
    review = review_of(block, relation)
    if review is None:
        return UNREVIEWED
    body_moved, claim_moved = _moved(block, review, claims, relation.target)
    if body_moved:
        return BODY_CHANGED
    if claim_moved:
        return CLAIM_RESTATED
    if review.get("outcome") != "aligned":
        return REVIEW_FAILED
    return ALIGNED


def review_call(block: Block, targets: list[str] | None = None) -> str:
    """The call that records a review of the region, once it was read against its claims."""
    only = f', target="{targets[0]}"' if targets and len(targets) == 1 else ""
    return f'review("{block.block_id}"{only}, note="what you checked")'


def header_lines(block: Block, claims: Mapping[str, ClaimRef]) -> tuple[str, ...]:
    """The begin and relation lines of a marker region with no pins: reviews are ledger records."""
    return tuple([block.header(None)] + [r.header(None) for r in block.relations])


def validate(index: CodeIndex, claims: Mapping[str, ClaimRef] | None, *,
             explain_claim: Callable[[str, str], str | None] | None = None,
             explain_body: Callable[[str, str, str], str | None] | None = None,
             reviews: Mapping[tuple[str, str], dict] | None = None,
             explain_since: Callable[[str, str], str | None] | None = None,
             translate_claim: Callable[[str, str], str] | None = None) -> None:
    """`reviews` maps (region, node) to its latest review in the ledger, its claim digest already
    under the current rule. `explain_claim` says why a header pin no longer matches;
    `explain_since` why a claim moved since a review's commit; `translate_claim` turns a header
    pin's earlier-rule claim digest into the current rule's at the revision it held (DEF-review)."""
    out = index.diagnostics
    reviews = reviews or {}
    present = {b.block_id for b in index.blocks}
    for block in index.blocks:
        block.reviews = {t: reviews[(block.block_id, t)] for t in block.targets() if (block.block_id, t) in reviews}
        for r in block.relations:
            if r.target in block.reviews or block.pin is None or r.pin is None:
                continue
            # A header pin is a review under grammar 1 and the earlier claim rule.
            known = claims.get(r.target) if claims else None
            claim = (known.pin if known and r.pin == known.pin_v1 else
                     translate_claim(r.target, r.pin) if translate_claim else r.pin)
            block.reviews[r.target] = {"body": block.pin, "claim": claim, "grammar": 1, "outcome": "aligned",
                                       "legacy": True, "pin": r.pin}
        # A region no longer carried, reviewed for the same node with this body, follows its code.
        if index.scope.paths is None:
            for r in block.relations:
                if r.target in block.reviews:
                    continue
                moved = [(region, rv) for (region, target), rv in reviews.items()
                         if target == r.target and region not in present and int(rv.get("grammar", 2)) >= 2
                         and rv.get("body") == block.body_pin]
                if len(moved) == 1:
                    region, rv = moved[0]
                    block.reviews[r.target] = {**rv, "relocated_from": region}
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
        known = [r for r in block.relations if r.target in claims and (r.needs_pin or r.pin)]
        states = {r.target: link_state(block, r, claims) for r in known}
        never = [r.target for r in known if states[r.target] == UNREVIEWED]
        if never:
            out.append(Diagnostic(
                "UNREVIEWED", REVIEW, block.block_id,
                f"never reviewed ({block.location}): read the region against {', '.join(never)} as it "
                f"stands at {rev}, then record the review", block.path, block.start_line,
                (review_call(block, never),)))
        body = [r for r in known if states[r.target] == BODY_CHANGED]
        if body:
            rv = review_of(block, body[0]) or {}
            if rv.get("legacy"):
                since = f"pinned @{rv.get('body')} in its header"
                why = explain_body(block.block_id, block.path, rv.get("body", "")) if explain_body else None
            else:
                commit = str(rv.get("commit") or "")[:7]
                since = f"{rv.get('id', 'its review')} at {commit}"
                why = f"`git diff {commit} {rev} -- {block.path}` shows what changed" if commit else None
            out.append(Diagnostic(
                "BODY_CHANGED", REVIEW, block.block_id,
                f"its code changed since it was reviewed ({since}, now @{block.body_pin}); "
                + (why + "; " if why else "")
                + f"re-read it against {', '.join(r.target for r in body)}, then record the review",
                block.path, block.start_line, (review_call(block, [r.target for r in body]),)))
        for r in known:
            rv = review_of(block, r) or {}
            if states[r.target] == CLAIM_RESTATED:
                if rv.get("legacy"):
                    since = f"pinned {r.target}@{rv.get('claim')} in its header"
                    why = explain_claim(r.target, rv.get("claim", "")) if explain_claim else None
                else:
                    since = f"{rv.get('id', 'its review')} at {str(rv.get('commit') or '')[:7]}"
                    why = explain_since(r.target, str(rv.get("commit") or "")) if explain_since else None
                out.append(Diagnostic(
                    "CLAIM_RESTATED", REVIEW, block.block_id,
                    f"{r.kind} {r.target} was reviewed against @{rv.get('claim')} ({since}), and "
                    f"{r.target} now pins @{claims[r.target].pin}: it, or a node it depends on, was "
                    "restated since" + (f" ({why})" if why else "") + "; re-read the region against the "
                    "claim as it stands, then record the review", block.path, r.line,
                    (review_call(block, [r.target]),)))
            elif states[r.target] == REVIEW_FAILED:
                out.append(Diagnostic(
                    "REVIEW_FAILED", REVIEW, block.block_id,
                    f"{rv.get('id', 'its latest review')} at {str(rv.get('commit') or '')[:7]} found "
                    f"{r.kind} {r.target} not aligned: {rv.get('note') or '(no note)'}; fix the code or "
                    "restate the claim, then review again", block.path, r.line,
                    (review_call(block, [r.target]),)))

        # Both kinds of review on one region: say which decides, so a header pin is not read as
        # the state, and suggest dropping it.
        pinned = [r for r in known if r.pin is not None]
        if block.pin is not None and pinned and all(not block.reviews.get(r.target, {}).get("legacy")
                                                    for r in pinned):
            out.append(Diagnostic(
                "HEADER_PIN_SUPERSEDED", OBSERVATION, block.block_id,
                f"its header pins (@{block.pin}) are no longer read: a review in the ledger decides each "
                "of its links -- drop the @digests from its begin and relation lines when the file is next "
                "touched", block.path, block.start_line))

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
        around = [blocks[b] for b in (m.blocks or ((m.block,) if m.block else ())) if b in blocks]
        covered = any(m.target == t or m.target in claims[t].basis
                      for block in around for t in block.targets() if t in claims)
        if not covered:
            inside = (f"inside {around[0].block_id}, which declares no relation covering it" if around
                      else "outside any region")
            remedy = ("add `Uses: " + m.target + "` (or Implements:, Checks:) to the docstring of the "
                      "function or class it describes" if m.where == "docstring" else
                      "declare it on the region the comment describes")
            out.append(Diagnostic("UNTRACKED_MENTION", OBSERVATION, where,
                                  f"{m.where} names {m.target} {inside}; nothing will notice when it "
                                  f"is restated -- {remedy}", m.path, m.line))

    if index.scope.paths is not None:
        return                                 # a partial scan cannot judge coverage
    linked = {r.target for b in index.blocks if b.valid for r in b.relations if r.needs_pin}
    for cid, ref in sorted(claims.items()):
        if ref.kind == "branch" and ref.candidates and cid not in linked:
            out.append(Diagnostic(
                "UNLINKED_CLAIM", OBSERVATION, cid,
                f"no region implements, uses or checks it; its subject {ref.subject} claims "
                f"{', '.join(ref.candidates[:4])}" + (" ..." if len(ref.candidates) > 4 else "")))
