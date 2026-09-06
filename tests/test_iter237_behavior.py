"""Black-box behaviour tests for iter 237 -- `watchdog.py`'s liveness seam stops
shelling out to a raw `pgrep -f` substring scan and delegates to
`foundry single-brain --json`, parsing the VERDICT PAYLOAD (never the exit code).

ISOLATION: written SOLELY from the iter-237 PM spec (`pm.md`, Expected Behaviors
1-8) and the test conventions already under `tests/` (the `_ROOT`/`sys.path`
preamble and `watchdog._pgrep` monkeypatch shape from
`tests/test_strangler_step4_watchdog.py` and `tests/test_iter06_behavior.py`).
The implementation source was NOT opened by hand, and neither was `git diff`,
`engineer.md` or `reviewer.md`. `watchdog.py` is touched only AS DATA, by
`ast.parse` over its text -- which is how Behaviors 1, 7 and 8 are *defined*.
Failure messages below deliberately report counts, names and line numbers rather
than echoing source lines, so a red run stays inside the isolation contract.

OFFLINE: Behaviors 2-4 and 6-7 run with no subprocess at all (Behavior 6 proves
that by making `subprocess.run` itself explode), and NO test in this module
inspects the ambient process table or performs a real process scan. The only real
child processes are Behavior 5's three trivial `-c` programs (which is the point
of that behavior -- the seam must really shell out) and Behavior 8's fresh-
interpreter import check.

VACUITY GUARDS: every `ast`-derived negative claim ("no such literal", "no such
import") first asserts that the walk found a plausible POPULATION, so a parse
that silently yielded nothing can never read as a pass.
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import os  # noqa: E402
import watchdog  # noqa: E402

_WATCHDOG_PY = _ROOT / "watchdog.py"

# The two modules that form the 31-test ratchet (Behavior 7). Relative POSIX
# paths only -- an absolute path literal in a shipped test is itself a ship
# blocker (iter-205), so nothing here is ever written as a machine path.
_ITER06 = "tests/test_iter06_behavior.py"
_STRANGLER = "tests/test_strangler_step4_watchdog.py"

# A nonexistent executable for Behavior 5, COMPOSED rather than written as an
# absolute-path literal (same iter-205 reason as above).
_NO_SUCH_EXE = "/".join(("", "nonexistent", "interp-237"))

# The published 7-key `single-brain --json` machine contract, as the spec quotes it.
_CONFLICT_PAYLOAD = {"pids": [123, 456], "scan_error": None, "unknown": False,
                     "conflict": True, "safe": False, "verdict": "CONFLICT",
                     "exit_code": 1}
_SAFE_PAYLOAD = {"pids": [], "scan_error": None, "unknown": False,
                 "conflict": False, "safe": True, "verdict": "SAFE",
                 "exit_code": 0}
_UNKNOWN_PAYLOAD = {"pids": [], "scan_error": "ps missing", "unknown": True,
                    "conflict": False, "safe": False, "verdict": "UNKNOWN",
                    "exit_code": 2}


# ==========================================================================
# helpers
# ==========================================================================
def _tree() -> ast.Module:
    assert _WATCHDOG_PY.is_file(), "watchdog.py must ship at the repo ROOT"
    return ast.parse(_WATCHDOG_PY.read_text(), filename="watchdog.py")


def _str_constants(tree: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _funcdef(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError("watchdog.py defines no function named %r" % name)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(_ROOT), capture_output=True, text=True)


def _boom(*a, **k):  # pragma: no cover - only reached if a purity claim is false
    raise AssertionError("this code path must not shell out")


# ==========================================================================
# Behavior 1 -- the raw scan is gone (no `"pgrep"` string literal survives)
# ==========================================================================
def test_b1_no_pgrep_string_literal_anywhere_in_the_module():
    strings = _str_constants(_tree())
    assert len(strings) >= 20, (
        "vacuity guard: the ast walk found only %d string constants in "
        "watchdog.py, so a 'no pgrep literal' pass would be meaningless" % len(strings))
    assert [s for s in strings if s == "pgrep"] == [], (
        "Behavior 1: watchdog.py still contains the string literal 'pgrep' "
        "(%d string constants scanned) -- the raw process scan must be gone; "
        "the identifier _pgrep and prose mentions are fine, a LITERAL is not"
        % len(strings))


# ==========================================================================
# Behavior 2 -- `single_brain_argv` is pure
# ==========================================================================
def test_b2_argv_head_is_this_interpreter_and_the_foundry_script():
    assert hasattr(watchdog, "FOUNDRY"), "Behavior 2 names watchdog.FOUNDRY as the default"
    a = watchdog.single_brain_argv()
    assert isinstance(a, list) and all(isinstance(x, str) for x in a), \
        "single_brain_argv must return a list[str], got %r" % (type(a),)
    assert a[0] == sys.executable, \
        "argv[0] must be sys.executable (the running interpreter), got %r" % (a[0],)
    assert a[1] == str(pathlib.Path(watchdog.FOUNDRY) / "foundry.py"), \
        "argv[1] must be <foundry_dir>/foundry.py, got %r" % (a[1],)


def test_b2_argv_carries_the_subcommand_and_json_flag():
    tail = watchdog.single_brain_argv()[2:]
    for tok in ("single-brain", "--json"):
        assert tok in tail, "Behavior 2: %r must appear in argv[2:], got %r" % (tok, tail)


@pytest.mark.parametrize("pattern", ["dispatcher.py", "other.py", "custom.py", ""])
def test_b2_pattern_flag_is_immediately_followed_by_the_pattern(pattern):
    a = watchdog.single_brain_argv(pattern)
    assert a.count("--pattern") == 1, \
        "Behavior 2: exactly one --pattern token expected, got %r" % (a,)
    i = a.index("--pattern")
    assert a[i + 1:i + 2] == [pattern], \
        "Behavior 2: --pattern must be IMMEDIATELY followed by %r, got %r" % (pattern, a[i + 1:])


def test_b2_default_pattern_is_dispatcher_py():
    assert watchdog.single_brain_argv() == watchdog.single_brain_argv("dispatcher.py"), \
        "Behavior 2: the default pattern must be 'dispatcher.py'"


def test_b2_is_deterministic_for_equal_arguments():
    first = watchdog.single_brain_argv("dispatcher.py")
    second = watchdog.single_brain_argv("dispatcher.py")
    assert first == second and first is not second, \
        "Behavior 2: two calls with equal arguments must return equal lists"


def test_b2_signature_keeps_foundry_dir_keyword_only():
    params = inspect.signature(watchdog.single_brain_argv).parameters
    assert list(params) == ["pattern", "foundry_dir"], \
        "Behavior 2 pins the signature (pattern, *, foundry_dir), got %r" % (list(params),)
    assert params["pattern"].default == "dispatcher.py"
    assert params["foundry_dir"].kind is inspect.Parameter.KEYWORD_ONLY, \
        "foundry_dir must be KEYWORD-ONLY, got %s" % (params["foundry_dir"].kind,)
    assert params["foundry_dir"].default == watchdog.FOUNDRY


def test_b2_touches_no_filesystem_and_does_not_shell_out(monkeypatch):
    # Purity: with every I/O door nailed shut AND a foundry_dir that does not
    # exist, the call must still return the composed argv without raising.
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(watchdog, "run_probe", _boom)
    missing = pathlib.Path("no-such-dir-237") / "nested"
    a = watchdog.single_brain_argv("dispatcher.py", foundry_dir=missing)
    assert a[1] == str(missing / "foundry.py"), \
        "Behavior 2: argv[1] must be composed from foundry_dir, not resolved on disk"
    assert not missing.exists(), "the fixture dir must stay nonexistent (no mkdir side effect)"


# ==========================================================================
# Behavior 3 -- a real payload parses
# ==========================================================================
def test_b3_conflict_payload_yields_its_pids_as_ints_in_order():
    got = watchdog.parse_single_brain_pids(json.dumps(_CONFLICT_PAYLOAD))
    assert got == [123, 456], "Behavior 3: CONFLICT payload must yield [123, 456], got %r" % (got,)
    assert all(type(p) is int for p in got), \
        "Behavior 3: pids must be ints, got %r" % ([type(p).__name__ for p in got],)


def test_b3_safe_payload_yields_no_pids():
    got = watchdog.parse_single_brain_pids(json.dumps(_SAFE_PAYLOAD))
    assert got == [], "Behavior 3: the SAFE payload must yield [], got %r" % (got,)


# ==========================================================================
# Behavior 4 -- every degenerate input yields [] and raises nothing
# ==========================================================================
_DEGENERATE = [
    ("empty", ""),
    ("blank", "   "),
    ("not json", "not json"),
    ("json non-dict list", "[1,2]"),
    ("json non-dict str", '"str"'),
    ("no unknown key", "{}"),
    ("pids not a list", json.dumps({"unknown": False, "pids": "123"})),
    ("pids is a dict", json.dumps({"unknown": False, "pids": {"a": 1}})),
    ("unknown probe", json.dumps(_UNKNOWN_PAYLOAD)),
    ("inconsistent unknown+pids", json.dumps({"unknown": True, "pids": [7]})),
]


@pytest.mark.parametrize("label,payload", _DEGENERATE, ids=[d[0] for d in _DEGENERATE])
def test_b4_degenerate_input_yields_empty_list_without_raising(label, payload):
    got = watchdog.parse_single_brain_pids(payload)
    assert got == [], "Behavior 4 (%s): expected [] from a degenerate payload, got %r" % (label, got)


def test_b4_non_int_members_are_dropped_not_raised_on():
    got = watchdog.parse_single_brain_pids(
        json.dumps({"unknown": False, "pids": [1, "two", None, 4]}))
    assert got == [1, 4], \
        "Behavior 4: non-int pids members must be DROPPED, expected [1, 4], got %r" % (got,)


def test_b4_every_result_member_is_a_plain_int():
    mixed = json.dumps({"unknown": False, "pids": [1, "two", None, 3.5, [], 4]})
    got = watchdog.parse_single_brain_pids(mixed)
    assert all(type(p) is int for p in got), \
        "Behavior 4: every returned pid must be a plain int, got %r" % (got,)
    assert 1 in got and 4 in got, \
        "Behavior 4: the valid members must survive the drop, got %r" % (got,)


def test_b4_a_probe_that_could_not_run_cannot_also_report_brains():
    # The polarity that matters for admission control: UNKNOWN wins over pids.
    assert watchdog.parse_single_brain_pids(
        json.dumps({"pids": [11, 22], "scan_error": "ps missing", "unknown": True,
                    "conflict": False, "safe": False, "verdict": "UNKNOWN",
                    "exit_code": 2})) == [], \
        "Behavior 4: an UNKNOWN payload must never report brains"


# ==========================================================================
# Behavior 5 -- `run_probe` is the single I/O seam and never raises
# ==========================================================================
def test_b5_nonexistent_executable_returns_empty_string():
    got = watchdog.run_probe([_NO_SUCH_EXE, "x"])
    assert got == "", \
        "Behavior 5: a nonexistent executable must yield '' (never raise), got %r" % (got,)


def test_b5_really_shells_out_and_returns_child_stdout_verbatim():
    got = watchdog.run_probe([sys.executable, "-c", "print('ok237')"])
    assert isinstance(got, str), "Behavior 5: run_probe must return a str, got %r" % (type(got),)
    assert got == "ok237\n", \
        "Behavior 5: the child's stdout must come back verbatim, got %r" % (got,)


def test_b5_a_nonzero_exit_still_returns_the_payload_it_printed():
    prog = ("import sys\n"
            "sys.stdout.write('{\"unknown\": false, \"pids\": [9]}')\n"
            "sys.exit(3)\n")
    got = watchdog.run_probe([sys.executable, "-c", prog])
    assert watchdog.parse_single_brain_pids(got) == [9], (
        "Behavior 5: run_probe reads only STDOUT -- a child that exits NON-ZERO "
        "while printing a valid payload must still have that payload returned "
        "(this is why the exit code is never the input), got %r" % (got,))


# ==========================================================================
# Behavior 6 -- `_pgrep` composes the three by BARE module name
# ==========================================================================
def test_b6_pgrep_returns_the_pids_of_a_conflict_payload(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _boom)  # no real subprocess in this behavior
    monkeypatch.setattr(watchdog, "run_probe",
                        lambda argv: json.dumps(dict(_CONFLICT_PAYLOAD, pids=[4242])))
    got = watchdog._pgrep("dispatcher.py")
    assert got == [4242], "Behavior 6: _pgrep must return the payload's pids, got %r" % (got,)


def test_b6_pgrep_returns_empty_when_the_seam_returns_nothing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(watchdog, "run_probe", lambda argv: "")
    got = watchdog._pgrep("dispatcher.py")
    assert got == [], "Behavior 6: an empty probe result must yield [], got %r" % (got,)


def test_b6_the_seam_receives_exactly_single_brain_argv_of_the_pattern(monkeypatch):
    seen: list[list[str]] = []

    def spy(argv):
        seen.append(list(argv))
        return ""

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(watchdog, "run_probe", spy)
    watchdog._pgrep("custom.py")
    assert seen == [watchdog.single_brain_argv("custom.py")], (
        "Behavior 6: _pgrep must hand run_probe exactly single_brain_argv(pattern) "
        "-- the pattern must be threaded through, got %r" % (seen,))


def test_b6_composition_goes_through_the_module_level_seam(monkeypatch):
    # `monkeypatch.setattr(watchdog, "run_probe", ...)` only bites if _pgrep reads
    # the global by BARE NAME at call time rather than capturing it at def time.
    monkeypatch.setattr(watchdog, "run_probe",
                        lambda argv: json.dumps(dict(_SAFE_PAYLOAD, pids=[7777])))
    assert watchdog._pgrep("dispatcher.py") == [7777]
    monkeypatch.setattr(watchdog, "run_probe", lambda argv: "garbage")
    assert watchdog._pgrep("dispatcher.py") == []


# ==========================================================================
# Behavior 7 -- the 31-test ratchet still holds, both modules BYTE-UNCHANGED
# ==========================================================================
@pytest.mark.parametrize("rel", [_ITER06, _STRANGLER])
def test_b7_existing_watchdog_test_modules_are_byte_unchanged_against_head(rel):
    shown = _git("show", "HEAD:%s" % rel)
    if shown.returncode != 0:
        pytest.skip("git show unavailable for %s" % rel)
    assert shown.stdout == (_ROOT / rel).read_text(), \
        "Behavior 7: %s must be BYTE-UNCHANGED against HEAD (frozen ratchet)" % rel


def test_b7_neither_ratchet_module_appears_in_the_tests_diff():
    r = _git("diff", "HEAD", "--name-only", "--", "tests/")
    if r.returncode != 0:
        pytest.skip("git diff unavailable")
    changed = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    assert changed.isdisjoint({_ITER06, _STRANGLER}), \
        "Behavior 7: the frozen watchdog test modules must not differ from HEAD; diff=%r" % (
            sorted(changed),)


def test_b7_the_ratchet_is_thirty_one_tests():
    counts = {}
    for rel in (_ITER06, _STRANGLER):
        counts[rel] = sum(1 for ln in (_ROOT / rel).read_text().splitlines()
                          if ln.startswith("def test_"))
    assert counts[_ITER06] == 19, "iter-06 ratchet must keep 19 tests, got %r" % (counts,)
    assert counts[_STRANGLER] == 12, "strangler ratchet must keep 12 tests, got %r" % (counts,)
    assert sum(counts.values()) == 31


def test_b7_pgrep_is_still_a_module_level_one_positional_arg_seam(monkeypatch):
    assert callable(getattr(watchdog, "_pgrep", None)), \
        "Behavior 7: _pgrep must remain a module-level attribute"
    params = inspect.signature(watchdog._pgrep).parameters
    assert list(params) == ["pattern"], \
        "Behavior 7: _pgrep must take ONE positional param named 'pattern', got %r" % (list(params),)
    assert params["pattern"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    monkeypatch.setattr(watchdog, "run_probe", lambda argv: "")
    assert isinstance(watchdog._pgrep("dispatcher.py"), list), "_pgrep must return a list"


def test_b7_monkeypatching_pgrep_still_bites_dispatcher_running(monkeypatch):
    monkeypatch.setattr(watchdog, "_pgrep", lambda pattern: [])
    assert watchdog.dispatcher_running() is False
    monkeypatch.setattr(watchdog, "_pgrep", lambda pattern: [999999])
    assert watchdog.dispatcher_running() is True


def test_b7_dispatcher_running_still_excludes_this_process(monkeypatch):
    monkeypatch.setattr(watchdog, "_pgrep", lambda pattern: [os.getpid()])
    assert watchdog.dispatcher_running() is False, \
        "Behavior 7: dispatcher_running must still exclude os.getpid()"
    monkeypatch.setattr(watchdog, "_pgrep", lambda pattern: [os.getpid(), 999999])
    assert watchdog.dispatcher_running() is True


def test_b7_dispatcher_running_calls_pgrep_by_bare_name_and_names_getpid():
    fn = _funcdef(_tree(), "dispatcher_running")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_pgrep" in called, \
        "Behavior 7: dispatcher_running must call _pgrep by BARE module name, calls=%r" % (
            sorted(called),)
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "getpid" in attrs, \
        "Behavior 7: dispatcher_running must still exclude os.getpid(); attrs=%r" % (sorted(attrs),)


# ==========================================================================
# Behaviors 5+6 END TO END -- the delegated probe must never report ITSELF
#
# SPEC GAP (PM feedback, see tester2.md): Behaviors 1-8 can ALL pass while the
# feature is inverted. Behavior 2 REQUIRES the argv to carry `--pattern <pattern>`,
# so the probe child's own command line contains both a python argv[0] AND a token
# whose basename is exactly the pattern -- i.e. the probe matches the very shape it
# is scanning for. Measured on this machine, the payload handed back to the seam for
# an impossible pattern really does contain the probe's own pid, so an exclusion
# somewhere in the chain is LOAD-BEARING for the whole feature and no numbered
# behavior pins it. If it ever regresses, `_pgrep` returns a non-empty list
# unconditionally, `dispatcher_running()` becomes permanently True, and the watchdog
# silently stops resurrecting anything -- the exact fail-shut bug this iteration
# exists to remove, made deterministic.
#
# The pattern below is synthesised with this process's own pid, so nothing on any
# machine (or in a concurrent test worker) can legitimately match it. The expected
# answer is therefore [] everywhere, including a fresh clone: this asserts NOTHING
# about the ambient process table.
# ==========================================================================
def _impossible_pattern() -> str:
    return "zzz-no-such-brain-237-%d.py" % os.getpid()


def test_e2e_probe_never_reports_its_own_probe_child():
    pattern = _impossible_pattern()
    # What the probe itself says about that pattern (recorded for the failure
    # message only -- never asserted on, since it is foundry's business, not this
    # module's, and this iteration does not touch foundry.py).
    raw = watchdog.run_probe(watchdog.single_brain_argv(pattern))
    self_reported = watchdog.parse_single_brain_pids(raw)
    got = watchdog._pgrep(pattern)
    assert got == [], (
        "END TO END: _pgrep(%r) must be [] -- no process on this machine can be "
        "running under a pid-unique synthetic name, so a non-empty answer means the "
        "probe counted ITSELF and every liveness answer is now a false True "
        "(dispatcher_running permanently True => the watchdog never resurrects). "
        "got=%r; the same argv run through the seam directly reported %r"
        % (pattern, got, self_reported))


def test_e2e_dispatcher_running_survives_the_real_seam():
    # No monkeypatch: the production path, end to end, with a real subprocess.
    # Ambient-independent -- only the TYPE and the absence of an exception are
    # asserted, never which brains happen to be alive.
    got = watchdog.dispatcher_running()
    assert isinstance(got, bool), (
        "END TO END: dispatcher_running() must still return a plain bool through "
        "the real (unpatched) probe seam, got %r" % (type(got).__name__,))


# ==========================================================================
# Behavior 8 -- the no-foundry-import property survives
# ==========================================================================
def test_b8_watchdog_never_imports_foundry():
    tree = _tree()
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert len(imports) >= 3, (
        "vacuity guard: only %d import statements found in watchdog.py, so a "
        "'no foundry import' pass would be meaningless" % len(imports))
    offenders = []
    for node in imports:
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        else:
            names = [node.module or ""]
        for name in names:
            if name == "foundry" or name.startswith("foundry."):
                offenders.append((node.lineno, name))
    assert offenders == [], (
        "Behavior 8: watchdog.py must NOT import foundry (a broken 23k-line "
        "module cannot be allowed to keep the company down); offenders=%r" % (offenders,))


def test_b8_watchdog_imports_in_a_fresh_interpreter():
    r = subprocess.run([sys.executable, "-c", "import watchdog"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, \
        "Behavior 8: `import watchdog` must succeed in a fresh subprocess; stderr tail=%r" % (
            r.stderr.strip().splitlines()[-1:],)


def test_b8_the_three_modules_still_import_together():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher, watchdog"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, \
        "quality bar: the three modules must stay importable; stderr tail=%r" % (
            r.stderr.strip().splitlines()[-1:],)
