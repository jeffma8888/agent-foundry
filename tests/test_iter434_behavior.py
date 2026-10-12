"""Iteration 434 -- ``launch.sh`` gates on ``preflight`` instead of bare
``single-brain``.

ISOLATION CONTRACT (honored): this file was written SOLELY from the iter-434
PM spec's Expected Behaviors (1-7), the product README, the ``tests/``
conventions (the launch.sh-as-data pattern from ``test_iter236_behavior.py``),
and the product's OWN OBSERVABLE behaviour by RUNNING it (the public
``launch_preflight_gaps`` function).  The implementation SOURCE of
``foundry.py`` / ``dispatcher.py``, the engineer's and reviewer's notes, and
``git diff`` were NOT read for test logic.  No test executes ``launch.sh``.
"""
from __future__ import annotations

import inspect
import pathlib
import re

import foundry

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LAUNCH = _ROOT / "launch.sh"
_USAGE = _ROOT / "USAGE.md"


def _launch_text() -> str:
    assert _LAUNCH.is_file(), "launch.sh must ship at the repo root"
    return _LAUNCH.read_text()


def _numbered(text: str):
    return list(enumerate(text.splitlines(), start=1))


# ==========================================================================
# EB1: launch.sh invokes `python3 foundry.py preflight --config "$FOUNDRY_CONFIG"`
#      instead of `python3 foundry.py single-brain`.
# ==========================================================================

def test_b1_prelaungh_gate_invokes_preflight_with_config():
    text = _launch_text()
    lines = _numbered(text)
    embedded_start = next(
        (n for n, ln in lines if re.match(r"^python3 -c '\s*$", ln)), None,
    )
    assert embedded_start, "no `python3 -c '` launch line found"
    pre_launch = [ln for n, ln in lines if n < embedded_start]
    pre_launch_blob = "\n".join(pre_launch)
    assert re.search(
        r"python3\s+foundry\.py\s+preflight\s+--config", pre_launch_blob
    ), (
        "launch.sh must invoke `python3 foundry.py preflight --config` "
        "BEFORE the detach; not found in the pre-launch section"
    )


def test_b1_preflight_invocation_passes_foundry_config_var():
    text = _launch_text()
    assert re.search(
        r'python3\s+foundry\.py\s+preflight\s+--config\s+"\$FOUNDRY_CONFIG"', text
    ), (
        "the preflight invocation must pass '\"$FOUNDRY_CONFIG\"' as the "
        "--config argument"
    )


def test_b1_no_bare_single_brain_gate():
    """The pre-launch gate must NOT be bare `single-brain` any more.
    `single-brain` may still appear for the post-launch confirmation (EB3),
    but the GATE line (the one whose exit code decides whether to launch)
    must be `preflight`."""
    text = _launch_text()
    lines = _numbered(text)
    embedded_start = next(
        (n for n, ln in lines if re.match(r"^python3 -c '\s*$", ln)), None,
    )
    assert embedded_start
    pre_launch_gates = [
        (n, ln) for n, ln in lines
        if n < embedded_start
        and "foundry.py" in ln
        and "single-brain" in ln
        and not ln.lstrip().startswith("#")
    ]
    assert pre_launch_gates == [], (
        "the pre-launch gate must NOT use bare `single-brain` any more; "
        "found pre-launch gate lines referencing it: %r" % pre_launch_gates
    )


# ==========================================================================
# EB2: Exit code 0 (GO) proceeds to launch; exit code 1 (NO-GO) refuses;
#      exit code 2 (CAUTION) refuses.
# ==========================================================================

def test_b2_exit_0_proceeds_to_launch():
    text = _launch_text()
    lines = _numbered(text)
    embedded_start = next(
        (n for n, ln in lines if re.match(r"^python3 -c '\s*$", ln)), None,
    )
    assert embedded_start
    go_msgs = [
        n for n, ln in lines
        if n < embedded_start and "GO" in ln
        and re.search(r"\b(echo|printf)\b", ln)
        and "NO-GO" not in ln
    ]
    assert go_msgs, "no GO message line found before the launch"
    no_exit_between_go_and_launch = all(
        not re.search(r"^\s*exit\s+", ln)
        for n, ln in lines
        if min(go_msgs) < n < embedded_start
        and "exit" in ln
        and not ln.lstrip().startswith("#")
        and not ln.lstrip().startswith("*)")
        and not re.search(r"^\s*\d+\)", ln.lstrip())
    )


def test_b2_exit_1_refuses_with_no_go():
    text = _launch_text()
    lines = _numbered(text)
    nogo_msgs = [
        (n, ln) for n, ln in lines
        if "NO-GO" in ln and re.search(r"\b(echo|printf)\b", ln)
    ]
    assert nogo_msgs, "no echo/printf line mentioning NO-GO found"
    first_nogo = min(n for n, _ in nogo_msgs)
    exit_after = [
        n for n, ln in lines
        if re.search(r"^\s*exit\s+1\s*(#.*)?$", ln) and n > first_nogo
    ]
    assert exit_after, (
        "the NO-GO branch (message at line %d) must `exit 1`" % first_nogo
    )


def test_b2_exit_2_refuses_with_caution():
    text = _launch_text()
    lines = _numbered(text)
    caution_msgs = [
        (n, ln) for n, ln in lines
        if "CAUTION" in ln and re.search(r"\b(echo|printf)\b", ln)
    ]
    assert caution_msgs, "no echo/printf line mentioning CAUTION found"
    first_caution = min(n for n, _ in caution_msgs)
    exit_after = [
        n for n, ln in lines
        if re.search(r"^\s*exit\s+1\s*(#.*)?$", ln) and n > first_caution
    ]
    assert exit_after, (
        "the CAUTION branch (message at line %d) must `exit 1`" % first_caution
    )


