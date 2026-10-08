"""Code links: tagged regions stay aligned with the claims they name, or say why not.

What is asserted is the alignment contract, not the parser: a link reads aligned only while the
code its body pin recorded and the claim its relation pin recorded are both still there; every
other link, and every mention of an id that names nothing, is reported at every revision until
someone deals with it; and none of it moves a proof state or reaches the verifier.
"""
# tdlp:foreign-ids the projects these tests build declare their own nodes and regions

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import BASE_YAML, git
from code_links import (ALIGNED, BODY_CHANGED, CLAIM_RESTATED, ERROR, OBSERVATION, REVIEW, REVIEW_FAILED,
                        UNKNOWN_CLAIM, UNREVIEWED, build_index, compare_indexes, display, link_state,
                        parse_python, resolve_revision, scan_worktree)
from code_links.impact import ADDED, BODY, MOVED, RELATIONS, REMOVED, RENAMED, REPINNED
from code_links.parser import code_tokens
from consistency_belief.links import claim_refs, scan

DESIGN = """
axioms:
  - id: AXM-bound
    domain: control
    statement: The arm's acceleration is bounded.
    rationale: The motors saturate.
definitions:
  - id: DEF-cap
    term: Cap
    meaning: A vector scaled down to at most a given norm, never up.
lemmas:
  - id: LMA-scaling
    statement: Capping a vector preserves its direction.
    premises: [DEF-cap]
    derivation_rule: Scaling by a positive factor preserves direction.
branches:
  - id: BRN-servo
    subject: CMP-grasp
    claim_type: contract
    statement: Each servo step changes the commanded velocity by at most the bound times dt.
    premises: [AXM-bound, LMA-scaling]
    derivation_rule: "The step is capped. evidence: CTR-grasp-reachable"
  - id: BRN-idle
    subject: CMP-grasp
    claim_type: contract
    statement: An idle arm commands no motion.
    premises: [AXM-bound]
    derivation_rule: "Nothing moves. evidence: CTR-grasp-reachable"
"""

SERVO = """\
def step(requested, previous, cap, dt):
    # tdlp:begin CODE-servo-cap{body}
    # tdlp:implements BRN-servo{brn}
    # tdlp:uses LMA-scaling{lma}
    delta = requested - previous
    delta = min(delta, cap * dt)
    return previous + delta
    # tdlp:end CODE-servo-cap
"""

CLAIMED = BASE_YAML.replace(
    "    remediation: Retune approach sampling\n",
    "    remediation: Retune approach sampling\n    code: [servo.py, idle.py]\n")


def commit(root: Path, files: dict[str, str], message: str = "change") -> str:
    for name, text in files.items():
        path = root / name
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return resolve_revision(root, "HEAD")


def servo(body: str = "", brn: str = "", lma: str = "") -> str:
    return SERVO.format(body=f"@{body}" if body else "", brn=f"@{brn}" if brn else "",
                        lma=f"@{lma}" if lma else "")


def codes(index, severity=None) -> list[str]:
    return sorted(d.code for d in index.diagnostics if severity is None or d.severity == severity)


def pinned(index) -> str:
    """The servo file with its header pinned as reviews were written before they were ledger
    records: the body under grammar 1, and each claim's digest under the earlier rule (DEF-review)."""
    block, claims = index.get_block("CODE-servo-cap"), index.claims
    return servo(body=block.legacy_body_pin, brn=claims["BRN-servo"].pin_v1, lma=claims["LMA-scaling"].pin_v1)


@pytest.fixture
def project(repo: Path) -> Path:
    commit(repo, {"belief.yaml": CLAIMED, "consistency.yaml": DESIGN, "servo.py": servo()}, "tag the servo")
    return repo


@pytest.fixture
def aligned(project: Path) -> Path:
    commit(project, {"servo.py": pinned(scan(project))}, "reviewed: pin the servo")
    return project


# --- the map: a region, its claims, and back --------------------------------------------------

class TestResolution:
    def test_a_tagged_region_resolves_and_its_claim_finds_it(self, project):
        index = scan(project)
        block = index.get_block("CODE-servo-cap")
        assert block and block.valid and (block.path, block.start_line, block.end_line) == ("servo.py", 2, 8)
        assert {(r.kind, r.target) for r in block.relations} == {("implements", "BRN-servo"), ("uses", "LMA-scaling")}
        assert [b.block_id for b, _ in index.for_claim("BRN-servo")] == ["CODE-servo-cap"]
        assert block.n_code_lines == 3

    def test_a_region_relates_to_several_claims_and_a_claim_to_several_regions(self, aligned):
        twin = ((aligned / "servo.py").read_text(encoding="utf-8")
                .replace("CODE-servo-cap", "CODE-servo-twin").replace("cap * dt", "cap * dt * 0.5"))
        commit(aligned, {"twin.py": twin})
        index = scan(aligned)
        assert sorted(b.block_id for b, _ in index.for_claim("BRN-servo")) == ["CODE-servo-cap", "CODE-servo-twin"]
        assert len(index.get_block("CODE-servo-cap").relations) == 2

    def test_one_id_in_two_files_is_reported_and_neither_counts(self, aligned):
        commit(aligned, {"copy.py": (aligned / "servo.py").read_text(encoding="utf-8")})
        index = scan(aligned)
        assert "DUPLICATE_BLOCK" in codes(index, ERROR)
        assert index.get_block("CODE-servo-cap") is None and index.for_claim("BRN-servo") == []

    def test_unknown_claims_and_unknown_relation_kinds_are_errors(self, project):
        commit(project, {"other.py": "# tdlp:begin CODE-o\n# tdlp:implements BRN-nowhere\n"
                                     "# tdlp:realises BRN-servo\nx = 1\n# tdlp:end CODE-o\n"})
        index = scan(project)
        assert {"UNKNOWN_CLAIM", "UNKNOWN_MARKER"} <= set(codes(index, ERROR))
        block = index.get_block("CODE-o")
        assert link_state(block, block.relations[0], index.claims) == UNKNOWN_CLAIM

    def test_definitions_and_axioms_can_be_implemented(self, project):
        commit(project, {"cap.py": "# tdlp:begin CODE-cap\n# tdlp:implements DEF-cap\nx = 1\n# tdlp:end CODE-cap\n"})
        index = scan(project)
        assert "UNKNOWN_CLAIM" not in codes(index) and index.for_claim("DEF-cap")


