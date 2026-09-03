"""Black-box behaviour tests for iter 204 -- iteration 203's `company-stops`
verb re-lands, and the frozen newest-ness-pin class that reverted it is retired.

Spec: products/_platform/state/iter-204/pm.md, Expected Behaviors 1-15.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-204 PM spec and the
product's OBSERVABLE surface -- importing modules, CALLING functions, reading
`__doc__` and `inspect.signature`, and reading files under `tests/` for
CONVENTIONS plus the product roadmap files and README (explicitly allowed, and
the SUBJECT of behaviors 12/13/15). Behaviors 11/12/14/15 are LEXICAL censuses
whose declared domain IS a source file, so they parse source mechanically (ast
walks, token counts, `git show HEAD:`) -- they never read it for design intent.
The engineer's notes (engineer.md), the reviewer's notes (reviewer.md), the
IMPLEMENTATION / reland patches and `git diff` output were NOT read.
"""
import ast
import contextlib
import dataclasses
import io
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tests"))
import foundry  # noqa: E402

THIS_ITER = 204
TESTS_DIR = _ROOT / "tests"
FOUNDRY_PY = _ROOT / "foundry.py"
DISPATCHER_PY = _ROOT / "dispatcher.py"
README = _ROOT / "README.md"

STOPS_NAMES = ("gather_stop", "summarize_stops", "company_stops_cli")
SUMM_FIELDS = ("dispatch_path", "products", "disabled", "errors")


# --------------------------------------------------------------------------
# helpers -- mirror the suite's existing conventions
# --------------------------------------------------------------------------
def _cfg(**over):
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _team(tmp_path, name, *, stop_text=None, stop_bytes=None, stop_dir=False):
    """A team whose work_root lives under tmp_path, optionally with a sentinel."""
    root = pathlib.Path(tmp_path) / name
    root.mkdir(parents=True, exist_ok=True)
    cfg = _cfg(name=name, work_root=str(root))
    target = pathlib.Path(cfg.stop_file)
    if stop_dir:
        target.mkdir(parents=True, exist_ok=True)
    elif stop_bytes is not None:
        target.write_bytes(stop_bytes)
    elif stop_text is not None:
        target.write_text(stop_text)
    return cfg


def _no_global(monkeypatch):
    monkeypatch.setattr(foundry, "global_stop", lambda: False)


def _row(**over):
    kw = dict(product="p", sentinel="/s/STOP", stopped=False, scope="none",
              reason="")
    kw.update(over)
    return foundry.StopRow(**kw)


def _summ(**over):
    kw = dict(dispatch_path="/d/foundry.config.json", products=(),
              disabled=(), errors=())
    kw.update(over)
    return foundry.summarize_stops(**kw)


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return str(p)


def _run_cli(dispatch_path, *, as_json=False):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = foundry.company_stops_cli(dispatch_path, as_json=as_json)
    return rc, out.getvalue() + err.getvalue()


def _git_show(rel):
    return subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(_ROOT),
                          capture_output=True, text=True)


# ==========================================================================
# Behavior 1 -- stop_reason is PURE and TOTAL on the happy path
# ==========================================================================
def test_b01_stop_reason_returns_collapsed_first_nonempty_line():
    f = foundry.stop_reason
    assert f("retired 2026-08-03\nlift when the fast test cmd lands") == \
        "retired 2026-08-03", "must return only the FIRST non-empty line"
    assert f("\n\n  retired\tfor \t now  \nsecond line") == "retired for now", \
        "a leading blank line is skipped, internal whitespace collapses, ends strip"
    assert f("  a   b  ") == "a b"
    # PURE: same input -> == result, and no mutation of the argument
    src = "keep\nme"
    assert f(src) == f(src) == "keep"
    assert src == "keep\nme", "stop_reason must not mutate its argument"


# ==========================================================================
# Behavior 2 -- totality: never raises, and truncates at 160 chars
# ==========================================================================
@pytest.mark.parametrize("bad", [None, 7, 0.5, [], {}, object(), b"bytes", "",
                                 "   ", "\n\n", "\t \n  \t"])
def test_b02_stop_reason_is_total(bad):
    got = foundry.stop_reason(bad)
    assert got == "", f"stop_reason({bad!r}) must be '' , got {got!r}"


