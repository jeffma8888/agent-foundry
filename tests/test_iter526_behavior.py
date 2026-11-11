"""Iteration 526 behavior tests -- the operator stop contract says what the code
does: ``touch STOP`` ABANDONS the iteration in flight, ``kill -USR1 <pid>`` is the
zero-loss DRAIN, across CONTINUOUS.md, launch.sh, dispatcher.py's docstring and
README.md.

BLACK-BOX / ISOLATION (honored): every assertion is derived from the PM spec's
Expected Behaviors 1-9 (``products/_platform/state/iter-526/pm.md``). The
engineer's and reviewer's notes and ``git diff`` were NOT read. The docs are read
as TEXT (they are the product surface under test); dispatcher.py is read only via
``ast.get_docstring`` for Behavior 7.

Offline by construction except ``bash -n`` (Behavior 6) and one
``python -c import`` subprocess (Behavior 9): no git, no network, nothing written.
All paths are TRACKED files located from this file's location (never an absolute
literal, never gitignored state).
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def _sections(text: str) -> list[str]:
    """Split markdown into heading-delimited sections (heading line included)."""
    out: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.startswith("#") and out[-1]:
            out.append([])
        out[-1].append(line)
    return ["\n".join(s) for s in out]


def _stop_section() -> str:
    hits = [s for s in _sections(_read("CONTINUOUS.md")) if "touch STOP" in s]
    assert hits, "CONTINUOUS.md has no section containing `touch STOP`"
    return hits[0]


def _launch_stop_block() -> list[str]:
    """The `# Stop:` comment line plus the contiguous comment lines after it."""
    lines = _read("launch.sh").splitlines()
    idx = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("# Stop:")]
    assert len(idx) == 1, f"expected exactly one `# Stop:` line, got {len(idx)}"
    i = idx[0]
    block = [lines[i]]
    for ln in lines[i + 1:]:
        s = ln.lstrip()
        if not s.startswith("#") or s.startswith("# ") and re.match(r"#\s*[A-Z][a-z]+:", s):
            break
        block.append(ln)
    return block


# --- Behavior 1 -----------------------------------------------------------

def test_b1_stop_section_says_abandon():
    sec = _stop_section()
    assert re.search(r"abandon", sec, re.I), sec


def test_b1_whole_company_drains_phrase_gone():
    assert "the whole company drains" not in _read("CONTINUOUS.md").lower()


# --- Behavior 2 -----------------------------------------------------------

def test_b2_drain_named_with_kill_usr1():
    sec = _stop_section()
    assert "kill -USR1" in sec
    assert re.search(r"drain", sec, re.I)


def test_b2_shift_finishes_or_exit_0_at_boundary():
    sec = _stop_section().lower()
    assert ("shift" in sec and ("finish" in sec or "boundary" in sec)) or "exit 0" in sec \
        or "exits 0" in sec, sec


# --- Behavior 3 -----------------------------------------------------------

def test_b3_pid_source_named():
    text = _read("CONTINUOUS.md")
    assert "drain-arm:" in text or "drain armed" in text


# --- Behavior 4 -----------------------------------------------------------

def test_b4_pre_515_caveat():
    sec = _stop_section()
    assert "SIGUSR1" in sec
    assert "515" in sec
    assert re.search(r"(no|without)\s+(a\s+)?(SIGUSR1\s+)?handler|handler", sec, re.I)


# --- Behavior 5 -----------------------------------------------------------

def test_b5_per_team_retirement_kept():
    text = _read("CONTINUOUS.md")
    assert "touch products/<name>/STOP" in text
    assert "Remove the STOP" in text


# --- Behavior 6 -----------------------------------------------------------

def test_b6_launch_stop_comment_fixed():
    lines = _read("launch.sh").splitlines()
    stop = [ln for ln in lines if ln.lstrip().startswith("# Stop:")]
    assert len(stop) == 1
    assert "finishes its shift" not in stop[0]
    block = "\n".join(_launch_stop_block())
    assert re.search(r"abandon", block, re.I), block
    assert "kill -USR1" in block, block


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_b6_launch_sh_parses():
    r = subprocess.run(["bash", "-n", str(_ROOT / "launch.sh")], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# --- Behavior 7 -----------------------------------------------------------

_BAD = re.compile(r"drain|finishes its shift", re.I)


def _dispatcher_doc() -> str:
    doc = ast.get_docstring(ast.parse(_read("dispatcher.py")))
    assert doc, "dispatcher.py has no module docstring"
    return doc


def _offending(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if "touch STOP" in ln and _BAD.search(ln)]


@pytest.mark.parametrize("name", ["CONTINUOUS.md", "launch.sh", "README.md"])
def test_b7_no_same_line_drain_claim(name):
    assert _offending(_read(name)) == []


def test_b7_dispatcher_docstring_no_same_line_drain_claim():
    assert _offending(_dispatcher_doc()) == []


def test_b7_guard_can_fail():
    # The guard trips on the pre-fix wording, so it can tell drift from the fix.
    assert _offending("- `touch STOP` -- the whole company drains: x")
    assert _offending("#   touch STOP (the dispatcher finishes its shift, then exits)")
    assert not _offending("`touch STOP` abandons the iteration in flight")


def test_b7_every_source_mentions_touch_stop_somewhere():
    # The guard is vacuous for a file that never says `touch STOP`; at least the
    # two files this iteration rewrote must still carry it.
    assert "touch STOP" in _read("CONTINUOUS.md")
    assert "touch STOP" in _read("launch.sh")


# --- Behavior 9 -----------------------------------------------------------

def test_b9_import_foundry_and_dispatcher():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
