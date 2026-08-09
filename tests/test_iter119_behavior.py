"""Black-box behaviour tests for iter 119 -- attempt-aware retry directive.

Spec (Expected Behaviors 1-11), from products/_platform/state/iter-119/pm.md:
  1.  foundry.retry_directive is a module-level callable returning "" for any
      attempt < 2 (1, 0, -1) for any stage / out_file.
  2.  For attempt >= 2 it returns a non-empty string starting with "\\n\\n" and
      containing the module constant foundry.RETRY_DIRECTIVE_MARKER (non-empty
      ASCII).
  3.  MAX_ATTEMPTS is read AT CALL TIME (module global, not captured at def
      time): patched to 7 -> "attempt 3 of 7"; unpatched -> "attempt 2 of 4".
  4.  The block names the stage and the exact required output file verbatim;
      out_file may be a pathlib.Path or a str and both give the same text.
  5.  Escalation content present (case-insensitive substrings, not wording):
      "no output file", "minimal", "scope", "already".
  6.  Bounded by CHARACTERS: len(...) <= foundry.RETRY_DIRECTIVE_MAX_CHARS for
      every attempt in 2..MAX_ATTEMPTS and for pathological 50k-char inputs;
      a truncated return ends with "...";  the constant is an int <= 2000.
  7.  Total + pure: raises for none of the inputs above, does no filesystem
      I/O, and is deterministic for identical arguments.
  8.  run_stage attempt 1 is BYTE-IDENTICAL to today: the {prompt} argv element
      equals build_prompt's return exactly (no prefix, no suffix).
  9.  run_stage attempt 2 carries the directive: {prompt} argv element ==
      sentinel + retry_directive(2, stage, out_file); returns (True, out_file);
      subprocess.run called exactly twice.
  10. The call is a monkeypatchable BARE-NAME seam: a fake retry_directive
      returning "ZZ-RETRY-SENTINEL" is absent from attempt 1's argv and present
      in attempt 2's, and the fake receives the attempt number.
  11. No other stage semantics change: first-attempt success -> exactly one
      subprocess call and (True, out); per-attempt log <stage>.attempt<N>.log
      still written for every attempt; a never-writing stage still makes
      exactly MAX_ATTEMPTS calls and returns (False, out); the iter-114
      per-attempt endpoint self-heal still injects env= on BOTH attempts.

ISOLATION CONTRACT (honored): every assertion here was written from the PM spec
and the product's OBSERVABLE runtime behaviour. run_stage is driven as a black
box with foundry.build_prompt, foundry.subprocess.run, foundry.stopping,
foundry.sleep_interruptible and foundry.resolve_agent_endpoint monkeypatched, so
NO real agent subprocess, socket, git, network or sleep is used and nothing is
written outside tmp_path. The implementation SOURCE LOGIC of foundry.py, the
engineer's and reviewer's notes, and git diff were NOT read. Behaviors 7 and 10
use only public runtime introspection (compiled function name tables via
_co_names_deep -- the iter-107 convention), never a read of module source text.
"""
import importlib.util
import inspect
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

_ROOT = pathlib.Path(foundry.__file__).resolve().parent
THIS_TEST = pathlib.Path(__file__).resolve()

ITERATION = 119
SYMBOL = "retry_directive"
SENTINEL = "SENTINEL-PROMPT-119"
FAKE_TOKEN = "ZZ-RETRY-SENTINEL"


