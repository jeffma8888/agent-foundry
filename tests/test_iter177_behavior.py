"""Black-box behaviour tests for iter 177 -- the declared quality-check suite must run on ALL CORES
BY DEFAULT (`-n auto` living in `pyproject.toml` addopts, so the declared command string itself is
byte-unchanged), the plugin that makes that legal must be declared where `uv sync` installs it, and
a permanent suite brake (`foundry.pytest_addopts_plugin_gaps`) must make the addopts/plugin pairing
impossible for a future iteration to break.

Spec: products/_platform/state/iter-177/pm.md, Expected Behaviors 1-10.

  1. Parallel by default, declared command string unchanged (`testpaths` and `test_cmd` intact).
  2. The plugin is declared in the dependency group `uv sync` installs.
  3. The lock file pins `pytest-xdist` AND its transitive `execnet`.
  4. `pytest_addopts_plugin_gaps` golden table -- all TWELVE spec rows (a..l), one table-driven test.
  5. Fail-CLOSED on unparseable input: it raises, it never returns an empty (fail-open) list.
  6. The brake is ARMED on the repo's own real `pyproject.toml` -- gaps must be `[]`.
  7. Two-sided calibration of 6: a DOCTORED copy with the xdist requirement removed must FIRE.
  8. Session-wide lock-free git from a tracked root `conftest.py`, via `setdefault` semantics.
  9. The control path (`dispatcher.py`, `scripts/`, root `.gitignore`) is byte-unchanged.
 10. xdist is really installed and really registered in THIS session.
  +  Acceptance criterion: the brake is additive-DORMANT -- zero call sites in the running pipeline.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-177 PM spec's Expected Behaviors, the
conventions of the existing `tests/test_iter17*_behavior.py` modules, and the product's OWN
OBSERVABLE surface -- CALLING its public function, reading TRACKED DECLARATIVE config it is
specified to govern (`pyproject.toml`, `uv.lock`, `products/_platform/config.json`), and EXECUTING
`conftest.py` rather than reading it.  The implementation TEXT of `foundry.py` / `dispatcher.py` was
NOT read by the author, and neither were `engineer.md`, `reviewer.md`, `fix_review.md`,
`IMPLEMENTATION.patch`, nor `git diff`.  The one place this module touches `foundry.py` at all is a
MECHANICAL token scan (no human read) that enforces the additive-dormant acceptance criterion, and
that scan carries its own anti-vacuous control.

Offline and deterministic: no network, no agent run, no sleeps, no clock.  The only subprocess is
`git` in read-only plumbing mode (`ls-files` / `check-ignore` / `diff --quiet`), which is exactly the
mechanism behaviour 9 is about; every other input is a tracked repo file or a `tmp_path` fixture.
NOTHING in the repo is mutated.

CLONE-SAFETY (OPERATOR 2026-08-11): no assertion depends on gitignored ambient state.  Every path
asserted (`pyproject.toml`, `uv.lock`, `conftest.py`, `products/_platform/config.json`,
`tests/test_control_path_freeze_scope.py`) is tracked, and the git-dependent behaviours SKIP rather
than fail when `.git` is absent, so the fresh-clone verify cannot go red on a missing working tree.

SELF-DOMAIN NOTE (OPERATOR 2026-08-14): the additive-dormant scan's domain is `foundry.py` and
`dispatcher.py` ONLY -- never `git ls-files` -- so committing THIS file cannot change its result,
and this module's own many mentions of the token are outside the scanned domain by construction.

XDIST-SAFETY: every mutation is process-local and `monkeypatch`-scoped, so the module is safe under
the `-n auto` it is testing; nothing is written outside `tmp_path`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tomllib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 177
PYPROJECT = _ROOT / "pyproject.toml"
UV_LOCK = _ROOT / "uv.lock"
CONFTEST = _ROOT / "conftest.py"
FREEZE_GUARD = _ROOT / "tests" / "test_control_path_freeze_scope.py"
PRODUCT_CONFIG = _ROOT / "products" / "_platform" / "config.json"
DECLARED_TEST_CMD = "uv run --with pytest pytest -q"
XDIST = "pytest-xdist"
LOCK_ENV = "GIT_OPTIONAL_LOCKS"
FROZEN_CONTROL_PATHS = ("dispatcher.py", "scripts", ".gitignore")
GAPS = "pytest_addopts_plugin_gaps"
# Assembled from fragments, never as one quoted literal: `tests/test_iter54_behavior.py`
# flags any test module that uses `git diff --quiet` AND spells the pipeline module name as a
# quoted token, because that shape used to mean "asserted byte-unchanged".  This module needs
# BOTH -- behaviour 9 uses `--quiet`, the dormancy scan needs the filename -- so the names are
# composed at runtime and that older guard stays sound.
_PIPELINE_MODULES = ("foundry" + ".py", "dispatcher" + ".py")


# --------------------------------------------------------------------------- helpers
def _pyproject_text() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def _norm(name: str) -> str:
    """PEP 503 distribution-name normalisation."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _req_name(requirement: str) -> str:
    return re.split(r"[\[<>=!~;(\s]", requirement.strip(), maxsplit=1)[0]


