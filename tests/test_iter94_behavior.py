"""Black-box behaviour tests for iter 94 -- `foundry product-gate --json`
(item 20 bite 4a, the EIGHTH and LAST CLI of the org-design decision-CLI
observability cadence and the FIRST composite): a machine-readable JSON payload
for the read-only DORMANT COMPOSITE product-gate decision CLI, added ON TOP of
the pre-existing dormant core (ProductGateDecision / decide_product_gate /
product_gate_cli, shipped iter 76). The change is a clean ADD-A-METHOD +
ADD-A-FLAG: a new `ProductGateDecision.to_dict()` (nesting BOTH leaf verdict
dicts -- ProductGatePrecheck.to_dict iter 92, ProductGateVerdict.to_dict iter 91)
+ an `as_json: bool = False` kw param on the existing `product_gate_cli` + a
`--json` store_true subparser arg + a one-line dispatch edit. ZERO call site:
nothing in the running loop invokes it, so this cannot break resume.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-16), the pre-existing tests/ dir (iter-76 core tests to learn the
ProductGateDecision API; iter-92 gate-precheck + iter-91 gate-verdict as the
leaf `--json` predecessors for conventions + the two nested leaf to_dict
shapes), and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure composite via `foundry.decide_product_gate`
+ `ProductGateDecision.to_dict`, the CLI via `foundry.product_gate_cli` and
`foundry.main(["product-gate", ...])`. The canonical drive cases are grounded in
observed behaviour: a proposal carrying an impact number + appetite + alternative
PASSES the pre-check (so the three seats are consulted), an empty proposal BOUNCES
(seats None); the seat triples exercise GO / KILL-by-seat / RECYCLE. The dormancy
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

# The 4 keys to_dict() must expose, IN THIS ORDER (two stored fields in
# declaration order, then the two derived props). NO exit_code key.
KEY_ORDER = ["precheck", "seats", "bounced", "verdict"]
EXPECTED_KEYS = set(KEY_ORDER)

# The three PRE-EXISTING product-gate symbols (they shipped iter 76, so a
# whole-file grep would FALSE-POSITIVE). Dormancy is proven ONLY against these
# specific symbols + the command string -- NEVER the generic `to_dict` name
# (many other classes own a to_dict).
PGD_SYMBOLS = ("ProductGateDecision", "decide_product_gate", "product_gate_cli")

# The 8-prefix human-line discriminator (the composite human render is
# variable-shape: a passed proposal prints business/killers/recyclers; a bounced
# proposal prints a single seats-bounced line; both share the four other lines).
HUMAN_PREFIXES = (
    "product-gate:", "impact_present:", "missing:", "seats:",
    "business:", "killers:", "recyclers:", "verdict:",
)

# A proposal that PASSES the deterministic pre-check (impact keyword co-located
# with a number, a stated appetite, a listed alternative) so the three seats are
# consulted. Grounded in the OBSERVED iter-76 core behaviour, not source.
GOOD = (
    "Impact: this saves 40 percent of latency and 2000000 dollars annually.\n"
    "Appetite: we can commit 3 weeks to this bet.\n"
    "Alternatives: we considered option A instead and rejected it.\n"
)
# A proposal that FAILS the pre-check (missing everything) -> bounced, seats None.
BAD = ""

# canonical seat triples -> composite verdict when the pre-check PASSES
GO_SEATS = ("go", "go", "go")            # verdict GO,      exit 0
KILL_SEATS = ("go", "kill", "go")        # verdict KILL,    exit 1, killers ["product"]
RECYCLE_SEATS = ("go", "recycle", "go")  # verdict RECYCLE, exit 2, recyclers ["product"]
EXIT_BY_VERDICT = {"GO": 0, "KILL": 1, "RECYCLE": 2}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _d(text, b, p, e):
    return foundry.decide_product_gate(text, b, p, e)


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def _write(tmp_path, text, name="proposal.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


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


def _expected_human(path, dec):
    """The documented composite human render (spec Behavior 8), reconstructed
    from the PUBLIC core -- not from the implementation source. Confirmed
    byte-identical to the CLI output for GO/KILL/RECYCLE/MIXED/BOUNCED."""
    pc = dec.precheck
    lines = [
        "product-gate: %s" % path,
        "  impact_present: %s  appetite_present: %s  alternatives_present: %s" % (
            pc.impact_present, pc.appetite_present, pc.alternatives_present),
        "  missing: %s" % (", ".join(pc.missing) if pc.missing else "(none)"),
    ]
    if dec.bounced:
        lines.append("  seats: bounced (pre-check failed, seats not consulted)")
    else:
        se = dec.seats
        lines.append("  business: %s  product: %s  engineering: %s" % (
            se.business, se.product, se.engineering))
        lines.append("  killers: %s" % (", ".join(se.killers) if se.killers else "(none)"))
        lines.append("  recyclers: %s" % (", ".join(se.recyclers) if se.recyclers else "(none)"))
    lines.append("verdict: %s" % dec.verdict)
    return "\n".join(lines) + "\n"


def _leaks_human_prefix(line):
    """True iff a printed line, stripped, begins with a human-report prefix."""
    return line.strip().startswith(HUMAN_PREFIXES)


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter94_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object + CLI tests non-vacuous (the fixtures
# really do pass/bounce and the seat triples really do produce their verdicts)
# ==========================================================================
def test_precondition_fixtures_and_seat_triples():
    assert _d(GOOD, *GO_SEATS).precheck.passed is True
    assert _d(GOOD, *GO_SEATS).bounced is False
    assert _d(BAD, *GO_SEATS).precheck.passed is False
    assert _d(BAD, *GO_SEATS).bounced is True
    assert _d(GOOD, *GO_SEATS).verdict == "GO"
    kill = _d(GOOD, *KILL_SEATS)
    assert kill.verdict == "KILL"
    assert kill.seats is not None and kill.seats.killers == ("product",)  # non-empty roster
    assert _d(GOOD, *RECYCLE_SEATS).verdict == "RECYCLE"


# ==========================================================================
# Behavior 1 -- to_dict() is a FRESH dict with EXACTLY the 4 ordered keys;
#               no exit_code key; hasattr(ProductGateDecision,"exit_code") False
# ==========================================================================
def test_b01_to_dict_exact_4_keys_in_order():
    for args in ((GOOD, *GO_SEATS), (GOOD, *KILL_SEATS), (GOOD, *RECYCLE_SEATS), (BAD, *GO_SEATS)):
        d = _d(*args).to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == KEY_ORDER, "key order %r != %r" % (list(d.keys()), KEY_ORDER)
        assert set(d.keys()) == EXPECTED_KEYS
        assert len(d) == 4
        assert "exit_code" not in d


def test_b01_no_exit_code_attribute():
    assert not hasattr(foundry.ProductGateDecision, "exit_code")


def test_b01_fresh_dict_each_call():
    r = _d(GOOD, *KILL_SEATS)
    assert r.to_dict() is not r.to_dict(), "to_dict returned the same dict object across calls"


# ==========================================================================
# Behavior 2 -- d["precheck"] == self.precheck.to_dict() (nested leaf reused
#               verbatim; the composite does NOT re-derive the figures)
# ==========================================================================
def test_b02_precheck_equals_nested_leaf_to_dict():
    for args in ((GOOD, *GO_SEATS), (GOOD, *KILL_SEATS), (BAD, *GO_SEATS)):
        r = _d(*args)
        d = r.to_dict()
        assert d["precheck"] == r.precheck.to_dict(), "precheck sub-dict != leaf precheck.to_dict()"
        # the leaf pre-check dict is the shipped 6-key shape
        assert set(d["precheck"].keys()) == {
            "impact_present", "appetite_present", "alternatives_present",
            "passed", "verdict", "missing"}


# ==========================================================================
# Behavior 3 -- passing pre-check -> d["seats"] == self.seats.to_dict()
# ==========================================================================
def test_b03_seats_equals_nested_leaf_when_passing():
    for seats in (GO_SEATS, KILL_SEATS, RECYCLE_SEATS):
        r = _d(GOOD, *seats)
        assert r.seats is not None
        d = r.to_dict()
        assert d["seats"] == r.seats.to_dict(), "seats sub-dict != leaf seats.to_dict()"
        assert set(d["seats"].keys()) == {
            "business", "product", "engineering", "verdict", "killers", "recyclers"}


# ==========================================================================
# Behavior 4 -- failing pre-check -> d["seats"] is None (JSON null), never a dict
# ==========================================================================
def test_b04_seats_none_when_bounced():
    r = _d(BAD, *GO_SEATS)
    assert r.bounced is True
    assert r.seats is None
    d = r.to_dict()
    assert d["seats"] is None, "bounced decision must serialize seats as None, not a dict"
    # even with three GO seats a failing pre-check never computes seats
    assert json.loads(json.dumps(d))["seats"] is None


# ==========================================================================
# Behavior 5 -- bounced is a bool and verdict is a str, both reusing the props
# ==========================================================================
def test_b05_bounced_bool_verdict_str_reuse_props():
    for args in ((GOOD, *GO_SEATS), (GOOD, *KILL_SEATS), (GOOD, *RECYCLE_SEATS), (BAD, *GO_SEATS)):
        r = _d(*args)
        d = r.to_dict()
        assert type(d["bounced"]) is bool
        assert d["bounced"] == r.bounced
        assert type(d["verdict"]) is str
        assert d["verdict"] == r.verdict
        assert d["verdict"] in ("GO", "KILL", "RECYCLE")


# ==========================================================================
# Behavior 6 -- THE DISCRIMINATING ROUND-TRIP over GO/RECYCLE/KILL/BOUNCED,
#               plus a non-vacuity guard proving a bare-tuple leaf roster fails it
# ==========================================================================
def test_b06_json_round_trip_all_cases():
    for args in ((GOOD, *GO_SEATS), (GOOD, *RECYCLE_SEATS), (GOOD, *KILL_SEATS), (BAD, *GO_SEATS)):
        d = _d(*args).to_dict()
        s = json.dumps(d)  # must not raise
        assert json.loads(s) == d, "composite to_dict did not round-trip for %r" % (args,)


def test_b06_round_trip_non_vacuous_bare_tuple_leaf_fails():
    """Prove the round-trip depends on the LEAF list-coercion: substituting a bare
    tuple into the KILL decision's non-empty nested seats.killers roster breaks
    equality (a tuple round-trips to a list)."""
    d = _d(GOOD, *KILL_SEATS).to_dict()
    assert d["seats"]["killers"], "KILL fixture unexpectedly had an empty killers roster"
    assert json.loads(json.dumps(d)) == d
    bad = json.loads(json.dumps(d))  # independent deep copy
    bad["seats"]["killers"] = tuple(bad["seats"]["killers"])  # bare tuple leaf
    assert json.loads(json.dumps(bad)) != bad, (
        "round-trip check is vacuous -- a tuple-valued nested roster did not fail equality"
    )


# ==========================================================================
# Behavior 7 -- to_dict() is pure/read-only: equal-but-distinct dicts; mutating a
#               returned dict (incl. a nested precheck/seats sub-list) is isolated
# ==========================================================================
def test_b07_two_calls_equal_but_distinct():
    r = _d(GOOD, *KILL_SEATS)
    a, b = r.to_dict(), r.to_dict()
    assert a == b
    assert a is not b
    assert a["seats"] is not b["seats"]
    assert a["seats"]["killers"] is not b["seats"]["killers"]
    assert a["precheck"] is not b["precheck"]


def test_b07_mutation_isolated_passing():
    r = _d(GOOD, *KILL_SEATS)
    snap = dataclasses.asdict(r)
    a = r.to_dict()
    a["seats"]["killers"].append("BOGUS")       # nested sub-list
    a["precheck"]["missing"].append("XXX")       # nested sub-list (empty -> appendable)
    a["verdict"] = "TAMPERED"                     # overwrite
    a["NEWKEY"] = 1                               # add key
    assert dataclasses.asdict(r) == snap, "to_dict mutated the frozen decision"
    assert r.to_dict() == _d(GOOD, *KILL_SEATS).to_dict(), "a fresh to_dict was affected by mutation"


def test_b07_mutation_isolated_bounced():
    r = _d(BAD, *GO_SEATS)
    snap = dataclasses.asdict(r)
    a = r.to_dict()
    assert a["precheck"]["missing"], "bounced fixture unexpectedly had empty missing"
    a["precheck"]["missing"].append("YYY")
    a["seats"] = {"tampered": True}               # overwrite the None
    assert dataclasses.asdict(r) == snap, "to_dict mutated the frozen bounced decision"
    assert r.to_dict()["seats"] is None


# ==========================================================================
# Behavior 8 -- default (human) render is byte-for-byte unchanged over both the
#               passed and bounced shapes; default == explicit as_json=False;
#               as_json defaults to False.
# ==========================================================================
def test_b08_default_human_render_bytes(tmp_path):
    cases = [
        (GOOD, GO_SEATS), (GOOD, KILL_SEATS), (GOOD, RECYCLE_SEATS),
        (GOOD, ("kill", "recycle", "kill")), (BAD, GO_SEATS),
    ]
    for i, (text, seats) in enumerate(cases):
        p = _write(tmp_path, text, name="p%d.md" % i)
        dec = _d(text, *seats)
        rc, out = _cap(lambda: foundry.product_gate_cli(str(p), *seats))
        assert out == _expected_human(str(p), dec), "human render mismatch:\n%r" % out
        assert rc == EXIT_BY_VERDICT[dec.verdict]


def test_b08_default_equals_explicit_false(tmp_path):
    p = _write(tmp_path, GOOD)
    rc_def, out_def = _cap(lambda: foundry.product_gate_cli(str(p), *KILL_SEATS))
    rc_false, out_false = _cap(lambda: foundry.product_gate_cli(str(p), *KILL_SEATS, as_json=False))
    assert out_def == out_false
    assert rc_def == rc_false


def test_b08_as_json_defaults_false():
    sig = inspect.signature(foundry.product_gate_cli)
    assert "as_json" in sig.parameters, "product_gate_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 9 -- default (human) mode stdout is NOT valid JSON.
# ==========================================================================
def test_b09_human_mode_not_valid_json(tmp_path):
    for text, seats in ((GOOD, GO_SEATS), (GOOD, KILL_SEATS), (BAD, GO_SEATS)):
        p = _write(tmp_path, text)
        _, out = _cap(lambda: foundry.product_gate_cli(str(p), *seats))
        with pytest.raises(Exception):
            json.loads(out)


# ==========================================================================
# Behavior 10 -- as_json=True prints EXACTLY json.dumps(to_dict(),indent=2)+nl
#                and parses back to to_dict.
# ==========================================================================
def test_b10_json_output_is_exact(tmp_path):
    for text, seats in ((GOOD, GO_SEATS), (GOOD, KILL_SEATS), (GOOD, RECYCLE_SEATS), (BAD, GO_SEATS)):
        p = _write(tmp_path, text)
        dec = _d(text, *seats)
        rc, out = _cap(lambda: foundry.product_gate_cli(str(p), *seats, as_json=True))
        expected = json.dumps(dec.to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(),indent=2)+newline:\n%r" % out
        assert json.loads(out) == dec.to_dict()


# ==========================================================================
# Behavior 11 -- as_json=True: NO human line leaks; discriminator is armed.
# ==========================================================================
def test_b11_no_human_lines_leak_into_json(tmp_path):
    for text, seats in ((GOOD, KILL_SEATS), (BAD, GO_SEATS)):
        p = _write(tmp_path, text)
        _, out = _cap(lambda: foundry.product_gate_cli(str(p), *seats, as_json=True))
        for ln in out.splitlines():
            if not ln.strip():
                continue
            assert not _leaks_human_prefix(ln), "human line leaked into JSON: %r" % ln
            assert ln.strip()[0] in "{}[]\"", "unexpected JSON line shape: %r" % ln


def test_b11_leak_discriminator_is_armed_both_shapes(tmp_path):
    """The SAME check flags every non-blank line of BOTH the passed and bounced
    human renders -- so the Behavior-11 no-leak assertion is non-vacuous."""
    for text, seats in ((GOOD, KILL_SEATS), (BAD, GO_SEATS)):
        p = _write(tmp_path, text)
        _, human = _cap(lambda: foundry.product_gate_cli(str(p), *seats))
        nonblank = [ln for ln in human.splitlines() if ln.strip()]
        assert nonblank, "human render was empty"
        flagged = [ln for ln in nonblank if _leaks_human_prefix(ln)]
        assert len(flagged) == len(nonblank), (
            "discriminator missed human line(s): %r" % [ln for ln in nonblank if ln not in flagged]
        )


# ==========================================================================
# Behavior 12 -- exit code identical in both modes: 0 GO / 1 KILL (seat OR
#                bounce) / 2 RECYCLE.
# ==========================================================================
def test_b12_exit_code_identical_both_modes(tmp_path):
    cases = [
        (GOOD, GO_SEATS, 0),        # GO
        (GOOD, KILL_SEATS, 1),      # KILL by seat
        (GOOD, RECYCLE_SEATS, 2),   # RECYCLE
        (BAD, GO_SEATS, 1),         # KILL by bounce
    ]
    for i, (text, seats, code) in enumerate(cases):
        p = _write(tmp_path, text, name="e%d.md" % i)
        rc_h, _ = _cap(lambda: foundry.product_gate_cli(str(p), *seats))
        rc_j, _ = _cap(lambda: foundry.product_gate_cli(str(p), *seats, as_json=True))
        assert rc_h == rc_j == code, "seats %r text-empty=%s -> human=%r json=%r expected %r" % (
            seats, text == BAD, rc_h, rc_j, code)


# ==========================================================================
# Behavior 13 -- file-not-found: byte-identical both modes, exit 3, plain human
#                line, never raises FileNotFoundError, emits no JSON.
# ==========================================================================
def test_b13_missing_file_identical_both_modes(tmp_path):
    missing = str(tmp_path / "does_not_exist.md")
    assert not pathlib.Path(missing).exists()
    rc_h, out_h = _cap(lambda: foundry.product_gate_cli(missing, *GO_SEATS))          # must not raise
    rc_j, out_j = _cap(lambda: foundry.product_gate_cli(missing, *GO_SEATS, as_json=True))
    assert rc_h == 3 and rc_j == 3
    assert out_h == out_j, "file-not-found output differs between modes"
    assert out_h == "product-gate: file not found: %s\n" % missing
    assert missing in out_h
    with pytest.raises(Exception):
        json.loads(out_j)


def test_b13_missing_file_no_exception_via_main(tmp_path):
    missing = str(tmp_path / "nope.md")
    rc = foundry.main(["product-gate", "--file", missing,
                       "--business", "go", "--product", "go", "--engineering", "go", "--json"])
    assert rc == 3


# ==========================================================================
# Behavior 14 -- writes NOTHING to disk in either mode (passing, bounced, missing).
# ==========================================================================
def test_b14_writes_nothing(tmp_path, monkeypatch):
    good = _write(tmp_path, GOOD, name="good.md")
    bad = _write(tmp_path, BAD, name="bad.md")
    missing = str(tmp_path / "ghost.md")
    empty = tmp_path / "cwd"
    empty.mkdir()
    monkeypatch.chdir(empty)
    for target in (str(good), str(bad), missing):
        for as_json in (False, True):
            before = sorted(p.name for p in empty.iterdir())
            _cap(lambda: foundry.product_gate_cli(target, *GO_SEATS, as_json=as_json))
            after = sorted(p.name for p in empty.iterdir())
            assert before == after == [], (
                "CLI wrote to cwd (target=%s as_json=%s): %r" % (target, as_json, after))


# ==========================================================================
# Behavior 15 -- argparse/dispatch + end-to-end via foundry.main.
# ==========================================================================
def test_b15_json_store_true_via_dispatch_spy(tmp_path, monkeypatch):
    captured = {}

    def fake(path, business, product, engineering, as_json=False):
        captured.update(path=path, business=business, product=product,
                        engineering=engineering, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "product_gate_cli", fake)
    p = _write(tmp_path, GOOD)
    foundry.main(["product-gate", "--file", str(p),
                  "--business", "go", "--product", "go", "--engineering", "go", "--json"])
    assert captured == {"path": str(p), "business": "go", "product": "go",
                        "engineering": "go", "as_json": True}
    captured.clear()
    foundry.main(["product-gate", "--file", str(p),
                  "--business", "go", "--product", "go", "--engineering", "go"])
    assert captured == {"path": str(p), "business": "go", "product": "go",
                        "engineering": "go", "as_json": False}


def test_b15_all_args_required(tmp_path):
    p = _write(tmp_path, GOOD)
    full = ["product-gate", "--file", str(p),
            "--business", "go", "--product", "go", "--engineering", "go"]
    for flag in ("--file", "--business", "--product", "--engineering"):
        i = full.index(flag)
        argv = full[:i] + full[i + 2:]
        with pytest.raises(SystemExit) as ei:
            with contextlib.redirect_stderr(io.StringIO()):
                foundry.main(argv)
        assert ei.value.code != 0, "omitting %s should SystemExit" % flag


def test_b15_main_passing_go(tmp_path):
    p = _write(tmp_path, GOOD)
    rc, out = _cap(lambda: foundry.main(["product-gate", "--file", str(p),
                   "--business", "go", "--product", "go", "--engineering", "go", "--json"]))
    assert rc == 0
    d = json.loads(out)
    assert d["verdict"] == "GO"
    assert d["bounced"] is False
    assert isinstance(d["seats"], dict)


def test_b15_main_bounced(tmp_path):
    p = _write(tmp_path, BAD)
    rc, out = _cap(lambda: foundry.main(["product-gate", "--file", str(p),
                   "--business", "go", "--product", "go", "--engineering", "go", "--json"]))
    assert rc == 1
    d = json.loads(out)
    assert d["verdict"] == "KILL"
    assert d["bounced"] is True
    assert d["seats"] is None


def test_b15_main_missing_file(tmp_path):
    missing = str(tmp_path / "absent.md")
    rc, out = _cap(lambda: foundry.main(["product-gate", "--file", missing,
                   "--business", "go", "--product", "go", "--engineering", "go", "--json"]))
    assert rc == 3
    assert out == "product-gate: file not found: %s\n" % missing
    with pytest.raises(Exception):
        json.loads(out)


# ==========================================================================
# Behavior 16 -- DORMANCY preserved: running loop unaffected.
# ==========================================================================
def test_b16_orchestrators_do_not_reference_product_gate_symbols():
    new = set(PGD_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references product-gate symbol(s): %r" % (fn.__name__, refs)


def test_b16_dispatcher_has_zero_product_gate_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in PGD_SYMBOLS:
        assert dtext.count(sym) == 0, "dispatcher.py references product-gate symbol %r" % sym
    assert dtext.count("product-gate") == 0, "dispatcher.py names the product-gate command string"


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.decide_product_gate)
    assert callable(foundry.product_gate_cli)
    assert dataclasses.is_dataclass(foundry.ProductGateDecision)
    assert callable(foundry.ProductGateDecision.to_dict)
    # the reused shipped leaf cores + their to_dicts remain present
    assert callable(foundry.product_gate_precheck)
    assert callable(foundry.aggregate_gate_verdict)
    assert callable(foundry.ProductGatePrecheck.to_dict)
    assert callable(foundry.ProductGateVerdict.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_help_lists_product_gate(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "product-gate" in out
    for sub in ("gate-precheck", "gate-verdict", "role-model"):
        assert sub in out, "subcommand %r missing from --help (regression)" % sub


def test_ac_new_symbols_ascii():
    """The new/changed code is pure ASCII. Scoped to the two symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 divider-em-dash trap)."""
    srcs = [
        inspect.getsource(foundry.ProductGateDecision.to_dict),
        inspect.getsource(foundry.product_gate_cli),
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
