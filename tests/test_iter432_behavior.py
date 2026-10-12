"""Iteration 432 -- fix graphql-rest-gateway config.json so that setup_cmd
uses npm ci (not the Python default) and test_cmd wraps the && chain in
sh -c so shlex.split produces a 3-element argv instead of passing && as a
literal argument.

ISOLATION CONTRACT (honored): this file was written ONLY from the iter-432
PM spec's Expected Behaviors (1-7), the product README, the ``tests/``
conventions, and the product's OWN OBSERVABLE behaviour by RUNNING it (the
``foundry lint-config`` CLI). The implementation SOURCE of ``foundry.py`` /
``dispatcher.py``, the engineer's and reviewer's notes, and ``git diff``
were NOT read for test logic. Fully offline & deterministic: the only
subprocess is the documented CLI invocation.
"""
import json
import pathlib
import re
import shlex
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

_CONFIG_PATH = _ROOT / "products" / "graphql-rest-gateway" / "config.json"


def _load_config():
    return json.loads(_CONFIG_PATH.read_text())


# EB1: setup_cmd field exists and equals "npm ci"
def test_b1_setup_cmd_is_npm_ci():
    data = _load_config()
    assert "setup_cmd" in data, "config must contain setup_cmd field"
    assert data["setup_cmd"] == "npm ci", (
        f"setup_cmd must be 'npm ci', got {data['setup_cmd']!r}"
    )


# EB2: test_cmd field equals the sh -c wrapped form
def test_b2_test_cmd_is_sh_c_wrapped():
    data = _load_config()
    expected = "sh -c 'npm test --silent && npm run typecheck --silent'"
    assert data["test_cmd"] == expected, (
        f"test_cmd must be {expected!r}, got {data['test_cmd']!r}"
    )


# EB3: shlex.split of test_cmd produces exactly 3 elements
def test_b3_shlex_split_test_cmd_three_elements():
    data = _load_config()
    argv = shlex.split(data["test_cmd"])
    assert argv == [
        "sh", "-c", "npm test --silent && npm run typecheck --silent"
    ], f"shlex.split(test_cmd) must be 3-element argv, got {argv!r}"
    assert len(argv) == 3, f"expected 3 elements, got {len(argv)}"


# EB4: shlex.split of setup_cmd produces exactly ['npm', 'ci']
def test_b4_shlex_split_setup_cmd():
    data = _load_config()
    argv = shlex.split(data["setup_cmd"])
    assert argv == ["npm", "ci"], (
        f"shlex.split(setup_cmd) must be ['npm', 'ci'], got {argv!r}"
    )


# EB5: lint-config exits 0 with 0 errors (warnings acceptable)
def test_b5_lint_config_zero_errors():
    r = subprocess.run(
        [sys.executable, "foundry.py", "lint-config",
         "--config", str(_CONFIG_PATH)],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (
        f"lint-config must exit 0; stderr:\n{r.stderr}\nstdout:\n{r.stdout}"
    )
    combined = r.stdout + r.stderr
    assert re.search(r"errors:\s*0", combined), (
        f"lint-config must report 0 errors; output:\n{combined}"
    )
