"""Black-box behaviour tests for iter 76 -- item 20, bite 4a of ~5: the DORMANT
pure COMPOSITE product-gate DECISION core
`decide_product_gate(proposal_text, business, product, engineering)
-> ProductGateDecision`
(plus the frozen `ProductGateDecision` dataclass with fields `precheck` +
`seats` and pure props `bounced` / `verdict`, and the on-demand read-only
`foundry product-gate --file <proposal> --business/--product/--engineering`
CLI). The composite folds the two shipped cores -- the deterministic
`product_gate_precheck` (iter 73) and the seat aggregation
`aggregate_gate_verdict` (iter 74) -- in the ORG_DESIGN section-6 ORDER: run the
free pre-check FIRST, and consult the three seats only if it passes. ZERO call
site: nothing in the pipeline invokes it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-13) and the product's own OBSERVABLE behaviour only (running it).
The implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure composite via `foundry.decide_product_gate`
(and the two reused cores `foundry.product_gate_precheck` /
`foundry.aggregate_gate_verdict` for value-equality anchoring), the patchable
knobs via their module attributes, and the CLI via
`foundry.main(["product-gate", ...])`. The dormancy / off-control-path checks use
only public RUNTIME introspection -- module attributes, compiled function name
tables (`__code__.co_names` recursed via `_co_names_deep`), `--help` output, and
a git `--quiet` exit-code probe -- plus, for the mechanical ASCII / leak-clean
acceptance criteria, `inspect.getsource` scoped to the NEW symbols only (the
established suite convention; never a whole-file scan / never `git diff`). Fully
offline and deterministic: NO subprocess/git/network/agent-run except the
fresh-import + `--help` regression probes and the control-path byte-unchanged
git `--quiet` probe. The dormancy proof is scoped to the SYMBOLS (not the
`product-gate` command string, which false-matches pre-existing comments).
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

# The symbols this iteration ADDS. They must be dormant: no orchestrator and
# dispatcher.py reference any of them by name.
NEW_SYMBOLS = (
    "decide_product_gate",
    "ProductGateDecision",
    "product_gate_cli",
)

# A proposal that PASSES the deterministic pre-check: an impact keyword
# co-located with a number on one line, a stated appetite, and a listed
# alternative. (Grounded against the OBSERVED pre-check behaviour, not source.)
GOOD = (
    "Impact: this saves 40 percent of latency and 2000000 dollars annually.\n"
    "Appetite: we can commit 3 weeks to this bet.\n"
    "Alternatives: we considered option A instead and rejected it.\n"
)
# A proposal that FAILS the pre-check (missing everything).
BAD = ""

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
    spec = importlib.util.spec_from_file_location("leak_guard_iter76_probe", gp)
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


def _d(text, b, p, e):
    return foundry.decide_product_gate(text, b, p, e)


def _write(tmp_path, text, name="proposal.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ==========================================================================
# Behavior 1 -- pure, total, never-raises, offline, deterministic
# ==========================================================================
def test_b01_total_never_raises_and_typed():
    cases = [
        ("", "", "", ""),
        (GOOD, "go", "go", "go"),
        (BAD, "kill", "recycle", "go"),
        ("random prose with no structure", "maybe", "", "  "),
        (GOOD, "  GO  ", "Recycle", "KILL"),
    ]
    for text, b, p, e in cases:
        r = _d(text, b, p, e)  # must not raise
        assert type(r).__name__ == "ProductGateDecision", (
            f"decide_product_gate did not return ProductGateDecision for {(text, b, p, e)!r}"
        )


def test_b01_deterministic_value_equality():
    for args in ((GOOD, "go", "go", "go"), (BAD, "kill", "go", "go"), ("", "", "", "")):
        assert _d(*args) == _d(*args), f"not deterministic / value-equal for {args!r}"


def test_b01_no_filesystem_access(monkeypatch):
    """Pure: the core opens no file. Sabotage builtins.open; it still works."""
    def _boom(*a, **k):
        raise AssertionError("decide_product_gate performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    r = _d(GOOD, "go", "go", "go")
    assert r.verdict == "GO"
    assert r.bounced is False


def test_b01_all_empty_never_raises():
    r = _d("", "", "", "")
    assert r.verdict == "KILL"
    assert r.seats is None


# ==========================================================================
# Behavior 2 -- frozen ProductGateDecision with fields precheck, seats
# ==========================================================================
def test_b02_frozen_dataclass_exact_fields():
    assert dataclasses.is_dataclass(foundry.ProductGateDecision)
    field_names = tuple(f.name for f in dataclasses.fields(foundry.ProductGateDecision))
    assert field_names == ("precheck", "seats"), (
        f"ProductGateDecision fields = {field_names}, expected ('precheck', 'seats')"
    )
    r = _d(GOOD, "go", "go", "go")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.precheck = None
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.seats = None


# ==========================================================================
# Behavior 3 -- precheck field equals a direct PGP(text) call
# ==========================================================================
def test_b03_precheck_equals_direct_pgp_passing():
    r = _d(GOOD, "go", "go", "go")
    assert r.precheck == foundry.product_gate_precheck(GOOD), (
        "composite .precheck != direct product_gate_precheck(text)"
    )


def test_b03_precheck_equals_direct_pgp_failing():
    r = _d(BAD, "go", "go", "go")
    assert r.precheck == foundry.product_gate_precheck(BAD)
    # partial proposals too: only appetite present, no impact number / alternative
    partial = "Appetite: two weeks.\n"
    assert _d(partial, "go", "go", "go").precheck == foundry.product_gate_precheck(partial)


# ==========================================================================
# Behavior 4 -- bounce-for-free: failing pre-check -> seats None, bounced True
# ==========================================================================
def test_b04_bounce_for_free_seats_is_none():
    r = _d(BAD, "go", "go", "go")
    assert r.precheck.passed is False, "fixture BAD unexpectedly passed the pre-check"
    assert r.seats is None, "seat aggregation was computed on a failing pre-check (not bounced-for-free)"
    assert r.bounced is True


def test_b04_bounce_for_free_ignores_positive_seat_args():
    # even with three GO seats, a failing pre-check bounces (seats never consulted)
    r = _d(BAD, "go", "go", "go")
    assert r.seats is None
    assert r.verdict == "KILL"


# ==========================================================================
# Behavior 5 -- passing pre-check -> seats == direct AGV, bounced False
# ==========================================================================
def test_b05_passing_seats_equals_direct_agv():
    for combo in (("go", "go", "go"), ("go", "kill", "go"), ("go", "recycle", "go"), ("maybe", "go", "go")):
        r = _d(GOOD, *combo)
        assert r.precheck.passed is True
        assert r.bounced is False
        assert r.seats == foundry.aggregate_gate_verdict(*combo), (
            f"composite .seats != direct aggregate_gate_verdict{combo}"
        )


# ==========================================================================
# Behavior 6 -- bounced iff precheck.passed is False (== seats is None)
# ==========================================================================
def test_b06_bounced_iff_precheck_failed():
    passing = _d(GOOD, "go", "go", "go")
    assert passing.bounced == (passing.precheck.passed is False) == (passing.seats is None) == False
    failing = _d(BAD, "go", "go", "go")
    assert failing.bounced == (failing.precheck.passed is False) == (failing.seats is None) == True


# ==========================================================================
# Behavior 7 -- verdict property matrix
# ==========================================================================
def test_b07_verdict_is_kill_when_bounced_regardless_of_seats():
    for combo in (("go", "go", "go"), ("recycle", "recycle", "recycle"), ("kill", "go", "go"), ("", "", "")):
        assert _d(BAD, *combo).verdict == "KILL", (
            f"failing pre-check with seats {combo} did not yield KILL"
        )


def test_b07_verdict_passing_matrix():
    assert _d(GOOD, "go", "go", "go").verdict == "GO"
    # any seat normalizing to KILL -> KILL
    assert _d(GOOD, "go", "kill", "go").verdict == "KILL"
    assert _d(GOOD, "kill", "go", "go").verdict == "KILL"
    # a RECYCLE seat with no KILL -> RECYCLE
    assert _d(GOOD, "go", "recycle", "go").verdict == "RECYCLE"
    # an unrecognized seat is default-KILL (inherited from AGV)
    assert _d(GOOD, "maybe", "go", "go").verdict == "KILL"


def test_b07_verdict_equals_seats_verdict_when_passing():
    for combo in (("go", "go", "go"), ("go", "kill", "go"), ("go", "recycle", "go")):
        r = _d(GOOD, *combo)
        assert r.verdict == r.seats.verdict


def test_b07_verdict_in_allowed_set():
    for text in (GOOD, BAD):
        for combo in (("go", "go", "go"), ("go", "recycle", "go"), ("kill", "go", "go")):
            assert _d(text, *combo).verdict in ("GO", "KILL", "RECYCLE")


# ==========================================================================
# Behavior 8 -- composite honors CALL-TIME knob reads of its reused cores
# ==========================================================================
def test_b08_seat_token_knob_read_at_call_time(monkeypatch):
    # "yes" is not a GO token by default -> KILL; patch GATE_GO_TOKENS to include it
    assert _d(GOOD, "yes", "yes", "yes").verdict == "KILL"
    monkeypatch.setattr(foundry, "GATE_GO_TOKENS", ("go", "yes"))
    assert _d(GOOD, "yes", "yes", "yes").verdict == "GO", (
        "monkeypatched GATE_GO_TOKENS not honored at call time by the composite"
    )


def test_b08_seat_token_knob_restore_reverts():
    # after the previous test restores GATE_GO_TOKENS, "yes" is not a GO token again
    assert _d(GOOD, "yes", "yes", "yes").verdict == "KILL"


def test_b08_precheck_keyword_knob_read_at_call_time(monkeypatch):
    # GOOD passes by default; patch the appetite keyword vocabulary to something
    # absent -> the pre-check now fails -> the composite bounces (seats None)
    assert _d(GOOD, "go", "go", "go").bounced is False
    monkeypatch.setattr(foundry, "GATE_APPETITE_KEYWORDS", ("zzzabsentkeyword",))
    r = _d(GOOD, "go", "go", "go")
    assert r.bounced is True, "monkeypatched GATE_APPETITE_KEYWORDS not honored at call time"
    assert r.seats is None
    assert r.verdict == "KILL"


def test_b08_precheck_keyword_knob_restore_reverts():
    assert _d(GOOD, "go", "go", "go").bounced is False


# ==========================================================================
# Behavior 9 -- CLI missing file: exit 3, names path, no FileNotFoundError, writes nothing
# ==========================================================================
def test_b09_cli_missing_file_exit3(tmp_path):
    missing = str(tmp_path / "does_not_exist.txt")
    rc, out = _cli(["product-gate", "--file", missing,
                    "--business", "go", "--product", "go", "--engineering", "go"])
    assert rc == 3, f"missing file returned {rc!r}, expected 3\n{out}"
    assert "file not found" in out.lower(), f"missing-file message absent:\n{out}"
    assert missing in out, f"missing-file message did not name the path:\n{out}"


def test_b09_cli_missing_file_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(x.name for x in tmp_path.iterdir())
    missing = str(tmp_path / "nope.txt")
    rc, _ = _cli(["product-gate", "--file", missing,
                  "--business", "go", "--product", "go", "--engineering", "go"])
    after = sorted(x.name for x in tmp_path.iterdir())
    assert rc == 3
    assert before == after, f"CLI wrote to disk on missing file: {before} -> {after}"


# ==========================================================================
# Behavior 10 -- CLI present file: prints figures + rosters/bounced note + verdict line, writes nothing
# ==========================================================================
def test_b10_cli_present_go_prints_figures_rosters_and_verdict(tmp_path):
    p = _write(tmp_path, GOOD)
    rc, out = _cli(["product-gate", "--file", str(p),
                    "--business", "go", "--product", "go", "--engineering", "go"])
    assert rc == 0
    low = out.lower()
    # pre-check present/missing figures appear
    assert "impact" in low and "appetite" in low and "alternative" in low
    # seat verdicts + rosters appear when seats is not None
    assert "killers" in low and "recyclers" in low, f"rosters missing:\n{out}"
    # the seat verdicts are surfaced (all three GO)
    assert out.count("GO") >= 3, f"seat GO verdicts not surfaced:\n{out}"
    # final verdict line
    assert "verdict: GO" in out, f"final verdict line missing/wrong:\n{out}"


def test_b10_cli_present_kill_surfaces_killer(tmp_path):
    p = _write(tmp_path, GOOD)
    rc, out = _cli(["product-gate", "--file", str(p),
                    "--business", "go", "--product", "kill", "--engineering", "go"])
    assert rc == 1
    assert "verdict: KILL" in out, f"verdict line wrong:\n{out}"
    assert "product" in out.lower(), f"killer seat not surfaced:\n{out}"


def test_b10_cli_bounced_prints_bounced_note(tmp_path):
    p = _write(tmp_path, BAD)
    rc, out = _cli(["product-gate", "--file", str(p),
                    "--business", "go", "--product", "go", "--engineering", "go"])
    assert rc == 1
    assert "verdict: KILL" in out, f"bounced verdict line wrong:\n{out}"
    # a bounced proposal surfaces a bounced / pre-check-failed indication, NOT seat rosters
    assert "bounce" in out.lower() or "pre-check" in out.lower(), (
        f"bounced note absent for a failing pre-check:\n{out}"
    )


def test_b10_cli_present_file_matches_decision(tmp_path):
    # the CLI is a THIN wrapper: its printed verdict matches the pure core
    for combo in (("go", "go", "go"), ("go", "kill", "go"), ("go", "recycle", "go")):
        p = _write(tmp_path, GOOD, name="p_" + "_".join(combo) + ".txt")
        rc, out = _cli(["product-gate", "--file", str(p),
                        "--business", combo[0], "--product", combo[1], "--engineering", combo[2]])
        expected = _d(GOOD, *combo).verdict
        assert f"verdict: {expected}" in out, f"CLI verdict != core verdict {expected}:\n{out}"


def test_b10_cli_present_file_writes_nothing(tmp_path, monkeypatch):
    p = _write(tmp_path, GOOD)
    before = sorted(x.name for x in tmp_path.iterdir())
    rc, _ = _cli(["product-gate", "--file", str(p),
                  "--business", "go", "--product", "go", "--engineering", "go"])
    after = sorted(x.name for x in tmp_path.iterdir())
    assert rc == 0
    assert before == after, f"CLI wrote/removed a file: {before} -> {after}"


# ==========================================================================
# Behavior 11 -- CLI exit-code map: 0 GO / 1 KILL / 2 RECYCLE / 3 file-not-found
# ==========================================================================
def test_b11_cli_exit_map_present_file(tmp_path):
    good = _write(tmp_path, GOOD, name="good.txt")
    expect = {
        ("go", "go", "go"): 0,          # GO
        ("go", "kill", "go"): 1,        # KILL
        ("go", "recycle", "go"): 2,     # RECYCLE
    }
    for combo, code in expect.items():
        rc, out = _cli(["product-gate", "--file", str(good),
                        "--business", combo[0], "--product", combo[1], "--engineering", combo[2]])
        assert rc == code, f"seats {combo} returned {rc!r}, expected {code}\n{out}"


def test_b11_cli_bounced_returns_1(tmp_path):
    bad = _write(tmp_path, BAD, name="bad.txt")
    rc, out = _cli(["product-gate", "--file", str(bad),
                    "--business", "go", "--product", "go", "--engineering", "go"])
    assert rc == 1, f"bounced (pre-check-failing) proposal returned {rc!r}, expected 1 (KILL)\n{out}"


def test_b11_cli_exit_map_agrees_with_core(tmp_path):
    good = _write(tmp_path, GOOD, name="g.txt")
    code_of = {"GO": 0, "KILL": 1, "RECYCLE": 2}
    for combo in (("go", "go", "go"), ("kill", "go", "go"), ("go", "recycle", "go"), ("maybe", "go", "go")):
        rc, _ = _cli(["product-gate", "--file", str(good),
                      "--business", combo[0], "--product", combo[1], "--engineering", combo[2]])
        assert rc == code_of[_d(GOOD, *combo).verdict], f"exit code disagrees with core for {combo}"


# ==========================================================================
# Behavior 12 -- --help lists product-gate and all prior subcommands
# ==========================================================================
def test_b12_help_lists_product_gate_and_prior_subcommands(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "product-gate" in out, f"product-gate missing from --help:\n{out}"
    for sub in ("run", "once", "doctor", "lint-spec", "gate-precheck", "gate-verdict", "role-model"):
        assert sub in out, f"subcommand {sub!r} missing from --help (regression)"


# ==========================================================================
# Behavior 13 -- DORMANT / zero call site
# ==========================================================================
def test_b13_dormant_zero_call_site():
    """No orchestrator and no dispatcher-module reference references any new
    symbol by name (compiled name tables -- no source text read), nor names the
    `product-gate` command string in dispatcher.py. The composite reuses the
    shipped cores, giving them a new NON-orchestrator caller, but the new symbols
    stay absent from the orchestrators, so iter-73/iter-74 dormancy tests hold."""
    new = set(NEW_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"
    assert "product-gate" not in dtext, "dispatcher.py names the 'product-gate' command string"


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_import_intact():
    assert callable(foundry.decide_product_gate)
    assert callable(foundry.product_gate_cli)
    assert dataclasses.is_dataclass(foundry.ProductGateDecision)
    # the reused shipped cores remain present
    assert callable(foundry.product_gate_precheck)
    assert callable(foundry.aggregate_gate_verdict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    assert dispatcher is not None


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
        inspect.getsource(foundry.decide_product_gate),
        inspect.getsource(foundry.ProductGateDecision),
        inspect.getsource(foundry.product_gate_cli),
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
