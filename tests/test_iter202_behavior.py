"""Black-box behaviour tests for iter 202 -- the tree-snapshot guard stops
attributing a concurrent xdist worker's bytecode write to the read-only command
under test, and iteration 201's sentinel-parser collapse re-lands in the same
commit.

Spec: products/_platform/state/iter-202/pm.md, Expected Behaviors 1-7.

  _is_volatile_snapshot_path(rel) -- pure, module-level, total
  1.  True for a `__pycache__` path COMPONENT at any depth and for a `.pyc` /
      `.pyo` basename anywhere; False for ordinary tracked files -- including
      THE DISCRIMINATING CASE `tests/data/__pycache__notes.md`, which merely
      CONTAINS the token, so a substring rule would silently blind the snapshot
      to a real write. Idempotent, and it touches no file (proved by snapshotting
      a tmp cwd around a sweep, bytes AND directory set).
  _tree_snapshot(root=REPO_ROOT)
  2.  the root is injectable and the exclusion is exact: against an 11-entry
      fixture tree the keys are EXACTLY {top.md, tests/keep.py, roles/keep.md}
      and each value is the sha256 hex digest of that file's bytes.
      The rule is reached BY BARE MODULE NAME -- a `monkeypatch.setattr` spy
      bites and records exactly the 7 files the walk visits, so `.git`,
      `products/` and `work*/` are proved excluded BY CONSTRUCTION (never even
      offered to the predicate) while only bytecode is filtered.
  3.  TWO-SIDED, and this is the deliverable -- the iteration-201 race is
      reproduced offline with no clone and no timing: a foreign
      `tests/__pycache__/other.cpython-313.pyc` appearing between two snapshots
      leaves them EQUAL (the false red is gone), and so does `root/late.pyc`,
      while a NEW `tests/newly_written.py` and a BYTE-REWRITE of an existing
      `tests/keep.py` each still make them DIFFER (the guard was not blinded).
  4.  the pre-existing iteration-134 guarantee survives with no argument: the
      real-tree snapshot is non-empty, still contains the tracked files it is
      there to watch, and now contains NO volatile key -- plus iteration 134's
      own `test_b10` is driven directly and still passes.
  the re-landed parser core (iteration 201, verbatim)
  5.  `foundry._sentinel_token` is live, documented, and honours the anchored
      rule (padded, unspaced, prose-after -> None, `None` text -> None); the
      three gate parsers each still return their OWN token pair and `None` when
      the sentinel is absent; `parse_ship_action` / `parse_ship_sha` are
      untouched; `tests/test_iter201_behavior.py` is present and owns the 54-cell
      golden matrix, which this file therefore does NOT duplicate.
  the iteration's own record
  6.  the roadmap records key to 202 and not to 201 -- a <=120-char ledger row, a
      matching archive bullet, a STATUS line naming 202 with 193/194/199/201 as
      the never-shipped exceptions -- and the live oracles agree, TWO-SIDED: the
      ledger oracle is EMPTY for a shipped set of (202,) and still reports [201]
      for (201,), so an empty result is evidence and not vacuity.
  7.  both modules still import.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-202 PM spec and the
product's OBSERVABLE surface -- importing modules, CALLING functions, reading
`__doc__` / `__module__`, and reading files under `tests/` for CONVENTIONS plus
the product roadmap files (the roadmap is explicitly allowed and is the SUBJECT
of behavior 6). The implementation BODIES of foundry.py / dispatcher.py, the
engineer's notes (engineer.md), the reviewer's notes (reviewer.md) and
`git diff` were NOT read.

Fully offline and deterministic: every fixture is built in `tmp_path`, and there
is no network, no git, no subprocess, no sleep and no clock dependence. Nothing
is written outside `tmp_path`. NO assertion counts files or directories in the
ambient tree and none names a repo-directory basename (the iteration-154
fresh-clone trap): the only ambient-tree assertions are membership of tracked
paths that exist in every clone, and the ABSENCE of a volatile key.
"""
import hashlib
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tests"))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (behavior 7 -- import-safety probe)

import test_iter134_behavior as t134  # noqa: E402  (the subject of behaviors 1-4)

THIS_ITER = 202

