# Theoretically Driven LLM Planning

A dual-MCP epistemic architecture for rigorous software architecture, system planning, and capability verification.

```
                         THEORETICALLY DRIVEN LLM PLANNING
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
     consistency-belief (Deductive)                  component-belief (Empirical)
  • Grounded in: Declared Axioms                  • Grounded in: Executable Test Trials
  • Representation: Deductive Proof DAG           • Representation: Component System Graph
  • Verification: LLM Falsification Probes        • Verification: Mechanical Test Execution
    (counterexample search, gap detection)          (exit codes, captured artifacts, hashes)
  • Model: Lean-style Proof Obligations           • Model: Beta-Binomial Credible Intervals
  • Storage: .consistency/ (append-only)          • Storage: .belief/ (append-only)
```

## The Commitment

An LLM agent is the primary caller, and an agent is a fluent producer of *plausible* numbers and assertions. Therefore, **in both MCPs, the agent has no write path to a belief**:
* In `component-belief`, there is no `set_belief`. Beliefs are a pure function of `(belief-eligible evidence, declared priors, model version)`.
* In `consistency-belief`, there is no `set_consistent`. Consistency is a pure function of `(axiomatic reachability, topological acyclicity, falsification probe outcomes)`.

This discipline is enforced by **missing tools**, not prompt instructions.

| Channel | Tool | Epistemic Weight |
|---|---|---|
| Server ran a declared test | `component_belief.run_test` | Measured empirical evidence (artifact + hash captured) |
| Server ran a falsification probe | `consistency_belief.verify_step` | Deductive verification trial (counterexample / entailment probe) |
| External import | `component_belief.ingest` | Imported evidence (requires source + artifact) |
| Agent or human statement | `note` (both servers) | **Zero weight** — recorded as `provenance=asserted` (testimony) |

---

## 1. `consistency-belief`: Deductive Proof Consistency (Lean-Style)

Design rules in [`docs/consistency_belief_mcp_design_rules.md`](docs/consistency_belief_mcp_design_rules.md).
Declarations in [`consistency.yaml`](consistency.yaml).

Axiom-to-branch design consistency for architectures, specifications, and planning:
* **Axiomatic Grounding**: Components, contracts, and design mutations must trace transitively back to declared root axioms (`AXM-...`). Ungrounded nodes are flagged as `UNGROUNDED`.
* **Mechanical DAG Kernel**: Enforces strict acyclicity before any semantic reasoning. Circular dependencies ($A \implies B \implies A$) are rejected immediately with cycle traces.
* **Open Proof Obligations (`sorry`)**: Any derived lemma or contract with fewer than $n_{\min}$ verification trials is surfaced as an open `OBLIGATION`.
* **Topological Blast Radii**: Modifying an upstream axiom or lemma invalidates all downstream dependents, marking them `STALE` until re-verified.
* **Trials Are Bound to What They Verified**: Every trial records a fingerprint of its target's statement and premises and of every premise upstream. Restating a node sets its earlier trials aside (they are reported, not counted); restating anything upstream marks the node `STALE` until it is re-verified. A revised claim keeps its id instead of needing a new one to escape old verdicts.
* **Staged Proposals**: `propose_branch` stages a branch in the ledger. It persists across calls, `verify_step` can target it and later proposals can cite it as a premise at once, and it shows as `· STAGED` in every view. It supports `decide()` only once the same id is declared in `consistency.yaml` at git HEAD; trials recorded while staged carry over if the declared statement is the same.
* **LLM Measurement via Falsification Probes**: The LLM measures consistency through adversarial probes (`verify_step`), searching for concrete counterexamples or unstated assumptions rather than merely affirming belief.
* **Only a Counterexample Refutes**: A probe with outcome `falsified` makes a node `REFUTED`. A `gap` -- a missing premise, an unproven step -- leaves it unproven: it counts against consensus (so the node reads `DOUBTED` once it has enough trials) and is listed under *Entailment Gaps* in `status(view="contradictions")`, whatever evidence text it carries.

### The Loop
```
status(view="obligations")  →  verify_step(...)  →  status(view="tree")
```

### The Seven Tools
* `status`: 7 views (`tree`, `branches`, `axioms`, `obligations`, `contradictions`, `audit`, `cycle`).
* `propose_branch`: Stages new contracts or lemmas (declared or staged premises); validates acyclicity and premise validity; re-proposing a staged id restates it.
* `verify_step`: Records falsifiable verification trials (counterexample search, entailment, negation), each bound to the statement it verified. A trial establishes entailment **from the declarations alone** — a verifier reads the axioms, definitions, premises and claims, never the implementation, and never runs it. A clause that cannot be judged without opening the code is a gap: the claim leans on a fact it does not cite. Implementation fidelity and measurement are the implementer's duty and belong in component-belief, cited here by id.
* `amend`: Reclassifies a mis-recorded trial (`invalid`, `quarantined`, `superseded`) by appending an amendment; the original record and the reason stay in the ledger.
* `audit_change`: Calculates topological blast radius of modifying axioms or lemmas.
* `note`: Qualitative annotation (inert channel, zero proof weight).
* `decide`: Evaluates consistency policy; enforces human approval for `ADOPT`.

```
AXM-damage-nonneg [AXIOM]
└── LMA-combat-health-monotonicity [PROVEN 2/2]
    └── BRN-combat-resolver [PROVEN 2/2]

basis: verification_trials×14 set=a1b1f9 · proven=7 obligations=0 refuted=0
```

---

## 2. `component-belief`: Empirical Evidence Grounding

Design rules in [`docs/component_belief_mcp_design_rules.md`](docs/component_belief_mcp_design_rules.md),
design in [`docs/component_belief_mcp_design.md`](docs/component_belief_mcp_design.md).
Declarations in [`belief.yaml`](belief.yaml).