def test_b02_stop_reason_truncates_a_long_first_line():
    long = "x" * 500
    got = foundry.stop_reason(long + "\nsecond")
    assert len(got) <= 160, f"must truncate to <=160 chars, got {len(got)}"
    assert len(got) == 160, f"a 500-char first line must yield 160, got {len(got)}"
    assert got == "x" * 160
    # a line exactly at the boundary survives whole
    assert foundry.stop_reason("y" * 160) == "y" * 160


# ==========================================================================
# Behavior 3 -- no team sentinel, no global sentinel -> not stopped
# ==========================================================================
def test_b03_no_sentinel_is_scope_none(tmp_path, monkeypatch):
    _no_global(monkeypatch)
    cfg = _team(tmp_path, "quiet")
    row = foundry.gather_stop(cfg)
    assert row.stopped is False, "no sentinel must not read as stopped"
    assert row.scope == "none", f"scope must be 'none', got {row.scope!r}"
    assert row.reason == "", f"reason must be empty, got {row.reason!r}"
    assert row.product == "quiet", "the row must name its team"
    assert row.sentinel == str(cfg.stop_file), \
        "the row must disclose the path it checked"
    assert not pathlib.Path(cfg.stop_file).exists(), \
        "gather_stop must not CREATE the sentinel it looks for"


# ==========================================================================
# Behavior 4 -- a team sentinel -> stopped, scope 'team', reason from its text
# ==========================================================================
def test_b04_team_sentinel_is_scope_team_with_its_reason(tmp_path, monkeypatch):
    _no_global(monkeypatch)
    text = "retired 2026-08-03: full suite 498s\nlift when a fast cmd lands"
    cfg = _team(tmp_path, "retired", stop_text=text)
    row = foundry.gather_stop(cfg)
    assert row.stopped is True
    assert row.scope == "team", f"scope must be 'team', got {row.scope!r}"
    assert row.reason == foundry.stop_reason(text), \
        "reason must equal stop_reason of the sentinel's text"
    assert row.reason == "retired 2026-08-03: full suite 498s"
    # an EMPTY sentinel still stops -- existence decides, text only explains
    cfg2 = _team(tmp_path, "empty-sentinel", stop_text="")
    row2 = foundry.gather_stop(cfg2)
    assert row2.stopped is True and row2.scope == "team"


# ==========================================================================
# Behavior 5 -- the global sentinel is broader and wins
# ==========================================================================
def test_b05_global_sentinel_stops_a_team_with_no_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "global_stop", lambda: True)
    cfg = _team(tmp_path, "no-own-sentinel")
    row = foundry.gather_stop(cfg)
    assert row.stopped is True, "a global stop must stop every team"
    assert row.scope == "global", f"scope must be 'global', got {row.scope!r}"


def test_b05_global_reason_wins_when_both_sentinels_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "global_stop", lambda: True)
    cfg = _team(tmp_path, "both", stop_text="team-level reason")
    row = foundry.gather_stop(cfg)
    assert row.scope == "global", \
        "global scope is strictly broader, so it must win over 'team'"
    assert row.reason != "team-level reason", \
        "when both exist the GLOBAL reason must win"


# ==========================================================================
# Behavior 6 -- an unreadable sentinel still stops, with a marker reason
# ==========================================================================
def test_b06_undecodable_sentinel_stops_with_a_marker_reason(tmp_path, monkeypatch):
    _no_global(monkeypatch)
    cfg = _team(tmp_path, "binary", stop_bytes=b"\xff\xfe\x00\x81\x9f")
    row = foundry.gather_stop(cfg)          # must not raise
    assert row.stopped is True, "existence decides the stop, not decodability"
    assert row.scope == "team"
    assert row.reason.strip() != "", \
        "an unreadable sentinel must still carry a NON-EMPTY marker reason"


def test_b06_unreadable_sentinel_stops_with_a_marker_reason(tmp_path, monkeypatch):
    _no_global(monkeypatch)
    cfg = _team(tmp_path, "dir-sentinel", stop_dir=True)
    row = foundry.gather_stop(cfg)          # a directory cannot be read as text
    assert row.stopped is True
    assert row.scope == "team"
    assert row.reason.strip() != ""


