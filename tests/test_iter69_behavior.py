"""Black-box behaviour tests for iter 69 -- roadmap item 19, bite 3a of 3.

This bite adds a DORMANT pure execution-PLAN layer above iter-67's
derive_stage_sequence: a SEAT_GATE_KINDS constant, a DEFAULT_GATE_KIND constant,
a frozen StagePlan(spec, gate) dataclass (pure reverts_on_fail / is_ship_gate
properties), a private _gate_kind_for_seat(seat), and a pure
derive_execution_plan(sequence) -- all with ZERO call site, so the running
pipeline is bit-for-bit unchanged and resume semantics are untouched. Bite 3b (a
later iteration) wires the plan into run_iteration behind an
absent-or-default-manifest guard.

ISOLATION CONTRACT (honored, with one disclosed deviation below): every test
here encodes the iter-69 PM spec's Expected Behaviors (1-12), driven purely
against the PUBLIC interface -- the importable public callables/constants
(foundry.derive_execution_plan, foundry.StagePlan, foundry.SEAT_GATE_KINDS,
foundry.DEFAULT_GATE_KIND, foundry._gate_kind_for_seat, and the reused iter-67
foundry.derive_stage_sequence / foundry.StageSpec / foundry._default_stage_sequence
/ foundry.CORE_SEAT_STAGES / foundry.MANIFEST_CORE_SEATS), the committed
scripts/leak_guard.py public API, and inspect.getsource / the dispatcher module's
file text (used ONLY to assert the SPEC's dormancy Behavior 11 and the
new-content-ASCII Behavior 12, both spec-mandated observables -- NOT to mirror
implementation logic). Fully offline & deterministic: no network, no product
subprocess, no real push. Every path is built at RUNTIME from foundry.__file__
(never a source-literal home path), so the committed leak-guard passes on the ship
commit. DISCLOSED DEVIATION: the runner supplied the engineer's & reviewer's iter
notes in the context digest, so complete blindness was not possible; nonetheless
every assertion below is derived from the pm.md spec's Expected Behaviors, not
from those notes -- the notes changed no expected value.

NB on Behavior 12 (pure ASCII): the spec's "new content is pure ASCII" clause
means the NEWLY-ADDED symbols, not the whole module -- the main module already
contains legitimate pre-existing non-ASCII (em-dash-dense docstrings from prior
iterations), so a whole-file ASCII scan would FALSE-fail. The new-content ASCII
property is checked via inspect.getsource of the new symbols; the authoritative
ship-gate leak-cleanliness is checked via the committed leak-guard.

NB on the iter-54 meta-scanner: this file contains a `git diff --quiet` call, so
it must not carry the quoted main-module filename token on any non-comment line.
The main module is located via the BARE module's __file__; it is NOT pinned
byte-unchanged (it legitimately grows this iter). Only the dispatcher module +
scripts/ are pinned byte-unchanged (the control path). iter-67 reuse (Behavior 11)
is proven BEHAVIORALLY (the reused callables still produce their iter-67 outputs)
-- a tester in isolation does not read implementation source, past or present, so
the byte-identical AST-vs-HEAD proof is the reviewer / final gate's out-of-band job.
"""
import dataclasses
import importlib.util
import inspect
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + expected data (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

CORE_SEATS = ("product_manager", "engineer", "reviewer", "qa_tester", "release_gate")
EXPECTED_SEAT_GATE_KINDS = {
    "product_manager": "pm",
    "engineer": "build",
    "reviewer": "review",
    "qa_tester": "test",
    "release_gate": "release",
}

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


def _spec(seat, stage=None):
    """A StageSpec with the convention fields; stage defaults to the seat name."""
    st = seat if stage is None else stage
    return foundry.StageSpec(
        seat=seat, stage=st,
        role_file="bench/" + seat + ".md", out_file=seat + ".md")


def _role_obj(name):
    return {"role": name, "model": "builder-class model", "gate": False,
            "done_criteria": "criteria"}


def _manifest(names):
    return {"product": "x", "iteration_budget": 5,
            "roles": [_role_obj(n) for n in names]}


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter69_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# B1 -- SEAT_GATE_KINDS exact + ordered; DEFAULT_GATE_KIND == "bench"; both read
#       INSIDE _gate_kind_for_seat (a monkeypatch bites)
# --------------------------------------------------------------------------
def test_b1_seat_gate_kinds_exact_and_ordered():
    assert foundry.SEAT_GATE_KINDS == EXPECTED_SEAT_GATE_KINDS
    assert list(foundry.SEAT_GATE_KINDS.keys()) == list(EXPECTED_SEAT_GATE_KINDS.keys())
    assert tuple(foundry.SEAT_GATE_KINDS) == foundry.MANIFEST_CORE_SEATS
    assert foundry.DEFAULT_GATE_KIND == "bench"


def test_b1_gate_kind_reads_globals_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "SEAT_GATE_KINDS", {"engineer": "OVERRIDE"})
    monkeypatch.setattr(foundry, "DEFAULT_GATE_KIND", "FALLBACK")
    assert foundry._gate_kind_for_seat("engineer") == "OVERRIDE"
    assert foundry._gate_kind_for_seat("reviewer") == "FALLBACK"