# --- the grammar: only real comments, and only well-formed regions -----------------------------

class TestMarkers:
    def test_marker_text_in_strings_and_docstrings_is_not_a_marker(self):
        text = ('"""\n# tdlp:begin CODE-in-doc\n"""\nX = "# tdlp:begin CODE-in-string"\n'
                'Y = """\n# tdlp:end CODE-in-string\n"""\n')
        scan_ = parse_python("m.py", text)
        assert scan_.blocks == [] and scan_.diagnostics == []

    @pytest.mark.parametrize("text,code", [
        ("# tdlp:begin CODE-a\n# tdlp:implements BRN-x\nx = 1\n", "UNMATCHED_BEGIN"),
        ("x = 1\n# tdlp:end CODE-a\n", "UNMATCHED_END"),
        ("# tdlp:begin CODE-a\n# tdlp:implements BRN-x\nx = 1\n# tdlp:end CODE-b\n", "MISMATCHED_END"),
        ("# tdlp:begin CODE-a\n# tdlp:implements BRN-x\n# tdlp:begin CODE-b\nx = 1\n"
         "# tdlp:end CODE-b\n# tdlp:end CODE-a\n", "NESTED_BLOCK"),
        ("# tdlp:begin CODE-a\n# tdlp:implements BRN-x\n# tdlp:end CODE-a\n", "EMPTY_BLOCK"),
        ("# tdlp:begin CODE-a\nx = 1\n# tdlp:end CODE-a\n", "NO_RELATIONS"),
        ("# tdlp:begin CODE-a\nx = 1\n# tdlp:implements BRN-x\n# tdlp:end CODE-a\n", "MISPLACED_RELATION"),
        ("# tdlp:implements BRN-x\nx = 1\n", "MISPLACED_RELATION"),
        ("# tdlp:begin CODE-a\n# tdlp:implements CTR-x\nx = 1\n# tdlp:end CODE-a\n", "MALFORMED_MARKER"),
        ("# tdlp:begin CODE-a\n# tdlp:uses BRN-x\n# tdlp:uses BRN-x\nx = 1\n# tdlp:end CODE-a\n",
         "DUPLICATE_RELATION"),
    ])
    def test_a_malformed_region_is_reported_never_dropped(self, text, code):
        scan_ = parse_python("m.py", text)
        assert code in [d.code for d in scan_.diagnostics]
        if code in ("UNMATCHED_BEGIN", "MISMATCHED_END", "NESTED_BLOCK", "EMPTY_BLOCK"):
            assert scan_.blocks and not all(b.valid for b in scan_.blocks), "kept, and marked invalid"

    def test_a_region_cannot_cross_files(self, project):
        commit(project, {"a.py": "# tdlp:begin CODE-split\n# tdlp:implements BRN-servo\nx = 1\n",
                         "b.py": "y = 2\n# tdlp:end CODE-split\n"})
        assert {"UNMATCHED_BEGIN", "UNMATCHED_END"} <= set(codes(scan(project), ERROR))

    def test_hostile_tag_text_is_shown_escaped(self):
        scan_ = parse_python("m.py", "# tdlp:begin \x1b[31mCODE-x<script>\nx = 1\n")
        [d] = [d for d in scan_.diagnostics if d.code == "MALFORMED_MARKER"]
        assert "\x1b" not in display(d.message) and "\\x1b" in display(d.message)
        assert "\x07" not in display("ring\x07") and len(display("a" * 500)) == 160

    def test_an_f_string_is_one_token_whatever_the_tokenizer(self):
        tokens = [t for t in code_tokens('t = f"{a!r} and {b:>{w}}"\n') if t[0] not in ("NEWLINE", "ENDMARKER")]
        assert [t[1] for t in tokens] == ["t", "=", 'f"{a!r} and {b:>{w}}"']


# --- alignment: the pins, and what changes them ----------------------------------------------

