# Changelog

Newest first. Versions are the `tdlp` plugin's, released as git tags `tdlp--v<version>`. Before
0.2.0 the harness was installed by hand at version 0.1.0 and never tagged. The ids point at the
change itself; an `evidence:` commit recording the suites' runs follows each.

## 0.9.0 — 2026-10-09 · a Lean certificate beside the statements

- **`certify()`** proves a lemma or branch in Lean before its verifier pass, an optional step.
  The committed source goes to a Lean service, which checks it once; its answer is kept whole in
  the ledger, bound to the node's fingerprint and the statements of the premises it cites.
  - `lean-prover`, the default: a Lean prover server. The sources are committed to a repository
    it hosts, it checks the declaration against `expected_statement` at that commit, audits every
    axiom, and keeps a certificate with a digest. A gateway timeout is recovered by the request's
    claim id, and `certificate_id=` adopts a certificate it already holds.
  - `axle`: Axiom's AXLE, which checks a proof against a sorried formal statement and admits
    Lean's standard axioms only.
- **The verifier reads the statements, and the certificate beside them.** The probe adds the Lean
  statement checked and what each axiom standing for a premise states, read from the committed
  source. A live run showed why the axiom's statement matters: a stand-in written over every pair
  of reals, `compute + motors ≤ 100`, is false and proves anything, and its name alone hides that.
- **A certificate moves no proof state.** A restatement of its node, or of a premise the node
  cites, sets it aside; a failed, mismatched or edited one is recorded and never served. A policy
  criterion may require one: `formal: certified`.
- **Addresses and keys stay out of the repository.** `certify(url=...)` takes the address the
  user gives; keys come from the environment or an untracked `.lean-services.yaml`, refused when
  git tracks it. The ledger records the service and its id for the check, never an address.
- `status(view="certificates")`; a tree badge `· LEAN` marks a node a certificate certifies.
- **Theory.** `DEF-lean-certificate` and `BRN-lean-certificates-beside-the-statements` are new;
  `DEF-source-reference` was restated, since its probe clause now names certificates. That leaves
  `BRN-references-carry-no-weight` stale until its next verifier pass.

## 0.8.1 — 2026-10-08 · reviews travel with the code, and a link's claim reads one layer

From a second report on code links, from embodied_ai.

- **Reviews have a tracked file of their own.** embodied_ai ignores `*.jsonl`, so its 0.8.0
  reviews, written to `events.jsonl`, existed on one machine. Reviews now go to
  `.consistency/reviews.yaml`. The first new review carries over those already in `events.jsonl`.
  `review()`, `links` and `status(view="reviews")` say when git ignores the file and give the line
  to add.
- **A link's claim digest reads one layer**, as trials have since 0.7.8: the claim's statement and
  the statements of the premises it cites.
  - In embodied_ai, 6 of 18 links reading `claim restated` had moved only two or more citations
    up; they read aligned now.
  - Header pins, derivation-rule pins and 0.8.0 reviews recorded the earlier digest. Each is
    judged as the one-layer digest its claim had at the latest revision with that earlier digest,
    so the change stales nothing.
  - `audit_change` lists the links and measurements of the node and the nodes citing it.
- **A moved function keeps its review.** A region no longer present, reviewed for the same claim
  with the same body, hands its review to the region now holding that code.
- **Which review decides.** `links` names it for each link: the ledger review (id, commit, actor)
  or the header pin under the old grammar. `HEADER_PIN_SUPERSEDED` suggests dropping a pin once a
  ledger review exists.
  - The report's "every header pin went stale" was this display: a new-grammar digest printed
    beside an old-grammar pin. embodied_ai read 43 aligned before and after 0.8.0.
- **`status(view="reviews")`** lists every review, newest first, with the latest marked.
- **Theory.** `DEF-code-link` (the claim digest) and `DEF-review` were restated, along with the two
  link branches.
  - Round one doubted both branches. It found the old digest's coverage unstated, and a loophole:
    renaming a region and keeping its pins could set aside a failed review.
  - `DEF-review` now orders a link's reviews: its own, then a moved region's, then its pins. The
    code was changed to match.

## 0.8.0 — 2026-10-08 · reviews are ledger records bound to a commit, and a docstring declares a region

From a field report on code links from RoboPraxis (27 regions, 70 header pins), and the user's
call that pins do not belong in the source.

