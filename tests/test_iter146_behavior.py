"""Black-box behaviour tests for iter 146 -- the six byte-identical
`company_*_cli` roll-up verbs collapse onto ONE shared module-level body while
every OBSERVABLE behaviour is unchanged.

Under test (roadmap item (i), re-scoped to the six exact-skeleton members):
`company_status_cli`, `company_weak_tests_cli`, `company_constant_asserts_cli`,
`company_skipped_tests_cli`, `company_test_quality_cli`,
`company_config_lint_cli` -- each `(dispatch_path: str, as_json: bool = False)
-> int`, each driving its OWN `gather_*` + `summarize_company*` seam pair plus
the shared `load_config` / `parse_dispatch_work_items` seams, all BY BARE
MODULE NAME at CALL time.

THE NAMING TRAP (spec measurement, re-asserted here): the status verb's
summarize seam is the BARE name `summarize_company`, NOT
`summarize_company_status`, so no seam may be derived from the verb name.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-146 PM
spec's Expected Behaviors (1-10), the tests/ conventions (esp.
tests/test_iter59_behavior.py and tests/test_iter61_behavior.py -- the
structural-mirror company roll-ups, and tests/test_iter30_behavior.py for the
`parse_dispatch_work_items` triple contract), and the product's OWN OBSERVABLE
behaviour (driving the six public callables and `main()` with scripted seams and
reading their rc / stdout / public runtime objects). foundry.py's source was
NOT read, no `inspect.getsource` is used anywhere in this file, and neither the
engineer's nor the reviewer's notes nor any `git diff` was consulted.
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
import dispatcher  # noqa: E402

# (cli name, gather seam, summarize seam, argparse subcommand)
VERBS: tuple[tuple[str, str, str, str], ...] = (
    ("company_status_cli", "gather_status", "summarize_company", "company-status"),
    ("company_weak_tests_cli", "gather_weak_tests",
     "summarize_company_weak_tests", "company-weak-tests"),
    ("company_constant_asserts_cli", "gather_constant_asserts",
     "summarize_company_constant_asserts", "company-constant-asserts"),
    ("company_skipped_tests_cli", "gather_skipped_tests",
     "summarize_company_skipped_tests", "company-skipped-tests"),
    ("company_test_quality_cli", "gather_test_quality",
     "summarize_company_test_quality", "company-test-quality"),
    ("company_config_lint_cli", "gather_config_lint",
     "summarize_company_config_lint", "company-lint-config"),
)

_CLI_NAMES = tuple(v[0] for v in VERBS)
# the four keyword-only fields the shared body must hand the summarize seam
_SUMM_KEYS = {"dispatch_path", "products", "disabled", "errors"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class _FakeSummary:
    """A stand-in for the six real Company* summaries: records the keyword
    arguments the shared body passed, and reports a distinctive exit code /
    render() / to_dict() so stdout and rc are fully attributable to it."""

    def __init__(self, exit_code=7, **kw):
        self.kw = dict(kw)
        self.exit_code = exit_code

    def render(self):
        return "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2"

    def to_dict(self):
        return {"fake": True, "n_products": len(self.kw.get("products", ()))}


class _FakeCfg:
    """A stand-in product config: carries only the path it was loaded from."""

    def __init__(self, path):
        self.path = path


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return str(p)


def _run(cli_name, dispatch_path, as_json=False):
    """Drive one verb directly, returning (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = getattr(foundry, cli_name)(dispatch_path, as_json=as_json)
    return rc, out.getvalue() + err.getvalue()


def _patch_seams(monkeypatch, gather, summarize, *, gather_impl=None,
                 load_impl=None, exit_code=7):
    """Patch load_config + this verb's gather seam + this verb's summarize seam
    BY BARE NAME, and return the recorder dict. Every patch is installed on the
    `foundry` module object, so it only bites if the body resolves the name as a
    module global at CALL time."""
    rec: dict = {"loaded": [], "gathered": [], "summ": []}

    def fake_load(path):
        rec["loaded"].append(path)
        if load_impl is not None:
            return load_impl(path)
        return _FakeCfg(path)

    def fake_gather(cfg):
        rec["gathered"].append(getattr(cfg, "path", cfg))
        if gather_impl is not None:
            return gather_impl(cfg)
        return ("GATHERED", getattr(cfg, "path", cfg))

    def fake_summ(**kw):
        rec["summ"].append(kw)
        return _FakeSummary(exit_code=exit_code, **kw)

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, gather, fake_gather)
    monkeypatch.setattr(foundry, summarize, fake_summ)
    return rec


