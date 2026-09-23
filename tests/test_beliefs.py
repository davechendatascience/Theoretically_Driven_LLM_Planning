"""The belief layer: what can move a posterior, and what provably cannot."""

from __future__ import annotations

from component_belief.declarations import load
from component_belief.model import (
    STATE_INSUFFICIENT,
    STATE_REFUTED,
    STATE_SUPPORTED,
    compare,
    compute_slices,
)
from component_belief.store import Store
from conftest import trial


def slices_for(repo, trials):
    return compute_slices(load(repo), trials)


def test_asserted_evidence_can_never_move_a_posterior(repo):
    """Rule 10.4, enforced structurally rather than by instruction."""
    measured = [trial(ik=True) for _ in range(6)]
    with_assertions = measured + [trial(ik=False, provenance="asserted") for _ in range(50)]

    base = slices_for(repo, measured)
    polluted = slices_for(repo, with_assertions)

    assert len(base) == len(polluted) == 1
    assert base[0].point == polluted[0].point
    assert base[0].n_valid == polluted[0].n_valid == 6


def test_note_channel_creates_no_evidence(repo):
    store = Store(repo)
    store.append_note("CMP-grasp", "felt jittery on the bench")
    assert store.effective_trials() == []
    assert len(store.notes("CMP-grasp")) == 1


def test_insufficient_evidence_is_a_state_not_a_low_number(repo):
    """Two passing trials must not present as a verdict (5.7)."""
    slices = slices_for(repo, [trial(ik=True), trial(ik=True)])
    assert slices[0].state == STATE_INSUFFICIENT
    assert slices[0].missing["trials_needed"] == 2
    assert slices[0].point > 0.5, "the estimate exists; it just cannot be a verdict"


def test_supported_and_refuted(repo):
    supported = slices_for(repo, [trial(ik=True) for _ in range(30)])
    assert supported[0].state == STATE_SUPPORTED
    refuted = slices_for(repo, [trial(ik=False) for _ in range(30)])
    assert refuted[0].state == STATE_REFUTED


def test_incompatible_evidence_is_never_pooled(repo):
    """Trials differing on a declared compatibility key land in separate
    slices (5.6). Pooling these would average a working revision with a broken
    one and report the mean as the system's health."""
    trials = [trial(ik=True, model_revision="v3") for _ in range(30)]
    trials += [trial(ik=False, model_revision="v4") for _ in range(30)]
    slices = slices_for(repo, trials)

    assert len(slices) == 2
    assert len({s.compat_group for s in slices}) == 2
    by_group = {s.compat_group: s for s in slices}
    assert sorted((s.passes, s.fails) for s in by_group.values()) == [(0, 30), (30, 0)]
    assert {s.state for s in slices} == {STATE_SUPPORTED, STATE_REFUTED}


def test_declared_buckets_partition_evidence(repo):
    trials = [trial(ik=True, lighting="normal") for _ in range(30)]
    trials += [trial(ik=False, lighting="low") for _ in range(30)]
    slices = slices_for(repo, trials)
    buckets = {s.bucket: s.state for s in slices}
    assert buckets == {"normal": STATE_SUPPORTED, "low": STATE_REFUTED}


def test_unmatched_conditions_land_unbucketed(repo):
    slices = slices_for(repo, [trial(ik=True, lighting="strobe") for _ in range(6)])
    assert slices[0].bucket == "unbucketed"


def test_invalid_trials_are_excluded_but_retained(repo):
    """A trial that failed because the rig was mis-calibrated is not evidence
    against the component (3.6). The posterior must be identical to the one
    computed without those trials present at all."""
    valid = [trial(ik=True) for _ in range(30)]
    with_invalid = valid + [trial(ik=False, validity="invalid") for _ in range(20)]

    clean = slices_for(repo, valid)[0]
    mixed = slices_for(repo, with_invalid)[0]

    assert mixed.n_valid == clean.n_valid == 30
    assert mixed.n_invalid == 20 and clean.n_invalid == 0
    assert mixed.point == clean.point
    assert mixed.state == clean.state == STATE_SUPPORTED


