"""Black-box behaviour tests for iter 25 -- a machine-readable `--json` output for
the read-only `foundry single-brain` launch-preflight subcommand (iter-24). Purely
ADDITIVE over the already-frozen iter-24 core (the exact `--json` complement pattern
shipped in iters 19/20/21/23). Surface under test:

  * `SingleBrainStatus.to_dict() -> dict` -- a NEW pure method exposing the frozen
    snapshot as a JSON-native document (7 ordered keys), re-deriving nothing (reuses
    the frozen `unknown`/`conflict`/`safe`/`verdict`/`exit_code` properties),
  * `single_brain_cli(pattern="dispatcher.py", as_json: bool = False) -> int` --
    on `as_json=True` prints `json.dumps(status.to_dict(), indent=2)`; on False the
    unchanged iter-24 `status.render()`; both return `status.exit_code`, write nothing,
  * a `single-brain --json` argparse flag (`store_true`, default off) routed by
    `main` to `single_brain_cli(pattern=..., as_json=args.json)`.

ISOLATION CONTRACT (honored): this file was written from the iter-25 PM spec's
Expected Behaviors (1-11) and the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure `foundry.summarize_single_brain(...)` builder + its new
`to_dict()`, the `foundry.single_brain_cli(...)` / `foundry.main(["single-brain",
...])` CLI with the documented process-scan seam `foundry.running_dispatchers`
monkeypatched WHOLESALE (forced offline -- zero real pgrep/subprocess). Behavior 11's
off-control-path checks use only public RUNTIME introspection (compiled
`__code__.co_names`/`co_consts` + `dispatcher` attributes) and the documented
`import foundry, dispatcher` subprocess probe -- NOT the source text. Fully offline &
deterministic: CLI tests run in a chdir'd tmp dir and snapshot it before/after to
prove the writes-nothing contract; the subprocess exit-code tests patch the seam by
bare name inside the child so no real dispatcher scan runs.
"""
import io
import json
import os
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# constants / helpers
# --------------------------------------------------------------------------
DICT_KEYS = ("pids", "scan_error", "unknown", "conflict", "safe", "verdict", "exit_code")
DERIVED = ("unknown", "conflict", "safe", "verdict", "exit_code")
# the four control-flow / pipeline fns that must stay off the single-brain surface
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _set_scan(monkeypatch, ret=None, exc=None, spy=None):
    """Force the ONE process-scan seam offline (patched by BARE name, per spec).
    Either return `ret` (a tuple), or raise `exc`. `spy` records each pattern."""
    def fake(pattern="dispatcher.py"):
        if spy is not None:
            spy.append(pattern)
        if exc is not None:
            raise exc
        return ret if ret is not None else ()
    monkeypatch.setattr(foundry, "running_dispatchers", fake)


def _fn_names_consts(fn):
    """Recursively gather LOAD_ATTR/name symbols + string consts a function's
    compiled code references (unpacks nested code/tuple/frozenset consts, so a
    kwnames tuple like ('as_json',) is caught too)."""
    stack, seen = [fn.__code__], set()
    names, consts = set(), set()

    def _add_const(c):
        if isinstance(c, str):
            consts.add(c)
        elif isinstance(c, types.CodeType):
            stack.append(c)
        elif isinstance(c, (tuple, frozenset)):
            for x in c:
                _add_const(x)

    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            _add_const(c)
    return names, consts


def _module_names_consts(module):
    names, consts = set(), set()
    for v in vars(module).values():
        if isinstance(v, types.FunctionType):
            n, c = _fn_names_consts(v)
            names |= n
            consts |= c
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    n, c = _fn_names_consts(m)
                    names |= n
                    consts |= c
    return names, consts


# the three canonical statuses used across the spec
def _safe():
    return foundry.summarize_single_brain(())


def _conflict(pids=(123, 456)):
    return foundry.summarize_single_brain(pids)


def _unknown(msg="no pgrep"):
    return foundry.summarize_single_brain((), scan_error=msg)