# Behavior 1's corpus, straight from the spec.
VOLATILE = (
    "tests/__pycache__/test_iter154_behavior.cpython-313.pyc",
    "roles/__pycache__/x.pyc",
    "tests/a/__pycache__/b/keep.txt",
    "tests/x.pyc",
    "tests/x.pyo",
    "stray.pyc",
)
ORDINARY = (
    "tests/test_iter134_behavior.py",
    "roles/pm.md",
    "foundry.py",
    "README.md",
    "tests/data/__pycache__notes.md",
)

# Behavior 2's fixture tree: 11 entries, only three of which may survive.
FIXTURE = {
    "top.md": b"top\n",
    "stray.pyc": b"\x00bytecode-at-root\n",
    "tests/keep.py": b"# keep\n",
    "tests/__pycache__/keep.cpython-313.pyc": b"\x00cached\n",
    "tests/nested/__pycache__/deep.pyc": b"\x00deep\n",
    "roles/keep.md": b"role\n",
    "roles/keep.pyc": b"\x00role-bytecode\n",
    "topdir/inner.md": b"not-top-level\n",
    "products/live.json": b"{}\n",
    "work1/live.json": b"{}\n",
    ".git/HEAD": b"ref: refs/heads/main\n",
}
SURVIVORS = {"top.md", "tests/keep.py", "roles/keep.md"}

# The spec's fixture proves the exclusion, but NOT that the snapshot applies the
# COMPONENT rule rather than a substring one -- an inlined substring filter keeps
# every assertion above green (measured: that mutant survived the first pass).
# This control sits in the discriminating range and is the only thing that reds it.
TRAP_REL = "tests/data/__pycache__notes.md"
FIXTURE_WITH_TRAP = dict(FIXTURE, **{TRAP_REL: b"notes, not a cache dir\n"})
SURVIVORS_WITH_TRAP = SURVIVORS | {TRAP_REL}


def _build(root, spec=FIXTURE):
    """Materialise a repo-shaped fixture tree under `root`; return `root`."""
    for rel, data in spec.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def _dir_bytes(root):
    """Everything under `root` as (files-as-bytes, directory set) -- iter 145's
    convention for proving a callable wrote nothing."""
    files, dirs = {}, set()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            dirs.add(rel)
        else:
            files[rel] = p.read_bytes()
    return files, dirs


# --------------------------------------------------------------------------
# 1. the predicate: pure, module-level, a COMPONENT match and not a substring
# --------------------------------------------------------------------------
def test_b1_predicate_is_a_module_level_documented_callable():
    pred = t134._is_volatile_snapshot_path
    assert callable(pred)
    assert pred.__module__ == t134.__name__, "must be module-level, not nested"
    assert pred is getattr(t134, "_is_volatile_snapshot_path")
    doc = pred.__doc__ or ""
    for token in ("__pycache__", ".pyc", ".pyo", "COMPONENT", "Pure"):
        assert token in doc, f"docstring must name {token!r}: {doc!r}"


@pytest.mark.parametrize("rel", VOLATILE)
def test_b1_volatile_paths_are_excluded(rel):
    assert t134._is_volatile_snapshot_path(rel) is True


@pytest.mark.parametrize("rel", ORDINARY)
def test_b1_ordinary_paths_are_kept(rel):
    assert t134._is_volatile_snapshot_path(rel) is False


def test_b1_substring_is_not_a_component():
    """THE DISCRIMINATING CASE: a tracked file merely CONTAINING the token stays
    visible, so the exclusion is as narrow as the race it covers."""
    assert t134._is_volatile_snapshot_path("tests/data/__pycache__notes.md") is False
    assert t134._is_volatile_snapshot_path("tests/data/__pycache__/notes.md") is True


def test_b1_is_idempotent_and_touches_no_file(tmp_path, monkeypatch):
    root = _build(tmp_path / "cwd")
    monkeypatch.chdir(root)
    before = _dir_bytes(root)
    for rel in VOLATILE + ORDINARY:
        first = t134._is_volatile_snapshot_path(rel)
        assert t134._is_volatile_snapshot_path(rel) is first, rel
    assert _dir_bytes(root) == before, "the predicate must read and write nothing"


# --------------------------------------------------------------------------
# 2. injectable root, exact exclusion, sha256 values
# --------------------------------------------------------------------------
def test_b2_injectable_root_keeps_exactly_the_non_volatile_tracked_files(tmp_path):
    root = _build(tmp_path / "repo")
    snap = t134._tree_snapshot(root)
    assert set(snap) == SURVIVORS


