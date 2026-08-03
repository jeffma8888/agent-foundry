"""Black-box behaviour tests for iter 78 -- item 22, bite 1 of ~3: the DORMANT
pure fixed-N no-trigger cadence-review DECISION core
`decide_cadence_review(counter, trigger_fired, n=None) -> CadenceReviewDecision`
(a frozen result with fields counter / trigger_fired / threshold plus derived
props `fires` / `next_counter` / `verdict`), driven by a patchable module-level
`CADENCE_REVIEW_N = 5` read at CALL time, plus an on-demand read-only
`foundry cadence-review --counter N [--trigger-fired] [--n N]` CLI. It adopts
ORG_DESIGN section-7's fixed-N no-trigger fallback: after N consecutive quiet
iterations the CEO + PM review the project anyway. ZERO call site: nothing in the
pipeline invokes it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.decide_cadence_review`,
the patchable threshold via the module attribute `foundry.CADENCE_REVIEW_N`, and
the CLI via `foundry.main(["cadence-review", ...])`. The dormancy /
off-control-path checks use only public RUNTIME introspection -- module
attributes, compiled function name tables (`__code__.co_names` recursed via
`_co_names_deep`), `--help` output, and a git `--quiet` exit-code probe -- plus,
for the mechanical ASCII / leak-clean acceptance criteria, `inspect.getsource`
scoped to the NEW symbols only (the established suite convention; never a
whole-file scan / never `git diff`). Fully offline and deterministic: NO
subprocess/git/network/agent-run except the fresh-import + `--help` regression
probes and the control-path byte-unchanged git `--quiet` probe. The dormancy
proof is scoped to the SYMBOLS and the `cadence-review` command string in
dispatcher.py ONLY -- never a bare `rg cadence-review foundry.py`, which now
self-matches the new CLI code.
"""
import dataclasses
import importlib.util
import inspect
import io
import contextlib
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The fixed field order of the frozen decision result.
ORDER = ("counter", "trigger_fired", "threshold")