# --------------------------------------------------------------------------
# runtime introspection helpers (pure -- do NOT read module source text)
# --------------------------------------------------------------------------
def _co_names_deep(fn):
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter119_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# run_stage drive harness (fully offline)
# --------------------------------------------------------------------------
class _FakeCP:
    """Stand-in for subprocess.CompletedProcess: only the attributes run_stage
    reads (.returncode/.stdout/.stderr)."""

    def __init__(self, rc=0, out="ok", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _make_cfg(tmp_path):
    """Minimal product config in a tmp dir (suite convention); repo + work_root
    are TMP so the live foundry repo and products/ tree are NEVER touched."""
    import json

    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (tmp_path / "VISION.md").write_text("vision\n")
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return foundry.load_config(str(p))


def _role_file(tmp_path):
    r = tmp_path / "role.md"
    r.write_text("do the thing\n")
    return str(r)


def _patch_common(monkeypatch, prompt=SENTINEL):
    """Neutralise build_prompt (no real role/vision/learnings needed), backoff
    sleep, STOP polling and the endpoint resolver."""
    monkeypatch.setattr(foundry, "build_prompt", lambda *a, **k: prompt)
    monkeypatch.setattr(foundry, "sleep_interruptible", lambda cfg, s: False)
    monkeypatch.setattr(foundry, "stopping", lambda cfg: False)
    monkeypatch.setattr(foundry, "resolve_agent_endpoint", lambda *a, **k: None)


def _drive(monkeypatch, cfg, role, out_name="engineer.md", stage="engineer",
           write_on=None, resolver=None, prompt=SENTINEL):
    """Drive run_stage once, recording (args, kwargs) of every subprocess.run.

    write_on: 1-based attempt number whose fake spawn writes a NON-EMPTY output
    file (None => never write, forcing the full retry loop). The out path is
    discovered black-box from run_stage's own return value of a throwaway
    non-writing run, exactly as the iter-114 harness does.
    """
    _patch_common(monkeypatch, prompt=prompt)

    out_path = None
    if write_on is not None:
        # Discovery run (default None resolver) purely to learn the out path.
        monkeypatch.setattr(foundry.subprocess, "run", lambda *a, **k: _FakeCP())
        ok0, out_path = foundry.run_stage(cfg, ITERATION, stage, role, out_name)
        assert ok0 is False and not out_path.exists()  # discovery leaves no file

    # Install the caller's resolver only for the MEASURED run, so a scripted
    # sequence is not consumed by the discovery run above.
    if resolver is not None:
        monkeypatch.setattr(foundry, "resolve_agent_endpoint", resolver)

    calls = []

    def fake_run(*a, **k):
        calls.append((a, dict(k)))
        if write_on is not None and len(calls) == write_on:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("STAGE OUTPUT\n")
        return _FakeCP()

    monkeypatch.setattr(foundry.subprocess, "run", fake_run)
    ok, out = foundry.run_stage(cfg, ITERATION, stage, role, out_name)
    return ok, out, calls


def _argv(call):
    """The command list run_stage handed to subprocess.run POSITIONALLY."""
    args = call[0]
    assert args, "subprocess.run was called with no positional argv"
    argv = args[0]
    assert isinstance(argv, (list, tuple)), "argv is not a list/tuple: %r" % (argv,)
    return list(argv)


def _prompt_arg(call, prefix=SENTINEL):
    """The single {prompt} argv element, located black-box by its known prefix."""
    hits = [a for a in _argv(call) if isinstance(a, str) and a.startswith(prefix)]
    assert len(hits) == 1, (
        "expected exactly one argv element starting with the prompt sentinel, got %d"
        % len(hits))
    return hits[0]


# ==========================================================================
# Behavior 1 -- "" for any attempt < 2
# ==========================================================================
@pytest.mark.parametrize("attempt", [1, 0, -1, -5])
@pytest.mark.parametrize("stage", ["engineer", "pm", "tester", ""])
def test_b1_empty_for_attempts_below_two(attempt, stage, tmp_path):
    p = tmp_path / "out.md"
    assert foundry.retry_directive(attempt, stage, p) == ""
    assert foundry.retry_directive(attempt, stage, str(p)) == ""


def test_b1_is_module_level_callable():
    assert callable(foundry.retry_directive)
    sig = inspect.signature(foundry.retry_directive)
    params = list(sig.parameters)
    assert params[:3] == ["attempt", "stage", "out_file"], params
    # any further parameter must be optional (additive-only surface).
    for name in params[3:]:
        assert sig.parameters[name].default is not inspect.Parameter.empty, name


# ==========================================================================
# Behavior 2 -- attempt >= 2: non-empty, starts with a blank-line separator,
#               carries the marker constant
# ==========================================================================
def test_b2_marker_constant_is_nonempty_ascii():
    m = foundry.RETRY_DIRECTIVE_MARKER
    assert isinstance(m, str) and m, "RETRY_DIRECTIVE_MARKER must be a non-empty str"
    assert all(ord(c) < 128 for c in m), "RETRY_DIRECTIVE_MARKER must be pure ASCII"


@pytest.mark.parametrize("attempt", [2, 3, 4, 9])
def test_b2_nonempty_starts_with_blank_line_and_has_marker(attempt, tmp_path):
    t = foundry.retry_directive(attempt, "engineer", tmp_path / "engineer.md")
    assert t, "attempt %d must produce a non-empty directive" % attempt
    assert t.startswith("\n\n"), repr(t[:10])
    assert foundry.RETRY_DIRECTIVE_MARKER in t


def test_b2_directive_is_pure_ascii(tmp_path):
    t = foundry.retry_directive(2, "engineer", tmp_path / "engineer.md")
    assert [(i, c) for i, c in enumerate(t) if ord(c) >= 128] == []


# ==========================================================================
# Behavior 3 -- MAX_ATTEMPTS read at CALL time, not captured at def time
# ==========================================================================
def test_b3_patched_max_attempts_is_observed(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "MAX_ATTEMPTS", 7)
    t = foundry.retry_directive(3, "engineer", tmp_path / "engineer.md")
    assert "attempt 3 of 7" in t, t
    assert "of 4" not in t, "MAX_ATTEMPTS looks captured at def time: %r" % t


def test_b3_unpatched_uses_live_max_attempts(tmp_path):
    t = foundry.retry_directive(2, "engineer", tmp_path / "engineer.md")
    assert "attempt 2 of %d" % foundry.MAX_ATTEMPTS in t, t


def test_b3_spec_literal_attempt_2_of_4(tmp_path, monkeypatch):
    # The spec's literal example, pinned independently of the live default.
    monkeypatch.setattr(foundry, "MAX_ATTEMPTS", 4)
    assert "attempt 2 of 4" in foundry.retry_directive(2, "engineer",
                                                      tmp_path / "engineer.md")


def test_b3_bare_name_max_attempts_reference():
    assert "MAX_ATTEMPTS" in _co_names_deep(foundry.retry_directive), (
        "retry_directive must read MAX_ATTEMPTS as a module global at call time")


# ==========================================================================
# Behavior 4 -- names the stage and the exact required output file
# ==========================================================================
@pytest.mark.parametrize("stage", ["engineer", "reviewer", "pm_scout_a"])
def test_b4_stage_and_out_file_verbatim(stage, tmp_path):
    p = tmp_path / "sub" / ("%s.md" % stage)
    t = foundry.retry_directive(2, stage, p)
    assert stage in t, t
    assert str(p) in t, t


def test_b4_path_and_str_produce_identical_text(tmp_path):
    p = tmp_path / "iter-119" / "engineer.md"
    assert (foundry.retry_directive(2, "engineer", p)
            == foundry.retry_directive(2, "engineer", str(p)))


def test_b4_relative_and_plain_string_paths_accepted():
    t = foundry.retry_directive(2, "engineer", "engineer.md")
    assert "engineer.md" in t
    t2 = foundry.retry_directive(2, "engineer", pathlib.Path("engineer.md"))
    assert t == t2


# ==========================================================================
# Behavior 5 -- escalation content (case-insensitive substrings)
# ==========================================================================
@pytest.mark.parametrize("needle", ["no output file", "minimal", "scope", "already"])
def test_b5_escalation_substrings_present(needle, tmp_path):
    t = foundry.retry_directive(2, "engineer", tmp_path / "engineer.md").lower()
    assert needle in t, "directive is missing %r" % needle


def test_b5_substrings_present_for_every_real_attempt(tmp_path):
    for attempt in range(2, foundry.MAX_ATTEMPTS + 1):
        t = foundry.retry_directive(attempt, "engineer", tmp_path / "e.md").lower()
        for needle in ("no output file", "minimal", "scope", "already"):
            assert needle in t, (attempt, needle)


# ==========================================================================
# Behavior 6 -- bounded by CHARACTERS
# ==========================================================================
def test_b6_max_chars_constant_is_small_int():
    m = foundry.RETRY_DIRECTIVE_MAX_CHARS
    assert isinstance(m, int) and not isinstance(m, bool)
    assert 0 < m <= 2000, m


def test_b6_bounded_for_every_real_attempt(tmp_path):
    for attempt in range(2, foundry.MAX_ATTEMPTS + 1):
        t = foundry.retry_directive(attempt, "engineer", tmp_path / "engineer.md")
        assert len(t) <= foundry.RETRY_DIRECTIVE_MAX_CHARS, (attempt, len(t))


@pytest.mark.parametrize("which", ["out_file", "stage"])
def test_b6_pathological_input_is_truncated_with_ellipsis(which):
    big = "Z" * 50000
    if which == "out_file":
        t = foundry.retry_directive(2, "engineer", big)
    else:
        t = foundry.retry_directive(2, big, "out.md")
    assert len(t) <= foundry.RETRY_DIRECTIVE_MAX_CHARS, len(t)
    assert t.endswith("..."), repr(t[-20:])
    assert t.startswith("\n\n")
    assert foundry.RETRY_DIRECTIVE_MARKER in t, (
        "truncation must keep the marker (it is the head of the block)")


def test_b6_pathological_both_args_bounded():
    big = "Z" * 50000
    for attempt in (2, 3, 4):
        t = foundry.retry_directive(attempt, big, big)
        assert len(t) <= foundry.RETRY_DIRECTIVE_MAX_CHARS, (attempt, len(t))
        assert t.endswith("...")


def test_b6_normal_input_is_not_truncated(tmp_path):
    # A realistic state-dir path stays comfortably inside the budget, so the
    # ellipsis marker only ever appears when truncation really happened.
    p = tmp_path / "products" / "_platform" / "state" / "iter-119" / "engineer.md"
    t = foundry.retry_directive(2, "engineer", p)
    assert len(t) < foundry.RETRY_DIRECTIVE_MAX_CHARS
    assert str(p) in t


# ==========================================================================
# Behavior 7 -- total and pure (no raise, no filesystem I/O, deterministic)
# ==========================================================================
def test_b7_totality_matrix_never_raises(tmp_path):
    big = "Z" * 50000
    stages = ["engineer", "", big, "stage with spaces", "a/b\\c"]
    files = [tmp_path / "x.md", "x.md", "", big,
             pathlib.Path("/nonexistent-dir-119/deeper/x.md")]
    for attempt in (-1, 0, 1, 2, 3, 4, 99):
        for s in stages:
            for f in files:
                got = foundry.retry_directive(attempt, s, f)
                assert isinstance(got, str)


def test_b7_no_filesystem_io_missing_vs_existing(tmp_path):
    # Same path string, once absent and once present with content: identical
    # text => the function never reads (or stats) the file.
    p = tmp_path / "engineer.md"
    before = foundry.retry_directive(2, "engineer", p)
    p.write_text("some real content that a reader would notice\n")
    after = foundry.retry_directive(2, "engineer", p)
    assert before == after
    p.unlink()
    assert foundry.retry_directive(2, "engineer", p) == before


def test_b7_nonexistent_parent_directory_is_fine():
    p = pathlib.Path("/definitely-not-here-119") / "iter-119" / "engineer.md"
    t = foundry.retry_directive(2, "engineer", p)
    assert str(p) in t


def test_b7_no_io_names_referenced():
    names = _co_names_deep(foundry.retry_directive)
    for forbidden in ("read_text", "open", "exists", "stat", "read_bytes",
                      "write_text", "iterdir", "glob"):
        assert forbidden not in names, (
            "retry_directive references filesystem call %r (must be pure)" % forbidden)


def test_b7_deterministic_across_calls(tmp_path):
    p = tmp_path / "engineer.md"
    first = foundry.retry_directive(3, "engineer", p)
    for _ in range(5):
        assert foundry.retry_directive(3, "engineer", p) == first


# ==========================================================================
# Behavior 8 -- run_stage attempt 1 is BYTE-IDENTICAL to today
# ==========================================================================
def test_b8_attempt1_prompt_is_exactly_build_prompt_output(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=1)
    assert ok is True
    assert len(calls) == 1
    argv = _argv(calls[0])
    assert SENTINEL in argv, (
        "attempt 1 argv must contain build_prompt's output verbatim: %r" % (argv,))
    assert argv.count(SENTINEL) == 1
    # No element merely *starts with* the sentinel -> no suffix was appended.
    assert _prompt_arg(calls[0]) == SENTINEL


def test_b8_attempt1_prompt_unchanged_even_when_stage_later_fails(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=None)
    assert ok is False
    assert _prompt_arg(calls[0]) == SENTINEL, "attempt 1 must carry no directive"


# ==========================================================================
# Behavior 9 -- run_stage attempt 2 carries the directive
# ==========================================================================
def test_b9_attempt2_prompt_is_sentinel_plus_directive(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, out_name="engineer.md",
                            stage="engineer", write_on=2)
    assert ok is True
    assert out.exists() and out.stat().st_size > 0
    assert len(calls) == 2, "expected exactly two subprocess.run calls, got %d" % len(calls)
    expected = SENTINEL + foundry.retry_directive(2, "engineer", out)
    assert _prompt_arg(calls[1]) == expected


def test_b9_out_file_is_state_iter_dir_out_name(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, out_name="engineer.md",
                            stage="engineer", write_on=2)
    assert out.name == "engineer.md"
    assert out.parent.name == "iter-%d" % ITERATION
    assert out.parent.parent.name == "state"
    # the directive names that exact absolute file
    assert str(out) in _prompt_arg(calls[1])


def test_b9_third_and_fourth_attempts_escalate_by_number(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=None)
    assert ok is False
    assert len(calls) == foundry.MAX_ATTEMPTS
    for n in range(2, foundry.MAX_ATTEMPTS + 1):
        expected = SENTINEL + foundry.retry_directive(n, "engineer", out)
        assert _prompt_arg(calls[n - 1]) == expected, "attempt %d prompt mismatch" % n
        assert "attempt %d of %d" % (n, foundry.MAX_ATTEMPTS) in _prompt_arg(calls[n - 1])


def test_b9_directive_is_a_suffix_not_a_prefix(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=2)
    p2 = _prompt_arg(calls[1])
    assert p2.startswith(SENTINEL), "the directive must be appended, not prepended"
    assert p2.index(foundry.RETRY_DIRECTIVE_MARKER) > len(SENTINEL)


# ==========================================================================
# Behavior 10 -- the call is a monkeypatchable BARE-NAME seam
# ==========================================================================
def test_b10_bare_name_reference_from_run_stage():
    assert SYMBOL in _co_names_deep(foundry.run_stage), (
        "run_stage must reference %s by bare name" % SYMBOL)


def test_b10_fake_seam_absent_attempt1_present_attempt2(tmp_path, monkeypatch):
    # SPEC NOTE (behavior 10 vs the AC): the AC mandates an UNCONDITIONAL call
    # site -- (prompt + retry_directive(attempt, stage, out_file)) -- so the
    # attempt-1 gate lives inside retry_directive (behavior 1), NOT in
    # run_stage. A fake that ignored `attempt` would therefore also decorate
    # attempt 1, which is correct behaviour, not a defect. The fake below
    # honours the real contract ("" below attempt 2), which is the only
    # reading of behavior 10 that is jointly satisfiable with the AC.
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    seen = []

    def fake(attempt, *a, **k):
        seen.append(attempt)
        return "" if attempt < 2 else FAKE_TOKEN

    monkeypatch.setattr(foundry, SYMBOL, fake)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=2)
    assert ok is True
    assert len(calls) == 2
    assert not any(FAKE_TOKEN in a for a in _argv(calls[0]) if isinstance(a, str)), (
        "attempt 1 argv must not carry the retry directive")
    assert any(FAKE_TOKEN in a for a in _argv(calls[1]) if isinstance(a, str)), (
        "attempt 2 argv must carry the seam's return value (bare-name call?)")
    assert seen, "run_stage never called the monkeypatched seam"
    assert 2 in seen, "the seam must receive the attempt number; got %r" % (seen,)
    assert _prompt_arg(calls[1]) == SENTINEL + FAKE_TOKEN


