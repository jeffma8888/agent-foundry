"""Black-box behaviour tests for iter 97 -- `foundry gate-scope --json`: a
machine-readable JSON payload for the read-only, fully-DORMANT `gate-scope`
diff-scope classifier CLI, added ON TOP of the pre-existing core (GateScope /
classify_gate_scope / gate_scope_cli, shipped iter 15). The change is a clean
ADD-A-METHOD + ADD-A-FLAG: a new `GateScope.to_dict()` + an `as_json: bool =
False` kw on the existing `gate_scope_cli` + a `--json` store_true subparser arg
+ a one-line dispatch edit. It serves the foundry's own dashboards / CI checks /
the future item-4-bite-2 gate wiring with a stable, parseable scope verdict.

This is a git-diff-SEAM CLI whose exit is 0/1/2 (light / full / git-diff-seam
failure). Exit 2 arises ONLY when `files is None` AND the monkeypatchable
`run_cmd` git-diff seam returns `ok=False`; the seam-failure branch prints the
plain-text `gate-scope: git diff failed: <detail>` in BOTH modes (json.loads
raises), never a JSON object, never an exception. When `files` is given
(INCLUDING an empty list) the seam is NEVER invoked, so exit 2 cannot occur:
`files=[]` classifies to an empty diff (all buckets empty), `light` is False,
`scope` is "full", exit 1. This exit shape is DISTINCT from prd #7 (2 =
missing-OR-invalid, two mode-divergent paths), lint-spec #6 (2 = file-not-found,
always plain-text), and product-gate #34 (0/1/2/3).

The four str-list buckets `changed`/`source`/`test`/`doc` are STORED fields
declared BEFORE the two derived props `light`/`scope`, so they land at the FRONT
of the 6-key to_dict (all four buckets first, props last) -- a NEW layout vs
prd's `pending` / lint-spec's `missing_sections` (a SINGLE str-list in the
MIDDLE) and vs gate-verdict/gate-precheck (a str-list as a derived prop -> last).
Each bucket must be coerced via `list(...)` so the JSON round-trip holds.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-16) and the product's own OBSERVABLE behaviour only (running it) plus
the pre-existing core test file under tests/ (test_iter15_behavior.py). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.classify_gate_scope(...)`
+ `GateScope.to_dict`, the CLI via `foundry.gate_scope_cli(cfg, ...)` and
`foundry.main(["gate-scope", ...])` against a TMP-`repo` config (the real repo is
NEVER touched). The expected human render is reconstructed INDEPENDENTLY from the
spec's documented Behavior-6 format + the public `classify_gate_scope`, then
compared byte-for-byte. The dormancy proof uses only public runtime
introspection -- compiled function name tables (`co_names` recursed via
`_co_names_deep`) + a `dispatcher.py` source symbol-count -- and the mechanical
ASCII acceptance check uses `inspect.getsource` SCOPED to the two new/changed
symbols only (the established suite convention; never a whole-file scan / never
`git diff`). Fully offline and deterministic: real temp files only; the git-diff
path is forced through the documented `foundry.run_cmd` seam, so there is NO real
subprocess / git / network (except the fresh-import regression probe). There is
deliberately NO `git diff --quiet HEAD` control-path guard in this file -- the
iter-86 fix removed that over-broad freeze anti-pattern.
"""
import contextlib
import dataclasses
import importlib.util
import inspect
import io
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (module located via the BARE __file__ object,
# never a quoted source-literal main-module name -- the iter-54 meta-scanner)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The 6 keys to_dict() must expose, IN THIS ORDER: the 4 stored str-list fields
# in declaration order (changed, source, test, doc) FIRST, THEN the 2 derived
# properties (light, scope) LAST. NO exit_code key (the CLI derives the exit).
KEY_ORDER = ["changed", "source", "test", "doc", "light", "scope"]
EXPECTED_KEYS = set(KEY_ORDER)

# The three PRE-EXISTING gate-scope symbols (the core shipped iter 15, so a
# whole-file grep would FALSE-POSITIVE). Dormancy is proven ONLY against these
# specific symbols + the command string -- NEVER the generic `to_dict` name.
SCOPE_SYMBOLS = ("gate_scope_cli", "classify_gate_scope", "GateScope")

# Canonical path lists (grounded in the observable behaviour of the pure
# classify_gate_scope): a test-only diff is LIGHT; a mix with any source or doc
# is FULL; the empty diff is FULL (light False).
LIGHT = ["tests/test_a.py", "b/tests/c.py"]           # test-only -> light, exit 0
FULL = ["src/x.py", "README.md", "tests/test_a.py"]   # source+doc+test -> full, exit 1
EMPTY = []                                            # no changes -> full, light False


# --------------------------------------------------------------------------
# helpers -- config, offline git-diff seam, stdout capture, introspection
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (mirrors the suite convention).
    `repo` is a TMP dir so the real foundry repo is NEVER touched."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _load_cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


class _Res:
    """Stand-in for the run_cmd result type: only `.ok`/`.out` are contracted
    (mirrors tests/test_iter15_behavior.py)."""
    def __init__(self, ok, out=""):
        self.ok = bool(ok)
        self.out = out


def _fail_seam(out="fatal: bad revision\n"):
    """A run_cmd replacement whose git-diff invocation reports failure."""
    def _run_cmd(args, cwd=None, timeout=None):
        return _Res(False, out)
    return _run_cmd


def _boom_seam(args, cwd=None, timeout=None):
    """A run_cmd replacement that RAISES if invoked -- used to prove that a
    files-given classification NEVER touches the git-diff seam."""
    raise AssertionError("run_cmd seam was invoked though files were given")


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def _run_cli(argv):
    """Drive foundry.main capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing nested code objects. Pure
    runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter97_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _expected_human(cfg, files):
    """Reconstruct the EXPECTED default human render for a files-given diff from
    the spec's Behavior-6 documented format + the PUBLIC classify_gate_scope --
    independent of the CLI implementation."""
    st = foundry.classify_gate_scope(files)
    lines = [
        "gate-scope: repo %s" % cfg.repo,
        "  changed: %d  test: %d  doc: %d  source: %d" % (
            len(st.changed), len(st.test), len(st.doc), len(st.source)),
        "scope: %s" % st.scope,
    ]
    return "\n".join(lines) + "\n"


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous (the canonical
# cases really do behave as the spec's names claim)
# ==========================================================================
def test_precondition_canonical_cases_behave_as_named():
    light = foundry.classify_gate_scope(LIGHT)
    assert light.light is True and light.scope == "light"
    assert len(light.test) >= 1 and light.source == () and light.doc == ()
    full = foundry.classify_gate_scope(FULL)
    assert full.light is False and full.scope == "full"
    assert len(full.source) >= 1
    empty = foundry.classify_gate_scope(EMPTY)
    assert empty.light is False and empty.scope == "full"
    assert (empty.changed, empty.source, empty.test, empty.doc) == ((), (), (), ())
    for f in ("changed", "source", "test", "doc"):
        assert type(getattr(full, f)) is tuple, (
            "raw %s must be a tuple to arm the non-vacuity guard" % f)


# ==========================================================================
# Behavior 1 -- to_dict() has EXACTLY 6 keys in the pinned order; no exit_code
# ==========================================================================
def test_b01_to_dict_exact_6_keys_in_order():
    for files in (LIGHT, FULL, EMPTY):
        d = foundry.classify_gate_scope(files).to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == KEY_ORDER, (
            "to_dict key order %r != %r" % (list(d.keys()), KEY_ORDER))
        assert set(d.keys()) == EXPECTED_KEYS
        assert len(d) == 6
        assert "exit_code" not in d


def test_b01_key_order_matches_field_then_property_declaration():
    """Independently derive the expected order from the public dataclass shape:
    stored fields in declaration order THEN properties in declaration order."""
    fields = [f.name for f in dataclasses.fields(foundry.GateScope)]
    props = [n for n, v in vars(foundry.GateScope).items() if isinstance(v, property)]
    assert fields + props == KEY_ORDER, (fields, props)


def test_b01_no_exit_code_attribute():
    assert not hasattr(foundry.GateScope, "exit_code")


# ==========================================================================
# Behavior 2 -- each bucket is a plain LIST == list(self.<field>) of str; the
#               two props are reused (light bool, scope str)
# ==========================================================================
def test_b02_bucket_values_are_lists_of_str():
    for files in (LIGHT, FULL, EMPTY):
        st = foundry.classify_gate_scope(files)
        d = st.to_dict()
        for field in ("changed", "source", "test", "doc"):
            assert type(d[field]) is list, "%s must be a list, not a tuple" % field
            assert d[field] == list(getattr(st, field))
            assert all(type(x) is str for x in d[field])


def test_b02_light_and_scope_reuse_props():
    for files in (LIGHT, FULL, EMPTY):
        st = foundry.classify_gate_scope(files)
        d = st.to_dict()
        assert d["light"] == st.light and type(d["light"]) is bool
        assert d["scope"] == st.scope and type(d["scope"]) is str


def test_b02_empty_buckets_are_empty_lists():
    d = foundry.classify_gate_scope(EMPTY).to_dict()
    for field in ("changed", "source", "test", "doc"):
        assert d[field] == []


# ==========================================================================
# Behavior 3 -- THE DISCRIMINATING ROUND-TRIP over light / full / empty
# ==========================================================================
def test_b03_json_round_trip_all_cases():
    for name, files in (("light", LIGHT), ("full", FULL), ("empty", EMPTY)):
        d = foundry.classify_gate_scope(files).to_dict()
        s = json.dumps(d)  # must not raise
        assert json.loads(s) == d, (
            "to_dict did not round-trip through JSON for %r (tuple leaked?)" % name)


# ==========================================================================
# Behavior 4 -- non-vacuity: a bare-tuple bucket would FAIL the round-trip
# ==========================================================================
def test_b04_round_trip_non_vacuous_bare_tuple_fails():
    """Prove the round-trip is a real discriminator: a variant whose `changed`
    value is the RAW frozen tuple `self.changed` breaks `==` (json reads a tuple
    back as a list). Armed on a FULL scope where the bucket is non-empty."""
    st = foundry.classify_gate_scope(FULL)
    d = st.to_dict()
    assert len(d["changed"]) > 0, "changed empty -- guard would be vacuous"
    assert json.loads(json.dumps(d)) == d
    bad = dict(d)
    bad["changed"] = st.changed  # the raw frozen tuple
    assert isinstance(bad["changed"], tuple)
    assert json.loads(json.dumps(bad)) != bad, (
        "round-trip check is vacuous -- a tuple-valued bucket did not break equality")


# ==========================================================================
# Behavior 5 -- to_dict() is a FRESH dict each call; mutation isolation
# ==========================================================================
def test_b05_to_dict_read_only():
    for files in (LIGHT, FULL):
        st = foundry.classify_gate_scope(files)
        before = dataclasses.asdict(st)
        d1 = st.to_dict()
        d1["changed"].append("BOGUS")
        d1["scope"] = "TAMPERED"
        d1["NEWKEY"] = 1
        d2 = st.to_dict()
        assert dataclasses.asdict(st) == before, "to_dict mutated the frozen instance"
        assert d2 == foundry.classify_gate_scope(files).to_dict(), "second to_dict affected by mutation"
        assert "NEWKEY" not in d2
        assert d1 is not d2


def test_b05_two_calls_equal_but_distinct():
    st = foundry.classify_gate_scope(FULL)
    a, b = st.to_dict(), st.to_dict()
    assert a == b
    assert a is not b
    assert a["changed"] is not b["changed"], "bucket list is shared across calls"


# ==========================================================================
# Behavior 6 -- DEFAULT (as_json=False) human render is byte-identical to the
#               spec's documented format; exit 0 for light, 1 for full
# ==========================================================================
def test_b06_default_human_render_byte_identical(tmp_path):
    cfg = _load_cfg(tmp_path)
    for name, files, code in (("light", LIGHT, 0), ("full", FULL, 1)):
        rc, out = _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=False))
        assert rc == code, "%s exit %r != %r\n%s" % (name, rc, code, out)
        assert out == _expected_human(cfg, files), (
            "human render mismatch for %r:\n got=%r\n exp=%r" % (name, out, _expected_human(cfg, files)))


def test_b06_default_equals_explicit_false(tmp_path):
    cfg = _load_cfg(tmp_path)
    for files in (LIGHT, FULL):
        rc_def, out_def = _cap(lambda: foundry.gate_scope_cli(cfg, files=files))
        rc_false, out_false = _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=False))
        assert out_def == out_false, "default != explicit as_json=False for %r" % files
        assert rc_def == rc_false


# ==========================================================================
# Behavior 7 -- the default (as_json=False) human render is NOT valid JSON
# ==========================================================================
def test_b07_human_render_not_valid_json(tmp_path):
    cfg = _load_cfg(tmp_path)
    for files in (LIGHT, FULL):
        _, human = _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=False))
        with pytest.raises(json.JSONDecodeError):
            json.loads(human)


# ==========================================================================
# Behavior 8 -- as_json=True prints EXACTLY json.dumps(to_dict(),indent=2)+nl
# ==========================================================================
def test_b08_json_output_is_exact(tmp_path):
    cfg = _load_cfg(tmp_path)
    for name, files in (("light", LIGHT), ("full", FULL), ("empty", EMPTY)):
        _, out = _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=True))
        expected = json.dumps(foundry.classify_gate_scope(files).to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(),indent=2)+nl for %r" % name
        assert json.loads(out) == foundry.classify_gate_scope(files).to_dict()


# ==========================================================================
# Behavior 9 -- as_json=True: NO human line leaks (JSON-structural), armed by
#               the human complement
# ==========================================================================
def test_b09_json_lines_start_with_json_token(tmp_path):
    cfg = _load_cfg(tmp_path)
    for name, files in (("light", LIGHT), ("full", FULL), ("empty", EMPTY)):
        _, out = _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=True))
        for ln in out.splitlines():
            s = ln.strip()
            assert s == "" or s[0] in "{}[]\"", (
                "JSON line does not start with a JSON token (%r case): %r" % (name, ln))


def test_b09_leak_check_armed_by_human_complement(tmp_path):
    """The SAME structural check must FAIL on the human render -- else its pass
    on JSON is meaningless. Every human line leads with a letter."""
    cfg = _load_cfg(tmp_path)
    for name, files in (("light", LIGHT), ("full", FULL)):
        _, human = _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=False))
        nonblank = [ln for ln in human.splitlines() if ln.strip()]
        assert nonblank, "human render empty for %r" % name
        offenders = [ln for ln in nonblank if ln.strip()[0] not in "{}[]\""]
        assert offenders, (
            "leak check inert for %r -- every human line looked like JSON: %r" % (name, human))


# ==========================================================================
# Behavior 10 -- EXIT-CODE parity: identical in both modes; 0 light / 1 full
# ==========================================================================
def test_b10_exit_code_parity(tmp_path):
    cfg = _load_cfg(tmp_path)
    for name, files, code in (("light", LIGHT, 0), ("full", FULL, 1)):
        rc_h, _ = _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=False))
        rc_j, _ = _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=True))
        assert rc_h == rc_j == code, (
            "exit diverged for %r: human=%r json=%r expected=%r" % (name, rc_h, rc_j, code))


# ==========================================================================
# Behavior 11 -- git-diff-SEAM failure (files=None, run_cmd ok=False): plain
#                human line + rc 2, byte-identical in BOTH modes, no raise
# ==========================================================================
def test_b11_seam_failure_exit2_both_modes(tmp_path, monkeypatch):
    cfg = _load_cfg(tmp_path)
    # leading spaces + trailing newline prove the reported detail is .strip()-ed
    monkeypatch.setattr(foundry, "run_cmd", _fail_seam("  fatal: bad revision\n"))
    expected = "gate-scope: git diff failed: %s\n" % "  fatal: bad revision\n".strip()
    for as_json in (False, True):
        rc, out = _cap(lambda: foundry.gate_scope_cli(cfg, files=None, as_json=as_json))
        assert rc == 2, "seam failure returned %r (as_json=%s)\n%s" % (rc, as_json, out)
        assert out == expected, "seam-failure line mismatch (as_json=%s): %r" % (as_json, out)
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)  # NOT JSON in either mode


def test_b11_seam_failure_never_raises(tmp_path, monkeypatch):
    cfg = _load_cfg(tmp_path)
    monkeypatch.setattr(foundry, "run_cmd", _fail_seam())
    for as_json in (False, True):
        try:
            _cap(lambda: foundry.gate_scope_cli(cfg, files=None, as_json=as_json))
        except Exception as e:  # pragma: no cover
            pytest.fail("gate_scope_cli raised on seam failure (as_json=%s): %r" % (as_json, e))


# ==========================================================================
# Behavior 12 -- files-given (INCLUDING []) NEVER invokes the seam; files=[]
#                classifies empty -> scope full -> exit 1 in both modes
# ==========================================================================
def test_b12_files_given_never_touches_seam(tmp_path, monkeypatch):
    cfg = _load_cfg(tmp_path)
    monkeypatch.setattr(foundry, "run_cmd", _boom_seam)  # raises if invoked
    for files in (LIGHT, FULL, []):
        for as_json in (False, True):
            # must complete without the boom seam firing
            _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=as_json))


def test_b12_empty_files_classifies_full_exit1(tmp_path, monkeypatch):
    cfg = _load_cfg(tmp_path)
    monkeypatch.setattr(foundry, "run_cmd", _boom_seam)
    for as_json in (False, True):
        rc, _ = _cap(lambda: foundry.gate_scope_cli(cfg, files=[], as_json=as_json))
        assert rc == 1, "files=[] must exit 1 (as_json=%s), got %r" % (as_json, rc)
    _, jout = _cap(lambda: foundry.gate_scope_cli(cfg, files=[], as_json=True))
    d = json.loads(jout)
    assert d["light"] is False and d["scope"] == "full"
    for field in ("changed", "source", "test", "doc"):
        assert d[field] == [], "bucket %s must be empty for files=[]" % field
    _, hout = _cap(lambda: foundry.gate_scope_cli(cfg, files=[], as_json=False))
    assert "scope: full" in hout


# ==========================================================================
# Behavior 13 -- writes NOTHING in either mode, from an empty cwd, over a light
#                diff, a full diff, and a seam-failure
# ==========================================================================
def test_b13_writes_nothing(tmp_path, monkeypatch):
    cfg = _load_cfg(tmp_path)
    cwd = tmp_path / "emptycwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    # files-given light + full: the boom seam guarantees no git subprocess
    monkeypatch.setattr(foundry, "run_cmd", _boom_seam)
    for files in (LIGHT, FULL):
        for as_json in (False, True):
            _cap(lambda: foundry.gate_scope_cli(cfg, files=files, as_json=as_json))
    assert sorted(p.name for p in cwd.iterdir()) == [], "CLI wrote to cwd (files path)"
    # seam-failure path (files=None): also writes nothing
    monkeypatch.setattr(foundry, "run_cmd", _fail_seam())
    for as_json in (False, True):
        _cap(lambda: foundry.gate_scope_cli(cfg, files=None, as_json=as_json))
    assert sorted(p.name for p in cwd.iterdir()) == [], "CLI wrote to cwd (seam-failure path)"


# ==========================================================================
# Behavior 14 -- argparse routing: --json is store_true; dispatch spy proves
#                as_json True/False + files/base pass-through; --config REQUIRED
# ==========================================================================
def test_b14_json_store_true_and_passthrough_via_dispatch_spy(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    captured = {}

    def fake(cfg, files=None, base=None, as_json=False):
        captured.clear()
        captured.update(files=files, base=base, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "gate_scope_cli", fake)
    foundry.main(["gate-scope", "--config", str(cfg_path), "--files", "tests/test_a.py", "--json"])
    assert captured == {"files": ["tests/test_a.py"], "base": None, "as_json": True}
    foundry.main(["gate-scope", "--config", str(cfg_path), "--files", "tests/test_a.py"])
    assert captured == {"files": ["tests/test_a.py"], "base": None, "as_json": False}
    foundry.main(["gate-scope", "--config", str(cfg_path), "--base", "deadbeef"])
    assert captured == {"files": None, "base": "deadbeef", "as_json": False}


def test_b14_config_required_raises_systemexit():
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["gate-scope"])
    assert ei.value.code != 0


def test_b14_json_takes_no_value(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["gate-scope", "--config", str(cfg_path), "--json", "bogus"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 15 -- end-to-end via foundry.main
# ==========================================================================
def test_b15_e2e_light_json(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    rc, out = _cap(lambda: foundry.main(
        ["gate-scope", "--config", str(cfg_path), "--files", "tests/test_a.py", "--json"]))
    d = json.loads(out)
    assert rc == 0
    assert d["scope"] == "light"
    assert d["light"] is True
    assert isinstance(d["test"], list) and len(d["test"]) >= 1


def test_b15_e2e_full_json(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    rc, out = _cap(lambda: foundry.main(
        ["gate-scope", "--config", str(cfg_path), "--files", "src/x.py", "tests/test_a.py", "--json"]))
    d = json.loads(out)
    assert rc == 1
    assert d["scope"] == "full"
    assert d["light"] is False


def test_b15_e2e_without_json_same_exits(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    rc_l, out_l = _cap(lambda: foundry.main(
        ["gate-scope", "--config", str(cfg_path), "--files", "tests/test_a.py"]))
    assert rc_l == 0
    assert "scope: light" in out_l
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_l)
    rc_f, out_f = _cap(lambda: foundry.main(
        ["gate-scope", "--config", str(cfg_path), "--files", "src/x.py", "tests/test_a.py"]))
    assert rc_f == 1
    assert "scope: full" in out_f


# ==========================================================================
# Behavior 16 -- DORMANCY: the running loop is unaffected
# ==========================================================================
def test_b16_orchestrators_do_not_reference_scope_symbols():
    new = set(SCOPE_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references gate-scope symbol(s): %r" % (fn.__name__, refs)


def test_b16_dispatcher_has_zero_scope_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for s in SCOPE_SYMBOLS:
        assert dtext.count(s) == 0, "dispatcher.py references %s" % s
    assert dtext.count("gate-scope") == 0, "dispatcher.py names the 'gate-scope' command string"


def test_b16_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b16_to_dict_does_not_change_field_equality():
    a = foundry.classify_gate_scope(FULL)
    b = foundry.classify_gate_scope(FULL)
    assert a == b, "adding to_dict must not change GateScope value-equality"
    _ = a.to_dict()
    assert a == b


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.classify_gate_scope)
    assert callable(foundry.gate_scope_cli)
    assert dataclasses.is_dataclass(foundry.GateScope)
    assert callable(foundry.GateScope.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_gate_scope(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "gate-scope" in out
    for sub in ("run", "once", "learnings", "agents", "lint-spec", "prd"):
        assert sub in out, "subcommand %r missing from --help (regression)" % sub


def test_ac_new_symbols_ascii():
    """Scoped to the two new/changed symbols via inspect.getsource -- NOT a
    whole-file scan (foundry.py carries pre-existing non-ASCII elsewhere -- the
    iter-67 trap)."""
    srcs = [
        inspect.getsource(foundry.GateScope.to_dict),
        inspect.getsource(foundry.gate_scope_cli),
    ]
    for src in srcs:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
