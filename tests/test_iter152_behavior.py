"""Black-box behaviour tests for iter 152 -- the three extra-kwarg
`company_*_cli` roll-up verbs collapse onto the ONE shared roll-up body while
every OBSERVABLE behaviour stays unchanged.

Under test (roadmap item (i)'s named follow-up, the three stragglers left out of
iteration 146's six-member collapse):
`company_history_cli(dispatch_path, limit=None, as_json=False)`,
`company_timing_cli(dispatch_path, limit=None, as_json=False)`,
`company_events_cli(dispatch_path, kind=None, limit=None, as_json=False)`.
Each still drives its OWN `gather_*` + `summarize_company_*` seam pair plus the
shared `load_config` / `parse_dispatch_work_items` seams, all BY BARE MODULE
NAME at CALL time, and each still hands its seams the extra arguments that kept
it out of the earlier collapse (`limit`, `threshold=`, `kind` / `kind_filter=`).

THE BLOCKING CRITERION (spec Acceptance): `company_timing_cli` must read
`SUITE_SLOW_SECONDS` at CALL time, never as a def-time default argument. A
green happy-path assertion cannot prove that on its own, so
`test_b04_timing_threshold_is_read_at_call_time_not_def_time` carries a DEFECT
TWIN defined in this file with the frozen-default bug: the twin must report the
stale value in the same process where the shipped verb reports the live one.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-152 PM
spec's Expected Behaviors (1-10), the tests/ conventions (esp.
tests/test_iter146_behavior.py -- the structural mirror for the other six
members of this family), and the product's OWN OBSERVABLE behaviour (calling
the three public verbs plus the shared body with scripted seams and reading
their return code, stdout and public runtime objects). foundry.py's source text
was NOT read, no `inspect.getsource` is used anywhere in this file, and neither
the engineer's nor the reviewer's notes nor any `git diff` was consulted.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

# ---------------------------------------------------------------------------
# the family under test
# ---------------------------------------------------------------------------
# (cli name, gather seam, summarize seam, public parameter list)
STRAGGLERS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("company_history_cli", "gather_history", "summarize_company_history",
     ("dispatch_path", "limit", "as_json")),
    ("company_timing_cli", "gather_timing", "summarize_company_timing",
     ("dispatch_path", "limit", "as_json")),
    ("company_events_cli", "gather_events", "summarize_company_events",
     ("dispatch_path", "kind", "limit", "as_json")),
)

# the six members collapsed by iteration 146 -- the incumbent 4-argument callers
# of the shared body, used here as the "unchanged" control for Behavior 1
SIX = (
    ("company_status_cli", "gather_status", "summarize_company"),
    ("company_weak_tests_cli", "gather_weak_tests", "summarize_company_weak_tests"),
    ("company_constant_asserts_cli", "gather_constant_asserts",
     "summarize_company_constant_asserts"),
    ("company_skipped_tests_cli", "gather_skipped_tests",
     "summarize_company_skipped_tests"),
    ("company_test_quality_cli", "gather_test_quality",
     "summarize_company_test_quality"),
    ("company_config_lint_cli", "gather_config_lint", "summarize_company_config_lint"),
)

NINE = tuple(v[0] for v in SIX) + tuple(v[0] for v in STRAGGLERS)

# the four keyword-only fields EVERY summarize seam in the family receives
BASE_SUMM_KEYS = {"dispatch_path", "products", "disabled", "errors"}


def _expected_gather_extra(cli_name, limit, kind):
    """The extra POSITIONAL arguments each verb owes its gather seam."""
    return {
        "company_history_cli": (limit,),
        "company_timing_cli": (limit,),
        "company_events_cli": (kind, limit),
    }[cli_name]


def _expected_extra_summ_keys(cli_name):
    return {
        "company_history_cli": set(),
        "company_timing_cli": {"threshold"},
        "company_events_cli": {"kind_filter"},
    }[cli_name]


# ---------------------------------------------------------------------------
# helpers (shape mirrored from tests/test_iter146_behavior.py)
# ---------------------------------------------------------------------------
class _FakeSummary:
    """Stand-in for CompanyHistory / CompanyTiming / CompanyEvents: records the
    keyword arguments it was handed and reports a distinctive exit code,
    render() and to_dict() so stdout and rc are fully attributable to it."""

    def __init__(self, exit_code=7, **kw):
        self.kw = dict(kw)
        self.exit_code = exit_code

    def render(self):
        return "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2"

    def to_dict(self):
        return {"fake": True, "n_products": len(self.kw.get("products", ()))}


class _FakeCfg:
    def __init__(self, path):
        self.path = path


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return str(p)


def _run(cli_name, dispatch_path, *, as_json=False, limit=None, kind=None):
    """Drive one verb through its PUBLIC keyword parameters (which pins the
    parameter names), returning (rc, stdout+stderr)."""
    fn = getattr(foundry, cli_name)
    out, err = io.StringIO(), io.StringIO()
    kwargs = {"as_json": as_json}
    if cli_name in ("company_history_cli", "company_timing_cli"):
        kwargs["limit"] = limit
    elif cli_name == "company_events_cli":
        kwargs["limit"] = limit
        kwargs["kind"] = kind
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(dispatch_path, **kwargs)
    return rc, out.getvalue() + err.getvalue()


def _patch_seams(monkeypatch, gather, summarize, *, gather_impl=None,
                 load_impl=None, exit_code=7):
    """Patch load_config + this verb's gather and summarize seams BY BARE NAME
    on the `foundry` module object, so a patch only bites if the body resolves
    the name as a module global at CALL time. Returns the recorder."""
    rec: dict = {"loaded": [], "gathered": [], "summ": []}

    def fake_load(path):
        rec["loaded"].append(path)
        if load_impl is not None:
            return load_impl(path)
        return _FakeCfg(path)

    def fake_gather(cfg, *extra):
        rec["gathered"].append((getattr(cfg, "path", cfg), extra))
        if gather_impl is not None:
            return gather_impl(cfg, *extra)
        return ("GATHERED", getattr(cfg, "path", cfg))

    def fake_summ(**kw):
        rec["summ"].append(kw)
        return _FakeSummary(exit_code=exit_code, **kw)

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, gather, fake_gather)
    monkeypatch.setattr(foundry, summarize, fake_summ)
    return rec


def _fn_names(fn):
    """co_names of fn plus every nested code object (tests/ convention)."""
    stack, seen, names = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, types.CodeType):
                stack.append(c)
    return names


def _exec_line_count(fn):
    """How many distinct SOURCE lines carry executable bytecode -- a thin
    wrapper has a handful, a full re-implementation has dozens. Derived from the
    code object, never from the file's text."""
    return len({ln for _s, _e, ln in fn.__code__.co_lines() if ln is not None})