# ==========================================================================
# Behavior 1 -- SAFE to_dict(): EXACTLY the 7 ordered keys + SAFE values
# ==========================================================================
def test_b1_safe_to_dict_keys_order_and_values():
    d = _safe().to_dict()
    assert isinstance(d, dict)
    assert list(d.keys()) == list(DICT_KEYS), (
        f"to_dict() must return exactly {DICT_KEYS} in order, got {list(d.keys())}")
    assert d["pids"] == [] and isinstance(d["pids"], list)
    assert d["scan_error"] is None
    assert d["unknown"] is False
    assert d["conflict"] is False
    assert d["safe"] is True
    assert d["verdict"] == "SAFE"
    assert d["exit_code"] == 0


# ==========================================================================
# Behavior 2 -- CONFLICT to_dict(): pids is a JSON array of ints, SAME order
# ==========================================================================
def test_b2_conflict_to_dict_pids_array_same_order():
    d = _conflict((123, 456)).to_dict()
    assert d["pids"] == [123, 456] and isinstance(d["pids"], list)
    assert all(isinstance(x, int) for x in d["pids"])
    assert d["scan_error"] is None
    assert d["unknown"] is False
    assert d["conflict"] is True
    assert d["safe"] is False
    assert d["verdict"] == "CONFLICT"
    assert d["exit_code"] == 1


def test_b2_conflict_pids_order_preserved():
    # order is meaningful: input order is echoed verbatim, not sorted
    d = foundry.summarize_single_brain((456, 123, 999)).to_dict()
    assert d["pids"] == [456, 123, 999]


# ==========================================================================
# Behavior 3 -- UNKNOWN to_dict(): scan_error surfaced, verdict/exit degrade
# ==========================================================================
def test_b3_unknown_to_dict_values():
    d = _unknown("no pgrep").to_dict()
    assert d["pids"] == []
    assert d["scan_error"] == "no pgrep"
    assert d["unknown"] is True
    assert d["conflict"] is False
    assert d["safe"] is False
    assert d["verdict"] == "UNKNOWN"
    assert d["exit_code"] == 2


# ==========================================================================
# Behavior 4 -- to_dict() is pure & JSON-safe: dumps ok + round-trips; no
#               disk writes; no mutation of the (frozen) status
# ==========================================================================
def test_b4_json_dumps_and_round_trip():
    for status in (_safe(), _conflict(), _unknown()):
        d = status.to_dict()
        text = json.dumps(d)                       # must NOT raise
        assert json.loads(text) == d, "to_dict() must survive a dumps/loads round-trip"


def test_b4_pretty_indent_round_trips_too():
    for status in (_safe(), _conflict(), _unknown()):
        d = status.to_dict()
        assert json.loads(json.dumps(d, indent=2)) == d


def test_b4_pure_no_disk_write_no_mutation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)
    for status in (_safe(), _conflict(), _unknown()):
        d1 = status.to_dict()
        d2 = status.to_dict()
        # idempotent / stateless: calling twice yields equal dicts
        assert d1 == d2
        # status is unchanged by the call (frozen dataclass)
        assert status.pids == status.pids and status.scan_error == status.scan_error
        assert status.verdict == d1["verdict"] and status.exit_code == d1["exit_code"]
    assert _snapshot_tree(tmp_path) == before, "to_dict() wrote to disk (must be pure)"


# ==========================================================================
# Behavior 5 -- the 5 derived values REUSE the frozen properties and can
#               never disagree with them
# ==========================================================================
def test_b5_derived_values_match_properties():
    cases = [
        foundry.summarize_single_brain(()),
        foundry.summarize_single_brain((1,)),
        foundry.summarize_single_brain((1, 2, 3)),
        foundry.summarize_single_brain((), scan_error="e"),
        foundry.summarize_single_brain((5, 6), scan_error="partial"),
    ]
    for status in cases:
        d = status.to_dict()
        assert d["unknown"] == status.unknown
        assert d["conflict"] == status.conflict
        assert d["safe"] == status.safe
        assert d["verdict"] == status.verdict
        assert d["exit_code"] == status.exit_code
        # stored fields echo the frozen snapshot too
        assert d["pids"] == list(status.pids)
        assert d["scan_error"] == status.scan_error


