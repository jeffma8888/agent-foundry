"""Black-box behaviour tests for iter 362 -- `scout-plan` gains an OPTIONAL
`--config` door so the only verb that previews a per-product pipeline decision
resolves `dual_pm_scouts` from that product's config instead of answering SINGLE
for every product on disk.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-9 + the Acceptance Criteria) and the product's own OBSERVABLE
behaviour only -- running the CLI and driving its PUBLIC runtime interface. The
implementation source (how the door, the loader guard or the resolver are
coded), the engineer's and reviewer's notes, and `git diff` were NOT read.
Every functional check drives the public entry point `foundry.main([...])`, the
public pure helper `foundry.resolve_dual_pm_scouts`, the public dataclass
`foundry.ProductConfig` and the public seam `foundry.load_config`; the resolver
was LOCATED by a runtime `dir(foundry)` scan, never by reading the module text.
The purity proof uses compiled-name introspection (`__code__.co_names`, recursed)
which reads a runtime code object, not source. Fully offline and deterministic:
every config fixture is built inside `tmp_path` (no assertion on the ambient
tree, the iter-154 lesson), and the ONLY subprocess is the import-safety probe.
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


_ROOT = pathlib.Path(foundry.__file__).resolve().parent
FOUNDRY_PY = _ROOT / "foundry.py"
THIS_TEST = pathlib.Path(__file__).resolve()

ITERATION = 362

# The exact pre-iteration bare-invocation output the spec pins in Behavior 1.
BARE_OUTPUT = "scout-plan: dual_pm_scouts=False count=0\nverdict: SINGLE\n"

VERDICT_TOKENS = ("verdict: DUAL", "verdict: SINGLE")

# Every verb the CLI is allowed to expose (iteration 362's Acceptance Criteria
# pinned "the same 57-verb set"; iteration 371 added the 58th verb, `stop`, and
# iteration 373 the 59th, `watchdog-arm`).
# Counted, not enumerated, so the check stays about the INVARIANT rather than
# re-typing a table the census already owns -- keep it an EXACT equality, never
# `>=`, so an accidental verb still reds.
EXPECTED_VERB_COUNT = 60


def _cap(fn):
    """Run a callable, capturing stdout and the exit code (return or SystemExit)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = fn()
        except SystemExit as exc:  # argparse-style exit
            rc = exc.code
    return rc, buf.getvalue()


def _cli(*argv):
    return _cap(lambda: foundry.main(["scout-plan"] + [str(a) for a in argv]))


def _write_cfg(tmp_path, stem, **extra):
    """A minimal but REAL product config on disk, built in tmp_path.

    Only the load-bearing field is toggled by callers; the three fields the
    public `ProductConfig` requires are always present so a fixture fault can
    never masquerade as the exit-2 path under test (Behavior 6).
    """
    payload = {
        "name": "probe-product",
        "repo": "example-repo",
        "allowed_push_repo": "example-repo",
        "branch": "main",
    }
    payload.update(extra)
    path = tmp_path / ("%s.json" % stem)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _product_config_default_dual():
    """The `ProductConfig` default for dual_pm_scouts, read from the PUBLIC
    dataclass rather than hard-coded, because Behavior 5 is *about* that default."""
    return foundry.ProductConfig(
        name="probe-product", repo="example-repo", allowed_push_repo="example-repo"
    ).dual_pm_scouts


