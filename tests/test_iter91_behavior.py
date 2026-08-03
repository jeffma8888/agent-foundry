"""Black-box behaviour tests for iter 91 -- `foundry gate-verdict --json`
(item 20 bite 2, ORG_DESIGN section 6): a machine-readable JSON payload for the
read-only tri-perspective product-gate seat-aggregation verdict, added ON TOP of
the pre-existing dormant core (aggregate_gate_verdict / ProductGateVerdict /
gate_verdict_cli, shipped iter 74). The change is a clean ADD-A-METHOD +
ADD-A-FLAG: a new `ProductGateVerdict.to_dict()` + an `as_json: bool = False` kw
param on the existing `gate_verdict_cli` + a `--json` store_true subparser arg +
a one-line dispatch edit. ZERO call site: nothing in the running loop invokes it.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the frozen value object via
`foundry.aggregate_gate_verdict` + `ProductGateVerdict.to_dict`, the CLI via
`foundry.gate_verdict_cli` and `foundry.main(["gate-verdict", ...])`. The four
canonical drive cases are grounded in observed behaviour: all-GO =
aggregate_gate_verdict("go","go","go") (GO, both rosters empty, exit 0);
single-KILL = aggregate_gate_verdict("go","kill","go") (KILL, killers
["product"], no recyclers, exit 1); single-RECYCLE =
aggregate_gate_verdict("go","recycle","go") (RECYCLE, no killers, recyclers
["product"], exit 2); mixed = aggregate_gate_verdict("kill","recycle","kill")
(KILL, killers ["business","engineering"], recyclers ["product"]). The dormancy
proof uses only public runtime introspection -- compiled function name tables
(`co_names` recursed via `_co_names_deep`) + a `dispatcher.py` source
symbol-count -- and the mechanical ASCII acceptance check uses `inspect.getsource`
SCOPED to the two new/changed symbols only (the established suite convention;
never a whole-file scan / never `git diff`). Fully offline and deterministic: no
subprocess/git/network except the fresh-import regression probe. There is
deliberately NO `git diff --quiet HEAD` control-path guard in this file -- the
iter-86 fix removed that over-broad freeze anti-pattern.
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

# The 6 keys to_dict() must expose, IN THIS ORDER. NO exit_code key.
KEY_ORDER = ["business", "product", "engineering", "verdict", "killers", "recyclers"]
EXPECTED_KEYS = set(KEY_ORDER)
SEAT_ORDER = ("business", "product", "engineering")

# The three PRE-EXISTING gate-verdict symbols (they shipped iter 74, so a
# whole-file grep would FALSE-POSITIVE; aggregate_gate_verdict/ProductGateVerdict
# are ALSO referenced by the dormant product-gate composite core). Dormancy is
# proven ONLY against these specific symbols + the command string -- NEVER the
# generic `to_dict` name (many other classes own a to_dict).
GV_SYMBOLS = ("gate_verdict_cli", "ProductGateVerdict", "aggregate_gate_verdict")

# The four canonical raw-input triples, grounded in observed behaviour.
ALL_GO = ("go", "go", "go")               # GO,      killers (),                 recyclers (),          exit 0
SINGLE_KILL = ("go", "kill", "go")        # KILL,    killers ("product",),       recyclers (),          exit 1
SINGLE_RECYCLE = ("go", "recycle", "go")  # RECYCLE, killers (),                 recyclers ("product",), exit 2
MIXED = ("kill", "recycle", "kill")       # KILL,    killers (business,eng),     recyclers (product,)
CANONICAL = (ALL_GO, SINGLE_KILL, SINGLE_RECYCLE, MIXED)
EXIT_BY_VERDICT = {"GO": 0, "KILL": 1, "RECYCLE": 2}


def _gv(triple):
    return foundry.aggregate_gate_verdict(*triple)


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
    spec = importlib.util.spec_from_file_location("leak_guard_iter91_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous (the four canonical
# cases really do behave as the spec's names claim)
# ==========================================================================
def test_precondition_canonical_cases_behave_as_named():
    ag = _gv(ALL_GO)
    assert ag.verdict == "GO" and ag.killers == () and ag.recyclers == ()
    sk = _gv(SINGLE_KILL)
    assert sk.verdict == "KILL" and sk.killers == ("product",) and sk.recyclers == ()
    sr = _gv(SINGLE_RECYCLE)
    assert sr.verdict == "RECYCLE" and sr.killers == () and sr.recyclers == ("product",)
    mx = _gv(MIXED)
    assert mx.verdict == "KILL" and mx.killers == ("business", "engineering") and mx.recyclers == ("product",)


# ==========================================================================
# Behavior 1 -- to_dict() is a FRESH dict with EXACTLY the 6 keys, in order;
#               no exit_code key; hasattr(ProductGateVerdict,"exit_code") False
# ==========================================================================
def test_b01_to_dict_exact_6_keys_in_order():
    for triple in CANONICAL:
        d = _gv(triple).to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == KEY_ORDER, (
            "to_dict key order %r != %r" % (list(d.keys()), KEY_ORDER)
        )
        assert set(d.keys()) == EXPECTED_KEYS
        assert len(d) == 6
        assert "exit_code" not in d


def test_b01_no_exit_code_attribute():
    assert not hasattr(foundry.ProductGateVerdict, "exit_code")


def test_b01_fresh_dict_each_call():
    V = _gv(MIXED)
    assert V.to_dict() is not V.to_dict(), "to_dict returned the same dict object across calls"


# ==========================================================================
# Behavior 2 -- the three stored seat keys == the frozen fields; verdict key ==
#               the verdict property (identity reuse -- payload can never
#               disagree with the human render or the exit code)
# ==========================================================================
def test_b02_stored_keys_equal_fields_and_verdict_prop():
    for triple in CANONICAL:
        V = _gv(triple)
        d = V.to_dict()
        for seat in SEAT_ORDER:
            assert d[seat] == getattr(V, seat), (
                "to_dict[%r] != frozen field for %r" % (seat, triple)
            )
            assert isinstance(d[seat], str)
        assert d["verdict"] == V.verdict
        assert isinstance(d["verdict"], str)


# ==========================================================================
# Behavior 3 -- killers/recyclers are LISTS (not tuples), == list(prop), in
#               fixed seat order (the escalation-check str-list footgun class)
# ==========================================================================
def test_b03_rosters_are_lists_matching_props():
    for triple in CANONICAL:
        V = _gv(triple)
        d = V.to_dict()
        assert type(d["killers"]) is list, "killers must be a list, not a tuple"
        assert type(d["recyclers"]) is list, "recyclers must be a list, not a tuple"
        assert d["killers"] == list(V.killers)
        assert d["recyclers"] == list(V.recyclers)


def test_b03_roster_seat_order_preserved():
    V = _gv(MIXED)
    d = V.to_dict()
    assert d["killers"] == ["business", "engineering"]
    assert d["recyclers"] == ["product"]
    # order is the fixed seat order, not the appearance order
    idx = [SEAT_ORDER.index(s) for s in d["killers"]]
    assert idx == sorted(idx), "killers not in fixed seat order: %r" % (d["killers"],)


def test_b03_empty_rosters_are_lists():
    d = _gv(ALL_GO).to_dict()
    assert d["killers"] == [] and type(d["killers"]) is list
    assert d["recyclers"] == [] and type(d["recyclers"]) is list


# ==========================================================================
# Behavior 4 -- THE DISCRIMINATING ROUND-TRIP over all four cases, plus a
#               non-vacuity guard proving a tuple-valued roster would FAIL it
# ==========================================================================
def test_b04_json_round_trip_all_four_cases():
    for triple in CANONICAL:
        d = _gv(triple).to_dict()
        s = json.dumps(d)  # must not raise
        assert json.loads(s) == d, (
            "to_dict did not round-trip through JSON for %r (tuple leaked?)" % (triple,)
        )


def test_b04_round_trip_non_vacuous_tuple_shape_fails():
    """Prove the round-trip is a real discriminator: the shape a bare
    `self.killers`/`self.recyclers` (tuples) would produce FAILS `== `."""
    d = _gv(MIXED).to_dict()
    assert json.loads(json.dumps(d)) == d
    bad = dict(d)
    bad["killers"] = tuple(d["killers"])
    bad["recyclers"] = tuple(d["recyclers"])
    assert json.loads(json.dumps(bad)) != bad, (
        "round-trip check is vacuous -- a tuple-valued roster did not fail equality"
    )


# ==========================================================================
# Behavior 5 -- to_dict() is read-only: mutating the returned dict never touches
#               the frozen instance; a fresh to_dict() is unaffected
# ==========================================================================
def test_b05_to_dict_read_only():
    for triple in CANONICAL:
        V = _gv(triple)
        before = dataclasses.asdict(V)
        d1 = V.to_dict()
        d1["killers"].append("BOGUS")
        d1["verdict"] = "TAMPERED"
        d1["NEWKEY"] = 1
        d2 = V.to_dict()
        assert dataclasses.asdict(V) == before, "to_dict mutated the frozen instance"
        assert d2 == _gv(triple).to_dict(), "second to_dict was affected by mutation"
        assert d1 is not d2
        assert d1["killers"] is not d2["killers"], "killers list is shared across calls"


# ==========================================================================
# Behavior 6 -- default == as_json=False, byte-for-byte human render + same code
# ==========================================================================
def test_b06_default_equals_explicit_false():
    for triple in CANONICAL:
        rc_def, out_def = _cap(lambda: foundry.gate_verdict_cli(*triple))
        rc_false, out_false = _cap(lambda: foundry.gate_verdict_cli(*triple, as_json=False))
        assert out_def == out_false, "default output != explicit as_json=False output"
        assert rc_def == rc_false


def test_b06_as_json_default_is_false():
    sig = inspect.signature(foundry.gate_verdict_cli)
    assert "as_json" in sig.parameters, "gate_verdict_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 7 -- the default (human) stdout is NOT valid JSON
# ==========================================================================
def test_b07_default_stdout_not_json():
    for triple in CANONICAL:
        _, out = _cap(lambda: foundry.gate_verdict_cli(*triple))
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)


# ==========================================================================
# Behavior 8 -- as_json=True prints EXACTLY json.dumps(to_dict(), indent=2)+nl,
#               with NO human line leaking; the leak check is armed/non-vacuous
# ==========================================================================
def test_b08_json_output_is_exact():
    for triple in CANONICAL:
        _, out = _cap(lambda: foundry.gate_verdict_cli(*triple, as_json=True))
        expected = json.dumps(_gv(triple).to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(), indent=2)+newline"
        assert json.loads(out) == _gv(triple).to_dict()


def test_b08_no_human_lines_leak_into_json():
    prefixes = ("gate-verdict:", "business:", "killers:", "recyclers:", "verdict:")
    _, out = _cap(lambda: foundry.gate_verdict_cli(*MIXED, as_json=True))
    for ln in out.splitlines():
        s = ln.strip()
        for pref in prefixes:
            assert not s.startswith(pref), "human line %r leaked into JSON" % ln


def test_b08_leak_discriminator_is_armed():
    """The SAME prefix check must flag EVERY line of the human render -- else it
    is inert and its pass on JSON is meaningless."""
    prefixes = ("gate-verdict:", "business:", "killers:", "recyclers:", "verdict:")
    _, human = _cap(lambda: foundry.gate_verdict_cli(*MIXED, as_json=False))
    lines = human.splitlines()
    flagged = [ln for ln in lines if ln.strip().startswith(prefixes)]
    assert len(lines) >= 5, "human render unexpectedly short: %r" % (lines,)
    assert len(flagged) == len(lines), (
        "leak discriminator is inert -- it did not flag every human line: %r" % (lines,)
    )


# ==========================================================================
# Behavior 9 -- exit code identical in both modes == {GO:0,KILL:1,RECYCLE:2}
# ==========================================================================
def test_b09_same_exit_code_both_modes():
    fixtures = [(ALL_GO, 0), (SINGLE_KILL, 1), (SINGLE_RECYCLE, 2), (MIXED, 1)]
    for triple, code in fixtures:
        rc_h, _ = _cap(lambda: foundry.gate_verdict_cli(*triple, as_json=False))
        rc_j, _ = _cap(lambda: foundry.gate_verdict_cli(*triple, as_json=True))
        V = _gv(triple)
        assert rc_h == rc_j == code, (
            "exit code diverged for %r: human=%r json=%r expected=%r" % (triple, rc_h, rc_j, code)
        )
        assert code == EXIT_BY_VERDICT[V.verdict], (
            "expected exit %r disagrees with verdict %r" % (code, V.verdict)
        )


# ==========================================================================
# Behavior 10 -- both modes write NOTHING to disk
# ==========================================================================
def test_b10_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for triple in CANONICAL:
        for as_json in (False, True):
            before = sorted(x.name for x in tmp_path.iterdir())
            _cap(lambda: foundry.gate_verdict_cli(*triple, as_json=as_json))
            after = sorted(x.name for x in tmp_path.iterdir())
            assert before == after, "CLI wrote to disk (%r, as_json=%s)" % (triple, as_json)


# ==========================================================================
# Behavior 11 -- --json is store_true; all three seats required; --json takes
#                no value (all proven via a dispatch spy + argparse SystemExit)
# ==========================================================================
def test_b11_json_store_true_via_dispatch_spy(monkeypatch):
    captured = {}

    def fake(business, product, engineering, as_json=False):
        captured.update(business=business, product=product, engineering=engineering, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "gate_verdict_cli", fake)
    foundry.main(["gate-verdict", "--business", "go", "--product", "go", "--engineering", "go", "--json"])
    assert captured == {"business": "go", "product": "go", "engineering": "go", "as_json": True}
    captured.clear()
    foundry.main(["gate-verdict", "--business", "go", "--product", "go", "--engineering", "go"])
    assert captured == {"business": "go", "product": "go", "engineering": "go", "as_json": False}


def test_b11_all_seats_required():
    for missing in (
        ["gate-verdict", "--product", "go", "--engineering", "go"],
        ["gate-verdict", "--business", "go", "--engineering", "go"],
        ["gate-verdict", "--business", "go", "--product", "go"],
    ):
        with pytest.raises(SystemExit) as ei:
            with contextlib.redirect_stderr(io.StringIO()):
                foundry.main(missing)
        assert ei.value.code != 0, "missing seat did not error: %r" % (missing,)


def test_b11_json_takes_no_value():
    with pytest.raises(SystemExit):
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["gate-verdict", "--business", "go", "--product", "go", "--engineering", "go", "--json", "x"])


# ==========================================================================
# Behavior 12 -- dispatch passes as_json through; end-to-end RECYCLE both modes
# ==========================================================================
def test_b12_dispatch_end_to_end_recycle():
    argv = ["gate-verdict", "--business", "go", "--product", "recycle", "--engineering", "go"]
    rc, out = _cap(lambda: foundry.main(argv + ["--json"]))
    d = json.loads(out)
    assert rc == 2
    assert set(d.keys()) == EXPECTED_KEYS
    assert d["verdict"] == "RECYCLE"
    assert d["recyclers"] == ["product"]
    assert d["killers"] == []
    rc_h, out_h = _cap(lambda: foundry.main(argv))
    assert rc_h == 2
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_h)


# ==========================================================================
# Behavior 13 -- end-to-end via foundry.main: all-GO (exit 0) + a KILL (exit 1)
# ==========================================================================
def test_b13_end_to_end_go_and_kill():
    rc, out = _cap(lambda: foundry.main(
        ["gate-verdict", "--business", "go", "--product", "go", "--engineering", "go", "--json"]))
    d = json.loads(out)
    assert rc == 0
    assert d["verdict"] == "GO"
    assert d["killers"] == []
    assert d["recyclers"] == []
    rc, out = _cap(lambda: foundry.main(
        ["gate-verdict", "--business", "kill", "--product", "go", "--engineering", "go", "--json"]))
    d = json.loads(out)
    assert rc == 1
    assert d["verdict"] == "KILL"


# ==========================================================================
# Behavior 14 -- DORMANCY: the running loop is unaffected
# ==========================================================================
def test_b14_orchestrators_do_not_reference_gate_verdict_symbols():
    new = set(GV_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references gate-verdict symbol(s): %r" % (fn.__name__, refs)


def test_b14_dispatcher_has_zero_gate_verdict_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in GV_SYMBOLS:
        assert dtext.count(sym) == 0, "dispatcher.py references gate-verdict symbol %r" % sym
    assert dtext.count("gate-verdict") == 0, "dispatcher.py names the gate-verdict command string"


def test_b14_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# ==========================================================================
# Behavior 15 -- the new to_dict + changed gate_verdict_cli are pure ASCII
# ==========================================================================
def test_b15_new_symbols_ascii():
    """Scoped to the two symbols via inspect.getsource -- NOT a whole-file scan
    (foundry.py carries pre-existing non-ASCII elsewhere -- the iter-67 trap)."""
    srcs = [
        inspect.getsource(foundry.ProductGateVerdict.to_dict),
        inspect.getsource(foundry.gate_verdict_cli),
    ]
    for src in srcs:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.aggregate_gate_verdict)
    assert callable(foundry.gate_verdict_cli)
    assert dataclasses.is_dataclass(foundry.ProductGateVerdict)
    assert callable(foundry.ProductGateVerdict.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_gate_verdict(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "gate-verdict" in out


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