- **`review()` records a review, in `.consistency/`, never in the source.**
  - A review names a code link (region and claim) or a cited measurement (branch and contract),
    the commit it read, the code and claim digests there, `aligned` or `not_aligned`, and a note.
  - It is refused while the region's file or the claim's declarations have uncommitted edits, so
    the commit holds what was read.
  - The latest review decides: a link reads `aligned`, `unreviewed`, `review failed`,
    `body changed` or `claim restated`.
- **A docstring declares a region.** `Implements:`, `Uses:`, `Checks:` and `Motivated-by:` lines
  in a function, class or module docstring make that definition a region. An optional
  `Region: CODE-x` line names it; otherwise its id comes from its path and qualified name.
  Regions nest. Prose mentions in a docstring now suggest a `Uses:` line, not deleting them.
- **Documenting code asks for no re-review.** The body digest under the new grammar sets
  docstrings aside, as comments and layout already were.
- **The review bundle.** For each link to review, `stamp-monitor links` shows the claim as it
  stands, a word diff of what moved in it since the review, the code diff since (the region's
  hunks only), and the last reviewer's note. The snapshot shows each link's and measurement's
  latest review: id, commit, actor and note.
- **Nothing goes stale on upgrade.** Header pins and derivation-rule pins still count as reviews,
  compared under the old grammar, which kept docstrings. A ledger review replaces them once
  recorded. The `@hash` can be dropped from a header whenever its file is next touched.
- "Unpinned" is now "unreviewed" (`UNREVIEWED`, `MEASUREMENT_UNREVIEWED`).
- **Theory.** `DEF-review` is new. `DEF-code-link`, `DEF-aligned-link`, `DEF-cited-measurement`
  and `DEF-snapshot` were restated, along with the two link branches. The verifier's first round
  found DEF-review silent on what a pin names and on withdrawal. Both were added; the code already
  behaved that way.
- **Not yet:** a review records the claim and the code, not the relation kind, and not the
  contract's own rule or tests. Restating a contract leaves its reviews standing.

## 0.7.8 — 2026-10-07 · a proof rests on its steps

Reported from embodied_ai on 0.7.7: `BRN-chain-is-the-models` was refuted, and two branches
resting on it still read `PROVEN 3/3`.

- **`PROVEN` now means the whole proof.**
  - A lemma or branch is proven only when its own step and every step beneath it are verified.
    One whose own step is verified over a step that is not reads `CONDITIONAL`, like a Lean
    theorem over a lemma proved by `sorry`.
  - It keeps its trials and names what it waits on, worst first:
    `[CONDITIONAL 3/3 · rests on REFUTED BRN-x]`.
  - `contradictions` lists the ones resting on a refuted or ungrounded premise. `obligations`
    lists them as nothing to probe. `decide()` passes none under a criterion requiring `proven`.
    The basis line counts them as `conditional=N`.
  - The state is computed at every read from the trials taken as a set, so the order the trials
    came in decides nothing.
- **A trial vouches for one step, so a restatement re-opens only the steps that read it.**
  - A trial records the statement of each premise its target cites, which is what its probe
    showed, and counts while those stand.
  - Restating a node sets aside its own trials, and those of the steps citing it if its statement
    changed. Everything further down keeps its trials and is proven again, with no verifier pass
    of its own, once those steps are.
  - A premise proven again at a *new* statement discharges nothing: the steps verified against
    the old one stay set aside.
  - Trials from before 0.7.8 recorded fingerprints. They are compared on their cited premises'
    fingerprints only, no longer on every node upstream.
  - `audit_change` reports the steps that need a pass apart from those that only wait.
- **On embodied_ai's ledger** (2026-10-07, before and after):
  - 35 claims that read `PROVEN` now read `CONDITIONAL`.
  - 3 that read `STALE` keep their trials and read `CONDITIONAL`, so `STALE` falls from 4 to 1.
  - 2 read `DOUBTED`: entailment gaps recorded against exactly their current claim and premises
    had been set aside only by a change deeper down, and count again.
- **The theory here was restated to match.** `AXM-blast-radius-invalidation`,
  `DEF-current-trial`, `DEF-proof-state` and `LMA-blast-radius-propagation` were restated, and
  `BRN-proven-rests-on-proven` is new. The verifier rounds falsified the lemma once and found
  gaps in `DEF-code-link`, `DEF-report` and the declarations gate. Each was fixed by saying what
  the code already did.
- graph-snapshot draws a conditional claim as a ring, between open and proven, and its inspector
  names the steps it waits on.

## 0.7.7 — 2026-10-07 · sources cited like a paper's references, and one node's tree

