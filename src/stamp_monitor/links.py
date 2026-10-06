"""Code links as the monitor reports them: the map, what needs review, and what a change did.

Three readings of one index (code_links), all read-only:

  report    the claim <-> region map at HEAD, each link's state, every diagnostic, and the
            uncommitted edits that would change a tagged region
  findings  the audit's share: tags that are broken or out of date, at every revision until
            someone fixes them -- not only in the commit that broke them
  section   impact's share: what the range base..HEAD did to tagged regions

A link is a declared relationship, not evidence: nothing here moves a belief or a proof state,
and a link that needs review blocks nothing. The CLI's `links --strict` is how a hook or CI makes
it block, by choice.
"""

from __future__ import annotations

from pathlib import Path

from code_links import (ALIGNED, ERROR, OBSERVATION, REVIEW, CodeIndex, build_index,
                        compare_indexes, display, header_lines, link_state, resolve_revision,
                        scan_worktree)
from code_links.impact import BODY, RELATIONS

from . import INFO, WARN, Finding


def scan(root: Path, revision: str = "HEAD", *, explain: bool = True) -> CodeIndex | None:
    try:
        from consistency_belief.links import scan as scan_links
    except ImportError:                                     # consistency-belief not installed
        sha = resolve_revision(root, revision)
        return None if sha is None else build_index(root, sha, explain_body=explain)
    return scan_links(root, revision, explain=explain)


def adopted(index: CodeIndex) -> bool:
    """A project that tags at least one region has opted in, and its coverage is worth reporting;
    one that tags none still hears about every broken tag and dangling mention."""
    return bool(index.blocks)


def findings(root: Path) -> list[Finding]:
    index = scan(root)
    if index is None:
        return []
    out: list[Finding] = []
    for d in index.sorted_diagnostics():
        if d.severity in (ERROR, REVIEW):
            out.append(Finding("LINK_" + d.code, WARN, display(d.subject, 80), display(d.message, 400)))
    if not adopted(index):
        return out
    observed: dict[str, list] = {}
    for d in index.by_severity(OBSERVATION):
        observed.setdefault(d.code, []).append(d)
    for code, items in sorted(observed.items()):
        files = sorted({d.path for d in items if d.path})
        where = f" in {len(files)} file(s)" if files else ""
        sample = ", ".join(display(d.subject, 60) for d in items[:3])
        out.append(Finding("LINK_" + code, INFO, f"{len(items)} item(s)",
                           f"{len(items)}{where}, e.g. {sample}; `stamp-monitor links` lists them"))
    return out


def report(root: Path, subject: str | None = None, *, index: CodeIndex | None = None,
           worktree: bool = True) -> str:
    index = index or scan(root)
    if index is None:
        return "code links: git does not know HEAD here, so there is no revision to scan"
    claims = index.claims
    rev = index.revision[:7]
    states = [(b, r, link_state(b, r, claims)) for b in index.blocks for r in b.relations]
    n_review = sum(1 for _, _, s in states if s != ALIGNED)
    lines = [f"code links at {rev}: {len(index.blocks)} region(s), {len(states)} link(s), "
             f"{len(states) - n_review} aligned, {n_review} not",
             f"scope: {index.scope.describe()}"]
    if not index.validated:
        lines.append("no consistency.yaml at this revision: references and pins are unchecked")

    shown = index.diagnostics
    if subject:
        block = index.get_block(subject)
        related = index.for_claim(subject)
        on_path = index.for_path(subject)
        if block is not None:
            lines += ["", _block_lines(block, claims, index)]
            shown = [d for d in index.diagnostics if d.subject == subject]
        elif related or (claims and subject in claims):
            lines += ["", f"{subject}: {len(related)} link(s)"]
            lines += [f"  {b.block_id} ({r.kind}) {b.location} [{link_state(b, r, claims)}]"
                      for b, r in related]
            if not related and claims and claims[subject].candidates:
                lines.append(f"  no region links it; its subject {claims[subject].subject} claims "
                             + ", ".join(claims[subject].candidates[:6]))
            ids = {b.block_id for b, _ in related}
            shown = [d for d in index.diagnostics if d.subject in ids | {subject}]
        elif on_path:
            lines += ["", f"{subject}: {len(on_path)} region(s)"]
            lines += [_block_lines(b, claims, index) for b in on_path]
            shown = [d for d in index.diagnostics if d.path == subject]
        else:
            return "\n".join(lines + ["", f"{subject!r} is not a region id, a claim with links, or "
                                          "a scanned path at this revision"])
    else:
        by_claim: dict[str, list[str]] = {}
        for b, r, state in states:
            by_claim.setdefault(r.target, []).append(f"{b.block_id} ({r.kind}) [{state}]")
        if by_claim:
            lines += ["", "claims and the regions linked to them:"]
            for cid in sorted(by_claim):
                lines.append(f"  {cid}: " + "; ".join(by_claim[cid]))

    for severity, title in ((ERROR, "errors -- tags that are malformed or name nothing"),
                            (REVIEW, "review -- links whose pins no longer match, or were never written"),
                            (OBSERVATION, "observations -- coverage, not defects")):
        items = [d for d in shown if d.severity == severity]
        if not items:
            continue
        lines += ["", f"{title} ({len(items)}):"]
        for d in sorted(items, key=lambda d: (d.code, d.subject, d.line)):
            lines.append(f"  {d.code} {display(d.subject, 80)}: {display(d.message, 600)}")
            lines += [f"      {display(f, 200)}" for f in d.fix]

    if worktree and subject is None:
        changes, dirty, working = scan_worktree(root, index)
        if changes:
            lines += ["", "uncommitted -- not in effect until committed, and then reviewed like any change:"]
            lines += [f"  {c.block_id} {c.change}: {c.detail}" for c in changes.items]
            lines += _pins_to_write(working, {c.block_id for c in changes.items})
    lines += ["", "next: " + _next(index)]
    return "\n".join(lines)


