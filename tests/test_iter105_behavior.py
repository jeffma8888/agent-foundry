"""Black-box behaviour tests for iter 105 -- `foundry novelty-check
[--config C] [--limit N] [--json]`: a read-only + DORMANT repetition brake
(discovery bite 3). It inspects the branch's most-recent commit subjects plus the
newest roadmap entries and emits a RUT / VARIED verdict with a 0/1 exit code and
a --json machine payload, giving the loop an objective, testable signal that it
is repeating the same increment shape. Nothing on a control path calls it this
bite.

New symbols (all in foundry.py): pure `novelty_shape(text) -> str`, pure
`novelty_verdict(commit_subjects, roadmap_entries) -> str`, frozen `NoveltyReport`
value object (two stored tuple fields; derived verdict / exit_code /
dominant_shape / dominant_count / render / to_dict), read-only `gather_novelty(cfg,
limit=None) -> NoveltyReport` seam, `novelty_check_cli(cfg, limit=None,
as_json=False) -> int` printer, and module constants NOVELTY_RUT_THRESHOLD (3),
NOVELTY_DEFAULT_N (5), NOVELTY_SELF_DESCRIBE_PHRASES.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-105 PM
spec's Expected Behaviors (1-11), the product README / roadmap, the tests/
conventions (esp. the read-only-CLI seam template in test_iter31 /
test_iter39_behavior.py and the value-object tests in
test_iter98_behavior.py), and the product's own OBSERVABLE behaviour (running it /
public RUNTIME introspection -- module attrs, --help output, compiled
`__code__.co_names` / `co_consts` tables). The implementation SOURCE (foundry.py /
dispatcher.py source text), the engineer's and reviewer's notes, and `git diff`
(and `git show HEAD:foundry.py`) were NOT read. Every check drives the PUBLIC
interface: the pure fns via `foundry.novelty_shape` / `foundry.novelty_verdict`,
the value object via `foundry.NoveltyReport`, the seam via
`foundry.gather_novelty` with a monkeypatched bare-name `git` seam + a TMP
`cfg.roadmap`, and the CLI via `foundry.novelty_check_cli` /
`foundry.main(["novelty-check", ...])` against a TMP-`work_root` / TMP-`repo`
config (the real foundry repo / state / git / network are NEVER touched). Fully
offline and deterministic: real temp files only, no subprocess / git / network.
"""
import dataclasses
import io
import contextlib
import json
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers (mirror the suite's conventions; repo/work_root are TMP dirs so the
# real foundry repo / state is NEVER touched)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, roadmap_text=None, roadmap_name="ROADMAP.md", **over):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    rm = tmp_path / roadmap_name
    if roadmap_text is not None:
        rm.write_text(roadmap_text)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
        "roadmap": str(rm),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **kw):
    return foundry.load_config(str(_write_cfg(tmp_path, **kw)))


def _run_fn(fn):
    """Drive a bare callable capturing (rc, stdout)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn()
    return rc, out.getvalue()


def _run_cli(argv):
    """Drive foundry.main capturing (rc, stdout+stderr); SystemExit -> code."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = foundry.main(argv)
        except SystemExit as ex:
            rc = ex.code
    return rc, out.getvalue() + err.getvalue()


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _deep(code, names, consts):
    names.update(code.co_names)
    for c in code.co_consts:
        if isinstance(c, str):
            consts.add(c)
        elif isinstance(c, types.CodeType):
            _deep(c, names, consts)
    return names, consts


NOVELTY_SYMBOLS = (
    "novelty_shape", "novelty_verdict", "NoveltyReport", "gather_novelty",
    "novelty_check_cli", "NOVELTY_RUT_THRESHOLD", "NOVELTY_DEFAULT_N",
    "NOVELTY_SELF_DESCRIBE_PHRASES",
)
NOVELTY_STRINGS = ("novelty-check", "novelty")


