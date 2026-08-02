"""Black-box behaviour tests for iter 74 -- item 20, bite 2 of ~4: the DORMANT
pure tri-perspective product-gate verdict-AGGREGATION core
`aggregate_gate_verdict(business, product, engineering) -> ProductGateVerdict`
(plus the frozen `ProductGateVerdict` dataclass with fields
business/product/engineering + pure `verdict`/`killers`/`recyclers` properties,
three patchable module-level token constants
`GATE_{GO,KILL,RECYCLE}_TOKENS`, and the on-demand read-only
`foundry gate-verdict --business <v> --product <v> --engineering <v>` CLI).
ZERO call site: nothing in the pipeline invokes it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-12) and the product's own OBSERVABLE behaviour only (running it).
The implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.aggregate_gate_verdict`,
the constants via `foundry.GATE_*_TOKENS`, and the CLI via
`foundry.main(["gate-verdict", ...])`. The dormancy / off-control-path checks
use only public RUNTIME introspection -- module attributes, compiled function
name tables (`__code__.co_names` recursed via `_co_names_deep`), `--help`
output, and a git `--quiet` exit-code probe -- plus, for the mechanical ASCII /
leak-clean acceptance criteria, `inspect.getsource` scoped to the NEW symbols
only (the established suite convention; never a whole-file scan / never
`git diff`). Fully offline and deterministic: NO subprocess/git/network/agent-run
except the fresh-import + `--help` regression probes and the control-path
byte-unchanged git `--quiet` probe.
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
# runtime-built paths + constants (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The symbols this iteration ADDS. They must be dormant: no orchestrator and
# dispatcher.py reference any of them by name.
NEW_SYMBOLS = (
    "aggregate_gate_verdict",
    "ProductGateVerdict",
    "GATE_GO_TOKENS",
    "GATE_KILL_TOKENS",
    "GATE_RECYCLE_TOKENS",
    "gate_verdict_cli",
)

# The normalized verdict tokens (fixed) and the fixed seat order.
NORMALIZED_TOKENS = ("GO", "KILL", "RECYCLE")
SEAT_ORDER = ("business", "product", "engineering")

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
    spec = importlib.util.spec_from_file_location("leak_guard_iter74_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cli(args):
    """Drive the CLI via foundry.main, capturing exit code (never raises)."""
    return foundry.main(list(args))


def _gv(b, p, e):
    return foundry.aggregate_gate_verdict(b, p, e)


# ==========================================================================
# Behavior 1 -- pure, total, never-raises, offline, deterministic
# ==========================================================================
def test_b01_total_never_raises_and_typed():
    for b, p, e in (("", "", ""), ("go", "go", "go"), ("weird", "x", "y"),
                    ("  Go  ", "recycle", "nope"), ("KILL", "GO", "RECYCLE")):
        r = _gv(b, p, e)                                     # must not raise
        assert type(r).__name__ == "ProductGateVerdict", (
            f"aggregate_gate_verdict did not return a ProductGateVerdict for {(b, p, e)!r}"
        )


def test_b01_deterministic_value_equality():
    for b, p, e in (("", "", ""), ("go", "go", "go"), ("go", "kill", "recycle"),
                    ("  Go ", "recycle", "nope")):
        assert _gv(b, p, e) == _gv(b, p, e), f"not deterministic / value-equal for {(b, p, e)!r}"


def test_b01_no_filesystem_access(monkeypatch):
    """Pure: it opens no file. Sabotage builtins.open; the core still works."""
    def _boom(*a, **k):
        raise AssertionError("aggregate_gate_verdict performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    r = _gv("go", "go", "go")
    assert r.verdict == "GO"


# ==========================================================================
# Behavior 2 -- frozen dataclass, fields business/product/engineering
# ==========================================================================
def test_b02_frozen_dataclass_with_fields():
    assert dataclasses.is_dataclass(foundry.ProductGateVerdict)
    field_names = tuple(f.name for f in dataclasses.fields(foundry.ProductGateVerdict))
    for seat in SEAT_ORDER:
        assert seat in field_names, f"ProductGateVerdict missing field {seat!r}: {field_names}"
    r = _gv("go", "go", "go")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.business = "KILL"                                 # frozen -> forbidden


def test_b02_fields_hold_normalized_tokens():
    r = _gv("go", "kill", "recycle")
    for seat in SEAT_ORDER:
        assert getattr(r, seat) in NORMALIZED_TOKENS, (
            f"field {seat} = {getattr(r, seat)!r} is not one of {NORMALIZED_TOKENS}"
        )


# ==========================================================================
# Behavior 3 -- normalization is case-insensitive + whitespace-tolerant
# ==========================================================================
def test_b03_case_and_space_normalization():
    for raw in ("go", "GO", "  Go  ", "gO"):
        assert _gv(raw, "go", "go").business == "GO", f"{raw!r} did not normalize to GO"
    assert _gv("kill", "go", "go").business == "KILL"
    assert _gv("KILL", "go", "go").business == "KILL"
    assert _gv("recycle", "go", "go").business == "RECYCLE"
    assert _gv("Recycle", "go", "go").business == "RECYCLE"


# ==========================================================================
# Behavior 4 -- default-Kill on an unrecognized or empty seat verdict
# ==========================================================================
def test_b04_default_kill_on_unrecognized_or_empty():
    assert _gv("go", "maybe", "go").product == "KILL"
    assert _gv("go", "go", "").engineering == "KILL"
    # whitespace-only stripped-empty also unrecognized -> KILL
    assert _gv("   ", "go", "go").business == "KILL"


# ==========================================================================
# Behavior 5 -- stored fields are NORMALIZED tokens, not the raw input
# ==========================================================================
def test_b05_stored_fields_are_normalized_not_raw():
    r = _gv("  Go ", "recycle", "nope")
    assert r.business == "GO"
    assert r.product == "RECYCLE"
    assert r.engineering == "KILL"


# ==========================================================================
# Behavior 6/7 -- verdict aggregation by precedence; all-GO -> GO
# ==========================================================================
def test_b07_all_go_is_go():
    assert _gv("go", "go", "go").verdict == "GO"


# ==========================================================================
# Behavior 8 -- any-KILL dominates RECYCLE and GO
# ==========================================================================
def test_b08_any_kill_dominates():
    assert _gv("go", "kill", "recycle").verdict == "KILL"
    assert _gv("recycle", "recycle", "kill").verdict == "KILL"
    # unrecognized seat normalizes to KILL and therefore dominates too
    assert _gv("go", "maybe", "go").verdict == "KILL"


# ==========================================================================
# Behavior 9 -- no-KILL-with-RECYCLE -> RECYCLE
# ==========================================================================
def test_b09_recycle_when_no_kill_present():
    assert _gv("go", "recycle", "go").verdict == "RECYCLE"
    assert _gv("recycle", "go", "recycle").verdict == "RECYCLE"


def test_b06_precedence_is_total_over_all_combos():
    """verdict is KILL iff any seat KILL, else RECYCLE iff any RECYCLE, else GO."""
    seats = ("GO", "KILL", "RECYCLE")
    raw = {"GO": "go", "KILL": "kill", "RECYCLE": "recycle"}
    for b in seats:
        for p in seats:
            for e in seats:
                r = _gv(raw[b], raw[p], raw[e])
                toks = (b, p, e)
                expected = "KILL" if "KILL" in toks else ("RECYCLE" if "RECYCLE" in toks else "GO")
                assert r.verdict == expected, f"{toks} -> {r.verdict}, expected {expected}"


# ==========================================================================
# Behavior 10 -- killers/recyclers = seat NAMES in FIXED order; () when none
# ==========================================================================
def test_b10_killers_and_recyclers_rosters():
    r = _gv("kill", "go", "recycle")
    assert r.killers == ("business",)
    assert r.recyclers == ("engineering",)
    # all-GO -> both empty tuples
    g = _gv("go", "go", "go")
    assert g.killers == ()
    assert g.recyclers == ()


def test_b10_rosters_preserve_fixed_seat_order():
    # business + engineering KILL (product GO) -> fixed order preserved
    r = _gv("kill", "go", "kill")
    assert r.killers == ("business", "engineering")
    # product + engineering RECYCLE (business GO) -> no KILL so verdict RECYCLE
    r2 = _gv("go", "recycle", "recycle")
    assert r2.recyclers == ("product", "engineering")
    assert r2.killers == ()


# ==========================================================================
# Behavior 11 -- token tuples read AT CALL TIME (monkeypatch a subsequent call)
# ==========================================================================
def test_b11_knobs_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "GATE_GO_TOKENS", ("go", "approve"))
    r = _gv("approve", "go", "go")
    assert r.business == "GO"
    assert r.verdict == "GO"
    # (monkeypatch auto-restores the global after the test)


def test_b11_restore_reverts_behavior(monkeypatch):
    # with the default vocabulary, "approve" is unrecognized -> KILL
    assert _gv("approve", "go", "go").business == "KILL"


def test_b11_default_token_tuples_are_lowercase():
    expected = {
        "GATE_GO_TOKENS": ("go",),
        "GATE_KILL_TOKENS": ("kill",),
        "GATE_RECYCLE_TOKENS": ("recycle",),
    }
    for name, exp in expected.items():
        val = getattr(foundry, name)
        assert isinstance(val, tuple) and val, f"{name} is not a non-empty tuple"
        assert all(isinstance(t, str) and t == t.lower() for t in val), f"{name} not lowercase strings"
        assert val == exp, f"{name} default = {val!r}, expected {exp!r}"


# ==========================================================================
# Behavior 12 -- CLI exit codes 0/1/2 + report tokens + writes nothing
# ==========================================================================
def test_b12_cli_go_exit0(capsys):
    rc = _cli(["gate-verdict", "--business", "go", "--product", "go", "--engineering", "go"])
    out = capsys.readouterr().out
    assert rc == 0, f"all-GO returned {rc!r}, expected 0"
    assert "verdict: GO" in out, f"report missing 'verdict: GO':\n{out}"


def test_b12_cli_kill_exit1(capsys):
    rc = _cli(["gate-verdict", "--business", "go", "--product", "kill", "--engineering", "recycle"])
    out = capsys.readouterr().out
    assert rc == 1, f"any-KILL returned {rc!r}, expected 1"
    assert "verdict: KILL" in out, f"report missing 'verdict: KILL':\n{out}"
    # the killer seat name is surfaced; the recycler seat name too
    assert "product" in out, f"KILL report does not name the killer seat:\n{out}"
    assert "engineering" in out, f"KILL report does not name the recycler seat:\n{out}"


def test_b12_cli_recycle_exit2(capsys):
    rc = _cli(["gate-verdict", "--business", "go", "--product", "recycle", "--engineering", "go"])
    out = capsys.readouterr().out
    assert rc == 2, f"RECYCLE (no KILL) returned {rc!r}, expected 2"
    assert "verdict: RECYCLE" in out, f"report missing 'verdict: RECYCLE':\n{out}"


def test_b12_cli_prints_normalized_seats(capsys):
    _cli(["gate-verdict", "--business", "  Go ", "--product", "kill", "--engineering", "recycle"])
    out = capsys.readouterr().out
    # normalized tokens surface (not the raw "  Go ")
    for tok in ("GO", "KILL", "RECYCLE"):
        assert tok in out, f"normalized token {tok!r} missing from CLI output:\n{out}"


def test_b12_cli_none_roster_when_empty(capsys):
    _cli(["gate-verdict", "--business", "go", "--product", "go", "--engineering", "go"])
    out = capsys.readouterr().out
    # all-GO: both killers and recyclers rosters are empty -> "(none)"
    assert "(none)" in out, f"empty roster not rendered as '(none)':\n{out}"


def test_b12_cli_figures_match_core(capsys):
    exit_by_verdict = {"GO": 0, "KILL": 1, "RECYCLE": 2}
    for b, p, e in (("go", "go", "go"), ("go", "kill", "recycle"),
                    ("go", "recycle", "go"), ("go", "maybe", "go")):
        rc = _cli(["gate-verdict", "--business", b, "--product", p, "--engineering", e])
        out = capsys.readouterr().out
        core = _gv(b, p, e)
        assert f"verdict: {core.verdict}" in out, (
            f"CLI verdict token disagrees with core.verdict ({core.verdict}):\n{out}"
        )
        assert rc == exit_by_verdict[core.verdict], (
            f"CLI exit {rc!r} disagrees with core.verdict {core.verdict!r}"
        )


def test_b12_cli_writes_nothing_and_needs_no_config(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(x.name for x in tmp_path.iterdir())
    # no --config supplied (dispatched before load_config, like gate-precheck/lint-spec)
    rc = _cli(["gate-verdict", "--business", "go", "--product", "go", "--engineering", "go"])
    capsys.readouterr()
    after = sorted(x.name for x in tmp_path.iterdir())
    assert rc == 0
    assert before == after == [], f"CLI wrote to disk: {before} -> {after}"


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_import_intact():
    assert callable(foundry.aggregate_gate_verdict)
    assert callable(foundry.gate_verdict_cli)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    assert dispatcher is not None


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_help_lists_gate_verdict(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "gate-verdict" in out, f"gate-verdict missing from --help:\n{out}"
    for sub in ("run", "once", "doctor", "lint-spec", "gate-precheck"):
        assert sub in out, f"subcommand {sub!r} missing from --help (regression)"


def test_ac_dormant_zero_call_site():
    """No orchestrator and no dispatcher-module function references any new
    symbol by name (compiled name tables -- no source text read), nor names the
    `gate-verdict` command string."""
    new = set(NEW_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
    # dispatcher.py (control module) references none of the new symbols
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"
    assert "gate-verdict" not in dtext, "dispatcher.py names the 'gate-verdict' command string"


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_ac_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts NOT byte-unchanged from HEAD"


def test_ac_new_symbols_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 trap)."""
    new_sources = [
        inspect.getsource(foundry.aggregate_gate_verdict),
        inspect.getsource(foundry.ProductGateVerdict),
        inspect.getsource(foundry.gate_verdict_cli),
        repr(foundry.GATE_GO_TOKENS),
        repr(foundry.GATE_KILL_TOKENS),
        repr(foundry.GATE_RECYCLE_TOKENS),
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
