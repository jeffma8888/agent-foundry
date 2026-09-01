"""Behaviour tests for iter 213 -- persist the exact assembled stage prompt per attempt.

Spec: products/_platform/state/iter-213/pm.md, Expected Behaviors 1-6.

  1. Persisted per attempt -- after attempt N runs, the iteration state dir holds
     `<stage>.attempt<N>.prompt`, byte-identical to the string substituted for the
     `{prompt}` placeholder in the agent argv on that attempt.
  2. Written BEFORE the agent is spawned -- if the spawn seam raises, that
     attempt's `.prompt` file still exists and still holds the full prompt text.
  3. Attempt-specific content, both retained -- attempt 1 == the base prompt;
     attempt 2 == base + `retry_directive(2, stage, out_file)`; the two differ and
     attempt 1 is NOT overwritten.
  4. Persistence never changes the stage verdict -- an `OSError` from the writer
     leaves `run_stage`'s `(success, out_file)` tuple exactly as it would be.
  5. Naming is single-sourced and pure -- a module-level helper maps
     `(stage, attempt)` to the filename; `("tester", 2)` -> `tester.attempt2.prompt`,
     pairing 1:1 with the existing `tester.attempt2.log`.
  6. Containment -- the persisted path is always inside `cfg.state`, and the
     TRACKED `.gitignore` already carries a pattern covering `products/*/state/`,
     so no `.gitignore` change is needed or made.

ISOLATION: written under the tester isolation contract. No implementation source,
no `git diff`, and no other stage's notes were read. `foundry.py` is driven as a
black box: the new surface was DISCOVERED at runtime (`dir(foundry)` plus
`inspect.signature`), never by reading its source. Provenance caveat stated
plainly: the loop's own bounded learnings digest, which is injected into every
stage prompt, contained `[ENG iter213]` and `[REV iter213]` lines, so this file's
coverage is not a claim of pure independent derivation -- but every behaviour
below is stated in the SPEC's terms and observed at RUNTIME.

Offline and deterministic: `build_prompt`, `subprocess.run`, `stopping`,
`sleep_interruptible` and `resolve_agent_endpoint` are monkeypatched via the
existing bare-name seams, so there is no real agent subprocess, socket, git,
network or sleep, and nothing is written outside `tmp_path`. Nothing asserts on
gitignored ambient state: every fixture is built in `tmp_path`, and the only
repo file read is the TRACKED, control-path-frozen `.gitignore`.
"""
import inspect
import importlib.util
import json
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

_ROOT = pathlib.Path(foundry.__file__).resolve().parent
THIS_TEST = pathlib.Path(__file__).resolve()
_GITIGNORE = _ROOT / ".gitignore"
_LEAK_GUARD = _ROOT / "scripts" / "leak_guard.py"
_DENYLIST = _ROOT / "scripts" / "leak_denylist.txt"

ITERATION = 213
SENTINEL = "SENTINEL-PROMPT-213"
# Captured at import so a drive with `save_exc=None` RESTORES the real writer:
# monkeypatch lives for the whole test function, so two drives in ONE test would
# otherwise share the first drive's patch and the "control" arm would be vacuous.
_REAL_SAVE_STAGE_PROMPT = foundry.save_stage_prompt
STAGE = "engineer"
OUT_NAME = "engineer.md"
PROMPT_SUFFIX = ".prompt"

# The measured cap-timeout tail, so a driven stage takes the full retry ladder.
CAP_TIMEOUT_BLOB = "agent run failed: agent run timed out after 600s"


