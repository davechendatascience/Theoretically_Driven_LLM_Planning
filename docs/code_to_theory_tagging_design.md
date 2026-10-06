# Code-to-Theory Tagging Design

Status: Phase 1 and the read-only half of Phase 2 built for 0.7.2; Phase 3 not started
Date: 2026-10-06
Project: Theoretically_Driven_LLM_Planning

## 1. Decision

Implement code tagging as a shared Python module, `code_links`, used by the existing servers. Do not introduce a fifth MCP server for parsing and navigation alone.

Keep source code out of consistency-belief's file-blind deductive verifier. A future code-conformance reviewer may warrant a separate server, with its own contracts, permissions and evidence lifecycle.

A tag is a declared relationship, not a proof. An aligned link means someone said they read this code against this claim as both stand now. It does not establish conformance.

## 2. Purpose and boundaries

Associate lemmas, branches, definitions and axioms with specific code regions. The goals:

- users can navigate between theory and implementation;
- missing mappings show up;
- users can see which correspondence reviews a change affects.

Code changes constantly, so one requirement outranks navigation: **a link that is no longer aligned is reported at every revision until someone deals with it, and an id named in code that no longer exists is reported, not left to rot.**

Three judgments stay separate:

| Judgment | Meaning | Where |
|---|---|---|
| Link validity and alignment | A region exists, its references resolve, and its pins match the code and the claim as they stand. | `code_links`, reported by stamp-monitor |
| Deductive status | A claim follows from declared premises. | consistency-belief |
| Implementation evidence | Tests support the implementation against a contract. | component-belief |

Non-goals, unchanged: proving program correctness; replacing component-belief tests; marking claims proven or supported; executing tagged code; inferring coverage from the presence of tags; a new ledger or server process.

## 3. Module architecture (as built)

```text
src/code_links/
    __init__.py     public API
    model.py        Block, Relation, Mention, Diagnostic, ClaimRef, Scope, CodeIndex
    parser.py       markers and mentions from Python's own tokenizer; the body digest
    index.py        revision-pinned scans (git ls-tree + cat-file at one SHA); the working tree beside it
    validation.py   identity, references, pins, mentions, coverage
    impact.py       compare two inventories: added, removed, renamed, moved, body, relations, repinned
src/consistency_belief/links.py   the theory side: claim pins, the pin history, scan()
src/stamp_monitor/links.py        the reports: the map, audit findings, impact's section
```

`code_links` imports nothing from any server. Each consumer passes in what it owns: consistency-belief passes the claims and their pins, and stamp-monitor decides what blocks and what informs. The module writes nothing and has no authority over proof states, evidence, declarations or policies.

## 4. Tag syntax

```python
# tdlp:begin CODE-servo-acceleration-cap@3f9a1c2e
# tdlp:implements BRN-servo-respects-acceleration-bound@7c41d0e2
# tdlp:uses LMA-vector-scaling-preserves-direction@19be44a0

delta = requested - previous
delta = cap_norm(delta, max_acceleration * dt)
executed = previous + delta

# tdlp:end CODE-servo-acceleration-cap
```

The `@xxxxxxxx` suffixes are **pins** (section 5). A tag may be written without them first. The scan then reports it as `UNPINNED` and prints the exact lines to write.

| Relation | Meaning | Pins |
|---|---|---|
| implements | The block is intended to realize the referenced node. | required |
| uses | The block relies on the referenced result. | required |
| checks | The block checks an aspect of the claim, through an assertion or a test. | required |
| motivated-by | An explanatory association; no correspondence asserted. | optional, checked when present |

Rules:

- Block ids are `CODE-<name>`, unique in the revision. Duplicates are reported, and none of them counts.
- Targets are `AXM-`, `DEF-`, `LMA-` or `BRN-` ids in the premise graph at the scanned revision. The draft allowed only LMA/BRN; see section 12.
- There is one relation per line. Relations go in the header, after `begin` and before the first code token. Plain comments may sit between them.
- Regions may not nest or overlap, begin and end must name the same id, and a region cannot cross files.
- An empty region, or one with no relations, gets a diagnostic. An empty region is never aligned.
- Only real comments are markers. Python's tokenizer decides what a comment is, so marker text inside a string or a docstring is not a marker.
- Any other tracked file that carries a line shaped like a marker is reported as `UNSUPPORTED_LANGUAGE`, rather than read by a guess at its comment syntax.
- `# tdlp:foreign-ids <why>` marks a file whose ids belong to projects it builds, such as a test suite writing fixture declarations. Its mentions are not checked. Its regions are checked as usual, and the scope line lists the file.