# ==========================================================================
# Behavior 1 -- pure, total shape classifier
# ==========================================================================
def test_b01_shape_spec_examples():
    assert foundry.novelty_shape("feat: outcomes --json (foundry iter 101)") == "tail:--json"
    assert foundry.novelty_shape("feat: company-history (iter 31)") == "family:company-*"
    assert foundry.novelty_shape("a DIRECT STRUCTURAL CLONE of history") == "self-describe"
    assert foundry.novelty_shape("chore: tidy up imports") == "lead:tidy up"
    assert foundry.novelty_shape("   ") == ""


def test_b01_shape_blank_and_empty_key():
    for blank in ("", "   ", "\t", "\n  \n"):
        assert foundry.novelty_shape(blank) == "", repr(blank)


def test_b01_shape_strips_conventional_prefix():
    # bare prefix + scoped prefix both stripped before classification
    assert foundry.novelty_shape("fix(tests): something --json") == "tail:--json"
    assert foundry.novelty_shape("chore(scope): tidy up imports") == "lead:tidy up"


def test_b01_shape_strips_only_trailing_iter_tag():
    # a MID-string parenthetical (iter N) is preserved; only the TRAILING one strips
    s = foundry.novelty_shape("feat: refactor (iter 3) core module (foundry iter 99)")
    assert "(iter" in s and s.startswith("lead:"), s
    # trailing tag gone: classification uses "refactor (iter 3) core module"
    assert foundry.novelty_shape("feat: alpha beta (foundry iter 104)") == "lead:alpha beta"


def test_b01_shape_first_match_selfdescribe_beats_json_tail():
    # (a) self-describe wins over (b) --json tail
    assert foundry.novelty_shape("feat: a clone thing --json") == "self-describe"
    assert foundry.novelty_shape("mirror of the last shape") == "self-describe"
    assert foundry.novelty_shape("same shape as before") == "self-describe"


def test_b01_shape_company_prefix_when_not_selfdescribe_or_json():
    assert foundry.novelty_shape("company-outcomes rollup") == "family:company-*"
    # company- but ALSO --json tail: --json is checked BEFORE company- (order b then c)
    assert foundry.novelty_shape("company-outcomes --json") == "tail:--json"


def test_b01_shape_collapses_internal_whitespace():
    assert foundry.novelty_shape("chore:    tidy     up   imports") == "lead:tidy up"


def test_b01_shape_lead_single_token():
    assert foundry.novelty_shape("solo") == "lead:solo"


def test_b01_shape_never_raises_on_odd_input():
    for weird in ("feat:", "()", "(iter 9)", "company-", "--json", ":::", "  --json  "):
        # must return a str, never raise
        assert isinstance(foundry.novelty_shape(weird), str), repr(weird)


# ==========================================================================
# Behavior 2 -- pure verdict RUT / VARIED
# ==========================================================================
def test_b02_verdict_oracle_twelve_json_is_rut():
    subs = [f"feat: thing{i} --json" for i in range(12)]
    assert foundry.novelty_verdict(subs, []) == "RUT"


def test_b02_verdict_oracle_twelve_varied_is_varied():
    subs = [f"feat: verb{i} noun{i}" for i in range(12)]
    assert foundry.novelty_verdict(subs, []) == "VARIED"


def test_b02_verdict_two_json_plus_blank_is_varied():
    # only 2 share (blank discarded) -> below threshold 3
    assert foundry.novelty_verdict(["a --json", "b --json"], ["   "]) == "VARIED"


def test_b02_verdict_exactly_threshold_is_rut():
    assert foundry.novelty_verdict(["a --json", "b --json", "c --json"], []) == "RUT"


def test_b02_verdict_both_empty_and_all_blank_is_varied():
    assert foundry.novelty_verdict([], []) == "VARIED"
    assert foundry.novelty_verdict(["  ", ""], [""]) == "VARIED"


def test_b02_verdict_pools_across_both_sources():
    # 2 --json commits + 1 --json roadmap entry -> pooled 3 share -> RUT
    assert foundry.novelty_verdict(["a --json", "b --json"], ["c --json"]) == "RUT"


def test_b02_verdict_accepts_any_iterable():
    subs = (f"x{i} --json" for i in range(4))  # generator
    assert foundry.novelty_verdict(subs, iter(["y --json"])) == "RUT"