def _fn_names(fn):
    """co_names of fn plus every nested code object (the tests/ convention from
    tests/test_iter59_behavior.py's `_fn_names_consts`)."""
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


def _nested_code_objects(fn):
    return [c.co_name for c in fn.__code__.co_consts if isinstance(c, types.CodeType)]


def _module_level_functions():
    return {k for k, v in vars(foundry).items() if isinstance(v, types.FunctionType)}


def _shared_body_names():
    """DERIVE (never hard-code) the module-level function(s) every one of the six
    verbs references -- the shared body must be exactly one such name."""
    mod_fns = _module_level_functions()
    common = None
    for cli_name, _g, _s, _sub in VERBS:
        cand = _fn_names(getattr(foundry, cli_name)) & mod_fns
        common = cand if common is None else (common & cand)
    return common or set()


def _snapshot(root):
    return {str(p.relative_to(root)): p.stat().st_size
            for p in sorted(pathlib.Path(root).rglob("*")) if p.is_file()}


# ==========================================================================
# Behavior 1 -- public name, exact signature, non-empty per-verb docstring
# ==========================================================================
def test_b01_six_verbs_keep_name_signature_and_docstring():
    for cli_name, _g, _s, _sub in VERBS:
        fn = getattr(foundry, cli_name, None)
        assert isinstance(fn, types.FunctionType), \
            f"{cli_name} must remain a public module-level function of foundry"
        assert "." not in fn.__qualname__, \
            f"{cli_name} must stay module-level, got qualname {fn.__qualname__!r}"
        sig = inspect.signature(fn)
        assert list(sig.parameters) == ["dispatch_path", "as_json"], \
            f"{cli_name} signature changed: {sig}"
        assert sig.parameters["as_json"].default is False, \
            f"{cli_name} as_json default changed: {sig}"
        assert (fn.__doc__ or "").strip(), f"{cli_name} lost its docstring"


def test_b01_per_verb_docstrings_survive_and_stay_distinct():
    """The six docstrings must NOT be collapsed onto one shared docstring."""
    docs = {}
    for cli_name, _g, _s, _sub in VERBS:
        doc = (getattr(foundry, cli_name).__doc__ or "").strip()
        assert len(doc) >= 200, \
            f"{cli_name} docstring shrank to {len(doc)} chars -- per-verb docs must survive"
        docs[cli_name] = doc
    assert len(set(docs.values())) == len(VERBS), \
        "each verb must keep its OWN docstring; duplicates found: " + repr(
            sorted(k for k, v in docs.items()
                   if list(docs.values()).count(v) > 1))


# ==========================================================================
# Behavior 2 -- each verb's gather seam is patchable (resolved at CALL time)
# ==========================================================================
def test_b02_gather_seam_monkeypatch_takes_effect_for_all_six(tmp_path, monkeypatch):
    for cli_name, gather, summarize, _sub in VERBS:
        d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}],
                            name=f"{cli_name}.json")
        with monkeypatch.context() as mp:
            rec = _patch_seams(mp, gather, summarize,
                               gather_impl=lambda cfg: ("SENTINEL", cfg.path))
            rc, _out = _run(cli_name, d)
        assert rc == 7, f"{cli_name} must return the summary's exit_code, got {rc}"
        assert rec["gathered"] == ["ca"], \
            f"{cli_name} did not call the patched {gather} exactly once: {rec['gathered']}"
        assert rec["summ"] and rec["summ"][0]["products"] == (("SENTINEL", "ca"),), \
            (f"{cli_name} must forward the PATCHED {gather}'s return value; "
             f"got {rec['summ'][0]['products'] if rec['summ'] else None!r}")