- **A declaration can reference the works it came from.**
  - `consistency.yaml` takes an optional `sources:` list (id, title, authors, year, doi, arxiv,
    isbn, url, note). Any axiom, definition, lemma or branch can name sources in `references:`,
    each with an optional place in the work (`at:`).
  - A reference is for the reader and weighs nothing in a proof. It is not a premise, not part of
    a fingerprint, never an edge, and never in a probe, whatever the source's id. Adding one
    restates nothing. Citing a famous result makes no claim count, and a verifier never sees the
    name. Stated as `AXM-references-carry-no-weight`, `DEF-source-reference` and
    `BRN-references-carry-no-weight`.
  - Nothing checks that a source says what the node states. The skill tells agents to leave an
    identifier or place out rather than guess it.
  - `status(view="sources")` is the reference list, and `status(view="axioms")` shows each
    axiom's references. The graph snapshot lists a node's references in its inspector, linked
    where a doi, arXiv id or web url gives an address.
  - `DANGLING_REFERENCE`, `UNREFERENCED_SOURCE`, `UNTITLED_SOURCE` and `MALFORMED_REFERENCE` are
    advisory.
  - embodied_ai's prose citations (ten nodes, eighteen sources) were moved over in its `d886f71`.
- **`status(view="tree", subject=<id>)` draws one node's lineage** (reported from embodied_ai).
  - It shows what the node rests on and what rests on it, or the same for each branch of a
    component.
  - On 157 branches the whole tree is 88.7 KB. The harness saves a reply that long to a file,
    and the verifier, which has no Read tool, could not report the state it left. The deepest VLA
    branch's lineage is 4.6 KB.
  - `status` now names any parameter the view it was given does not read. Before, `subject=` on
    `tree` was dropped in silence.
  - The verifier's protocol ends with each `verify_step` reply's state and, for a lineage, the
    subject tree.

## 0.7.6 — 2026-10-07 · status views in seconds, and the cited-measurement report sorted

Reported from embodied_ai on 0.7.5.

- **`status(view="coverage")` and `status(view="goals")` took over 120 seconds there.** Profiling
  disproved the report's guesses: the DAG rebuild, claim pins and the 3,617-slice contract were all
  cheap. The cost was staleness.
  - **Every trial was judged on its own.** Each one matched every claimed `code:` entry against
    every tracked file, about 25 million `fnmatch` calls on this repository. On Windows each of
    those also paid `normcase` twice.
  - **The fixes.** A run's trials share a stamp, so a run is now judged once. The files a set of
    entries claims at HEAD are matched once. `normcase` is remembered, so a glob reads exactly as
    `fnmatch` reads it.
  - **The revision fallback** for trials from before stamps diffed the ledger directories with
    rename detection on. It no longer does.
  - **The result here:** coverage went from 42.5 s to 3.8 s, goals to 3.1 s. Every slice's state,
    count and stale reason is identical: 21 slices, 3,196 stale trials and 154 reasons compared
    before and after.
- **Contracts no branch cites are sorted by what they measure:** a component's first, then an
  interface's, then a goal's measure, which the goal's outcome already explains. One with no
  evidence is marked `(no evidence yet)` rather than listed as measured. There, 27 had sat in one
  list, goal measures and unmeasured contracts among them.
- **graph-snapshot shows the cited measurements.**
  - Each branch's "Cites the measures" gives each contract's review state.
  - The Issues tab lists unreviewed cited measurements in their own group, and every contract no
    design cites, marked by what it measures.
  - The review state is judged from the declarations at the snapshot's commit, so the snapshot
    still reads no evidence. `DEF-snapshot` was restated to say so (`355b0ee`), and
    `BRN-snapshot-shows-one-revision` was re-proven against it.

## 0.7.5 — 2026-10-06 · a cited measurement is reviewed only while its claim stands

- **A citation can carry a pin.** A branch cites the contract that measures it, and nothing held
  the two together. A branch restated to claim more kept citing the contract that measured the old
  claim. That contract read supported, so once the branch was re-proven the release gate passed,
  and no one was asked whether the contract still measured the claim.
  - **The pin.** Write `evidence: CTR-x@<pin>`, where the pin is the branch's claim digest (the
    one a code link's claim pin records) at the moment the contract's rule and tests were read
    against the claim.
  - **What breaks it.** Restating the branch, or anything it rests on, leaves the citation
    unreviewed. The coverage view prints the pin to write, `audit_change` lists the citations a
    restatement will leave unreviewed, and `stamp-monitor audit` warns `MEASUREMENT_NOT_REVIEWED`.
  - **What it costs.** A pin lives in the derivation rule, so writing one restates nothing and
    sets no trial aside.
  - It is reported, not gated: `decide` is unchanged.
