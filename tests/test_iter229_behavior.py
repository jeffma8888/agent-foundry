"""Iteration 229 -- BLACK-BOX behavior tests: the worktree can state the test-touch invariant.

The product ships one pure renderer (`test_touch_line`), one read-only probe seam
(`probe_test_touch`) and one dormant report-only CLI verb (`test-touch`) that answer, from
the WORKTREE and never from git history, whether the iteration currently in flight has
touched a file under a test directory.  Scout A's census found the invariant is 186/186
true for shipped iterations, so the value of the feature is that the repo stops
re-deriving it as prose; the value of THESE tests is that the counting rule, the
fail-SAFE probe and the always-0 exit code are pinned.

Spec under test (products/_platform/state/iter-229/pm.md), Expected Behaviors 1-8:
   1. Clean tree -- empty or whitespace-only porcelain renders EXACTLY the clean line.
   2. A touch renders EXACTLY `test-dir touched -- N of M uncommitted path(s)`, counting
      all three real porcelain shapes (`?? path`, `AM path`, collapsed `?? tests/`).
   3. No touch renders EXACTLY `NO-TEST-TOUCH -- 0 of M uncommitted path(s) are under a
      test dir`.
   4. A rename line contributes BOTH sides; a space-bearing path git double-quotes is
      unquoted before the segment test; two lines naming one path count ONCE.
   5. No path body ever reaches the output -- counts only, and no sentinel token can be
      smuggled through a path.
   6. Total: a `str` for every adversarial input, never an exception.
   7. `probe_test_touch` issues exactly ONE repo-scoped porcelain command through the
      BARE-name `run_cmd` seam with an EXPLICIT `timeout=`; returns `None` (never the
      clean line, never raising) on a not-ok result and on a raising seam.
   8. `test-touch --config` prints EXACTLY ONE `test-touch: ...` line, exits 0 in BOTH
      the known and the unknown case, writes nothing, and is indexed in the README.

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors, and
decidable from TRACKED text alone so every verdict still holds in the fresh clone the
release gate builds (OPERATOR 2026-08-11 -- iteration 154 shipped green and went
post-release BROKEN on a precondition that was only true in this worktree):
   A. This iteration's roadmap record lands in the SAME diff as the code -- exactly one
      `- iter 229 ` ledger row of at most 120 chars, and exactly one `- **iter 229 `
      archive bullet.
   B. This module is on the b15 allow-list in `tests/test_iter204_behavior.py` (the spec
      calls that criterion FORCED, so it is worth an independent assertion here rather
      than trusting the sibling module to be the only witness).
   C. DORMANCY: `dispatcher.py` names neither new symbol, so nothing in the dispatch path
      can reach them.  Asserted by a machine scan of the file's TEXT, not by reading it.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-229 PM spec's Expected
Behaviors and Acceptance Criteria, the conventions of `tests/` (the scripted-seam /
frozen-literal shape of `tests/test_iter198_behavior.py`, which owns the sibling
`worktree_scope_line` / `probe_worktree_scope` pair, plus the config-fixture shape of
`tests/test_iter134_behavior.py` and `tests/test_iter215_behavior.py`), the README, and
the product's OWN OBSERVABLE surface -- importing the modules, calling their public
functions and running the verb.  The implementation TEXT of `foundry.py` was NOT read by
the author; where an acceptance criterion is only decidable from source text (the verb
census of criterion 4, the dormancy scan of C) the text is passed to a PUBLIC oracle or
to a machine scan and never inspected by hand.  `engineer.md`, `reviewer.md`,
`IMPLEMENTATION.patch` and `git diff` were NOT read.

Offline and deterministic: behaviors 1-7 touch no subprocess, git, network, clock or
file; behavior 8 drives `foundry.main` IN-PROCESS over a `tmp_path` config with `run_cmd`
scripted, so no real git runs there either.  No assertion reads a gitignored path, and no
assertion counts files in the ambient `tests/` or `products/` tree.
"""