def test_b10_seam_receives_every_attempt_number(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    seen = []

    def fake(attempt, stage, out_file):
        seen.append((attempt, stage, str(out_file)))
        return ""

    monkeypatch.setattr(foundry, SYMBOL, fake)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=None)
    assert ok is False
    attempts = [s[0] for s in seen]
    assert attempts == list(range(1, foundry.MAX_ATTEMPTS + 1)), attempts
    assert {s[1] for s in seen} == {"engineer"}
    assert {s[2] for s in seen} == {str(out)}
    # a seam returning "" leaves every prompt byte-identical
    for c in calls:
        assert _prompt_arg(c) == SENTINEL


def test_b10_gate_lives_in_the_pure_function_not_in_run_stage(tmp_path, monkeypatch):
    """Documents WHERE the attempt gate lives (PM feedback, behavior 1 + AC).

    An attempt-BLIND fake decorates every attempt, including the first --
    which proves run_stage calls the seam unconditionally and delegates the
    "attempt < 2 => empty" decision to retry_directive itself. With the REAL
    function, attempt 1 is byte-identical (test_b8_*), so the guarantee that
    matters is preserved either way. Asserted as a disjunction so a future
    implementation that ALSO gates at the call site stays green.
    """
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    monkeypatch.setattr(foundry, SYMBOL, lambda *a, **k: FAKE_TOKEN)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=2)
    assert ok is True and len(calls) == 2
    a1 = _prompt_arg(calls[0])
    assert a1 in (SENTINEL, SENTINEL + FAKE_TOKEN), repr(a1)
    assert _prompt_arg(calls[1]) == SENTINEL + FAKE_TOKEN


