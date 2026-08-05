"""Black-box behaviour tests for iter 114 -- wiring the DORMANT connect-probe
IPC-endpoint resolver `foundry.resolve_agent_endpoint` into `foundry.run_stage`
so every stage child is handed a freshly-resolved LIVE agent IPC endpoint.

Spec (Expected Behaviors 1-7):
  1. Live endpoint injected: resolver -> non-empty str P => subprocess.run gets
     env= containing all of os.environ AND env[KEY] == P (overriding a stale
     inherited value of KEY).
  2. None => no env change: resolver -> None => subprocess.run called with NO
     env= keyword (byte-identical default). The real resolver pointed at an
     empty socket dir returns None, so an unconfigured machine sees zero change.
  3. Resolver called through its bare module name: monkeypatching
     foundry.resolve_agent_endpoint changes what run_stage uses;
     _co_names_deep(run_stage) contains the symbol.
  4. Per-attempt resolution: a resolver returning "A","B",... on successive
     calls yields env[KEY]=="A" on the first spawn and "B" on the second, etc.
  5. Success/failure contract unchanged: (True,out) iff out exists and is
     non-empty after an attempt; (False,out) after exhausting MAX_ATTEMPTS. Env
     injection never alters the return value.
  6. run_stage is the SOLE in-module caller (no other orchestrator; not
     dispatcher.py / watchdog.py).
  7. Imports + public surface intact; resolver signature is (sock_dir=None).

ISOLATION CONTRACT (honored): these tests were written from the PM spec and the
product's OBSERVABLE runtime behaviour only. run_stage is driven as a black box
with `foundry.subprocess.run`, `foundry.build_prompt`, `foundry.sleep_interruptible`
and `foundry.resolve_agent_endpoint` monkeypatched so NO real app, socket, git,
network, sleep, or agent subprocess is used. The implementation SOURCE LOGIC of
foundry.py, the engineer's/reviewer's notes and `git diff` were NOT read. The
call-site proof (Behavior 6) uses only public runtime introspection (compiled
function name tables via _co_names_deep, the iter-107 convention) plus a
dispatcher/watchdog module scan. The mechanical ASCII / leak-clean checks feed a
byte-scan straight to a scanner (suite convention), never a read of logic.

The denylisted vendor env-var key is NEVER written as a literal here: it is read
from the public module constant `foundry._AGENT_ENDPOINT_ENV` at runtime (KEY),
which is exactly the split-literal constant run_stage uses to inject it.
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
import watchdog  # noqa: E402  (import-safety probe)

_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
WATCHDOG_PY = _ROOT / "watchdog.py"
THIS_TEST = pathlib.Path(__file__).resolve()

ITERATION = 114
SYMBOL = "resolve_agent_endpoint"
# Runtime value of the env-var key; NEVER the denylisted literal in source.
KEY = foundry._AGENT_ENDPOINT_ENV


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


def _module_functions(mod):
    out = {}
    for name in dir(mod):
        obj = getattr(mod, name)
        if callable(obj) and hasattr(obj, "__code__"):
            out[name] = obj
        elif isinstance(obj, type):
            for mname, m in vars(obj).items():
                if callable(m) and hasattr(m, "__code__"):
                    out["%s.%s" % (name, mname)] = m
    return out


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter114_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# run_stage drive harness (fully offline)
# --------------------------------------------------------------------------
class _FakeCP:
    """Stand-in for subprocess.CompletedProcess: only the attributes run_stage
    reads (.returncode/.stdout/.stderr) are provided."""
    def __init__(self, rc=0, out="ok", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _make_cfg(tmp_path):
    """A minimal product config in a tmp dir (mirrors the suite convention);
    repo + work_root are TMP so the real foundry repo is NEVER touched."""
    import json
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


def _patch_common(monkeypatch):
    """Neutralise build_prompt (so no real role/vision/learnings needed) and
    sleep_interruptible (so retry backoff is instant and never stops early)."""
    monkeypatch.setattr(foundry, "build_prompt", lambda *a, **k: "PROMPT")
    monkeypatch.setattr(foundry, "sleep_interruptible", lambda cfg, s: False)


def _drive(monkeypatch, cfg, role, out_name, resolver, write=False):
    """Drive run_stage once. Records the kwargs of every subprocess.run call.
    If write=True the fake writes a non-empty out file on its FIRST call (the
    out path is discovered black-box via a throwaway non-writing run first)."""
    _patch_common(monkeypatch)
    out_path = None
    if write:
        monkeypatch.setattr(foundry, "resolve_agent_endpoint", lambda *a, **k: None)
        monkeypatch.setattr(foundry.subprocess, "run", lambda *a, **k: _FakeCP())
        ok0, out_path = foundry.run_stage(cfg, ITERATION, "tester", role, out_name)
        assert ok0 is False and not out_path.exists()  # discovery leaves no file
    calls = []
    monkeypatch.setattr(foundry, "resolve_agent_endpoint", resolver)

    def fake_run(*a, **k):
        calls.append(dict(k))
        if write and len(calls) == 1:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("STAGE OUTPUT\n")
        return _FakeCP()

    monkeypatch.setattr(foundry.subprocess, "run", fake_run)
    ok, out = foundry.run_stage(cfg, ITERATION, "tester", role, out_name)
    return ok, out, calls


# ==========================================================================
# Behavior 1 -- Live endpoint is injected (and overrides a stale inherited one)
# ==========================================================================
def test_b1_live_endpoint_injected_into_env(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    monkeypatch.setenv(KEY, "STALE-INHERITED")   # dispatcher's dead endpoint
    monkeypatch.setenv("FOUNDRY_MARKER_KEEP", "keepme")
    ok, out, calls = _drive(
        monkeypatch, cfg, role, "tester.md",
        resolver=lambda *a, **k: "LIVE-SOCK-PATH", write=True)
    assert ok is True
    assert len(calls) == 1
    env = calls[0].get("env")
    assert env is not None, "run_stage did not pass env= when resolver returned a live path"
    # (a) contains every key/value of os.environ ...
    for k, v in os.environ.items():
        if k == KEY:
            continue
        assert env.get(k) == v, "env dropped inherited var %r" % k
    assert "FOUNDRY_MARKER_KEEP" in env and env["FOUNDRY_MARKER_KEEP"] == "keepme"
    # (b) ... and overrides the inherited KEY with the resolved live path.
    assert env[KEY] == "LIVE-SOCK-PATH"
    assert os.environ.get(KEY) == "STALE-INHERITED"  # process env unchanged


def test_b1_env_superset_size(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(
        monkeypatch, cfg, role, "tester.md",
        resolver=lambda *a, **k: "P", write=True)
    env = calls[0]["env"]
    # A superset (or equal) of os.environ -- injection only ever adds/overrides KEY.
    assert set(os.environ).issubset(set(env))
    assert env[KEY] == "P"


# ==========================================================================
# Behavior 2 -- None => no env change (byte-identical default)
# ==========================================================================
def test_b2_none_resolver_passes_no_env(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(
        monkeypatch, cfg, role, "tester.md",
        resolver=lambda *a, **k: None, write=True)
    assert ok is True
    assert len(calls) == 1
    assert "env" not in calls[0] or calls[0].get("env") is None, (
        "resolver None must leave subprocess.run's env unset (byte-identical)")


def test_b2_real_resolver_empty_dir_returns_none_no_env(tmp_path, monkeypatch):
    # Integration with the REAL resolver: pointed at an EMPTY socket dir it
    # returns None deterministically, so run_stage passes no env= -- the
    # "unconfigured machine sees zero behavior change" guarantee, made robust
    # against any live socket in the platform default dir.
    empty = tmp_path / "empty_sock_dir"
    empty.mkdir()
    monkeypatch.setenv("FOUNDRY_AGENT_SOCK_DIR", str(empty))
    assert foundry.resolve_agent_endpoint() is None  # precondition
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    # Use the REAL resolver (not a fake) this time.
    _patch_common(monkeypatch)
    calls = []
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: (calls.append(dict(k)) or _FakeCP()))
    ok, out = foundry.run_stage(cfg, ITERATION, "tester", role, "tester.md")
    assert ok is False  # nothing wrote the file
    assert calls, "subprocess.run was never invoked"
    assert all(("env" not in c or c.get("env") is None) for c in calls), (
        "real resolver returned None but run_stage still injected env=")


def test_b2_default_resolver_str_or_none_without_raising():
    # The real default-arg resolver is environment-dependent; it must not raise
    # and must return str-or-None. Value NOT asserted (iter-110 convention).
    got = foundry.resolve_agent_endpoint()
    assert got is None or isinstance(got, str)


# ==========================================================================
# Behavior 3 -- resolver is reached through its bare module name
# ==========================================================================
def test_b3_bare_name_reference():
    assert SYMBOL in _co_names_deep(foundry.run_stage), (
        "run_stage must reference %s by bare name" % SYMBOL)


def test_b3_monkeypatched_fake_is_observed(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    seen = []

    def spy_resolver(*a, **k):
        seen.append(True)
        return "SPY-PATH"

    ok, out, calls = _drive(monkeypatch, cfg, role, "tester.md",
                            resolver=spy_resolver, write=True)
    assert seen, "run_stage did not call the monkeypatched resolver (not bare name?)"
    assert calls[0]["env"][KEY] == "SPY-PATH"


# ==========================================================================
# Behavior 4 -- resolution is per-attempt
# ==========================================================================
def test_b4_per_attempt_resolution(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    seq = iter(["A", "B", "C", "D"])
    # Never write the out file => forces the full MAX_ATTEMPTS retry loop.
    ok, out, calls = _drive(monkeypatch, cfg, role, "tester.md",
                            resolver=lambda *a, **k: next(seq), write=False)
    assert ok is False
    assert len(calls) == foundry.MAX_ATTEMPTS
    per_attempt = [c["env"][KEY] for c in calls]
    assert per_attempt == ["A", "B", "C", "D"][:foundry.MAX_ATTEMPTS], per_attempt


def test_b4_first_two_attempts_A_then_B(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    seq = iter(["A", "B", "B", "B"])
    ok, out, calls = _drive(monkeypatch, cfg, role, "tester.md",
                            resolver=lambda *a, **k: next(seq), write=False)
    assert calls[0]["env"][KEY] == "A"
    assert calls[1]["env"][KEY] == "B"


# ==========================================================================
# Behavior 5 -- success/failure contract unchanged
# ==========================================================================
def test_b5_success_returns_true_and_path(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, "tester.md",
                            resolver=lambda *a, **k: "P", write=True)
    assert ok is True
    assert isinstance(out, pathlib.Path)
    assert out.exists() and out.stat().st_size > 0
    assert len(calls) == 1  # succeeded on first attempt


def test_b5_failure_returns_false_after_max_attempts(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    ok, out, calls = _drive(monkeypatch, cfg, role, "tester.md",
                            resolver=lambda *a, **k: "P", write=False)
    assert ok is False
    assert isinstance(out, pathlib.Path)
    assert not out.exists()
    assert len(calls) == foundry.MAX_ATTEMPTS


def test_b5_empty_output_file_is_failure(tmp_path, monkeypatch):
    # A zero-byte out file is NOT "non-empty" -> failure (contract unchanged).
    cfg = _make_cfg(tmp_path)
    role = _role_file(tmp_path)
    _patch_common(monkeypatch)
    monkeypatch.setattr(foundry, "resolve_agent_endpoint", lambda *a, **k: None)
    monkeypatch.setattr(foundry.subprocess, "run", lambda *a, **k: _FakeCP())
    ok0, out = foundry.run_stage(cfg, ITERATION, "tester", role, "tester.md")
    assert ok0 is False

    calls = []

    def fake_run(*a, **k):
        calls.append(dict(k))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("")  # empty
        return _FakeCP()

    monkeypatch.setattr(foundry.subprocess, "run", fake_run)
    ok, out2 = foundry.run_stage(cfg, ITERATION, "tester", role, "tester.md")
    assert ok is False, "an empty output file must count as failure"
    assert out2.exists() and out2.stat().st_size == 0


def test_b5_env_injection_does_not_change_return(tmp_path, monkeypatch):
    # Same success input, once with a live endpoint and once with None -> the
    # (ok, out) return is identical; env injection is transparent to the caller.
    cfg1 = _make_cfg(tmp_path / "a")
    cfg2 = _make_cfg(tmp_path / "b")
    r1 = _role_file(tmp_path / "a")
    r2 = _role_file(tmp_path / "b")
    ok_live, out_live, _ = _drive(monkeypatch, cfg1, r1, "tester.md",
                                  resolver=lambda *a, **k: "P", write=True)
    ok_none, out_none, _ = _drive(monkeypatch, cfg2, r2, "tester.md",
                                  resolver=lambda *a, **k: None, write=True)
    assert ok_live is True and ok_none is True
    assert out_live.name == out_none.name == "tester.md"


# ==========================================================================
# Behavior 6 -- run_stage is the SOLE in-module caller
# ==========================================================================
def test_b6_only_run_stage_calls_resolver():
    callers = sorted(
        name for name, fn in _module_functions(foundry).items()
        if SYMBOL in _co_names_deep(fn))
    assert callers == ["run_stage"], (
        "%s must have exactly one in-module caller (run_stage), got %r"
        % (SYMBOL, callers))


def test_b6_named_orchestrators_do_not_reference_resolver():
    for fn in (foundry.build_prompt, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan,
               foundry.scout_phase_outcome, foundry.run_scout_phase):
        assert SYMBOL not in _co_names_deep(fn), (
            "orchestrator foundry.%s references %s (only run_stage may)"
            % (fn.__name__, SYMBOL))


def test_b6_dispatcher_and_watchdog_have_zero_references():
    for py in (DISPATCHER_PY, WATCHDOG_PY):
        assert py.read_text(encoding="utf-8").count(SYMBOL) == 0, (
            "%s references %s" % (py.name, SYMBOL))
    for mod in (dispatcher, watchdog):
        for name, fn in _module_functions(mod).items():
            assert SYMBOL not in _co_names_deep(fn), (
                "%s.%s references %s" % (mod.__name__, name, SYMBOL))


# ==========================================================================
# Behavior 7 -- imports + public surface intact
# ==========================================================================
def test_b7_imports_and_signature():
    assert callable(foundry.resolve_agent_endpoint)
    sig = inspect.signature(foundry.resolve_agent_endpoint)
    assert list(sig.parameters) == ["sock_dir"]
    assert sig.parameters["sock_dir"].default is None
    assert callable(foundry.run_stage)


def test_b7_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher, watchdog"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b7_key_constant_is_the_endpoint_env(tmp_path):
    # The injected key is the agent IPC-endpoint env var, referenced via the
    # split-literal constant (never the denylisted literal in this file).
    assert isinstance(KEY, str) and KEY
    assert KEY.endswith("_IPC_ENDPOINT")
    assert "IPC_ENDPOINT" in KEY


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