class TestAlignment:
    def test_an_unreviewed_link_names_the_review_to_record(self, project):
        index = scan(project)
        [finding] = [d for d in index.diagnostics if d.severity == REVIEW]
        assert finding.code == "UNREVIEWED" and finding.fix == ('review("CODE-servo-cap", note="what you checked")',)
        block = index.get_block("CODE-servo-cap")
        assert {link_state(block, r, index.claims) for r in block.relations} == {UNREVIEWED}

    def test_written_pins_align_every_link(self, aligned):
        index = scan(aligned)
        assert codes(index, REVIEW) == [] and codes(index, ERROR) == []
        block = index.get_block("CODE-servo-cap")
        assert {link_state(block, r, index.claims) for r in block.relations} == {ALIGNED}

    def test_a_formatter_run_or_a_comment_edit_keeps_the_pin(self, aligned):
        text = (aligned / "servo.py").read_text(encoding="utf-8")
        text = text.replace("delta = min(delta, cap * dt)",
                            "# clamp to the per-step bound\n    delta = min( delta,\n                 cap*dt )\n\n")
        commit(aligned, {"servo.py": text}, "reformat")
        assert codes(scan(aligned), REVIEW) == []

    def test_a_code_edit_stays_reported_at_every_later_commit_until_repinned(self, aligned):
        reviewed = resolve_revision(aligned, "HEAD")
        text = (aligned / "servo.py").read_text(encoding="utf-8")
        commit(aligned, {"servo.py": text.replace("cap * dt", "cap * dt * 2")}, "double the step")
        commit(aligned, {"unrelated.py": "z = 0\n"}, "something else entirely")
        index = scan(aligned)
        [finding] = [d for d in index.diagnostics if d.code == "BODY_CHANGED"]
        assert f"git diff {reviewed[:7]}" in finding.message, "names the revision to diff against"
        block = index.get_block("CODE-servo-cap")
        assert {link_state(block, r, index.claims) for r in block.relations} == {BODY_CHANGED}
        # re-reviewed: the agent writes the header the finding prints
        fixed = (aligned / "servo.py").read_text(encoding="utf-8").replace(
            f"# tdlp:begin CODE-servo-cap@{block.pin}", finding.fix[0])
        commit(aligned, {"servo.py": fixed}, "reviewed the doubled step")
        assert codes(scan(aligned), REVIEW) == []

    def test_moving_a_statement_into_a_branch_is_a_change(self, aligned):
        text = (aligned / "servo.py").read_text(encoding="utf-8").replace(
            "    return previous + delta\n", "    if dt:\n        return previous + delta\n")
        commit(aligned, {"servo.py": text})
        assert "BODY_CHANGED" in codes(scan(aligned), REVIEW)

    def test_restating_a_premise_stales_the_links_of_the_claims_that_cite_it(self, aligned):
        """A claim digest reads one layer (DEF-code-link): the lemma cites DEF-cap, the branch does
        not -- it cites the lemma, whose statement is unchanged."""
        commit(aligned, {"consistency.yaml": DESIGN.replace("never up.", "never up, and never to zero.")},
               "restate DEF-cap")
        index = scan(aligned)
        [restated] = [d for d in index.diagnostics if d.code == "CLAIM_RESTATED"]
        assert "uses LMA-scaling" in restated.message and "the premise it cites DEF-cap" in restated.message
        block = index.get_block("CODE-servo-cap")
        assert {r.target: link_state(block, r, index.claims) for r in block.relations} == {
            "BRN-servo": ALIGNED, "LMA-scaling": CLAIM_RESTATED}

    def test_restating_the_claim_itself_says_so(self, aligned):
        commit(aligned, {"consistency.yaml": DESIGN.replace("at most the bound times dt", "at most the bound")})
        [d] = [d for d in scan(aligned).diagnostics if d.code == "CLAIM_RESTATED"]
        assert "BRN-servo itself" in d.message

    def test_a_derivation_rule_edit_restates_nothing_and_keeps_the_pins(self, aligned):
        commit(aligned, {"consistency.yaml": DESIGN.replace("The step is capped.", "The step is clamped.")})
        assert codes(scan(aligned), REVIEW) == []

    def test_a_removed_claim_leaves_its_tag_and_its_mentions_dangling(self, aligned):
        text = (aligned / "servo.py").read_text(encoding="utf-8") + "# see LMA-scaling for why\n"
        lemma_gone = DESIGN.replace("premises: [AXM-bound, LMA-scaling]", "premises: [AXM-bound, DEF-cap]")
        lemma_gone = lemma_gone[:lemma_gone.index("lemmas:")] + lemma_gone[lemma_gone.index("branches:"):]
        commit(aligned, {"servo.py": text, "consistency.yaml": lemma_gone}, "drop the lemma")
        index = scan(aligned)
        assert "UNKNOWN_CLAIM" in codes(index, ERROR) and "DANGLING_MENTION" in codes(index, ERROR)


# --- mentions: tracked, untracked, dangling --------------------------------------------------

class TestMentions:
    def test_a_mention_outside_any_region_is_untracked(self, aligned):
        commit(aligned, {"util.py": '"""Follows BRN-servo."""\n# by LMA-scaling\nx = 1\n'})
        untracked = [d for d in scan(aligned).diagnostics if d.code == "UNTRACKED_MENTION"]
        assert {d.subject for d in untracked} == {"util.py:1", "util.py:2"}
        assert all(d.severity == OBSERVATION for d in untracked)

    def test_a_mention_a_region_covers_is_tracked_premises_included(self, aligned):
        text = (aligned / "servo.py").read_text(encoding="utf-8").replace(
            "    delta = requested - previous\n",
            "    # LMA-scaling and DEF-cap say capping keeps direction; BRN-idle is another matter\n"
            "    delta = requested - previous\n")
        commit(aligned, {"servo.py": text})
        index = scan(aligned)
        untracked = [d for d in index.diagnostics if d.code == "UNTRACKED_MENTION"]
        assert len(untracked) == 1 and "BRN-idle" in untracked[0].message
        assert codes(index, REVIEW) == [], "a comment edit keeps the body pin"

    def test_a_foreign_ids_file_sets_its_mentions_aside_and_says_so(self, aligned):
        commit(aligned, {"test_x.py": "# tdlp:foreign-ids fixtures\n# builds BRN-made-up\nx = 1\n"})
        index = scan(aligned)
        assert "DANGLING_MENTION" not in codes(index) and index.scope.foreign == ["test_x.py"]
        assert "foreign-ids" in index.scope.describe()

    def test_an_unlinked_branch_names_the_files_its_subject_claims(self, aligned):
        [d] = [d for d in scan(aligned).diagnostics if d.code == "UNLINKED_CLAIM"]
        assert d.subject == "BRN-idle" and "servo.py, idle.py" in d.message


# --- revisions: one commit per scan, and the working tree beside it ---------------------------