## 5. Alignment: how links stay true while code moves

### 5.1 Two pins, written in the source

| Pin | Covers | Goes stale when | Does not go stale when |
|---|---|---|---|
| **Body pin**, on `begin` | The region's code tokens. Comments, blank lines and whitespace inside a line are set aside. Each logical line keeps its indentation relative to the region. Each f-string or t-string counts as one token. | a token changes, or a statement moves into or out of a branch | a formatter run, a comment edit, the region moving to another file, line or nesting level |
| **Claim pin**, on each relation | the target's fingerprint (statement plus cited premises) and the fingerprint of every node it depends on: what a verification trial binds to (DEF-current-trial) | the claim is restated, a premise anywhere upstream is restated, or a premise is added or dropped | a derivation-rule edit, such as re-citing a `CTR-` or rewording the argument |

The claim pin uses consistency-belief's own fingerprints. That keeps one meaning of "stale" across the harness: a link goes stale exactly when a trial of its claim would. If a definition three levels up is restated, the trials of the branch above it go stale, and so does every region that implements that branch.

### 5.2 Why the pins live in the code

Comparing base with HEAD shows what one range of commits did, and that report disappears in the next range. A body edit that nobody reacted to in commit N is gone from `impact HEAD~1` by commit N+1. That is the stale mention this design exists to catch.

A pin is the persistent reference point. Every scan at every revision compares each pin with what is there now, so a link edited without review stays reported until someone re-reads it and updates the pin. The update is part of a commit, and so it is reviewable. A commit's trailer already says who made it, so a re-pin by the agent carries the agent's name.

Nothing writes pins. The finding prints the header lines to paste. A pin is an assertion, and the scan only checks it.

### 5.3 Link states

Every link ends in exactly one state:

| State | Meaning | Severity |
|---|---|---|
| aligned | both pins present and matching | (none) |
| unpinned | never reviewed; the finding prints the lines to write | review |
| body changed | the code differs from the pinned body; names the revision to `git diff` against | review |
| claim restated | the claim, or something upstream, was restated since the pin; names the revision and which nodes changed | review |
| unknown claim | the target is not in the premise graph at this revision (removed, renamed, staged only, or not admitted) | error |
| invalid block | malformed, nested, empty, or sharing its id | error |

### 5.4 Mentions

An id written in a comment or docstring, outside a marker, is a mention. Ids in other string literals are data (messages, fixtures, patterns) and are not read.

| Mention | Reported as |
|---|---|
| names nothing at this revision | `DANGLING_MENTION`, an error: the stale mention itself |
| inside a region whose relations cover it, either a target or a node a target depends on | tracked; its rot is caught by that relation's claim pin |
| anywhere else | `UNTRACKED_MENTION`, an observation: it will go stale with nobody watching |

### 5.5 Scope is reported

Every report states the revision, how many Python files were scanned, and what was not scanned and why: documentation, ledger directories, symlinks (never followed), submodules, over-size files, and files marked `foreign-ids`. "No finding" means no finding *within that scope*.

## 6. How the servers use it

| Server | Uses | Surface |
|---|---|---|
| consistency-belief | `links.claim_refs` supplies each node's pin. `audit_change` lists the regions a restatement would unpin, by id only. | **No new view.** The verifier holds `status`, so a code-navigation view there would hand it paths into the implementation. The probe is unchanged. |
| stamp-monitor | `links(subject)` gives the map: each link's state, every diagnostic, and the working tree beside it. `audit` adds `LINK_*` warnings for every error and review, and once a project has tagged a region, one info line per kind of observation. `impact` gets a "tagged code regions" section. | the 4th MCP tool; CLI `stamp-monitor links [--subject X] [--strict]` |
| graph-snapshot | Each claim, axiom and definition node lists its regions (id, relation, location, link state), computed at the snapshot's own commit. Link errors and reviews appear in the Issues tab under `code links`. No region is a node or an edge, and no source text is copied. | the snapshot page |
| component-belief | Not yet: blocks shown beside contracts. | none |

