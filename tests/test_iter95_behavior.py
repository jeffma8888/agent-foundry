"""Black-box behaviour tests for iter 95 -- `foundry prd --json`: a
machine-readable JSON payload for the read-only `prd` story-progress CLI, added
ON TOP of the pre-existing core (PrdStatus / prd_status / prd_status_cli, shipped
iter 11-12). The change is a clean ADD-A-METHOD + ADD-A-FLAG: a new
`PrdStatus.to_dict()` + an `as_json: bool = False` kw on the existing
`prd_status_cli` + a `--json` store_true subparser arg + a one-line dispatch
edit. It serves roadmap item 1's original "jq-able N/M stories pass" goal.

This is a `--config`/file-reading CLI whose exit is 0/1/2 (complete / incomplete
/ missing-OR-invalid), the SAME 0/1/2 shape as status #9, NOT the 0/1 flag CLIs
(role-model #33 / scout-plan #38) nor product-gate #34's 0/1/2/3. Exit 2 covers
TWO paths that DIVERGE BY MODE: a MISSING file prints the plain-text
`prd: file not found: <path>` in BOTH modes (json.loads raises), never a JSON
object; an INVALID-but-PRESENT file DOES have a status object, so `--json` emits
the useful {"valid": false, ...} JSON. The str-list `pending` is a STORED field
declared before the derived props, so it lands in the MIDDLE of the 6-key
to_dict (the role-model `argv` placement), and must be coerced via `list(...)`
so the JSON round-trip holds.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-14) and the product's own OBSERVABLE behaviour only (running it) plus
the pre-existing core test files under tests/. The implementation source
(foundry.py internals), the engineer's and reviewer's notes, and `git diff` were
NOT read to design these behaviour tests. Every check drives the PUBLIC
interface: the pure core via `foundry.prd_status(...)` + `PrdStatus.to_dict`, the
CLI via `foundry.prd_status_cli(cfg, ...)` and `foundry.main(["prd", ...])` with
a tmp product config whose `prd` points at a tmp file (the real repo's prd path
is NEVER used). The expected human render is reconstructed INDEPENDENTLY from the
spec's documented format + the public `prd_status`, then compared byte-for-byte.
The dormancy proof uses only public runtime introspection -- compiled function
name tables (`co_names` recursed via `_co_names_deep`) + a `dispatcher.py` source
symbol-count -- and the mechanical ASCII acceptance check uses `inspect.getsource`
SCOPED to the two new/changed symbols only (the established suite convention;
never a whole-file scan / never `git diff`). Fully offline and deterministic: no
subprocess/git/network except the fresh-import regression probe. There is
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

# The 6 keys to_dict() must expose, IN THIS ORDER. The str-list `pending` is a
# STORED field declared before the derived `complete`/`summary` props, so it
# lands in the MIDDLE (the role-model `argv` placement), and the two props last.
# NO exit_code key (the CLI derives the exit code).
KEY_ORDER = ["valid", "total", "passed", "pending", "complete", "summary"]
EXPECTED_KEYS = set(KEY_ORDER)

# The two PRE-EXISTING prd symbols (the core shipped iter 11-12, so a whole-file
# grep would FALSE-POSITIVE). Dormancy is proven ONLY against these specific
# symbols + the command string -- NEVER the generic `to_dict` name.
PRD_SYMBOLS = ("prd_status_cli", "PrdStatus")

# The exact invalid-JSON human line, per the spec's Behavior 6.
INVALID_MSG = ('prd: invalid JSON -- expected an array of story objects or a '
               '{"stories": [...]} object')

# Canonical drive cases (grounded in the observable behaviour of prd_status).
COMPLETE = json.dumps([{"id": "S1", "passes": True}, {"id": "S2", "passes": 1}])
INCOMPLETE = json.dumps([{"id": "S1", "passes": True},
                         {"id": "S2", "passes": False},
                         {"title": "T3", "passes": False}])
EMPTY = json.dumps([])
INVALID = "{not valid json at all"
# name -> prd text (None means the prd file is ABSENT)
EXISTING_CASES = {"complete": COMPLETE, "incomplete": INCOMPLETE,
                  "empty": EMPTY, "invalid": INVALID}
ALL_CASES = dict(EXISTING_CASES, missing=None)


# --------------------------------------------------------------------------
# helpers -- synthetic prd JSON + tmp configs (never the real repo)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    data = {
        "name": "demoprod",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg_with_prd(tmp_path, prd_text=None):
    """Config whose `prd` points at <repo>/prd.json; seed the file iff prd_text
    is not None. Returns (loaded ProductConfig, cfg_path)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    prd_path = repo / "prd.json"
    cfg_path = _write_cfg(tmp_path, prd=str(prd_path))
    if prd_text is not None:
        prd_path.write_text(prd_text)
    return foundry.load_config(str(cfg_path)), cfg_path


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


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
    spec = importlib.util.spec_from_file_location("leak_guard_iter95_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _expected_human(cfg, prd_text):
    """Reconstruct the EXPECTED default human render from the spec's Behavior 6
    format + the PUBLIC prd_status -- independent of the CLI implementation."""
    prd = cfg.prd
    if not pathlib.Path(prd).is_file():
        return "prd: file not found: %s\n" % prd
    st = foundry.prd_status(prd_text)
    if not st.valid:
        return "prd: %s\n%s\n" % (prd, INVALID_MSG)
    lines = ["prd: %s" % prd, "  %s" % st.summary, "  complete: %s" % st.complete]
    if st.pending:
        lines.append("  pending: %s" % ", ".join(st.pending))
    return "\n".join(lines) + "\n"


def _expected_rc(prd_text, exists):
    if not exists:
        return 2
    st = foundry.prd_status(prd_text)
    if not st.valid:
        return 2
    return 0 if st.complete else 1


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous (the canonical
# cases really do behave as the spec's names claim)
# ==========================================================================
def test_precondition_canonical_cases_behave_as_named():
    c = foundry.prd_status(COMPLETE)
    assert c.valid is True and c.total == 2 and c.passed == 2 and c.complete is True
    i = foundry.prd_status(INCOMPLETE)
    assert i.valid is True and i.complete is False and len(i.pending) >= 1
    assert type(i.pending) is tuple, "raw pending must be a tuple to arm the non-vacuity guard"
    e = foundry.prd_status(EMPTY)
    assert e.valid is True and e.total == 0 and e.complete is False and e.pending == ()
    v = foundry.prd_status(INVALID)
    assert v.valid is False and v.complete is False


# ==========================================================================
# Behavior 1 -- to_dict() has EXACTLY 6 keys in the pinned order; no exit_code
# ==========================================================================
def test_b01_to_dict_exact_6_keys_in_order():
    for txt in EXISTING_CASES.values():
        d = foundry.prd_status(txt).to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == KEY_ORDER, (
            "to_dict key order %r != %r" % (list(d.keys()), KEY_ORDER))
        assert set(d.keys()) == EXPECTED_KEYS
        assert len(d) == 6
        assert "exit_code" not in d


def test_b01_no_exit_code_attribute():
    assert not hasattr(foundry.PrdStatus, "exit_code")


# ==========================================================================
# Behavior 2 -- the four scalar keys equal their sources verbatim
# ==========================================================================
def test_b02_scalar_keys_equal_sources():
    for txt in EXISTING_CASES.values():
        st = foundry.prd_status(txt)
        d = st.to_dict()
        assert d["valid"] == st.valid and type(d["valid"]) is bool
        assert d["total"] == st.total and type(d["total"]) is int
        assert d["passed"] == st.passed and type(d["passed"]) is int
        assert d["complete"] == st.complete and type(d["complete"]) is bool
        assert d["summary"] == st.summary and type(d["summary"]) is str


def test_b02_summary_string_shape():
    d = foundry.prd_status(INCOMPLETE).to_dict()
    assert d["summary"] == "1/3 stories pass"
    assert d["passed"] == 1 and d["total"] == 3


# ==========================================================================
# Behavior 3 -- pending is a plain LIST (not a tuple) == list(self.pending)
# ==========================================================================
def test_b03_pending_is_list_of_str():
    for txt in EXISTING_CASES.values():
        st = foundry.prd_status(txt)
        d = st.to_dict()
        assert type(d["pending"]) is list, "pending must be a list, not a tuple"
        assert d["pending"] == list(st.pending)
        assert all(type(x) is str for x in d["pending"])


def test_b03_incomplete_pending_contents():
    d = foundry.prd_status(INCOMPLETE).to_dict()
    assert d["pending"] == ["S2", "T3"]


# ==========================================================================
# Behavior 4 -- THE DISCRIMINATING ROUND-TRIP over 4 cases + a non-vacuity guard
#               proving a bare-tuple pending would FAIL it
# ==========================================================================
def test_b04_json_round_trip_all_cases():
    for name, txt in EXISTING_CASES.items():
        d = foundry.prd_status(txt).to_dict()
        s = json.dumps(d)  # must not raise
        assert json.loads(s) == d, (
            "to_dict did not round-trip through JSON for %r (tuple leaked?)" % name)


def test_b04_round_trip_non_vacuous_bare_tuple_fails():
    """Prove the round-trip is a real discriminator: a variant whose `pending`
    value is the RAW tuple `self.pending` breaks `==` (json reads a tuple back
    as a list). Armed on INCOMPLETE where pending is non-empty."""
    st = foundry.prd_status(INCOMPLETE)
    d = st.to_dict()
    assert len(d["pending"]) > 0, "incomplete pending unexpectedly empty -- guard would be vacuous"
    assert json.loads(json.dumps(d)) == d
    bad = dict(d)
    bad["pending"] = st.pending  # the raw frozen tuple
    assert isinstance(bad["pending"], tuple)
    assert json.loads(json.dumps(bad)) != bad, (
        "round-trip check is vacuous -- a tuple-valued pending did not break equality")


# ==========================================================================
# Behavior 5 -- to_dict() is a FRESH dict each call; mutation isolation
# ==========================================================================
def test_b05_to_dict_read_only():
    for txt in (INCOMPLETE, COMPLETE):
        st = foundry.prd_status(txt)
        before = dataclasses.asdict(st)
        d1 = st.to_dict()
        d1["pending"].append("BOGUS")
        d1["summary"] = "TAMPERED"
        d1["NEWKEY"] = 1
        d2 = st.to_dict()
        assert dataclasses.asdict(st) == before, "to_dict mutated the frozen instance"
        assert d2 == foundry.prd_status(txt).to_dict(), "second to_dict affected by mutation"
        assert "NEWKEY" not in d2
        assert d1 is not d2


def test_b05_two_calls_equal_but_distinct():
    st = foundry.prd_status(INCOMPLETE)
    a, b = st.to_dict(), st.to_dict()
    assert a == b
    assert a is not b
    assert a["pending"] is not b["pending"], "pending list is shared across calls"


# ==========================================================================
# Behavior 6 -- DEFAULT (as_json=False) human render is byte-identical to the
#               spec's documented format + same exit code, for every case
# ==========================================================================
def test_b06_default_human_render_byte_identical(tmp_path):
    for name, txt in ALL_CASES.items():
        sub = tmp_path / name
        sub.mkdir()
        cfg, _ = _cfg_with_prd(sub, prd_text=txt)
        exists = txt is not None
        rc, out = _cap(lambda: foundry.prd_status_cli(cfg))
        assert out == _expected_human(cfg, txt), (
            "human render mismatch for %r:\n got=%r\n exp=%r" % (name, out, _expected_human(cfg, txt)))
        assert rc == _expected_rc(txt, exists), "rc mismatch for %r: %r" % (name, rc)


def test_b06_default_equals_explicit_false(tmp_path):
    for name, txt in ALL_CASES.items():
        sub = tmp_path / name
        sub.mkdir()
        cfg, _ = _cfg_with_prd(sub, prd_text=txt)
        rc_def, out_def = _cap(lambda: foundry.prd_status_cli(cfg))
        rc_false, out_false = _cap(lambda: foundry.prd_status_cli(cfg, as_json=False))
        assert out_def == out_false, "default != explicit as_json=False for %r" % name
        assert rc_def == rc_false


def test_b06_as_json_default_is_false():
    sig = inspect.signature(foundry.prd_status_cli)
    assert "as_json" in sig.parameters, "prd_status_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 7 -- as_json=True on an EXISTING file prints EXACTLY
#               json.dumps(to_dict(), indent=2)+newline and NOTHING else
# ==========================================================================
def test_b07_json_output_is_exact(tmp_path):
    for name, txt in EXISTING_CASES.items():
        sub = tmp_path / name
        sub.mkdir()
        cfg, _ = _cfg_with_prd(sub, prd_text=txt)
        _, out = _cap(lambda: foundry.prd_status_cli(cfg, as_json=True))
        expected = json.dumps(foundry.prd_status(txt).to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(),indent=2)+nl for %r" % name
        assert json.loads(out) == foundry.prd_status(txt).to_dict()


# ==========================================================================
# Behavior 8 -- JSON mode leaks NO human line (JSON-structural check); the
#               check is ARMED by the human-render complement; human not JSON
# ==========================================================================
def test_b08_json_lines_start_with_json_token(tmp_path):
    for name, txt in EXISTING_CASES.items():
        sub = tmp_path / name
        sub.mkdir()
        cfg, _ = _cfg_with_prd(sub, prd_text=txt)
        _, out = _cap(lambda: foundry.prd_status_cli(cfg, as_json=True))
        for ln in out.splitlines():
            s = ln.strip()
            assert s == "" or s[0] in "{}[]\"", (
                "JSON line does not start with a JSON token (%r case): %r" % (name, ln))


def test_b08_leak_check_armed_by_human_complement(tmp_path):
    """The SAME structural check must FAIL on the human render -- else its pass
    on JSON is meaningless. The human render for each existing case has at least
    one non-blank line whose stripped first char is NOT a JSON token."""
    for name, txt in EXISTING_CASES.items():
        sub = tmp_path / name
        sub.mkdir()
        cfg, _ = _cfg_with_prd(sub, prd_text=txt)
        _, human = _cap(lambda: foundry.prd_status_cli(cfg, as_json=False))
        nonblank = [ln for ln in human.splitlines() if ln.strip()]
        assert nonblank, "human render empty for %r" % name
        offenders = [ln for ln in nonblank if ln.strip()[0] not in "{}[]\""]
        assert offenders, (
            "leak check inert for %r -- every human line looked like JSON: %r" % (name, human))


def test_b08_human_render_not_valid_json(tmp_path):
    for name, txt in EXISTING_CASES.items():
        sub = tmp_path / name
        sub.mkdir()
        cfg, _ = _cfg_with_prd(sub, prd_text=txt)
        _, human = _cap(lambda: foundry.prd_status_cli(cfg, as_json=False))
        with pytest.raises(json.JSONDecodeError):
            json.loads(human)


# ==========================================================================
# Behavior 9 -- FILE-NOT-FOUND in BOTH modes: identical plain-text, rc 2, no raise
# ==========================================================================
def test_b09_missing_file_both_modes_plain_text(tmp_path):
    cfg, _ = _cfg_with_prd(tmp_path, prd_text=None)  # prd file absent
    assert not pathlib.Path(cfg.prd).exists()
    expected = "prd: file not found: %s\n" % cfg.prd
    for as_json in (False, True):
        rc, out = _cap(lambda: foundry.prd_status_cli(cfg, as_json=as_json))
        assert rc == 2, "missing file returned %r (as_json=%s)" % (rc, as_json)
        assert out == expected, "missing-file line mismatch (as_json=%s): %r" % (as_json, out)
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)  # NOT JSON in either mode


def test_b09_missing_file_never_raises_filenotfound(tmp_path):
    cfg, _ = _cfg_with_prd(tmp_path, prd_text=None)
    for as_json in (False, True):
        try:
            foundry.prd_status_cli(cfg, as_json=as_json)  # must not raise
        except FileNotFoundError:  # pragma: no cover
            pytest.fail("prd_status_cli raised FileNotFoundError (as_json=%s)" % as_json)


# ==========================================================================
# Behavior 10 -- EXIT-CODE parity: both modes agree per case (0,1,2,2)
# ==========================================================================
def test_b10_exit_code_parity(tmp_path):
    expected = {"complete": 0, "incomplete": 1, "invalid": 2, "missing": 2}
    for name, code in expected.items():
        sub = tmp_path / name
        sub.mkdir()
        cfg, _ = _cfg_with_prd(sub, prd_text=ALL_CASES[name])
        rc_h, _ = _cap(lambda: foundry.prd_status_cli(cfg, as_json=False))
        rc_j, _ = _cap(lambda: foundry.prd_status_cli(cfg, as_json=True))
        assert rc_h == rc_j == code, (
            "exit diverged for %r: human=%r json=%r expected=%r" % (name, rc_h, rc_j, code))


# ==========================================================================
# Behavior 11 -- writes NOTHING in both modes, from an empty cwd, over all cases
# ==========================================================================
def test_b11_writes_nothing(tmp_path, monkeypatch):
    cwd = tmp_path / "emptycwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    for name, txt in ALL_CASES.items():
        sub = tmp_path / ("case_" + name)
        sub.mkdir()
        cfg, _ = _cfg_with_prd(sub, prd_text=txt)
        before_repo = _snapshot_tree(cfg.repo)
        before_work = _snapshot_tree(cfg.work_root)
        for as_json in (False, True):
            _cap(lambda: foundry.prd_status_cli(cfg, as_json=as_json))
        assert sorted(p.name for p in cwd.iterdir()) == [], "CLI wrote to cwd for %r" % name
        assert _snapshot_tree(cfg.repo) == before_repo, "CLI changed the repo tree for %r" % name
        assert _snapshot_tree(cfg.work_root) == before_work, "CLI changed work_root for %r" % name


# ==========================================================================
# Behavior 12 -- argparse routing: --json is store_true; dispatch spy proves
#                as_json True/False; --config REQUIRED
# ==========================================================================
def test_b12_json_store_true_via_dispatch_spy(tmp_path, monkeypatch):
    cfg, cfg_path = _cfg_with_prd(tmp_path, prd_text=COMPLETE)
    captured = {}

    def fake(cfg_arg, as_json=False):
        captured.update(name=cfg_arg.name, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "prd_status_cli", fake)
    foundry.main(["prd", "--config", str(cfg_path), "--json"])
    assert captured == {"name": "demoprod", "as_json": True}
    captured.clear()
    foundry.main(["prd", "--config", str(cfg_path)])
    assert captured == {"name": "demoprod", "as_json": False}


def test_b12_config_required_raises_systemexit():
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["prd"])
    assert ei.value.code != 0