import io
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 229

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
README = _ROOT / "README.md"
SOURCE = _ROOT / "foundry.py"
DISPATCHER = _ROOT / "dispatcher.py"
ALLOW_LIST_MODULE = _ROOT / "tests" / "test_iter204_behavior.py"

# Names are FIXED by the spec ("the tests and the roadmap record both cite them"), so they
# are reached by string here: a rename in the implementation must fail these tests loudly
# rather than silently stop testing anything.
LINE = "test_touch_line"
PROBE = "probe_test_touch"
DIRS = "TEST_TOUCH_DIR_NAMES"
VERB = "test-touch"

CLEAN = "clean -- 0 uncommitted path(s), so no test-dir touch to report"
UNKNOWN = "test-touch: unknown -- the worktree read did not succeed"

# A relative fixture path -- NEVER an absolute machine path (iteration 205 was reverted
# for exactly one absolute-home literal in a test).
REL_FIXTURE_PATH = "products/_platform/state/iter-229"


def _line(porcelain: str) -> str:
    return getattr(foundry, LINE)(porcelain)


def _probe(repo):
    return getattr(foundry, PROBE)(repo)


def _touched(n: int, m: int) -> str:
    return f"test-dir touched -- {n} of {m} uncommitted path(s)"


def _no_touch(m: int) -> str:
    return f"NO-TEST-TOUCH -- 0 of {m} uncommitted path(s) are under a test dir"


# --------------------------------------------------------------------------- #
# helpers -- scripted seams only, mirroring tests/test_iter198_behavior.py
# --------------------------------------------------------------------------- #
def _install(monkeypatch, *, porcelain="?? tests/test_iter229_behavior.py\n",
             ok=True, raises=False):
    """Script `run_cmd` by BARE module name and record every call's argv and kwargs."""
    calls: list[tuple[list[str], dict]] = []

    def fake_run_cmd(args, *rest, **kw):
        calls.append(([str(a) for a in args], dict(kw)))
        if raises:
            raise RuntimeError("probe-boom-xyz")
        return foundry.CmdResult(ok, porcelain)

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    return calls


def _cfg_file(tmp_path):
    """A minimal on-disk product config, as tests/test_iter215_behavior.py builds one."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "placeholder.txt").write_text("x\n", encoding="utf-8")
    conf = tmp_path / "config.json"
    conf.write_text(
        json.dumps({
            "name": "t",
            "repo": str(repo),
            "allowed_push_repo": "unit-test-repo",
            "work_root": str(tmp_path / "work"),
        }),
        encoding="utf-8",
    )
    return conf, repo


def _capture(fn):
    """Run fn() with stdout captured; return (rc, stdout)."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn()
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