def test_b2_each_value_is_the_sha256_of_the_files_bytes(tmp_path):
    root = _build(tmp_path / "repo")
    snap = t134._tree_snapshot(root)
    for rel in SURVIVORS:
        expected = hashlib.sha256(FIXTURE[rel]).hexdigest()
        assert snap[rel] == expected, rel


def test_b2_the_snapshot_applies_the_COMPONENT_rule_not_a_substring(tmp_path):
    """A tracked file whose NAME merely contains the token must survive the
    SNAPSHOT, not just the predicate: an inlined substring filter passes every
    other assertion in this file, so this is the control that reds it."""
    root = _build(tmp_path / "repo", FIXTURE_WITH_TRAP)
    snap = t134._tree_snapshot(root)
    assert set(snap) == SURVIVORS_WITH_TRAP
    assert snap[TRAP_REL] == hashlib.sha256(FIXTURE_WITH_TRAP[TRAP_REL]).hexdigest()


def test_b3_a_real_write_to_the_trap_file_is_still_visible(tmp_path):
    """The same control on the DIFFERENCE path: over-broad exclusion would hide a
    genuine rewrite of this file, which is the false GREEN to guard against."""
    root = _build(tmp_path / "repo", FIXTURE_WITH_TRAP)
    before = t134._tree_snapshot(root)
    (root / TRAP_REL).write_bytes(b"MUTATED\n")
    after = t134._tree_snapshot(root)
    assert after != before
    assert after[TRAP_REL] != before[TRAP_REL]


def test_b2_root_defaults_to_the_repository(tmp_path):
    """The parameter is a DEFAULT, so every existing call site keeps working."""
    import inspect
    default = inspect.signature(t134._tree_snapshot).parameters["root"].default
    assert pathlib.Path(default) == _ROOT


# Measured: the exact set of files the walk OFFERS to the predicate, and the
# four fixture paths it never even reaches. The snapshot's exclusion sentence
# names four things; only bytecode is enforced by a filter, the other three hold
# BY CONSTRUCTION -- these two constants pin which is which, black-box.
SEAM_CALLS = {
    "top.md",
    "stray.pyc",
    "tests/keep.py",
    "tests/__pycache__/keep.cpython-313.pyc",
    "tests/nested/__pycache__/deep.pyc",
    "roles/keep.md",
    "roles/keep.pyc",
}
NEVER_OFFERED = {"topdir/inner.md", "products/live.json", "work1/live.json", ".git/HEAD"}


def test_b2_the_filter_is_routed_through_the_module_level_predicate_seam(tmp_path, monkeypatch):
    """The rule is written ONCE and reached BY BARE MODULE NAME: a spy installed
    with `monkeypatch.setattr` bites (a def-time capture would not), and the
    arguments it records are repo-relative POSIX paths -- exactly the files the
    walk visits, each offered once. Source is never inspected."""
    root = _build(tmp_path / "repo")
    calls = []
    real = t134._is_volatile_snapshot_path

    def spy(rel):
        calls.append(rel)
        return real(rel)

    monkeypatch.setattr(t134, "_is_volatile_snapshot_path", spy)
    snap = t134._tree_snapshot(root)

    assert calls, "the snapshot must consult the module-level predicate"
    assert len(calls) == len(set(calls)), f"each file offered exactly once: {calls}"
    assert set(calls) == SEAM_CALLS
    assert set(snap) == SURVIVORS, "the spy passes through, so the verdict is unchanged"


def test_b2_the_by_construction_exclusions_are_never_even_offered(tmp_path, monkeypatch):
    """`.git`, `products/` and `work*/` are excluded because the walk never
    descends into them, NOT by the predicate. Proving that distinction is what
    stops a future reader trusting a docstring exclusion that no code enforces."""
    root = _build(tmp_path / "repo")
    calls = []

    def recorder(rel):
        calls.append(rel)
        return False

    monkeypatch.setattr(t134, "_is_volatile_snapshot_path", recorder)
    t134._tree_snapshot(root)
    assert NEVER_OFFERED.isdisjoint(calls), sorted(NEVER_OFFERED & set(calls))