`links(subject)` narrows every section to a region id, a claim or a path, including the uncommitted section. A region that exists only in the working tree is found that way, with its pins. The full report puts the uncommitted section first. Past 40 lines, the rest of a severity are counted per file, so it fits in one tool response on a large project.

A link never blocks in `audit`, because it is not evidence. `stamp-monitor links --strict` exits 1 on any error or review. It is how a CI job or a pre-push hook makes "every tagged region was reviewed against its claim as both stand now" a condition of landing.

`impact` reports a region **beside** the chain, never on it. A changed region asks for a review of that link. It adds no reason to the design branch it implements, and the branch is still reached only through its component.

## 7. Adoption: code that has no ids yet

`stamp-monitor links` on an untagged project gives the worklist:

1. **Untracked mentions.** Comments and docstrings that already cite a node. On this repository: `model._partition`'s docstring cites DEF-current-trial, and two comments in `component_belief/server.py` cite DEF-belief-eligible. These are the seeds.
2. **Unlinked branches**, each listed with the files its subject component claims in `belief.yaml`. That narrows where the realizing code is.
3. **Dangling mentions.** Ids that no longer exist. Fix these first.

For each region the agent:

1. Wraps the code that realizes the node, picking a descriptive `CODE-` id. Renaming it later reads as removed plus added, and `impact` reports a removed and an added region with the same body as `renamed`.
2. Writes the relations without pins.
3. Runs `stamp-monitor links`. Its uncommitted section prints the header lines that would align each edited region **once committed as it stands**, against the claims at HEAD. Tagging and pinning therefore take one commit.
4. Reads the region against the claim (`status(view="branches", subject=<id>)` gives the statement), pastes the lines, and commits.

From then on:

- editing a tagged body without re-pinning stays a review finding;
- restating a claim gets listed by `audit_change` before it happens, and shows as `CLAIM_RESTATED` after;
- deleting the last region that implements a claim shows in `impact` as "lost its last implementing region".

## 8. Change and freshness semantics

| Change | Effect |
|---|---|
| Code body changes | `BODY_CHANGED` until re-pinned; `impact` says `body` for the range. Deductive status is unchanged. |
| Block moves with identical contents | `impact` says `moved`; the pins hold. |
| Relation changes | `impact` says `relations`, with what was dropped and added; a new relation is `UNPINNED`. |
| Claim or any premise upstream restated | `CLAIM_RESTATED` until re-pinned. The deductive rules apply as before. |
| Claim removed or renamed | `UNKNOWN_CLAIM` on the tag, and `DANGLING_MENTION` on any prose naming it. |
| Block deleted | `impact` says `removed`, and names any claim that lost its last implementing region. |
| The file changes around an unchanged body | `impact` lists it as changed around, because a helper or constant the block uses may not be the same. Component staleness, by file, still decides whether evidence counts. |

Block digests never replace file-level staleness. Narrower dependency tracking is future work.

## 9. Diagnostics

Errors:

- `MALFORMED_MARKER`, `UNKNOWN_MARKER`
- `UNMATCHED_BEGIN`, `UNMATCHED_END`, `MISMATCHED_END`, `NESTED_BLOCK`
- `MISPLACED_RELATION`, `DUPLICATE_RELATION`, `EMPTY_BLOCK`, `NO_RELATIONS`, `DUPLICATE_BLOCK`
- `UNKNOWN_CLAIM`, `DANGLING_MENTION`
- `UNSUPPORTED_LANGUAGE`, `SOURCE_UNPARSABLE`, `SOURCE_UNREADABLE`, `SOURCE_READ_FAILURE`

Review: `UNPINNED`, `BODY_CHANGED`, `CLAIM_RESTATED`.

Observations: `UNTRACKED_MENTION`, `UNLINKED_CLAIM` (judged only on a full scan), `SOURCE_TOO_LARGE`.

## 10. Security and provenance

- Only tracked files at one resolved commit are read: `git ls-tree` and `git cat-file --batch` at that SHA. A commit landing mid-scan changes nothing the scan sees. The working tree is a separate report and is never merged in.
- Source is never executed or imported. Symlinks and submodules are not followed. Ledger directories are not read. No network access.
- Tag and source text is untrusted: control characters are shown escaped and long lines are cut (`display`). No snippets of source are emitted: reports carry ids, paths and lines.
- `GRAMMAR_VERSION` is part of the body digest, so a future change to the normalisation is explicit.
- Agent-written tags and pins grant no authority over axioms, policies or verdicts.