def _pins_to_write(working: CodeIndex, changed: set[str]) -> list[str]:
    """For each edited region, the header that aligns it once committed as it stands -- against
    the claims at HEAD. Written only after the region was read against those claims."""
    claims = working.claims
    if not claims:
        return []
    out: list[str] = []
    for block in working.blocks:
        if block.block_id not in changed or not block.valid or not block.relations:
            continue
        want = list(header_lines(block, claims))
        have = [block.header(block.pin)] + [r.header(r.pin) for r in block.relations]
        if want != have:
            out.append(f"  {block.block_id}: once committed as it stands, and read against "
                       f"{', '.join(sorted(block.targets()))}, these lines align it:")
            out += [f"      {line}" for line in want]
    return out


def _block_lines(block, claims, index: CodeIndex) -> str:
    pinned = f"@{block.pin}" if block.pin else "unpinned"
    out = [f"{block.block_id} {block.location}  body {pinned} (now @{block.body_pin})"
           + ("" if block.valid else "  INVALID")]
    for r in block.relations:
        expected = f" (now @{claims[r.target].pin})" if claims and r.target in claims else ""
        out.append(f"  {r.kind} {r.target}{'@' + r.pin if r.pin else ''}{expected} "
                   f"[{link_state(block, r, claims)}]")
    return "\n".join(out)


def _next(index: CodeIndex) -> str:
    errors, reviews = index.by_severity(ERROR), index.by_severity(REVIEW)
    if errors:
        return f"fix {len(errors)} broken tag(s) or mention(s) first; each names the line"
    if reviews:
        return (f"review {len(reviews)} region(s) against their claims and write the pins each "
                "names -- a pin says you read this code against this claim")
    if not index.blocks:
        return ("no region is tagged; tag the code that realizes a branch with "
                "`# tdlp:begin CODE-<name>` / `# tdlp:implements BRN-<id>` / `# tdlp:end CODE-<name>`")
    return "every link is aligned"


def section(root: Path, base: str, committed: list[str], worktree: list[str]) -> list[str]:
    """Impact's lines for tagged regions: what base..HEAD did to them, which of those still need
    review at HEAD, and the regions whose file changed around an unchanged body."""
    py = [p for p in committed if p.endswith((".py", ".pyi"))]
    if not py and not [p for p in worktree if p.endswith((".py", ".pyi"))]:
        return []
    head = scan(root)
    base_sha = resolve_revision(root, base)
    if head is None or base_sha is None:
        return []
    lines: list[str] = []
    if py:
        before = build_index(root, base_sha, paths=py, explain_body=False)
        changes = compare_indexes(before, head)
        claims = head.claims
        for c in changes.items:
            block = head.get_block(c.block_id)
            states = sorted({link_state(block, r, claims) for r in block.relations}) if block else []
            tail = f" [now: {', '.join(states)}]" if states else ""
            ask = (f" -- review against {', '.join(c.targets)}" if c.change in (BODY, RELATIONS)
                   and c.targets else "")
            lines.append(f"  {c.block_id} {c.change}: {c.detail}{ask}{tail}")
        for cid in changes.orphaned:
            lines.append(f"  {cid} lost its last implementing region")
        touched = {c.block_id for c in changes.items}
        around = sorted(b.block_id for b in head.blocks if b.path in py and b.block_id not in touched)
        if around:
            lines.append(f"  file changed around {', '.join(around[:6])}"
                         + (" ..." if len(around) > 6 else "")
                         + " (body unchanged; a helper or constant it uses may not be -- the "
                         "component's contracts say whether that mattered)")
    if worktree:
        changes, _, _ = scan_worktree(root, head)
        lines += [f"  uncommitted: {c.block_id} {c.change}: {c.detail}" for c in changes.items]
    return lines