# ==========================================================================
# Behavior 3 -- threshold + phrases are CALL-TIME module constants
# ==========================================================================
def test_b03_constants_types_and_defaults():
    assert isinstance(foundry.NOVELTY_RUT_THRESHOLD, int) and foundry.NOVELTY_RUT_THRESHOLD == 3
    assert isinstance(foundry.NOVELTY_DEFAULT_N, int) and foundry.NOVELTY_DEFAULT_N == 5
    assert isinstance(foundry.NOVELTY_SELF_DESCRIBE_PHRASES, tuple)
    assert all(isinstance(p, str) for p in foundry.NOVELTY_SELF_DESCRIBE_PHRASES)
    assert foundry.NOVELTY_SELF_DESCRIBE_PHRASES == ("clone", "mirror", "same shape as")


def test_b03_threshold_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "NOVELTY_RUT_THRESHOLD", 2)
    # two shared shapes now trip RUT
    assert foundry.novelty_verdict(["a --json", "b --json"], []) == "RUT"


def test_b03_phrases_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "NOVELTY_SELF_DESCRIBE_PHRASES", ("wibble",))
    assert foundry.novelty_shape("this is a wibble increment") == "self-describe"
    # the default phrase no longer classifies as self-describe
    assert foundry.novelty_shape("a clone of x --json") == "tail:--json"


# ==========================================================================
# Behavior 4 -- frozen report value object
# ==========================================================================
def _report(commits=(), roadmap=()):
    return foundry.NoveltyReport(commit_subjects=tuple(commits),
                                 roadmap_entries=tuple(roadmap))


def test_b04_frozen_two_stored_fields_in_order():
    fields = [f.name for f in dataclasses.fields(foundry.NoveltyReport)]
    assert fields == ["commit_subjects", "roadmap_entries"], fields
    assert foundry.NoveltyReport.__dataclass_params__.frozen is True


def test_b04_value_equality_and_immutability():
    a = _report(("x --json",), ("y --json",))
    b = _report(("x --json",), ("y --json",))
    assert a == b
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.commit_subjects = ()


def test_b04_derived_verdict_and_exit_code():
    rut = _report([f"t{i} --json" for i in range(3)])
    assert rut.verdict == "RUT" and rut.exit_code == 1
    varied = _report([f"verb{i} noun{i}" for i in range(3)])
    assert varied.verdict == "VARIED" and varied.exit_code == 0
    # derived properties agree with the pure fn
    assert rut.verdict == foundry.novelty_verdict(rut.commit_subjects, rut.roadmap_entries)


def test_b04_dominant_shape_and_count():
    r = _report(["a --json", "b --json", "c --json", "solo lead"])
    assert r.dominant_shape == "tail:--json" and r.dominant_count == 3


def test_b04_dominant_tie_break_first_appearance():
    # two "lead:alpha beta" (first), two "lead:gamma delta" -> tie broken to first
    r = _report(["alpha beta x", "gamma delta y", "alpha beta z", "gamma delta w"])
    assert r.dominant_shape == "lead:alpha beta" and r.dominant_count == 2


def test_b04_dominant_pool_order_commits_before_roadmap():
    # commits pooled first -> a commit shape wins a cross-source tie
    r = _report(["gamma delta a", "gamma delta b"], ["alpha beta c", "alpha beta d"])
    assert r.dominant_shape == "lead:gamma delta" and r.dominant_count == 2


def test_b04_dominant_empty_pool_is_blank_zero():
    r = _report()
    assert (r.dominant_shape, r.dominant_count) == ("", 0)
    assert r.verdict == "VARIED" and r.exit_code == 0
    # all-blank pool also empties out
    rb = _report(["  ", ""], [""])
    assert (rb.dominant_shape, rb.dominant_count) == ("", 0)


# ==========================================================================
# Behavior 5 -- render() human report
# ==========================================================================
def test_b05_render_substrings_and_final_line():
    r = _report([f"t{i} --json" for i in range(3)], ["road --json"])
    text = r.render()
    assert "foundry novelty-check" in text
    assert "3 commits" in text and "1 roadmap" in text
    assert "tail:--json" in text  # dominant shape named
    assert "4" in text            # dominant count (3 commits + 1 roadmap)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: RUT", lines[-1]