# ==========================================================================
# Behavior 11 -- no other stage semantics change
# ==========================================================================
def test_b11_first_attempt_success_makes_exactly_one_call(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=1)
    assert ok is True
    assert isinstance(out, pathlib.Path)
    assert len(calls) == 1


def test_b11_never_writing_stage_exhausts_max_attempts(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=None)
    assert ok is False
    assert isinstance(out, pathlib.Path)
    assert not out.exists()
    assert len(calls) == foundry.MAX_ATTEMPTS


def test_b11_per_attempt_log_written_for_every_attempt(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, stage="engineer",
                            out_name="engineer.md", write_on=None)
    assert ok is False
    for n in range(1, foundry.MAX_ATTEMPTS + 1):
        log = out.parent / ("engineer.attempt%d.log" % n)
        assert log.exists(), "missing per-attempt log %s" % log.name


def test_b11_log_written_on_a_succeeding_second_attempt(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=2)
    assert ok is True
    for n in (1, 2):
        assert (out.parent / ("engineer.attempt%d.log" % n)).exists()


def test_b11_empty_output_file_still_counts_as_failure(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    _patch_common(monkeypatch)
    monkeypatch.setattr(foundry.subprocess, "run", lambda *a, **k: _FakeCP())
    ok0, out = foundry.run_stage(cfg, ITERATION, "engineer", role, "engineer.md")
    assert ok0 is False

    calls = []

    def fake_run(*a, **k):
        calls.append((a, dict(k)))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("")
        return _FakeCP()

    monkeypatch.setattr(foundry.subprocess, "run", fake_run)
    ok, out2 = foundry.run_stage(cfg, ITERATION, "engineer", role, "engineer.md")
    assert ok is False, "a zero-byte output file must still be a failure"
    assert len(calls) == foundry.MAX_ATTEMPTS


def test_b11_endpoint_self_heal_still_injects_env_on_both_attempts(tmp_path, monkeypatch):
    key = foundry._AGENT_ENDPOINT_ENV
    monkeypatch.setenv(key, "STALE-INHERITED")
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    seq = iter(["LIVE-A", "LIVE-B", "LIVE-C", "LIVE-D"])
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=2,
                            resolver=lambda *a, **k: next(seq))
    assert ok is True
    assert len(calls) == 2
    for i, c in enumerate(calls):
        env = c[1].get("env")
        assert env is not None, "attempt %d lost the env injection" % (i + 1)
        assert set(os.environ).issubset(set(env))
    assert calls[0][1]["env"][key] == "LIVE-A"
    assert calls[1][1]["env"][key] == "LIVE-B"
    assert os.environ.get(key) == "STALE-INHERITED"


