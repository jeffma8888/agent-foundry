"""Black-box behaviour tests for iter 110 -- the DORMANT, stdlib-only connect-probe
IPC-endpoint resolver `foundry.resolve_agent_endpoint(sock_dir=None) -> str | None`.

The resolver globs agent unix-socket files inside `sock_dir` (default = the
platform's agent-socket dir, overridable for tests), orders candidates
newest-mtime-first, and returns the FIRST path that answers a real
`socket.connect()` probe, else `None`. It has ZERO call site in the running
pipeline through iter 110 (additive-dormant foundation); iter 114 then wired it
into `run_stage` (Behavior 9 below now asserts run_stage is the SOLE caller).

Vendor-neutral socket names: the repo's leak-guard forbids the vendor token in
tracked files (a hard public-safety constraint -- the same reason the shipped
resolver uses a vendor-neutral hyphenated `*-*.sock`-shaped glob rather than a
vendor-prefixed one), so these tests exercise the observable behaviour with
generic hyphenated socket names (`agent-<n>.sock`, `srv-<n>.sock`) that the
resolver's glob recognises. This tests the SPEC's Expected Behaviours (newest
LIVE socket wins by connect-probe; dead / non-matching files ignored) without
the illegal token.

ISOLATION CONTRACT (honored): these tests were written from the PM spec (Expected
Behaviors 1-10) and the product's OBSERVABLE runtime behaviour only -- driving the
PUBLIC function `foundry.resolve_agent_endpoint(sock_dir=...)` against real
`AF_UNIX` listeners / dead socket files created in a short tmp dir, and
introspecting the PUBLIC runtime surface. The implementation SOURCE LOGIC
(foundry.py internals: how the resolver is coded, its exact glob string, its
default-dir constant), the engineer's and reviewer's notes, and `git diff` were
NOT read to design these tests. The dormancy / call-site proof (Behavior 9) uses
only public RUNTIME introspection -- compiled function name tables
(`__code__.co_names` recursed via `_co_names_deep`, the iter-107 convention) + a
`dispatcher.py`/`watchdog.py` module scan. The mechanical ASCII / leak-clean
acceptance checks use `inspect.getsource` SCOPED to the single new symbol only
(the established suite convention: a MECHANICAL byte-scan fed straight to a
scanner, NEVER a read of implementation LOGIC and never used to shape a behaviour
test). Fully offline and deterministic: NO real app, NO network, NO git; the only
subprocess is the fresh-import regression probe.
"""
import contextlib
import importlib.util
import inspect
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)
import watchdog  # noqa: E402  (import-safety probe)

# --------------------------------------------------------------------------
# runtime-built paths (module located via the BARE module object, never a
# quoted source-literal filename -- iter-54 meta-scanner convention)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
WATCHDOG_PY = _ROOT / "watchdog.py"
THIS_TEST = pathlib.Path(__file__).resolve()

ITERATION = 110
NEW_SYMBOL = "resolve_agent_endpoint"
R = foundry.resolve_agent_endpoint