def _module_level_functions():
    return {k for k, v in vars(foundry).items() if isinstance(v, types.FunctionType)}


def _shared_body_name():
    """DERIVE (never hard-code) the single module-level function every one of
    the nine verbs delegates to."""
    mod_fns = _module_level_functions()
    common = None
    for cli_name in NINE:
        cand = _fn_names(getattr(foundry, cli_name)) & mod_fns
        common = cand if common is None else (common & cand)
    return common or set()


def _bytes_snapshot(root):
    root = pathlib.Path(root)
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _stat_snapshot(root):
    """Non-recursive (name -> size, mtime_ns) of one directory."""
    out = {}
    for p in sorted(pathlib.Path(root).iterdir()):
        if p.is_file():
            st = p.stat()
            out[p.name] = (st.st_size, st.st_mtime_ns)
    return out


# ==========================================================================
# Behavior 1 -- the shared body grows TWO optional pass-through parameters and
# every existing 4-argument call is unchanged
# ==========================================================================
def test_b01_shared_body_takes_two_new_optional_passthrough_params():
    shared = _shared_body_name()
    assert len(shared) == 1, \
        f"all nine verbs must delegate to exactly ONE shared body, found {sorted(shared)}"
    fn = getattr(foundry, next(iter(shared)))
    sig = inspect.signature(fn)
    params = list(sig.parameters)
    assert params[:4] == ["dispatch_path", "as_json", "gather", "summarize"], \
        f"the four incumbent parameters must keep their names and order: {sig}"
    assert len(params) == 6, \
        f"exactly two NEW pass-through parameters expected, got {sig}"
    extra_pos, extra_kw = params[4], params[5]
    assert sig.parameters[extra_pos].default == (), \
        f"{extra_pos} must default to an empty tuple: {sig}"
    assert sig.parameters[extra_kw].default in (None, {}), \
        f"{extra_kw} must default to empty/None: {sig}"
    for name in (extra_pos, extra_kw):
        assert sig.parameters[name].kind is not inspect.Parameter.KEYWORD_ONLY, \
            f"{name} must stay POSITIONAL_OR_KEYWORD, not KEYWORD_ONLY: {sig}"
        assert sig.parameters[name].default is not inspect.Parameter.empty, \
            f"{name} must be OPTIONAL: {sig}"