def test_b11_resolver_none_still_passes_no_env(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=2,
                            resolver=lambda *a, **k: None)
    assert ok is True
    assert all(("env" not in k or k.get("env") is None) for _, k in calls)


def test_b11_stage_timeout_and_backoffs_unchanged(tmp_path, monkeypatch):
    # The retry SCHEDULE is explicitly out of scope for this iteration.
    assert foundry.MAX_ATTEMPTS == 4
    assert foundry.BACKOFFS == [600, 1200, 2400]
    assert foundry.STAGE_TIMEOUT == 1800
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, write_on=1)
    assert calls[0][1].get("timeout") == foundry.STAGE_TIMEOUT
    assert calls[0][1].get("capture_output") is True
    assert calls[0][1].get("text") is True


def test_b11_stop_sentinel_still_short_circuits_retries(tmp_path, monkeypatch):
    # STOP handling is untouched: a stage that stops during backoff must not
    # burn all MAX_ATTEMPTS. sleep_interruptible returning True == "stop now".
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    _patch_common(monkeypatch)
    monkeypatch.setattr(foundry, "sleep_interruptible", lambda cfg, s: True)
    calls = []
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: (calls.append((a, dict(k))) or _FakeCP()))
    ok, out = foundry.run_stage(cfg, ITERATION, "engineer", role, "engineer.md")
    assert ok is False
    assert len(calls) < foundry.MAX_ATTEMPTS, (
        "an interrupted backoff must stop retrying, got %d calls" % len(calls))