# ==========================================================================
# Behavior 6 -- single_brain_cli(as_json=True) SAFE: one JSON doc == SAFE
#               to_dict(), returns 0, writes nothing
# ==========================================================================
def test_b6_cli_json_safe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _set_scan(monkeypatch, ret=())
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.single_brain_cli(as_json=True))
    assert rc == 0
    d = json.loads(out)                            # whole stdout is ONE JSON doc
    assert d == foundry.summarize_single_brain(()).to_dict()
    assert d["safe"] is True and d["verdict"] == "SAFE" and d["pids"] == []
    assert _snapshot_tree(tmp_path) == before, "single-brain --json wrote to disk"


# ==========================================================================
# Behavior 7 -- single_brain_cli(as_json=True) CONFLICT: one JSON doc ==
#               CONFLICT to_dict(), returns 1
# ==========================================================================
def test_b7_cli_json_conflict(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _set_scan(monkeypatch, ret=(111,))
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.single_brain_cli(as_json=True))
    assert rc == 1
    d = json.loads(out)
    assert d == foundry.summarize_single_brain((111,)).to_dict()
    assert d["conflict"] is True and d["pids"] == [111] and d["verdict"] == "CONFLICT"
    assert _snapshot_tree(tmp_path) == before


# ==========================================================================
# Behavior 8 -- single_brain_cli(as_json=True) with the seam RAISING degrades
#               to a JSON UNKNOWN (never crashes), returns 2
# ==========================================================================
def test_b8_cli_json_unknown_on_seam_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _set_scan(monkeypatch, exc=RuntimeError("boom"))
    before = _snapshot_tree(tmp_path)
    rc, out, _ = _capture(lambda: foundry.single_brain_cli(as_json=True))
    assert rc == 2
    d = json.loads(out)                            # still ONE valid JSON doc
    assert d["unknown"] is True
    assert d["verdict"] == "UNKNOWN"
    assert d["exit_code"] == 2
    assert d["conflict"] is False and d["safe"] is False and d["pids"] == []
    assert "boom" in (d["scan_error"] or ""), f"scan_error must carry the failure text: {d!r}"
    assert _snapshot_tree(tmp_path) == before


def test_b8_cli_json_matches_summary_for_forced_states(monkeypatch):
    # the JSON payload must equal the pure to_dict() for the SAME forced scan state
    _set_scan(monkeypatch, ret=(7, 8, 9))
    rc, out, _ = _capture(lambda: foundry.single_brain_cli(as_json=True))
    assert rc == foundry.summarize_single_brain((7, 8, 9)).exit_code
    assert json.loads(out) == foundry.summarize_single_brain((7, 8, 9)).to_dict()


# ==========================================================================
# Behavior 9 -- default / as_json=False is byte-for-byte the iter-24 human
#               render() with identical exit codes; --json only ADDS a payload
# ==========================================================================
def test_b9_as_json_default_is_false():
    import inspect
    sig = inspect.signature(foundry.single_brain_cli)
    assert "as_json" in sig.parameters, "single_brain_cli must gain an `as_json` param"
    assert sig.parameters["as_json"].default is False, (
        f"as_json default must be False, got {sig.parameters['as_json'].default!r}")


def test_b9_default_equals_explicit_false_and_equals_render(monkeypatch):
    for ret, code in [((), 0), ((111, 222), 1)]:
        _set_scan(monkeypatch, ret=ret)
        rc_def, out_def, _ = _capture(lambda: foundry.single_brain_cli())
        _set_scan(monkeypatch, ret=ret)
        rc_false, out_false, _ = _capture(lambda: foundry.single_brain_cli(as_json=False))
        # default path is byte-for-byte the explicit as_json=False path
        assert out_def == out_false
        assert rc_def == rc_false == code
        # and byte-for-byte the frozen human render() for that state
        assert out_def.strip() == foundry.summarize_single_brain(ret).render().strip()
        # the human path is NOT JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(out_def)


