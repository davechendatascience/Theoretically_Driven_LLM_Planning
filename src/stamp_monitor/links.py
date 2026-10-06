"""Code links as the monitor reports them: the map, what needs review, and what a change did.

Three readings of one index (code_links), all read-only:

  report    the claim <-> region map at HEAD, each link's state, every diagnostic, and the
            uncommitted edits that would change a tagged region
  findings  the audit's share: tags that are broken or out of date, at every revision until
            someone fixes them -- not only in the commit that broke them
  section   impact's share: what the range base..HEAD did to tagged regions

A link is a declared relationship, not evidence: nothing here moves a belief or a proof state,
and a link that needs review blocks nothing. So each link is shown beside the measurement its
claim cites: "aligned" says the code was read against the claim, and only the contract's state
says whether it still works -- a solver upgraded under an unchanged region changes the second
and not the first, and only when the test declares the lockfile in its `reads:`. The CLI's `links --strict` is how a hook or CI makes
it block, by choice.
"""

from __future__ import annotations

import shlex
from fnmatch import fnmatch
from pathlib import Path

from code_links import (ALIGNED, ERROR, EXPLANATORY, OBSERVATION, REVIEW, CodeIndex, Diagnostic, build_index,
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


#: Files whose content is the environment a test ran in. In a test's `reads:`, or named on its
#: run line, they are stamped with its evidence, so a dependency upgrade stales what it measured.
ENVIRONMENT_FILES = ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock", "requirements*.txt",
                     "constraints*.txt", "environment.yml", "environment.yaml", "conda-lock.yml",
                     "pyproject.toml", "setup.cfg", "setup.py", "package-lock.json", "yarn.lock",
                     "pnpm-lock.yaml", "Cargo.lock", "go.sum")


def _names_environment(run: str, reads: list[str]) -> bool:
    try:
        tokens = shlex.split(run, posix=True)
    except ValueError:
        tokens = run.split()
    names = {t.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] for t in [*tokens, *reads]}
    return any(fnmatch(n, pattern) for n in names for pattern in ENVIRONMENT_FILES)


def measurement(root: Path, index: CodeIndex) -> tuple[dict[str, str], list[Diagnostic]]:
    """The state of each contract a linked claim cites, and two observations: a claim whose
    regions read aligned while the evidence it cites is not supported, and a test behind a linked
    claim that declares no environment file. Read from component-belief, as decide() reads it."""
    claims = index.claims or {}
    linked = sorted({r.target for b in index.blocks if b.valid for r in b.relations
                     if r.needs_pin and r.target in claims})
    if not any(claims[t].cites for t in linked):
        return {}, []
    try:
        from component_belief.declarations import load as load_components
        from consistency_belief.declarations import contract_states
    except ImportError:
        return {}, []
    states = contract_states(root) or {}
    decl = load_components(root)
    out: list[Diagnostic] = []
    aligned = sorted({r.target for b in index.blocks for r in b.relations
                      if r.needs_pin and link_state(b, r, claims) == ALIGNED})
    for target in aligned:
        weak = [(c, states.get(c, "not declared")) for c in claims[target].cites
                if states.get(c) != "supported"]
        if weak:
            out.append(Diagnostic(
                "LINKED_EVIDENCE_NOT_SUPPORTED", OBSERVATION, target,
                "its regions read aligned -- their code was read against the claim -- but the "
                f"evidence it cites is {', '.join(f'{c} {s}' for c, s in weak)}: whether that code "
                "still works is not measured"))
    behind: dict[str, set[str]] = {}
    for target in linked:
        for cid in claims[target].cites:
            contract = decl.contracts.get(cid)
            for tid in (contract.evaluable_by if contract else []):
                behind.setdefault(tid, set()).add(target)
    for tid, targets in sorted(behind.items()):
        test = decl.tests.get(tid)
        if test is not None and not _names_environment(test.run, list(test.reads)):
            out.append(Diagnostic(
                "UNSCOPED_ENVIRONMENT", OBSERVATION, tid,
                f"measures what {', '.join(sorted(targets))} cite{'s' if len(targets) == 1 else ''} "
                "and names no environment file (uv.lock, a requirements file, ...) on its run line "
                "or in reads:, so a dependency upgrade under unchanged code stales none of its "
                "evidence -- add the lockfile to its reads:"))
    return states, out


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
    for d in index.by_severity(OBSERVATION) + measurement(root, index)[1]:
        observed.setdefault(d.code, []).append(d)
    for code, items in sorted(observed.items()):
        files = sorted({d.path for d in items if d.path})
        where = f" in {len(files)} file(s)" if files else ""
        sample = ", ".join(display(d.subject, 60) for d in items[:3])
        out.append(Finding("LINK_" + code, INFO, f"{len(items)} item(s)",
                           f"{len(items)}{where}, e.g. {sample}; `stamp-monitor links` lists them"))
    return out