- **A contract no branch cites is listed** as "measured, cited by no design" in the coverage view,
  and as `UNCITED_CONTRACT` in `audit`. Here that is the four interface contracts and the four
  goal measures, the same subjects the snapshot lists with no design claim.
- Design first: `AXM-cited-measurements-reviewed`, `DEF-cited-measurement` and
  `BRN-cited-measurements-reviewed-while-the-claim-stands` (`87a7e8a`). "Cited measurement", not
  "citation", because `DEF-premise-graph` already calls a premise a citation.
- Two suggestions from an agent adopting the harness, taken together. They are the two
  directions of one join.

## 0.7.4 — 2026-10-06 · tests in parallel, and "aligned" never read as "works"

- **`run_test` calls made together run at once.** By default, half the cores run at once;
  `BELIEF_MAX_RUNS` sets the number. Until now one lock covered the whole run. Only three things
  need to be one at a time, and only those are now:
  - taking a run id: the run makes its artifact directory with `exist_ok=False`, so two runs never
    share an id, even from two server processes;
  - appending to the ledger, with its evidence ids;
  - installing the read hook, which is written atomically and only when it changed, so a run
    starting mid-write cannot import half a hook and record no reads.

  The digest cache is replaced whole rather than written in place. Two concurrent runs are shown
  to overlap: each waits for the other to start. The suites here use 22 cores.
- **Each link shows the measurement its claim cites:** `evidence: CTR-x [stale]` beside every link
  in `stamp-monitor links`. "Aligned" says code was read against a claim; whether it still works
  is the contract's to say. Two observations follow:
  - `LINKED_EVIDENCE_NOT_SUPPORTED`: a claim whose regions read aligned while its cited evidence
    is not supported.
  - `UNSCOPED_ENVIRONMENT`: a test behind linked code that names no lockfile, so upgrading a
    dependency under unchanged code stales nothing.
- **This repository's suites now read `uv.lock`**, so a dependency bump stales their evidence.
  The acceptance suites' `reads:` are in `goals.yaml`, which is the human's to change.

## 0.7.3 — 2026-10-06 · code links, verified and usable at scale

- **`links(subject=...)` works on the cases an adopting agent hit.** These were reported from
  embodied_ai on 0.7.2 (`dccf26c`).
  - **A scanned file with no region** read as "not a scanned path". It now prints `0 region(s)`
    and its diagnostics.
  - **A region only in the working tree** could not be found by its id. A subject (region id,
    claim, or path) now narrows the uncommitted section too, and that section prints the pins to
    write.
  - **The full report outgrew one tool response** on a large project: 121 KB of 353 untracked
    mentions and 143 unlinked branches, with the pins printed last. The uncommitted section now
    comes first. Past 40 lines, the rest of a severity are counted per file instead of listed.
- **An unpinned `motivated-by` reads `explanatory`, never `aligned`** (`91946d5`). It asserts no
  correspondence, so it is not a code link.
- **The code-links theory was verified.** The verifier refuted the first wording of
  `BRN-links-stale-when-either-side-moves` (TRL-0307..0309). Its claim-pin clause named an event
  where it should have compared states, and it had four entailment gaps. The branch, its axiom
  and its two definitions were restated (`70f9497`) and proven (TRL-0310..0312).
- **`DEF-snapshot` says what a snapshot shows of code links** (`455a196`): each node's regions
  with their link state, and the scan's broken tags and unaligned links.
  `BRN-snapshot-shows-one-revision` was re-verified against it.
- `code_links`' own docstrings named example ids that resolve to nothing, and its own scan
  reported them. They are placeholders now (`da35623`).

## 0.7.2 — 2026-10-06 · code linked to the claims it realizes

- **Tagged code regions** (`code_links`, a library the servers share, not a fifth server).
  - `# tdlp:begin CODE-<name>` / `# tdlp:implements BRN-<id>` / `# tdlp:end CODE-<name>` mark
    a region and the node it realizes (also `uses`, `checks`, `motivated-by`). Targets may be
    branches, lemmas, definitions or axioms.
  - Each tag carries pins. The body pin is set by the code tokens; comments and layout do not
    move it. The claim pin is set by the claim's fingerprint and everything upstream, which is
    what a trial binds to.
  - A link whose pins no longer match is reported at every revision until it is re-read and
    re-pinned, with the revision to diff against or the nodes restated since.
  - Ids named in comments and docstrings are checked: one that names nothing is an error, and
    one no region tracks is listed.