def test_b01_four_argument_call_of_the_shared_body_is_unchanged(tmp_path, monkeypatch):
    """A direct 4-positional-argument call still gathers, summarizes, prints
    render() and returns the summary's exit code -- no extra args required."""
    shared = getattr(foundry, next(iter(_shared_body_name())))
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}], name="four-arg.json")
    monkeypatch.setattr(foundry, "load_config", lambda path: _FakeCfg(path))
    seen = {"gather": [], "summ": []}

    def gather(cfg, *extra):
        seen["gather"].append((getattr(cfg, "path", cfg), extra))
        return ("G", getattr(cfg, "path", cfg))

    def summarize(**kw):
        seen["summ"].append(kw)
        return _FakeSummary(exit_code=9, **kw)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = shared(d, False, gather, summarize)
    assert rc == 9, f"4-argument call must return the summary's exit_code, got {rc}"
    assert out.getvalue() == "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2\n", \
        f"4-argument call must print render(): {out.getvalue()!r}"
    assert seen["gather"] and seen["gather"][0][1] == (), \
        f"with no extra args the gather seam takes cfg only: {seen['gather']!r}"
    assert len(seen["summ"]) == 1 and set(seen["summ"][0]) == BASE_SUMM_KEYS, \
        f"with no extra kwargs the summarize seam gets exactly the four base keys: {seen['summ']!r}"
    assert seen["summ"][0]["errors"] == () and seen["summ"][0]["products"] == (("G", "ca"),), \
        f"the 4-argument path must be error-free and forward the gathered value: {seen['summ']!r}"


def test_b01_the_six_iter146_wrappers_are_unchanged(tmp_path, monkeypatch):
    """The six 4-argument callers still print the same report and return the
    same exit code with the same seams patched."""
    for cli_name, gather, summarize in SIX:
        d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}],
                            name=f"six-{cli_name}.json")
        with monkeypatch.context() as mp:
            rec = _patch_seams(mp, gather, summarize, exit_code=13)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = getattr(foundry, cli_name)(d, as_json=False)
        assert rc == 13, f"{cli_name} must still return the patched summary's exit_code, got {rc}"
        assert out.getvalue() == "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2\n", \
            f"{cli_name} stdout changed: {out.getvalue()!r}"
        assert rec["gathered"] == [("ca", ())], \
            f"{cli_name} must still call its gather seam with cfg ONLY: {rec['gathered']!r}"
        assert len(rec["summ"]) == 1 and set(rec["summ"][0]) == BASE_SUMM_KEYS, \
            f"{cli_name} summarize kwargs changed: {rec['summ']!r}"


# ==========================================================================
# Behavior 2 -- public name / signature / defaults / docstring preserved, and
# both seams still resolve by BARE name at CALL time
# ==========================================================================
def test_b02_three_verbs_keep_name_signature_defaults_and_docstring():
    for cli_name, gather, summarize, params in STRAGGLERS:
        fn = getattr(foundry, cli_name, None)
        assert isinstance(fn, types.FunctionType), \
            f"{cli_name} must remain a public module-level function of foundry"
        assert "." not in fn.__qualname__, \
            f"{cli_name} must stay module-level, got qualname {fn.__qualname__!r}"
        sig = inspect.signature(fn)
        assert tuple(sig.parameters) == params, f"{cli_name} signature changed: {sig}"
        for name in params[1:]:
            assert sig.parameters[name].default is not inspect.Parameter.empty, \
                f"{cli_name}.{name} lost its default: {sig}"
        assert sig.parameters["as_json"].default is False, \
            f"{cli_name} as_json default changed: {sig}"
        assert fn.__closure__ is None, \
            f"{cli_name} must not close over anything (no def-time seam capture)"
        assert fn.__kwdefaults__ in (None, {}), \
            f"{cli_name} must have no keyword-only defaults: {fn.__kwdefaults__!r}"
        names = _fn_names(fn)
        assert gather in names, f"{cli_name} must reference {gather} by BARE name"
        assert summarize in names, f"{cli_name} must reference {summarize} by BARE name"