def test_b12_json_takes_no_value(tmp_path):
    _, cfg_path = _cfg_with_prd(tmp_path, prd_text=COMPLETE)
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["prd", "--config", str(cfg_path), "--json", "bogus"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 13 -- end-to-end via foundry.main
# ==========================================================================
def test_b13_e2e_complete(tmp_path):
    _, cfg_path = _cfg_with_prd(tmp_path, prd_text=COMPLETE)
    rc, out = _cap(lambda: foundry.main(["prd", "--config", str(cfg_path), "--json"]))
    d = json.loads(out)
    assert rc == 0
    assert d["valid"] is True
    assert d["complete"] is True
    assert isinstance(d["summary"], str)
    assert d["pending"] == []


def test_b13_e2e_incomplete(tmp_path):
    _, cfg_path = _cfg_with_prd(tmp_path, prd_text=INCOMPLETE)
    rc, out = _cap(lambda: foundry.main(["prd", "--config", str(cfg_path), "--json"]))
    d = json.loads(out)
    assert rc == 1
    assert d["complete"] is False
    assert isinstance(d["pending"], list) and len(d["pending"]) >= 1


def test_b13_e2e_invalid_present(tmp_path):
    _, cfg_path = _cfg_with_prd(tmp_path, prd_text=INVALID)
    rc, out = _cap(lambda: foundry.main(["prd", "--config", str(cfg_path), "--json"]))
    d = json.loads(out)
    assert rc == 2
    assert d["valid"] is False


def test_b13_e2e_missing_plain_text(tmp_path):
    cfg, cfg_path = _cfg_with_prd(tmp_path, prd_text=None)
    rc, out = _cap(lambda: foundry.main(["prd", "--config", str(cfg_path), "--json"]))
    assert rc == 2
    assert out == "prd: file not found: %s\n" % cfg.prd
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# ==========================================================================
# Behavior 14 -- DORMANCY: the running loop is unaffected
# ==========================================================================
def test_b14_orchestrators_do_not_reference_prd_cli_symbols():
    new = set(PRD_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references prd CLI symbol(s): %r" % (fn.__name__, refs)


def test_b14_dispatcher_has_zero_prd_cli_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    assert dtext.count("prd_status_cli") == 0, "dispatcher.py references prd_status_cli"
    assert dtext.count("PrdStatus") == 0, "dispatcher.py references PrdStatus"
    assert dtext.count('"prd"') == 0 and dtext.count("'prd'") == 0, (
        "dispatcher.py names the 'prd' command string")


def test_b14_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b14_to_dict_does_not_change_field_equality():
    a = foundry.prd_status(INCOMPLETE)
    b = foundry.prd_status(INCOMPLETE)
    assert a == b, "adding to_dict must not change PrdStatus value-equality"
    _ = a.to_dict()
    assert a == b


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.prd_status)
    assert callable(foundry.prd_status_cli)
    assert dataclasses.is_dataclass(foundry.PrdStatus)
    assert callable(foundry.PrdStatus.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_prd(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "prd" in out
    for sub in ("run", "once", "learnings", "agents", "lint-spec"):
        assert sub in out, "subcommand %r missing from --help (regression)" % sub


def test_ac_new_symbols_ascii():
    """Scoped to the two symbols via inspect.getsource -- NOT a whole-file scan
    (foundry.py carries pre-existing non-ASCII elsewhere -- the iter-67 trap)."""
    srcs = [
        inspect.getsource(foundry.PrdStatus.to_dict),
        inspect.getsource(foundry.prd_status_cli),
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