class TestRevisions:
    def test_reads_are_pinned_to_one_revision_while_head_moves(self, aligned):
        before = resolve_revision(aligned, "HEAD")
        commit(aligned, {"servo.py": None}, "delete the servo")
        old = build_index(aligned, before, claim_refs(aligned, before))
        assert old.get_block("CODE-servo-cap") is not None and codes(old, REVIEW) == []
        assert scan(aligned).get_block("CODE-servo-cap") is None

    def test_working_tree_edits_are_reported_and_never_indexed(self, aligned):
        text = (aligned / "servo.py").read_text(encoding="utf-8")
        (aligned / "servo.py").write_text(text.replace("cap * dt", "cap"), encoding="utf-8")
        (aligned / "new.py").write_text("# tdlp:begin CODE-new\n# tdlp:implements BRN-idle\nx = 0\n"
                                        "# tdlp:end CODE-new\n", encoding="utf-8")
        index = scan(aligned)
        assert codes(index, REVIEW) == [] and index.get_block("CODE-new") is None
        changes, dirty, _ = scan_worktree(aligned, index)
        assert {(c.block_id, c.change) for c in changes.items} == {("CODE-servo-cap", BODY), ("CODE-new", ADDED)}
        assert dirty == ["new.py", "servo.py"]

    def test_a_region_is_tagged_committed_and_reviewed(self, aligned, monkeypatch):
        """Untagged code: the agent names the claim in the docstring, commits the code, reads it
        against its claim and records the review -- no pin is written into the source."""
        from consistency_belief.server import review
        from stamp_monitor.links import report

        monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(aligned))
        idle = 'def idle():\n    """Command nothing.\n\n    Implements: BRN-idle\n    """\n    return 0.0\n'
        (aligned / "idle.py").write_text(idle, encoding="utf-8")
        assert "CODE-idle--idle: commit it as it stands" in report(aligned)
        assert "a review reads committed code" in review("CODE-idle--idle"), "uncommitted is refused"
        commit(aligned, {"idle.py": idle}, "tag the idle path")
        assert "REV-0001 recorded: CODE-idle--idle implements BRN-idle -- aligned" in review(
            "CODE-idle--idle", note="returns zero, so nothing moves")
        index = scan(aligned)
        assert codes(index, REVIEW) == [] and codes(index, ERROR) == []
        assert "UNLINKED_CLAIM" not in codes(index), "the branch is linked now"
        assert "idle.py" not in subprocess.run(["git", "status", "--porcelain"], cwd=aligned, check=False,
                                               capture_output=True, text=True).stdout, "no source edited"


# --- what a range of commits did --------------------------------------------------------------

class TestChanges:
    def test_identity_survives_movement_and_inserted_lines(self, aligned):
        base = resolve_revision(aligned, "HEAD")
        text = (aligned / "servo.py").read_text(encoding="utf-8")
        commit(aligned, {"servo.py": None, "control/servo.py": "import math\n\n\n" + text}, "move it")
        changes = compare_indexes(build_index(aligned, base), scan(aligned))
        assert [(c.block_id, c.change) for c in changes.items] == [("CODE-servo-cap", MOVED)]
        assert codes(scan(aligned), REVIEW) == [], "a move is not an edit"

    def test_a_body_change_and_a_relation_change_are_told_apart(self, aligned):
        base = resolve_revision(aligned, "HEAD")
        text = (aligned / "servo.py").read_text(encoding="utf-8")
        commit(aligned, {"servo.py": text.replace("cap * dt", "cap * dt * 2")})
        assert [c.change for c in compare_indexes(build_index(aligned, base), scan(aligned)).items] == [BODY]
        mid = resolve_revision(aligned, "HEAD")
        lines = [ln for ln in text.splitlines(keepends=True) if "tdlp:uses" not in ln]
        commit(aligned, {"servo.py": "".join(lines).replace("cap * dt", "cap * dt * 2")})
        [change] = compare_indexes(build_index(aligned, mid), scan(aligned)).items
        assert change.change == RELATIONS and "dropped uses LMA-scaling" in change.detail

    def test_a_repin_is_visible_as_a_review_asserted(self, aligned):
        base = resolve_revision(aligned, "HEAD")
        text = (aligned / "servo.py").read_text(encoding="utf-8")
        block = scan(aligned).get_block("CODE-servo-cap")
        commit(aligned, {"servo.py": text.replace(f"@{block.pin}", "@00000000")})
        assert [c.change for c in compare_indexes(build_index(aligned, base), scan(aligned)).items] == [REPINNED]

    def test_a_deleted_region_orphans_its_claim_and_a_rename_is_recognised(self, aligned):
        base = resolve_revision(aligned, "HEAD")
        text = (aligned / "servo.py").read_text(encoding="utf-8")
        commit(aligned, {"servo.py": text.replace("CODE-servo-cap", "CODE-servo-step")})
        changes = compare_indexes(build_index(aligned, base), scan(aligned))
        assert {c.change for c in changes.items} == {REMOVED, RENAMED, ADDED} and changes.orphaned == []
        commit(aligned, {"servo.py": "def step():\n    pass\n"})
        changes = compare_indexes(build_index(aligned, base), scan(aligned))
        assert changes.orphaned == ["BRN-servo"]


# --- scope: what is read, and what is said about the rest -------------------------------------

class TestScope:
    def test_unsupported_languages_and_unreadable_files_are_explicit(self, aligned):
        commit(aligned, {"deploy.sh": "#!/bin/sh\n# tdlp:begin CODE-sh\n# tdlp:implements BRN-idle\n",
                         "README.md": "# tdlp:begin CODE-in-docs\n",
                         "broken.py": 'x = """never closed\n'})
        (aligned / "latin.py").write_bytes(b"# -*- coding: ascii -*-\nx = '\xe9'\n")
        git(aligned, "add", "-A")
        git(aligned, "commit", "-q", "-m", "odd files")
        index = scan(aligned)
        errors = {(d.code, d.subject) for d in index.diagnostics if d.severity == ERROR}
        assert ("UNSUPPORTED_LANGUAGE", "deploy.sh") in errors
        assert ("SOURCE_UNPARSABLE", "broken.py") in errors and ("SOURCE_UNREADABLE", "latin.py") in errors
        assert not any("README.md" in s for _, s in errors), "documentation is excluded, and counted"
        assert index.scope.excluded.get("documentation") == 1

    def test_ledger_files_are_never_scanned(self, aligned):
        commit(aligned, {".consistency/notes.py": "# tdlp:begin CODE-ledger\n"})
        index = scan(aligned)
        assert "UNMATCHED_BEGIN" not in codes(index) and index.scope.excluded.get("ledger") == 1


# --- boundaries: no proof state moves, and the verifier never sees code ------------------------

