"""Iteration 363 -- BLACK-BOX behavior tests.

One module-level `gather_attempt_records` walks the attempt logs ONCE, and both
`gather_losses` and `gather_auth_recency` become thin callers that differ only in
which verdict function they hand the records to.

ISOLATION: written from the PM spec (`pm.md` in this iteration's state dir) plus the
repo's own `tests/` conventions, the roadmap files and the product's OWN OUTPUT by
running it.  No implementation source, no `git diff`, no engineer/reviewer/fix notes
were read.  Every assertion drives the public interface and grades observable output.

Expected Behaviors, numbered as the spec numbers them:
   1. `gather_attempt_records(cfg, limit=None)` exists at module level and returns a
      `tuple` of `(stage, iteration, attempt, produced, kind)` 5-tuples, ascending by
      sorted glob order.
   2. A filename that does not match the attempt-log pattern, and a parent dir whose
      name holds no iteration number, are both SKIPPED -- never guessed at.
   3. `gather_losses(cfg, limit)` == `attempt_loss_summary(product=cfg.name,
      records=gather_attempt_records(cfg, limit))` for limit in (None, 1, 0, -3).
   4. `gather_auth_recency(cfg, limit)` == `auth_recency_verdict(
      gather_attempt_records(cfg, limit))` for the same limits, and the window
      behaves identically for both readers.
   5. Seam visibility survives the extraction: the five collaborators are read by
      BARE NAME at call time, so both readers see a reshaped kind.
   6. The no-news contract is unchanged and TOTAL: missing state dir, unreadable
      state dir and invalid UTF-8 all degrade instead of raising.
   7. The duplication is measurably gone, and ONLY where scoped.
   8. Control path unmoved, so a loop in flight resumes byte-identically.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import pathlib
import re
import subprocess
import sys
import textwrap

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 363

FOUNDRY_SRC = _ROOT / "foundry.py"
DISPATCHER_SRC = _ROOT / "dispatcher.py"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

# A RELATIVE literal: an absolute machine path in a shipped test is a leak-guard
# finding (OPERATOR 2026-08-30, which reverted iteration 205 over exactly this shape).
REL_REPO = "products/_platform/state/iter-363"

# Names are FIXED by the spec's vocabulary, so they are reached by STRING: a rename
# must fail loudly rather than silently stop testing anything.
GATHER = "gather_attempt_records"
LOSSES = "gather_losses"
RECENCY = "gather_auth_recency"
LOSS_VERDICT = "attempt_loss_summary"
RECENCY_VERDICT = "auth_recency_verdict"
RESCUES = "gather_rescues"
RECOVERABLE = "gather_recoverable"

# The five collaborators the shared walk must read by bare name at call time.
COLLABORATORS = ("ATTEMPT_LOG_GLOB", "_ATTEMPT_LOG_RE", "iteration_numbers",
                 "_stage_output_present", "classify_attempt_failure")

CONTROL_FNS = ("run_stage", "run_iteration", "build_prompt", "postrelease_step",
               "run_continuous")


def _cfg(**over):
    kw = dict(name="demo", repo=REL_REPO, allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _fn(name):
    fn = getattr(foundry, name, None)
    assert callable(fn), f"{name} must exist at module level in foundry.py"
    return fn


def _records(cfg, *a, **kw):
    return _fn(GATHER)(cfg, *a, **kw)


def _fabricate(tmp_path, tree):
    """Build a state dir the REAL reader walks.  `tree` maps relpath -> text."""
    cfg = _cfg(work_root=str(tmp_path))
    state = pathlib.Path(cfg.state)
    for rel, text in tree.items():
        p = state / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return cfg


TWO = {"iter-7/engineer.attempt1.log": "connection stalled\n",
       "iter-8/tester.attempt2.log": "auth failed\n"}


# ========================================================================== #
# Behavior 1 -- the shared record-builder exists and returns 5-tuples
# ========================================================================== #
def test_b1_the_shared_builder_exists_at_module_level() -> None:
    fn = _fn(GATHER)
    assert getattr(fn, "__qualname__", "") == GATHER, \
        f"{GATHER} must be a MODULE-LEVEL def, not nested: {fn}"
    assert getattr(fn, "__module__", "") == "foundry", fn


def test_b1_two_logs_yield_exactly_two_records_in_sorted_glob_order(tmp_path) -> None:
    cfg = _fabricate(tmp_path, TWO)
    recs = _records(cfg)
    assert isinstance(recs, tuple), f"the contract is a tuple, got {type(recs)}"
    assert len(recs) == 2, recs
    for r in recs:
        assert isinstance(r, tuple) and len(r) == 5, f"5-tuple contract: {r!r}"
    stages = [r[0] for r in recs]
    iters = [r[1] for r in recs]
    attempts = [r[2] for r in recs]
    assert stages == ["engineer", "tester"], recs
    assert iters == [7, 8], f"ascending by sorted glob order: {recs}"
    assert attempts == [1, 2], recs
    for r in recs:
        assert isinstance(r[3], bool), f"produced must be a bool: {r!r}"
        assert isinstance(r[4], str) and r[4], f"kind must be a non-empty str: {r!r}"


def test_b1_produced_reflects_the_stage_output_file(tmp_path) -> None:
    """`produced` is the output-file success signal, not a guess about the log."""
    cfg = _fabricate(tmp_path, TWO)
    assert [r[3] for r in _records(cfg)] == [False, False]
    (pathlib.Path(cfg.state) / "iter-8" / "tester.md").write_text("out\n", encoding="utf-8")
    assert [r[3] for r in _records(cfg)] == [False, True], _records(cfg)


# ========================================================================== #
# Behavior 2 -- unmatched names and unnumbered parents are SKIPPED
# ========================================================================== #
NOISE = {"iter-8/notes.txt": "not a log\n",
         "iter-8/engineer.log": "no attempt token\n",
         "iter-8/pm.attempt.log": "an attempt with NO number\n",
         "iter-8/pm.attemptX.log": "a non-numeric attempt\n",
         "scratch/engineer.attempt1.log": "a parent that is not an iteration\n",
         "iter-none/engineer.attempt1.log": "a parent holding no number\n"}


def test_b2_noise_never_changes_the_record_set(tmp_path) -> None:
    cfg = _fabricate(tmp_path, TWO)
    before = _records(cfg)
    assert len(before) == 2, before
    for rel, text in NOISE.items():
        p = pathlib.Path(cfg.state) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    assert _records(cfg) == before, \
        f"noise was guessed at instead of skipped: {_records(cfg)} vs {before}"


def test_b2_the_skip_test_is_not_vacuous(tmp_path) -> None:
    """DISCRIMINATION: a REAL third log does move the count, so the guard above
    is measuring a skip rather than a reader that never reads anything."""
    cfg = _fabricate(tmp_path, TWO)
    p = pathlib.Path(cfg.state) / "iter-9" / "reviewer.attempt1.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("real log\n", encoding="utf-8")
    recs = _records(cfg)
    assert len(recs) == 3 and recs[-1][:3] == ("reviewer", 9, 1), recs


# ========================================================================== #
# Behaviors 3 + 4 -- both readers ARE the composition over the shared walk
# ========================================================================== #
LIMITS = (None, 1, 0, -3)

# iteration -> (stage, attempt, log text, wrote_output)
THREE = {"iter-5/pm.attempt1.log": "auth failed\n",
         "iter-6/engineer.attempt1.log": "connection stalled\n",
         "iter-7/tester.attempt3.log": "nothing notable\n"}


def _three(tmp_path):
    cfg = _fabricate(tmp_path, THREE)
    (pathlib.Path(cfg.state) / "iter-7" / "tester.md").write_text("out\n", encoding="utf-8")
    return cfg


@pytest.mark.parametrize("limit", LIMITS)
def test_b3_gather_losses_is_exactly_the_documented_composition(tmp_path, limit) -> None:
    cfg = _three(tmp_path)
    expected = _fn(LOSS_VERDICT)(product=cfg.name, records=_records(cfg, limit))
    assert _fn(LOSSES)(cfg, limit) == expected, \
        f"gather_losses(cfg, {limit!r}) is no longer the verdict over the shared walk"


@pytest.mark.parametrize("limit", LIMITS)
def test_b4_gather_auth_recency_is_exactly_the_documented_composition(tmp_path, limit) -> None:
    cfg = _three(tmp_path)
    expected = _fn(RECENCY_VERDICT)(_records(cfg, limit))
    assert _fn(RECENCY)(cfg, limit) == expected, \
        f"gather_auth_recency(cfg, {limit!r}) is no longer the verdict over the walk"


def test_b34_the_composition_equality_is_not_between_two_empties(tmp_path) -> None:
    """DISCRIMINATION: the parametrized equalities above are over a NON-TRIVIAL
    corpus, and the limit really reaches the walk."""
    cfg = _three(tmp_path)
    assert len(_records(cfg, None)) == 3 and len(_records(cfg, 1)) == 1
    wide, narrow = _fn(LOSSES)(cfg, None), _fn(LOSSES)(cfg, 1)
    assert wide.rows and wide != narrow, (wide, narrow)
    assert _fn(RECENCY)(cfg, None) != _fn(RECENCY)(cfg, 1), "the window is ignored"


def test_b4_a_positive_limit_keeps_the_newest_iterations_only(tmp_path) -> None:
    cfg = _three(tmp_path)
    assert [r[1] for r in _records(cfg, 1)] == [7]
    assert [r[1] for r in _records(cfg, 2)] == [6, 7]
    assert [r[1] for r in _records(cfg, 3)] == [5, 6, 7]
    assert [r[1] for r in _records(cfg, 99)] == [5, 6, 7]


@pytest.mark.parametrize("limit", [None, 0, -3])
def test_b4_a_none_or_non_positive_limit_scans_everything(tmp_path, limit) -> None:
    cfg = _three(tmp_path)
    assert _records(cfg, limit) == _records(cfg, None), \
        f"limit={limit!r} must scan the whole tree, not a slice"


def test_b4_the_window_is_identical_for_both_readers(tmp_path) -> None:
    cfg = _three(tmp_path)
    AuthRecency = getattr(foundry, "AuthRecency")
    assert _fn(RECENCY)(cfg, 1) == AuthRecency(7, None), "newest iteration only"
    assert _fn(RECENCY)(cfg, None) == AuthRecency(7, 5)
    assert _fn(LOSSES)(cfg, 1).attempts == 1
    assert _fn(LOSSES)(cfg, None).attempts == 3


# ========================================================================== #
# Behavior 5 -- seam visibility survives the extraction
# ========================================================================== #
LOUD = {"iter-5/pm.attempt1.log": "auth failed\n",
        "iter-6/engineer.attempt1.log": "auth failed\n"}
QUIET = {"iter-5/pm.attempt1.log": "nothing notable\n",
         "iter-6/engineer.attempt1.log": "nothing notable\n"}
FABRICATED_KIND = "fabricated-kind"


def test_b5_a_reshaped_kind_reaches_BOTH_readers(tmp_path, monkeypatch) -> None:
    """The classifier is read by BARE NAME at call time, from ONE shared walk."""
    cfg = _fabricate(tmp_path, QUIET)
    auth = getattr(foundry, "AUTH_LOSS_KIND")
    monkeypatch.setattr(foundry, "classify_attempt_failure", lambda blob: auth)
    assert {r[4] for r in _records(cfg)} == {auth}, _records(cfg)
    assert {r.kind for r in _fn(LOSSES)(cfg).rows} == {auth}, _fn(LOSSES)(cfg).rows
    assert _fn(RECENCY)(cfg) == getattr(foundry, "AuthRecency")(6, 6), _fn(RECENCY)(cfg)


def test_b5_the_reshape_also_works_in_the_OTHER_direction(tmp_path, monkeypatch) -> None:
    """A def-time capture would leave an auth-worded corpus reading as auth."""
    cfg = _fabricate(tmp_path, LOUD)
    auth = getattr(foundry, "AUTH_LOSS_KIND")
    assert _fn(RECENCY)(cfg).newest_loss == 6, "precondition: the real text IS auth"
    monkeypatch.setattr(foundry, "classify_attempt_failure", lambda blob: FABRICATED_KIND)
    assert {r[4] for r in _records(cfg)} == {FABRICATED_KIND}, _records(cfg)
    assert {r.kind for r in _fn(LOSSES)(cfg).rows} == {FABRICATED_KIND}
    assert auth not in {r.kind for r in _fn(LOSSES)(cfg).rows}
    assert _fn(RECENCY)(cfg).newest_loss is None, _fn(RECENCY)(cfg)


def test_b5_all_five_collaborators_are_named_at_module_level() -> None:
    for name in COLLABORATORS:
        assert hasattr(foundry, name), f"{name} must stay a module-level seam"


def test_b5_the_glob_seam_is_read_at_call_time(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, LOUD)
    assert _records(cfg), "precondition"
    monkeypatch.setattr(foundry, "ATTEMPT_LOG_GLOB", "no-such-dir-*/*.attempt*.log")
    assert _records(cfg) == (), "the glob constant is captured at def time"
    assert _fn(LOSSES)(cfg).exit_code == 2, "both readers share the ONE walk"
    assert _fn(RECENCY)(cfg) == getattr(foundry, "AuthRecency")(None, None)


def test_b5_the_filename_regex_seam_is_read_at_call_time(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, LOUD)
    monkeypatch.setattr(foundry, "_ATTEMPT_LOG_RE", re.compile(r"(?!)"))
    assert _records(cfg) == (), "the filename regex is captured at def time"
    assert _fn(LOSSES)(cfg).exit_code == 2
    assert _fn(RECENCY)(cfg) == getattr(foundry, "AuthRecency")(None, None)


def test_b5_the_iteration_number_seam_is_read_at_call_time(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, LOUD)
    assert len(_records(cfg, 1)) == 1, "precondition: a positive limit windows"
    monkeypatch.setattr(foundry, "iteration_numbers", lambda names: [])
    assert _records(cfg, 1) == (), "the window helper is captured at def time"


def test_b5_the_output_presence_seam_is_read_at_call_time(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, LOUD)
    assert [r[3] for r in _records(cfg)] == [False, False], "precondition"
    monkeypatch.setattr(foundry, "_stage_output_present", lambda *a, **k: True)
    assert [r[3] for r in _records(cfg)] == [True, True]
    assert not _fn(LOSSES)(cfg).rows, "a produced attempt is not a loss"
    monkeypatch.setattr(foundry, "_stage_output_present", lambda *a, **k: False)
    assert [r[3] for r in _records(cfg)] == [False, False]


# ========================================================================== #
# Behavior 6 -- the no-news contract is unchanged and TOTAL
# ========================================================================== #
def test_b6_a_missing_state_dir_is_no_news_from_all_three(tmp_path) -> None:
    cfg = _cfg(work_root=str(tmp_path))
    assert not pathlib.Path(cfg.state).exists(), "precondition"
    assert _records(cfg) == ()
    assert _fn(LOSSES)(cfg).exit_code == 2
    assert _fn(RECENCY)(cfg) == getattr(foundry, "AuthRecency")(None, None)


def test_b6_an_unreadable_state_path_degrades_instead_of_raising(tmp_path) -> None:
    """The OSError fallback: `state` is a FILE, so the walk itself fails."""
    cfg = _cfg(work_root=str(tmp_path))
    p = pathlib.Path(cfg.state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not a directory\n", encoding="utf-8")
    assert _records(cfg) == ()
    assert _fn(LOSSES)(cfg).exit_code == 2
    assert _fn(RECENCY)(cfg) == getattr(foundry, "AuthRecency")(None, None)


def test_b6_an_undecodable_log_still_yields_a_default_kind_record(tmp_path) -> None:
    cfg = _fabricate(tmp_path, TWO)
    bad = pathlib.Path(cfg.state) / "iter-9" / "pm.attempt1.log"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"\xff\xfe\x00 undecodable \x80\n")
    recs = _records(cfg)
    assert len(recs) == 3, recs
    assert recs[-1][:3] == ("pm", 9, 1), recs
    assert recs[-1][4] == getattr(foundry, "ATTEMPT_FAILURE_DEFAULT"), recs[-1]
    assert _fn(LOSSES)(cfg).attempts == 3
    assert _fn(RECENCY)(cfg).newest_scanned == 9


# ========================================================================== #
# Behavior 7 -- the duplication is measurably gone, and only where scoped
# ========================================================================== #
def _src(name) -> str:
    return inspect.getsource(_fn(name))


def _returns(name) -> int:
    tree = ast.parse(textwrap.dedent(_src(name)))
    return sum(isinstance(n, ast.Return) for n in ast.walk(tree))


@pytest.mark.parametrize("caller", [LOSSES, RECENCY])
def test_b7_neither_thin_caller_still_names_the_filename_regex(caller) -> None:
    assert "_ATTEMPT_LOG_RE" not in _src(caller), \
        f"{caller} still carries its own copy of the attempt-log walk"


@pytest.mark.parametrize("caller", [LOSSES, RECENCY])
def test_b7_each_thin_caller_is_one_return_over_the_shared_walk(caller) -> None:
    src = _src(caller)
    assert _returns(caller) == 1, f"{caller} must be a docstring plus ONE return"
    assert src.count(GATHER + "(") == 1, \
        f"{caller} must compose the shared walk exactly once"


def test_b7_the_regex_call_site_count_is_exactly_one() -> None:
    src = FOUNDRY_SRC.read_text(encoding="utf-8")
    n = len(re.findall(r"_ATTEMPT_LOG_RE\.match\(", src))
    assert n == 1, f"expected 1 attempt-log walk (shared walk only), found {n}"


def test_b7_the_third_walker_is_folded(tmp_path) -> None:
    """`gather_rescues` no longer walks on its own (the later bite: iteration 380).

    It consumes the shared generator, NOT the records tuple -- its lens needs the raw
    text, which `gather_attempt_records` has already classified away."""
    assert "_ATTEMPT_LOG_RE" not in _src(RESCUES), \
        f"{RESCUES} still carries its own copy of the attempt-log walk"
    assert GATHER + "(" not in _src(RESCUES), f"{RESCUES} must stay independent"
    cfg = _three(tmp_path)
    assert _fn(RESCUES)(cfg) is not None


def test_b7_the_out_of_scope_fourth_window_copy_is_untouched(tmp_path) -> None:
    assert GATHER + "(" not in _src(RECOVERABLE), f"{RECOVERABLE} is out of scope"
    assert "iteration_numbers" in _src(RECOVERABLE), \
        f"{RECOVERABLE} kept its own limit window"
    cfg = _three(tmp_path)
    assert _fn(RECOVERABLE)(cfg) is not None


def test_b7_the_defended_fork_still_exists_unmerged() -> None:
    """Out of scope by name: a duplication whose docstring defends it."""
    for name in ("_report_unreadable_config", "_report_unreadable_scout_config"):
        assert hasattr(foundry, name), f"{name} must NOT have been collapsed"


# ========================================================================== #
# Behavior 8 -- control path unmoved, so a loop in flight resumes identically
# ========================================================================== #
@pytest.mark.parametrize("fn", CONTROL_FNS)
def test_b8_no_control_function_names_the_new_walk(fn) -> None:
    assert GATHER not in _src(fn), \
        f"{fn} composes {GATHER}; a running loop's resume semantics moved"


def test_b8_the_dispatcher_never_names_the_new_walk() -> None:
    assert GATHER not in DISPATCHER_SRC.read_text(encoding="utf-8")


@pytest.mark.parametrize("mod", ["foundry", "dispatcher"])
def test_b8_both_modules_import_from_a_clean_interpreter(mod) -> None:
    p = subprocess.run([sys.executable, "-c", f"import {mod}"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert p.returncode == 0, f"import {mod} failed: {p.stderr[-400:]}"


def test_b8_the_shared_walk_is_reachable_only_from_the_two_thin_callers() -> None:
    src = FOUNDRY_SRC.read_text(encoding="utf-8")
    n = len(re.findall(rf"(?<!def ){GATHER}\(", src))
    assert n == 2, f"{GATHER} has {n} call sites in foundry.py, expected 2"


# ========================================================================== #
# Acceptance criteria reachable black-box: the CLI surface is unchanged
# ========================================================================== #
LOSSES_JSON_KEYS = ["attempts", "exit_code", "kinds", "lost", "product", "rows", "verdict"]
LOSSES_ROW_KEYS = ["kind", "lost", "stages"]


def test_ac_the_losses_json_payload_keys_are_unchanged(tmp_path) -> None:
    cfg = _three(tmp_path)
    conf = tmp_path / "cfg.json"
    conf.write_text(json.dumps({"name": cfg.name, "repo": str(tmp_path),
                                "allowed_push_repo": cfg.name,
                                "work_root": str(tmp_path)}), encoding="utf-8")
    p = subprocess.run([sys.executable, str(FOUNDRY_SRC), "losses",
                        "--config", str(conf), "--json"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert "Traceback" not in p.stderr, p.stderr[-400:]
    payload = json.loads(p.stdout)
    assert sorted(payload) == LOSSES_JSON_KEYS, sorted(payload)
    assert payload["rows"] and sorted(payload["rows"][0]) == LOSSES_ROW_KEYS
    assert payload["attempts"] == 3 and payload["exit_code"] == p.returncode


def test_ac_the_two_doctor_lines_still_render_over_the_shared_walk(tmp_path) -> None:
    cfg = _three(tmp_path)
    auth = foundry.auth_loss_line(cfg)
    assert auth.startswith(getattr(foundry, "AUTH_LOSS_PREFIX")), auth
    budget = foundry.stage_budget_line(cfg)
    assert budget.startswith(getattr(foundry, "STAGE_BUDGET_PREFIX")), budget


def test_ac_the_loss_summary_shape_is_unchanged() -> None:
    summary = getattr(foundry, "LossSummary")
    assert dataclasses.is_dataclass(summary)
    assert [f.name for f in dataclasses.fields(summary)] == ["product", "rows", "attempts"]
    assert [f.name for f in dataclasses.fields(getattr(foundry, "LossRow"))] == \
        ["kind", "lost", "stages"]


# ========================================================================== #
# Records -- decidable from git-TRACKED text alone (OPERATOR 2026-08-11)
# ========================================================================== #
def test_records_this_iteration_owes_no_ledger_row_or_archive_bullet() -> None:
    idx, arc = ROADMAP.read_text(encoding="utf-8"), ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(idx, arc, (THIS_ITER,)) == [], \
        f"iteration {THIS_ITER} owes a ledger row and an archive bullet"
    rows = [ln for ln in idx.splitlines() if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1 and len(rows[0]) <= 120, [len(r) for r in rows] or rows
    bullets = [ln for ln in arc.splitlines() if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, len(bullets)


# ========================================================================== #
# RETRY ROUND -- gaps the first (cap-killed) round could not see.  Every fixture
# below is built in `tmp_path`; nothing asserts against the ambient repo state.
# ========================================================================== #

# Double-digit iteration dirs: `iter-10` sorts BEFORE `iter-9` lexically, so this
# corpus is the one that tells a lexical walk from a numeric window.  The first
# round's fixtures were all single-digit, where the two are indistinguishable.
DOUBLE = {"iter-2/tester.attempt1.log": "auth failed\n",
          "iter-9/pm.attempt1.log": "auth failed\n",
          "iter-10/engineer.attempt1.log": "auth failed\n"}


def _relpaths(recs):
    return [f"iter-{r[1]}/{r[0]}.attempt{r[2]}.log" for r in recs]


def test_b1_the_record_order_is_the_SORTED_GLOB_order(tmp_path) -> None:
    """Behavior 1 says "ascending by the sorted glob order".  AMBIGUITY NOTED as
    PM feedback: for `iter-10` vs `iter-9` that order is LEXICAL, not numeric, so
    the records are NOT in ascending iteration order once a product passes iter-9.
    Pinned to the order derived from the FIXTURE (never a magic literal) because
    both readers now share this one walk, so both inherit whatever it decides."""
    cfg = _fabricate(tmp_path, DOUBLE)
    assert _relpaths(_records(cfg)) == sorted(DOUBLE), _records(cfg)


def test_b1_two_consecutive_walks_are_identical(tmp_path) -> None:
    """A shared walk feeding two readers must be deterministic, or behaviors 3
    and 4 would only hold by luck."""
    cfg = _three(tmp_path)
    assert _records(cfg) == _records(cfg)


def test_b4_the_window_keeps_the_NUMERICALLY_newest_iterations(tmp_path) -> None:
    """Behavior 4: a positive limit keeps the NEWEST `limit` iteration dirs.  With
    a lexical walk order, a slice-off-the-end implementation would keep iter-9."""
    cfg = _fabricate(tmp_path, DOUBLE)
    assert sorted(r[1] for r in _records(cfg, 1)) == [10], _records(cfg, 1)
    assert sorted(r[1] for r in _records(cfg, 2)) == [9, 10], _records(cfg, 2)
    assert sorted(r[1] for r in _records(cfg, 3)) == [2, 9, 10], _records(cfg, 3)


def test_b4_both_verdicts_read_the_numeric_newest_despite_lexical_order(tmp_path) -> None:
    AuthRecency = getattr(foundry, "AuthRecency")
    cfg = _fabricate(tmp_path, DOUBLE)
    assert _fn(RECENCY)(cfg) == AuthRecency(10, 10), _fn(RECENCY)(cfg)
    assert _fn(RECENCY)(cfg, 1) == AuthRecency(10, 10)
    assert _fn(LOSSES)(cfg, 1).attempts == 1
    assert _fn(LOSSES)(cfg, None).attempts == 3


def test_b6_a_directory_named_like_a_log_degrades_instead_of_raising(tmp_path) -> None:
    """Behavior 6 calls the no-news contract TOTAL: a path that MATCHES the log
    name but cannot be read as a file must still yield a record with the default
    kind, and must not raise out of any of the three entry points."""
    cfg = _fabricate(tmp_path, {"iter-5/tester.attempt1.log": "auth failed\n"})
    (pathlib.Path(cfg.state) / "iter-4" / "pm.attempt1.log").mkdir(parents=True)
    recs = _records(cfg)
    kinds = {r[:3]: r[4] for r in recs}
    assert ("pm", 4, 1) in kinds, recs
    assert kinds[("pm", 4, 1)] == getattr(foundry, "ATTEMPT_FAILURE_DEFAULT"), recs
    assert _fn(LOSSES)(cfg).attempts == 2, _fn(LOSSES)(cfg)
    assert _fn(RECENCY)(cfg) == getattr(foundry, "AuthRecency")(5, 5)


def test_b8_all_three_readers_leave_the_state_tree_byte_identical(tmp_path) -> None:
    """Resume safety: the collapsed walk is a pure READER, so a loop in flight
    cannot be perturbed by anyone reading its attempt logs."""
    cfg = _three(tmp_path)
    state = pathlib.Path(cfg.state)

    def snap():
        return sorted((str(q.relative_to(state)), q.is_dir(),
                       q.stat().st_size if q.is_file() else -1)
                      for q in state.rglob("*"))

    before = snap()
    assert before, "precondition: the fixture is non-empty"
    _records(cfg)
    _fn(LOSSES)(cfg)
    _fn(RECENCY)(cfg)
    assert snap() == before, "a reader wrote to the state tree"


@pytest.mark.parametrize("name", [GATHER, LOSSES, RECENCY])
def test_b8_the_three_doors_share_one_call_signature(name) -> None:
    """Behavior 8 keeps existing call sites working: every door stays
    `(cfg, limit=None)`, so `f(cfg)` and `f(cfg, n)` both remain valid."""
    params = list(inspect.signature(_fn(name)).parameters.items())
    assert [n for n, _ in params] == ["cfg", "limit"], params
    assert params[1][1].default is None, params


# Every name the Acceptance Criteria freeze as BYTE-UNTOUCHED.  A test in an
# isolated stage may not read `git diff`, so this grades the weaker but decidable
# property: none of them was removed, renamed or folded into the collapse.
FROZEN = (LOSS_VERDICT, RECENCY_VERDICT, "_loss_fields", "LossRow", "LossSummary",
          "AuthRecency", "classify_attempt_failure", RESCUES, RECOVERABLE)


@pytest.mark.parametrize("name", FROZEN)
def test_ac_every_frozen_name_still_exists_at_module_level(name) -> None:
    assert hasattr(foundry, name), f"{name} is frozen by the spec, not removable"


def test_ac_the_doctor_verb_still_renders_both_lines_with_no_traceback(tmp_path) -> None:
    """Acceptance criterion, driven through the CLI rather than in-process, and
    cross-checked against the public line builders so the wording is never
    guessed at.  The config is built in `tmp_path`: the real product's state dir
    is gitignored, so asserting on it would pass only on this machine."""
    cfg = _three(tmp_path)
    conf = tmp_path / "doctor-cfg.json"
    conf.write_text(json.dumps({"name": cfg.name, "repo": REL_REPO,
                                "allowed_push_repo": cfg.name,
                                "work_root": str(tmp_path)}), encoding="utf-8")
    p = subprocess.run([sys.executable, str(FOUNDRY_SRC), "doctor", "--config", str(conf)],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert "Traceback" not in (p.stdout + p.stderr), (p.stdout + p.stderr)[-500:]
    auth = [ln for ln in p.stdout.splitlines()
            if ln.startswith(getattr(foundry, "AUTH_LOSS_PREFIX"))]
    budget = [ln for ln in p.stdout.splitlines()
              if ln.startswith(getattr(foundry, "STAGE_BUDGET_PREFIX"))]
    assert len(auth) == 1 and len(budget) == 1, (auth, budget)
    # The CLI renders the line under `doctor`'s own most-recent-iterations window,
    # so its PROSE carries one clause the unwindowed in-process builder omits.
    # Graded on SUBSTANCE instead: the same verdict token and the same two
    # iteration numbers, both derived from the public verdict over the shared walk.
    rec = _fn(RECENCY)(cfg)
    assert f"iteration {rec.newest_loss}" in auth[0], (auth[0], rec)
    assert f"iteration {rec.newest_scanned}" in auth[0], (auth[0], rec)
    prefix = getattr(foundry, "AUTH_LOSS_PREFIX")

    def _verdict(line):
        return line[len(prefix):].split()[0]

    assert _verdict(auth[0]) == _verdict(foundry.auth_loss_line(cfg)), \
        (auth[0], foundry.auth_loss_line(cfg))


@pytest.mark.parametrize("older", [362, 361, 360, 339, 228, 195])
def test_records_no_older_record_was_evicted(older) -> None:
    idx, arc = ROADMAP.read_text(encoding="utf-8"), ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(idx, arc, (older,)) == [], \
        f"iteration {older}'s record was evicted by this iteration's edit"
