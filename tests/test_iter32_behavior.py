"""
Behavior tests — iteration 32  (HOTFIX; no source change).

ISOLATION CONTRACT — HONORED. This is a black-box tester. I did NOT read the
implementation source (`foundry.py` / `dispatcher.py`), the engineer's or
reviewer's notes, or `git diff`. Sources used: the iter-32 spec (`pm.md`), the
product README/roadmap, and files under `tests/` (which the isolation contract
explicitly permits me to read and drive), plus running the product's own CLI.
The tests below encode the spec's Expected Behaviors, not implementation quirks.

SPEC UNDER TEST
---------------
Make `test_iter31_behavior.py::test_b13_live_smoke_on_real_dispatch_config` SKIP
(instead of hard-failing) when the machine-local, gitignored `foundry.config.json`
is absent from the repo root, so that a fresh-clone / CI suite is green, while the
smoke still RUNS and passes on a live machine where the config IS present. The fix
is test-only: it must not change any source behavior or the iter-31 public surface.

DESIGN NOTE (why no pytest-in-a-subprocess)
-------------------------------------------
The spec's Behaviors 1 & 2 are about a "fresh checkout" running the full suite.
No existing test in this repo spawns `pytest` as a subprocess, and doing so here
would (a) break that convention and (b) COMPOUND at every future post-release
fresh-clone verify (each future clone would re-run a nested full suite). So the
fresh-checkout guarantees are proven WITHOUT recursion:
  * Behavior 2 (the crux) is exercised directly: the exact iter-31 smoke function
    is driven under a simulated config-less checkout (its module dir has no
    `foundry.config.json`) and must raise pytest's SKIP outcome with a reason
    naming the file.
  * Behavior 1 is proven structurally: b13 is the ONLY committed test that
    couples the full suite to the machine-local repo-root config's *existence*
    (verified by scanning `tests/`), and that coupling is now a `pytest.skip`
    guard -- so a config-less fresh checkout has no failure from this dev-tree
    leak class. (The operational green-suite is additionally confirmed by the
    tester's own full-suite run and by the factory's post-release gate.)
"""
import importlib
import json
import pathlib
import re
import subprocess
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve()
REPO_ROOT = _HERE.parents[1]
TESTS_DIR = _HERE.parent
ITER31 = TESTS_DIR / "test_iter31_behavior.py"

sys.path.insert(0, str(REPO_ROOT))   # -> import foundry, dispatcher
sys.path.insert(0, str(TESTS_DIR))   # -> import sibling test module by name
import foundry     # noqa: E402
import dispatcher  # noqa: E402

# The iter-31 *test* module (reading/driving tests/ is allowed by the contract).
_iter31 = importlib.import_module("test_iter31_behavior")
_b13 = _iter31.test_b13_live_smoke_on_real_dispatch_config
_run_cli = _iter31._run_cli


def _repo_root_config():
    """Where the smoke looks for the machine-local dispatch config."""
    return pathlib.Path(foundry.__file__).resolve().parent / "foundry.config.json"


# =====================================================================
# Behavior 2 -- config ABSENT (fresh checkout): b13 SKIPS, reason names file
# =====================================================================
def test_b2_smoke_skips_when_machine_local_config_absent(tmp_path, monkeypatch):
    # Simulate a fresh clone: point foundry's module dir at a location with no
    # `foundry.config.json` (exactly what a `git clone`/`git archive` yields,
    # since the file is gitignored and never tracked).
    fake_module = tmp_path / "foundry.py"
    fake_module.write_text("# location-only stand-in for a config-less checkout\n")
    monkeypatch.setattr(foundry, "__file__", str(fake_module))
    assert not _repo_root_config().exists(), "precondition: config absent in this froot"

    with pytest.raises(pytest.skip.Exception) as exc:
        _b13()
    reason = str(exc.value)
    assert "foundry.config.json" in reason, (
        "skip reason must name the absent machine-local config; "
        f"got: {reason!r}"
    )
    # A SKIP is not a failure/error: the outcome must NOT be an assertion failure.
    assert not isinstance(exc.value, AssertionError)