def test_b02_nine_docstrings_survive_and_stay_distinct():
    docs = {}
    for cli_name in NINE:
        doc = (getattr(foundry, cli_name).__doc__ or "").strip()
        assert len(doc) >= 200, \
            f"{cli_name} docstring shrank to {len(doc)} chars -- per-verb report contract must survive"
        docs[cli_name] = doc
    assert len(set(docs.values())) == len(NINE), \
        "each verb must keep its OWN docstring; duplicates: " + repr(
            sorted(k for k, v in docs.items() if list(docs.values()).count(v) > 1))


@pytest.mark.parametrize("cli_name,gather,summarize,_params", STRAGGLERS)
def test_b02_bare_name_seam_patches_bite(tmp_path, monkeypatch, cli_name, gather,
                                         summarize, _params):
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}], name=f"bare-{cli_name}.json")
    rec = _patch_seams(monkeypatch, gather, summarize,
                       gather_impl=lambda cfg, *e: ("SENTINEL", cfg.path), exit_code=7)
    rc, out = _run(cli_name, d, kind="k", limit=5)
    assert rc == 7, f"{cli_name} must return the PATCHED summarize's exit_code, got {rc}"
    assert out == "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2\n", \
        f"{cli_name} stdout must be the PATCHED summary's render(): {out!r}"
    assert [g[0] for g in rec["gathered"]] == ["ca"], \
        f"{cli_name} did not call the patched {gather} exactly once: {rec['gathered']!r}"
    assert rec["summ"][0]["products"] == (("SENTINEL", "ca"),), \
        f"{cli_name} must forward the PATCHED gather's value: {rec['summ'][0]['products']!r}"


# ==========================================================================
# Behavior 3 -- `limit` reaches EVERY per-product gather call
# ==========================================================================
@pytest.mark.parametrize("cli_name,gather,summarize,_params", STRAGGLERS)
def test_b03_limit_reaches_every_gather_call(tmp_path, monkeypatch, cli_name, gather,
                                             summarize, _params):
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"},
                                   {"name": "b", "config": "cb"}],
                        name=f"limit-{cli_name}.json")
    rec = _patch_seams(monkeypatch, gather, summarize)
    rc, _out = _run(cli_name, d, limit=3, kind="evk")
    assert rc == 7
    assert [g[0] for g in rec["gathered"]] == ["ca", "cb"], \
        f"{cli_name} must gather BOTH enabled work items: {rec['gathered']!r}"
    expected = _expected_gather_extra(cli_name, 3, "evk")
    assert [g[1] for g in rec["gathered"]] == [expected, expected], \
        (f"{cli_name} must hand every gather call {expected!r}; "
         f"got {[g[1] for g in rec['gathered']]!r}")


@pytest.mark.parametrize("cli_name,gather,summarize,_params", STRAGGLERS)
def test_b03_default_limit_none_still_reaches_the_gather_seam(tmp_path, monkeypatch,
                                                             cli_name, gather,
                                                             summarize, _params):
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}], name=f"dflt-{cli_name}.json")
    rec = _patch_seams(monkeypatch, gather, summarize)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = getattr(foundry, cli_name)(d)          # every optional left at default
    assert rc == 7
    assert [g[1] for g in rec["gathered"]] == [_expected_gather_extra(cli_name, None, None)], \
        f"{cli_name} default call passed {rec['gathered']!r}"


# ==========================================================================
# Behavior 4 -- timing still passes threshold=, read at CALL time
# ==========================================================================
def _defect_twin_frozen_default(dispatch_path, limit=None, as_json=False,
                                threshold=foundry.SUITE_SLOW_SECONDS):
    """THE DEFECT TWIN: this captures SUITE_SLOW_SECONDS in a DEFAULT ARGUMENT,
    i.e. at def (import) time. It exists so the control below is two-sided --
    the twin must report the stale value where the shipped verb reports the
    live one."""
    return threshold