- **stamp-monitor gets `links`**, its fourth tool, plus `stamp-monitor links [--strict]`.
  `audit` reports broken and stale links as warnings, never blocks. `impact` lists what the range
  did to tagged regions beside the chain, never on it. consistency-belief gets no view: the
  verifier holds `status`. `audit_change` names, by id only, the regions a restatement unpins.
- **graph-snapshot lists each claim's regions** with their link state at the snapshot's commit,
  and broken or stale links in its Issues tab. Regions are never nodes or edges.
- **Tag and pin in one commit.** `stamp-monitor links` prints the pins an uncommitted region
  would need, so an untagged region goes to aligned in a single reviewed commit.
- **The servers no longer time out after an update.** On 0.7.0 three of the four failed with
  `CONNECT_TIMEOUT`. The first start at a new tag clones, builds and installs, which took 50 to 100
  seconds here, against Claude Code's 30-second connect limit; graph-snapshot connected only on a
  retry, once the build had finished. A plugin cannot raise the limit, so this project sets
  `MCP_TIMEOUT` to 120 seconds in `.claude/settings.json`, and the quick start says to do the
  same.
- **Fixed, from a review of the harness:**
  - **Compatibility groups.** A refuted compatibility group in a bucket no longer hides behind a
    supported one: the policy read one state per bucket, and the last slice overwrote the rest.
  - **Unknown policy id.** consistency-belief `decide` refuses a policy id it does not declare,
    instead of deciding under the first one.
  - **Goals policy.** It is no longer approved by the human's commit when it reads something the
    agent declares: a prior on a goal measure, or `mandatory:` flags through `safety_gates`.
  - **Goal guard and record.** A file renamed out of a goal test's directory is refused by the
    guard and found by the record.
  - **Malformed entries.** One stray entry in `belief.yaml`, `goals.yaml` or `consistency.yaml`
    (a bare id, a mapping with no id, a string criterion) is reported as `MALFORMED`. It no
    longer raises in every tool.
  - **Design-ledger audit.** `audit` checks `.consistency/` for duplicate trial ids and for
    amendments and decisions citing trials that do not exist.
  - **Policy ids in both files.** `impact` keeps what each ledger's policy gates when
    `belief.yaml` and `consistency.yaml` declare the same policy id.
  - **Unstamped evidence.** It reads a `code:` directory as a directory.
  - **Test version check.** A changed test stales its evidence even when no staleness reader is
    passed.

## 0.7.0 — 2026-10-06 · the whole design, drawn at one revision

- **graph-snapshot, a fourth server** (`5878314`), with one tool, `snapshot(focus)`. It joins
  `consistency.yaml`, `belief.yaml` and `goals.yaml` at one commit, with the proof state
  consistency-belief computes for each lemma and branch, and writes one self-contained page
  (`.graph-snapshot/snapshot.html`). The page has:
  - an index of components, claims worst first, foundations and issues;
  - the selected node's lineage, drawn left to right as "rests on";
  - an inspector with the full claim, why it is in its state, and its proof tree down to axioms
    and definitions.

  The same file opens in a browser or publishes as an Artifact. Design:
  [`docs/graph_snapshot_mcp_design.md`](docs/graph_snapshot_mcp_design.md).