def test_b3_neutralising_the_rule_restores_exactly_the_volatile_keys(tmp_path, monkeypatch):
    """TWO-SIDED AT THE SEAM, which is what makes behavior 4's `offenders == []`
    load-bearing rather than vacuous: neutralise the rule and the snapshot
    regains the volatile keys and NOTHING else, so the fix subtracts no tracked
    file. Stated as a set identity, never a count, so it holds on a cold clone."""
    root = _build(tmp_path / "repo")
    shipped = t134._tree_snapshot(root)
    monkeypatch.setattr(t134, "_is_volatile_snapshot_path", lambda rel: False)
    unfiltered = t134._tree_snapshot(root)

    extra = set(unfiltered) - set(shipped)
    assert extra == SEAM_CALLS - SURVIVORS
    assert all("__pycache__" in k.split("/") or k.endswith((".pyc", ".pyo"))
               for k in extra), extra
    assert not set(shipped) - set(unfiltered), "the fix must lose no tracked file"


# --------------------------------------------------------------------------
# 3. the iteration-201 race, reproduced offline -- and the guard NOT blinded
# --------------------------------------------------------------------------
def test_b3_a_concurrent_workers_pyc_no_longer_changes_the_snapshot(tmp_path):
    """The exact iteration-201 false red: a foreign bytecode file appearing
    between two snapshots must leave them EQUAL."""
    root = _build(tmp_path / "repo")
    before = t134._tree_snapshot(root)
    late = root / "tests" / "__pycache__" / "other.cpython-313.pyc"
    late.parent.mkdir(parents=True, exist_ok=True)
    late.write_bytes(b"\x00written-by-another-worker\n")
    assert t134._tree_snapshot(root) == before


def test_b3_a_pyc_directly_under_the_root_is_also_ignored(tmp_path):
    root = _build(tmp_path / "repo")
    before = t134._tree_snapshot(root)
    (root / "late.pyc").write_bytes(b"\x00late\n")
    assert t134._tree_snapshot(root) == before


def test_b3_a_new_real_test_file_still_makes_the_snapshot_differ(tmp_path):
    """The load-bearing OTHER side: the fix must not buy a false GREEN."""
    root = _build(tmp_path / "repo")
    before = t134._tree_snapshot(root)
    (root / "tests" / "newly_written.py").write_bytes(b"# new\n")
    after = t134._tree_snapshot(root)
    assert after != before
    assert set(after) - set(before) == {"tests/newly_written.py"}


def test_b3_rewriting_an_existing_files_bytes_still_makes_it_differ(tmp_path):
    root = _build(tmp_path / "repo")
    before = t134._tree_snapshot(root)
    (root / "tests" / "keep.py").write_bytes(b"# MUTATED\n")
    after = t134._tree_snapshot(root)
    assert after != before
    assert set(after) == set(before), "same keys -- only the digest moved"
    assert after["tests/keep.py"] != before["tests/keep.py"]


# --------------------------------------------------------------------------
# 4. the pre-existing iteration-134 guarantee, unchanged in intent
# --------------------------------------------------------------------------
def test_b4_real_tree_snapshot_still_watches_the_files_it_exists_for():
    snap = t134._tree_snapshot()
    assert snap, "the real-tree snapshot must not be empty"
    for rel in ("foundry.py", "tests/test_iter134_behavior.py", "roles/pm.md"):
        assert rel in snap, rel


def test_b4_no_volatile_key_survives_in_the_real_tree_snapshot():
    """Fails on every cached-bytecode key against the unfixed helper; states no
    COUNT, so it is equally true on a cold clone where none exists yet."""
    offenders = [k for k in t134._tree_snapshot()
                 if "__pycache__" in k.split("/") or k.endswith((".pyc", ".pyo"))]
    assert offenders == []


def test_b4_iteration_134s_own_read_only_guarantee_still_passes(tmp_path):
    """Drive iteration 134's own behavior-10 test directly: the helper's fix must
    keep the guarantee it was written for."""
    t134.test_b10_linting_a_typo_config_writes_nothing_into_the_repo_tree(tmp_path)


# --------------------------------------------------------------------------
# 5. the re-landed shared parser core is live (equivalence NOT re-proved here)
# --------------------------------------------------------------------------
def test_b5_sentinel_token_is_a_documented_module_level_callable():
    core = foundry._sentinel_token
    assert callable(core)
    assert (core.__doc__ or "").strip(), "the shared rule must be documented"