class TestBoundaries:
    @pytest.fixture
    def roots(self, aligned, monkeypatch):
        monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(aligned))
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(aligned))
        monkeypatch.setenv("STAMP_MONITOR_ROOT", str(aligned))
        return aligned

    def test_links_move_no_proof_state_and_enter_no_premise_graph(self, roots):
        from consistency_belief.views import Context

        tagged = Context.build(roots)
        commit(roots, {"servo.py": "def step():\n    pass\n"}, "untag")
        untagged = Context.build(roots)
        assert [(s.target_id, s.state) for s in tagged.slices] == [(s.target_id, s.state) for s in untagged.slices]
        assert {n: sorted(p) for n, p in tagged.dag.parents.items()} == {n: sorted(p) for n, p in untagged.dag.parents.items()}
        assert not any(n.startswith("CODE-") for n in tagged.dag.nodes)

    def test_the_probe_carries_no_code(self, roots):
        from consistency_belief.server import status

        probe = status(view="probe")
        assert "BRN-servo" in probe
        assert "CODE-" not in probe and "servo.py" not in probe and "tdlp:" not in probe

    def test_audit_change_names_the_links_a_restatement_unpins_by_id_only(self, roots):
        from consistency_belief.server import audit_change

        out = audit_change("DEF-cap", proposed_statement="A vector scaled to exactly a given norm.")
        assert "CODE-servo-cap uses LMA-scaling" in out, "the lemma cites DEF-cap"
        assert "CODE-servo-cap implements BRN-servo" not in out, "the branch reads the lemma, not DEF-cap"
        assert "servo.py" not in out
        same = audit_change("DEF-cap", proposed_statement="A vector scaled down to at most a given norm, never up.")
        assert "unaffected, their reviews hold" in same

    def test_the_monitor_reports_and_writes_nothing(self, roots):
        from stamp_monitor.audit import audit
        from stamp_monitor.server import links

        text = (roots / "servo.py").read_text(encoding="utf-8")
        commit(roots, {"servo.py": text.replace("cap * dt", "cap")}, "edit the servo")
        ledgers = {p: p.read_bytes() for d in (".belief", ".consistency") if (roots / d).exists()
                   for p in (roots / d).rglob("*") if p.is_file()}
        report = links()
        assert "BODY_CHANGED CODE-servo-cap" in report and "to review (1)" in report and "code since" in report
        assert "LINK_BODY_CHANGED" in {f.code for f in audit(roots)}
        assert {p: p.read_bytes() for p in ledgers} == ledgers

    def test_impact_reports_what_the_range_did_beside_the_chain(self, roots):
        from stamp_monitor.impact import impact, render

        text = (roots / "servo.py").read_text(encoding="utf-8")
        commit(roots, {"servo.py": text.replace("cap * dt", "cap") + "\nOTHER = 1\n"}, "edit")
        result = impact(roots, "HEAD~1")
        assert any("CODE-servo-cap body" in line and "review against BRN-servo" in line for line in result.links)
        assert result.branches["BRN-servo"] == ["governs CMP-grasp", "cites CTR-grasp-reachable"], \
            "a region is not a premise of its branch: the branch is reached through its component alone"
        assert "tagged code regions" in render(result)

    def test_strict_links_exits_one_until_every_link_is_aligned(self, roots):
        def cli() -> int:
            return subprocess.run([sys.executable, "-m", "stamp_monitor.cli", "links", "--strict"],
                                  cwd=roots, capture_output=True, text=True,
                                  env={**__import__("os").environ,
                                       "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}).returncode

        assert cli() == 0
        text = (roots / "servo.py").read_text(encoding="utf-8")
        commit(roots, {"servo.py": text.replace("cap * dt", "cap")}, "edit without review")
        assert cli() == 1


def test_an_unpinned_motivated_by_is_explanatory_never_aligned(project):
    """motivated-by asserts no correspondence, so it is not a code link (DEF-code-link): without a
    pin of its own it is reported as explanatory, and never counted as aligned."""
    from code_links import EXPLANATORY
    from stamp_monitor.links import report

    commit(project, {"why.py": "# tdlp:begin CODE-why\n# tdlp:motivated-by AXM-bound\nx = 1\n# tdlp:end CODE-why\n"})
    index = scan(project)
    block = index.get_block("CODE-why")
    assert link_state(block, block.relations[0], index.claims) == EXPLANATORY
    assert "UNPINNED" not in {d.code for d in index.diagnostics if d.subject == "CODE-why"}
    assert "1 motivated-by, explanatory only" in report(project)



class TestReportBySubject:
    """Reported from a project with seven regions in its working tree and hundreds of untracked
    mentions: a scanned file without regions was 'not a scanned path', a region not yet committed
    could not be found by its id, and the pins to write were at the end of a report too large to
    return."""

    def test_a_scanned_file_with_no_region_resolves(self, aligned):
        from stamp_monitor.links import report

        commit(aligned, {"util.py": "# by LMA-scaling\nx = 1\n", "plain.py": "y = 2\n"})
        text = report(aligned, "util.py")
        assert "util.py: 0 region(s)" in text and "UNTRACKED_MENTION util.py:1" in text
        assert "plain.py: 0 region(s)" in report(aligned, "plain.py")
        assert "nothing uncommitted matches it either" in report(aligned, "nowhere.py")

    def test_an_uncommitted_region_is_found_by_id_claim_or_path_with_what_to_do(self, aligned):
        from stamp_monitor.links import report

        (aligned / "idle.py").write_text("# tdlp:begin CODE-idle\n# tdlp:implements BRN-idle\nx = 0\n"
                                         "# tdlp:end CODE-idle\n", encoding="utf-8")
        for subject in ("CODE-idle", "BRN-idle", "idle.py"):
            text = report(aligned, subject)
            assert "CODE-idle added" in text, subject
            assert 'CODE-idle: commit it as it stands, read it against BRN-idle, then record review("CODE-idle"' in text, subject
        assert "in the working tree only" in report(aligned, "CODE-idle")
        assert "CODE-idle" not in report(aligned, "CODE-servo-cap"), "narrowed to its subject"

    def test_a_long_report_counts_what_it_cannot_list_and_puts_the_uncommitted_first(self, aligned):
        from stamp_monitor.links import LISTED, report

        commit(aligned, {f"pkg/m{i:02d}.py": f"# per LMA-scaling, step {i}\nx = {i}\n" for i in range(LISTED + 10)})
        (aligned / "idle.py").write_text("# tdlp:begin CODE-idle\n# tdlp:implements BRN-idle\nx = 0\n"
                                         "# tdlp:end CODE-idle\n", encoding="utf-8")
        text = report(aligned)
        assert text.count("UNTRACKED_MENTION pkg/") == 0, "counted, not listed"
        assert f"UNTRACKED_MENTION {LISTED + 10} in {LISTED + 10} place(s)" in text
        assert text.index("uncommitted --") < text.index("observations --")
        assert "UNTRACKED_MENTION pkg/m03.py:1" in report(aligned, "pkg/m03.py"), "listed in full by subject"



class TestMeasurementBesideLinks:
    """'aligned' says the code was read against the claim; only the cited contract says whether it
    still works. A solver upgraded under an unchanged region moves the second, never the first."""

    def test_each_link_shows_the_state_of_the_evidence_its_claim_cites(self, aligned):
        from stamp_monitor.links import report

        text = report(aligned)
        assert "evidence: CTR-grasp-reachable [no evidence]" in text
        assert "LINKED_EVIDENCE_NOT_SUPPORTED BRN-servo" in text
        assert "evidence: CTR-grasp-reachable [no evidence]" in report(aligned, "CODE-servo-cap")

    def test_a_test_that_names_no_environment_file_is_reported_until_it_does(self, aligned):
        from stamp_monitor.audit import audit
        from stamp_monitor.links import report

        assert "UNSCOPED_ENVIRONMENT TST-grasp-ik" in report(aligned)
        assert "LINK_UNSCOPED_ENVIRONMENT" in {f.code for f in audit(aligned)}
        belief = (aligned / "belief.yaml").read_text(encoding="utf-8").replace(
            "    capture: [lighting, model_revision]\n",
            "    capture: [lighting, model_revision]\n    reads: [uv.lock]\n")
        commit(aligned, {"belief.yaml": belief, "uv.lock": "# the lock\n"}, "scope the test's environment")
        assert "UNSCOPED_ENVIRONMENT" not in report(aligned)

    def test_names_environment_reads_run_lines_and_reads(self):
        from stamp_monitor.links import _names_environment

        assert _names_environment("python run.py", ["deps/requirements-dev.txt"])
        assert _names_environment("pip install -r requirements.txt && pytest", [])
        assert not _names_environment("python run.py $OUT", ["tests/conftest.py"])


# --- reviews: ledger records bound to a commit, never lines in the source ----------------------

@pytest.fixture
def reviewing(project: Path, monkeypatch) -> Path:
    for var in ("CONSISTENCY_PROJECT_ROOT", "BELIEF_PROJECT_ROOT", "STAMP_MONITOR_ROOT"):
        monkeypatch.setenv(var, str(project))
    return project


def states(root: Path, block_id: str = "CODE-servo-cap") -> dict[str, str]:
    index = scan(root)
    block = index.get_block(block_id)
    return {r.target: link_state(block, r, index.claims) for r in block.relations}


class TestReviews:
    def test_a_ledger_review_aligns_a_link_until_either_side_moves(self, reviewing):
        from consistency_belief.server import review

        assert set(states(reviewing).values()) == {UNREVIEWED}
        out = review("CODE-servo-cap", note="delta is capped at cap * dt; the scaling keeps direction")
        assert "REV-0001 recorded: CODE-servo-cap implements BRN-servo -- aligned" in out
        assert "REV-0002 recorded: CODE-servo-cap uses LMA-scaling -- aligned" in out
        assert set(states(reviewing).values()) == {ALIGNED}
        assert "tdlp:begin CODE-servo-cap\n" in (reviewing / "servo.py").read_text(encoding="utf-8"), "no pin written"

        text = (reviewing / "servo.py").read_text(encoding="utf-8")
        commit(reviewing, {"servo.py": text.replace("cap * dt", "cap")}, "edit the servo")
        assert set(states(reviewing).values()) == {BODY_CHANGED}
        review("CODE-servo-cap", note="the cap no longer scales with dt; still a cap")
        assert set(states(reviewing).values()) == {ALIGNED}

        commit(reviewing, {"consistency.yaml": DESIGN.replace("preserves its direction", "keeps its direction")},
               "restate the lemma")
        assert states(reviewing) == {"BRN-servo": CLAIM_RESTATED, "LMA-scaling": CLAIM_RESTATED}, \
            "the lemma is the branch's premise: both claims moved"

    def test_a_failed_review_reads_not_aligned_until_reviewed_again(self, reviewing):
        from consistency_belief.server import review

        assert "needs a note" in review("CODE-servo-cap", target="BRN-servo", outcome="not_aligned")
        review("CODE-servo-cap", target="BRN-servo", outcome="not_aligned", note="no cap when dt is negative")
        review("CODE-servo-cap", target="LMA-scaling")
        assert states(reviewing) == {"BRN-servo": REVIEW_FAILED, "LMA-scaling": ALIGNED}
        finding = [d for d in scan(reviewing).diagnostics if d.code == "REVIEW_FAILED"]
        assert len(finding) == 1 and "no cap when dt is negative" in finding[0].message
        review("CODE-servo-cap", target="BRN-servo", note="dt is never negative: the scheduler guarantees it")
        assert states(reviewing) == {"BRN-servo": ALIGNED, "LMA-scaling": ALIGNED}, "the latest review wins"

    def test_a_review_of_uncommitted_code_or_claims_is_refused(self, reviewing):
        from consistency_belief.server import review

        text = (reviewing / "servo.py").read_text(encoding="utf-8")
        (reviewing / "servo.py").write_text(text.replace("cap * dt", "cap"), encoding="utf-8")
        assert "servo.py has uncommitted edits" in review("CODE-servo-cap")
        (reviewing / "servo.py").write_text(text, encoding="utf-8")
        (reviewing / "consistency.yaml").write_text(DESIGN.replace("preserves its direction", "keeps its direction"),
                                                    encoding="utf-8")
        assert "LMA-scaling, or a node it rests on, has uncommitted edits" in review("CODE-servo-cap", target="LMA-scaling")
        assert "BRN-servo, or a node it rests on, has uncommitted edits" in review("CODE-servo-cap", target="BRN-servo")
        assert set(states(reviewing).values()) == {UNREVIEWED}, "nothing was recorded"
        assert "is not a region at" in review("CODE-nowhere")

    def test_pins_in_headers_count_as_reviews(self, aligned, monkeypatch):
        """Pins written before reviews were ledger records still align, under grammar 1 -- so an
        upgrade stales nothing -- and a ledger review, once recorded, takes their place."""
        from consistency_belief.server import review

        monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(aligned))
        assert set(states(aligned).values()) == {ALIGNED}
        text = (aligned / "servo.py").read_text(encoding="utf-8")
        documented = text.replace("    delta = requested - previous\n",
                                  '    """The step, capped."""\n    delta = requested - previous\n')
        commit(aligned, {"servo.py": documented}, "document the servo step")
        assert set(states(aligned).values()) == {BODY_CHANGED}, "grammar 1 kept docstrings"
        review("CODE-servo-cap", note="only a docstring was added")
        assert set(states(aligned).values()) == {ALIGNED}
        commit(aligned, {"servo.py": documented.replace("The step, capped.", "One capped step.")}, "reword")
        assert set(states(aligned).values()) == {ALIGNED}, "a ledger review is under grammar 2: docstrings aside"


IDLE = '''"""The idle path.

Uses: AXM-bound
"""


class Idle:
    """An idle arm.

    Implements: BRN-idle
    """

    def command(self):
        """Command nothing; by LMA-scaling a zero step stays zero.

        Region: CODE-idle-command
        Uses: LMA-scaling
        """
        return 0.0
'''


class TestDocstringRegions:
    def test_a_docstring_declares_a_function_region(self, reviewing):
        from consistency_belief.server import review

        commit(reviewing, {"idle.py": IDLE}, "the idle path, linked in its docstrings")
        index = scan(reviewing)
        found = {b.block_id: (b.origin, sorted((r.kind, r.target) for r in b.relations), b.start_line, b.end_line)
                 for b in index.blocks if b.path == "idle.py"}
        assert found == {"CODE-idle": ("docstring", [("uses", "AXM-bound")], 1, 20),
                         "CODE-idle--Idle": ("docstring", [("implements", "BRN-idle")], 7, 19),
                         "CODE-idle-command": ("docstring", [("uses", "LMA-scaling")], 13, 19)}
        assert "UNTRACKED_MENTION" not in [d.code for d in index.diagnostics if d.path == "idle.py"], \
            "a mention inside a region that declares it is tracked"
        assert "UNLINKED_CLAIM" not in [d.code for d in index.diagnostics if d.subject == "BRN-idle"]

        for region in ("CODE-idle", "CODE-idle--Idle", "CODE-idle-command"):
            review(region, note="read against its claim")
        assert {s for b in ("CODE-idle", "CODE-idle--Idle", "CODE-idle-command")
                for s in states(reviewing, b).values()} == {ALIGNED}
        commit(reviewing, {"idle.py": IDLE.replace("Command nothing", "Send no command")}, "reword a docstring")
        assert set(states(reviewing, "CODE-idle-command").values()) == {ALIGNED}, "a docstring edit stales nothing"
        commit(reviewing, {"idle.py": IDLE.replace("return 0.0", "return 0")}, "change the code")
        assert set(states(reviewing, "CODE-idle-command").values()) == {BODY_CHANGED}
        assert set(states(reviewing, "CODE-idle--Idle").values()) == {BODY_CHANGED}, "the class holds the method"

    def test_a_docstring_relation_carries_no_pin_and_prose_declares_nothing(self):
        scan_ = parse_python("x.py", 'def f():\n    """Implements: BRN-servo@12345678\n\n    Uses: the grid, per DEF-cap.\n    """\n    return 1\n')
        assert [d.code for d in scan_.diagnostics] == ["MALFORMED_MARKER"]
        [block] = scan_.blocks
        assert [(r.kind, r.target, r.pin) for r in block.relations] == [("implements", "BRN-servo", None)]
        assert [m.target for m in scan_.mentions] == ["DEF-cap"], "a line of prose is a mention, not a relation"


class TestReviewBundle:
    def test_a_stale_link_shows_both_diffs_since_its_review(self, reviewing):
        from consistency_belief.server import review
        from stamp_monitor.links import report

        review("CODE-servo-cap", note="capped at cap * dt")
        text = (reviewing / "servo.py").read_text(encoding="utf-8")
        commit(reviewing, {"servo.py": text.replace("cap * dt", "cap"),
                           "consistency.yaml": DESIGN.replace("preserves its direction", "keeps its direction")},
               "edit the servo and restate the lemma")
        out = report(reviewing, "CODE-servo-cap")
        assert "to review:" in out
        assert "claim since" in out and "LMA-scaling: Capping a vector [-preserves-] {+keeps+} its direction." in out
        assert "code since" in out and "-    delta = min(delta, cap * dt)" in out and "+    delta = min(delta, cap)" in out
        assert "last review REV-0001" in out and "capped at cap * dt" in out
        assert 'once read, record: review("CODE-servo-cap", note="what you checked")' in out
        assert "to review (1)" in report(reviewing), "the full report draws the bundle too"


# --- reviews travel with the code; claims read one layer; moved code keeps its review ----------

class TestVersionedReviews:
    def test_reviews_go_to_a_file_git_can_track_and_an_ignored_one_is_named(self, reviewing):
        """Reported from embodied_ai, whose .gitignore keeps *.jsonl ledgers local: its reviews
        existed on one machine. Reviews now have a file of their own, and an ignored one is named."""
        from consistency_belief.server import review
        from consistency_belief.store import Store

        # A review 0.8.0 recorded as an event is carried into the file by the first new one.
        (reviewing / ".consistency").mkdir(exist_ok=True)
        old = {"timestamp": "2026-10-08T00:00:00+00:00", "actor": "agent", "tool": "review",
               "payload": {"id": "REV-0001", "kind": "link", "region": "CODE-servo-cap", "target": "LMA-scaling",
                           "commit": "0" * 40, "body": "00000000", "claim": "00000000", "outcome": "aligned"}}
        (reviewing / ".consistency" / "events.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")
        out = review("CODE-servo-cap", target="BRN-servo", note="capped at cap * dt")
        assert "REV-0002 recorded" in out and "commit .consistency/reviews.yaml with your change" in out
        text = (reviewing / ".consistency" / "reviews.yaml").read_text(encoding="utf-8")
        assert text.startswith("# Reviews of code links") and '"carried_from": "events.jsonl"' in text
        assert [r["id"] for r in Store(reviewing).reviews()] == ["REV-0001", "REV-0002"]

        commit(reviewing, {".gitignore": ".consistency/\n"}, "keep the ledgers local")
        out = review("CODE-servo-cap", target="BRN-servo", note="again")
        assert ".consistency/reviews.yaml is ignored by git (.gitignore:1:.consistency/)" in out
        assert "`!.consistency/reviews.yaml`" in out


class TestClaimDigest:
    def test_a_restatement_beyond_the_cited_premises_leaves_the_link_aligned(self, reviewing):
        from consistency_belief.server import review

        review("CODE-servo-cap", note="read against both")
        commit(reviewing, {"consistency.yaml": DESIGN.replace("never up.", "never up, and never to zero.")},
               "restate DEF-cap, which the lemma cites and the branch does not")
        assert states(reviewing) == {"BRN-servo": ALIGNED, "LMA-scaling": CLAIM_RESTATED}

    def test_old_claim_digests_are_judged_at_the_revision_they_were_taken(self, aligned, monkeypatch):
        """Header pins and 0.8.0 reviews recorded the earlier, transitive digest. Each counts as the
        one-layer digest its claim had at the latest revision with that earlier digest
        (DEF-review): the change of rule stales nothing, and a deep restatement stales only what
        reads it."""
        monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(aligned))
        assert set(states(aligned).values()) == {ALIGNED}, "the change of rule stales nothing"
        index = scan(aligned)
        (aligned / ".consistency").mkdir(exist_ok=True)
        old = {"timestamp": "2026-10-08T00:00:00+00:00", "actor": "agent", "tool": "review",
               "payload": {"id": "REV-0001", "kind": "link", "region": "CODE-servo-cap", "target": "BRN-servo",
                           "commit": index.revision, "body": index.get_block("CODE-servo-cap").body_pin,
                           "grammar": 2, "claim": index.claims["BRN-servo"].pin_v1, "outcome": "aligned"}}
        (aligned / ".consistency" / "events.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")
        commit(aligned, {"consistency.yaml": DESIGN.replace("never up.", "never up, and never to zero.")},
               "restate DEF-cap")
        assert states(aligned) == {"BRN-servo": ALIGNED, "LMA-scaling": CLAIM_RESTATED}
        commit(aligned, {"consistency.yaml": DESIGN.replace("never up.", "never up, and never to zero.")
                         .replace("preserves its direction", "keeps its direction")}, "restate the lemma")
        assert states(aligned) == {"BRN-servo": CLAIM_RESTATED, "LMA-scaling": CLAIM_RESTATED}, \
            "the branch cites the lemma: its statement is what the branch reads"


