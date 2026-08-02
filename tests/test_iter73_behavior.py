"""Black-box behaviour tests for iter 73 -- item 20, bite 1 of ~4: the DORMANT
pure tri-perspective product-gate DETERMINISTIC pre-check
`product_gate_precheck(proposal_text) -> ProductGatePrecheck` (plus the frozen
`ProductGatePrecheck` dataclass with pure `passed`/`verdict`/`missing`
properties, three patchable module-level keyword constants
`GATE_{IMPACT,APPETITE,ALTERNATIVES}_KEYWORDS`, and the on-demand read-only
`foundry gate-precheck --file <proposal>` CLI). ZERO call site: nothing in the
pipeline invokes it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-12) and the product's own OBSERVABLE behaviour only (running it).
The implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.product_gate_precheck`,
the constants via `foundry.GATE_*_KEYWORDS`, and the CLI via
`foundry.main(["gate-precheck", "--file", ...])` with tmp-path proposal files
(the real repo is never touched). The dormancy / off-control-path checks use
only public RUNTIME introspection -- module attributes, compiled function
name tables (`__code__.co_names` recursed via `_co_names_deep`), `--help`
output, and a git `--quiet` exit-code probe -- plus, for the mechanical ASCII /
leak-clean acceptance criteria, `inspect.getsource` scoped to the NEW symbols
only (the established suite convention; never a whole-file scan / never
`git diff`). Fully offline and deterministic: real temp files only, NO
subprocess/git/network/agent-run except the fresh-import + `--help` regression
probes and the control-path byte-unchanged git `--quiet` probe.
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
    "product_gate_precheck",
    "ProductGatePrecheck",
    "GATE_IMPACT_KEYWORDS",
    "GATE_APPETITE_KEYWORDS",
    "GATE_ALTERNATIVES_KEYWORDS",
    "gate_precheck_cli",
)

# Fixed human labels for the failed checks, in the spec's FIXED order.
FIXED_MISSING_LABELS = ("impact number", "appetite", "alternatives")

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
    spec = importlib.util.spec_from_file_location("leak_guard_iter73_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(tmp_path, text, name="proposal.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# A structurally-complete PROCEED proposal reused by several behaviours.
_FULL = "Impact: 40% fewer stalls\nAppetite: 6 iterations\nAlternatives considered: none"


# ==========================================================================
# Behavior 1 -- pure, total, never-raises, offline, deterministic, frozen
# ==========================================================================
def test_b01_total_never_raises_and_typed():
    for text in ("", "   \n\t  ", "no structure here", _FULL, "impact 3\nappetite\nalternative"):
        r = foundry.product_gate_precheck(text)              # must not raise
        assert type(r).__name__ == "ProductGatePrecheck", (
            f"product_gate_precheck did not return a ProductGatePrecheck for {text[:20]!r}"
        )


def test_b01_deterministic_value_equality():
    for text in ("", "   ", _FULL, "Impact 40\nno appetite"):
        a = foundry.product_gate_precheck(text)
        b = foundry.product_gate_precheck(text)
        assert a == b, f"not deterministic / not value-equal for {text[:20]!r}"


def test_b01_frozen_dataclass():
    assert dataclasses.is_dataclass(foundry.ProductGatePrecheck)
    r = foundry.product_gate_precheck(_FULL)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.impact_present = False          # frozen -> mutation forbidden


def test_b01_no_filesystem_access(monkeypatch):
    """Pure: it opens no file. Sabotage builtins.open; the core still works."""
    def _boom(*a, **k):
        raise AssertionError("product_gate_precheck performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    r = foundry.product_gate_precheck(_FULL)
    assert r.passed is True and r.verdict == "PROCEED"


# ==========================================================================
# Behavior 2 -- IMPACT: keyword AND a digit on the SAME line
# ==========================================================================
def test_b02_impact_keyword_and_digit_same_line():
    r = foundry.product_gate_precheck("Impact: $40K ARR in year one")
    assert r.impact_present is True


# ==========================================================================
# Behavior 3 -- IMPACT negative: keyword but no digit on that line
# ==========================================================================
def test_b03_impact_keyword_without_number():
    r = foundry.product_gate_precheck("This has real impact.")
    assert r.impact_present is False


# ==========================================================================
# Behavior 4 -- IMPACT negative: digit but no impact keyword co-located
# ==========================================================================
def test_b04_number_without_impact_keyword():
    assert foundry.product_gate_precheck("We ship in 3 weeks.").impact_present is False


def test_b04_cross_line_keyword_and_digit_not_colocated():
    # keyword on one line, digit on ANOTHER line -> not co-located -> False
    r = foundry.product_gate_precheck("This has real impact.\nWe ship in 3 weeks.")
    assert r.impact_present is False


# ==========================================================================
# Behavior 5 -- APPETITE / ALTERNATIVES: keyword on any line, no digit needed
# ==========================================================================
def test_b05_appetite_and_alternatives_keyword_only():
    r = foundry.product_gate_precheck("Appetite: soon\nAlternatives: none")
    assert r.appetite_present is True
    assert r.alternatives_present is True


def test_b05_absent_keywords_are_false():
    r = foundry.product_gate_precheck("Impact: 40% win, nothing else stated")
    assert r.appetite_present is False
    assert r.alternatives_present is False


# ==========================================================================
# Behavior 6 -- passed == all three present -> PROCEED, missing == ()
# ==========================================================================
def test_b06_all_present_passes():
    r = foundry.product_gate_precheck(_FULL)
    assert r.passed is True
    assert r.verdict == "PROCEED"
    assert r.missing == ()


# ==========================================================================
# Behavior 7 -- verdict PROCEED iff passed else KILL (default-Kill)
# ==========================================================================
def test_b07_default_kill_when_any_check_fails():
    # drop the appetite line -> one check fails
    r = foundry.product_gate_precheck("Impact: 40% fewer stalls\nAlternatives: none")
    assert r.passed is False
    assert r.verdict == "KILL"


def test_b07_verdict_matches_passed():
    for text in ("", _FULL, "Impact: 40 win", "Appetite: yes\nAlternatives: no"):
        r = foundry.product_gate_precheck(text)
        assert r.verdict == ("PROCEED" if r.passed else "KILL")


# ==========================================================================
# Behavior 8 -- missing == failed labels in FIXED order, filtered
# ==========================================================================
def test_b08_missing_single_failed_impact():
    # appetite + alternatives present, no impact NUMBER -> only impact missing
    r = foundry.product_gate_precheck("Appetite: two\nAlternatives: none")
    assert r.missing == ("impact number",)


def test_b08_missing_empty_proposal_all_three():
    assert foundry.product_gate_precheck("").missing == FIXED_MISSING_LABELS


def test_b08_missing_fixed_order_subset():
    # impact present + alternatives present, appetite MISSING -> ("appetite",)
    r = foundry.product_gate_precheck("Impact: 40 gain\nAlternatives: none")
    assert r.missing == ("appetite",)
    # impact + appetite present, alternatives MISSING -> ("alternatives",)
    r2 = foundry.product_gate_precheck("Impact: 40 gain\nAppetite: soon")
    assert r2.missing == ("alternatives",)
    # impact + alternatives MISSING (appetite present) -> order preserved
    r3 = foundry.product_gate_precheck("Appetite: soon")
    assert r3.missing == ("impact number", "alternatives")


# ==========================================================================
# Behavior 9 -- case-insensitive (compare against line.lower())
# ==========================================================================
def test_b09_uppercase_passes_like_lowercase():
    upper = foundry.product_gate_precheck("IMPACT 40%\nAPPETITE: two weeks\nALTERNATIVES:")
    assert upper.passed is True
    assert upper.verdict == "PROCEED"
    lower = foundry.product_gate_precheck("impact 40%\nappetite: two weeks\nalternatives:")
    assert upper == lower


# ==========================================================================
# Behavior 10 -- keyword tuples read AT CALL TIME (monkeypatch a subsequent call)
# ==========================================================================
def test_b10_knobs_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "GATE_APPETITE_KEYWORDS", ("budget",))
    # "budget" now counts as appetite; "appetite" no longer does
    assert foundry.product_gate_precheck("Budget: 6 iterations").appetite_present is True
    assert foundry.product_gate_precheck("Appetite: 2 weeks").appetite_present is False
    # (monkeypatch auto-restores the global after the test)


def test_b10_default_constants_are_lowercase_tuples():
    for name in ("GATE_IMPACT_KEYWORDS", "GATE_APPETITE_KEYWORDS", "GATE_ALTERNATIVES_KEYWORDS"):
        val = getattr(foundry, name)
        assert isinstance(val, tuple) and val, f"{name} is not a non-empty tuple"
        assert all(isinstance(k, str) and k == k.lower() for k in val), f"{name} not lowercase strings"


# ==========================================================================
# Behavior 11 -- CLI exit codes + report tokens
# ==========================================================================
def test_b11_cli_proceed_exit0(tmp_path, capsys):
    p = _write(tmp_path, _FULL)
    rc = foundry.main(["gate-precheck", "--file", str(p)])
    out = capsys.readouterr().out
    assert rc == 0, f"PROCEED proposal returned {rc!r}, expected 0"
    assert "verdict: PROCEED" in out, f"report missing 'verdict: PROCEED':\n{out}"


def test_b11_cli_kill_exit1_names_missing(tmp_path, capsys):
    # a vague proposal missing all three
    p = _write(tmp_path, "Just a vague idea with no structure.")
    rc = foundry.main(["gate-precheck", "--file", str(p)])
    out = capsys.readouterr().out
    assert rc == 1, f"KILL proposal returned {rc!r}, expected 1"
    assert "verdict: KILL" in out, f"report missing 'verdict: KILL':\n{out}"
    # names the missing checks (the `missing` labels)
    core = foundry.product_gate_precheck(p.read_text())
    for label in core.missing:
        assert label in out, f"KILL report does not name missing label {label!r}:\n{out}"


def test_b11_cli_missing_file_exit2_no_exception(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.md"
    assert not missing.exists()
    rc = foundry.main(["gate-precheck", "--file", str(missing)])  # must NOT raise
    cap = capsys.readouterr()
    combined = cap.out + cap.err
    assert rc == 2, f"missing file returned {rc!r}, expected 2 (distinct from KILL=1)"
    assert str(missing) in combined, "not-found message does not include the offending path"


# ==========================================================================
# Behavior 12 -- CLI is a read-only THIN wrapper over the pure core
# ==========================================================================
def test_b12_cli_figures_match_core(tmp_path, capsys):
    for text in (_FULL,                                             # PROCEED
                 "Appetite: soon\nAlternatives: none",              # KILL (no impact number)
                 ""):                                               # KILL (all missing)
        p = _write(tmp_path, text, name="w.md")
        foundry.main(["gate-precheck", "--file", str(p)])
        out = capsys.readouterr().out
        core = foundry.product_gate_precheck(text)
        assert f"verdict: {core.verdict}" in out, (
            f"CLI verdict token disagrees with core.verdict ({core.verdict}):\n{out}"
        )
        # the CLI adds no pre-check logic: its printed missing labels match the core
        for label in core.missing:
            assert label in out, f"CLI does not surface core missing label {label!r}"


def test_b12_cli_writes_nothing_and_needs_no_config(tmp_path, capsys):
    p = _write(tmp_path, _FULL, name="only.md")
    before = sorted(x.name for x in tmp_path.iterdir())
    # no --config supplied (dispatched before load_config, like lint-spec)
    rc = foundry.main(["gate-precheck", "--file", str(p)])
    capsys.readouterr()
    after = sorted(x.name for x in tmp_path.iterdir())
    assert rc == 0
    assert before == after == ["only.md"], f"CLI wrote to disk: {before} -> {after}"


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_import_intact():
    assert callable(foundry.product_gate_precheck)
    assert callable(foundry.gate_precheck_cli)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    assert dispatcher is not None


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_help_lists_gate_precheck(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "gate-precheck" in out, f"gate-precheck missing from --help:\n{out}"
    for sub in ("run", "once", "doctor", "lint-spec"):
        assert sub in out, f"subcommand {sub!r} missing from --help (regression)"


def test_ac_dormant_zero_call_site():
    """No orchestrator and no dispatcher-module function references any new
    symbol by name (compiled name tables -- no source text read)."""
    new = set(NEW_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
    # dispatcher.py (control module) references none of the new symbols
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"


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
        inspect.getsource(foundry.product_gate_precheck),
        inspect.getsource(foundry.ProductGatePrecheck),
        inspect.getsource(foundry.gate_precheck_cli),
        repr(foundry.GATE_IMPACT_KEYWORDS),
        repr(foundry.GATE_APPETITE_KEYWORDS),
        repr(foundry.GATE_ALTERNATIVES_KEYWORDS),
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