#: Past this many lines of one severity, the full report counts the rest per file instead of
#: listing them: a project with hundreds of untracked mentions produced a report larger than one
#: tool response carries, and the uncommitted pins an agent needed sat at its end.
LISTED = 40


def report(root: Path, subject: str | None = None, *, index: CodeIndex | None = None,
           worktree: bool = True) -> str:
    """The map, each link's state, the diagnostics, and the working tree beside them.

    `subject` -- a region id, a claim id or a scanned path -- narrows every section to it,
    the uncommitted one included, so a region that exists only in the working tree is found by
    its id and its pins are printed. The uncommitted section comes first: it is what an agent
    tagging code acts on next."""
    index = index or scan(root)
    if index is None:
        return "code links: git does not know HEAD here, so there is no revision to scan"
    claims = index.claims
    rev = index.revision[:7]
    states = [(b, r, link_state(b, r, claims)) for b in index.blocks for r in b.relations]
    n_explain = sum(1 for _, _, s in states if s == EXPLANATORY)
    n_review = sum(1 for _, _, s in states if s not in (ALIGNED, EXPLANATORY))
    lines = [f"code links at {rev}: {len(index.blocks)} region(s), {len(states) - n_explain} link(s), "
             f"{len(states) - n_explain - n_review} aligned, {n_review} not"
             + (f"; {n_explain} motivated-by, explanatory only" if n_explain else ""),
             f"scope: {index.scope.describe()}"]
    if not index.validated:
        lines.append("no consistency.yaml at this revision: references and pins are unchecked")

    pending = _uncommitted(root, index, subject) if worktree else []
    contract_state, measured = measurement(root, index)

    def evidence(target: str) -> str:
        cites = claims[target].cites if claims and target in claims else ()
        return ("  ·  evidence: " + ", ".join(f"{c} [{contract_state.get(c, 'not declared')}]" for c in cites)
                if cites and contract_state else "")

    shown = index.diagnostics + measured
    if subject:
        block = index.get_block(subject)
        related = index.for_claim(subject)
        on_path = index.for_path(subject)
        scanned = subject in index.scope.files or any(d.path == subject for d in index.diagnostics)
        if block is not None:
            lines += ["", _block_lines(block, claims, index, evidence)]
            shown = [d for d in index.diagnostics if d.subject == subject]
        elif related or (claims and subject in claims):
            lines += ["", f"{subject}: {len(related)} link(s)" + evidence(subject)]
            lines += [f"  {b.block_id} ({r.kind}) {b.location} [{link_state(b, r, claims)}]"
                      for b, r in related]
            if not related and claims and claims[subject].candidates:
                lines.append(f"  no region links it; its subject {claims[subject].subject} claims "
                             + ", ".join(claims[subject].candidates[:6]))
            ids = {b.block_id for b, _ in related}
            shown = [d for d in index.diagnostics if d.subject in ids | {subject}]
            shown += [d for d in measured if d.subject == subject or subject in d.message.split()]
        elif on_path or scanned:
            lines += ["", f"{subject}: {len(on_path)} region(s)"]
            lines += [_block_lines(b, claims, index, evidence) for b in on_path]
            shown = [d for d in index.diagnostics if d.path == subject]
        elif pending:
            lines += ["", f"{subject} is not in the committed index at {rev}; it is in the working tree only"]
            shown = []
        else:
            return "\n".join(lines + ["", f"{subject!r} is not a region id, a claim id, or a scanned "
                                          f"path at {rev}, and nothing uncommitted matches it either"])
    else:
        by_claim: dict[str, list[str]] = {}
        for b, r, state in states:
            by_claim.setdefault(r.target, []).append(f"{b.block_id} ({r.kind}) [{state}]")
        if by_claim:
            lines += ["", "claims and the regions linked to them:"]
            for cid in sorted(by_claim):
                lines.append(f"  {cid}: " + "; ".join(by_claim[cid]) + evidence(cid))

    if pending:
        lines += ["", "uncommitted -- not in effect until committed, and then reviewed like any change:",
                  *pending]

    for severity, title in ((ERROR, "errors -- tags that are malformed or name nothing"),
                            (REVIEW, "review -- links whose pins no longer match, or were never written"),
                            (OBSERVATION, "observations -- coverage, not defects")):
        items = sorted((d for d in shown if d.severity == severity), key=lambda d: (d.code, d.subject, d.line))
        if not items:
            continue
        lines += ["", f"{title} ({len(items)}):"]
        # Narrowed to a subject, everything is listed. The full report lists errors and reviews up
        # to LISTED and counts the rest; observations past LISTED are counted, never listed.
        listed = items if subject or len(items) <= LISTED else ([] if severity == OBSERVATION else items[:LISTED])
        for d in listed:
            lines.append(f"  {d.code} {display(d.subject, 80)}: {display(d.message, 600)}")
            lines += [f"      {display(f, 200)}" for f in d.fix]
        if len(listed) < len(items):
            lines += _counted(items[len(listed):], listed_some=bool(listed))
    lines += ["", "next: " + _next(index)]
    return "\n".join(lines)