def test_missing_metrics_excluded_not_scored_off_exit_code(repo):
    """A quiet fallback to the runner's outcome is how an unmeasured thing
    starts looking measured. It must be excluded with a reason instead."""
    trials = [trial(ik=True) for _ in range(4)]
    trials += [trial(metrics={}, outcome="pass") for _ in range(4)]
    slices = slices_for(repo, trials)
    assert slices[0].n_valid == 4
    assert slices[0].n_excluded == 4
    assert slices[0].exclusions == {"missing_metrics": 4}


def test_set_hash_is_stable_and_order_independent(repo):
    """The same evidence set must always cite as the same handle, whatever
    order it was read in."""
    trials = [trial(ik=True) for _ in range(6)]
    a = slices_for(repo, trials)[0]
    b = slices_for(repo, list(reversed(trials)))[0]
    assert a.set_hash == b.set_hash


def test_set_hash_changes_when_the_evidence_set_changes(repo):
    six = [trial(ik=True) for _ in range(6)]
    a = slices_for(repo, six)[0]
    b = slices_for(repo, six + [trial(ik=False)])[0]
    assert a.set_hash != b.set_hash, "a citation must not survive its evidence changing"


def test_regression_only_across_compatible_slices(repo):
    before = slices_for(repo, [trial(ik=True, model_revision="v3") for _ in range(30)])
    after = slices_for(repo, [trial(ik=False, model_revision="v3") for _ in range(30)])
    result = compare(before, after)
    assert len(result["regressions"]) == 1
    assert result["not_comparable"] == []


def test_hardware_swap_reports_not_comparable_not_no_regression(repo):
    """The reading that lets a real regression hide behind a hardware swap."""
    before = slices_for(repo, [trial(ik=True, model_revision="v3") for _ in range(30)])
    after = slices_for(repo, [trial(ik=False, model_revision="v9") for _ in range(30)])
    result = compare(before, after)
    assert result["regressions"] == []
    assert len(result["not_comparable"]) == 1
    assert result["not_comparable"][0]["differing_fields"] == ["model_revision"]


def test_amendment_folds_over_the_original(repo):
    store = Store(repo)
    ids = store.append_trials([trial(ik=True) for _ in range(3)])
    store.append_amendment(ids[0], validity="invalid", reason="rig was mis-calibrated")

    folded = {t["id"]: t for t in store.effective_trials()}
    assert folded[ids[0]]["validity"] == "invalid"
    assert folded[ids[0]]["validity_reason"] == "rig was mis-calibrated"
    assert folded[ids[1]]["validity"] == "valid"

    raw = [r for r in store.raw_records() if r.get("kind") == "trial"]
    assert all(r["validity"] == "valid" for r in raw), "the original record is never edited"
    assert any(r.get("kind") == "amendment" for r in store.raw_records())


def test_prior_is_named_in_the_slice(repo):
    from conftest import git
    yaml = (repo / "belief.yaml").read_text() + """
priors:
  - contract: CTR-grasp-reachable
    alpha: 8
    beta: 2
    rationale: prior generation shipped at ~0.8
"""
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "prior")
    slices = slices_for(repo, [trial(ik=True) for _ in range(6)])
    assert slices[0].prior_id == "PRI-CTR-grasp-reachable"
    assert slices[0].alpha == 8 + 6


# --- stamps: what made each file, what ran it, what rests on it --------------------------------