# ==========================================================================
# Behavior 7 -- summarize_stops is keyword-only and returns a frozen mixin type
# ==========================================================================
def test_b07_summarize_stops_is_keyword_only():
    import inspect
    params = inspect.signature(foundry.summarize_stops).parameters
    assert [p.name for p in params.values()] == list(SUMM_FIELDS), \
        f"parameter names must be exactly {SUMM_FIELDS}"
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY
               for p in params.values()), "every parameter must be keyword-only"
    with pytest.raises(TypeError):
        foundry.summarize_stops("/d", (), (), ())          # positional is refused


def test_b07_company_stops_is_a_frozen_rollup_dataclass():
    cls = foundry.CompanyStops
    assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen, \
        "CompanyStops must be a FROZEN dataclass"
    assert tuple(f.name for f in dataclasses.fields(cls)) == SUMM_FIELDS, \
        f"fields must be exactly {SUMM_FIELDS}"
    assert foundry.CompanyRollupCounts in cls.__mro__, \
        "CompanyStops must mix in CompanyRollupCounts"
    for name in ("n_products", "n_disabled", "n_errors"):
        assert name not in vars(cls), \
            f"{name} must be INHERITED from the mixin, not redeclared"
        assert hasattr(cls, name), f"{name} must be reachable on CompanyStops"


def test_b07_equal_inputs_compare_equal_and_fields_are_immutable():
    kw = dict(dispatch_path="/d", products=(_row(product="a"),),
              disabled=("b",), errors=(("c", "boom"),))
    a, b = foundry.summarize_stops(**kw), foundry.summarize_stops(**kw)
    assert a == b, "equal inputs must compare =="
    for name in SUMM_FIELDS:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(a, name, ("mutated",))


# ==========================================================================
# Behavior 8 -- the verdict/exit table is DERIVED from stored fields
# ==========================================================================
def test_b08_n_stopped_counts_stopped_rows():
    s = _summ(products=(_row(product="a", stopped=True, scope="team"),
                        _row(product="b"),
                        _row(product="c", stopped=True, scope="global")))
    assert s.n_stopped == 2, f"n_stopped must be 2, got {s.n_stopped}"
    assert s.n_products == 3


@pytest.mark.parametrize("products,disabled,errors,verdict,code", [
    ((_row(product="a", stopped=True, scope="team"),), (), (), "STOPPED", 1),
    # a stopped row outranks errors
    ((_row(product="a", stopped=True, scope="team"),), (),
     (("x", "boom"),), "STOPPED", 1),
    ((_row(product="a"),), (), (), "RUNNING", 0),
    ((), (), (), "NOTHING-TO-REPORT", 2),
])
def test_b08_verdict_and_exit_table(products, disabled, errors, verdict, code):
    s = _summ(products=products, disabled=disabled, errors=errors)
    assert s.verdict == verdict, \
        f"verdict must be {verdict!r}, got {s.verdict!r}"
    assert s.exit_code == code, \
        f"exit_code must be {code}, got {s.exit_code}"


def test_b08_errors_alone_still_exit_nonzero():
    s = _summ(products=(_row(product="a"),), errors=(("x", "boom"),))
    assert s.n_stopped == 0
    assert s.exit_code == 1, \
        "no stopped row but a non-empty errors tuple must still exit 1"


# ==========================================================================
# Behavior 9 -- to_dict()/render() can never disagree with exit_code
# ==========================================================================
@pytest.mark.parametrize("products,errors", [
    ((_row(product="a", stopped=True, scope="team", reason="r"),), ()),
    ((_row(product="a"),), ()),
    ((), ()),
    ((_row(product="a"),), (("x", "boom"),)),
])
def test_b09_render_and_to_dict_name_the_same_verdict(products, errors):
    s = _summ(products=products, errors=errors)
    d, text = s.to_dict(), s.render()
    assert s.verdict in json.dumps(d), \
        f"to_dict must name the verdict token {s.verdict!r}"
    assert s.verdict in text, \
        f"render must name the verdict token {s.verdict!r}"


def test_b09_render_names_every_stopped_team_with_scope_and_reason():
    s = _summ(products=(_row(product="alpha", stopped=True, scope="team",
                             reason="retired 2026-08-03"),
                        _row(product="beta", stopped=True, scope="global",
                             reason="fleet freeze"),
                        _row(product="gamma")),
              disabled=("delta",))
    text = s.render()
    for tok in ("alpha", "team", "retired 2026-08-03",
                "beta", "global", "fleet freeze"):
        assert tok in text, f"render must disclose {tok!r}"
    assert re.search(r"\b1\b", text), "render must disclose n_disabled"
    assert "delta" in text or "disabled" in text.lower(), \
        "a disabled work item must never be silently absent"


