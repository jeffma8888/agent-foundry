"""iter 511 -- tests/conftest.py never collects a callable re-exported from foundry/dispatcher.

Black-box: every case copies the REAL ``tests/conftest.py`` (or not) into a fresh
``tmp_path`` next to a probe module and runs pytest as a subprocess, then reads the
summary counts. No gitignored state is consulted. Nested runs pass ``-n 0`` (xdist is a
project dependency) and ``-p no:cacheprovider`` so nothing is written into the repo.

HAZARD PIN: this module never does ``from foundry import test_*`` itself; the probe
modules that do are written into tmp_path only.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
CONFTEST = REPO / "tests" / "conftest.py"

SEAMS = (
    "test_tree",
    "test_quality_cli",
    "test_failure_lines",
    "test_touch_line",
    "test_touch_drift_line",
    "test_touch_cli",
)

def _mk(tmp_path: pathlib.Path, files: dict[str, str], *, conftest: bool) -> pathlib.Path:
    d = tmp_path / ("with_hook" if conftest else "no_hook")
    d.mkdir()
    # An empty ini pins rootdir here, so the repo's pyproject addopts never apply.
    (d / "pytest.ini").write_text("[pytest]\n")
    if conftest:
        shutil.copy(CONFTEST, d / "conftest.py")
    for name, body in files.items():
        (d / name).write_text(textwrap.dedent(body))
    return d


def _run(d: pathlib.Path, *extra: str) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO), str(d)])
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_XDIST_WORKER", None)
    # xdist is a project dependency (pyproject addopts carry ``-n auto``), so ``-n 0`` is
    # always valid; it stays in the literal argv so test_iter502's static brake sees it.
    cmd = [sys.executable, "-m", "pytest", "-n", "0", "-q", "-p", "no:cacheprovider", "-rA"]
    cmd += list(extra)
    proc = subprocess.run(cmd, cwd=d, env=env, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def _counts(out: str) -> dict[str, int]:
    """Parse the final pytest summary line into {passed, failed, errors, ...}."""
    summary = [ln for ln in out.splitlines() if re.search(r"\d+ (passed|failed|errors?|error)\b", ln)]
    assert summary, f"no pytest summary line in output:\n{out}"
    got: dict[str, int] = {"passed": 0, "failed": 0, "errors": 0}
    for n, word in re.findall(r"(\d+) (passed|failed|errors?|skipped)", summary[-1]):
        key = "errors" if word.startswith("error") else word
        got[key] = int(n)
    return got


PROBE_FOUNDRY = """
    from foundry import (
        test_tree, test_quality_cli, test_failure_lines,
        test_touch_line, test_touch_drift_line, test_touch_cli,
    )

    def test_real_one():
        assert 1 + 1 == 2