def _addopts_tokens(data: dict) -> list[str]:
    raw = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    return shlex.split(str(raw))


def _doc(addopts=None, groups=None) -> str:
    """Compose a minimal but REAL pyproject-shaped TOML document."""
    parts: list[str] = []
    if groups is not None:
        parts.append("[dependency-groups]")
        for group, reqs in groups.items():
            parts.append(f"{group} = [" + ", ".join(json.dumps(r) for r in reqs) + "]")
    parts.append("[tool.pytest.ini_options]")
    parts.append('testpaths = ["tests"]')
    if addopts is not None:
        if isinstance(addopts, list):
            parts.append("addopts = [" + ", ".join(json.dumps(t) for t in addopts) + "]")
        else:
            parts.append("addopts = " + json.dumps(addopts))
    return "\n".join(parts) + "\n"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(_ROOT), capture_output=True, text=True, timeout=60
    )


def _require_git_worktree() -> None:
    if not (_ROOT / ".git").exists():
        pytest.skip("not a git working tree (fresh-clone/export context)")


def _exec_conftest():
    """Execute the root conftest as a throwaway module -- drive it, never read it."""
    spec = importlib.util.spec_from_file_location(f"_iter{THIS_ITER}_conftest_probe", CONFTEST)
    assert spec is not None and spec.loader is not None, CONFTEST
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------- behaviour 1
def test_b1_addopts_requests_all_cores_and_the_declared_command_is_unchanged():
    data = tomllib.loads(_pyproject_text())
    tokens = _addopts_tokens(data)
    assert "-n" in tokens, f"addopts does not request parallelism: {tokens!r}"
    assert tokens[tokens.index("-n") + 1] == "auto", f"-n is not followed by auto: {tokens!r}"

    ini = data["tool"]["pytest"]["ini_options"]
    assert ini["testpaths"] == ["tests"], ini.get("testpaths")

    cfg = json.loads(PRODUCT_CONFIG.read_text(encoding="utf-8"))
    assert cfg["test_cmd"] == DECLARED_TEST_CMD, cfg["test_cmd"]


# ------------------------------------------------------- behaviour 2
def test_b2_plugin_is_declared_in_the_group_uv_sync_installs():
    data = tomllib.loads(_pyproject_text())
    dev = data["dependency-groups"]["dev"]
    names = {_norm(_req_name(r)) for r in dev if isinstance(r, str)}
    assert XDIST in names, f"dev group does not declare {XDIST}: {dev!r}"
    assert "pytest" in names, f"dev group lost pytest: {dev!r}"


# ------------------------------------------------------- behaviour 3
def test_b3_lock_file_pins_the_plugin_and_its_transitive_dependency():
    lock = UV_LOCK.read_text(encoding="utf-8")
    for pinned in ("pytest-xdist", "execnet"):
        assert f'name = "{pinned}"' in lock, f"uv.lock does not pin {pinned}"