def test_b09_json_stdout_is_exactly_one_indent2_document(tmp_path, monkeypatch):
    _no_global(monkeypatch)
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: _team(tmp_path, "solo", stop_text="halted"))
    d = _write_dispatch(tmp_path, [{"name": "solo", "config": "c-solo"}],
                        name="json-one.json")
    rc, out = _run_cli(d, as_json=True)
    doc = json.loads(out)                      # exactly ONE document parses
    assert out.strip() == json.dumps(doc, indent=2).strip(), \
        "stdout must be exactly one json.dumps(..., indent=2) document"
    assert rc == 1 and doc.get("verdict") == "STOPPED"


# ==========================================================================
# Behavior 10 -- resilience: a report, never a traceback
# ==========================================================================
@pytest.mark.parametrize("body", [None, "this is not json {{{",
                                  '["a", "list", "not", "an", "object"]'])
def test_b10_bad_dispatch_config_is_one_report_with_one_error(tmp_path, body):
    p = pathlib.Path(tmp_path) / "bad.json"
    if body is not None:
        p.write_text(body)
    rc, out = _run_cli(str(p))
    assert rc == 1, f"a bad dispatch config must exit 1, got {rc}"
    assert "Traceback" not in out, "must never leak a traceback"
    assert out.strip(), "must still print a report"


def test_b10_one_raising_work_item_is_recorded_and_the_rollup_continues(
        tmp_path, monkeypatch):
    _no_global(monkeypatch)
    good = _team(tmp_path, "good", stop_text="halted here")

    def _load(path):
        if "boom" in path:
            raise RuntimeError("synthetic load failure")
        return good

    monkeypatch.setattr(foundry, "load_config", _load)
    d = _write_dispatch(tmp_path, [{"name": "boom", "config": "c-boom"},
                                   {"name": "good", "config": "c-good"}],
                        name="one-raises.json")
    rc, out = _run_cli(d, as_json=True)
    doc = json.loads(out)
    assert doc["n_errors"] == 1, \
        f"the raising item must be recorded once, got {doc['n_errors']}"
    assert doc["n_products"] == 1, \
        "the roll-up must CONTINUE over the remaining teams"
    assert rc == 1 and "Traceback" not in out


def test_b10_a_raising_gather_is_also_recorded(tmp_path, monkeypatch):
    _no_global(monkeypatch)
    monkeypatch.setattr(foundry, "load_config",
                        lambda p: _team(tmp_path, "g" + str(abs(hash(p)) % 97)))
    monkeypatch.setattr(foundry, "gather_stop",
                        lambda cfg: (_ for _ in ()).throw(OSError("gather boom")))
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"},
                                   {"name": "b", "config": "cb"}],
                        name="gather-raises.json")
    rc, out = _run_cli(d, as_json=True)
    doc = json.loads(out)
    assert doc["n_errors"] == 2, \
        f"both raising gathers must be recorded, got {doc['n_errors']}"
    assert rc == 1 and "Traceback" not in out


def test_b10_a_disabled_work_item_is_recorded_and_never_loaded(tmp_path,
                                                               monkeypatch):
    _no_global(monkeypatch)
    seen = []

    def _load(path):
        seen.append(path)
        return _team(tmp_path, "on")

    monkeypatch.setattr(foundry, "load_config", _load)
    d = _write_dispatch(tmp_path, [{"name": "on", "config": "c-on"},
                                   {"name": "off", "config": "c-off",
                                    "enabled": False}],
                        name="disabled.json")
    rc, out = _run_cli(d, as_json=True)
    doc = json.loads(out)
    assert doc["n_disabled"] == 1, \
        f"the disabled item must be recorded, got {doc['n_disabled']}"
    assert doc["disabled"] == ["off"]
    assert not any("c-off" in s for s in seen), \
        "a disabled work item must never be loaded"


# ==========================================================================
# Behavior 11 -- DORMANT and read-only
# ==========================================================================
def _call_sites(source_text, names):
    """(callee, enclosing def name) for every Call whose callee is in `names`."""
    tree = ast.parse(source_text)
    owner = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                owner.setdefault(id(child), node.name)
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        nm = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if nm in names:
            sites.append((nm, owner.get(id(node), "<module>")))
    return sites