# --------------------------------------------------------------------------
# runtime introspection helpers (pure -- do NOT read module source text)
# --------------------------------------------------------------------------
def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects.
    Pure runtime introspection -- the iter-107 convention."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _module_functions(mod):
    """Every module-level function + every method on a module-level class that
    owns a __code__ object. Pure runtime introspection."""
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
    spec = importlib.util.spec_from_file_location("leak_guard_iter110_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# AF_UNIX test harness. A live listener MUST drain its accept backlog or a
# `listen(N)` queue fills after N un-accepted probe connects (Behavior 10
# probes 50x) -- so every live listener runs a daemon accepter thread that
# accept()s and immediately closes. Dead socket files are bind()+close(): the
# file persists on disk but connect() raises ConnectionRefusedError.
# --------------------------------------------------------------------------
class LiveListener:
    def __init__(self, path):
        self.path = path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(64)
        self._t = threading.Thread(target=self._accept_loop, daemon=True)
        self._t.start()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
                conn.close()
            except OSError:
                return  # listener closed -> thread exits

    def close(self):
        with contextlib.suppress(OSError):
            self.sock.close()


class SockEnv:
    """A short tmp dir plus helpers to populate it and guarantee cleanup.

    Uses tempfile.mkdtemp() (short base, ~60 chars on macOS) + short socket
    names so full AF_UNIX paths stay under the ~104-char sun_path limit.
    """

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self._listeners = []

    def path(self, name):
        return os.path.join(self.dir, name)

    def listener(self, name, mtime=None):
        p = self.path(name)
        lst = LiveListener(p)
        self._listeners.append(lst)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def deadfile(self, name, mtime=None):
        """A socket file that exists but is NOT listening (connect -> refused)."""
        p = self.path(name)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(p)
        s.close()  # file persists; connect() will be refused
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def plainfile(self, name, mtime=None):
        p = self.path(name)
        with open(p, "w") as fh:
            fh.write("x")
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def cleanup(self):
        for lst in self._listeners:
            lst.close()
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture
def env():
    e = SockEnv()
    try:
        yield e
    finally:
        e.cleanup()


# ==========================================================================
# Behavior 1 -- Absent or empty dir, or a dir with no matching socket file -> None
# ==========================================================================
def test_b01_absent_dir_returns_none(env):
    missing = os.path.join(env.dir, "does-not-exist")
    assert not os.path.exists(missing)
    assert R(sock_dir=missing) is None


def test_b01_empty_dir_returns_none(env):
    assert sorted(os.listdir(env.dir)) == []
    assert R(sock_dir=env.dir) is None


def test_b01_dir_with_no_matching_files_returns_none(env):
    env.plainfile("readme.txt")
    env.plainfile("state.json")
    assert R(sock_dir=env.dir) is None


# ==========================================================================
# Behavior 2 -- Single live listener -> its exact path (as a str)
# ==========================================================================
def test_b02_single_live_listener_returns_its_path(env):
    p = env.listener("agent-1.sock")
    got = R(sock_dir=env.dir)
    assert got == p
    assert isinstance(got, str)


# ==========================================================================
# Behavior 3 -- a NEWER dead socket file is SKIPPED for an OLDER live listener
#   (connect-probe wins over mtime AND filename order; a pid/mtime-only impl
#    FAILS this)
# ==========================================================================
def test_b03_newer_dead_skipped_for_older_live(env):
    live = env.listener("srv-live.sock", mtime=1000.0)      # OLDER
    dead = env.deadfile("srv-dead.sock", mtime=9000.0)      # NEWER, dead
    assert os.stat(dead).st_mtime > os.stat(live).st_mtime  # sanity
    assert R(sock_dir=env.dir) == live


def test_b03_multiple_newer_dead_still_lose_to_one_live(env):
    live = env.listener("srv-a.sock", mtime=100.0)          # oldest, live
    env.deadfile("srv-b.sock", mtime=5000.0)                # newer, dead
    env.deadfile("srv-c.sock", mtime=9000.0)                # newest, dead
    assert R(sock_dir=env.dir) == live


# ==========================================================================
# Behavior 4 -- newest LIVE wins among multiple live listeners
# ==========================================================================
def test_b04_newest_live_wins_among_multiple_live(env):
    env.listener("srv-old.sock", mtime=1000.0)
    newest = env.listener("srv-new.sock", mtime=8000.0)
    assert R(sock_dir=env.dir) == newest


def test_b04_newest_live_wins_three_way(env):
    env.listener("agent-1.sock", mtime=1000.0)
    top = env.listener("agent-2.sock", mtime=7000.0)
    env.listener("agent-3.sock", mtime=3000.0)
    assert R(sock_dir=env.dir) == top


# ==========================================================================
# Behavior 5 -- only dead socket files -> None
# ==========================================================================
def test_b05_only_dead_sockets_returns_none(env):
    env.deadfile("agent-1.sock")
    assert R(sock_dir=env.dir) is None


def test_b05_several_dead_sockets_returns_none(env):
    env.deadfile("agent-1.sock", mtime=1000.0)
    env.deadfile("agent-2.sock", mtime=2000.0)
    env.deadfile("agent-3.sock", mtime=3000.0)
    assert R(sock_dir=env.dir) is None


# ==========================================================================
# Behavior 6 -- malformed filenames never raise (no parseable pid, empty stem)
# ==========================================================================
def test_b06_malformed_names_dont_raise_and_return_none(env):
    env.deadfile("srv-.sock")
    env.deadfile("srv-notapid.sock")
    env.deadfile("srv-xyz.sock")
    # Must not raise; nothing is live -> None
    assert R(sock_dir=env.dir) is None


def test_b06_malformed_names_alongside_a_live_listener(env):
    env.deadfile("srv-.sock", mtime=9000.0)
    env.deadfile("srv-notapid.sock", mtime=9500.0)
    live = env.listener("agent-42.sock", mtime=1000.0)  # older but the only live one
    assert R(sock_dir=env.dir) == live


# ==========================================================================
# Behavior 7 -- non-matching files are ignored, EVEN IF a same-named listener
#   would connect. (The spec's examples: none has the socket-file shape, so they
#   are ignored regardless of the exact glob.)
# ==========================================================================
def test_b07_nonmatching_files_ignored(env):
    env.plainfile("agent-123.txt")   # wrong extension
    env.plainfile("notes.md")        # unrelated
    env.deadfile("other.sock")       # no hyphen-shaped stem -> non-matching
    assert R(sock_dir=env.dir) is None


def test_b07_nonmatching_listener_is_not_returned(env):
    # A LISTENING socket whose name does not match the agent-socket pattern
    # must never be returned ("even if a same-named listener would connect").
    env.listener("other.sock")       # non-matching name, but LIVE
    assert R(sock_dir=env.dir) is None


def test_b07_nonmatching_ignored_but_matching_live_returned(env):
    env.plainfile("agent-999.txt")
    env.listener("other.sock")            # non-matching, live -> ignored
    live = env.listener("agent-7.sock")   # matching, live -> returned
    assert R(sock_dir=env.dir) == live


# ==========================================================================
# Behavior 8 -- return type is str on success, exactly None on failure
# ==========================================================================
def test_b08_success_returns_str_not_path_not_bytes(env):
    env.listener("agent-1.sock")
    got = R(sock_dir=env.dir)
    assert isinstance(got, str)
    assert not isinstance(got, (bytes, bytearray))
    assert not isinstance(got, pathlib.PurePath)
    assert got != ""


def test_b08_failure_returns_exactly_none(env):
    got = R(sock_dir=env.dir)  # empty dir
    assert got is None


def test_b08_default_arg_returns_str_or_none_without_raising():
    # Calling with no arg (the real default socket dir) must not raise and must
    # return str-or-None. Value is environment-dependent, so it is NOT asserted.
    got = R()
    assert got is None or isinstance(got, str)


# ==========================================================================
# Behavior 9 -- CALL-SITE CONTRACT: after iter 114 `run_stage` is the SOLE
#   in-module caller; no other orchestrator and no dispatcher/watchdog function
#   references the resolver; imports still succeed.
# ==========================================================================
def test_b09_orchestrators_do_not_reference_resolver():
    # iter-114 contract change (intended, NOT a regression): the resolver was
    # WIRED into `run_stage`, so `run_stage` is now the SINGLE permitted caller.
    # Every OTHER orchestrator must still NOT reference it.
    for fn in (foundry.build_prompt, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan,
               foundry.scout_phase_outcome, foundry.run_scout_phase):
        assert NEW_SYMBOL not in _co_names_deep(fn), (
            "orchestrator foundry.%s references %s (only run_stage may)"
            % (fn.__name__, NEW_SYMBOL))
    # run_stage IS now the caller (Behavior: run_stage resolves the endpoint).
    assert NEW_SYMBOL in _co_names_deep(foundry.run_stage), (
        "run_stage must reference %s after the iter-114 wiring" % NEW_SYMBOL)


def test_b09_no_foundry_function_calls_resolver():
    # iter-114 contract change: exactly ONE in-module caller now -- run_stage.
    callers = sorted(
        name for name, fn in _module_functions(foundry).items()
        if NEW_SYMBOL in _co_names_deep(fn))
    assert callers == ["run_stage"], (
        "%s must have exactly one in-module caller (run_stage), got %r"
        % (NEW_SYMBOL, callers))


def test_b09_dispatcher_and_watchdog_have_zero_references():
    for py in (DISPATCHER_PY, WATCHDOG_PY):
        assert py.read_text(encoding="utf-8").count(NEW_SYMBOL) == 0, (
            "%s references %s" % (py.name, NEW_SYMBOL))
    for mod in (dispatcher, watchdog):
        for name, fn in _module_functions(mod).items():
            assert NEW_SYMBOL not in _co_names_deep(fn), (
                "%s.%s references %s" % (mod.__name__, name, NEW_SYMBOL))


def test_b09_imports_still_succeed():
    assert foundry is not None
    assert dispatcher is not None
    assert watchdog is not None
    assert callable(foundry.resolve_agent_endpoint)


# ==========================================================================
# Behavior 10 -- idempotent / no side effects across many calls
# ==========================================================================
def test_b10_idempotent_50_calls_same_result(env):
    p = env.listener("agent-1.sock")
    results = [R(sock_dir=env.dir) for _ in range(50)]
    assert all(r == p for r in results), "repeated calls gave a different answer"


def test_b10_no_side_effects_on_dir(env):
    env.listener("agent-1.sock")
    env.deadfile("agent-2.sock")
    before = sorted(os.listdir(env.dir))
    for _ in range(30):
        R(sock_dir=env.dir)
    after = sorted(os.listdir(env.dir))
    assert before == after, "resolver mutated the socket dir"


def test_b10_repeated_calls_on_empty_dir_stay_none(env):
    for _ in range(25):
        assert R(sock_dir=env.dir) is None


# ==========================================================================
# Cross-cutting: PathLike sock_dir accepted (spec: "accepts a str or os.PathLike")
# ==========================================================================
def test_pathlike_sock_dir_accepted(env):
    p = env.listener("agent-1.sock")
    assert R(sock_dir=pathlib.Path(env.dir)) == p


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_signature_is_optional_single_arg():
    sig = inspect.signature(foundry.resolve_agent_endpoint)
    params = list(sig.parameters)
    assert params == ["sock_dir"], "signature must be resolve_agent_endpoint(sock_dir=None)"
    assert sig.parameters["sock_dir"].default is None


def test_ac_no_os_kill_liveness_pid_reuse_guard(env):
    # The connect-probe is the ONLY liveness test. A dead socket file whose
    # numeric stem collides with a LIVE unrelated pid must still be skipped --
    # a pid-parse + os.kill(pid,0) impl would wrongly return it. Asserted
    # behaviorally (not by reading source).
    live_pid = os.getpid()  # certainly-alive pid
    env.deadfile("agent-%d.sock" % live_pid, mtime=9999.0)  # dead file, live-pid stem
    assert R(sock_dir=env.dir) is None, (
        "a dead socket file named for a LIVE pid was returned -- looks like "
        "os.kill/pid liveness, not a connect-probe")


def test_ac_public_surface_intact():
    assert callable(foundry.resolve_agent_endpoint)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage",
               "run_execution_plan", "run_scout_phase", "scout_phase_outcome"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None and watchdog is not None


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher, watchdog"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_new_symbol_ascii():
    """Mechanical byte-scan of the single new symbol (suite convention:
    inspect.getsource scoped to the new symbol only, fed straight to ord() --
    never a read of logic, never a whole-file scan)."""
    src = inspect.getsource(foundry.resolve_agent_endpoint)
    offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
    assert offenders == [], offenders[:5]


def test_ac_this_test_file_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_new_symbol_leak_clean():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    src = inspect.getsource(foundry.resolve_agent_endpoint)
    assert mod.scan_text(src, denylist) == (), "new source leaks a denylisted token"