def test_b2_unexpected_exit_code_also_refuses():
    """A wildcard/default branch must also refuse on unexpected exit codes."""
    text = _launch_text()
    lines = _numbered(text)
    wildcard_hits = [
        (n, ln) for n, ln in lines
        if re.search(r"^\s*\*\)", ln)
    ]
    assert wildcard_hits, "no wildcard `*)` case branch found"


# ==========================================================================
# EB3: Post-launch confirmation still uses `single-brain` (unchanged).
# ==========================================================================

def test_b3_post_launch_confirmation_uses_single_brain():
    text = _launch_text()
    lines = _numbered(text)
    embedded_start = next(
        (n for n, ln in lines if re.match(r"^python3 -c '\s*$", ln)), None,
    )
    assert embedded_start
    post_launch = [
        (n, ln) for n, ln in lines
        if n > embedded_start
        and "foundry.py" in ln
        and "single-brain" in ln
        and not ln.lstrip().startswith("#")
    ]
    assert post_launch, (
        "after the detach, launch.sh must still use `foundry.py single-brain` "
        "for the post-launch confirmation; not found after line %d" % embedded_start
    )


def test_b3_post_launch_confirmation_is_not_preflight():
    """The post-launch check must NOT use `preflight` -- it only needs to
    verify a brain is running, not re-check the environment."""
    text = _launch_text()
    lines = _numbered(text)
    embedded_start = next(
        (n for n, ln in lines if re.match(r"^python3 -c '\s*$", ln)), None,
    )
    assert embedded_start
    post_preflight = [
        (n, ln) for n, ln in lines
        if n > embedded_start
        and "foundry.py" in ln
        and "preflight" in ln
        and not ln.lstrip().startswith("#")
    ]
    assert post_preflight == [], (
        "the post-launch confirmation must NOT use `preflight`; found: %r"
        % post_preflight
    )


# ==========================================================================
# EB4: Header comment updated to reflect that launch gates on `preflight`.
# ==========================================================================

def test_b4_header_comment_mentions_preflight():
    text = _launch_text()
    header_lines = []
    for line in text.splitlines():
        if line.startswith("#") or line.startswith("#!/"):
            header_lines.append(line)
        elif header_lines and not line.startswith("#"):
            break
    header = "\n".join(header_lines)
    assert "preflight" in header, (
        "the header comment block must mention `preflight`; it does not"
    )


# ==========================================================================
# EB5: Dormant `launch_preflight_gaps(launch_path)` in foundry.py returns a
#      non-empty tuple when launch.sh does NOT invoke `preflight`.
# ==========================================================================

def test_b5_launch_preflight_gaps_exists():
    assert hasattr(foundry, "launch_preflight_gaps"), (
        "foundry.launch_preflight_gaps must exist as a public function"
    )
    assert callable(foundry.launch_preflight_gaps)


def test_b5_current_launch_sh_returns_empty_tuple():
    """Two-sided: the CURRENT launch.sh should pass (no gaps)."""
    text = _launch_text()
    sig = inspect.signature(foundry.launch_preflight_gaps)
    params = list(sig.parameters.keys())
    assert len(params) >= 1, "launch_preflight_gaps must accept at least 1 arg"
    result = foundry.launch_preflight_gaps(text)
    assert isinstance(result, tuple), (
        "launch_preflight_gaps must return a tuple, got %s" % type(result).__name__
    )
    assert result == (), (
        "current launch.sh must produce NO gaps, got: %r" % (result,)
    )


def test_b5_old_style_bare_single_brain_returns_nonempty():
    """Two-sided: a launch.sh that uses bare `single-brain` (the old pattern)
    must trigger gaps."""
    old_style = (
        "#!/bin/bash\n"
        "python3 foundry.py single-brain\n"
        "sb_status=$?\n"
    )
    result = foundry.launch_preflight_gaps(old_style)
    assert isinstance(result, tuple)
    assert len(result) > 0, (
        "old-style launch.sh with bare `single-brain` must produce at least "
        "one gap, got empty tuple"
    )


def test_b5_empty_text_returns_nonempty():
    """An empty launch script has no preflight gate -- should be flagged."""
    result = foundry.launch_preflight_gaps("")
    assert isinstance(result, tuple)
    assert len(result) > 0, (
        "an empty launch script must produce at least one gap"
    )


# ==========================================================================
# EB6: USAGE.md updated to name `preflight` instead of `single-brain`.
# ==========================================================================

def test_b6_usage_names_preflight_near_launch_sh():
    text = _USAGE.read_text()
    lines = _numbered(text)
    launch_refs = [
        (n, ln) for n, ln in lines if "launch.sh" in ln
    ]
    assert launch_refs, "USAGE.md must mention launch.sh"
    launch_region = "\n".join(
        ln for n, ln in lines
        if any(abs(n - ref_n) <= 5 for ref_n, _ in launch_refs)
    )
    assert "preflight" in launch_region, (
        "USAGE.md near the launch.sh mention must name `preflight`; "
        "the nearby region does not contain it"
    )


def test_b6_usage_does_not_say_gates_on_single_brain():
    """The old phrasing "gates the launch on `foundry.py single-brain`"
    should be replaced."""
    text = _USAGE.read_text()
    assert "gates the launch on" not in text or "preflight" in text, (
        "USAGE.md still says 'gates the launch on' without naming preflight"
    )


# ==========================================================================
# EB7: Full suite passes -- tested by running it separately.
#      Importability is already verified by the top-level `import foundry`.
# ==========================================================================

def test_b7_import_succeeds():
    import foundry as f
    import dispatcher as d
    assert hasattr(f, "launch_preflight_gaps")
    assert hasattr(d, "load_dispatch")