def test_b02_no_seam_captured_at_def_time_or_as_a_default_argument():
    """A wrapper that froze a seam in a default arg or a closure cell would be
    unpatchable, so neither is allowed."""
    for cli_name, gather, summarize, _sub in VERBS:
        fn = getattr(foundry, cli_name)
        assert fn.__defaults__ == (False,), \
            f"{cli_name} must have exactly one default (as_json=False), got {fn.__defaults__!r}"
        assert fn.__kwdefaults__ in (None, {}), \
            f"{cli_name} must have no keyword-only defaults, got {fn.__kwdefaults__!r}"
        assert fn.__closure__ is None, \
            f"{cli_name} must not close over anything (no def-time seam capture)"
        names = _fn_names(fn)
        assert gather in names, f"{cli_name} must reference {gather} by BARE name"
        assert summarize in names, f"{cli_name} must reference {summarize} by BARE name"


# ==========================================================================
# Behavior 3 -- each verb's summarize seam is patchable on BOTH paths
# ==========================================================================
@pytest.mark.parametrize("path_kind", ["error", "success"])
def test_b03_summarize_seam_patch_bites_on_error_and_success_paths(
        tmp_path, monkeypatch, path_kind):
    for cli_name, gather, summarize, _sub in VERBS:
        if path_kind == "error":
            dispatch = str(tmp_path / f"missing-{cli_name}.json")   # unreadable
        else:
            dispatch = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}],
                                       name=f"ok-{cli_name}.json")
        with monkeypatch.context() as mp:
            rec = _patch_seams(mp, gather, summarize, exit_code=11)
            rc, out = _run(cli_name, dispatch)
        assert rc == 11, \
            f"{cli_name} ({path_kind} path) must return the PATCHED {summarize}'s exit_code"
        assert out == "FAKE-RENDER-LINE-1\nFAKE-RENDER-LINE-2\n", \
            f"{cli_name} ({path_kind} path) stdout must be the PATCHED summary's render(): {out!r}"
        assert len(rec["summ"]) == 1, \
            f"{cli_name} must call {summarize} exactly once on the {path_kind} path"
        assert set(rec["summ"][0]) == _SUMM_KEYS, \
            f"{cli_name} must pass exactly {_SUMM_KEYS} to {summarize}, got {set(rec['summ'][0])}"
        if path_kind == "error":
            errs = rec["summ"][0]["errors"]
            assert len(errs) == 1 and errs[0][0] == dispatch, \
                f"{cli_name} must record the unreadable dispatch path in errors: {errs!r}"
            assert rec["summ"][0]["products"] == () and rec["summ"][0]["disabled"] == ()


def test_b03_status_verb_summarize_seam_is_the_bare_name(tmp_path, monkeypatch):
    """THE NAMING TRAP: patching `summarize_company` (not
    `summarize_company_status`) must bite -- so no seam is name-derived."""
    assert not hasattr(foundry, "summarize_company_status"), \
        "a `summarize_company_status` alias would hide the naming trap this asserts"
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}], name="trap.json")
    with monkeypatch.context() as mp:
        rec = _patch_seams(mp, "gather_status", "summarize_company", exit_code=5)
        rc, out = _run("company_status_cli", d)
    assert rc == 5 and out.startswith("FAKE-RENDER-LINE-1"), \
        "patching the BARE name summarize_company must control company_status_cli"
    assert len(rec["summ"]) == 1