def test_b05_render_varied_final_line():
    r = _report([f"verb{i} noun{i}" for i in range(3)])
    lines = [ln for ln in r.render().splitlines() if ln.strip()]
    assert lines[-1] == "verdict: VARIED", lines[-1]


def test_b05_render_no_dominant_line_when_pool_empty():
    r = _report()
    text = r.render()
    assert "dominant" not in text.lower()
    assert "0 commits" in text and "0 roadmap" in text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: VARIED"


def test_b05_render_deterministic():
    r = _report(["a --json", "b --json", "c --json"])
    assert r.render() == r.render()


# ==========================================================================
# Behavior 6 -- to_dict() machine payload
# ==========================================================================
def test_b06_to_dict_keys_exact_order():
    r = _report(["a --json", "b --json", "c --json"], ["r --json"])
    d = r.to_dict()
    assert list(d.keys()) == [
        "commit_subjects", "roadmap_entries", "dominant_shape",
        "dominant_count", "verdict", "exit_code",
    ]


def test_b06_to_dict_values_reuse_derived_and_are_json_native():
    r = _report(["a --json", "b --json", "c --json"])
    d = r.to_dict()
    assert d["commit_subjects"] == ["a --json", "b --json", "c --json"]
    assert isinstance(d["commit_subjects"], list) and isinstance(d["roadmap_entries"], list)
    assert d["dominant_shape"] == r.dominant_shape
    assert d["dominant_count"] == r.dominant_count
    assert d["verdict"] == r.verdict
    assert d["exit_code"] == r.exit_code
    # JSON round-trip holds (every value JSON-native)
    assert json.loads(json.dumps(d)) == d


def test_b06_to_dict_cannot_disagree_with_render_and_exit():
    r = _report([f"t{i} --json" for i in range(4)], ["x lead", "y lead"])
    d = r.to_dict()
    assert d["verdict"] in r.render()
    assert d["exit_code"] == r.exit_code


# ==========================================================================
# Behavior 7 -- gather_novelty seam (read-only)
# ==========================================================================
def _fake_git(output):
    calls = {}

    def git(cfg, *args):
        calls["args"] = args
        calls["count"] = calls.get("count", 0) + 1
        return output
    git.calls = calls
    return git


def test_b07_limit_positive_selects_n(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, roadmap_text="- a\n- b\n")
    g = _fake_git("s1\ns2\ns3\ns4\ns5\ns6\n")
    monkeypatch.setattr(foundry, "git", g)
    rep = foundry.gather_novelty(cfg, limit=3)
    assert g.calls["args"] == ("log", "--format=%s", "-n", "3")
    assert rep.commit_subjects == ("s1", "s2", "s3")


def test_b07_limit_none_or_nonpositive_uses_default_n(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, roadmap_text="- a\n")
    for lim in (None, 0, -4):
        g = _fake_git("\n".join(f"c{i}" for i in range(9)) + "\n")
        monkeypatch.setattr(foundry, "git", g)
        rep = foundry.gather_novelty(cfg, limit=lim)
        assert g.calls["args"] == ("log", "--format=%s", "-n", str(foundry.NOVELTY_DEFAULT_N)), lim
        assert len(rep.commit_subjects) == foundry.NOVELTY_DEFAULT_N, lim


def test_b07_git_called_by_bare_name(tmp_path, monkeypatch):
    # monkeypatching foundry.git must bite -> proves bare-name call
    cfg = _cfg(tmp_path, roadmap_text="- a\n")
    g = _fake_git("only --json\n")
    monkeypatch.setattr(foundry, "git", g)
    rep = foundry.gather_novelty(cfg, limit=1)
    assert g.calls["count"] == 1
    assert rep.commit_subjects == ("only --json",)


def test_b07_commit_lines_stripped_and_blanks_dropped(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, roadmap_text="- a\n")
    monkeypatch.setattr(foundry, "git", _fake_git("  s1  \n\n   \ns2\n"))
    rep = foundry.gather_novelty(cfg, limit=9)
    assert rep.commit_subjects == ("s1", "s2")