def _listing(root: pathlib.Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# ========================================================================== #
# Behavior 1 -- clean tree
# ========================================================================== #
def test_b1_empty_porcelain_is_exactly_the_clean_line() -> None:
    assert _line("") == CLEAN


@pytest.mark.parametrize("porcelain", ["   ", "\n", "\n\n", " \t \n  \n", "\r\n"])
def test_b1_whitespace_only_porcelain_is_exactly_the_clean_line(porcelain) -> None:
    assert _line(porcelain) == CLEAN


def test_b1_the_clean_line_never_claims_a_touch_or_a_no_touch() -> None:
    """The clean case is its OWN verdict: a 0-path tree has no test-dir question to
    answer, so it must not render as the NO-TEST-TOUCH alarm shape."""
    assert "NO-TEST-TOUCH" not in _line("")
    assert "touched" not in _line("")


# ========================================================================== #
# Behavior 2 -- touch reported with counts, over all three real porcelain shapes
# ========================================================================== #
def test_b2_untracked_test_module_is_a_touch() -> None:
    assert _line("?? tests/test_iter229_behavior.py\n") == _touched(1, 1)


def test_b2_staged_add_plus_unstaged_modification_is_a_touch() -> None:
    """`AM` is the shape `git ls-files -s` misreads as the EMPTY blob (OPERATOR
    2026-08-14); porcelain sees it, so the renderer must count it."""
    assert _line("AM tests/test_iter229_behavior.py\n") == _touched(1, 1)


def test_b2_collapsed_untracked_directory_entry_is_a_touch() -> None:
    """`?? tests/` has ONE segment and that segment IS the dir name."""
    assert _line("?? tests/\n") == _touched(1, 1)


def test_b2_counts_are_n_under_a_test_dir_of_m_distinct_paths() -> None:
    porcelain = (
        "?? tests/test_iter229_behavior.py\n"
        "AM tests/helper.py\n"
        " M foundry.py\n"
        "?? README.md\n"
    )
    assert _line(porcelain) == _touched(2, 4)


def test_b2_every_status_prefix_is_counted_not_just_untracked() -> None:
    porcelain = " M tests/a.py\nM  tests/b.py\nA  tests/c.py\nD  tests/d.py\n"
    assert _line(porcelain) == _touched(4, 4)


def test_b2_blank_lines_are_not_paths() -> None:
    assert _line("\n?? tests/a.py\n\n\n M foundry.py\n\n") == _touched(1, 2)


def test_b2_the_dir_name_tuple_is_read_at_call_time(monkeypatch) -> None:
    """VISION says the framework is repo-agnostic: another product may name the dir
    `spec`.  Patching the module attribute must bite, which it can only do if the tuple
    is read INSIDE the function rather than captured at def-time."""
    assert isinstance(getattr(foundry, DIRS), tuple)
    assert getattr(foundry, DIRS) == ("tests",)
    monkeypatch.setattr(foundry, DIRS, ("spec",))
    assert _line("?? spec/test_a.py\n") == _touched(1, 1)
    assert _line("?? tests/test_a.py\n") == _no_touch(1)


def test_b2_a_test_dir_name_deeper_than_the_first_segment_is_not_a_touch() -> None:
    """The segment test is on the FIRST segment: a `tests` dir nested under some other
    top-level dir is not this iteration's invariant."""
    assert _line("?? docs/tests/a.py\n") == _no_touch(1)


# ========================================================================== #
# Behavior 3 -- no touch reported with counts
# ========================================================================== #
def test_b3_no_test_path_renders_the_no_touch_line_exactly() -> None:
    assert _line(" M foundry.py\n") == _no_touch(1)


def test_b3_m_counts_every_distinct_non_test_path() -> None:
    porcelain = " M foundry.py\n?? README.md\nAM dispatcher.py\n"
    assert _line(porcelain) == _no_touch(3)


def test_b3_a_path_merely_starting_with_the_dir_name_is_not_a_touch() -> None:
    """`tests_helper.py` and `testsuite/x.py` are NOT under `tests/`; a prefix match
    instead of a segment match would report a touch that never happened."""
    assert _line("?? tests_helper.py\n") == _no_touch(1)
    assert _line("?? testsuite/x.py\n") == _no_touch(1)


# ========================================================================== #
# Behavior 4 -- rename, quoting and de-duplication
# ========================================================================== #
def test_b4_a_rename_contributes_both_sides() -> None:
    assert _line("R  old.py -> tests/new.py\n") == _touched(1, 2)


def test_b4_a_rename_into_a_non_test_dir_contributes_two_non_test_paths() -> None:
    assert _line("R  tests/old.py -> lib/new.py\n") == _touched(1, 2)


def test_b4_a_quoted_space_bearing_path_is_unquoted_before_the_segment_test() -> None:
    """git double-quotes a porcelain path containing a space; the leading `"` would make
    the first segment `"tests` and hide the touch."""
    assert _line('?? "tests/a b.py"\n') == _touched(1, 1)


def test_b4_a_quoted_non_test_path_is_still_only_one_path() -> None:
    assert _line('?? "a b.py"\n') == _no_touch(1)


def test_b4_a_rename_may_quote_one_side_only() -> None:
    """Reading behaviors 4's two halves together: git quotes PER SIDE, so a rename whose
    destination needs quoting still has to unquote before the segment test.  Noted as a
    reasonable-reading extension in tester.md, not a spec quote."""
    assert _line('R  old.py -> "tests/a b.py"\n') == _touched(1, 2)


def test_b4_two_lines_naming_the_same_path_count_once() -> None:
    assert _line("M  tests/a.py\n M tests/a.py\n") == _touched(1, 1)


def test_b4_de_duplication_applies_to_the_non_test_side_too() -> None:
    assert _line("M  foundry.py\n M foundry.py\n") == _no_touch(1)


# ========================================================================== #
# Behavior 5 -- no path body ever reaches the output
# ========================================================================== #
def test_b5_no_path_substring_reaches_the_rendered_line() -> None:
    porcelain = "?? not_a_test.py\n?? tests/deep/nested_name.py\n"
    out = _line(porcelain)
    assert out == _touched(1, 2)
    for token in ("not_a_test", "nested_name", "deep"):
        assert token not in out


def test_b5_a_sentinel_token_in_a_path_cannot_reach_the_line() -> None:
    """The final gate parses `ACTION:` and preship parses `PRESHIP:`; a crafted filename
    must not be able to smuggle either token into a report (the constraint
    `worktree_scope_line` documents)."""
    porcelain = "?? tests/ACTION: PUSHED deadbeef.py\n?? PRESHIP: VERIFIED.py\n"
    out = _line(porcelain)
    assert out == _touched(1, 2)
    assert "PRESHIP:" not in out
    assert "ACTION:" not in out


def test_b5_the_line_is_invariant_under_renaming_every_path() -> None:
    """Two porcelains with the same COUNTS and wildly different bodies must render
    identically -- the strongest form of 'counts only'."""
    a = "?? tests/aaa.py\n M zzz.py\n"
    b = '?? "tests/PRESHIP: a b.py"\n M ACTION:-x/y.py\n'
    assert _line(a) == _line(b) == _touched(1, 2)


def test_b5_the_line_is_a_single_line_with_no_newline() -> None:
    for porcelain in ("", " M foundry.py\n", "?? tests/a.py\n?? tests/b.py\n"):
        out = _line(porcelain)
        assert "\n" not in out and "\r" not in out


# ========================================================================== #
# Behavior 6 -- total
# ========================================================================== #
ADVERSARIAL = [
    "",
    "   ",
    "\n\n",
    "?",
    "??",
    "R  -> ",
    " -> ",
    "?? " + "x" * 10_000,
    "x" * 10_000,
    "?? " + REL_FIXTURE_PATH + "/a.py",
    "R  a -> b -> c\n",
    '?? "unterminated\n',
    "\x00\n?? tests/a.py\n",
]


@pytest.mark.parametrize("porcelain", ADVERSARIAL)
def test_b6_is_total_and_returns_a_str_for_every_adversarial_input(porcelain) -> None:
    out = _line(porcelain)
    assert isinstance(out, str)
    assert out


def test_b6_the_adversarial_set_is_non_empty_and_bounded_output(porcelain=None) -> None:
    """A 10,000-char path must not bloat the report: the output is built from counts, so
    its length is tiny for ANY input length."""
    assert len(ADVERSARIAL) >= 6
    assert len(_line("?? " + "x" * 10_000)) < 120


def test_b6_no_adversarial_input_raises() -> None:
    for porcelain in ADVERSARIAL:
        try:
            _line(porcelain)
        except Exception as exc:  # pragma: no cover -- a raise IS the failure
            pytest.fail(f"{LINE}({porcelain!r:.40}) raised {exc!r}")


# ========================================================================== #
# Behavior 7 -- probe seam, fail-SAFE
# ========================================================================== #
def test_b7_probe_issues_exactly_one_repo_scoped_porcelain_command(monkeypatch,
                                                                   tmp_path) -> None:
    calls = _install(monkeypatch)
    repo = tmp_path / "repo"
    _probe(repo)
    assert len(calls) == 1, f"expected exactly ONE command, got {[c[0] for c in calls]}"
    assert calls[0][0] == ["git", "-C", str(repo), "status", "--porcelain"]


def test_b7_the_seam_is_reached_by_bare_module_name(monkeypatch, tmp_path) -> None:
    """If the probe had captured `run_cmd` at def-time, patching the module attribute
    would not intercept it and `calls` would stay empty."""
    calls = _install(monkeypatch)
    _probe(tmp_path / "repo")
    assert calls, "monkeypatching foundry.run_cmd did not intercept the probe"


def test_b7_timeout_is_passed_as_an_explicit_keyword(monkeypatch, tmp_path) -> None:
    """A diagnostic may never outlive the report it annotates, so the bound must be
    explicit -- and a KEYWORD, so a positional shuffle in `run_cmd` cannot silently
    turn it into something else."""
    calls = _install(monkeypatch)
    _probe(tmp_path / "repo")
    kwargs = calls[0][1]
    assert "timeout" in kwargs, f"no explicit timeout= keyword; kwargs={kwargs}"
    assert isinstance(kwargs["timeout"], (int, float)) and kwargs["timeout"] > 0


def test_b7_probe_returns_exactly_what_the_pure_function_returns(monkeypatch,
                                                                tmp_path) -> None:
    porcelain = "?? tests/test_iter229_behavior.py\n M foundry.py\n"
    _install(monkeypatch, porcelain=porcelain)
    assert _probe(tmp_path / "repo") == _line(porcelain) == _touched(1, 2)


def test_b7_a_clean_scripted_tree_reports_the_clean_line(monkeypatch, tmp_path) -> None:
    _install(monkeypatch, porcelain="")
    assert _probe(tmp_path / "repo") == CLEAN


def test_b7_a_not_ok_result_yields_none_and_never_the_clean_line(monkeypatch,
                                                                tmp_path) -> None:
    """Fail-SAFE: a failed read must be UNKNOWN, not a false 'clean' -- the clean line
    would assert something the probe did not observe."""
    _install(monkeypatch, ok=False, porcelain="fatal: not a git repository")
    assert _probe(tmp_path / "repo") is None


def test_b7_a_raising_seam_yields_none_and_does_not_propagate(monkeypatch,
                                                             tmp_path) -> None:
    _install(monkeypatch, raises=True)
    assert _probe(tmp_path / "repo") is None


def test_b7_probe_accepts_a_string_repo_as_well_as_a_path(monkeypatch,
                                                          tmp_path) -> None:
    calls = _install(monkeypatch)
    repo = tmp_path / "repo"
    assert _probe(str(repo)) == _touched(1, 1)
    assert calls[0][0][2] == str(repo)


# ========================================================================== #
# Behavior 8 -- dormant report-only verb
# ========================================================================== #
def test_b8_verb_prints_exactly_one_line_and_exits_zero(monkeypatch, tmp_path) -> None:
    _install(monkeypatch, porcelain="?? tests/test_iter229_behavior.py\n M foundry.py\n")
    conf, _ = _cfg_file(tmp_path)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 0
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines == [f"{VERB}: {_touched(1, 2)}"], out


def test_b8_a_clean_tree_still_exits_zero(monkeypatch, tmp_path) -> None:
    _install(monkeypatch, porcelain="")
    conf, _ = _cfg_file(tmp_path)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 0
    assert out.strip() == f"{VERB}: {CLEAN}"


def test_b8_an_unknown_read_prints_the_unknown_line_and_still_exits_zero(monkeypatch,
                                                                        tmp_path) -> None:
    """Report-only, never a brake: the failure case is a WORD, not an exit code."""
    _install(monkeypatch, ok=False, porcelain="fatal: not a git repository")
    conf, _ = _cfg_file(tmp_path)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 0
    assert out.strip() == UNKNOWN


def test_b8_a_raising_seam_also_prints_unknown_and_exits_zero(monkeypatch,
                                                             tmp_path) -> None:
    _install(monkeypatch, raises=True)
    conf, _ = _cfg_file(tmp_path)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 0
    assert out.strip() == UNKNOWN


def test_b8_the_verb_writes_nothing_into_the_repo_it_reads(monkeypatch,
                                                           tmp_path) -> None:
    """The spec's claim is about THE REPO: a read-only probe may not leave a byte in the
    tree it measured."""
    _install(monkeypatch)
    conf, repo = _cfg_file(tmp_path)
    before = _listing(repo)
    rc, _ = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 0
    assert _listing(repo) == before == ["placeholder.txt"]


def test_b8_the_verb_adds_no_write_of_its_own_beyond_the_config_load(monkeypatch,
                                                                    tmp_path) -> None:
    """Two-sided control.  Loading a `--config` scaffolds `work/state` for EVERY verb
    that takes one, so a bare 'nothing was created anywhere' assertion would fail on
    ambient behaviour rather than on this feature.  The honest test is that the new
    verb's filesystem delta is IDENTICAL to an existing read-only verb's -- measured
    here, not assumed (`recoverable` was confirmed to produce the same two entries)."""
    calls = _install(monkeypatch)

    def delta(argv, root):
        conf, _ = _cfg_file(root)
        before = _listing(root)
        try:
            _capture(lambda: foundry.main(argv + ["--config", str(conf)]))
        except SystemExit:  # pragma: no cover -- argparse-level exit, not a write
            pass
        return sorted(set(_listing(root)) - set(before))

    mine = delta([VERB], tmp_path / "mine")
    control = delta(["recoverable"], tmp_path / "control")
    assert mine == control, f"new verb wrote {sorted(set(mine) - set(control))}"
    assert calls, "the probe seam was never reached, so the delta proves nothing"


def test_b8_no_path_body_survives_the_cli_either(monkeypatch, tmp_path) -> None:
    _install(monkeypatch,
             porcelain='?? "tests/PRESHIP: a b.py"\n?? ACTION:-secret_name.py\n')
    conf, _ = _cfg_file(tmp_path)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 0
    assert out.strip() == f"{VERB}: {_touched(1, 2)}"
    for token in ("PRESHIP:", "ACTION:", "secret_name"):
        assert token not in out


def test_b8_the_verb_is_registered_and_indexed_in_the_readme() -> None:
    """The verb census and the README index are PUBLIC oracles; the source text is handed
    to them, never read by this author (isolation)."""
    verbs = foundry.foundry_cli_verbs(SOURCE.read_text(encoding="utf-8"))
    assert VERB in verbs, f"{VERB} is not a registered subcommand"
    gaps = foundry.readme_verb_index_gaps(README.read_text(encoding="utf-8"), verbs)
    assert not getattr(gaps, "missing_verbs", ()), gaps
    assert gaps.ok is True, gaps


def test_b8_the_readme_invocation_form_is_the_uv_run_python_one() -> None:
    """Iteration 142's rule: there is no bare `foundry` on PATH, so a copyable
    invocation must go through `uv run python foundry.py`."""
    text = README.read_text(encoding="utf-8")
    assert f"uv run python foundry.py {VERB} --config" in text


# ========================================================================== #
# Acceptance criteria A / B / C -- decidable from TRACKED text alone
# ========================================================================== #
def test_aA_this_iterations_roadmap_record_lands_in_the_same_diff() -> None:
    index = ROADMAP.read_text(encoding="utf-8")
    rows = [ln for ln in index.splitlines() if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, f"{len(rows[0])} chars > 120: {rows[0]}"
    archive = ARCHIVE.read_text(encoding="utf-8")
    bullets = [ln for ln in archive.splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, bullets


def test_aA_the_ledger_brake_is_satisfied_by_the_shipping_tree() -> None:
    gaps = foundry.roadmap_ledger_gaps(ROADMAP.read_text(encoding="utf-8"),
                                       ARCHIVE.read_text(encoding="utf-8"),
                                       (THIS_ITER,))
    assert gaps == [], gaps


def test_aB_this_module_is_on_the_b15_allow_list() -> None:
    """The spec calls this criterion FORCED; assert it independently rather than trusting
    the sibling module to be the only witness."""
    text = ALLOW_LIST_MODULE.read_text(encoding="utf-8")
    assert "tests/test_iter229_behavior.py" in text


def test_aC_the_feature_is_dormant_in_the_dispatch_path() -> None:
    """Machine scan, not a reading: the dispatcher must not name either new symbol."""
    text = DISPATCHER.read_text(encoding="utf-8")
    assert LINE not in text
    assert PROBE not in text


def test_aC_both_modules_still_import() -> None:
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