Evidence-grounded belief state for a system modeled as components and interfaces:
* **Declared Contracts**: Slices defined per component/interface, operating condition, and compatibility key.
* **Trial-Level Granularity**: Stores individual trials from pytest or telemetry into `.belief/`.
* **Beta-Binomial Statistics**: Computes uncertainty intervals; rejects premature verdicts on sparse data (`insufficient_evidence`).
* **Regressions & Bottlenecks**: Surfaces regressions and ranks bottlenecks by decision relevance without blaming unobserved components.

### The Loop
```
status(view="diagnose")  →  run_test(...)  →  status(view="belief")
```

### The Six Tools
* `status`: 7 views (`graph`, `coverage`, `belief`, `diagnose`, `plan`, `cycle`, `trace`).
* `run_test`: Executes declared test commands, captures artifacts, extracts trials.
* `ingest`: Imports external evidence with provenance.
* `amend`: Corrects or invalidates trials without destructive mutations.
* `note`: Qualitative annotation (inert channel).
* `decide`: Evaluates policy against observed evidence; requires human approver for `ADOPT`/`ROLLBACK`.

```
CTR-grasp-reachable [normal, model_revision=v3] supported 0.91 [0.84,0.96] n=34
CTR-grasp-reachable [low, model_revision=v3] insufficient n=3 (need 5 more)
basis: evidence×37 set=a3f9c1 · model bb-1 · prior none
next: run_test TST-grasp-ik conditions={low}  # closes the thin slice
```

---

## Declarations Live in Git, Not in Tools

Declarations (`consistency.yaml` and `belief.yaml`) load from **git HEAD, not the working tree**:
* Editing a declaration file changes nothing until a human commits it.
* Uncommitted edits show as `PENDING` in status.
* Neither a threshold change nor a weakened axiom in the working tree can flip a verdict without a human git commit.
* A staged proposal (consistency-belief) is reviewable before that commit -- it can be verified and cited -- but it cannot support a decision until it is declared and committed.

> Caveat: This is exactly as strong as your commit discipline. If agents can commit unattended, add CODEOWNERS on `consistency.yaml` and `belief.yaml` or require signed commits.

---

## Install & Register

```bash
pip install -e .
```

Register both servers with Claude Code or Antigravity via `.mcp.json`:

```json
{
  "mcpServers": {
    "consistency-belief": {
      "command": "uv",
      "args": [
        "--directory", "/home/edge-host/Documents/GitHub/Theoretically_Driven_LLM_Planning",
        "run", "consistency-belief-mcp"
      ],
      "env": {
        "CONSISTENCY_PROJECT_ROOT": "/home/edge-host/Documents/GitHub/Theoretically_Driven_LLM_Planning",
        "CONSISTENCY_ACTOR": "agent"
      }
    },
    "component-belief": {
      "command": "uv",
      "args": [
        "--directory", "/home/edge-host/Documents/GitHub/Theoretically_Driven_LLM_Planning",
        "run", "component-belief-mcp"
      ],
      "env": {
        "BELIEF_PROJECT_ROOT": "/home/edge-host/Documents/GitHub/Theoretically_Driven_LLM_Planning",
        "BELIEF_ACTOR": "agent"
      }
    }
  }
}
```

Or run directly:
```bash
PYTHONPATH=src python -m consistency_belief.server
PYTHONPATH=src python -m component_belief.server
```

---

## Layout

```
consistency.yaml                                       # Axioms, definitions, lemmas, contracts (applied to itself)
belief.yaml                                            # Components, interfaces, contracts, tests (applied to itself)
docs/
  consistency_belief_mcp_design_rules.md               # 8 design rules for deductive consistency
  component_belief_mcp_design_rules.md                 # 11 design rules for empirical belief
  component_belief_mcp_design.md                       # Empirical model & architecture specification
src/
  consistency_belief/                                  # Deductive MCP server
    declarations.py                                    # Git-HEAD loader and schema validator
    graph.py                                           # Proof DAG kernel (acyclicity, grounding, blast radius)
    model.py                                           # Verification state (PROVEN, REFUTED, OBLIGATION, STALE)
    probes.py                                          # LLM verification probe generators & parsers
    decide.py                                          # Consistency policy evaluation & human approval gate
    render.py / views.py                               # ASCII proof tree and status views
    server.py                                          # FastMCP server (6 tools)
    store.py                                           # Append-only JSONL ledger in .consistency/
  component_belief/                                    # Empirical MCP server
    declarations.py                                    # Git-HEAD loader and validation
    model.py                                           # Beta-Binomial belief slices
    diagnose.py                                        # Bottleneck ranking & discriminating tests
    decide.py                                          # Policy evaluation & human approval gate
    planning.py                                        # Round test selection
    runner.py                                          # Test execution and artifact capture
    views.py / render.py                               # Empirical status views
    server.py                                          # FastMCP server (6 tools)
    store.py                                           # Append-only JSONL ledger in .belief/
tools/pytest_trials.py                                 # pytest -> trials JSON adapter
tests/                                                 # 109 test cases asserting all epistemic invariants
```

---

## Tests

```bash
PYTHONPATH=src python -m pytest tests -q
# 109 passed in 1.73s
```

The test suite asserts the core epistemic invariants across both systems:
1. Asserted notes cannot move posteriors or close proof obligations.
2. Uncommitted threshold or axiom edits cannot alter verdicts.
3. Mechanical DAG checking detects and rejects circular dependencies.
4. Upstream mutations trigger exact topological blast radius invalidation.
5. Falsification probes capturing counterexamples immediately transition claims to `REFUTED`.
6. Final adoption decisions refuse to self-approve without a human approver.