def test_b04_timing_threshold_is_read_at_call_time_not_def_time(tmp_path, monkeypatch):
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}], name="thr.json")
    frozen = _defect_twin_frozen_default(d)
    rec = _patch_seams(monkeypatch, "gather_timing", "summarize_company_timing")

    for new_value in (999.5, 42.25):
        monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", new_value)
        rec["summ"].clear()
        rc, _out = _run("company_timing_cli", d, limit=2)
        assert rc == 7
        assert rec["summ"][0].get("threshold") == new_value, \
            ("company_timing_cli must read SUITE_SLOW_SECONDS at CALL time; patched to "
             f"{new_value} but summarize got {rec['summ'][0].get('threshold')!r}")
        # two-sided control: the frozen-default twin CANNOT see the new value
        assert _defect_twin_frozen_default(d) == frozen != new_value, \
            "the defect twin must stay stale -- otherwise this test cannot detect the bug"
    assert foundry.company_timing_cli.__defaults__ == (None, False), \
        ("company_timing_cli must not carry a threshold default argument: "
         f"{foundry.company_timing_cli.__defaults__!r}")


def test_b04_timing_summarize_kwargs_are_exactly_base_plus_threshold(tmp_path, monkeypatch):
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}], name="thrkeys.json")
    rec = _patch_seams(monkeypatch, "gather_timing", "summarize_company_timing")
    rc, _out = _run("company_timing_cli", d)
    assert rc == 7
    assert set(rec["summ"][0]) == BASE_SUMM_KEYS | {"threshold"}, \
        f"company_timing_cli summarize kwargs changed: {sorted(rec['summ'][0])}"


# ==========================================================================
# Behavior 5 -- events passes kind to gather AND kind_filter= to summarize, on
# BOTH the normal and the bad-dispatch-config path
# ==========================================================================
@pytest.mark.parametrize("path_kind", ["success", "error"])
def test_b05_events_kind_reaches_both_seams_on_both_paths(tmp_path, monkeypatch, path_kind):
    if path_kind == "success":
        d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}], name="ev-ok.json")
    else:
        d = str(tmp_path / "ev-missing.json")          # unreadable dispatch
    rec = _patch_seams(monkeypatch, "gather_events", "summarize_company_events", exit_code=4)
    rc, out = _run("company_events_cli", d, kind="release", limit=8)
    assert rc == 4, f"events ({path_kind}) must return the patched summary's exit_code: {rc}"
    assert out == "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2\n", f"events ({path_kind}) stdout: {out!r}"
    assert len(rec["summ"]) == 1, f"events ({path_kind}) must summarize exactly once"
    assert set(rec["summ"][0]) == BASE_SUMM_KEYS | {"kind_filter"}, \
        f"events ({path_kind}) summarize kwargs: {sorted(rec['summ'][0])}"
    assert rec["summ"][0]["kind_filter"] == "release", \
        f"events ({path_kind}) must pass kind_filter=kind: {rec['summ'][0]['kind_filter']!r}"
    if path_kind == "success":
        assert [g[1] for g in rec["gathered"]] == [("release", 8)], \
            f"events must call gather_events(cfg, kind, limit): {rec['gathered']!r}"
    else:
        assert rec["gathered"] == [], "events must not gather when the dispatch config is bad"


# ==========================================================================
# Behavior 6 -- a DISABLED work item is listed by name and never loaded
# ==========================================================================
@pytest.mark.parametrize("cli_name,gather,summarize,_params", STRAGGLERS)
def test_b06_disabled_item_named_and_never_loaded(tmp_path, monkeypatch, cli_name,
                                                  gather, summarize, _params):
    d = _write_dispatch(tmp_path, [{"name": "on", "config": "c-on"},
                                   {"name": "off", "config": "c-off", "enabled": False}],
                        name=f"dis-{cli_name}.json")
    rec = _patch_seams(monkeypatch, gather, summarize)
    rc, _out = _run(cli_name, d, limit=1, kind="k")
    assert rc == 7
    assert rec["summ"][0]["disabled"] == ("off",), \
        f"{cli_name} must record the disabled item BY NAME: {rec['summ'][0]['disabled']!r}"
    assert rec["loaded"] == ["c-on"], \
        f"{cli_name} must never load a disabled item's config: {rec['loaded']!r}"
    assert [g[0] for g in rec["gathered"]] == ["c-on"], \
        f"{cli_name} must never gather a disabled item: {rec['gathered']!r}"