# ==========================================================================
# Public-surface / import safety
# ==========================================================================
def test_imports_still_succeed_in_a_fresh_interpreter():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_new_symbols_absent_from_dispatcher():
    txt = (_ROOT / "dispatcher.py").read_text(encoding="utf-8")
    for sym in (SYMBOL, "RETRY_DIRECTIVE_MARKER", "RETRY_DIRECTIVE_MAX_CHARS"):
        assert sym not in txt, "dispatcher.py must not reference %s" % sym


def test_run_stage_is_the_sole_in_module_caller():
    callers = []
    for name in dir(foundry):
        obj = getattr(foundry, name)
        if callable(obj) and hasattr(obj, "__code__"):
            if SYMBOL in _co_names_deep(obj):
                callers.append(name)
    # iter-144: widened from ONE name to an explicit allowlist. The invariant
    # protected here is that the retry text enters the PIPELINE at exactly one
    # place -- `run_stage`. The two additions belong to the read-only `prompt`
    # verb (#45), which exists to REPRODUCE what `run_stage` composes and is on
    # no control path: `render_stage_prompt` builds the rendered text and
    # `prompt_cli` measures the block for its banner. Both must call the seam by
    # BARE module name (spec behaviors 5/6/8 turn on a monkeypatch biting).
    # EQUALITY, not a subset: a new unlisted caller still fails here, and so
    # does `run_stage` ever ceasing to call it.
    assert sorted(callers) == ["prompt_cli", "render_stage_prompt",
                               "run_stage"], (
        "%s must be called only by run_stage and the read-only `prompt` "
        "renderer, got %r" % (SYMBOL, sorted(callers)))


# ==========================================================================
# Mechanical acceptance checks (suite convention)
# ==========================================================================
def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_this_test_file_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_no_byte_unchanged_freeze_guard_added():
    # AC: this file must NOT add a byte-unchanged freeze over foundry.py,
    # README.md or roles/ -- tests/test_control_path_freeze_scope.py documents
    # why such a guard deadlocks later iterations. Literal split so the check
    # cannot match its own source marker.
    forbidden = "byte_" + "unchanged"
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert ttext.count(forbidden) == 1, (
        "this test file must not define a %s freeze guard" % forbidden)