# ==========================================================================
# Behavior 4 -- load_config and parse_dispatch_work_items patches still bite
# ==========================================================================
def test_b04_load_config_and_parse_dispatch_work_items_patches_bite(tmp_path, monkeypatch):
    for cli_name, gather, summarize, _sub in VERBS:
        # a dispatch file with NO work_items: only a patched parser can yield one
        p = pathlib.Path(tmp_path) / f"pdw-{cli_name}.json"
        p.write_text(json.dumps({"unrelated": "key"}))
        with monkeypatch.context() as mp:
            rec = _patch_seams(mp, gather, summarize)
            mp.setattr(foundry, "parse_dispatch_work_items",
                       lambda dispatch: (("scripted", "cfg-from-patched-parser", True),))
            rc, _out = _run(cli_name, str(p))
        assert rc == 7, f"{cli_name} must reach the patched summarize seam"
        assert rec["loaded"] == ["cfg-from-patched-parser"], \
            (f"{cli_name} must call BOTH parse_dispatch_work_items and load_config by "
             f"bare name at call time; load_config saw {rec['loaded']!r}")
        assert rec["gathered"] == ["cfg-from-patched-parser"]


def test_b04_foundry_placeholder_in_a_work_item_config_is_substituted(tmp_path, monkeypatch):
    """`{FOUNDRY}` in a work item's config path is expanded to the foundry
    checkout root before load_config sees it (shared-body behaviour)."""
    d = _write_dispatch(tmp_path, [{"name": "a", "config": "{FOUNDRY}/x/y.json"}],
                        name="subst.json")
    with monkeypatch.context() as mp:
        rec = _patch_seams(mp, "gather_status", "summarize_company")
        _run("company_status_cli", d)
    assert rec["loaded"] and "{FOUNDRY}" not in rec["loaded"][0], \
        f"the {{FOUNDRY}} placeholder must be substituted, got {rec['loaded']!r}"
    assert rec["loaded"][0].endswith("/x/y.json")


# ==========================================================================
# Behavior 5 -- exit codes unchanged across four scripted inputs
# ==========================================================================
def test_b05_exit_codes_unreadable_notobject_and_no_enabled_items(tmp_path):
    """Real summarize seams: unreadable -> 1, not-a-JSON-object -> 1,
    no ENABLED items -> 2. Asserted identically for all six verbs."""
    missing = str(tmp_path / "does-not-exist.json")
    notobj = pathlib.Path(tmp_path) / "notobj.json"
    notobj.write_text("[1, 2, 3]")
    empty = _write_dispatch(tmp_path, [], name="empty.json")
    all_disabled = _write_dispatch(
        tmp_path, [{"name": "x", "config": "cx", "enabled": False}], name="disabled.json")
    cases = (("unreadable", missing, 1), ("not-an-object", str(notobj), 1),
             ("no-work-items", empty, 2), ("all-disabled", all_disabled, 2))
    for cli_name, _g, _s, sub in VERBS:
        for label, dispatch, want in cases:
            rc, out = _run(cli_name, dispatch)
            assert rc == want, f"{cli_name} on {label} must exit {want}, got {rc}\n{out}"
            assert out.splitlines()[0] == f"foundry {sub}", \
                f"{cli_name} must keep its own header line `foundry {sub}`: {out.splitlines()[:1]}"
            assert any(ln.strip().lower().startswith("verdict:")
                       for ln in out.splitlines()), \
                f"{cli_name} on {label} must still print a verdict line:\n{out}"
            rc_j, out_j = _run(cli_name, dispatch, as_json=True)
            doc = json.loads(out_j)
            assert rc_j == want == doc["exit_code"], \
                f"{cli_name} --json exit_code must agree with rc on {label}"


def test_b05_enabled_items_return_whatever_the_summary_reports(tmp_path, monkeypatch):
    for cli_name, gather, summarize, _sub in VERBS:
        d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}],
                            name=f"rc-{cli_name}.json")
        for want in (0, 1, 2, 9):
            with monkeypatch.context() as mp:
                _patch_seams(mp, gather, summarize, exit_code=want)
                rc, _out = _run(cli_name, d)
            assert rc == want, f"{cli_name} must return the summary's exit_code {want}, got {rc}"