def test_artifacts_view_stamps_files_and_finds_the_unclaimed(repo, monkeypatch):
    """A file no component claims, no test names and no evidence rests on is a candidate; one a
    declared test invoked is not."""
    from component_belief import server
    from component_belief.declarations import load
    from component_belief.stamps import collect
    from component_belief.store import Store
    from conftest import git

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "grasp.py").write_text("# claimed\n", encoding="utf-8")
    (repo / "src" / "orphan.py").write_text("# nobody claims this\n", encoding="utf-8")
    belief = (repo / "belief.yaml").read_text(encoding="utf-8").replace(
        "    remediation: Retune approach sampling",
        "    remediation: Retune approach sampling\n    code: [src/grasp.py]")
    (repo / "belief.yaml").write_text(belief + "\nartifacts: [out]\n", encoding="utf-8")
    (repo / "out").mkdir(exist_ok=True)
    (repo / "out" / "cache.bin").write_text("x" * 100, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "claim one file, leave the other")

    stamps = {s.path: s for s in collect(repo, load(repo), Store(repo))}
    assert "claimed" in stamps["src/grasp.py"].kinds()
    assert stamps["src/orphan.py"].prune_candidate()
    assert not stamps["src/grasp.py"].prune_candidate()
    assert "out/cache.bin" in stamps and not stamps["out/cache.bin"].tracked

    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    text = server.status(view="artifacts")
    assert "src/orphan.py" in text.split("prune candidates")[1]
    assert "out/cache.bin" in text


def test_the_read_hook_records_what_a_run_opened(repo, monkeypatch):
    """A run that opens an artifact says so itself, so the artifact's verdict is a fact about
    what read it rather than a guess from its mtime."""
    from component_belief import server
    from component_belief.declarations import load
    from component_belief.stamps import collect
    from component_belief.store import Store
    from conftest import git

    (repo / "out").mkdir(exist_ok=True)
    (repo / "out" / "big.bin").write_text("data" * 10, encoding="utf-8")
    (repo / "reader.py").write_text(
        "from pathlib import Path\n"
        "print(Path('out/big.bin').read_text())\n"
        "Path(__import__('os').environ['OUT']).write_text('[{\"metrics\": {\"ik_success\": true}}]')\n",
        encoding="utf-8")
    belief = (repo / "belief.yaml").read_text(encoding="utf-8").replace(
        '    run: "echo ok"', '    run: "python reader.py"')
    (repo / "belief.yaml").write_text(belief + "\nartifacts: [out]\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a test that reads an artifact")

    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    server.run_test(test_id="TST-grasp-ik")

    stamps = {s.path: s for s in collect(repo, load(repo), Store(repo))}
    artifact = stamps["out/big.bin"]
    assert "opened" in artifact.kinds(), artifact.stamps
    assert artifact.artifact_verdict().startswith("kept"), artifact.artifact_verdict()
    assert "reader.py" not in [p for p in stamps if stamps[p].prune_candidate()]