def test_b11_the_verb_has_no_call_site_in_any_control_path():
    sites = _call_sites(FOUNDRY_PY.read_text(), set(STOPS_NAMES))
    banned = {"run_iteration", "run_stage", "final_gate"}
    for callee, enclosing in sites:
        low = enclosing.lower()
        assert enclosing not in banned, \
            f"{callee} must have NO call site in {enclosing}, found one"
        assert not (low.startswith("stage_") or low.endswith("_stage")), \
            f"{callee} must not be called from stage {enclosing}"
        assert "final_gate" not in low, \
            f"{callee} must not be called from the final gate ({enclosing})"
    disp = DISPATCHER_PY.read_text()
    for name in STOPS_NAMES:
        assert name not in disp, \
            f"dispatcher.py must not mention {name}; the verb is on-demand only"


def test_b11_the_verb_writes_nothing_to_disk(tmp_path, monkeypatch):
    _no_global(monkeypatch)
    ro = _team(tmp_path, "ro", stop_text="halted")   # fixture writes BEFORE the snap
    monkeypatch.setattr(foundry, "load_config", lambda p: ro)
    d = _write_dispatch(tmp_path, [{"name": "ro", "config": "c-ro"}],
                        name="readonly.json")

    def snap():
        return {str(p): (p.stat().st_size, p.stat().st_mtime_ns)
                for p in sorted(pathlib.Path(tmp_path).rglob("*")) if p.is_file()}

    before = snap()
    monkeypatch.chdir(tmp_path)
    rc, _ = _run_cli(d, as_json=True)
    after = snap()
    assert after == before, \
        f"company-stops must write nothing; changed: {set(after) ^ set(before)}"
    assert rc == 1


# ==========================================================================
# Behavior 12 -- live brakes over the LIVE tree
# ==========================================================================
def test_b12_company_stops_is_a_registered_verb_and_the_readme_indexes_it():
    verbs = foundry.foundry_cli_verbs(FOUNDRY_PY.read_text())
    assert "company-stops" in verbs, \
        f"'company-stops' must be a foundry CLI verb; got {len(verbs)} verbs"
    audit = foundry.readme_verb_index_gaps(README.read_text(), verbs)
    assert audit.ok is True, f"README verb index must be clean, got {audit}"
    assert not audit.missing_verbs, \
        f"README must index every verb, missing: {audit.missing_verbs}"


def test_b12_readme_no_longer_claims_a_last_company_member():
    text = README.read_text()
    for bad in ("5th and LAST", "5th and last"):
        assert bad not in text, \
            f"README must not claim {bad!r} company-* member; it is false today"


# ==========================================================================
# Behavior 13 -- the two iter-185 de-pins hold their DURABLE intent
# ==========================================================================
def test_b13_the_185_depins_are_existence_and_lower_bound_claims():
    src = (TESTS_DIR / "test_iter185_behavior.py").read_text()
    flat = " ".join(src.split())
    assert "ARCHIVE_HEADING in heads" in flat, \
        "b09a must assert EXISTENCE (`ARCHIVE_HEADING in heads`), not position"
    assert "heads[-1] == ARCHIVE_HEADING" not in flat, \
        "the newest-ness pin `heads[-1] == ARCHIVE_HEADING` must be GONE"
    assert "heads.count(ARCHIVE_HEADING) == 1" in flat, \
        "the pre-existing uniqueness assertion must stay -- it is what makes " \
        "the loosening safe rather than a weakening"
    assert "iters[-1] >= THIS_ITER" in flat, \
        "b09c must assert a LOWER BOUND on the newest compacted iteration"
    assert "THIS_ITER in iters" in flat, \
        "b09c must ALSO assert `THIS_ITER in iters`; `>=` alone goes vacuous " \
        "if 185's own heading is ever dropped"
    assert "iters[-1] == THIS_ITER" not in flat, \
        "the newest-ness pin `iters[-1] == THIS_ITER` must be GONE"
    assert "iters == sorted(iters)" in flat, \
        "the pre-existing ordering assertion must stay"