def test_b9_human_unknown_branch_unchanged(monkeypatch):
    _set_scan(monkeypatch, exc=RuntimeError("scan broke"))
    rc, out, _ = _capture(lambda: foundry.single_brain_cli())          # default human
    assert rc == 2
    assert "UNKNOWN" in out and "scan broke" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_b9_json_and_human_agree_on_exit_code(monkeypatch):
    # --json only ADDS a payload: same exit code as the human path, all 3 verdicts
    for ret, exc, code in [((), None, 0), ((5,), None, 1), (None, RuntimeError("x"), 2)]:
        _set_scan(monkeypatch, ret=ret, exc=exc)
        rc_h, _, _ = _capture(lambda: foundry.single_brain_cli(as_json=False))
        _set_scan(monkeypatch, ret=ret, exc=exc)
        rc_j, _, _ = _capture(lambda: foundry.single_brain_cli(as_json=True))
        assert rc_h == rc_j == code


# ==========================================================================
# Behavior 10 -- CLI wiring: main dispatches to single_brain_cli(pattern=...,
#                as_json=...); process exit == returned code; imports hold
# ==========================================================================
def test_b10_main_dispatches_json_and_forwards_pattern(monkeypatch):
    # --json routes to the JSON branch (stdout parses) AND forwards --pattern
    spy = []
    _set_scan(monkeypatch, ret=(), spy=spy)
    rc, out, _ = _capture(lambda: foundry.main(["single-brain", "--pattern", "foo.py", "--json"]))
    assert rc == 0
    assert spy == ["foo.py"], f"--pattern must reach the seam: {spy}"
    d = json.loads(out)                            # proves as_json=True routed here
    assert d["verdict"] == "SAFE" and d["safe"] is True


def test_b10_main_no_flag_runs_human_path(monkeypatch):
    _set_scan(monkeypatch, ret=(111, 222))
    rc, out, _ = _capture(lambda: foundry.main(["single-brain"]))
    assert rc == 1 and "CONFLICT" in out and "111" in out and "222" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)                            # default is still human, not JSON


def test_b10_process_exit_status_equals_return_code():
    """Real subprocess: the `single-brain --json` process exit status equals the
    0/1/2 code. The seam is patched by bare name INSIDE the child (offline)."""
    root = str(pathlib.Path(foundry.__file__).resolve().parent)
    # SAFE (0) and CONFLICT (1) via a returning seam
    for ret, code, verdict in [("()", 0, "SAFE"), ("(111,)", 1, "CONFLICT")]:
        snippet = (
            "import foundry, sys\n"
            f"foundry.running_dispatchers = lambda pattern='dispatcher.py': {ret}\n"
            "sys.exit(foundry.main(['single-brain', '--json']))\n"
        )
        proc = subprocess.run([sys.executable, "-c", snippet], cwd=root,
                              capture_output=True, text=True)
        assert proc.returncode == code, (verdict, proc.stdout, proc.stderr)
        d = json.loads(proc.stdout)
        assert d["verdict"] == verdict and d["exit_code"] == code
    # UNKNOWN (2) via a raising seam -> degrades to JSON, exit 2, never crashes
    snippet_u = (
        "import foundry, sys\n"
        "def boom(pattern='dispatcher.py'):\n"
        "    raise RuntimeError('kaboom')\n"
        "foundry.running_dispatchers = boom\n"
        "sys.exit(foundry.main(['single-brain', '--json']))\n"
    )
    proc = subprocess.run([sys.executable, "-c", snippet_u], cwd=root,
                          capture_output=True, text=True)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    d = json.loads(proc.stdout)
    assert d["verdict"] == "UNKNOWN" and "kaboom" in (d["scan_error"] or "")