"""


# -- behavior 1 -------------------------------------------------------------

def test_b1_foundry_seams_not_collected_with_hook(tmp_path):
    d = _mk(tmp_path, {"test_probe.py": PROBE_FOUNDRY}, conftest=True)
    rc, out = _run(d)
    c = _counts(out)
    assert c == {"passed": 1, "failed": 0, "errors": 0}, out
    assert rc == 0, out
    for seam in SEAMS:
        assert f"::{seam}" not in out, (seam, out)


def test_b1_can_fail_witness_without_hook(tmp_path):
    """The same probe WITHOUT the conftest copy is red: the trap is real."""
    d = _mk(tmp_path, {"test_probe.py": PROBE_FOUNDRY}, conftest=False)
    rc, out = _run(d)
    c = _counts(out)
    assert c["errors"] > 0, out
    assert rc != 0, out
    assert c["passed"] >= 1, out


def test_b1_star_import_not_collected_with_hook(tmp_path):
    """Stricter reading: ``import *`` drags the seams in too; the hook still drops them."""
    d = _mk(tmp_path, {"test_star.py": """
        from foundry import *  # noqa: F401,F403

        def test_real_star():
            assert True
    """}, conftest=True)
    rc, out = _run(d)
    c = _counts(out)
    assert c["failed"] == 0 and c["errors"] == 0, out
    assert c["passed"] == 1, out
    assert rc == 0, out


# -- behavior 2 -------------------------------------------------------------

def test_b2_dispatcher_alias_not_collected(tmp_path):
    body = """
        from dispatcher import main as test_main_alias

        def test_real_two():
            assert True
    """
    d = _mk(tmp_path, {"test_disp.py": body}, conftest=True)
    rc, out = _run(d)
    assert _counts(out) == {"passed": 1, "failed": 0, "errors": 0}, out
    assert "test_main_alias" not in out, out
    assert rc == 0, out


def test_b2_dispatcher_alias_collected_without_hook(tmp_path):
    """Anti-vacuity for b2: without the hook the alias IS collected (fails or errors)."""
    body = """
        from dispatcher import main as test_main_alias

        def test_real_two():
            assert True
    """
    d = _mk(tmp_path, {"test_disp.py": body}, conftest=False)
    rc, out = _run(d, "--collect-only")
    assert "test_main_alias" in out, out


# -- behavior 3 -------------------------------------------------------------

def test_b3_real_failing_test_still_reported(tmp_path):
    body = PROBE_FOUNDRY + """
    def test_real_fails():
        assert 1 == 2, "genuine failure"
