"""Black-box behaviour tests for iter 88 -- `foundry cadence-review --json`
(item 22 bite 1, ORG_DESIGN section 7): a machine-readable JSON payload for the
read-only fixed-N no-trigger cadence-review predicate, added ON TOP of the
pre-existing dormant core (decide_cadence_review / CadenceReviewDecision /
cadence_review_cli, iter 78). The change is a clean ADD-A-METHOD + ADD-A-FLAG:
a new `CadenceReviewDecision.to_dict()` + an `as_json: bool = False` kw param on
the existing `cadence_review_cli` + a `--json` store_true subparser arg + a
one-line dispatch edit. ZERO call site: nothing in the running loop invokes it.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the frozen value object via
`foundry.decide_cadence_review` + `CadenceReviewDecision.to_dict`, the CLI via
`foundry.cadence_review_cli` and `foundry.main(["cadence-review", ...])`. The
three canonical drive cases are grounded in observed behaviour: FIRING =
decide_cadence_review(4, False, 5) (fires, REVIEW, exit 1); TRIGGER-BROKEN =
decide_cadence_review(4, True, 5) (a real trigger this iteration -> resets to 0,
CONTINUE, exit 0); NOT-YET = decide_cadence_review(0, False, 5) (quiet but streak
not reached -> next_counter 1, CONTINUE, exit 0). The dormancy proof uses only
public runtime introspection -- compiled function name tables (`co_names`
recursed) + a `dispatcher.py` source symbol-count -- and the mechanical ASCII
acceptance check uses `inspect.getsource` SCOPED to the two new/changed symbols
only (the established suite convention; never a whole-file scan / never
`git diff`). Fully offline and deterministic: no subprocess/git/network except
the fresh-import regression probe. There is deliberately NO
`git diff --quiet HEAD` control-path guard in this file -- the iter-86 fix
removed that over-broad freeze anti-pattern.
"""
import contextlib
import dataclasses
import importlib.util
import inspect
import io
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (module located via the BARE __file__ object,
# never a quoted source-literal main-module name -- the iter-54 meta-scanner)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The 6 keys to_dict() must expose, exactly. NO exit_code key.
EXPECTED_KEYS = {"counter", "trigger_fired", "threshold", "fires", "next_counter", "verdict"}

# The three PRE-EXISTING cadence symbols (they existed since iter 78, so a
# whole-file grep would FALSE-POSITIVE). Dormancy is proven ONLY against these
# specific symbols + the command string -- NOT the generic `to_dict` name (many
# other classes own a to_dict).
CAD_SYMBOLS = ("cadence_review_cli", "CadenceReviewDecision", "decide_cadence_review")

# The three canonical decisions, grounded in observed behaviour.
FIRING = (4, False, 5)           # fires True,  next_counter 0, REVIEW,   exit 1
TRIGGER_BROKEN = (4, True, 5)    # fires False, next_counter 0, CONTINUE, exit 0
NOT_YET = (0, False, 5)          # fires False, next_counter 1, CONTINUE, exit 0
CANONICAL = (FIRING, TRIGGER_BROKEN, NOT_YET)


def _d(args):
    return foundry.decide_cadence_review(*args)


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing nested code objects. Pure
    runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter88_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous (the three canonical
# cases really do behave as the spec's names claim)
# ==========================================================================
def test_precondition_canonical_cases_behave_as_named():
    f = _d(FIRING)
    assert f.fires is True and f.verdict == "REVIEW" and f.next_counter == 0
    tb = _d(TRIGGER_BROKEN)
    assert tb.fires is False and tb.verdict == "CONTINUE" and tb.next_counter == 0
    ny = _d(NOT_YET)
    assert ny.fires is False and ny.verdict == "CONTINUE" and ny.next_counter == 1


# ==========================================================================
# Behavior 1 -- to_dict() has EXACTLY the 6 keys
# ==========================================================================
def test_b01_to_dict_exact_6_keys():
    for args in CANONICAL:
        d = _d(args).to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == EXPECTED_KEYS, (
            "to_dict keys %r != %r" % (set(d.keys()), EXPECTED_KEYS)
        )
        assert len(d) == 6
        assert "exit_code" not in d


# ==========================================================================
# Behavior 2 -- each value equals its source field/property; the two booleans
#               hold by IDENTITY (a re-derived-but-unequal-type cannot pass)
# ==========================================================================
def test_b02_values_match_source_and_bools_by_identity():
    for args in CANONICAL:
        D = _d(args)
        d = D.to_dict()
        assert d["counter"] == D.counter
        assert d["threshold"] == D.threshold
        assert d["next_counter"] == D.next_counter
        assert d["verdict"] == D.verdict
        # the two booleans by identity
        assert d["trigger_fired"] is D.trigger_fired
        assert d["fires"] is D.fires


# ==========================================================================
# Behavior 3 -- every value is JSON-native scalar; NO list/tuple/nested field
# ==========================================================================
def test_b03_all_values_json_native_scalar():
    for args in CANONICAL:
        d = _d(args).to_dict()
        assert type(d["counter"]) is int
        assert type(d["threshold"]) is int
        assert type(d["next_counter"]) is int
        assert type(d["trigger_fired"]) is bool
        assert type(d["fires"]) is bool
        assert type(d["verdict"]) is str
        # no container anywhere in the payload (unlike escalation-check categories)
        for v in d.values():
            assert not isinstance(v, (list, tuple, dict, set)), (
                "payload carries a non-scalar value %r" % (v,)
            )
        # json.dumps never raises (no coercion needed)
        json.dumps(d)


# ==========================================================================
# Behavior 4 -- json round-trip survives for all three canonical cases
# ==========================================================================
def test_b04_json_round_trip_all_canonical():
    for args in CANONICAL:
        d = _d(args).to_dict()
        s = json.dumps(d)  # must not raise
        assert json.loads(s) == d, (
            "to_dict did not round-trip through JSON for %r" % (args,)
        )


# ==========================================================================
# Behavior 5 -- to_dict() is read-only + returns a FRESH dict each call
# ==========================================================================
def test_b05_no_mutation_and_fresh_dict():
    for args in CANONICAL:
        D = _d(args)
        before = dataclasses.asdict(D)
        d1 = D.to_dict()
        # mutate the returned dict aggressively
        d1["fires"] = "TAMPERED"
        d1["verdict"] = "TAMPERED"
        d1["counter"] = 99999
        d2 = D.to_dict()
        assert dataclasses.asdict(D) == before, "to_dict mutated the frozen instance"
        assert d2 == _d(args).to_dict(), "second to_dict was affected by mutation"
        assert d1 is not d2, "to_dict returned the same dict object across calls"


def test_b05_two_calls_equal():
    D = _d(FIRING)
    assert D.to_dict() == D.to_dict()


# ==========================================================================
# Behavior 6 -- verdict/fires consistency in the payload
# ==========================================================================
def test_b06_verdict_fires_consistency():
    for args in CANONICAL:
        D = _d(args)
        d = D.to_dict()
        if d["fires"] is True:
            assert d["verdict"] == "REVIEW"
        else:
            assert d["fires"] is False
            assert d["verdict"] == "CONTINUE"
        # and it agrees with the frozen property exactly
        assert d["verdict"] == D.verdict


# ==========================================================================
# Behavior 7 -- default == as_json=False, byte-for-byte human render + NOT JSON
# ==========================================================================
def test_b07_default_equals_explicit_false():
    for args in CANONICAL:
        rc_def, out_def = _cap(lambda: foundry.cadence_review_cli(*args))
        rc_false, out_false = _cap(lambda: foundry.cadence_review_cli(*args, as_json=False))
        assert out_def == out_false, "default output != explicit as_json=False output"
        assert rc_def == rc_false
        # the default/human path is NOT JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(out_def)


def test_b07_as_json_default_is_false():
    sig = inspect.signature(foundry.cadence_review_cli)
    assert "as_json" in sig.parameters, "cadence_review_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 8 -- as_json=True prints EXACTLY json.dumps(to_dict(), indent=2)+nl,
#               and NONE of the human-report lines leak in
# ==========================================================================
def test_b08_json_output_is_exact():
    for args in CANONICAL:
        rc, out = _cap(lambda: foundry.cadence_review_cli(*args, as_json=True))
        expected = json.dumps(_d(args).to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(), indent=2)+newline"
        # whole stdout is exactly ONE JSON document == the pure to_dict()
        assert json.loads(out) == _d(args).to_dict()


def test_b08_no_human_lines_leak_into_json():
    _, out = _cap(lambda: foundry.cadence_review_cli(*FIRING, as_json=True))
    # the human report has a "cadence-review:" header, a "  fires:" line, a
    # "  next_counter:" line, and a final "verdict:" line. After .strip() each of
    # those starts with the bare label; a JSON line strips to a leading double
    # quote (e.g. '"fires": true'), so this is a true discriminator.
    for ln in out.splitlines():
        s = ln.strip()
        assert not s.startswith("cadence-review:"), "human header leaked into JSON: %r" % ln
        assert not s.startswith("fires:"), "human fires line leaked into JSON: %r" % ln
        assert not s.startswith("next_counter:"), "human next_counter line leaked into JSON: %r" % ln
        assert not s.startswith("verdict:"), "human verdict line leaked into JSON: %r" % ln


# ==========================================================================
# Behavior 9 -- --json changes ONLY output, never the verdict/exit code
# ==========================================================================
def test_b09_same_exit_code_both_modes():
    fixtures = [(FIRING, 1), (TRIGGER_BROKEN, 0), (NOT_YET, 0)]
    for args, code in fixtures:
        rc_h, _ = _cap(lambda: foundry.cadence_review_cli(*args, as_json=False))
        rc_j, _ = _cap(lambda: foundry.cadence_review_cli(*args, as_json=True))
        assert rc_h == rc_j == code, (
            "exit code diverged for %r: human=%r json=%r expected=%r" % (args, rc_h, rc_j, code)
        )


# ==========================================================================
# Behavior 10 -- --trigger-fired always CONTINUE regardless of counter
# ==========================================================================
def test_b10_trigger_fired_always_continue():
    rc, out = _cap(lambda: foundry.cadence_review_cli(99, True, 5, as_json=True))
    d = json.loads(out)
    assert d["fires"] is False
    assert d["next_counter"] == 0
    assert d["verdict"] == "CONTINUE"
    assert rc == 0


# ==========================================================================
# Behavior 11 -- end-to-end dispatch via foundry.main: --json routes as_json
# ==========================================================================
def test_b11_main_routes_as_json(monkeypatch):
    captured = {}

    def fake(counter, trigger_fired, n, as_json=False):
        captured.update(counter=counter, trigger_fired=trigger_fired, n=n, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "cadence_review_cli", fake)
    foundry.main(["cadence-review", "--counter", "4", "--json"])
    assert captured == {"counter": 4, "trigger_fired": False, "n": None, "as_json": True}
    captured.clear()
    foundry.main(["cadence-review", "--counter", "4"])
    assert captured == {"counter": 4, "trigger_fired": False, "n": None, "as_json": False}


# ==========================================================================
# Behavior 12 -- --json is store_true; --counter is required
# ==========================================================================
def test_b12_json_store_true_and_counter_required():
    # store_true: providing a value after --json is rejected by argparse
    with pytest.raises(SystemExit):
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["cadence-review", "--counter", "4", "--json", "x"])
    # --counter omitted -> argparse exits non-zero
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["cadence-review", "--json"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 13 -- end-to-end through foundry.main (no spy): process code + JSON
# ==========================================================================
def test_b13_main_end_to_end_json():
    rc, out = _cap(lambda: foundry.main(["cadence-review", "--counter", "4", "--n", "5", "--json"]))
    assert rc == 1
    d = json.loads(out)
    assert d["verdict"] == "REVIEW"
    assert d["fires"] is True

    rc, out = _cap(lambda: foundry.main(["cadence-review", "--counter", "0", "--json"]))
    assert rc == 0
    d = json.loads(out)
    assert d["verdict"] == "CONTINUE"
    assert d["fires"] is False


# ==========================================================================
# Behavior 14 -- DORMANCY: the running loop is unaffected
# ==========================================================================
def test_b14_orchestrators_do_not_reference_cadence_symbols():
    new = set(CAD_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references cadence symbol(s): %r" % (fn.__name__, refs)


def test_b14_dispatcher_has_zero_cadence_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in CAD_SYMBOLS:
        assert dtext.count(sym) == 0, "dispatcher.py references cadence symbol %r" % sym
    assert dtext.count("cadence-review") == 0, "dispatcher.py names the cadence-review command string"


# ==========================================================================
# Behavior 15 -- fresh subprocess import + CLI writes nothing to disk
# ==========================================================================
def test_b15_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b15_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for args in CANONICAL:
        for as_json in (False, True):
            before = sorted(x.name for x in tmp_path.iterdir())
            _cap(lambda: foundry.cadence_review_cli(*args, as_json=as_json))
            after = sorted(x.name for x in tmp_path.iterdir())
            assert before == after, "CLI wrote to disk (%r, as_json=%s)" % (args, as_json)


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.decide_cadence_review)
    assert callable(foundry.cadence_review_cli)
    assert dataclasses.is_dataclass(foundry.CadenceReviewDecision)
    assert callable(foundry.CadenceReviewDecision.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_cadence_review(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "cadence-review" in out


def test_ac_new_symbols_ascii():
    """The new/changed code is pure ASCII. Scoped to the two symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 divider-em-dash trap)."""
    srcs = [
        inspect.getsource(foundry.CadenceReviewDecision.to_dict),
        inspect.getsource(foundry.cadence_review_cli),
    ]
    for src in srcs:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a runtime-built home path IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