# --------------------------------------------------------------------------
# B2 -- StagePlan is a frozen dataclass with EXACTLY {spec, gate}; value-eq; immutable
# --------------------------------------------------------------------------
def test_b2_stageplan_frozen_two_fields_value_eq():
    assert dataclasses.is_dataclass(foundry.StagePlan)
    assert [f.name for f in dataclasses.fields(foundry.StagePlan)] == ["spec", "gate"]
    s = _spec("engineer")
    a = foundry.StagePlan(spec=s, gate="build")
    b = foundry.StagePlan(spec=s, gate="build")
    assert a == b
    assert a != foundry.StagePlan(spec=s, gate="review")          # unequal gate
    assert a != foundry.StagePlan(spec=_spec("reviewer"), gate="build")  # unequal spec
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.gate = "changed"


# --------------------------------------------------------------------------
# B3 -- reverts_on_fail: False only for gate == "pm", True for every other gate
# --------------------------------------------------------------------------
@pytest.mark.parametrize("gate,expected", [
    ("pm", False), ("build", True), ("review", True),
    ("test", True), ("release", True), ("bench", True),
])
def test_b3_reverts_on_fail(gate, expected):
    p = foundry.StagePlan(spec=_spec("x"), gate=gate)
    assert p.reverts_on_fail is expected


# --------------------------------------------------------------------------
# B4 -- is_ship_gate: True iff gate == "release", else False
# --------------------------------------------------------------------------
@pytest.mark.parametrize("gate,expected", [
    ("pm", False), ("build", False), ("review", False),
    ("test", False), ("release", True), ("bench", False),
])
def test_b4_is_ship_gate(gate, expected):
    p = foundry.StagePlan(spec=_spec("x"), gate=gate)
    assert p.is_ship_gate is expected


# --------------------------------------------------------------------------
# B5 -- _gate_kind_for_seat: core -> declared kind; ANY non-core -> "bench";
#       exact-match, no normalization; never raises for a string input
# --------------------------------------------------------------------------
def test_b5_gate_kind_core_seats():
    for seat, kind in EXPECTED_SEAT_GATE_KINDS.items():
        assert foundry._gate_kind_for_seat(seat) == kind


@pytest.mark.parametrize("seat", [
    "designer", "tpm", "", "reviewer ", " reviewer", "REVIEWER",
    "release_gate ", "product_manager\t", "unknown_seat",
])
def test_b5_gate_kind_non_core_is_bench(seat):
    assert foundry._gate_kind_for_seat(seat) == "bench"


# --------------------------------------------------------------------------
# B6 -- derive_execution_plan is pure/deterministic/offline; one StagePlan per
#       input StageSpec IN ORDER; spec is the identical input object; gate correct
# --------------------------------------------------------------------------
def test_b6_plan_shape_order_identity_gate_determinism():
    seq = (_spec("product_manager", "pm"), _spec("designer"),
           _spec("release_gate", "final"))
    plan = foundry.derive_execution_plan(seq)
    assert isinstance(plan, tuple)
    assert len(plan) == len(seq)
    for i, sp in enumerate(seq):
        assert isinstance(plan[i], foundry.StagePlan)
        assert plan[i].spec is sp                        # identical object, stronger than ==
        assert plan[i].gate == foundry._gate_kind_for_seat(sp.seat)
    assert [p.gate for p in plan] == ["pm", "bench", "release"]
    # deterministic: two calls on the same input -> equal output
    assert foundry.derive_execution_plan(seq) == foundry.derive_execution_plan(seq)
    # value-equal (distinct-but-equal) input -> equal output
    seq2 = (_spec("product_manager", "pm"), _spec("designer"),
            _spec("release_gate", "final"))
    assert foundry.derive_execution_plan(seq) == foundry.derive_execution_plan(seq2)


# --------------------------------------------------------------------------
# B7 -- LOAD-BEARING: default-sequence plan reproduces run_iteration's five
#       stages + gate behaviors bit-for-bit
# --------------------------------------------------------------------------
def test_b7_default_plan_reproduces_orchestrator():
    plan = foundry.derive_execution_plan(foundry._default_stage_sequence())
    assert len(plan) == 5
    assert [(p.spec.stage, p.gate) for p in plan] == [
        ("pm", "pm"),
        ("engineer", "build"),
        ("reviewer", "review"),
        ("tester", "test"),
        ("final", "release"),
    ]
    assert [p.reverts_on_fail for p in plan] == [False, True, True, True, True]
    assert [p.is_ship_gate for p in plan] == [False, False, False, False, True]