def test_the_hook_survives_a_command_that_sets_pythonpath(repo, monkeypatch):
    """A declared command of the form `env PYTHONPATH=... python ...` replaces the environment the
    runner prepared. Recording nothing then reads exactly like a run that opened no files."""
    from pathlib import Path

    from component_belief import readlog, server
    from component_belief.store import Store
    from conftest import git

    import os

    hook, sep = str(Path("/hook")), os.pathsep      # the platform's own spelling of both
    woven = readlog.weave("env PYTHONPATH=third_party:. python x.py", Path("/hook"))
    assert woven.startswith(f"env PYTHONPATH={hook}{sep}third_party:. ")
    assert readlog.weave('PYTHONPATH="a:b" python x.py', Path("/hook")) == f'PYTHONPATH="{hook}{sep}a:b" python x.py'
    assert readlog.weave("python x.py", Path("/hook")) == "python x.py"

    (repo / "lib").mkdir(exist_ok=True)
    (repo / "lib" / "data.txt").write_text("payload", encoding="utf-8")
    (repo / "reader2.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "Path('lib/data.txt').read_text()\n"
        "Path(os.environ['OUT']).write_text('[{\"metrics\": {\"ik_success\": true}}]')\n",
        encoding="utf-8")
    belief = (repo / "belief.yaml").read_text(encoding="utf-8").replace(
        '    run: "echo ok"', '    run: "env PYTHONPATH=lib:. python reader2.py"')
    (repo / "belief.yaml").write_text(belief, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a test that sets PYTHONPATH itself")

    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    server.run_test(test_id="TST-grasp-ik")
    reads = readlog.read(Store(repo).artifacts_dir / "RUN-0001")
    assert "lib/data.txt" in reads, reads


def test_the_read_log_drops_the_environments_own_files(tmp_path):
    """A run opens hundreds of library files; they say nothing about what the project needs."""
    from component_belief import readlog

    log = tmp_path / "reads.log"
    root = tmp_path / "proj"
    (root / "lib").mkdir(parents=True)
    log.write_text("\n".join(str(root / p) for p in (
        ".venv/lib/python3.12/site-packages/numpy/__init__.py",
        "__pycache__/x.cpython-312.pyc",
        ".pytest_cache/v/cache/lastfailed",
        ".belief/artifacts/RUN-0001/stdout.txt",
        "lib/data.txt",
        "tools/run.py",
    )), encoding="utf-8")
    assert readlog.harvest(root, log) == ["lib/data.txt", "tools/run.py"]


def test_an_import_from_cached_bytecode_counts_as_reading_the_source(tmp_path):
    """With a valid .pyc Python opens only the cache, so the source it compiled from is what the run
    read. A .pyc whose source is gone stays environment noise."""
    from component_belief import readlog

    root = tmp_path / "proj"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    log = tmp_path / "reads.log"
    log.write_text("\n".join(str(root / p) for p in (
        "src/pkg/__pycache__/mod.cpython-312.pyc",
        "src/pkg/__pycache__/gone.cpython-312.pyc",
    )), encoding="utf-8")
    assert readlog.harvest(root, log) == ["src/pkg/mod.py"]


def _probe_test(repo, script: str) -> None:
    """Declare TST-grasp-ik as `python probe.py`, with `script` as probe.py, and commit."""
    from conftest import git

    (repo / "probe.py").write_text(
        script + "import os, json\njson.dump([{'metrics': {'ik_success': True}}], "
                 "open(os.environ['OUT'], 'w'))\n", encoding="utf-8")
    belief = (repo / "belief.yaml").read_text(encoding="utf-8").replace(
        '    run: "echo ok"', '    run: "python probe.py"')
    (repo / "belief.yaml").write_text(belief, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a probe test")


def test_the_hook_keeps_the_environments_own_sitecustomize(repo, monkeypatch):
    """Python imports the first sitecustomize on the path and no other. The hook's must run the
    one it shadows, or instrumenting a run quietly changes the environment it measures."""
    from component_belief import server

    (repo / "site_extra").mkdir()
    (repo / "site_extra" / "sitecustomize.py").write_text(
        "open('ENV_SITECUSTOMIZE_RAN', 'x').close()\n", encoding="utf-8")
    _probe_test(repo, "")
    monkeypatch.setenv("PYTHONPATH", str(repo / "site_extra"))
    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    server.run_test(test_id="TST-grasp-ik")
    assert (repo / "ENV_SITECUSTOMIZE_RAN").exists()


def test_a_file_the_run_writes_is_not_a_file_it_read(repo, monkeypatch):
    """Output is not a dependency: counting it would keep every artifact a live run produced."""
    import json

    from component_belief import readlog, server
    from component_belief.store import Store

    (repo / "lib").mkdir()
    (repo / "lib" / "in.txt").write_text("input", encoding="utf-8")
    (repo / "made").mkdir()
    _probe_test(repo, "open('lib/in.txt').read()\nopen('made/out.txt', 'w').write('x')\n"
                      "import os\nos.close(os.open('made/raw.bin', os.O_WRONLY | os.O_CREAT))\n")
    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    server.run_test(test_id="TST-grasp-ik")

    run_dir = Store(repo).artifacts_dir / "RUN-0001"
    reads = readlog.read(run_dir)
    assert "lib/in.txt" in reads, "project-relative and in posix form on every platform"
    assert not any(p.startswith("made/") for p in reads), reads
    stamp = json.loads((run_dir / "stamp.json").read_text(encoding="utf-8"))
    assert "lib/in.txt" in stamp["opened"] and "lib/in.txt" in stamp["files"]


def test_evidence_citations_keep_an_artifact_and_flag_the_missing(repo, monkeypatch):
    """A trial names what it measured; while that trial is live, the file it names is not
    prunable -- and if the file is already gone, that is its own finding."""
    from component_belief import server
    from component_belief.declarations import load
    from component_belief.stamps import collect
    from component_belief.store import Store
    from conftest import git, trial

    (repo / "out").mkdir(exist_ok=True)
    (repo / "out" / "model_a.pt").write_text("weights", encoding="utf-8")
    (repo / "belief.yaml").write_text(
        (repo / "belief.yaml").read_text(encoding="utf-8") + "\nartifacts: [out]\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "an artifact a trial will cite")

    store = Store(repo)
    store.append_trials([
        {**trial(), "repro": {"model_revision": "model_a.pt:abc123"}},
        {**trial(), "repro": {"model_revision": "model_gone.pt:def456"}},
    ])

    records = {s.path: s for s in collect(repo, load(repo), store)}
    assert "cited" in records["out/model_a.pt"].kinds()
    assert records["out/model_a.pt"].artifact_verdict().startswith("kept")
    assert collect.dangling.get("model_gone.pt") == 1

    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    text = server.status(view="artifacts")
    assert "model_gone.pt" in text.split("GONE FROM DISK")[1]


def test_a_settings_string_is_not_a_filename_and_a_symlink_answers_for_its_target(repo, monkeypatch):
    """Two heuristics the view got wrong on a real project: a repro value with dots in it is not
    a file, and a trial cites the revision a symlink points at rather than the symlink."""
    from component_belief.declarations import load
    from component_belief.stamps import _FILENAME, collect
    from component_belief.store import Store
    from conftest import git, trial

    assert _FILENAME.fullmatch("vla_gc_r2.pt")
    assert not _FILENAME.fullmatch("layout0.08_xy0.1_z0.05_yaw30_tilt10_null0.3_h400")
    assert not _FILENAME.fullmatch("samples=48,horizon=12,segments=4")

    (repo / "out").mkdir(exist_ok=True)
    (repo / "out" / "model_r3.pt").write_text("weights", encoding="utf-8")
    (repo / "out" / "current.pt").symlink_to("model_r3.pt")
    (repo / "belief.yaml").write_text(
        (repo / "belief.yaml").read_text(encoding="utf-8") + "\nartifacts: [out]\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a symlink to the current revision")

    store = Store(repo)
    store.append_trials([{**trial(), "repro": {"model_revision": "model_r3.pt:abc"}}])
    records = {s.path: s for s in collect(repo, load(repo), store)}
    assert records["out/current.pt"].artifact_verdict().startswith("kept"), \
        "the alias is kept by what its target's trials cite"


def test_amend_reclassifies_many_in_one_pass(repo, monkeypatch):
    """A correction that takes hours does not get made: amend reads the whole ledger per record,
    which is fine for one and impossible for thousands."""
    from component_belief import server
    from component_belief.store import Store
    from conftest import trial

    store = Store(repo)
    ids = store.append_trials([trial() for _ in range(5)])   # the store mints the ids

    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    assert "reason is required" in server.amend(evidence_ids=ids, validity="quarantined")
    assert "not in the ledger" in server.amend(
        evidence_ids=[*ids, "EV-nope"], validity="quarantined", reason="r")

    out = server.amend(evidence_ids=ids, validity="quarantined",
                       reason="the checkpoint these measured is gone")
    assert "amended 5 records" in out
    kept = {t["id"]: t for t in Store(repo).effective_trials()}
    assert all(kept[i]["validity"] == "quarantined" for i in ids)


def test_an_ingested_artifact_uri_is_a_claim_on_the_file(repo, monkeypatch):
    """ingest requires an artifact_uri; a directory every imported trial points at is not
    unwanted just because no repro field repeats its name."""
    from component_belief.declarations import load
    from component_belief.stamps import collect
    from component_belief.store import Store
    from conftest import git, trial

    (repo / "out").mkdir(exist_ok=True)
    (repo / "out" / "round1.trials.json").write_text("[]", encoding="utf-8")
    (repo / "belief.yaml").write_text(
        (repo / "belief.yaml").read_text(encoding="utf-8") + "\nartifacts: [out]\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "an ingested artifact")

    store = Store(repo)
    store.append_trials([{**trial(), "provenance": "imported",
                          "artifact_uri": str(repo / "out" / "round1.trials.json")}])
    records = {s.path: s for s in collect(repo, load(repo), store)}
    assert records["out/round1.trials.json"].artifact_verdict().startswith("kept")

    # and the directory holding it: trials name the file, never the folder
    (repo / "out" / "round2").mkdir()
    (repo / "out" / "round2" / "inner.trials.json").write_text("[]", encoding="utf-8")
    store.append_trials([{**trial(), "provenance": "imported",
                          "artifact_uri": str(repo / "out" / "round2" / "inner.trials.json")}])
    records = {s.path: s for s in collect(repo, load(repo), store)}
    assert records["out/round2"].artifact_verdict().startswith("kept")


def test_every_file_and_folder_carries_a_stamp(repo, monkeypatch):
    """A repository is pruned folder by folder as much as file by file, so a folder is a record
    rather than something a reader assembles from the files inside it."""
    from component_belief.declarations import load
    from component_belief.stamps import collect
    from component_belief.store import Store
    from conftest import git

    (repo / "out" / "round1").mkdir(parents=True)
    (repo / "out" / "round1" / "shard.npz").write_text("x", encoding="utf-8")
    (repo / "src" / "deep").mkdir(parents=True)
    (repo / "src" / "deep" / "mod.py").write_text("# code\n", encoding="utf-8")
    belief = (repo / "belief.yaml").read_text(encoding="utf-8").replace(
        "    remediation: Retune approach sampling",
        "    remediation: Retune approach sampling\n    code: [src/deep/mod.py]")
    (repo / "belief.yaml").write_text(belief + "\nartifacts: [out]\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a nested file on each side")

    records = {s.path: s for s in collect(repo, load(repo), Store(repo))}
    assert records["out/round1"].directory and records["out/round1/shard.npz"].stamps
    assert records["src/deep"].directory, "a tracked folder is stamped too"
    assert "claimed" in records["src/deep"].kinds(), "a folder carries what its files carry"
    assert not records["src/deep"].prune_candidate(), "a folder is not pruned as if it were code"


def test_the_artifacts_view_writes_the_verdicts_to_a_file(repo, monkeypatch):
    """A verdict you can diff week to week beats one you have to re-read from a report."""
    import json

    from component_belief import server

    (repo / "out").mkdir(exist_ok=True)
    (repo / "out" / "thing.bin").write_text("x", encoding="utf-8")
    (repo / "belief.yaml").write_text(
        (repo / "belief.yaml").read_text(encoding="utf-8") + "\nartifacts: [out]\n", encoding="utf-8")
    from conftest import git
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "one artifact")

    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    text = server.status(view="artifacts")
    assert "stamps.jsonl" in text

    lines = (repo / ".belief/stamps.jsonl").read_text().splitlines()
    header, rows = json.loads(lines[0]), [json.loads(l) for l in lines[1:]]
    assert header["kind"] == "header" and header["declarations"] == "git-HEAD" and header["at"]
    by_path = {r["path"]: r for r in rows}
    assert by_path["out/thing.bin"]["verdict"].startswith("undecidable")
    assert "at" not in by_path["out/thing.bin"], "a committed file diffs on verdicts, not on clocks"
    assert [r["path"] for r in rows] == sorted(r["path"] for r in rows), "stable order"
    assert any(r["directory"] for r in rows), "folders are in the file too"