class TestRelocation:
    def test_a_moved_function_keeps_its_review(self, reviewing):
        from consistency_belief.server import review
        from stamp_monitor.links import report

        commit(reviewing, {"idle.py": IDLE}, "the idle path")
        review("CODE-idle-command", note="returns zero")       # named by its Region: line
        review("CODE-idle--Idle", note="an idle class")         # named by its path: moves change it
        commit(reviewing, {"idle.py": None, "arm/idle.py": IDLE}, "move the idle path into arm/")
        assert set(states(reviewing, "CODE-idle-command").values()) == {ALIGNED}, "a named region kept its id"
        assert set(states(reviewing, "CODE-arm-idle--Idle").values()) == {ALIGNED}, "the review followed the code"
        assert "carried from CODE-idle--Idle (moved, its code unchanged)" in report(reviewing, "CODE-arm-idle--Idle")
        commit(reviewing, {"arm/idle.py": IDLE.replace("return 0.0", "return 0")}, "and edit it")
        assert set(states(reviewing, "CODE-arm-idle--Idle").values()) == {UNREVIEWED}, \
            "a review follows unchanged code only"


class TestDecider:
    def test_the_report_says_which_review_decides(self, aligned, monkeypatch):
        """Reported from embodied_ai: a header pin @5db46a30 beside `body @3e85d4e1` read as a stale
        link, though the pin is compared under grammar 1, where it matches."""
        from consistency_belief.server import review
        from stamp_monitor.links import report

        monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(aligned))
        index = scan(aligned)
        block = index.get_block("CODE-servo-cap")
        out = report(aligned, "CODE-servo-cap")
        assert f"header pin @{block.pin} is grammar 1's @{block.legacy_body_pin}" in out
        assert "decided by its header pin" in out and "HEADER_PIN_SUPERSEDED" not in out
        review("CODE-servo-cap", note="read again")
        out = report(aligned, "CODE-servo-cap")
        assert "decided by REV-0001" in out and "decided by its header pin" not in out
        assert "HEADER_PIN_SUPERSEDED" in [d.code for d in scan(aligned).diagnostics]