# ==========================================================================
# Behavior 6 -- a raising item is recorded and the roll-up CONTINUES
# ==========================================================================
def test_b06_raising_load_or_gather_is_recorded_and_rollup_continues(tmp_path, monkeypatch):
    items = [{"name": "a", "config": "ca"},
             {"name": "b", "config": "cb"},            # gather raises
             {"name": "c", "config": "cc", "enabled": False},   # disabled
             {"name": "d", "config": "cd"}]            # load_config raises
    for cli_name, gather, summarize, _sub in VERBS:
        d = _write_dispatch(tmp_path, items, name=f"err-{cli_name}.json")

        def load_impl(path):
            if path == "cd":
                raise ValueError("boom-load")
            return _FakeCfg(path)

        def gather_impl(cfg):
            if cfg.path == "cb":
                raise RuntimeError("boom-gather")
            return ("G", cfg.path)

        with monkeypatch.context() as mp:
            rec = _patch_seams(mp, gather, summarize,
                               gather_impl=gather_impl, load_impl=load_impl)
            try:
                rc, _out = _run(cli_name, d)
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"{cli_name} must not let an item exception escape: {exc!r}")
        kw = rec["summ"][0]
        assert kw["products"] == (("G", "ca"),), \
            f"{cli_name} must keep the healthy item and continue: {kw['products']!r}"
        assert kw["disabled"] == ("c",), \
            f"{cli_name} must record the DISABLED item by name: {kw['disabled']!r}"
        assert "cc" not in rec["loaded"], \
            f"{cli_name} must never load a disabled item's config: {rec['loaded']!r}"
        names = [e[0] for e in kw["errors"]]
        assert names == ["b", "d"], \
            f"{cli_name} must record BOTH raising items, in order: {kw['errors']!r}"
        blob = " ".join(str(e[1]) for e in kw["errors"])
        assert "boom-gather" in blob and "boom-load" in blob, \
            f"{cli_name} must record each exception's message: {kw['errors']!r}"
        assert rc == 7


# ==========================================================================
# Behavior 7 -- stdout / --json shape, and ONE shared print path
# ==========================================================================
def test_b07_human_stdout_is_render_and_json_is_one_indent2_document(tmp_path, monkeypatch):
    for cli_name, gather, summarize, _sub in VERBS:
        d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"}],
                            name=f"out-{cli_name}.json")
        with monkeypatch.context() as mp:
            _patch_seams(mp, gather, summarize)
            _rc, human = _run(cli_name, d)
            _rcj, js = _run(cli_name, d, as_json=True)
        assert human == _FakeSummary().render() + "\n", \
            f"{cli_name} human stdout must be exactly render() + newline: {human!r}"
        want = json.dumps({"fake": True, "n_products": 1}, indent=2) + "\n"
        assert js == want, f"{cli_name} --json stdout must be one indent=2 document: {js!r}"
        # exactly ONE document -- a second would make this raise
        json.loads(js)


def test_b07_all_six_emit_byte_identical_output_on_identical_scripted_seams(
        tmp_path, monkeypatch):
    """The six share ONE print path, so with identical scripted seam outputs
    their stdout must be byte-identical (human AND --json)."""
    seen: dict[str, tuple[str, str, int]] = {}
    for cli_name, gather, summarize, _sub in VERBS:
        d = _write_dispatch(tmp_path, [{"name": "a", "config": "ca"},
                                       {"name": "z", "config": "cz", "enabled": False}],
                            name=f"same-{cli_name}.json")
        with monkeypatch.context() as mp:
            _patch_seams(mp, gather, summarize, exit_code=4)
            rc, human = _run(cli_name, d)
            _rcj, js = _run(cli_name, d, as_json=True)
        seen[cli_name] = (human, js, rc)
    distinct = set(seen.values())
    assert len(distinct) == 1, \
        "all six verbs must share one print path; divergence: " + repr(
            {k: v for k, v in seen.items() if v != next(iter(distinct))})