def test_b10_pattern_and_json_subprocess(tmp_path):
    """`single-brain --pattern X --json` parses & dispatches (child patches seam
    with a spy written to a file).

    The spy artifact goes under the pytest-provided temp dir, NOT the repo root.
    The child still runs with ``cwd=root`` because that is what makes `import
    foundry` resolve, but it no longer CREATES a file there: an untracked file
    that appears and then disappears in the shared repo root is a legitimate,
    correctly-enumerated member of the whole-population leak brake, so under
    ``-n auto`` another worker could enumerate it and then fail to read it. The
    output path travels in the ENVIRONMENT rather than baked into the snippet, so
    no absolute machine path becomes a literal in this file.
    """
    root = str(pathlib.Path(foundry.__file__).resolve().parent)
    spy_file = tmp_path / "spy.txt"
    snippet = (
        "import foundry, sys, json, os, pathlib\n"
        "seen = []\n"
        "def spy(pattern='dispatcher.py'):\n"
        "    seen.append(pattern); return ()\n"
        "foundry.running_dispatchers = spy\n"
        "rc = foundry.main(['single-brain', '--pattern', 'mine.py', '--json'])\n"
        "pathlib.Path(os.environ['ITER25_SPY_OUT']).write_text(json.dumps(seen))\n"
        "sys.exit(rc)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", snippet], cwd=root, capture_output=True,
        text=True, env={**os.environ, "ITER25_SPY_OUT": str(spy_file)})
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    d = json.loads(proc.stdout)
    assert d["verdict"] == "SAFE"
    assert json.loads(spy_file.read_text()) == ["mine.py"]


def test_b10_help_advertises_json_flag():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "single-brain", "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "--json" in combined, f"single-brain --help missing --json:\n{combined}"
    assert "--pattern" in combined, f"--pattern regressed from single-brain --help:\n{combined}"


def test_b10_both_modules_still_import():
    root = str(pathlib.Path(foundry.__file__).resolve().parent)
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


# ==========================================================================
# Behavior 11 -- resume-safety / off the control path / invariants preserved
# ==========================================================================
def test_b11_control_flow_fns_do_not_reference_json_surface():
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
        names, consts = _fn_names_consts(getattr(foundry, fn))
        for sym in ("to_dict", "as_json", "single_brain_cli",
                    "summarize_single_brain", "running_dispatchers", "SingleBrainStatus"):
            assert sym not in names, (
                f"{fn} references {sym!r} -- the single-brain/json surface must stay off "
                f"the control path (resume-safety)")
            assert sym not in consts, f"{fn} embeds the const {sym!r}"
        assert "single-brain" not in consts, f"{fn} embeds the 'single-brain' subcommand string"


def test_b11_pipeline_and_dispatcher_never_call_single_brain_cli():
    # neither the four control-flow fns nor dispatcher.py may call the CLI
    for fn in CONTROL_FLOW_FNS:
        names, consts = _fn_names_consts(getattr(foundry, fn))
        assert "single_brain_cli" not in names and "single_brain_cli" not in consts
    assert not hasattr(dispatcher, "single_brain_cli"), "dispatcher must not expose single_brain_cli"
    d_names, d_consts = _module_names_consts(dispatcher)
    for sym in ("single_brain_cli", "to_dict", "as_json", "SingleBrainStatus",
                "summarize_single_brain", "running_dispatchers"):
        assert sym not in d_names, f"dispatcher references {sym!r}"
    assert "single-brain" not in d_consts, "dispatcher embeds the 'single-brain' subcommand string"


def test_b11_no_new_sentinel_vocab():
    # the existing sentinel / status vocabulary is intact (no vocab churn from this add)
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), f"sentinel prefix {sentinel!r} vanished from foundry"
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"


def test_b11_iter24_core_surface_intact():
    # the frozen iter-24 surface this iter builds on is unchanged in shape
    assert callable(foundry.summarize_single_brain)
    assert callable(foundry.single_brain_cli)
    assert callable(foundry.running_dispatchers)
    assert isinstance(foundry.SingleBrainStatus, type)
    # to_dict is a NEW method on the frozen dataclass
    assert callable(getattr(foundry.SingleBrainStatus, "to_dict", None)), (
        "SingleBrainStatus.to_dict must exist")