# --------------------------------------------------------------------------
# B8 -- absent manifest yields the default plan (value-equality)
# --------------------------------------------------------------------------
def test_b8_none_manifest_equals_default_plan():
    from_none = foundry.derive_execution_plan(foundry.derive_stage_sequence(None))
    from_default = foundry.derive_execution_plan(foundry._default_stage_sequence())
    assert from_none == from_default


# --------------------------------------------------------------------------
# B9 -- one extra seat activated at its declared position -> a bench StagePlan
#       there; core seats keep gate kinds + relative order
# --------------------------------------------------------------------------
def test_b9_extra_designer_seat_inserted():
    names = ["product_manager", "engineer", "reviewer",
             "designer", "qa_tester", "release_gate"]
    seq = foundry.derive_stage_sequence(_manifest(names))
    assert seq != foundry._default_stage_sequence()   # precondition: non-default
    plan = foundry.derive_execution_plan(seq)
    assert len(plan) == 6
    dp = plan[3]
    assert dp.spec == foundry.StageSpec(
        seat="designer", stage="designer",
        role_file="bench/designer.md", out_file="designer.md")
    assert dp.gate == "bench"
    assert dp.reverts_on_fail is True
    assert dp.is_ship_gate is False
    # core seats retain their kinds and the declared relative order
    assert [(p.spec.seat, p.gate) for p in plan] == [
        ("product_manager", "pm"),
        ("engineer", "build"),
        ("reviewer", "review"),
        ("designer", "bench"),
        ("qa_tester", "test"),
        ("release_gate", "release"),
    ]


# --------------------------------------------------------------------------
# B10 -- empty sequence -> (); accepts a list or a tuple, returns a tuple both ways
# --------------------------------------------------------------------------
def test_b10_empty_and_iterable_types():
    assert foundry.derive_execution_plan(()) == ()
    assert foundry.derive_execution_plan([]) == ()
    seq = foundry._default_stage_sequence()
    as_tuple = foundry.derive_execution_plan(tuple(seq))
    as_list = foundry.derive_execution_plan(list(seq))
    assert isinstance(as_tuple, tuple) and isinstance(as_list, tuple)
    assert as_tuple == as_list


# --------------------------------------------------------------------------
# B11 -- DORMANT / zero call site + iter-67 reuse (behavioral)
# --------------------------------------------------------------------------
NEW_SYMBOL_NAMES = ("derive_execution_plan", "StagePlan", "SEAT_GATE_KINDS")


def test_b11_zero_call_site():
    for fn in (foundry.run_iteration, foundry.run_continuous,
               foundry.run_stage, foundry.build_prompt):
        src = inspect.getsource(fn)
        for name in NEW_SYMBOL_NAMES:
            assert name not in src, (fn.__name__, name)
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for name in NEW_SYMBOL_NAMES:
        assert name not in dtext, name


def test_b11_import_ok_fresh_subprocess():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b11_iter67_symbols_reused_unchanged_behaviorally():
    # A tester in isolation does not read implementation source (past or present),
    # so iter-67 reuse is proven BEHAVIORALLY: the reused callables still produce
    # their iter-67 outputs. The byte-identical AST-vs-HEAD proof is the reviewer /
    # final gate's out-of-band job.
    seq = foundry.derive_stage_sequence(None)
    assert tuple(x.seat for x in seq) == CORE_SEATS
    for x in seq:
        assert (x.stage, x.role_file, x.out_file) == foundry.CORE_SEAT_STAGES[x.seat]
    assert dataclasses.is_dataclass(foundry.StageSpec)
    assert tuple(foundry.CORE_SEAT_STAGES) == foundry.MANIFEST_CORE_SEATS
    assert foundry._default_stage_sequence() == foundry.derive_stage_sequence(None)


# --------------------------------------------------------------------------
# B12 -- control-path byte-unchanged pin + leak/ASCII safety
# --------------------------------------------------------------------------
@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_b12_control_path_byte_unchanged():
    # `git diff --quiet` emits NO diff text (exit-code-only) -> honors isolation.
    # The main module legitimately grows this iter, so it is NOT pinned here; only
    # the dispatcher module + scripts/ (the control path) are pinned byte-unchanged.
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts NOT byte-unchanged from HEAD"


def test_b12_new_symbols_pure_ascii():
    # NEW symbols only (never a whole-file scan -- the module has pre-existing
    # non-ASCII em-dashes from prior iters that would false-fail).
    new_sources = [
        inspect.getsource(foundry.derive_execution_plan),
        inspect.getsource(foundry.StagePlan),
        inspect.getsource(foundry._gate_kind_for_seat),
        repr(foundry.SEAT_GATE_KINDS),
        repr(foundry.DEFAULT_GATE_KIND),
    ]
    for src in new_sources:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]
    # the whole new test file is pure ASCII too
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_b12_leak_clean_with_armed_matcher():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    module_text = pathlib.Path(foundry.__file__).read_text(encoding="utf-8")
    assert mod.scan_text(module_text, denylist) == (), "main module leaks a denylisted token"
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