# ==========================================================================
# Behavior 8 -- the verbs write nothing to disk
# ==========================================================================
def test_b08_no_verb_writes_anything_to_disk(tmp_path, monkeypatch):
    work = pathlib.Path(tmp_path) / "work"
    work.mkdir()
    d = _write_dispatch(work, [{"name": "a", "config": "ca"}], name="d.json")
    monkeypatch.chdir(work)          # any relative write would land here
    before_tmp = _snapshot(work)
    before_root = sorted(p.name for p in _ROOT.iterdir())
    for cli_name, gather, summarize, _sub in VERBS:
        with monkeypatch.context() as mp:
            _patch_seams(mp, gather, summarize)
            _run(cli_name, d)
            _run(cli_name, d, as_json=True)
        _run(cli_name, str(work / "nope.json"))       # real summarize, error path
    assert _snapshot(work) == before_tmp, \
        f"a verb wrote to disk: {set(_snapshot(work)) ^ set(before_tmp)!r}"
    assert sorted(p.name for p in _ROOT.iterdir()) == before_root, \
        "a verb created an entry in the repo root"


# ==========================================================================
# Behavior 9 -- main() routing and --help still list all six
# ==========================================================================
def test_b09_main_routes_each_subcommand_to_its_verb(monkeypatch):
    for cli_name, _g, _s, sub in VERBS:
        calls: list = []
        with monkeypatch.context() as mp:
            mp.setattr(foundry, cli_name,
                       lambda dispatch_path, as_json=False: (
                           calls.append((dispatch_path, as_json)), 42)[1])
            rc = foundry.main([sub, "--config", "D.json"])
            rc_j = foundry.main([sub, "--config", "D.json", "--json"])
        assert (rc, rc_j) == (42, 42), f"main() must return {cli_name}'s exit code"
        assert calls == [("D.json", False), ("D.json", True)], \
            f"main() must route {sub} -> {cli_name}(dispatch_path, as_json): {calls!r}"


def test_b09_help_still_lists_all_six_subcommands():
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        with pytest.raises(SystemExit):
            foundry.main(["--help"])
    text = out.getvalue()
    for _c, _g, _s, sub in VERBS:
        assert sub in text, f"`foundry --help` must still list {sub}"


# ==========================================================================
# Behavior 10 -- ONE module-level shared body behind six thin wrappers
# ==========================================================================
def test_b10_exactly_one_shared_module_level_body_backs_all_six():
    shared = _shared_body_names()
    assert len(shared) == 1, \
        ("the six verbs must delegate to EXACTLY ONE common module-level function; "
         f"derived candidates: {sorted(shared)}")
    name = next(iter(shared))
    body = getattr(foundry, name)
    assert isinstance(body, types.FunctionType)
    assert "." not in body.__qualname__, \
        f"the shared body must be MODULE-LEVEL, not nested: qualname {body.__qualname__!r}"
    assert body.__module__ == "foundry"
    # the shared body must not be one of the six verbs (no verb chaining)
    assert name not in _CLI_NAMES, "a verb must not be the shared body of the others"
    for cli_name, _g, _s, _sub in VERBS:
        others = set(_CLI_NAMES) - {cli_name}
        assert not (_fn_names(getattr(foundry, cli_name)) & others), \
            f"{cli_name} must not call a sibling verb"


def test_b10_wrappers_are_thin_and_hold_no_duplicated_body():
    """Each wrapper is a delegation, not a copy: no nested code objects and a
    tiny code size (a 36-line roll-up body cannot fit in this budget)."""
    for cli_name, _g, _s, _sub in VERBS:
        fn = getattr(foundry, cli_name)
        assert _nested_code_objects(fn) == [], \
            f"{cli_name} must hold no nested code object (comprehension/closure)"
        size = len(fn.__code__.co_code)
        assert size <= 256, \
            f"{cli_name} is not a thin wrapper: {size} bytes of bytecode"
        # a thin wrapper references only the shared body + its two seams
        assert len(_fn_names(fn)) <= 4, \
            f"{cli_name} references too many globals to be a delegation: {sorted(_fn_names(fn))}"


# ==========================================================================
# Acceptance -- both modules still import in a clean interpreter
# ==========================================================================
def test_acceptance_foundry_and_dispatcher_still_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"
    assert dispatcher is not None