"""
    d = _mk(tmp_path, {"test_probe.py": body}, conftest=True)
    rc, out = _run(d)
    assert _counts(out) == {"passed": 1, "failed": 1, "errors": 0}, out
    assert "test_real_fails" in out, out
    assert rc == 1, out


def test_b3_module_defined_test_with_foundry_wrapped_name_still_collected(tmp_path):
    """A test the module defines itself (``__module__`` == the test module) is never hidden,
    even when it shares a name with a foundry seam."""
    body = """
        def test_tree():
            assert True

        def test_failure_lines():
            assert True
    """
    d = _mk(tmp_path, {"test_own.py": body}, conftest=True)
    rc, out = _run(d)
    assert _counts(out) == {"passed": 2, "failed": 0, "errors": 0}, out
    assert rc == 0, out


# -- behavior 4 -------------------------------------------------------------

def test_b4_non_foundry_test_named_import_is_collected(tmp_path):
    files = {
        "helper_mod.py": """
            def test_from_helper():
                assert True
        """,
        "test_uses_helper.py": """
            from helper_mod import test_from_helper

            def test_real_four():
                assert True
        """,
    }
    d = _mk(tmp_path, files, conftest=True)
    rc, out = _run(d)
    assert _counts(out) == {"passed": 2, "failed": 0, "errors": 0}, out
    assert "test_from_helper" in out, out
    assert rc == 0, out


# -- behavior 5 -------------------------------------------------------------

def test_b5_test_class_and_non_callables_untouched(tmp_path):
    body = """
        import foundry

        test_constant = 5            # non-callable: pytest ignores it either way
        test_seam_list = [foundry.main]  # non-callable container holding a foundry callable

        class TestThing:
            def test_method_a(self):
                assert True

            def test_method_b(self):
                assert True
    """
    d = _mk(tmp_path, {"test_cls.py": body}, conftest=True)
    rc, out = _run(d)
    assert _counts(out) == {"passed": 2, "failed": 0, "errors": 0}, out
    assert "TestThing::test_method_a" in out and "TestThing::test_method_b" in out, out
    assert rc == 0, out


def test_b5_failing_test_class_method_still_fails(tmp_path):
    body = """
        class TestBroken:
            def test_m(self):
                assert False, "class failure"
    """
    d = _mk(tmp_path, {"test_cls_fail.py": body}, conftest=True)
    rc, out = _run(d)
    assert _counts(out) == {"passed": 0, "failed": 1, "errors": 0}, out
    assert rc == 1, out


# -- behavior 6 -------------------------------------------------------------

DROP_COUNTER = '''
import pytest

DROPPED = []
ALL = []


@pytest.hookimpl(hookwrapper=True)
def pytest_pycollect_makeitem(collector, name, obj):
    outcome = yield
    res = outcome.get_result()
    if res == [] and callable(obj) and getattr(obj, "__module__", None) in ("foundry", "dispatcher"):
        ALL.append(name)
        # Only a drop pytest would otherwise have COLLECTED shrinks the suite: a foundry
        # class imported as ``R`` or ``_RESULT_TYPE`` matches no python_* pattern.
        if collector.funcnamefilter(name) or collector.classnamefilter(name):
            DROPPED.append(f"{collector.nodeid}::{name}")


def pytest_collection_finish(session):
    print(f"DROPCOUNT={len(DROPPED)} SEEN={len(ALL)}")
    for n in DROPPED:
        print(f"DROPPED {n}")
'''


def test_b6_real_suite_collection_does_not_shrink(tmp_path):
    """The hook drops ZERO objects from the real tests/ tree, so the collected count with
    the hook equals the count without it. A hookwrapper plugin counts every drop."""
    plug = tmp_path / "plug"
    plug.mkdir()
    (plug / "drop_counter_511.py").write_text(DROP_COUNTER)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO), str(plug)])
    env.pop("PYTEST_ADDOPTS", None)
    cmd = [sys.executable, "-m", "pytest", "-n", "0", "--collect-only", "-q",
           "-p", "no:cacheprovider", "-p", "drop_counter_511", "-s"]
    cmd.append(str(REPO / "tests"))
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-3000:]
    m = re.search(r"DROPCOUNT=(\d+)", out)
    assert m, out[-3000:]
    dropped = [ln for ln in out.splitlines() if ln.startswith("DROPPED ")]
    assert int(m.group(1)) == 0, dropped
    collected = re.search(r"(\d+) tests? collected", out)
    assert collected and int(collected.group(1)) > 1000, out[-2000:]


# -- behavior 7 / 8 ---------------------------------------------------------

def test_b7_foundry_and_dispatcher_importable():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"], cwd=REPO,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_b8_existing_conftest_fixtures_kept():
    text = CONFTEST.read_text()
    for needle in ("def _clear_drift_cache", "def _invoke_main", "_smoke_cache",
                   "def live_smoke_result", "def pytest_pycollect_makeitem",
                   "tryfirst=True"):
        assert needle in text, needle


def test_b8_hook_present_in_copied_conftest_drops_seam_but_fixtures_still_work(tmp_path):
    """The autouse ``_clear_drift_cache`` fixture still runs in the copied conftest
    (it imports foundry), and the ``live_smoke_result`` fixture still resolves by name."""
    body = """
        from foundry import test_tree

        def test_uses_fixture(request):
            names = request.fixturenames
            assert "_clear_drift_cache" in names

        def test_smoke_fixture_defined(request):
            fm = request.session._fixturemanager
            assert fm.getfixturedefs("live_smoke_result", request.node)
    """
    d = _mk(tmp_path, {"test_fx.py": body}, conftest=True)
    rc, out = _run(d)
    assert _counts(out) == {"passed": 2, "failed": 0, "errors": 0}, out
    assert rc == 0, out


def test_b6_drop_counter_is_not_vacuous(tmp_path):
    """Anti-vacuity for the b6 counter: on the foundry probe it counts all 6 seams."""
    d = _mk(tmp_path, {"test_probe.py": PROBE_FOUNDRY,
                       "drop_counter_511.py": DROP_COUNTER}, conftest=True)
    rc, out = _run(d, "--collect-only", "-s", "-p", "drop_counter_511")
    m = re.search(r"DROPCOUNT=(\d+)", out)
    assert m and int(m.group(1)) == len(SEAMS), out
    assert rc == 0, out