def test_b07_roadmap_bullet_lines_last_n_left_stripped_match(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "git", _fake_git(""))
    rm = "intro\n- first\n- second\nplain line\n  - indented\n- last\n"
    cfg = _cfg(tmp_path, roadmap_text=rm)
    rep = foundry.gather_novelty(cfg, limit=3)
    # left-stripped-startswith('- ') matches: first, second, indented, last (4)
    # take LAST 3 in file order:
    assert rep.roadmap_entries == ("- second", "  - indented", "- last")


def test_b07_missing_roadmap_is_guarded(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "git", _fake_git("s1\n"))
    # roadmap path that does not exist
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))  # roadmap file not created
    rep = foundry.gather_novelty(cfg)  # must NOT raise
    assert rep.roadmap_entries == ()


def test_b07_returns_novelty_report_and_writes_nothing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, roadmap_text="- a --json\n- b --json\n- c --json\n")
    monkeypatch.setattr(foundry, "git", _fake_git("x --json\ny --json\nz --json\n"))
    before = _snapshot_tree(tmp_path)
    rep = foundry.gather_novelty(cfg, limit=3)
    after = _snapshot_tree(tmp_path)
    assert isinstance(rep, foundry.NoveltyReport)
    assert before == after, "gather_novelty must write NOTHING to disk"


# ==========================================================================
# Behavior 8 -- novelty_check_cli printer
# ==========================================================================
def test_b08_cli_human_prints_render_and_returns_exit(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    sentinel = _report([f"t{i} --json" for i in range(3)])  # RUT -> exit 1
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: sentinel)
    rc, out = _run_fn(lambda: foundry.novelty_check_cli(cfg))
    assert out == sentinel.render() + "\n"
    assert rc == sentinel.exit_code == 1


def test_b08_cli_json_prints_to_dict_indent2_and_same_exit(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    sentinel = _report([f"t{i} --json" for i in range(3)])
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: sentinel)
    rc, out = _run_fn(lambda: foundry.novelty_check_cli(cfg, as_json=True))
    assert out == json.dumps(sentinel.to_dict(), indent=2) + "\n"
    assert rc == sentinel.exit_code


def test_b08_cli_exit_identical_in_both_modes(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    for commits in ([f"t{i} --json" for i in range(3)],           # RUT
                    [f"verb{i} noun{i}" for i in range(3)]):       # VARIED
        sentinel = _report(commits)
        monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: sentinel)
        rc_h, _ = _run_fn(lambda: foundry.novelty_check_cli(cfg))
        rc_j, _ = _run_fn(lambda: foundry.novelty_check_cli(cfg, as_json=True))
        assert rc_h == rc_j == sentinel.exit_code


def test_b08_cli_delegates_to_gather_novelty_bare_name(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen = {}
    sentinel = _report(["z --json", "z --json", "z --json"])

    def fake_gather(cfg, limit=None):
        seen["limit"] = limit
        return sentinel
    monkeypatch.setattr(foundry, "gather_novelty", fake_gather)
    rc, out = _run_fn(lambda: foundry.novelty_check_cli(cfg, limit=7))
    assert seen["limit"] == 7
    assert out == sentinel.render() + "\n"
    assert rc == sentinel.exit_code


def test_b08_cli_writes_nothing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, roadmap_text="- a --json\n")
    monkeypatch.setattr(foundry, "git", _fake_git("x --json\n"))
    before = _snapshot_tree(tmp_path)
    _run_fn(lambda: foundry.novelty_check_cli(cfg, as_json=True))
    assert _snapshot_tree(tmp_path) == before


# ==========================================================================
# Behavior 9 -- CLI wiring (subparser + main dispatch after load_config)
# ==========================================================================
def test_b09_main_e2e_prints_report_and_exits(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path, roadmap_text="- a --json\n- b --json\n- c --json\n")
    monkeypatch.setattr(foundry, "git", _fake_git("x --json\ny --json\nz --json\n"))
    rc, out = _run_cli(["novelty-check", "--config", str(cfg_path)])
    assert "foundry novelty-check" in out
    assert "verdict: RUT" in out
    assert rc == 1


