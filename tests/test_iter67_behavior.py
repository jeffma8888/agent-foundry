"""Black-box behaviour tests for iter 67 -- roadmap item 19, bite 1 of 2.

This bite adds a DORMANT, pure derivation core to the main foundry module: a
`CORE_SEAT_STAGES` constant, a frozen `StageSpec` dataclass, and
`derive_stage_sequence(manifest)` -- all with ZERO call site, so the running
pipeline is bit-for-bit unchanged and resume semantics are untouched. Bite 2
(a later iteration) wires the function in behind an absent-manifest ==
current-behavior guard.

ISOLATION CONTRACT (honored): every test below encodes the iter-67 PM spec's
Expected Behaviors (1-12), driven purely against the PUBLIC interface -- the
importable public callables/constants (foundry.derive_stage_sequence,
foundry.StageSpec, foundry.CORE_SEAT_STAGES, foundry.MANIFEST_CORE_SEATS), the
real shipped example manifest read via pathlib.Path(foundry.__file__), the
committed scripts/leak_guard.py public API, and inspect.getsource / the
dispatcher module's file text (used ONLY to assert the SPEC's dormancy Behavior
10 and the new-content-ASCII Behavior 11, both spec-mandated observables -- NOT
to mirror implementation logic). The engineer's / reviewer's notes and git diff
text were NOT read as design input; assertions encode the SPEC's behaviors, not
impl quirks. Fully offline & deterministic: no network, no real push. Every path
is built at RUNTIME from foundry.__file__ (never a source-literal home path), so
the committed leak-guard passes on the ship commit.

NB on Behavior 11 (pure ASCII): the spec's "new content is pure ASCII" clause
means the NEWLY-ADDED symbols, not the whole module -- the main module already
contains legitimate pre-existing non-ASCII (em-dash-dense docstrings from prior
iterations), so a whole-file ASCII scan would FALSE-fail. The new-content ASCII
property is checked here via inspect.getsource of the new symbols; the
authoritative ship-gate leak-cleanliness is checked via the committed leak-guard.

NB on Behavior 12: this file contains a `git diff --quiet` call, so per the
shipped iter-54 meta-scanner it must not carry the quoted main-module filename
token on any non-comment line. The main module is located via the BARE module's
__file__; it is NOT pinned byte-unchanged (it legitimately changes this iter).
Only the dispatcher module + scripts/ are pinned byte-unchanged (control path).
"""
import dataclasses
import importlib.util
import inspect
import json
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
STAFFING_JSON = _ROOT / "products" / "repolens" / "staffing.json"
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

CORE_SEATS = ("product_manager", "engineer", "reviewer", "qa_tester", "release_gate")
EXPECTED_CORE_SEAT_STAGES = {
    "product_manager": ("pm", "pm.md", "pm.md"),
    "engineer": ("engineer", "engineer.md", "engineer.md"),
    "reviewer": ("reviewer", "reviewer.md", "reviewer.md"),
    "qa_tester": ("tester", "tester.md", "tester.md"),
    "release_gate": ("final", "final.md", "final.md"),
}

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


def _role_obj(name):
    """A well-formed role object: string role/model/done_criteria + bool gate."""
    return {"role": name, "model": "builder-class model", "gate": False,
            "done_criteria": "criteria"}


def _manifest(names):
    return {"product": "x", "iteration_budget": 5,
            "roles": [_role_obj(n) for n in names]}


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter67_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# B1 -- importable public surface; StageSpec is a frozen dataclass
# --------------------------------------------------------------------------
def test_b1_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b1_public_surface_and_frozen_stagespec():
    assert callable(foundry.derive_stage_sequence)
    assert isinstance(foundry.CORE_SEAT_STAGES, dict)
    assert dataclasses.is_dataclass(foundry.StageSpec)
    inst = foundry.StageSpec(seat="a", stage="b", role_file="c", out_file="d")
    with pytest.raises(dataclasses.FrozenInstanceError):
        inst.seat = "changed"


# --------------------------------------------------------------------------
# B2 -- CORE_SEAT_STAGES exact + ordered, tuple == MANIFEST_CORE_SEATS
# --------------------------------------------------------------------------
def test_b2_core_seat_stages_exact_and_ordered():
    assert foundry.CORE_SEAT_STAGES == EXPECTED_CORE_SEAT_STAGES
    assert list(foundry.CORE_SEAT_STAGES.keys()) == list(EXPECTED_CORE_SEAT_STAGES.keys())
    assert tuple(foundry.CORE_SEAT_STAGES) == foundry.MANIFEST_CORE_SEATS


# --------------------------------------------------------------------------
# B3 -- derive_stage_sequence(None) is the fixed 5-core-seat default
# --------------------------------------------------------------------------
def test_b3_default_sequence_from_none():
    seq = foundry.derive_stage_sequence(None)
    assert isinstance(seq, tuple)
    assert len(seq) == 5
    assert all(isinstance(x, foundry.StageSpec) for x in seq)
    assert tuple(x.seat for x in seq) == CORE_SEATS
    for x in seq:
        assert (x.stage, x.role_file, x.out_file) == foundry.CORE_SEAT_STAGES[x.seat]


# --------------------------------------------------------------------------
# B4 -- core-only manifest == None (item-19 Done-when bullet 2)
# --------------------------------------------------------------------------
def test_b4_core_only_manifest_equals_none():
    mf = _manifest(CORE_SEATS)
    assert foundry.derive_stage_sequence(mf) == foundry.derive_stage_sequence(None)


