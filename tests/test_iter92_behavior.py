"""Black-box behaviour tests for iter 92 -- `foundry gate-precheck --json`
(item 20 bite 1): a machine-readable JSON payload for the read-only DETERMINISTIC
product-gate PRE-CHECK CLI, added ON TOP of the pre-existing dormant core
(product_gate_precheck / ProductGatePrecheck / gate_precheck_cli, shipped iter 73).
The change is a clean ADD-A-METHOD + ADD-A-FLAG: a new `ProductGatePrecheck.to_dict()`
+ an `as_json: bool = False` kw param on the existing `gate_precheck_cli` + a
`--json` store_true subparser arg + a one-line dispatch edit. ZERO call site:
nothing in the running loop invokes it, so this cannot break resume.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15), the product README, the roadmap, the pre-existing tests/ dir
(iter-73 core tests to learn the ProductGatePrecheck API; iter-87 escalation-check
as the `--file` `--json` predecessor for conventions), and the product's own
OBSERVABLE behaviour only (running it). The implementation source (foundry.py
internals), the engineer's and reviewer's notes, and `git diff` were NOT read to
design these behaviour tests. Every check drives the PUBLIC interface: the frozen
value object via `foundry.product_gate_precheck` / `foundry.ProductGatePrecheck`
+ `.to_dict`, the CLI via `foundry.gate_precheck_cli` and
`foundry.main(["gate-precheck", ...])`. The canonical drive cases are grounded in
observed behaviour: PROCEED = a proposal carrying an impact number + appetite +
alternative (verdict PROCEED, passed True, missing [], exit 0); KILL = a proposal
missing the impact NUMBER (verdict KILL, missing ["impact number"], exit 1); the
eight boolean triples exercise every `missing` shape. The dormancy proof uses
only public runtime introspection -- compiled function name tables (`co_names`
recursed via `_co_names_deep`) + a `dispatcher.py` source symbol-count -- and the
mechanical ASCII acceptance check uses `inspect.getsource` SCOPED to the two
new/changed symbols only (the established suite convention; never a whole-file
scan / never `git diff`). Fully offline and deterministic: no subprocess/git/
network except the fresh-import regression probe. There is deliberately NO
`git diff --quiet HEAD` control-path guard in this file -- the iter-86 fix removed
that over-broad freeze anti-pattern.
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
KEY_ORDER = ["impact_present", "appetite_present", "alternatives_present",
             "passed", "verdict", "missing"]
EXPECTED_KEYS = set(KEY_ORDER)

# The failed-check labels in fixed order (learned from the iter-73 core tests).
FIXED_MISSING_LABELS = ("impact number", "appetite", "alternatives")

PGP_SYMBOLS = ("ProductGatePrecheck", "product_gate_precheck", "gate_precheck_cli")

# All eight boolean triples (impact_present, appetite_present, alternatives_present).
TRIPLES = [(a, b, c) for a in (True, False) for b in (True, False) for c in (True, False)]

# Proposal texts whose deterministic pre-check yields each verdict (grounded in
# the iter-73 core-behaviour tests + confirmed by running the core).
PROCEED_TEXT = "Impact: 40% fewer stalls\nAppetite: two weeks\nAlternatives: none\n"
KILL_TEXT = "Appetite: soon\nAlternatives: none\n"     # no impact NUMBER -> KILL
KILL_ALL_TEXT = ""                                      # empty -> all three missing


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
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


def _expected_human(path, core):
    """The documented 4-line human report (spec Behavior 7), reconstructed from
    the PUBLIC core -- not from the implementation source."""
    missing_str = ", ".join(core.missing) if core.missing else "(none)"
    return (
        "gate-precheck: %s\n"
        "  impact_present: %s  appetite_present: %s  alternatives_present: %s\n"
        "  missing: %s\n"
        "verdict: %s\n"
    ) % (path, core.impact_present, core.appetite_present,
         core.alternatives_present, missing_str, core.verdict)


def _leaks_human_prefix(line):
    """True iff a printed line, stripped, begins with a human-report prefix.
    The discriminator used to prove no human line leaks into JSON mode."""
    return line.strip().startswith(
        ("gate-precheck:", "impact_present:", "missing:", "verdict:"))


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter92_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object + CLI tests non-vacuous
# ==========================================================================
def test_precondition_fixtures_proceed_and_kill():
    assert foundry.product_gate_precheck(PROCEED_TEXT).verdict == "PROCEED"
    assert foundry.product_gate_precheck(PROCEED_TEXT).passed is True
    assert foundry.product_gate_precheck(PROCEED_TEXT).missing == ()
    k = foundry.product_gate_precheck(KILL_TEXT)
    assert k.verdict == "KILL"
    assert k.passed is False
    assert k.missing == ("impact number",)
    assert foundry.product_gate_precheck(KILL_ALL_TEXT).missing == FIXED_MISSING_LABELS


# ==========================================================================
# Behavior 1 -- to_dict returns a NEW dict with EXACTLY the 6 ordered keys;
# no exit_code key; hasattr(class, "exit_code") is False.
# ==========================================================================
def test_b01_to_dict_exact_6_keys_ordered():
    for t in TRIPLES:
        d = foundry.ProductGatePrecheck(*t).to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == KEY_ORDER, "key set/order wrong for %r: %r" % (t, list(d.keys()))
        assert set(d.keys()) == EXPECTED_KEYS
        assert "exit_code" not in d


def test_b01_no_exit_code_attr():
    assert not hasattr(foundry.ProductGatePrecheck, "exit_code")


# ==========================================================================
# Behavior 2 -- the three stored booleans serialize verbatim (Python bool).
# ==========================================================================
def test_b02_stored_bools_verbatim():
    for t in TRIPLES:
        p = foundry.ProductGatePrecheck(*t)
        d = p.to_dict()
        assert d["impact_present"] is p.impact_present
        assert d["appetite_present"] is p.appetite_present
        assert d["alternatives_present"] is p.alternatives_present
        for k in ("impact_present", "appetite_present", "alternatives_present"):
            assert type(d[k]) is bool


# ==========================================================================
# Behavior 3 -- passed/verdict REUSE the frozen properties.
# ==========================================================================
def test_b03_scalar_derived_reuse_props():
    for t in TRIPLES:
        p = foundry.ProductGatePrecheck(*t)
        d = p.to_dict()
        assert d["passed"] == p.passed
        assert type(d["passed"]) is bool
        assert d["verdict"] == p.verdict
        assert d["verdict"] in ("PROCEED", "KILL")
        # PROCEED iff all three True, else KILL
        assert d["verdict"] == ("PROCEED" if all(t) else "KILL")
        assert d["passed"] is (d["verdict"] == "PROCEED")


# ==========================================================================
# Behavior 4 -- missing is a plain list == list(P.missing): failed labels in
# the fixed order, empty iff passed.
# ==========================================================================
def test_b04_missing_is_list_coerced():
    for t in TRIPLES:
        p = foundry.ProductGatePrecheck(*t)
        d = p.to_dict()
        assert type(d["missing"]) is list, "missing must be a list, got %r" % type(d["missing"])
        assert d["missing"] == list(p.missing)


def test_b04_missing_fixed_order_and_empty_iff_passed():
    for t in TRIPLES:
        p = foundry.ProductGatePrecheck(*t)
        d = p.to_dict()
        # subsequence of the fixed label order
        idx = [FIXED_MISSING_LABELS.index(lbl) for lbl in d["missing"]]
        assert idx == sorted(idx), "missing not in fixed order for %r: %r" % (t, d["missing"])
        # every label in FIXED_MISSING_LABELS, no dupes
        assert all(lbl in FIXED_MISSING_LABELS for lbl in d["missing"])
        # empty iff passed
        assert (d["missing"] == []) == d["passed"]


# ==========================================================================
# Behavior 5 -- round-trip holds for EVERY triple; the bare-tuple variant is
# proven to break it whenever missing is non-empty (non-vacuity).
# ==========================================================================
def test_b05_json_round_trip_all_triples():
    for t in TRIPLES:
        d = foundry.ProductGatePrecheck(*t).to_dict()
        assert json.loads(json.dumps(d)) == d, "round-trip broke for %r" % (t,)


def test_b05_bare_tuple_variant_breaks_round_trip():
    armed = 0
    for t in TRIPLES:
        p = foundry.ProductGatePrecheck(*t)
        bad = p.to_dict()
        bad["missing"] = p.missing              # bare frozen tuple, NOT list(...)
        if p.missing:                           # non-empty -> discriminating
            assert json.loads(json.dumps(bad)) != bad, \
                "bare-tuple variant unexpectedly round-trips for %r" % (t,)
            armed += 1
    assert armed >= 1, "non-vacuity guard never exercised a non-empty missing"


# ==========================================================================
# Behavior 6 -- to_dict is pure/read-only and returns a FRESH dict.
# ==========================================================================
def test_b06_no_mutation_of_instance():
    for t in TRIPLES:
        p = foundry.ProductGatePrecheck(*t)
        snap = dataclasses.asdict(p)
        d = p.to_dict()
        d["missing"].append("XXX")
        d["verdict"] = "MUTATED"
        d["new_key"] = 1
        assert dataclasses.asdict(p) == snap, "to_dict mutated the frozen instance for %r" % (t,)


def test_b06_fresh_dict_each_call():
    for t in TRIPLES:
        p = foundry.ProductGatePrecheck(*t)
        a = p.to_dict()
        b = p.to_dict()
        assert a == b
        assert a is not b
        assert a["missing"] is not b["missing"]
        a["missing"].append("Z")
        assert "Z" not in b["missing"]
        assert "Z" not in list(p.missing)


# ==========================================================================
# Behavior 7 -- default (human) render is the documented 4 lines; exit 0/1.
# ==========================================================================
def test_b07_default_human_render_bytes_and_exit(tmp_path):
    for text in (PROCEED_TEXT, KILL_TEXT, KILL_ALL_TEXT):
        p = _write(tmp_path, text)
        core = foundry.product_gate_precheck(p.read_text(encoding="utf-8"))
        rc, out = _cap(lambda: foundry.gate_precheck_cli(str(p)))
        assert out == _expected_human(str(p), core), "human render mismatch:\n%r" % out
        assert rc == (0 if core.passed else 1)


def test_b07_default_equals_explicit_false(tmp_path):
    p = _write(tmp_path, PROCEED_TEXT)
    rc_def, out_def = _cap(lambda: foundry.gate_precheck_cli(str(p)))
    rc_false, out_false = _cap(lambda: foundry.gate_precheck_cli(str(p), as_json=False))
    assert out_def == out_false
    assert rc_def == rc_false


def test_b07_as_json_param_defaults_false():
    sig = inspect.signature(foundry.gate_precheck_cli)
    assert "as_json" in sig.parameters, "gate_precheck_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 8 -- as_json=True prints EXACTLY json.dumps(to_dict(), indent=2)+nl;
# parses to to_dict; no human report line leaks.
# ==========================================================================
def test_b08_json_output_is_exact(tmp_path):
    for text in (PROCEED_TEXT, KILL_TEXT):
        p = _write(tmp_path, text)
        core = foundry.product_gate_precheck(p.read_text(encoding="utf-8"))
        rc, out = _cap(lambda: foundry.gate_precheck_cli(str(p), as_json=True))
        expected = json.dumps(core.to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(), indent=2)+newline:\n%r" % out
        assert json.loads(out) == core.to_dict()


def test_b08_no_human_lines_leak_into_json(tmp_path):
    p = _write(tmp_path, KILL_TEXT)
    _, out = _cap(lambda: foundry.gate_precheck_cli(str(p), as_json=True))
    for ln in out.splitlines():
        if not ln.strip():
            continue
        assert not _leaks_human_prefix(ln), "human line leaked into JSON: %r" % ln
        assert ln.strip()[0] in "{}[]\"", "unexpected JSON line shape: %r" % ln


def test_b08_leak_discriminator_is_armed(tmp_path):
    """The SAME check flags every non-blank line of the human report -- so the
    Behavior-8 no-leak assertion is non-vacuous (armed)."""
    p = _write(tmp_path, KILL_TEXT)
    _, human = _cap(lambda: foundry.gate_precheck_cli(str(p)))
    nonblank = [ln for ln in human.splitlines() if ln.strip()]
    assert nonblank, "human render was empty"
    flagged = [ln for ln in nonblank if _leaks_human_prefix(ln)]
    assert len(flagged) == len(nonblank), \
        "discriminator failed to flag every human line: %r" % [ln for ln in nonblank if ln not in flagged]


# ==========================================================================
# Behavior 9 -- default (human) mode stdout is NOT valid JSON.
# ==========================================================================
def test_b09_human_mode_not_valid_json(tmp_path):
    for text in (PROCEED_TEXT, KILL_TEXT):
        p = _write(tmp_path, text)
        _, out = _cap(lambda: foundry.gate_precheck_cli(str(p)))
        with pytest.raises(Exception):
            json.loads(out)


# ==========================================================================
# Behavior 10 -- exit code identical in both modes over PROCEED + KILL.
# ==========================================================================
def test_b10_same_exit_code_both_modes(tmp_path):
    for text in (PROCEED_TEXT, KILL_TEXT, KILL_ALL_TEXT):
        p = _write(tmp_path, text)
        core = foundry.product_gate_precheck(p.read_text(encoding="utf-8"))
        rc_h, _ = _cap(lambda: foundry.gate_precheck_cli(str(p)))
        rc_j, _ = _cap(lambda: foundry.gate_precheck_cli(str(p), as_json=True))
        assert rc_h == rc_j
        assert rc_h == (0 if core.passed else 1)


# ==========================================================================
# Behavior 11 -- file-not-found: byte-identical both modes, exit 2, plain
# human line, never raises FileNotFoundError.
# ==========================================================================
def test_b11_missing_file_identical_both_modes(tmp_path):
    missing = str(tmp_path / "does_not_exist.md")
    assert not pathlib.Path(missing).exists()
    rc_h, out_h = _cap(lambda: foundry.gate_precheck_cli(missing))          # must not raise
    rc_j, out_j = _cap(lambda: foundry.gate_precheck_cli(missing, as_json=True))
    assert rc_h == 2 and rc_j == 2
    assert out_h == out_j, "file-not-found output differs between modes"
    assert out_h == "gate-precheck: file not found: %s\n" % missing
    assert missing in out_h
    # the JSON flag does NOT turn the error into a JSON document
    with pytest.raises(Exception):
        json.loads(out_j)


def test_b11_missing_file_no_exception_via_main(tmp_path):
    missing = str(tmp_path / "nope.md")
    # foundry.main must return 2, not propagate FileNotFoundError
    rc = foundry.main(["gate-precheck", "--file", missing, "--json"])
    assert rc == 2


# ==========================================================================
# Behavior 12 -- writes NOTHING to disk in either mode (present + missing).
# ==========================================================================
def test_b12_writes_nothing(tmp_path, monkeypatch):
    proc = _write(tmp_path, PROCEED_TEXT, name="proc.md")
    kill = _write(tmp_path, KILL_TEXT, name="kill.md")
    missing = str(tmp_path / "ghost.md")
    empty = tmp_path / "cwd"
    empty.mkdir()
    monkeypatch.chdir(empty)
    for target in (str(proc), str(kill), missing):
        for as_json in (False, True):
            before = sorted(p.name for p in empty.iterdir())
            _cap(lambda: foundry.gate_precheck_cli(target, as_json=as_json))
            after = sorted(p.name for p in empty.iterdir())
            assert before == after == [], \
                "CLI wrote to cwd (target=%s as_json=%s): %r" % (target, as_json, after)


# ==========================================================================
# Behavior 13 -- argparse: --json store_true; --file required; no-value-after-flag.
# ==========================================================================
def test_b13_json_store_true_via_dispatch_spy(tmp_path, monkeypatch):
    captured = {}

    def fake(path, as_json=False):
        captured["path"] = path
        captured["as_json"] = as_json
        return 0

    monkeypatch.setattr(foundry, "gate_precheck_cli", fake)
    p = _write(tmp_path, PROCEED_TEXT)
    foundry.main(["gate-precheck", "--file", str(p), "--json"])
    assert captured == {"path": str(p), "as_json": True}
    captured.clear()
    foundry.main(["gate-precheck", "--file", str(p)])
    assert captured == {"path": str(p), "as_json": False}


def test_b13_file_required_and_no_value_after_flag(tmp_path):
    p = _write(tmp_path, PROCEED_TEXT)
    # --file omitted -> SystemExit
    with pytest.raises(SystemExit) as ei1:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["gate-precheck", "--json"])
    assert ei1.value.code != 0
    # a value token after store_true --json -> SystemExit
    with pytest.raises(SystemExit) as ei2:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["gate-precheck", "--file", str(p), "--json", "x"])
    assert ei2.value.code != 0


# ==========================================================================
# Behavior 14 -- dispatch end-to-end via foundry.main.
# ==========================================================================
def test_b14_main_proceed(tmp_path):
    p = _write(tmp_path, PROCEED_TEXT)
    rc, out = _cap(lambda: foundry.main(["gate-precheck", "--file", str(p), "--json"]))
    assert rc == 0
    d = json.loads(out)
    assert d["verdict"] == "PROCEED"
    assert d["passed"] is True
    assert d["missing"] == []


def test_b14_main_kill(tmp_path):
    p = _write(tmp_path, KILL_TEXT)
    core = foundry.product_gate_precheck(KILL_TEXT)
    rc, out = _cap(lambda: foundry.main(["gate-precheck", "--file", str(p), "--json"]))
    assert rc == 1
    d = json.loads(out)
    assert d["verdict"] == "KILL"
    assert d["passed"] is False
    assert d["missing"] == list(core.missing)
    assert d["missing"] != []


def test_b14_main_missing_file(tmp_path):
    missing = str(tmp_path / "absent.md")
    rc, out = _cap(lambda: foundry.main(["gate-precheck", "--file", missing, "--json"]))
    assert rc == 2
    assert out == "gate-precheck: file not found: %s\n" % missing
    with pytest.raises(Exception):
        json.loads(out)


# ==========================================================================
# Behavior 15 -- DORMANCY + import invariants: running loop unaffected.
# ==========================================================================
def test_b15_orchestrators_do_not_reference_precheck_symbols():
    new = set(PGP_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references pre-check symbol(s): %r" % (fn.__name__, refs)


def test_b15_dispatcher_has_zero_precheck_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in PGP_SYMBOLS:
        assert dtext.count(sym) == 0, "dispatcher.py references pre-check symbol %r" % sym
    assert dtext.count("gate-precheck") == 0, "dispatcher.py names the gate-precheck command string"


def test_b15_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b15_no_new_module_level_import():
    # json + pathlib are already imported; the change adds no new top-level import.
    assert hasattr(foundry, "json")
    assert hasattr(foundry, "pathlib") or hasattr(foundry, "Path")


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.product_gate_precheck)
    assert callable(foundry.gate_precheck_cli)
    assert dataclasses.is_dataclass(foundry.ProductGatePrecheck)
    assert callable(foundry.ProductGatePrecheck.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_gate_precheck(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "gate-precheck" in out


def test_ac_new_symbols_ascii():
    """The new/changed code is pure ASCII. Scoped to the two symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 divider-em-dash trap)."""
    srcs = [
        inspect.getsource(foundry.ProductGatePrecheck.to_dict),
        inspect.getsource(foundry.gate_precheck_cli),
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