def _counted(items: list, *, listed_some: bool) -> list[str]:
    """Diagnostics too many to list, counted per kind and per file, with where to see them."""
    out = [f"  {'and ' if listed_some else ''}{len(items)} {'more ' if listed_some else ''}counted, "
           "not listed -- links(subject=<path>) lists one file's, links(subject=<id>) one region's "
           "or claim's:"]
    by_code: dict[str, list] = {}
    for d in items:
        by_code.setdefault(d.code, []).append(d)
    for code, group in sorted(by_code.items()):
        per_file: dict[str, int] = {}
        for d in group:
            key = d.path or d.subject
            per_file[key] = per_file.get(key, 0) + 1
        top = sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ", ".join(f"{display(k, 80)} ({n})" for k, n in top[:8])
        out.append(f"    {code} {len(group)} in {len(per_file)} place(s): {shown}"
                   + (f", +{len(top) - 8} more" if len(top) > 8 else ""))
    return out


def _uncommitted(root: Path, index: CodeIndex, subject: str | None) -> list[str]:
    """The working tree's changes to tagged regions, and the pins each edited region needs once
    committed as it stands -- narrowed to `subject` (a region id, a claim it names, or its path)."""
    changes, _dirty, working = scan_worktree(root, index)
    items = changes.items
    if subject:
        items = [c for c in items if subject in (c.block_id, c.path) or subject in c.targets]
    lines = [f"  {c.block_id} {c.change}: {c.detail}" for c in items]
    return lines + _pins_to_write(working, {c.block_id for c in items})


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


def _block_lines(block, claims, index: CodeIndex, evidence=lambda _t: "") -> str:
    pinned = f"@{block.pin}" if block.pin else "unpinned"
    out = [f"{block.block_id} {block.location}  body {pinned} (now @{block.body_pin})"
           + ("" if block.valid else "  INVALID")]
    for r in block.relations:
        expected = f" (now @{claims[r.target].pin})" if claims and r.target in claims else ""
        out.append(f"  {r.kind} {r.target}{'@' + r.pin if r.pin else ''}{expected} "
                   f"[{link_state(block, r, claims)}]" + evidence(r.target))
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