def test_b13_the_live_archive_carries_this_iterations_compaction_heading():
    arc = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()
    heading = f"## Compacted from the index by iter {THIS_ITER}"
    assert heading in arc, f"the archive must carry {heading!r}"
    assert arc.count(heading) == 1, "exactly one such heading"
    stale = "## Compacted from the index by iter 203"
    assert stale not in arc, \
        f"{stale!r} must have been re-keyed to {THIS_ITER}"
    assert stale not in (_ROOT / "PLATFORM_ROADMAP.md").read_text(), \
        "no index stub may point at a compaction heading that no longer exists"


# ==========================================================================
# Behavior 14 -- a test-only meta-brake keeps the frozen class empty
# ==========================================================================
def _assert_probe(src, node):
    """The assert's source, flattened, with every string/bytes literal REMOVED.

    A newest-ness marker inside a QUOTED span is a test TALKING ABOUT the
    pattern -- behaviors 13 and 15 of this very file quote both fatal forms
    verbatim -- not an assertion making the claim. Counting quoted text makes
    the detector accuse its own documentation, which is a fail-CLOSED bug: it
    reports a defect in a correct file and points at a destructive repair."""
    seg = ast.get_source_segment(src, node) or ""
    pieces = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.JoinedStr) or (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, (str, bytes))):
            piece = ast.get_source_segment(src, sub)
            if piece:
                pieces.append(piece)
    for piece in sorted(pieces, key=len, reverse=True):
        seg = seg.replace(piece, "")
    return " ".join(seg.split())


NEWEST_MARKERS = ("[-1]", "max(", "[0].startswith")
DOC_TOKENS = ("ROADMAP", "ARCHIVE", "README")
_FROZEN_RHS = re.compile(r"==\s*(?:\d+|THIS_ITER)\b")


def newest_ness_pin_sites(source_by_name):
    """PURE detector. Returns every assertion that (i) makes a newest-ness claim,
    (ii) compares with `==` or `.startswith(`, and (iii) sits in a TEST FUNCTION
    whose OWN BODY reads a live tracked doc. Condition (iii) is scoped to the
    function body on purpose: evaluated at module level it over-accuses tests
    that merely live beside a doc-reading test."""
    sites = []
    for name in sorted(source_by_name):
        src = source_by_name[name]
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test_"):
                continue
            body = ast.get_source_segment(src, fn) or ""
            if not any(tok in body for tok in DOC_TOKENS):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Assert):
                    continue
                probe = _assert_probe(src, node)
                if not any(m in probe for m in NEWEST_MARKERS):
                    continue
                if "==" not in probe and ".startswith(" not in probe:
                    continue
                sites.append((name, node.lineno, fn.name, probe))
    return tuple(sites)


def _tree_sources():
    return {p.name: p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(TESTS_DIR.glob("test_*.py"))}


def test_b14_detector_is_non_vacuous_over_the_shipped_tree():
    srcs = _tree_sources()
    assert len(srcs) >= 100, \
        f"the detector must parse >=100 test files, saw {len(srcs)}"
    parsed = sum(1 for s in srcs.values()
                 if _parses(s))
    assert parsed >= 100, f"only {parsed} files parsed; a silent scan cannot pass"


def _parses(src):
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def test_b14_no_frozen_newest_ness_pin_remains_in_the_shipped_tree():
    offenders = [s for s in newest_ness_pin_sites(_tree_sources())
                 if _FROZEN_RHS.search(s[3])]
    assert offenders == [], (
        "a newest-ness claim about a live tracked doc must never be compared "
        "with == against a bare integer literal or THIS_ITER:\n"
        + "\n".join(f"  {f}:{ln} in {fn}: {seg}" for f, ln, fn, seg in offenders))