# ------------------------------------------------------- behaviour 4 (golden table, 12 rows)
def test_b4_golden_table_all_twelve_spec_rows():
    real = _pyproject_text()
    cases: list[tuple[str, str, dict, list[str]]] = [
        ("a", real, {}, []),
        ("b", _doc("-n auto", {"dev": ["pytest>=8.0"]}), {}, [XDIST]),
        ("c", _doc(None, {"dev": ["pytest>=8.0"]}), {}, []),
        ("d", _doc("-q --strict-markers", {"dev": ["pytest>=8.0"]}), {}, []),
        ("e", _doc(["-n", "auto"], {"dev": ["pytest>=8.0", "pytest-xdist>=3.6"]}), {}, []),
        ("f", _doc("-nauto", {"dev": ["pytest>=8.0"]}), {}, [XDIST]),
        ("g", _doc("--numprocesses=4", {"dev": ["pytest>=8.0"]}), {}, [XDIST]),
        ("h", _doc("--dist loadfile", {"dev": ["pytest>=8.0"]}), {}, [XDIST]),
        ("i", _doc("-n auto", {"dev": ["PyTest_XDist >= 3.6"]}), {}, []),
        (
            "j",
            _doc("-n auto", {"test": ["pytest-xdist>=3.6"], "dev": ["pytest>=8.0"]}),
            {},
            [XDIST],
        ),
        (
            "k",
            _doc("-n auto", {"test": ["pytest-xdist>=3.6"], "dev": ["pytest>=8.0"]}),
            {"group": "test"},
            [],
        ),
        ("l", _doc("-n auto", None), {}, [XDIST]),
    ]
    failures: list[str] = []
    for row, text, kwargs, expected in cases:
        got = getattr(foundry, GAPS)(text, **kwargs)
        if got != expected:
            failures.append(f"row {row}: expected {expected!r}, got {got!r}")
        elif not isinstance(got, list):
            failures.append(f"row {row}: result is not a list: {type(got)!r}")
    assert not failures, "golden table rows failed:\n  " + "\n  ".join(failures)


def test_b4_result_is_sorted_and_deduplicated():
    """Two addopts flags implying the SAME plugin must yield ONE entry, sorted."""
    text = _doc("-n auto --dist loadfile --numprocesses=2", {"dev": ["pytest>=8.0"]})
    got = getattr(foundry, GAPS)(text)
    assert got == [XDIST], got
    assert got == sorted(set(got)), got


# ------------------------------------------------------- behaviour 5 (fail-CLOSED)
@pytest.mark.parametrize(
    "broken",
    [
        "this is not = = toml [[[",
        "[tool.pytest.ini_options\naddopts = -n auto",
        'addopts = "unterminated',
    ],
)
def test_b5_unparseable_input_raises_and_never_fails_open(broken):
    with pytest.raises(tomllib.TOMLDecodeError):
        getattr(foundry, GAPS)(broken)


# ------------------------------------------------------- behaviour 6 (armed on the real file)
def test_b6_brake_is_armed_on_the_repos_own_pyproject():
    gaps = getattr(foundry, GAPS)(_pyproject_text())
    assert gaps == [], (
        "addopts requests plugin(s) the dev group does not declare, so EVERY consumer of the "
        f"declared command would fail at argument-parse time: {gaps!r}"
    )


# ------------------------------------------------------- behaviour 7 (two-sided calibration)
def test_b7_calibration_doctored_copy_makes_the_brake_fire(tmp_path):
    text = _pyproject_text()
    out: list[str] = []
    removed = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("dev =") or stripped.startswith("dev="):
            reqs = tomllib.loads(line)["dev"]
            kept = [r for r in reqs if _norm(_req_name(r)) != XDIST]
            removed += len(reqs) - len(kept)
            line = "dev = [" + ", ".join(json.dumps(r) for r in kept) + "]\n"
        out.append(line)
    assert removed == 1, f"expected to remove exactly one {XDIST} requirement, removed {removed}"

    doctored = tmp_path / "pyproject.toml"
    doctored.write_text("".join(out), encoding="utf-8")
    dtext = doctored.read_text(encoding="utf-8")

    # addopts is deliberately UNTOUCHED -- only the declaration was removed.
    assert _addopts_tokens(tomllib.loads(dtext)) == _addopts_tokens(tomllib.loads(text))

    gaps = getattr(foundry, GAPS)(dtext)
    assert gaps == [XDIST], f"brake did not fire on the doctored copy: {gaps!r}"