# ==========================================================================
# Behavior 7 -- a bad dispatch path yields ONE report with ONE synthetic error
# ==========================================================================
@pytest.mark.parametrize("bad_kind", ["missing", "not-json", "json-not-object"])
@pytest.mark.parametrize("cli_name,gather,summarize,_params", STRAGGLERS)
def test_b07_bad_dispatch_config_is_a_report_never_a_crash(tmp_path, monkeypatch,
                                                           cli_name, gather, summarize,
                                                           _params, bad_kind):
    p = pathlib.Path(tmp_path) / f"bad-{bad_kind}-{cli_name}.json"
    if bad_kind == "not-json":
        p.write_text("this is not json {{{")
    elif bad_kind == "json-not-object":
        p.write_text(json.dumps(["a", "list", "not", "an", "object"]))
    d = str(p)
    rec = _patch_seams(monkeypatch, gather, summarize, exit_code=3)
    rc, out = _run(cli_name, d, limit=2, kind="k")
    assert rc == 3, f"{cli_name} ({bad_kind}) must return the report's own exit code: {rc}"
    assert out == "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2\n", \
        f"{cli_name} ({bad_kind}) must print exactly ONE report: {out!r}"
    assert len(rec["summ"]) == 1, \
        f"{cli_name} ({bad_kind}) must summarize exactly once: {len(rec['summ'])}"
    kw = rec["summ"][0]
    assert set(kw) == BASE_SUMM_KEYS | _expected_extra_summ_keys(cli_name), \
        (f"{cli_name} ({bad_kind}) must still supply its extra summarize kwargs on the "
         f"error path: {sorted(kw)}")
    assert kw["products"] == () and kw["disabled"] == (), \
        f"{cli_name} ({bad_kind}) must report no products/disabled: {kw!r}"
    errs = kw["errors"]
    assert len(errs) == 1 and len(errs[0]) == 2, \
        f"{cli_name} ({bad_kind}) must record exactly ONE (name, message) error: {errs!r}"
    assert any(d in str(part) for part in errs[0]), \
        f"{cli_name} ({bad_kind}) synthetic error must name the dispatch path: {errs[0]!r}"
    assert rec["loaded"] == [] and rec["gathered"] == [], \
        f"{cli_name} ({bad_kind}) must load/gather nothing: {rec!r}"


# ==========================================================================
# Behavior 8 -- a per-item failure is contained and the roll-up CONTINUES
# ==========================================================================
@pytest.mark.parametrize("failing_seam", ["load_config", "gather"])
@pytest.mark.parametrize("cli_name,gather,summarize,_params", STRAGGLERS)
def test_b08_per_item_error_is_contained_and_rollup_continues(tmp_path, monkeypatch,
                                                              cli_name, gather,
                                                              summarize, _params,
                                                              failing_seam):
    d = _write_dispatch(tmp_path, [{"name": "first", "config": "c1"},
                                   {"name": "second", "config": "c2"}],
                        name=f"err-{failing_seam}-{cli_name}.json")

    def boom_load(path):
        if path == "c1":
            raise RuntimeError("BOOM-LOAD")
        return _FakeCfg(path)

    def boom_gather(cfg, *extra):
        if getattr(cfg, "path", cfg) == "c1":
            raise ValueError("BOOM-GATHER")
        return ("G", cfg.path)

    if failing_seam == "load_config":
        rec = _patch_seams(monkeypatch, gather, summarize, load_impl=boom_load)
        marker = "BOOM-LOAD"
    else:
        rec = _patch_seams(monkeypatch, gather, summarize, gather_impl=boom_gather)
        marker = "BOOM-GATHER"

    rc, out = _run(cli_name, d, limit=1, kind="k")
    assert rc == 7, f"{cli_name} ({failing_seam}) must still return the report's exit code: {rc}"
    assert out == "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2\n", \
        f"{cli_name} ({failing_seam}) must still print ONE report: {out!r}"
    kw = rec["summ"][0]
    errs = kw["errors"]
    assert len(errs) == 1 and errs[0][0] == "first", \
        f"{cli_name} ({failing_seam}) must record the failing item BY NAME: {errs!r}"
    assert marker in str(errs[0][1]), \
        f"{cli_name} ({failing_seam}) must record the exception message: {errs[0]!r}"
    assert len(kw["products"]) == 1, \
        f"{cli_name} ({failing_seam}) must still gather the SECOND item: {kw['products']!r}"
    assert [g[0] for g in rec["gathered"]][-1:] == ["c2"], \
        f"{cli_name} ({failing_seam}) must continue to the second item: {rec['gathered']!r}"