def test_b14_detector_is_two_sided_on_synthetic_source():
    fatal = (
        "ARCHIVE_HEADING = 'h'\n"
        "THIS_ITER = 204\n"
        "def test_fatal_a():\n"
        "    heads = _heads(ARCHIVE_HEADING)\n"
        "    assert heads[-1] == ARCHIVE_HEADING\n"
        "def test_fatal_b():\n"
        "    iters = _iters('PLATFORM_ROADMAP_ARCHIVE.md')\n"
        "    assert iters[-1] == THIS_ITER\n"
    )
    safe = (
        "ARCHIVE_HEADING = 'h'\n"
        "THIS_ITER = 204\n"
        "def test_safe_a():\n"
        "    heads = _heads(ARCHIVE_HEADING)\n"
        "    assert ARCHIVE_HEADING in heads\n"
        "def test_safe_b():\n"
        "    iters = _iters('PLATFORM_ROADMAP_ARCHIVE.md')\n"
        "    assert iters[-1] >= THIS_ITER\n"
    )
    fired = newest_ness_pin_sites({"synthetic_fatal.py": fatal})
    assert len(fired) == 2, f"detector must FIRE on both fatal forms, got {fired}"
    segs = [s[3] for s in fired]
    assert any("heads[-1]" in s and "ARCHIVE_HEADING" in s for s in segs), \
        f"detector must FIRE on the heads[-1] == ARCHIVE_HEADING form, got {segs}"
    assert any(_FROZEN_RHS.search(s) for s in segs), \
        f"detector must FIRE on the iters[-1] == THIS_ITER form, got {segs}"
    silent = newest_ness_pin_sites({"synthetic_safe.py": safe})
    assert silent == (), \
        f"detector must be SILENT on both de-pinned forms, got {silent}"


def test_b14_detector_scopes_the_doc_condition_to_the_test_body():
    """A module that READS a doc must not make its unrelated tests offenders."""
    src = (
        "ROADMAP = 'PLATFORM_ROADMAP.md'\n"
        "def test_unrelated():\n"
        "    pool = [1.0, 2.0, 100.0]\n"
        "    assert max(pool) == 100.0\n"
    )
    assert newest_ness_pin_sites({"m.py": src}) == (), \
        "the doc condition must be scoped to the TEST FUNCTION body, not the module"


# ==========================================================================
# Behavior 15 -- the over-broad sweep is REFUSED, measured against HEAD
# ==========================================================================
@pytest.mark.parametrize("rel", ["tests/test_iter124_behavior.py",
                                 "tests/test_iter162_behavior.py"])
def test_b15_the_benign_literal_class_is_byte_unchanged_against_head(rel):
    shown = _git_show(rel)
    if shown.returncode != 0:
        pytest.skip(f"git show unavailable for {rel}")
    assert shown.stdout == (_ROOT / rel).read_text(), \
        f"{rel} must be BYTE-UNCHANGED against HEAD -- it is not a newest-ness pin"


def test_b15_the_benign_literals_still_stand():
    a = " ".join((TESTS_DIR / "test_iter124_behavior.py").read_text().split())
    assert "max(frozen) == 119" in a, \
        "a deliberately FROZEN historical set must keep its == pin"
    assert "len(frozen) == 98" in a, "its companion pin must also stand"
    b = " ".join((TESTS_DIR / "test_iter162_behavior.py").read_text().split())
    assert "sorted(nums) == list(range(0, max(nums) + 1))" in b, \
        "a CONTIGUITY claim derived from max(nums) itself must not be converted"