# The symbols this iteration ADDS. They must be dormant: no orchestrator and
# dispatcher.py reference any of them by name.
NEW_SYMBOLS = (
    "decide_cadence_review",
    "CadenceReviewDecision",
    "cadence_review_cli",
    "CADENCE_REVIEW_N",
)

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects.
    Pure runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter78_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cli(args):
    """Drive the CLI via foundry.main, capturing stdout + exit code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.main(list(args))
    return rc, buf.getvalue()


def _d(counter, trigger_fired, n=None):
    if n is None:
        return foundry.decide_cadence_review(counter, trigger_fired)
    return foundry.decide_cadence_review(counter, trigger_fired, n=n)


# ==========================================================================
# Behavior 1 -- pure, total, never-raises, offline, deterministic, value-equal
# ==========================================================================
def test_b01_total_never_raises_and_typed():
    cases = [(0, False), (0, True), (4, False), (5, True), (-1, False),
             (-100, True), (999, False), (1, True), (10, False)]
    for counter, tf in cases:
        r = _d(counter, tf)  # must not raise, including negatives / 0
        assert type(r).__name__ == "CadenceReviewDecision", (
            f"decide_cadence_review did not return CadenceReviewDecision for "
            f"({counter}, {tf})"
        )


def test_b01_deterministic_value_and_repr_equal():
    for counter, tf in ((0, False), (4, False), (5, False), (999, True), (-3, False)):
        a = _d(counter, tf)
        b = _d(counter, tf)
        assert a == b, f"not value-equal for ({counter}, {tf}): {a!r} vs {b!r}"
        assert repr(a) == repr(b), f"repr not equal for ({counter}, {tf})"


def test_b01_different_args_not_equal():
    # sanity: value equality is meaningful, not a degenerate always-equal
    assert _d(4, False) != _d(3, False)
    assert _d(4, False) != _d(4, True)


def test_b01_no_filesystem_access(monkeypatch):
    """Pure: the core opens no file. Sabotage builtins.open; it still works."""
    def _boom(*a, **k):
        raise AssertionError("decide_cadence_review performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    r = _d(4, False)
    assert r.fires is True
    assert r.verdict == "REVIEW"


# ==========================================================================
# Behavior 2 -- frozen CadenceReviewDecision
# ==========================================================================
def test_b02_frozen_dataclass():
    assert dataclasses.is_dataclass(foundry.CadenceReviewDecision)
    r = _d(4, False)
    for field, value in (("counter", 99), ("trigger_fired", True), ("threshold", 1)):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(r, field, value)


# ==========================================================================
# Behavior 3 -- fields counter/trigger_fired/threshold in that order
# ==========================================================================
def test_b03_fields_names_and_order():
    field_names = tuple(f.name for f in dataclasses.fields(foundry.CadenceReviewDecision))
    assert field_names == ORDER, (
        f"CadenceReviewDecision fields = {field_names}, expected {ORDER}"
    )


def test_b03_field_values_track_input():
    r = _d(7, False)               # default threshold 5
    assert r.counter == 7 and isinstance(r.counter, int)
    assert r.trigger_fired is False and isinstance(r.trigger_fired, bool)
    assert r.threshold == foundry.CADENCE_REVIEW_N and isinstance(r.threshold, int)
    r2 = _d(3, True, n=9)          # explicit threshold 9
    assert r2.counter == 3
    assert r2.trigger_fired is True
    assert r2.threshold == 9


# ==========================================================================
# Behavior 4 -- trigger_fired True: never fires, next_counter resets to 0,
# regardless of the counter (far below AND far above the threshold)
# ==========================================================================
def test_b04_trigger_fired_resets_regardless_of_counter():
    thr = foundry.CADENCE_REVIEW_N
    for counter in (0, 1, thr - 1, thr, thr + 1, 999, -50):
        r = _d(counter, True)
        assert r.fires is False, f"trigger_fired=True still fired at counter={counter}"
        assert r.next_counter == 0, (
            f"trigger_fired=True did not reset next_counter at counter={counter}: "
            f"{r.next_counter}"
        )
        assert r.verdict == "CONTINUE"


# ==========================================================================
# Behavior 5 -- quiet, counter+1 < threshold: no fire, streak grows by one
# ==========================================================================
def test_b05_quiet_below_threshold_grows():
    thr = foundry.CADENCE_REVIEW_N
    # counter+1 < thr  <=>  counter < thr-1  <=>  counter <= thr-2
    for counter in range(-3, thr - 1):
        assert counter + 1 < thr  # test-fixture invariant
        r = _d(counter, False)
        assert r.fires is False, f"fired below threshold at counter={counter}"
        assert r.next_counter == counter + 1, (
            f"streak did not grow by one at counter={counter}: {r.next_counter}"
        )
        assert r.verdict == "CONTINUE"


# ==========================================================================
# Behavior 6 -- quiet, counter+1 == threshold (exact boundary): fires, resets
# ==========================================================================
def test_b06_quiet_at_exact_boundary_fires_and_resets():
    thr = foundry.CADENCE_REVIEW_N
    counter = thr - 1              # counter + 1 == thr
    assert counter + 1 == thr
    r = _d(counter, False)
    assert r.fires is True, f"did not fire at exact boundary counter={counter}"
    assert r.next_counter == 0, f"did not reset at exact boundary: {r.next_counter}"
    assert r.verdict == "REVIEW"


# ==========================================================================
# Behavior 7 -- quiet, counter+1 > threshold (already at/over): still fires (>=)
# ==========================================================================
def test_b07_quiet_over_threshold_still_fires():
    thr = foundry.CADENCE_REVIEW_N
    for counter in (thr, thr + 1, thr + 5, thr + 100):
        assert counter + 1 > thr
        r = _d(counter, False)
        assert r.fires is True, f"did not fire over threshold at counter={counter} (>= not honored)"
        assert r.next_counter == 0, f"did not reset over threshold at counter={counter}"
        assert r.verdict == "REVIEW"


# ==========================================================================
# Behavior 8 -- verdict is REVIEW iff fires; verdict/fires mutually consistent
# ==========================================================================
def test_b08_verdict_matches_fires_across_truth_table():
    thr = foundry.CADENCE_REVIEW_N
    counters = list(range(-3, thr + 6)) + [999, -999]
    for counter in counters:
        for tf in (False, True):
            r = _d(counter, tf)
            assert r.verdict in ("REVIEW", "CONTINUE")
            assert r.verdict == ("REVIEW" if r.fires else "CONTINUE"), (
                f"verdict/fires inconsistent at counter={counter} tf={tf}: "
                f"fires={r.fires} verdict={r.verdict}"
            )
            # cross-check the state-machine definition independently
            expected_fires = (not tf) and (counter + 1 >= thr)
            assert r.fires is expected_fires, (
                f"fires wrong at counter={counter} tf={tf}: got {r.fires}, "
                f"expected {expected_fires}"
            )
            expected_next = 0 if (tf or expected_fires) else counter + 1
            assert r.next_counter == expected_next, (
                f"next_counter wrong at counter={counter} tf={tf}: "
                f"got {r.next_counter}, expected {expected_next}"
            )


# ==========================================================================
# Behavior 9 -- call-time default threshold via CADENCE_REVIEW_N;
# monkeypatch flips a SUBSEQUENT decide; restore reverts (knob not captured
# at definition time)
# ==========================================================================
def test_b09_call_time_threshold_read(monkeypatch):
    orig = foundry.CADENCE_REVIEW_N
    # at default (5), counter=4 -> 4+1==5 -> fires
    r_default = _d(4, False)
    assert r_default.threshold == orig
    assert r_default.fires is True
    # raise the knob to 10 -> 4+1=5 < 10 -> no longer fires; threshold tracks
    monkeypatch.setattr(foundry, "CADENCE_REVIEW_N", 10)
    r_raised = _d(4, False)
    assert r_raised.threshold == 10, "threshold did not read the patched CADENCE_REVIEW_N"
    assert r_raised.fires is False, "patched-higher threshold still fired (import-time capture?)"
    assert r_raised.next_counter == 5
    assert r_raised.verdict == "CONTINUE"


def test_b09_restore_reverts():
    # after the previous test's monkeypatch is undone, default behaviour returns
    r = _d(4, False)
    assert r.threshold == foundry.CADENCE_REVIEW_N == 5
    assert r.fires is True
    assert r.verdict == "REVIEW"


def test_b09_lowering_knob_makes_earlier_counters_fire(monkeypatch):
    monkeypatch.setattr(foundry, "CADENCE_REVIEW_N", 2)
    # counter=1 -> 1+1==2 -> fires under the lowered threshold
    r = _d(1, False)
    assert r.threshold == 2
    assert r.fires is True
    assert r.next_counter == 0
    assert r.verdict == "REVIEW"


# ==========================================================================
# Behavior 10 -- explicit threshold override ignores the module-level knob
# ==========================================================================
def test_b10_explicit_override_uses_k(monkeypatch):
    # explicit n=3: counter=2 -> 2+1==3 -> fires, independent of module N
    r = _d(2, False, n=3)
    assert r.threshold == 3
    assert r.fires is True
    assert r.verdict == "REVIEW"
    # even with the module knob set absurdly high, the explicit n wins
    monkeypatch.setattr(foundry, "CADENCE_REVIEW_N", 999)
    r2 = _d(2, False, n=3)
    assert r2.threshold == 3, "explicit n= did not override the module-level CADENCE_REVIEW_N"
    assert r2.fires is True
    # and a large explicit n suppresses a fire the default would have produced
    r3 = _d(4, False, n=50)
    assert r3.threshold == 50
    assert r3.fires is False
    assert r3.verdict == "CONTINUE"


# ==========================================================================
# Behavior 11 -- CLI exit map (no flag): REVIEW->1, CONTINUE->0 + verdict line
# ==========================================================================
def test_b11_cli_review_exit1():
    # counter=4 at default threshold 5 -> 4+1==5 -> REVIEW
    rc, out = _cli(["cadence-review", "--counter", "4"])
    assert rc == 1, f"REVIEW returned {rc!r}, expected 1\n{out}"
    assert "verdict: REVIEW" in out, f"verdict line missing/wrong:\n{out}"


def test_b11_cli_continue_exit0():
    # counter=2 -> 2+1=3 < 5 -> CONTINUE
    rc, out = _cli(["cadence-review", "--counter", "2"])
    assert rc == 0, f"CONTINUE returned {rc!r}, expected 0\n{out}"
    assert "verdict: CONTINUE" in out, f"verdict line missing/wrong:\n{out}"


def test_b11_cli_over_threshold_reviews():
    rc, out = _cli(["cadence-review", "--counter", "10"])
    assert rc == 1
    assert "verdict: REVIEW" in out


def test_b11_cli_exit_tracks_core(monkeypatch):
    """The CLI is a THIN wrapper: exit + verdict track the pure core (default N)."""
    for counter in (0, 2, 4, 5, 8):
        core = _d(counter, False)
        expected_code = 1 if core.fires else 0
        expected_verdict = core.verdict
        rc, out = _cli(["cadence-review", "--counter", str(counter)])
        assert rc == expected_code, (
            f"CLI exit {rc!r} != core-derived {expected_code} for counter={counter}\n{out}"
        )
        assert f"verdict: {expected_verdict}" in out, (
            f"CLI verdict != core verdict {expected_verdict} for counter={counter}:\n{out}"
        )


# ==========================================================================
# Behavior 12 -- CLI --trigger-fired always CONTINUE (exit 0), next_counter 0
# ==========================================================================
def test_b12_cli_trigger_fired_always_continue():
    for counter in ("0", "4", "5", "999"):
        rc, out = _cli(["cadence-review", "--counter", counter, "--trigger-fired"])
        assert rc == 0, f"--trigger-fired returned {rc!r} at counter={counter}, expected 0\n{out}"
        assert "verdict: CONTINUE" in out, f"verdict not CONTINUE with --trigger-fired:\n{out}"
        # next_counter reported as 0 regardless of the counter
        assert "next_counter: 0" in out, f"next_counter not reset to 0 with --trigger-fired:\n{out}"


# ==========================================================================
# Behavior 13 -- CLI --n K override tracks K, not the module-level knob
# ==========================================================================
def test_b13_cli_n_override_tracks_k():
    # counter=2 --n 3 -> 2+1==3 -> REVIEW exit 1
    rc, out = _cli(["cadence-review", "--counter", "2", "--n", "3"])
    assert rc == 1, f"--n 3 at counter 2 returned {rc!r}, expected 1\n{out}"
    assert "verdict: REVIEW" in out
    assert "threshold=3" in out, f"CLI did not report the overridden threshold:\n{out}"
    # counter=2 --n 10 -> 2+1=3 < 10 -> CONTINUE exit 0
    rc, out = _cli(["cadence-review", "--counter", "2", "--n", "10"])
    assert rc == 0, f"--n 10 at counter 2 returned {rc!r}, expected 0\n{out}"
    assert "verdict: CONTINUE" in out
    assert "threshold=10" in out


def test_b13_cli_n_override_beats_module_knob(monkeypatch):
    monkeypatch.setattr(foundry, "CADENCE_REVIEW_N", 999)
    # default would CONTINUE at 999, but --n 3 forces REVIEW
    rc, out = _cli(["cadence-review", "--counter", "2", "--n", "3"])
    assert rc == 1, f"CLI --n did not override the module knob\n{out}"
    assert "verdict: REVIEW" in out


# ==========================================================================
# Behavior 14 -- CLI writes NOTHING; prints the five figures + verdict line
# ==========================================================================
def test_b14_cli_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(x.name for x in tmp_path.iterdir())
    for args in (["cadence-review", "--counter", "4"],
                 ["cadence-review", "--counter", "2"],
                 ["cadence-review", "--counter", "9", "--trigger-fired"],
                 ["cadence-review", "--counter", "2", "--n", "3"]):
        _cli(args)
    after = sorted(x.name for x in tmp_path.iterdir())
    assert before == after == [], f"CLI wrote to disk: {before} -> {after}"


def test_b14_cli_prints_all_figures():
    rc, out = _cli(["cadence-review", "--counter", "4"])
    low = out.lower()
    # the five figures the spec names, plus the verdict line
    assert "counter" in low, f"'counter' figure absent:\n{out}"
    assert "trigger_fired" in low, f"'trigger_fired' figure absent:\n{out}"
    assert "threshold" in low, f"'threshold' figure absent:\n{out}"
    assert "fires" in low, f"'fires' figure absent:\n{out}"
    assert "next_counter" in low, f"'next_counter' figure absent:\n{out}"
    assert "verdict:" in low, f"final 'verdict:' line absent:\n{out}"
    # the concrete values for this input are reported
    assert "4" in out and "5" in out  # counter 4, threshold 5


def test_b14_cli_dispatched_before_load_config():
    # no product --config is required; the CLI runs standalone (mirrors escalation-check)
    rc, out = _cli(["cadence-review", "--counter", "4"])
    assert rc == 1, f"cadence-review needed a --config (not dispatched before load_config)?\n{out}"


# ==========================================================================
# Behavior 15 -- --help lists cadence-review; prior subcommands still registered
# ==========================================================================
def test_b15_help_lists_cadence_review_and_prior_subcommands(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "cadence-review" in out, f"cadence-review missing from --help:\n{out}"
    for sub in ("escalation-check", "product-gate", "gate-verdict", "gate-precheck",
                "role-model", "gate-scope", "lint-spec"):
        assert sub in out, f"prior subcommand {sub!r} missing from --help (regression)"


def test_b15_cadence_review_subparser_help_ok(capsys):
    # the subcommand's own --help renders without error and names its flags
    with pytest.raises(SystemExit) as ei:
        foundry.main(["cadence-review", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--counter" in out, f"--counter absent from subparser help:\n{out}"
    assert "--trigger-fired" in out, f"--trigger-fired absent from subparser help:\n{out}"
    assert "--n" in out, f"--n absent from subparser help:\n{out}"


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_import_intact():
    assert callable(foundry.decide_cadence_review)
    assert callable(foundry.cadence_review_cli)
    assert dataclasses.is_dataclass(foundry.CadenceReviewDecision)
    assert isinstance(foundry.CADENCE_REVIEW_N, int) and not isinstance(foundry.CADENCE_REVIEW_N, bool)
    assert foundry.CADENCE_REVIEW_N == 5, "default CADENCE_REVIEW_N should be 5 (ORG_DESIGN section 7)"
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    # reused prior-bite cores remain present (no regression to the item-20/21 family)
    assert callable(foundry.classify_escalation)
    assert callable(foundry.product_gate_precheck)
    assert callable(foundry.aggregate_gate_verdict)
    assert dispatcher is not None


def test_ac_dormant_zero_call_site():
    """No orchestrator and no dispatcher-module reference references any new
    symbol by name (compiled name tables -- no source text read), nor names the
    `cadence-review` command string in dispatcher.py."""
    new = set(NEW_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"
    assert "cadence-review" not in dtext, "dispatcher.py names the 'cadence-review' command string"


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_new_symbols_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 trap)."""
    new_sources = [
        inspect.getsource(foundry.decide_cadence_review),
        inspect.getsource(foundry.CadenceReviewDecision),
        inspect.getsource(foundry.cadence_review_cli),
    ]
    for src in new_sources:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_ac_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/", ".gitignore"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts / .gitignore NOT byte-unchanged from HEAD"