def _co_names_deep(fn):
    """Every name fn's compiled code references, recursing into nested code
    objects. Pure runtime introspection -- does NOT read module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _stage_lines(out):
    """The indented per-scout-stage lines of a human plan render."""
    return [
        ln for ln in out.splitlines()
        if ln.startswith(" ") and ln.strip() and not ln.strip().startswith("verdict:")
    ]


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter362_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Behavior 1 -- the bare invocation is UNCHANGED (byte-identical, exit 0)
# ==========================================================================
def test_b1_bare_invocation_byte_identical():
    rc, out = _cli()
    assert rc == 0, rc
    assert out == BARE_OUTPUT, repr(out)


def test_b1_bare_first_and_last_line_exact():
    _rc, out = _cli()
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[0] == "scout-plan: dual_pm_scouts=False count=0", lines[0]
    assert lines[-1] == "verdict: SINGLE", lines[-1]


def test_b1_bare_form_never_reaches_the_top_level_config_load(monkeypatch):
    """AC: the bare form still dispatches BEFORE the top-level `load_config`.

    Observable proof: with the public `load_config` seam replaced by a raiser,
    the bare plan STILL renders and exits 0 -- so nothing on the bare path went
    through it.
    """
    def boom(*_a, **_k):
        raise AssertionError("top-level load_config was reached")

    monkeypatch.setattr(foundry, "load_config", boom)
    rc, out = _cli()
    assert rc == 0, rc
    assert out == BARE_OUTPUT, repr(out)


def test_b1_preexisting_dual_flag_form_unchanged():
    """The pre-iteration `--dual-pm-scouts` form keeps its own contract."""
    rc, out = _cli("--dual-pm-scouts")
    assert rc == 1, rc
    lines = out.splitlines()
    assert lines[0] == "scout-plan: dual_pm_scouts=True count=2", lines[0]
    assert lines[-1] == "verdict: DUAL", lines[-1]


# ==========================================================================
# Behavior 2 -- a dual config FLIPS the verdict
# ==========================================================================
def test_b2_dual_config_flips_verdict(tmp_path):
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    rc, out = _cli("--config", cfg)
    lines = out.splitlines()
    assert lines[0] == "scout-plan: dual_pm_scouts=True count=2", lines[0]
    assert lines[-1] == "verdict: DUAL", lines[-1]
    assert rc == 1, rc


def test_b2_dual_config_renders_one_indented_line_per_stage(tmp_path):
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    _rc, out = _cli("--config", cfg)
    stages = _stage_lines(out)
    assert len(stages) == 2, stages
    lens_a, lens_b = foundry.PM_SCOUT_LENSES
    assert stages[0] == "  pm_scout_a (lens: %s)" % lens_a, stages[0]
    assert stages[1] == "  pm_scout_b (lens: %s)" % lens_b, stages[1]


def test_b2_dual_config_matches_the_explicit_flag_render(tmp_path):
    """The config door must reach the SAME renderer as the flag, not a copy."""
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    rc_cfg, out_cfg = _cli("--config", cfg)
    rc_flag, out_flag = _cli("--dual-pm-scouts")
    assert (rc_cfg, out_cfg) == (rc_flag, out_flag)


def test_b2_preview_verdict_matches_the_pipelines_own_decision(tmp_path):
    """The reason the door exists: for the SAME resolved config value, the
    preview's verdict must equal what the live pipeline decision function
    answers. Checked across the boolean cases AND the junk-typed ones, because
    a preview that only agrees on `true`/`false` is still free to diverge on
    everything an operator can actually type into a JSON file.
    """
    cases = (
        ("true", True), ("false", False), ("null", None),
        ("one", 1), ("zero", 0), ("empty-string", ""), ("false-string", "false"),
    )
    for label, val in cases:
        cfg = _write_cfg(tmp_path, "fidelity-%s" % label, dual_pm_scouts=val)
        rc, out = _cli("--config", cfg)
        resolved = foundry.ProductConfig(
            name="probe-product", repo="example-repo",
            allowed_push_repo="example-repo", dual_pm_scouts=val,
        ).dual_pm_scouts
        plan = foundry.decide_scout_phase(resolved)
        want = "verdict: %s" % ("DUAL" if plan.enabled else "SINGLE")
        assert out.splitlines()[-1] == want, (label, out)
        assert rc == (1 if plan.enabled else 0), (label, rc)
        assert len(_stage_lines(out)) == len(plan.stages), (label, out)


# ==========================================================================
# Behavior 3 -- a single config keeps SINGLE
# ==========================================================================
def test_b3_single_config_keeps_single(tmp_path):
    cfg = _write_cfg(tmp_path, "single", dual_pm_scouts=False)
    rc, out = _cli("--config", cfg)
    assert rc == 0, rc
    assert "dual_pm_scouts=False count=0" in out, out
    assert out.splitlines()[-1] == "verdict: SINGLE", out
    assert _stage_lines(out) == []


def test_b3_single_config_is_byte_identical_to_the_bare_form(tmp_path):
    cfg = _write_cfg(tmp_path, "single", dual_pm_scouts=False)
    rc, out = _cli("--config", cfg)
    assert (rc, out) == (0, BARE_OUTPUT), repr(out)


# ==========================================================================
# Behavior 4 -- the explicit flag WINS over the config
# ==========================================================================
def test_b4_explicit_flag_beats_a_single_config(tmp_path):
    cfg = _write_cfg(tmp_path, "single", dual_pm_scouts=False)
    rc, out = _cli("--dual-pm-scouts", "--config", cfg)
    assert rc == 1, rc
    assert "dual_pm_scouts=True" in out, out
    assert out.splitlines()[-1] == "verdict: DUAL", out


def test_b4_flag_wins_regardless_of_argv_order(tmp_path):
    cfg = _write_cfg(tmp_path, "single", dual_pm_scouts=False)
    a = _cli("--dual-pm-scouts", "--config", cfg)
    b = _cli("--config", cfg, "--dual-pm-scouts")
    assert a == b
    assert a[0] == 1, a


# ==========================================================================
# Behavior 5 -- the door reads the RESOLVED config, not the raw JSON
# ==========================================================================
def test_b5_omitted_key_resolves_from_the_productconfig_default(tmp_path):
    cfg = _write_cfg(tmp_path, "omitted")  # no dual_pm_scouts key at all
    assert "dual_pm_scouts" not in json.loads(cfg.read_text(encoding="utf-8"))
    default = _product_config_default_dual()
    assert default is True, "spec premise: ProductConfig.dual_pm_scouts defaults True"
    rc, out = _cli("--config", cfg)
    assert rc == 1, rc
    assert out.splitlines()[-1] == "verdict: DUAL", out


def test_b5_verdict_tracks_the_resolved_default_not_the_literal_json(tmp_path):
    """A raw-JSON reader would answer SINGLE for an omitted key; the resolved
    reader answers whatever `ProductConfig` itself defaults to."""
    cfg = _write_cfg(tmp_path, "omitted")
    default = _product_config_default_dual()
    rc, out = _cli("--config", cfg)
    expected = "verdict: DUAL" if default else "verdict: SINGLE"
    assert out.splitlines()[-1] == expected, out
    assert rc == (1 if default else 0), rc


# ==========================================================================
# Behavior 6 -- an unreadable --config is a THIRD outcome, never a verdict
# ==========================================================================
def _unreadable_cases(tmp_path):
    missing = tmp_path / "absent.json"
    not_json = tmp_path / "not-json.json"
    not_json.write_text("{not json", encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    a_dir = tmp_path / "a-directory.json"
    a_dir.mkdir()
    unknown = tmp_path / "unknown-key.json"
    unknown.write_text(
        json.dumps({"name": "p", "repo": "r", "allowed_push_repo": "r", "no_such_key": 1}),
        encoding="utf-8",
    )
    return [
        ("missing path", missing),
        ("invalid json", not_json),
        ("empty file", empty),
        ("directory", a_dir),
        ("unknown key", unknown),
    ]


def test_b6_unreadable_config_exits_2_names_the_path_and_emits_no_verdict(tmp_path):
    for label, path in _unreadable_cases(tmp_path):
        rc, out = _cli("--config", path)
        assert rc == 2, "%s: exit %r, expected 2" % (label, rc)
        assert str(path) in out, "%s: message does not name the path: %r" % (label, out)
        for token in VERDICT_TOKENS:
            assert token not in out, "%s: verdict contract polluted: %r" % (label, out)


def test_b6_unreadable_config_never_raises_a_traceback(tmp_path):
    for label, path in _unreadable_cases(tmp_path):
        rc, out = _cli("--config", path)
        assert "Traceback" not in out, "%s: %r" % (label, out)
        assert rc == 2, label


def test_b6_json_channel_also_withholds_a_verdict_on_a_bad_config(tmp_path):
    for label, path in _unreadable_cases(tmp_path):
        rc, out = _cli("--config", path, "--json")
        assert rc == 2, "%s: exit %r" % (label, rc)
        for token in VERDICT_TOKENS:
            assert token not in out, "%s: %r" % (label, out)
        if out.strip().startswith("{"):
            doc = json.loads(out)
            assert doc.get("verdict") is None, "%s: %r" % (label, doc)


def test_b6_config_load_is_self_managed(monkeypatch, tmp_path):
    """AC: the load is self-managed (the `lint-config` idiom), so a load that
    blows up maps to exit 2 with the path named -- never a traceback out of the
    top-level pre-dispatch."""
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)

    def boom(*_a, **_k):
        raise RuntimeError("synthetic load failure")

    monkeypatch.setattr(foundry, "load_config", boom)
    rc, out = _cli("--config", cfg)
    assert rc == 2, rc
    assert str(cfg) in out, out
    assert "Traceback" not in out, out
    for token in VERDICT_TOKENS:
        assert token not in out, out


def test_b6_exit_2_is_distinct_from_both_verdict_codes(tmp_path):
    dual = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    single = _write_cfg(tmp_path, "single", dual_pm_scouts=False)
    codes = {
        _cli("--config", dual)[0],
        _cli("--config", single)[0],
        _cli("--config", tmp_path / "absent.json")[0],
    }
    assert codes == {0, 1, 2}, codes


# ==========================================================================
# Behavior 7 -- the JSON channel carries the RESOLVED value
# ==========================================================================
def test_b7_json_carries_resolved_dual(tmp_path):
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    rc, out = _cli("--config", cfg, "--json")
    assert rc == 1, rc
    doc = json.loads(out)  # one parseable document
    assert doc["enabled"] is True, doc
    assert doc["verdict"] == "DUAL", doc
    assert "scout-plan:" not in out, out


def test_b7_json_carries_resolved_single(tmp_path):
    cfg = _write_cfg(tmp_path, "single", dual_pm_scouts=False)
    rc, out = _cli("--config", cfg, "--json")
    assert rc == 0, rc
    doc = json.loads(out)
    assert doc["enabled"] is False, doc
    assert doc["verdict"] == "SINGLE", doc
    assert "scout-plan:" not in out, out


def test_b7_json_and_human_channels_agree_on_the_verdict(tmp_path):
    for stem, dual in (("dual", True), ("single", False)):
        cfg = _write_cfg(tmp_path, stem, dual_pm_scouts=dual)
        rc_h, out_h = _cli("--config", cfg)
        rc_j, out_j = _cli("--config", cfg, "--json")
        assert rc_h == rc_j, (stem, rc_h, rc_j)
        doc = json.loads(out_j)
        assert out_h.splitlines()[-1] == "verdict: %s" % doc["verdict"], (stem, out_h, doc)


def test_b7_json_omitted_key_reports_the_resolved_default(tmp_path):
    cfg = _write_cfg(tmp_path, "omitted")
    rc, out = _cli("--config", cfg, "--json")
    doc = json.loads(out)
    assert doc["enabled"] is _product_config_default_dual(), doc
    assert (rc, doc["verdict"]) == (1, "DUAL"), (rc, doc)


# ==========================================================================
# Behavior 8 -- lens precedence is UNTOUCHED by the new door
# ==========================================================================
def test_b8_lens_order_survives_the_config_door(tmp_path):
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    rc, out = _cli("--config", cfg, "--lens", "alpha", "--lens", "beta")
    assert rc == 1, rc
    stages = _stage_lines(out)
    assert len(stages) == 2, stages
    assert stages[0] == "  pm_scout_a (lens: alpha)", stages[0]
    assert stages[1] == "  pm_scout_b (lens: beta)", stages[1]


def test_b8_lens_still_beats_iteration_through_the_door(tmp_path):
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    rot_a, rot_b = foundry.select_scout_lenses(2)
    _rc, out = _cli("--config", cfg, "--iteration", 2, "--lens", "alpha", "--lens", "beta")
    stages = _stage_lines(out)
    assert stages == ["  pm_scout_a (lens: alpha)", "  pm_scout_b (lens: beta)"], stages
    for rot in (rot_a, rot_b):
        if rot not in ("alpha", "beta"):
            assert rot not in out, "rotation lens leaked past --lens: %r" % out


def test_b8_iteration_rotation_still_works_through_the_door(tmp_path):
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    for n in (0, 2, 5, ITERATION):
        _rc, out = _cli("--config", cfg, "--iteration", n)
        a, b = foundry.select_scout_lenses(n)
        stages = _stage_lines(out)
        assert stages == [
            "  pm_scout_a (lens: %s)" % a,
            "  pm_scout_b (lens: %s)" % b,
        ], (n, stages)


def test_b8_lens_and_iteration_render_identically_with_or_without_the_door(tmp_path):
    """The door may change WHICH verdict is reached, never HOW the plan renders."""
    cfg = _write_cfg(tmp_path, "dual", dual_pm_scouts=True)
    for extra in (["--lens", "alpha", "--lens", "beta"], ["--iteration", "7"], []):
        via_cfg = _cli("--config", cfg, *extra)
        via_flag = _cli("--dual-pm-scouts", *extra)
        assert via_cfg == via_flag, extra


# ==========================================================================
# Behavior 9 -- the resolution is a PURE function
# ==========================================================================
def test_b9_resolver_is_a_module_level_callable():
    fn = foundry.resolve_dual_pm_scouts
    assert callable(fn)
    assert fn.__module__ == foundry.__name__
    assert getattr(foundry, fn.__name__, None) is fn


def test_b9_resolver_truth_table():
    fn = foundry.resolve_dual_pm_scouts
    cases = {
        (False, None): False,
        (False, True): True,
        (False, False): False,
        (True, False): True,
        (True, None): True,
    }
    for (flag, cfg), want in cases.items():
        got = fn(flag, cfg)
        assert got is want, "(%r, %r) -> %r, expected %r" % (flag, cfg, got, want)


def test_b9_resolver_is_total_and_deterministic():
    fn = foundry.resolve_dual_pm_scouts
    for flag in (False, True):
        for cfg in (None, True, False):
            first = fn(flag, cfg)
            assert isinstance(first, bool)
            for _ in range(3):
                assert fn(flag, cfg) is first, (flag, cfg)
    assert fn(True, True) is True


def test_b9_resolver_touches_no_io():
    """Purity by compiled-name introspection: the resolver references no
    filesystem, subprocess, clock, network or config-loading name."""
    names = _co_names_deep(foundry.resolve_dual_pm_scouts)
    banned = {
        "open", "read_text", "write_text", "Path", "pathlib", "os", "subprocess",
        "run", "time", "monotonic", "datetime", "now", "urlopen", "requests",
        "load_config", "json", "loads", "input", "print", "random",
    }
    assert names & banned == set(), sorted(names & banned)


def test_b9_resolver_agrees_with_the_cli_for_every_combination(tmp_path):
    """The pure resolver is the one the CLI actually consults -- not a dormant
    twin. For each (flag_given, cfg_enabled) the CLI verdict equals the
    resolver's answer."""
    fn = foundry.resolve_dual_pm_scouts
    combos = [
        (False, None, []),
        (False, True, None),
        (False, False, None),
        (True, True, None),
        (True, False, None),
        (True, None, []),
    ]
    for flag, cfg_enabled, _slot in combos:
        argv = ["--dual-pm-scouts"] if flag else []
        if cfg_enabled is not None:
            cfg = _write_cfg(tmp_path, "combo-%s" % cfg_enabled, dual_pm_scouts=cfg_enabled)
            argv += ["--config", str(cfg)]
        rc, out = _cli(*argv)
        want = fn(flag, cfg_enabled)
        assert out.splitlines()[-1] == "verdict: %s" % ("DUAL" if want else "SINGLE"), (
            flag, cfg_enabled, out)
        assert rc == (1 if want else 0), (flag, cfg_enabled, rc)