def test_b15_only_the_three_expected_test_files_differ_from_head():
    r = subprocess.run(["git", "diff", "HEAD", "--name-only", "--", "tests/"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("git diff unavailable")
    changed = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    # This iteration's OWN new test file joins the set the moment the final gate
    # runs `git add -A` (an untracked path is invisible to `git diff HEAD`, a
    # STAGED one is not), so it is expected rather than an unswept-class hit.
    expected = {"tests/test_iter185_behavior.py",
                "tests/test_iter175_behavior.py",
                "tests/test_iter202_behavior.py",
                f"tests/test_iter{THIS_ITER}_behavior.py",
                # iter 212: retired ONE stale (sibling, symbol) pair in iter 59's
                # additive-dormancy brake, because `test_quality_cli` now composes
                # through the `gather_test_quality` seam. This path is allow-listed
                # rather than the assertion weakened: the edit is provably OUTSIDE
                # this brake's domain -- `newest_ness_pin_sites` over that file is
                # `()` at HEAD AND in the worktree, so no newest-ness pin was
                # swept, converted or added. The CONTENT guarantees for the
                # 75-assertion literal class are carried by the two sibling checks
                # above (the byte-unchanged pins on iters 124/162 and
                # `test_b15_the_benign_literals_still_stand`), which are untouched.
                "tests/test_iter59_behavior.py",
                # iter 215: repaired iter 131's scout-slate parse brake, which had
                # gone RED on ambient gitignored state left by a CONCURRENT product's
                # cap-killed scout stage -- nothing in iteration 215's own diff.
                # Measured on this checkout: under HEAD's rule 3 slates parse to zero
                # candidates against its `<= 2` bound, and all 3 self-declare as
                # write-early checkpoints (2 of the 3 belong to other products), so
                # REVERTING that edit leaves iter 131 red -- it is forced, not
                # optional. Allow-listed rather than the assertion weakened, on the
                # same evidence the iter-59 row above uses: `newest_ness_pin_sites`
                # over that file is `()` at HEAD AND in the worktree, so no
                # newest-ness pin was swept, converted or added, and the
                # 75-assertion literal class keeps both sibling checks above.
                "tests/test_iter131_behavior.py",
                # iter 217: `gather_status` composes the report-only live-lag
                # sentence, so `StatusSummary.to_dict()` gains `lag_line` and
                # `lag_verdict` (12 -> 14 keys) and `render()` gains one line.
                # TWO shipped test files are FORCED to differ from HEAD by that:
                #   * iter 19 owns the ONLY key-count/order pin on that payload
                #     (`STORED_KEYS`/`DERIVED_KEYS`, `len(d) == 14`) -- the
                #     3-line re-pin the spec requires;
                #   * iter 16 `test_b11_no_iterations_exit2` carried a
                #     WHOLE-OUTPUT `\bOK\b` negative pin that the composed
                #     `live-lag: OK ...` line trips. It is SCOPED to the
                #     report's own lines -- the composed line has its own
                #     `live-lag:` verdict namespace -- NOT weakened, and the
                #     scoping also removes a real machine-dependence:
                #     `dispatcher.out` is UNTRACKED, so that line renders `OK`
                #     on a machine with a live brain and `UNKNOWN` in the fresh
                #     clone, which would have flipped this brake either way.
                # Allow-listed rather than either assertion weakened, on the same
                # evidence the two rows above use: `newest_ness_pin_sites` over
                # BOTH files is `()` at HEAD AND in the worktree, so no
                # newest-ness pin was swept, converted or added, and the
                # 75-assertion literal class keeps both sibling checks above.
                "tests/test_iter19_behavior.py",
                "tests/test_iter16_behavior.py",
                # iter 219: repaired iter 214's whole-population leak brake,
                # which had gone RED intermittently under a concurrent suite on
                # an OVER-ASSERTION -- it pinned `missing == ()` while
                # `scan_paths`' own docstring defines `missing` as a SOFT skip
                # that does "NOT change the exit code". TWO shipped test files
                # are FORCED to differ from HEAD by that repair:
                #   * iter 214 owns the three whole-population brake sites;
                #     each now routes `missing` through a PURE classifier that
                #     reds on a TRACKED unreadable member (there the scan
                #     really did cover less than the shipping tree) and
                #     tolerates an UNTRACKED vanished one, whose existence is
                #     not a stable property while another worker runs. The
                #     brake is made to match the scanner's own documented
                #     contract, NOT weakened: leak-detection strength is
                #     untouched and the findings assertion still runs.
                #   * iter 25 `test_b10_pattern_and_json_subprocess` was the
                #     one observed writer of a transient artifact into the
                #     SHARED repo root, i.e. the race's source. Its spy output
                #     moves to the pytest temp dir and travels in the
                #     environment, so no absolute machine path becomes a
                #     literal here. Removing the writer alone would leave the
                #     race open to any other transient untracked path, so both
                #     halves are required.
                # Allow-listed rather than either assertion weakened, on the
                # same evidence the rows above use: `newest_ness_pin_sites`
                # over BOTH files is `()` at HEAD AND in the worktree, so no
                # newest-ness pin was swept, converted or added, and the
                # 75-assertion literal class keeps both sibling checks above.
                "tests/test_iter214_behavior.py",
                "tests/test_iter25_behavior.py"}
    assert changed <= expected, \
        f"the 75-assertion literal class must NOT be swept; unexpected: {changed - expected}"
    # NOT asserted here: that 185 IS in `changed`. Post-commit -- and in the
    # throwaway FRESH CLONE every ship is re-verified from -- HEAD already
    # carries the de-pins, so this diff is legitimately EMPTY. The de-pins
    # landing is proved from FILE CONTENT in b13, which is clone-safe.
