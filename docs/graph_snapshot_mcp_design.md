# graph-snapshot: one page for the whole design graph

Status: declared 2026-10-06 (`DEF-snapshot`, `BRN-snapshot-shows-one-revision`, `CMP-graph-snapshot`
planned), to be built after the verifier pass. The prototype pages are
[this repository at 2ee5f30](https://claude.ai/artifact/CHkMx94oJ3UbAyQqC9MdB8) and
[embodied_ai at 1402e5a](https://claude.ai/artifact/3GeFFnW8LH4b7dEJ8xif8G).

## What it answers

"Show me every component, the theory it rests on, and the proof tree behind each claim."

Today that answer is spread across four reads: `component-belief status(view="graph")` for the
components, `consistency-belief status(view="coverage")` for which branch governs each one,
`status(view="audit", subject=CMP-…)` for the axioms and definitions beneath it, and
`status(view="tree")` for the proof DAG. The tree view is rooted at axioms, prints shared
premises as "(shown above)", and cuts each statement at 110 characters. None of these views can
show a 300-node graph in a form someone can read.

graph-snapshot joins the three declaration files at one revision into one graph. It writes that
graph as a single self-contained page, which can be opened in a browser or published as an
Artifact.

## What it is not

* **Not a belief server.** It records nothing and decides nothing. Every state on the page comes
  from the server that owns it: a lemma's or branch's proof state from consistency-belief's own
  `Context`, and a component's coverage (governed, undeclared design, planned) from the same
  declarations rule that `status(view="coverage")` applies. Hence the name: it has no `-belief`
  suffix, and it stands beside stamp-monitor as a reader.
* **Not an event trace.** It reads no evidence ledger and lists no trials, runs, amendments or
  decisions. Contracts appear only as names: what a component is measured by, and what a branch
  cites. Evidence state stays in component-belief. Asking "is the evidence for this still current?"
  is stamp-monitor's job.
* **Not live.** A snapshot names its revision and the time it was taken. The page says it does not
  update. To see later commits, take a new one.

## Principles

1. **Only what the owners compute.** The snapshot adds edges, never verdicts. It imports
   `consistency_belief.views.Context` and `component_belief.declarations.load`, as stamp-monitor
   does, so "proven" and "governed" each have one definition.
2. **One revision.** Resolve HEAD to a sha once, then read every declaration at that sha. The
   prototype read `HEAD` symbolically. During its first, 12-minute run on embodied_ai, another
   session committed there, so the declarations and the recorded revision came from different
   commits. The two loaders and `Context.build` take a `revision` argument, `"HEAD"` by default,
   so the servers are unchanged and the snapshot passes the sha it resolved.
3. **Declarations and proof state, no evidence.** This is also what makes the snapshot affordable
   (see [Measured cost](#measured-cost)).
4. **Writes only its own page.** The page goes in `.graph-snapshot/`, which carries its own
   `.gitignore` (`*`). It never shows up in `git status`, whatever the project's `.gitignore`
   says. It writes nothing to `.belief/`, `.consistency/` or any declaration file. If a
   declaration names that directory, for example a test that `reads:` the page, it writes
   nothing, because rewriting a page a stamp covers would stale evidence.

## Tool surface: one tool

Each server's schemas cost context in every session, so there is one tool:

```
snapshot(focus: str | None = None) -> str
```

* It writes `.graph-snapshot/snapshot.html`, a standalone page to open in a browser, and
  `.graph-snapshot/artifact.html`, the same page without the document wrapper. The Artifact page
  contract forbids `<!doctype>`/`<html>`/`<head>`/`<body>`, and a local file without a doctype
  renders in quirks mode, so the two files differ only in that wrapper.
* `focus` names the node the page opens on (any id). Without it, the page opens on the first
  governed component.
* It returns four lines: the title block, the state counts, and the two paths. For example:

```
graph snapshot: embodied_ai @ 1402e5a (2026-10-06) · consistency.yaml git-HEAD · belief.yaml git-HEAD · goals.yaml b7ed05a
branches 146: 61 proven, 75 stale, 7 doubted, 3 obligation · lemmas 22: 7 proven, 8 doubted, 4 stale, 2 refuted, 1 obligation
components 24: 9 governed, 15 undeclared design · interfaces 12: no design claim · 82 axioms (none traces to a goal) · 20 definitions · 4 goals
page: .graph-snapshot/snapshot.html (open in a browser) · .graph-snapshot/artifact.html (publish as an Artifact)
```

The server never publishes an Artifact itself. A published page is a copy of the design on
claude.ai, so publishing is for the human to ask for and for Claude to do with the Artifact tool.

## The snapshot

One JSON document embedded in the page:

| Field | Holds |
|---|---|
| `project`, `revision`, `subject`, `committed`, `taken` | what it is a snapshot of |
| `sources` | each declaration file and where it was read (`git-HEAD`, a goals.yaml blob, `none`) |
| `pending` | which declaration files have uncommitted edits the snapshot does not show |
| `nodes` | goals, axioms, definitions, lemmas, branches, components, interfaces, each with its full text; lemmas and branches carry premises, derivation rule, proof state, `n_independent/n_min`, the first issue, staged, cited contracts and gating policies; components carry purpose, capability, goal, code paths, coverage and contract names |
| `edges` | `[a, b]`: *a rests on b*. A component rests on the branches that govern it, a claim on its premises, an axiom on the goal whose requirement it states |

All edges point one way ("rests on"), so a node's lineage is two closures: what it rests on, and
what rests on it.

## Presentation

There are three panes, because no single picture of embodied_ai works. Its graph has 310 nodes and
865 edges, and its branches cite branches 251 times, in chains up to 12 deep. A map with one column
per kind would draw hundreds of edges inside one column. A full layered map would need about 17
columns.

1. **Index.** Four tabs:
   * **Components**: each component or interface, its coverage, and one mark per branch that
     governs it, worst first.
   * **Claims**: every branch and lemma, worst first (refuted, doubted, stale, obligation,
     proven), with filter chips.
   * **Foundations**: goals, axioms and definitions, each with how many components rest on it.
   * **Issues**: the declaration issues the loaders already report, under their own codes; the
     gaps only the joined graph shows (an axiom naming no goal, a goal no axiom names, a component
     with code and no design, an interface or goal with no design claim, an axiom or definition
     nothing rests on, and since 0.7.6 a contract no branch cites, marked as a goal's, an
     interface's or a component's measure); the cited measurements not reviewed against their
     claims, in their own group (0.7.6); broken code tags and unaligned links (0.7.2); and a count
     of claims not proven, linking to the Claims tab. Each issue links to its node, and the
     inspector lists a node's own issues. The inspector also shows a branch's cited measurements
     with their review state, any node's tagged code regions with their link state, and (0.7.7)
     the sources a node references, as a list and never an edge, since a reference is no premise.
     From 0.7.8 a conditional claim -- its own step verified over a step that is not -- is drawn
     as a ring between open and proven, and its inspector names the steps it waits on. Both are
     judged from the declarations and code at the snapshot's commit, so no evidence is read.
2. **Lineage.** The selected node, everything it rests on and everything that rests on it, drawn
   left to right as "rests on":
   * Claims are placed in columns by longest path, with definitions, axioms and goals as the last
     three columns.
   * An edge that crosses a column runs through a lane slot there, shared by every edge bound for
     the same premise. An edge therefore never passes behind a node it does not touch.
   * Clicking a node walks to it, and Back returns.
3. **Inspector.** The selected node in full:
   * the claim and its derivation rule, with every id a link;
   * why it is in its state, for example "3 trial(s) verified it before AXM-… was restated";
   * the proof tree as a collapsible outline down to axioms and definitions;
   * for a component, every axiom, definition and lemma beneath it.

A title block sits across the top, like a drawing's. It holds the revision, when the snapshot was
taken, and which file was read from where. A banner appears when declarations have uncommitted
edits. State is shown by mark shape as well as colour: a filled dot for proven or governed, a ring
for open, half-filled for doubted, dashed for stale, a diamond for refuted, and a dotted border
for staged. The page works in light and dark themes and at phone width.

## Measured cost

| | this repository | embodied_ai |
|---|---|---|
| nodes / edges | 68 / 87 | 310 / 865 |
| snapshot, declarations and proof states | 0.1 s | 1.1 s |
| page size | 99 KB | 1.3 MB |
| with contract states (first prototype) | — | 12 min 37 s |

The 12 minutes is `component_belief.staleness.CodeStaleness.stale_reason`, called once per
evidence record (600,670 in embodied_ai). Each call matches every file at HEAD against the
component's `code:` globs: about 3,200 `fnmatch` calls per record, or 50 million on a 20,000-record
sample. The answer depends only on the run's stamp and the code paths, so it could be cached per
(run, stamp, code paths). **That is a component-belief defect, separate from this design.** It
slows every full slice computation in a large ledger: component-belief's status views,
consistency-belief's `coverage` view and the `evidence: supported` gate in `decide`, and
stamp-monitor's `impact`.

## What the prototype found in embodied_ai

* None of its 82 axioms carries `goal:`, so nothing traces the theory to its four goals.
* 15 of 24 components are undeclared designs (code with no declared branch). None of its 12
  interfaces has a design claim.
* 75 of 146 branches are stale and 2 lemmas are refuted. The Claims tab lists these first.

## Declarations first

Following this repository's order, the theory is committed and verified before any code.

**belief.yaml**: `CMP-graph-snapshot`, `goal: GOL-sound-designs`, declared with no `code:` (so it
reads as planned) until the code commit adds `src/graph_snapshot/`. Its contract is
`CTR-snapshot-shows-one-revision` (gate), measured by `TST-graph-snapshot`. Its failure modes,
each observed by a named case:

| Failure mode | What would be observed |
|---|---|
| `FM-state-invented` | a lemma or branch shows a proof state the consistency server does not compute for it |
| `FM-revisions-mixed` | a snapshot names one revision and shows a declaration committed at another |
| `FM-worktree-shown` | an uncommitted declaration edit appears in a snapshot, or goes unmentioned |
| `FM-gap-missed` | an axiom naming no goal, or a component with code and no design, is not listed as a gap |
| `FM-snapshot-writes` | taking a snapshot changes a ledger file or a declaration file |
| `FM-reads-evidence` | taking a snapshot reads the component ledger's evidence |
| `FM-page-tracked` | `git status` lists the page |
| `FM-page-is-evidence` | a snapshot rewrites a page that a declared test or component names |
| `FM-template-missing` | installed as a package, the server finds no page template |

**consistency.yaml**: list `CMP-graph-snapshot` under `components:`, and add one definition and
one branch, both in the file:

* `DEF-snapshot` states the mechanism: one resolved commit, the premise graph built from it and the
  staged proposals as read, each proof state the one `DEF-proof-state` gives, the issues and gaps
  listed, no contract state and no evidence read, no ledger record and no declaration changed,
  and one page written where no declaration names it.
* `BRN-snapshot-shows-one-revision` (subject `CMP-graph-snapshot`, evidence
  `CTR-snapshot-shows-one-revision`) derives from it, as `BRN-monitor-moves-nothing` does from
  `DEF-report`, that every declaration shown is from the named revision, every proof state is the
  premise graph's, and taking a snapshot changes no measured belief and no proof state.

Widening `DEF-report` to cover a written page would have restated it and staled the proven
`BRN-monitor-moves-nothing`. A separate definition stales nothing: the commit's only new
fingerprints are the two new nodes. `POL-consistency-gate` and `POL-release` gain the new
branch and contract.

## Build

* `src/graph_snapshot/`: `snapshot.py` (the join, the pinned revision, the gaps), `page.py` with
  `page.html` (the template, read through `importlib.resources`), `server.py` (FastMCP, one
  tool), and `cli.py`, so `graph-snapshot [--focus ID]` runs from a shell like `stamp-monitor`
  does.
* `revision="HEAD"` on `component_belief.declarations.load`, `consistency_belief.declarations.load`
  and `import_subjects`, and on `Context.build` and its historical builds. This stales
  `CTR-declarations-gate`, `CTR-consistency-declarations-gate` and `CTR-trial-ledger-replay`, so
  their suites run again.
* `pyproject.toml`: scripts `graph-snapshot-mcp` and `graph-snapshot`, and
  `[tool.setuptools.package-data] graph_snapshot = ["*.html"]`.
* `plugin/.mcp.json`: a fourth server, `GRAPH_SNAPSHOT_ROOT=${CLAUDE_PROJECT_DIR}`, from the same
  tag. `TST-plugin` already requires every server to agree on the tag.
* `tests/test_graph_snapshot.py`: one case per failure mode above, plus this repository's own
  snapshot, which has every node and the same proof states as `status(view="cycle")`.
* Release as 0.7.0. Bump `pyproject.toml`, `plugin.json`, the marketplace entry and the tag
  together.

## Open decisions

1. **Contract states on the page.** They are left out, by your call ("only the snapshots, not
   the events"), and on embodied_ai they would cost 12 minutes until `stale_reason` is cached.
   Revisit once it is?
2. **Web fonts.** The page loads three faces from Google Fonts. Opened locally, that is one
   request carrying nothing from the snapshot, and offline it falls back to system fonts. Keep
   them, or ship the local page with system fonts only?
3. **One page or one per revision.** The proposal overwrites `.graph-snapshot/snapshot.html`.
   Keeping `<sha>.html` per revision would allow before-and-after comparison, at the cost of a
   directory that grows.