def test_b09_main_e2e_varied_exit_zero(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path, roadmap_text="- alpha one\n- beta two\n")
    monkeypatch.setattr(foundry, "git", _fake_git("gamma three\ndelta four\n"))
    rc, out = _run_cli(["novelty-check", "--config", str(cfg_path)])
    assert "verdict: VARIED" in out
    assert rc == 0


def test_b09_main_json_flag(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path, roadmap_text="- a --json\n")
    monkeypatch.setattr(foundry, "git", _fake_git("x --json\ny --json\nz --json\n"))
    rc, out = _run_cli(["novelty-check", "--config", str(cfg_path), "--json"])
    payload = json.loads(out)
    assert payload["verdict"] == "RUT" and payload["exit_code"] == 1
    assert rc == 1


def test_b09_main_limit_flows_through(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path, roadmap_text="- a\n")
    g = _fake_git("s1\ns2\ns3\ns4\ns5\n")
    monkeypatch.setattr(foundry, "git", g)
    _run_cli(["novelty-check", "--config", str(cfg_path), "--limit", "2"])
    assert g.calls["args"] == ("log", "--format=%s", "-n", "2")


def test_b09_config_is_required():
    rc, out = _run_cli(["novelty-check"])
    assert rc == 2  # argparse usage error
    assert "config" in out.lower()


def test_b09_subparser_help_lists_flags():
    rc, out = _run_cli(["novelty-check", "--help"])
    assert rc == 0
    assert "--config" in out and "--limit" in out and "--json" in out


# ==========================================================================
# Behavior 10 -- fully dormant / resume-safe
# ==========================================================================
ORCHESTRATORS = ("build_prompt", "run_stage", "run_iteration",
                 "run_continuous", "run_execution_plan")


def test_b10_orchestrators_reference_no_novelty_symbol():
    for fn in ORCHESTRATORS:
        names, consts = _deep(getattr(foundry, fn).__code__, set(), set())
        for sym in NOVELTY_SYMBOLS:
            assert sym not in names, f"{fn} references {sym}"
        for s in NOVELTY_STRINGS:
            assert not any(s in c for c in consts), f"{fn} embeds string {s!r}"


def test_b10_dispatcher_references_no_novelty_symbol():
    hits = set()
    for obj_name in dir(dispatcher):
        obj = getattr(dispatcher, obj_name)
        codes = []
        if isinstance(obj, types.FunctionType):
            codes.append(obj.__code__)
        elif isinstance(obj, type):
            for m in vars(obj).values():
                if isinstance(m, types.FunctionType):
                    codes.append(m.__code__)
        for code in codes:
            names, consts = _deep(code, set(), set())
            for sym in NOVELTY_SYMBOLS:
                if sym in names:
                    hits.add(sym)
            for s in NOVELTY_STRINGS:
                if any(s in c for c in consts):
                    hits.add(s)
    assert hits == set(), f"dispatcher references novelty symbols: {hits}"


def test_b10_both_modules_import():
    import importlib
    importlib.reload  # attribute exists; both already imported at top
    assert foundry is not None and dispatcher is not None


def test_b10_preexisting_public_symbols_still_present():
    # black-box proxy for "pre-existing symbols byte-unchanged": the public
    # surface the loop depends on is intact and callable.
    for name in ("load_config", "build_prompt", "run_stage", "run_iteration",
                 "run_continuous", "run_execution_plan", "main", "git",
                 "learnings_digest", "gather_history"):
        assert callable(getattr(foundry, name)), name


# ==========================================================================
# Behavior 11 -- public-safety (observable ASCII) + full suite is run separately
# ==========================================================================
def test_b11_observable_output_is_ascii():
    # The spec's ASCII requirement covers SOURCE lines (a reviewer/source check
    # outside a black-box tester's remit). As a black-box proxy we assert the
    # product's own observable output carries no non-ASCII.
    r = _report(["a --json", "b --json", "c --json"], ["r --json"])
    r.render().encode("ascii")
    json.dumps(r.to_dict()).encode("ascii")
    for sym in NOVELTY_SYMBOLS:
        sym.encode("ascii")


def test_b11_this_test_file_is_pure_ascii():
    src = pathlib.Path(__file__).read_bytes()
    src.decode("ascii")  # raises if any non-ASCII byte slipped in