@pytest.mark.parametrize("text,expected", [
    ("noise\nRESULT: PASS\n\n", "PASS"),
    ("RESULT:PASS", "PASS"),
    ("RESULT: PASS\ntrailing prose\n", None),
    (None, None),
])
def test_b5_sentinel_token_honours_the_anchored_rule(text, expected):
    assert foundry._sentinel_token(text, "RESULT:", ("PASS", "FAIL")) == expected


@pytest.mark.parametrize("parser,prefix,tokens", [
    ("parse_postrelease_verdict", "POSTRELEASE:", ("HEALTHY", "BROKEN")),
    ("parse_review_verdict", "VERDICT:", ("APPROVE", "CHANGES_REQUIRED")),
    ("parse_tester_result", "RESULT:", ("PASS", "FAIL")),
])
def test_b5_each_gate_parser_still_carries_its_own_token_pair(parser, prefix, tokens):
    fn = getattr(foundry, parser)
    for token in tokens:
        assert fn(f"detail line\n{prefix} {token}\n") == token
    assert fn("detail line\nno sentinel at all\n") is None
    assert fn("") is None


def test_b5_the_channels_do_not_bleed_into_each_other():
    """Each parser must reject the OTHER channels' sentinels -- the collapse
    shares the rule, never the prefix/token pair."""
    assert foundry.parse_tester_result("VERDICT: APPROVE\n") is None
    assert foundry.parse_review_verdict("RESULT: PASS\n") is None
    assert foundry.parse_postrelease_verdict("RESULT: PASS\n") is None


def test_b5_ship_parsers_are_untouched():
    assert foundry.parse_ship_action("detail\nACTION: PUSHED deadbee\n") == "PUSHED"
    assert foundry.parse_ship_action("detail\nACTION: REVERTED why\n") == "REVERTED"
    assert foundry.parse_ship_action("detail\nACTION: PENDING\n") is None
    assert foundry.parse_ship_sha("detail\nACTION: PUSHED deadbee\n") == "deadbee"


def test_b5_iteration_201s_golden_matrix_file_is_present_and_owns_that_proof():
    """It re-landed intact, so this file must NOT duplicate its 54-cell matrix."""
    owner = _ROOT / "tests" / "test_iter201_behavior.py"
    assert owner.is_file()
    assert owner.read_text(encoding="utf-8").strip(), "must not be a stub"


# --------------------------------------------------------------------------
# 6. this iteration records itself, keyed to 202
# --------------------------------------------------------------------------
def _roadmaps():
    idx = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    arc = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    return idx, arc


def test_b6_ledger_row_exists_and_is_within_120_chars():
    idx, _ = _roadmaps()
    rows = [ln for ln in idx.splitlines() if ln.startswith("- iter 202 ")]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, len(rows[0])


def test_b6_archive_bullet_exists_for_202():
    _, arc = _roadmaps()
    bullets = [ln for ln in arc.splitlines() if ln.startswith("- **iter 202 ")]
    assert len(bullets) == 1, bullets


def test_b6_status_line_names_202_and_the_never_shipped_exceptions():
    idx, _ = _roadmaps()
    status = [ln for ln in idx.splitlines() if ln.startswith("STATUS (iter ")]
    assert len(status) == 1, status
    assert status[0].startswith("STATUS (iter 202)"), status[0]
    for missing in ("193", "194", "199", "201"):
        assert missing in status[0], (missing, status[0])


def test_b6_the_live_ledger_oracle_is_empty_for_202_and_two_sided():
    """An empty result is only evidence if the SAME oracle still reports a real
    gap: 201 never shipped and owes no row, so claiming it did must flag it."""
    idx, arc = _roadmaps()
    assert foundry.roadmap_ledger_gaps(idx, arc, (202,)) == []
    assert foundry.roadmap_ledger_gaps(idx, arc, (201,)) == [201]


def test_b6_archive_oracle_is_empty_and_the_index_is_within_budget():
    idx, arc = _roadmaps()
    assert foundry.roadmap_archive_gaps(idx, arc) == []
    assert foundry.roadmap_size_verdict(idx).over_budget is False


# --------------------------------------------------------------------------
# 7. both modules still import
# --------------------------------------------------------------------------
def test_b7_both_modules_import():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