# --------------------------------------------------------------------------
# B5 -- the real shipped example manifest == None
# --------------------------------------------------------------------------
def test_b5_real_shipped_manifest_equals_none():
    parsed = json.loads(STAFFING_JSON.read_text(encoding="utf-8"))
    assert foundry.derive_stage_sequence(parsed) == foundry.derive_stage_sequence(None)


# --------------------------------------------------------------------------
# B6 -- an extra seat inserts its stage at its declared position
#       (item-19 Done-when bullet 3)
# --------------------------------------------------------------------------
def test_b6_designer_inserted_at_declared_position():
    names = ["product_manager", "engineer", "designer",
             "reviewer", "qa_tester", "release_gate"]
    seq = foundry.derive_stage_sequence(_manifest(names))
    assert len(seq) == 6
    assert tuple(x.seat for x in seq) == tuple(names)
    assert seq[2] == foundry.StageSpec(
        seat="designer", stage="designer",
        role_file="bench/designer.md", out_file="designer.md")


# --------------------------------------------------------------------------
# B7 -- a trailing extra seat runs last (declared order is authoritative)
# --------------------------------------------------------------------------
def test_b7_trailing_extra_seat_runs_last():
    names = ["product_manager", "engineer", "reviewer",
             "qa_tester", "release_gate", "tpm"]
    seq = foundry.derive_stage_sequence(_manifest(names))
    assert tuple(x.seat for x in seq) == tuple(names)
    assert seq[-1] == foundry.StageSpec(
        seat="tpm", stage="tpm",
        role_file="bench/tpm.md", out_file="tpm.md")


# --------------------------------------------------------------------------
# B8 -- fail-safe: structurally-unusable manifest -> default, never raises.
#       All-or-nothing: one malformed role entry falls the whole thing back.
# --------------------------------------------------------------------------
FAILSAFE_INPUTS = [
    [1, 2],
    "roles",
    7,
    {},
    {"roles": "nope"},
    {"roles": []},
    {"roles": [42]},
    {"roles": [{"model": "m"}]},
    {"roles": [{"role": "engineer"}, 99]},
]


@pytest.mark.parametrize("bad", FAILSAFE_INPUTS)
def test_b8_failsafe_falls_back_to_default(bad):
    # If the function raised, pytest would error the test -> proves "never raises".
    assert foundry.derive_stage_sequence(bad) == foundry.derive_stage_sequence(None)


# --------------------------------------------------------------------------
# B9 -- no role-card file required; no observable I/O; deterministic
# --------------------------------------------------------------------------
def test_b9_no_card_file_required_and_deterministic():
    phantom = "phantom_seat_no_card"
    assert not (_ROOT / "roles" / "bench" / (phantom + ".md")).exists()
    seq = foundry.derive_stage_sequence(_manifest([phantom]))
    assert seq[0] == foundry.StageSpec(
        seat=phantom, stage=phantom,
        role_file="bench/" + phantom + ".md", out_file=phantom + ".md")
    mf = _manifest(["product_manager", "engineer", "designer"])
    assert foundry.derive_stage_sequence(mf) == foundry.derive_stage_sequence(mf)


# --------------------------------------------------------------------------
# B10 -- DORMANT / zero call site
# --------------------------------------------------------------------------
def test_b10_dormant_zero_call_site():
    for fn in (foundry.run_iteration, foundry.run_continuous,
               foundry.run_stage, foundry.build_prompt):
        src = inspect.getsource(fn)
        assert "derive_stage_sequence" not in src, fn.__name__
        assert "StageSpec" not in src, fn.__name__
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert "derive_stage_sequence" not in dtext
    assert "StageSpec" not in dtext


# --------------------------------------------------------------------------
# B11 -- leak-safe (ship-blocker) with an ARMED matcher + new content ASCII
# --------------------------------------------------------------------------
def test_b11_leak_clean_and_new_content_ascii():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    module_text = pathlib.Path(foundry.__file__).read_text(encoding="utf-8")
    assert mod.scan_text(module_text, denylist) == (), "main module leaks a denylisted token"
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
    # The NEW symbols' source is pure ASCII. (The whole module legitimately has
    # pre-existing non-ASCII, so we check only the newly-added content here, in
    # isolation via inspect.getsource -- never a whole-file scan / never git diff.)
    new_sources = [
        inspect.getsource(foundry.derive_stage_sequence),
        inspect.getsource(foundry.StageSpec),
        repr(foundry.CORE_SEAT_STAGES),
    ]
    for src in new_sources:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]
    # the whole new test file is pure ASCII
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


# --------------------------------------------------------------------------
# B12 -- control-path byte-unchanged pin + import
#
# The main module legitimately CHANGES this iter (the new dormant symbols), so
# it is NOT pinned byte-unchanged here (that would break the next iteration that
# extends it -- the iter-54 invariant). Its byte-unchanged status is verified
# out-of-band by the reviewer / final gate via numstat. What IS durable and
# pinned: the control path (the dispatcher module + guard scripts) stays
# byte-unchanged, and both modules still import.
# --------------------------------------------------------------------------
@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_b12_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts NOT byte-unchanged from HEAD"


def test_b12_import_foundry_and_dispatcher():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