- **It reads no evidence, so it is fast.** It takes 1.2 s on embodied_ai's 310-node graph.
  Contracts appear by name only. A first prototype that also read contract states took 12½ minutes
  there; see [Measured cost](docs/graph_snapshot_mcp_design.md#measured-cost) for the
  component-belief cost behind that.
- **One revision.** Both declaration loaders and `Context.build` take a `revision`, `HEAD` by
  default, so the servers are unchanged. A snapshot resolves HEAD once and reads every file at
  that sha. During the prototype's slow run, embodied_ai's HEAD moved mid-read, which is what
  showed this was needed.
- **Issues and gaps.** The page lists the issues both loaders and the premise-graph build already
  report, under their own codes. It also lists the gaps only the join shows: an axiom naming no
  goal, a goal no axiom names, code with no declared design, an interface or goal no branch
  governs, and an axiom or definition nothing rests on. In embodied_ai none of the 82 axioms names
  a goal.
- **The theory came first.** `DEF-snapshot` and `BRN-snapshot-shows-one-revision` were committed
  (`321906d`) before the code, as a new definition rather than a widened `DEF-report`, so nothing
  already proven went stale. The first verifier pass refuted the branch: the definition limited
  which declarations a snapshot shows but not which proposals. Both were restated (`745b545`)
  before the code was committed, and a second pass proved the branch with no gaps (17 of 17
  claims proven). That proof rests on one actor's judgement, so treat it as provisional.
- **Your goal set.** `acceptance/test_any_project.py` expects three servers, so
  `CTR-runs-in-any-project` reads refuted until you decide whether a fourth belongs there. The
  agent proposed the one-line change in a note on `GOL-any-project` and did not make it.

## 0.6.2 — 2026-10-03 · the marketplace has its own name

- **The marketplace is `davechendatascience-marketplace`** (`956a80e`). It was named `tdlp`, the
  same as the plugin, so the install read `tdlp@tdlp`. It now reads
  `tdlp@davechendatascience-marketplace`. To move a project that installed `tdlp@tdlp`, follow
  [Moving a project that installed `tdlp@tdlp`](docs/guide.md#moving-a-project-that-installed-tdlptdlp)
  (`037ebe9`). The servers, skills and verifier have not changed since 0.6.1.
- `uv.lock` now records the package's version. It read 0.1.0 through 0.6.1.

## 0.6.1 — 2026-10-01 · the audit sees what was set aside

- **An audit finding on evidence nothing counts any more stops blocking.** The remedy for an
  artifact that cannot be audited is to set its records aside with `amend`. The audit read raw
  trials and never folded amendments, so it went on blocking after every record was quarantined.
  A missing or mismatched artifact, or an untrusted stamp, now blocks while any record resting on
  it still counts. Once none does, it is reported as information naming the amendment's reason;
  it is never dropped. An unhashed import whose records are all set aside moves from a warning to
  one information line. In embodied_ai: four blocks became information, and 157 warnings became
  112 plus one line for 45 runs set aside.
- The design came first: `AXM-damage-blocks-while-it-counts`, `DEF-set-aside` (which states what
  the model already did -- a set-aside record moves no belief) and `BRN-audit-blocks-what-counts`.

## 0.6.0 — 2026-10-01 · every stage of the V has a home

- **Row 9 of the systems-engineering mapping.**
  - A design claim may govern an interface (`subject: IFC-...`, from `belief.yaml` or
    `goals.yaml`) or a goal, as well as a component.
  - An axiom names the goal whose requirement it states (`goal:`). `goal:` is not part of the
    fingerprint, so tracing an axiom restates nothing.
  - `status(view="coverage")` lists interfaces and goals with and without a design claim, and
    traces each goal to its axioms.
  - A failure mode names the contract and the case that observe it (`observed_by:`, `case:`).
    `status(view="graph")` lists those nothing observes and checks each named case passed in its
    latest trial.
- **A trial made before fingerprints is judged by the build it was made against.** Until now it
  stayed current through any restatement upstream, which `AXM-blast-radius-invalidation` forbids.
  It now counts as having recorded the fingerprints its nodes had then: `consistency.yaml` at the
  last commit before it, plus the proposals staged by then. In a project with such trials (three
  on this machine hold 104), a node whose premises were restated since goes STALE and needs
  re-verifying.
- **The configuration audit stops reporting present artifacts.** A run recorded on Windows wrote
  its artifact path with backslashes and hashed CRLF bytes, which git stores, and Linux checks
  out, as LF. 43 artifacts here read as missing, then as tampered. Both separators and both
  line-ending directions now audit as what they are, and the runner records POSIX paths.
- **A long `run_test` stays alive.** A stdio tool call that sends nothing for 30 minutes is
  aborted by the client's idle timeout, and the server sent nothing while a test ran. The test
  now runs in a worker thread, and the tool reports progress every minute: a progress
  notification when the client sent a progress token, and a log message either way. Runs are
  still one at a time (until 0.7.4). How long a test may run is its own `timeout_s` (default 900 seconds),
  declared with the test.
- **Evidence from an earlier version of its test is stale** (design rule 3.5). A test's version
  is its run line and metrics. It was recorded on every trial and read by nothing, so a changed
  run line pooled old and new procedures, and a gate read its latest run whatever the version.
  An edit that left the procedure the same is mapped explicitly with `same_as: [<version>]` on the
  test. An import that names only the test id records the declared version.
- **A value cut at an unquoted comma is reported (`SPLIT_VALUE`).** `{id: FM-x, observable: a, b}`
  reads as "a" plus a stray key. Four failure modes and three component notes here had been cut
  that way.
- **The design graph was re-verified until it held.** Eight verifier passes, each judged from the
  served probes alone, found:
  - one stale doubt (`LMA-blast-radius-propagation`);
  - two refuted new designs (the goal guard and the plugin);
  - claims wider than their premises;
  - "when" where "exactly when" was meant;
  - three places where the theory and the code disagreed. `AXM-no-belief-write-path` is now
    scoped to the declarations in effect. `BRN-runner-captures` says the runner takes `passed`
    from the exit code. `DEF-belief-eligible` agrees with that.

  Each fix was audited before it was committed. The code commit followed the declarations.
- This repository applies all of it to itself:
  - an integration test for each of its four component interfaces;
  - every failure mode traced to the case that catches it, with five new tests where none did;
  - every axiom traced to a goal;
  - design claims for the goal guard, the plugin and the goal interface.

## 0.5.2 — 2026-10-01 · what an adopting agent tripped on

- **`run_test` no longer crashes on a directory at `$OUT`.** It hashed `$OUT` as a file, so a
  measure in several parts that made it a directory recorded nothing. Each way `$OUT` can be
  wrong falls back to one trial built from the exit code, and the reply names which it was:
  absent, a directory, not JSON, or a shape it does not accept.
- **The goals view names a guard from an earlier release.** Upgrading the plugin leaves the
  commit-msg hook on the release that installed it, and the view said "installed" either way.
  Running the install command again replaces it; `--force` is only for a hook that is not the
  guard.
- **`audit_change` says whether anything restates.** A trial vouches for a node's statement and
  premises, not its derivation rule. Given the proposal, the audit says whether the node's own
  trials are kept and whether its dependents go stale. Without one, it says what a restatement
  would cost, and that a change only to a citation costs nothing.
- **`ingest` says why it refuses an artifact:** a URL, a missing path, a directory, or several
  paths in one string. It has refused all four since 0.2.0, but only as "not a file".
- **Skills.**
  - component-belief has a new section, *Declaring contracts and tests*: what clears a target,
    gates, compatibility keys, the `$OUT` format, what evidence is bound to, and keeping the
    read hook through a wrapper script.
  - adopt-goals adds what shapes a draft: a goal reads its worst slice, and which files become
    the human's.
  - consistency-belief: re-citing a contract restates nothing.
- The staleness docs no longer say that a file the run opened makes its evidence stale. The stamp
  records it, but nothing watches it.

## 0.5.1 — 2026-10-01 · the artifacts view reads a run line the way staleness does

- **`status(view="artifacts")`** looked for a run line's files only under the top-level
  directories some component's `code:` mentions. Staleness matches every token against every
  tracked file. So a script elsewhere, such as `bash acceptance/replay_labels.sh $OUT`, carried
  live evidence while the view gave it no `named`, `invoked` or `supports` stamp. Bash runs it, so
  the read hook never saw it opened either, and the view listed it as a prune candidate. Both now
  use one extractor, `named_paths`, so they cannot disagree.
- A run line that starts `cd dir && …` names everything under `dir`. Staleness always read it
  that way; the view now keeps those files too.

## 0.5.0 — 2026-10-01 · setting up goals in any project that uses TDLP

- **`/tdlp:adopt-goals`**, a plugin skill, walks the agent through putting goals into a project
  that already uses the harness. It drafts, checks and installs the guard; the human commits;
  then the agent cleans up. Only the human's commit waits on the human.
- **The goals view**, with no goals in effect, lists the candidate measures: contracts an
  end-to-end test already measures. It also checks a `goals.yaml` in the working tree as a draft
  and puts nothing in effect, so the agent can validate what it will hand over without
  committing it.
- **A measure promoted** from `belief.yaml` into `goals.yaml`, with its id and test, is shown to
  keep its evidence ids and state before, during and after the move, with no re-run.
- **This repository adopted its own goals** (`680e5da`, committed by the human): honest evidence,
  sound designs, goals that stay the human's, and running in any project, plus the interface
  from evidence to designs. Each is measured by the acceptance suite in `acceptance/`.

## 0.4.0 — 2026-10-01 · evidence on files git does not track

- A declared input git ignores is stamped by its content digest and judged against the file on
  disk. This covers a checkpoint, a dataset or a directory of demonstrations, whether in `reads:`
  or named as a file on the run line. Retrain the checkpoint and its evidence goes stale; restore
  the same bytes and it counts again; delete it and the reason says so. Before, a gitignored
  checkpoint never entered the stamp, so retraining it staled nothing, and an untracked dataset
  left its evidence stale forever.
- A file git neither tracks nor ignores stays stale until it is committed or ignored, and the
  reason now says exactly that instead of calling it an uncommitted edit.
- Digests are cached by size and modification time, so a large file is hashed once per change.

## 0.3.0 — 2026-10-01 · goals the human owns

- **`goals.yaml`** (`746dc2a`) holds the goals, the interfaces between them, and the contracts,
  tests and policy that measure them. Only the human commits it. The agent owns `belief.yaml` and
  `consistency.yaml` and commits them as it works. A component names the goal it serves, so a
  goal's evidence goes stale with that code.
- **The guard, `tdlp-guard install`,** is a commit-msg hook. It refuses a commit that carries the
  agent's trailer and changes the goal set.
- **`status(view="goals")`** is the one view to check in with. `note(subject="GOL-…")` is how the
  agent proposes a goal change.
- **`decide`** records an adoption under the goals policy without an approver, since the human's
  commit approved it. That holds until the agent touches the goal set; `workflow` reports any
  such commit.
- **`impact`** now reaches a contract through every component its subject rests on. Goals and
  interfaces were missed before.
- The PYTHONPATH read-hook test runs end to end only where `env` exists (`6491778`). The last
  hand-registered servers gave way to the plugin (`3bc2f68`).

## 0.2.0 — 2026-09-30 · one plugin, and imports that hold to their definition

- **`ingest`** (`b2cabd2`) requires a test the contract lists and a local artifact, which it copies
  and hashes itself, and `audit` checks imported artifacts. Before, one call naming a made-up test
  and a missing file could turn a gate supported and let `decide` record an adoption, with `audit`
  and `workflow` both clean.
- **The plugin `tdlp`** (`d733b29`) ships the three servers, both skills and the verifier as one
  Claude Code plugin. The servers install with `uvx` from a release tag and read the project
  Claude Code reports. A declared test runs in the project's environment, not the plugin's.
  `UV_LINK_MODE=copy` avoids broken installs under OneDrive.
- `a3812c2` enables the plugin for this project and adds the migration steps for a project that
  registered the servers by hand.

## 0.1.0 — 2026-08-31 to 2026-09-23 · three ledgers, applied to themselves

- **component-belief** (`edf8945`, 2026-08-31) holds evidence-grounded belief per contract slice.
  Beta-Binomial rates keep "insufficient" as an answer, and diagnosis comes before optimising.
  Its first self-hosted run is `41f48ee`.
- **consistency-belief** (`bbdacd5`, 2026-09-21) builds axioms → lemmas → branches, verified by
  falsification probes. Staged proposals persist and trials bind to the statement they verified
  (`243250b`), and only a falsified probe refutes (`627dde7`).
- **The join** (2026-09-23): a branch names the component it governs (`41fd0b1`) and the contract
  that measures it (`1677af7`), and `POL-consistency-gate` needs both. The verifier reasons from
  declarations only (`c3dbae9`), is served its probe, and has independence counted (`3782055`).
  It runs in a context that cannot open a file (`81c35fb`).
- **Evidence and its currency**: gate contracts read their latest run (`6822fc9`); a run records
  what it opened (`5e16d92`) and every file carries a stamp (`e138229`). Evidence is bound to the
  content it measured, not the revision (`105e434`).
- **stamp-monitor** (`2a3dea5`) is a read-only view across both ledgers: impact, audit, workflow.
- **Self-application**: both ledgers declare this repository (`81c35fb`). Eight verifier passes
  narrowed the design to convergence (`d54e2a5` to `cd0dbd6`), and the identity model was stated
  once (`f2f9fab` to `a69b43e`).

## damped-plan — 2026-08-17 to 2026-08-31 · the predecessor, retired

This was a planning MCP (`6d8cb13`) whose own version numbers are unrelated to the ones above.

- It had a PreToolUse gate hook, an allowlisted command runner with evidence capture (`96ffa28`)
  and a plan-reviewer agent.
- It had a predictive layer of contracts, posterior checks and the dominant residual (`1c9303d`),
  and a research loop with a human-supervised gate (`cda5b4e`).
- It recorded its own gaps, among them "the missing human-only ultimate goal" (`5cdfb8b`,
  2026-08-21), which `goals.yaml` answers in 0.3.0.
- Retired (`3deaca3`) on 2026-08-31, the day component-belief (`edf8945`) replaced it.