# ==========================================================================
# Acceptance criteria (offline, mechanical)
# ==========================================================================
def test_ac_config_flag_is_optional_on_scout_plan():
    rc, _out = _cli()
    assert rc == 0, "bare scout-plan must still work, so --config is optional"


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_verb_census_unchanged():
    verbs = foundry.foundry_cli_verbs(FOUNDRY_PY.read_text(encoding="utf-8"))
    assert len(set(verbs)) == EXPECTED_VERB_COUNT, sorted(verbs)
    assert "scout-plan" in verbs


def test_ac_readme_verb_index_has_no_gaps():
    verbs = foundry.foundry_cli_verbs(FOUNDRY_PY.read_text(encoding="utf-8"))
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    audit = foundry.readme_verb_index_gaps(readme, verbs)
    assert audit.missing_verbs == (), audit.missing_verbs
    assert audit.sections_without_invocation == (), audit.sections_without_invocation
    assert audit.unknown_invocations == (), audit.unknown_invocations
    assert audit.ok is True, audit


def test_ac_top_level_help_still_lists_scout_plan(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "scout-plan" in out


def test_ac_subparser_help_keeps_every_preexisting_flag(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["scout-plan", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--dual-pm-scouts", "--lens", "--iteration", "--json", "--config"):
        assert flag in out, "%s absent from scout-plan help" % flag


def test_ac_roadmap_ledger_row_recorded_and_within_the_width_wall():
    rows = [
        ln.rstrip("\n")
        for ln in (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8").splitlines()
        if ln.startswith("- iter %d " % ITERATION)
    ]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, len(rows[0])


def test_ac_roadmap_archive_detail_bullet_recorded():
    text = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert ("- **iter %d " % ITERATION) in text


def test_ac_this_test_file_is_ascii():
    text = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(text) if ord(c) >= 128] == []


def test_ac_this_test_file_leak_clean():
    """Suite convention (iter 107): scan this file's bytes with the shipped
    denylist, then prove the matcher is ARMED so a clean result means something."""
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text(encoding="utf-8"))
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