# =====================================================================
# Behavior 3 -- config PRESENT (live machine): b13 RUNS (not skipped) & PASSES
# =====================================================================
def test_b3_smoke_runs_and_passes_when_config_present():
    if not _repo_root_config().exists():
        pytest.skip(
            "no machine-local foundry.config.json at repo root; the live-machine "
            "path (B3) is only exercisable when the operator's config is present"
        )
    try:
        result = _b13()  # must RUN its original assertions, not skip
    except pytest.skip.Exception as s:  # pragma: no cover - would be a regression
        pytest.fail(f"b13 wrongly SKIPPED though foundry.config.json is present: {s}")
    assert result is None  # a passing test function completes and returns None


# =====================================================================
# Behavior 1 -- fresh checkout full suite has 0 failures from this leak class
#   (structural, non-recursive): b13 is the ONLY committed test coupling the
#   suite to the machine-local repo-root config existence, now skip-guarded.
# =====================================================================
def test_b1_b13_is_a_skip_guard_naming_the_config():
    src = ITER31.read_text()
    m = re.search(
        r'if not \(froot / "foundry\.config\.json"\)\.exists\(\):\s*'
        r'pytest\.skip\(\s*"([^"]*)"',
        src,
        re.S,
    )
    assert m, (
        "iter-31 b13 must SKIP (not assert) when the repo-root foundry.config.json "
        "is absent -- expected an `if not (froot / \"foundry.config.json\").exists(): "
        "pytest.skip(...)` guard"
    )
    assert "foundry.config.json" in m.group(1), (
        f"skip reason must name the config file; got: {m.group(1)!r}"
    )


def test_b1_no_committed_test_hard_asserts_repo_root_config_exists():
    """The dev-tree-leak class this hotfix closes: no test may HARD-ASSERT the
    repo-root config's existence -- existence may only DECIDE a skip. A tmp-scoped
    config or a monkeypatched path-*string* assertion is fine."""
    offenders = []
    for tf in sorted(TESTS_DIR.glob("test_*.py")):
        if tf.name == _HERE.name:
            continue
        for lineno, line in enumerate(tf.read_text().splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or "foundry.config.json" not in s:
                continue
            tmp_scoped = any(
                k in s
                for k in ("_write_dispatch", "tmp_path", "captured",
                          "name=", "dispatch_path=", "/d/")
            )
            if tmp_scoped:
                continue
            if s.startswith("assert") and ".exists()" in s:
                offenders.append(f"{tf.name}:{lineno}: {s}")
    assert not offenders, (
        "hard existence-assert on the repo-root config leaks into a fresh clone:\n"
        + "\n".join(offenders)
    )


# =====================================================================
# Behavior 4 -- invariants intact: both modules import; control-flow fns callable
# =====================================================================
def test_b4_imports_and_control_flow_functions_intact():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
    assert dispatcher is not None
    for fn in ("build_prompt", "run_stage", "run_iteration", "run_continuous"):
        assert callable(getattr(foundry, fn, None)), f"missing control-flow fn {fn}"


# =====================================================================
# Behavior 5 -- iter-31 public surface unchanged (the fix touches only a test):
#   company-history + --json run; --json is ONE parseable JSON doc whose
#   exit_code equals the process exit code, and human/json codes agree.
# =====================================================================
def test_b5_company_history_public_surface_intact():
    rc_h, _ = _run_cli(["company-history"])
    rc_j, out_j = _run_cli(["company-history", "--json"])
    doc = json.loads(out_j.strip())  # exactly one parseable JSON document
    assert isinstance(doc, dict), f"--json must emit a JSON object, got {type(doc)}"
    assert "exit_code" in doc, f"--json doc must carry an exit_code: {sorted(doc)}"
    assert doc["exit_code"] == rc_j, "json doc exit_code must equal the --json process code"
    assert rc_h == rc_j, "human and --json exit codes must agree"