# --------------------------------------------------------------------------
# helpers (pure runtime introspection -- never a read of control-path source)
# --------------------------------------------------------------------------
def _co_names_deep(fn):
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _load_leak_guard():
    spec = importlib.util.spec_from_file_location(
        "leak_guard_iter213_probe", _LEAK_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# offline run_stage drive harness (shape copied from tests/test_iter129_behavior.py)
# --------------------------------------------------------------------------
class _FakeCP:
    """Stand-in for subprocess.CompletedProcess: only the attributes run_stage
    reads (.returncode / .stdout / .stderr)."""

    def __init__(self, rc=1, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _make_cfg(tmp_path):
    """Minimal product config in a tmp dir; repo + work_root are TMP so the live
    foundry repo and products/ tree are NEVER touched."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (tmp_path / "VISION.md").write_text("vision\n", encoding="utf-8")
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return foundry.load_config(str(p))


def _role_file(tmp_path):
    r = tmp_path / "role.md"
    r.write_text("do the thing\n", encoding="utf-8")
    return str(r)


def _drive(monkeypatch, tmp_path, *, blob=CAP_TIMEOUT_BLOB, prompt=SENTINEL,
           write_output=False, spawn_exc=None, save_exc=None):
    """Drive `run_stage` offline as a black box.

    `write_output=True` makes the fake agent write a non-empty output file, so the
    stage SUCCEEDS on attempt 1; otherwise the full retry ladder runs.
    `spawn_exc` makes the spawn seam raise (Behavior 2). `save_exc` makes the
    prompt-persisting seam raise (Behavior 4).
    """
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    it_dir = cfg.state / ("iter-%d" % ITERATION)

    monkeypatch.setattr(foundry, "build_prompt", lambda *a, **k: prompt)
    monkeypatch.setattr(foundry, "stopping", lambda _cfg: False)
    monkeypatch.setattr(foundry, "resolve_agent_endpoint", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "sleep_interruptible", lambda _cfg, _s: False)

    def bad_save(*a, **k):
        raise save_exc

    monkeypatch.setattr(foundry, "save_stage_prompt",
                        bad_save if save_exc is not None
                        else _REAL_SAVE_STAGE_PROMPT)

    calls = []

    def fake_run(*a, **k):
        calls.append((a, dict(k)))
        if spawn_exc is not None:
            raise spawn_exc
        if write_output:
            it_dir.mkdir(parents=True, exist_ok=True)
            (it_dir / OUT_NAME).write_text("stage output\n", encoding="utf-8")
        return _FakeCP(out=blob)

    monkeypatch.setattr(foundry.subprocess, "run", fake_run)

    result = None
    raised = None
    try:
        result = foundry.run_stage(cfg, ITERATION, STAGE, role, OUT_NAME)
    except BaseException as exc:      # Behavior 2 drives a raising spawn seam
        raised = exc

    return types.SimpleNamespace(
        result=result, raised=raised, calls=calls, cfg=cfg, it_dir=it_dir,
        ok=(result[0] if result else None), out=(result[1] if result else None))


def _argv(call):
    args = call[0]
    assert args, "subprocess.run was called with no positional argv"
    argv = args[0]
    assert isinstance(argv, (list, tuple)), "argv is not a list/tuple: %r" % (argv,)
    return list(argv)


def _prompt_argv_element(call, prompt=SENTINEL):
    """The single argv element that carries the `{prompt}` substitution."""
    hits = [a for a in _argv(call)
            if isinstance(a, str) and a.startswith(prompt)]
    assert len(hits) == 1, (
        "expected exactly one argv element carrying the prompt, got %d" % len(hits))
    return hits[0]


def _prompt_files(it_dir):
    return sorted(p.name for p in it_dir.iterdir()) if it_dir.exists() else []


# ==========================================================================
# Behavior 1 -- persisted per attempt, byte-identical to the argv element
# ==========================================================================
def test_b1_every_attempt_leaves_a_prompt_artifact(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path)
    assert len(d.calls) == foundry.MAX_ATTEMPTS, (
        "precondition: the drive must exercise every attempt, got %d" % len(d.calls))
    for n in range(1, foundry.MAX_ATTEMPTS + 1):
        f = d.it_dir / ("%s.attempt%d%s" % (STAGE, n, PROMPT_SUFFIX))
        assert f.exists(), (
            "attempt %d left no prompt artifact; state dir holds %r"
            % (n, _prompt_files(d.it_dir)))
        assert f.stat().st_size > 0, "attempt %d's prompt artifact is empty" % n


def test_b1_persisted_bytes_equal_the_bytes_actually_sent(monkeypatch, tmp_path):
    """The load-bearing assertion of the whole bite: a replay input that differs
    from what was sent is worse than none, so compare BYTES per attempt."""
    d = _drive(monkeypatch, tmp_path)
    for n in range(1, foundry.MAX_ATTEMPTS + 1):
        sent = _prompt_argv_element(d.calls[n - 1])
        f = d.it_dir / ("%s.attempt%d%s" % (STAGE, n, PROMPT_SUFFIX))
        assert f.read_bytes() == sent.encode("utf-8"), (
            "attempt %d: persisted prompt is not byte-identical to the argv "
            "element (persisted %d bytes, sent %d bytes)"
            % (n, f.stat().st_size, len(sent.encode("utf-8"))))


def test_b1_a_successful_stage_also_persists_its_one_attempt(monkeypatch, tmp_path):
    """The artifact must not be a failure-path-only side effect: a stage that
    succeeds on attempt 1 still records the input it was given."""
    d = _drive(monkeypatch, tmp_path, write_output=True)
    assert d.ok is True and len(d.calls) == 1
    f = d.it_dir / ("%s.attempt1%s" % (STAGE, PROMPT_SUFFIX))
    assert f.exists() and f.read_text(encoding="utf-8") == SENTINEL


def test_b1_the_prompt_artifact_sits_beside_the_log_it_explains(monkeypatch, tmp_path):
    """Discovery is by colocation (the spec's stated consumer story): every
    `<stage>.attemptN.log` has a `<stage>.attemptN.prompt` sibling."""
    d = _drive(monkeypatch, tmp_path)
    names = set(_prompt_files(d.it_dir))
    logs = sorted(n for n in names if n.endswith(".log"))
    assert logs, "precondition: the drive produced no attempt logs"
    for log in logs:
        sibling = log[: -len(".log")] + PROMPT_SUFFIX
        assert sibling in names, (
            "%s has no %s sibling -- colocation is the only discovery path in "
            "this bite" % (log, sibling))


# ==========================================================================
# Behavior 2 -- written BEFORE the agent is spawned
# ==========================================================================
def test_b2_prompt_survives_a_spawn_that_raises(monkeypatch, tmp_path):
    """A stage killed mid-run must leave its replay input behind. The
    DISCRIMINATING evidence is the PAIR: the `.prompt` file present AND the
    post-spawn `.log` file absent. `.prompt` alone would also be present under a
    post-spawn write whenever the spawn succeeded, so it decides nothing."""
    d = _drive(monkeypatch, tmp_path,
               spawn_exc=RuntimeError("spawn-seam-raised-213"))
    assert isinstance(d.raised, RuntimeError), (
        "precondition: the spawn seam must have raised, got %r" % (d.raised,))
    prompt_file = d.it_dir / ("%s.attempt1%s" % (STAGE, PROMPT_SUFFIX))
    log_file = d.it_dir / ("%s.attempt1.log" % STAGE)
    assert prompt_file.exists(), (
        "the prompt was NOT persisted before the spawn; state dir holds %r"
        % (_prompt_files(d.it_dir),))
    assert prompt_file.read_text(encoding="utf-8") == SENTINEL, \
        "the persisted prompt is truncated or altered, not the full text"
    assert not log_file.exists(), (
        "precondition for the ordering claim: the attempt log is written AFTER "
        "the spawn, so it must be absent here -- state dir holds %r"
        % (_prompt_files(d.it_dir),))
    assert _prompt_files(d.it_dir) == [prompt_file.name], (
        "the only artifact of a spawn that never returned must be the prompt")


def test_b2_a_real_cap_kill_persists_every_attempts_prompt(monkeypatch, tmp_path):
    """The motivating scenario, in its REAL shape. A 600s cap kill does not reach
    run_stage as an arbitrary exception -- it arrives as `subprocess.TimeoutExpired`,
    which run_stage CATCHES and retries. So the spec's claim ("a stage killed
    mid-run therefore leaves its replay input behind") has to hold across a full
    ladder of timed-out attempts, not just for one raise that escapes."""
    d = _drive(monkeypatch, tmp_path,
               spawn_exc=subprocess.TimeoutExpired(cmd=["agent"], timeout=600))
    assert d.raised is None, (
        "a cap timeout is a HANDLED failure; it must not escape run_stage: %r"
        % (d.raised,))
    assert d.ok is False and len(d.calls) == foundry.MAX_ATTEMPTS
    base = None
    for n in range(1, foundry.MAX_ATTEMPTS + 1):
        f = d.it_dir / ("%s.attempt%d%s" % (STAGE, n, PROMPT_SUFFIX))
        assert f.exists(), (
            "attempt %d was cap-killed and left NO replay input -- the exact case "
            "GAP-041 exists for; state dir holds %r" % (n, _prompt_files(d.it_dir)))
        text = f.read_text(encoding="utf-8")
        if n == 1:
            base = text
            assert base == SENTINEL
        else:
            assert text == base + foundry.retry_directive(n, STAGE, d.out), (
                "attempt %d's cap-killed prompt is not base + retry_directive(%d)"
                % (n, n))


def test_b2_control_a_spawn_that_returns_does_leave_the_log(monkeypatch, tmp_path):
    """Two-sided partner: the same harness with a NON-raising spawn produces the
    log, which is what makes its absence above evidence of ordering rather than
    evidence that the log is never written at all."""
    d = _drive(monkeypatch, tmp_path, write_output=True)
    assert (d.it_dir / ("%s.attempt1.log" % STAGE)).exists()


# ==========================================================================
# Behavior 3 -- attempt-specific content, both retained
# ==========================================================================
def test_b3_attempt1_is_the_base_prompt_and_attempt2_appends_the_directive(
        monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path)
    first = (d.it_dir / ("%s.attempt1%s" % (STAGE, PROMPT_SUFFIX))).read_text(
        encoding="utf-8")
    second = (d.it_dir / ("%s.attempt2%s" % (STAGE, PROMPT_SUFFIX))).read_text(
        encoding="utf-8")
    assert first == SENTINEL, (
        "attempt 1 must be exactly build_prompt's return (retry_directive is "
        "empty for attempt 1); got %d chars" % len(first))
    expected = SENTINEL + foundry.retry_directive(2, STAGE, d.out)
    assert second == expected, (
        "attempt 2 must be the base prompt plus retry_directive(2, ...); "
        "got %d chars, expected %d" % (len(second), len(expected)))
    assert first != second, "the two attempts' inputs are indistinguishable"


def test_b3_attempt1_is_not_overwritten_by_later_attempts(monkeypatch, tmp_path):
    """Per-attempt retention is the point: a single `<stage>.prompt` would keep
    only the LAST attempt, and the interesting attempt is often the first."""
    d = _drive(monkeypatch, tmp_path)
    texts = {}
    for n in range(1, foundry.MAX_ATTEMPTS + 1):
        texts[n] = (d.it_dir / ("%s.attempt%d%s" % (STAGE, n, PROMPT_SUFFIX))
                    ).read_text(encoding="utf-8")
    assert texts[1] == SENTINEL, "attempt 1's file was overwritten by a retry"
    for n in range(2, foundry.MAX_ATTEMPTS + 1):
        assert texts[n] != texts[1], (
            "attempt %d must carry its own retry directive, not attempt 1's text"
            % n)
        assert texts[n].startswith(SENTINEL), (
            "attempt %d lost the base prompt" % n)


def test_b3_the_retry_directive_is_the_only_difference(monkeypatch, tmp_path):
    """Nothing else may be injected into the persisted text: stripping the
    directive from attempt N must return exactly attempt 1's bytes."""
    d = _drive(monkeypatch, tmp_path)
    base = (d.it_dir / ("%s.attempt1%s" % (STAGE, PROMPT_SUFFIX))).read_text(
        encoding="utf-8")
    for n in range(2, foundry.MAX_ATTEMPTS + 1):
        text = (d.it_dir / ("%s.attempt%d%s" % (STAGE, n, PROMPT_SUFFIX))
                ).read_text(encoding="utf-8")
        assert text == base + foundry.retry_directive(n, STAGE, d.out), (
            "attempt %d's persisted prompt is not base + retry_directive(%d)" % (n, n))


# ==========================================================================
# Behavior 4 -- persistence never changes the stage verdict
# ==========================================================================
@pytest.mark.parametrize("write_output,expected_ok", [(False, False), (True, True)])
def test_b4_an_oserror_from_the_writer_leaves_the_verdict_identical(
        monkeypatch, tmp_path, write_output, expected_ok):
    clean = _drive(monkeypatch, tmp_path / "clean", write_output=write_output)
    broken = _drive(monkeypatch, tmp_path / "broken", write_output=write_output,
                    save_exc=OSError("no space left on device (probe 213)"))
    assert clean.raised is None and broken.raised is None, (
        "a failed prompt write must never propagate out of run_stage: %r"
        % (broken.raised,))
    assert broken.ok is expected_ok, (
        "the stage verdict changed when persistence failed: %r" % (broken.ok,))
    assert (broken.ok, broken.out.name) == (clean.ok, clean.out.name), (
        "run_stage returned %r with a broken writer but %r with a working one"
        % ((broken.ok, broken.out.name), (clean.ok, clean.out.name)))
    assert len(broken.calls) == len(clean.calls), (
        "a failed prompt write changed the number of attempts (%d vs %d)"
        % (len(broken.calls), len(clean.calls)))


def test_b4_control_the_broken_writer_really_was_in_force(monkeypatch, tmp_path):
    """Two-sided control: with the writer raising, NO prompt artifact is left, and
    with it intact there is one per attempt. Without this the test above would
    also pass if the OSError patch never bit."""
    broken = _drive(monkeypatch, tmp_path / "broken",
                    save_exc=OSError("no space left on device (probe 213)"))
    clean = _drive(monkeypatch, tmp_path / "clean")
    broken_prompts = [n for n in _prompt_files(broken.it_dir)
                      if n.endswith(PROMPT_SUFFIX)]
    clean_prompts = [n for n in _prompt_files(clean.it_dir)
                     if n.endswith(PROMPT_SUFFIX)]
    assert broken_prompts == [], (
        "the OSError patch did not bite -- artifacts still appeared: %r"
        % (broken_prompts,))
    assert len(clean_prompts) == foundry.MAX_ATTEMPTS, (
        "the unpatched control must produce one artifact per attempt, got %r"
        % (clean_prompts,))
    assert [n for n in _prompt_files(broken.it_dir) if n.endswith(".log")], \
        "the stage still ran: its attempt logs must be present"


def test_b4_the_writer_is_called_by_bare_name_so_a_patch_can_bite():
    assert "save_stage_prompt" in _co_names_deep(foundry.run_stage), (
        "run_stage must call save_stage_prompt by BARE module name, or neither a "
        "monkeypatch nor Behavior 4's guarantee is observable")


# ==========================================================================
# Behavior 5 -- naming is single-sourced and pure
# ==========================================================================
@pytest.mark.parametrize("stage,attempt,expected", [
    ("tester", 2, "tester.attempt2.prompt"),
    ("engineer", 1, "engineer.attempt1.prompt"),
    ("pm", 4, "pm.attempt4.prompt"),
    ("final", 3, "final.attempt3.prompt"),
])
def test_b5_naming_helper_maps_the_pair_to_the_filename(stage, attempt, expected):
    assert foundry.stage_prompt_name(stage, attempt) == expected


@pytest.mark.parametrize("stage,attempt", [
    ("tester", 2), ("engineer", 1), ("pm", 4), ("reviewer", 3), ("final", 2),
])
def test_b5_the_name_pairs_one_to_one_with_the_existing_attempt_log(stage, attempt):
    """The pairing IS the discovery mechanism, so state it as an equation against
    the log name the loop has always written."""
    log_name = "%s.attempt%d.log" % (stage, attempt)
    assert foundry.stage_prompt_name(stage, attempt) == \
        log_name[: -len(".log")] + PROMPT_SUFFIX


def test_b5_the_name_is_a_bare_filename_with_no_path_component():
    name = foundry.stage_prompt_name("tester", 2)
    assert "/" not in name and "\\" not in name and ".." not in name, (
        "the helper must return a filename, not a path: %r" % name)
    assert pathlib.Path(name).name == name


def test_b5_the_helper_is_pure_and_touches_no_filesystem(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        assert foundry.stage_prompt_name("tester", 2) == "tester.attempt2.prompt"
    assert list(tmp_path.iterdir()) == [], "a pure naming helper wrote to disk"


def test_b5_the_producer_single_sources_its_filename_from_the_helper():
    """Producer and any future reader cannot disagree only if there is ONE name
    expression. The writer seam must reach the helper by bare name."""
    assert "stage_prompt_name" in _co_names_deep(foundry.save_stage_prompt), (
        "save_stage_prompt must derive its filename from stage_prompt_name, "
        "otherwise the name exists twice and can drift")


def test_b5_the_writer_returns_the_single_sourced_path(tmp_path):
    """Drive the seam directly: it writes the given text under the given dir at
    the helper's name and returns that path."""
    it_dir = tmp_path / "iter-999"
    it_dir.mkdir(parents=True)
    text = "exact prompt text 213\nwith a second line\n"
    got = foundry.save_stage_prompt(it_dir, "tester", 2, text)
    assert isinstance(got, pathlib.Path)
    assert got == it_dir / foundry.stage_prompt_name("tester", 2)
    assert got.read_text(encoding="utf-8") == text
    assert sorted(p.name for p in it_dir.iterdir()) == ["tester.attempt2.prompt"]


# ==========================================================================
# Behavior 6 -- containment; no .gitignore change is needed or made
# ==========================================================================
def test_b6_the_tracked_gitignore_already_covers_the_state_dir():
    """Asserted against the TRACKED, control-path-frozen `.gitignore` -- never
    against local ignored state, so this holds in a fresh clone."""
    lines = [ln.strip() for ln in _GITIGNORE.read_text(encoding="utf-8").splitlines()]
    assert "products/*/state/" in lines, (
        "the tracked .gitignore no longer carries products/*/state/, so the new "
        "runtime artifact could leak into a ship diff")


def test_b6_no_new_gitignore_entry_was_added_for_this_artifact():
    """The whole point of landing inside an already-ignored directory: the frozen
    control path (dispatcher.py / scripts/ / .gitignore) stays untouched."""
    text = _GITIGNORE.read_text(encoding="utf-8")
    assert PROMPT_SUFFIX not in text, (
        ".gitignore mentions %r -- containment was supposed to make that "
        "unnecessary, and .gitignore is frozen this iteration" % PROMPT_SUFFIX)


def test_b6_every_persisted_path_is_inside_cfg_state(monkeypatch, tmp_path):
    d = _drive(monkeypatch, tmp_path)
    written = [p for p in d.it_dir.rglob("*" + PROMPT_SUFFIX)]
    assert written, "precondition: the drive persisted nothing"
    for p in written:
        assert p.resolve().is_relative_to(d.cfg.state.resolve()), (
            "%s escaped cfg.state, so .gitignore's products/*/state/ rule would "
            "not cover it" % p)


def test_b6_nothing_is_written_outside_the_iteration_dir(monkeypatch, tmp_path):
    """A drive must leave no `.prompt` anywhere else under the work root."""
    d = _drive(monkeypatch, tmp_path)
    work_root = pathlib.Path(str(d.cfg.work_root))
    stray = [p for p in work_root.rglob("*" + PROMPT_SUFFIX)
             if p.parent != d.it_dir]
    assert stray == [], "prompt artifacts appeared outside the iteration dir: %r" % (
        [str(p) for p in stray],)


# ==========================================================================
# Acceptance criteria
# ==========================================================================
def test_ac_import_safety_of_both_modules():
    assert foundry.__file__ and dispatcher.__file__


def test_ac_attempt_one_argv_is_still_byte_identical_to_build_prompt(
        monkeypatch, tmp_path):
    """The hoist must not change what is SENT. iter 129 pins this too; repeated
    here because this iteration is the one that touches the expression."""
    d = _drive(monkeypatch, tmp_path)
    assert _prompt_argv_element(d.calls[0]) == SENTINEL


def test_ac_the_drive_is_offline_no_real_spawn_and_no_sleep(monkeypatch, tmp_path):
    """Determinism guard: every attempt went through the patched seam, so no real
    agent process, socket or sleep was involved."""
    d = _drive(monkeypatch, tmp_path)
    assert len(d.calls) == foundry.MAX_ATTEMPTS
    for call in d.calls:
        assert _argv(call), "an attempt reached subprocess.run with no argv"


# ==========================================================================
# Behavior 1, extended -- the persisted bytes must be EXACT, which a 19-char
# ASCII sentinel cannot demonstrate. Out of Scope forbids "bounding, truncating,
# compressing or redacting the persisted prompt", so both holes are on-spec:
# a writer that truncates at any cap, or that re-encodes, passes every
# sentinel-sized assertion above.
# ==========================================================================
NON_ASCII_PROMPT = (
    "SENTINEL-PROMPT-213-UNICODE\n"
    "em dash \u2014 arrow \u2192 nbsp \u00a0 quote \u201cq\u201d\n"
    "cjk \u4e2d\u6587\u6d4b\u8bd5 greek \u03b1\u03b2\u03b3\n"
    "astral \U0001f600 combining e\u0301\n"
)


def test_b1_a_non_ascii_prompt_round_trips_byte_for_byte(monkeypatch, tmp_path):
    """Real prompts are not ASCII: the injected learnings digest carries em
    dashes, arrows and CJK. A writer that re-encodes (or opens the file without
    an explicit encoding on a non-UTF-8 default locale) is invisible to an ASCII
    sentinel, because ASCII is a fixed point of every such encoding."""
    d = _drive(monkeypatch, tmp_path, prompt=NON_ASCII_PROMPT, write_output=True)
    assert d.ok is True and len(d.calls) == 1
    sent = _prompt_argv_element(d.calls[0], prompt=NON_ASCII_PROMPT)
    assert sent == NON_ASCII_PROMPT, "precondition: the argv element is the prompt"
    f = d.it_dir / foundry.stage_prompt_name(STAGE, 1)
    assert f.read_bytes() == NON_ASCII_PROMPT.encode("utf-8"), (
        "the persisted prompt is not the UTF-8 encoding of the text that was "
        "sent (persisted %d bytes, sent %d)"
        % (f.stat().st_size, len(NON_ASCII_PROMPT.encode("utf-8"))))
    assert f.read_text(encoding="utf-8") == sent, (
        "the persisted prompt does not decode back to the string that was sent")


def test_b1_a_realistically_large_prompt_is_persisted_whole(monkeypatch, tmp_path):
    """No truncation, at a size well past this product's real prompts (measured
    ~20-22 KB per stage). A cap anywhere -- 4 KiB, 8 KiB, 64 KiB -- would defeat
    GAP-041, whose whole content is that the EXACT input is kept, and every
    assertion above would still pass because the sentinel is 19 chars."""
    big = "".join("line %06d of a large assembled prompt\n" % i
                  for i in range(5000))
    assert len(big) == 200000, "measured fixture size, not a predicted one"
    d = _drive(monkeypatch, tmp_path, prompt=big, write_output=True)
    assert d.ok is True and len(d.calls) == 1
    sent = _prompt_argv_element(d.calls[0], prompt=big)
    f = d.it_dir / foundry.stage_prompt_name(STAGE, 1)
    got = f.read_bytes()
    assert len(got) == len(sent.encode("utf-8")), (
        "the persisted prompt was truncated or padded: %d bytes on disk vs %d sent"
        % (len(got), len(sent.encode("utf-8"))))
    assert got == sent.encode("utf-8"), (
        "the persisted prompt is the right LENGTH but not the right BYTES")
    assert got.endswith(b"line 004999 of a large assembled prompt\n"), \
        "the tail of the prompt is missing -- a truncating writer"


def test_ac_new_code_and_this_test_scan_clean_under_the_committed_denylist():
    if not (_LEAK_GUARD.exists() and _DENYLIST.exists()):
        pytest.skip("leak-guard not present in this repo (repo-agnostic)")
    lg = _load_leak_guard()
    patterns = lg.load_denylist(_DENYLIST.read_text())
    home_prefix = "/" + "Users" + "/"  # built at runtime; never a source literal
    # two-sided: prove the matcher is LIVE before trusting a clean result
    assert len(lg.scan_text(home_prefix + "somebody/x", patterns)) >= 1, \
        "denylist appears inert (a home-path probe did not match)"
    texts = {
        "this test file": THIS_TEST.read_text(encoding="utf-8"),
        "stage_prompt_name": inspect.getsource(foundry.stage_prompt_name),
        "save_stage_prompt": inspect.getsource(foundry.save_stage_prompt),
    }
    for label, txt in texts.items():
        assert len(lg.scan_text(txt, patterns)) == 0, \
            "%s contains a denylisted token (would BLOCK this iteration's ship)" % label
        assert home_prefix not in txt, \
            "%s contains an absolute home-directory path" % label