## 11. Acceptance tests

`tests/test_code_links.py`, one or more cases each:

1. Resolve a block and reverse-look-up its claim.
2. Several claims per block, several blocks per claim.
3. Duplicate ids across files.
4. Missing, mismatched and nested markers, and regions crossing files.
5. Marker text in strings and docstrings.
6. Unknown claims and relation kinds.
7. Identity across movement and inserted lines.
8. Body change versus relation change versus re-pin.
9. Reads pinned to one revision while HEAD moves.
10. Working-tree edits reported, never indexed.
11. Adding a link moves no proof state.
12. No code in the probe.
13. A deleted block orphans its claim; a change around an unchanged body is listed.
14. Hostile tag text is escaped.
15. Unsupported languages and unreadable or unparsable files.
16. Links do not enter the premise graph.

Added for alignment:

- unpinned links print their fix;
- formatting and comment edits keep the pin;
- a body edit stays reported across later commits, names the revision to diff against, and clears on re-pin;
- a statement moved into a branch is a change;
- an upstream restatement stales every link resting on it;
- a derivation-rule edit restates nothing;
- a removed claim leaves its tag unknown and its mentions dangling;
- tracked, untracked and foreign mentions;
- unlinked branches name candidate files;
- `audit_change` lists unpinned links by id only;
- the monitor writes nothing;
- `links --strict` exit codes.

## 12. Decisions against the first draft

| Draft | Built | Why |
|---|---|---|
| `source_hash` and `body_hash` as identity of the inspected version | the same, plus **pins written into the tag** | a base..HEAD comparison forgets an unreviewed edit after one more commit, and a pin does not |
| a raw body hash | a token digest with comments and layout set aside | otherwise every formatter run asks for a re-review of every block, and re-pinning decays into rubber-stamping |
| claim pin, unspecified | the node's fingerprint plus everything upstream | it binds to what a trial binds to, so stale has one meaning |
| targets LMA- and BRN- only | AXM-, DEF-, LMA- and BRN- | this repository's own code realizes definitions: `model._partition` realizes DEF-current-trial, and `ProofDAG.from_declarations` realizes DEF-premise-graph |
| consistency-belief: link metadata | claim pins, and `audit_change` naming unpinned links by id; no view | the verifier holds `status`; a links view there would hand it the paths |
| graph-snapshot: code nodes and typed relations | regions listed on the node they relate to; no code nodes, no edges | the snapshot's graph is "rests on" edges, and a region is not a premise of what it realizes; the page renders every field with `textContent`, so hostile tag text is inert there too (test 14) |
| comments only | comments and docstrings for mentions; comments only for markers | docstrings are where this code cites the theory it follows |
| (none) | `# tdlp:foreign-ids` | a harness that tests itself writes fixture ids that resolve nowhere; the opt-out is per file, explicit, and listed in scope |

## 13. Proposed, not built: theory against measurement

A link joins a claim to code, and the claim already cites the contract that measures it. That allows a per-link quadrant:

| | cited contract supported | cited contract refuted |
|---|---|---|
| claim proven | consistent | **contradiction**: the code does not realize the claim, a premise is false of the world, or the test measures something else |
| claim not proven | works, unargued; if the claim is refuted, its counterexample is a scenario no test exercises | open on both sides |

"Where it fails" enters only as a measurement: a failing case recorded by `run_test`, in a test region tagged `checks`. An agent's account of where the failure is would be an assertion, and assertions carry zero weight (`note()`). This would be a read-only section of `stamp-monitor links`, and needs no new record.

## 14. Delivery

- **Phase 1, built:** the parser, the revision-pinned index, reference and pin validation, mentions, and tests.
- **Phase 2, built, read-only:** `stamp-monitor links`, `audit` findings, the `impact` section, `audit_change` naming unpinned links, and regions on the graph-snapshot page.
- **Phase 2, not built:** component-belief showing blocks beside contracts; the theory-against-measurement section (section 13).
- **Phase 3, not started:** a conformance reviewer, only once its responsibilities, threat model, evidence records and acceptance gates are defined.