# ==========================================================================
# Behavior 9 -- as_json prints ONE indent=2 document, same rc, and writes
# NOTHING to disk
# ==========================================================================
@pytest.mark.parametrize("cli_name,gather,summarize,_params", STRAGGLERS)
def test_b09_as_json_prints_one_indent2_document_with_the_same_exit_code(
        tmp_path, monkeypatch, cli_name, gather, summarize, _params):
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}], name=f"js-{cli_name}.json")
    rec = _patch_seams(monkeypatch, gather, summarize, exit_code=5)
    rc_text, out_text = _run(cli_name, d, limit=2, kind="k")
    rc_json, out_json = _run(cli_name, d, as_json=True, limit=2, kind="k")
    assert rc_json == rc_text == 5, \
        f"{cli_name} json rc {rc_json} must equal text rc {rc_text}"
    doc = json.loads(out_json)                    # exactly ONE document parses
    assert doc == {"fake": True, "n_products": 1}, \
        f"{cli_name} must print the summary's to_dict(): {doc!r}"
    assert out_json == json.dumps(doc, indent=2) + "\n", \
        f"{cli_name} must print json.dumps(..., indent=2): {out_json!r}"
    assert "FAKE-RENDER-LINE-1" not in out_json, \
        f"{cli_name} must not print render() in json mode: {out_json!r}"
    assert len(rec["summ"]) == 2, "one summarize call per invocation"


@pytest.mark.parametrize("as_json", [False, True])
def test_b09_the_three_verbs_write_nothing_to_disk(tmp_path, monkeypatch, as_json):
    """Byte-exact snapshot of the working tree the verbs run in, plus a
    size+mtime snapshot of the repo root, before and after all three verbs."""
    work = pathlib.Path(tmp_path) / "work"
    work.mkdir()
    dispatches = {}
    for cli_name, _g, _s, _p in STRAGGLERS:
        dispatches[cli_name] = _write_dispatch(work, [{"name": "a", "config": "ca"}],
                                               name=f"snap-{cli_name}.json")
    monkeypatch.chdir(work)                       # any relative write lands HERE
    before_tree = _bytes_snapshot(work)
    before_root = _stat_snapshot(_ROOT)
    for cli_name, gather, summarize, _p in STRAGGLERS:
        with monkeypatch.context() as mp:
            _patch_seams(mp, gather, summarize)
            rc, _out = _run(cli_name, dispatches[cli_name], as_json=as_json,
                            limit=2, kind="k")
        assert rc == 7
    assert _bytes_snapshot(work) == before_tree, \
        "the three roll-up verbs must write NOTHING to the tree they run in"
    assert _stat_snapshot(_ROOT) == before_root, \
        "the three roll-up verbs must not touch any file in the repo root"


# ==========================================================================
# Behavior 10 -- import stays clean, all nine names survive, and the three
# stragglers are now THIN wrappers (the observable form of the line deletion)
# ==========================================================================
def test_b10_import_is_clean_and_nine_names_survive():
    proc = subprocess.run([sys.executable, "-c",
                           "import foundry, dispatcher; "
                           "print(sorted(n for n in vars(foundry) "
                           "if n.startswith('company_') and n.endswith('_cli')))"],
                          cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"import foundry, dispatcher failed: {proc.stderr}"
    printed = proc.stdout.strip()
    for name in NINE:
        assert repr(name) in printed, f"{name} missing from a fresh import: {printed}"


def test_b10_three_stragglers_are_thin_wrappers_like_the_iter146_six():
    """Derived, not hard-coded: each straggler's executable-line count must be
    within a few lines of the THICKEST already-collapsed iter-146 wrapper."""
    six_counts = {n: _exec_line_count(getattr(foundry, n)) for n, _g, _s in SIX}
    ceiling = max(six_counts.values()) + 4        # +4: threshold read / extra args
    for cli_name, _g, _s, _p in STRAGGLERS:
        got = _exec_line_count(getattr(foundry, cli_name))
        assert got <= ceiling, (
            f"{cli_name} still has {got} executable lines; the collapsed iter-146 "
            f"wrappers have {six_counts} so the ceiling is {ceiling} -- it is not a "
            "thin wrapper yet")


def test_b10_every_straggler_delegates_to_the_one_shared_body():
    shared = _shared_body_name()
    assert len(shared) == 1, f"expected exactly one shared body, got {sorted(shared)}"
    name = next(iter(shared))
    for cli_name, _g, _s, _p in STRAGGLERS:
        assert name in _fn_names(getattr(foundry, cli_name)), \
            f"{cli_name} must delegate to {name}"