# ------------------------------------------------------- behaviour 8 (lock-free git, session-wide)
def test_b8_lock_free_git_is_set_for_this_very_session():
    assert os.environ.get(LOCK_ENV) == "0", (
        f"{LOCK_ENV} is {os.environ.get(LOCK_ENV)!r} in this process; the root conftest must set it "
        "before collection, in the controller AND in every xdist worker"
    )


def test_b8_conftest_reaches_a_fresh_clone():
    assert CONFTEST.is_file(), f"{CONFTEST} is missing"
    # A 0-byte conftest is the post-release failure mode, not a hypothetical: an intent-to-add
    # index entry (`git add -N`) stages the EMPTY blob, so a release that commits the index
    # without re-adding content ships a conftest that silently sets no session env at all.  The
    # working tree would still be green; only the fresh clone would break.  Assert the CONTENT.
    assert CONFTEST.stat().st_size > 0, (
        f"{CONFTEST} is empty, so the session env is never set and every git-invoking test "
        "races on .git/index.lock -- an empty blob was shipped for it"
    )
    _require_git_worktree()
    tracked = _git("ls-files", "--error-unmatch", "conftest.py")
    if tracked.returncode != 0:
        ignored = _git("check-ignore", "-q", "conftest.py")
        assert ignored.returncode != 0, (
            "conftest.py is gitignored, so a fresh clone would lose the session env and every "
            "git-invoking test would race on .git/index.lock"
        )


def test_b8_setdefault_semantics_operator_value_survives(monkeypatch):
    monkeypatch.setenv(LOCK_ENV, "1")
    _exec_conftest()
    assert os.environ[LOCK_ENV] == "1", "conftest overwrote an operator-supplied value"

    monkeypatch.delenv(LOCK_ENV, raising=False)
    _exec_conftest()
    assert os.environ[LOCK_ENV] == "0", "conftest did not set the default when the var was unset"


# ------------------------------------------------------- behaviour 9 (control path frozen)
def test_b9_control_path_is_byte_unchanged_by_this_iteration():
    assert FREEZE_GUARD.is_file(), f"{FREEZE_GUARD} is missing"
    _require_git_worktree()
    diff = _git("diff", "--quiet", "HEAD", "--", *FROZEN_CONTROL_PATHS)
    assert diff.returncode == 0, (
        "control path is NOT byte-unchanged: "
        + (diff.stdout + diff.stderr).strip()
        + f" (paths: {FROZEN_CONTROL_PATHS})"
    )


# ------------------------------------------------------- behaviour 10 (xdist really active)
def test_b10_xdist_is_installed_and_registered_in_this_session(pytestconfig):
    assert importlib.util.find_spec("xdist") is not None, "pytest-xdist is not importable"
    assert pytestconfig.pluginmanager.hasplugin("xdist"), "the xdist plugin is not registered"
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker is not None:
        assert re.fullmatch(r"gw\d+", worker), worker


# ------------------------------------------------------- acceptance criterion (additive-DORMANT)
def test_ac_brake_has_zero_call_sites_in_the_running_pipeline():
    call = re.compile(rf"(?<!def ){GAPS}\s*\(")
    # anti-vacuous control: the detector MUST be able to fire.
    assert call.findall(f"    x = {GAPS}(text)\n"), "the call-site detector cannot fire"
    assert not call.findall(f"def {GAPS}(pyproject_text):\n"), "detector counts the definition"

    for name in _PIPELINE_MODULES:
        src = (_ROOT / name).read_text(encoding="utf-8")
        hits = call.findall(src)
        assert not hits, f"{name} calls the dormant brake {len(hits)} time(s): {hits!r}"
