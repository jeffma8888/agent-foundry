"""Black-box behaviour tests for iter 217 -- the status surface REPORTS the
live-lag liveness verdict (iter 130/141) as the FOURTH operator signal composed
by `gather_status`, while every existing exit code stays byte-identical:

  * `StatusSummary` gains a NINTH field `lag_line: str | None` positioned LAST
    with default `None` (so the eight-argument positional construction used by
    the iter-16 / iter-19 / iter-30 modules stays valid),
  * a pure `StatusSummary.lag_verdict` property == `live_lag_verdict(lag_line)`,
    resolved as a MODULE GLOBAL at call time,
  * `render()` emits exactly ONE additional line right after `  prd: ...`,
  * `to_dict()` returns EXACTLY 14 keys (9 stored + 5 derived), JSON-native,
  * REPORT-ONLY: `attention` / `ok` / `exit_code` / `verdict` never move,
  * `gather_status` populates it via the BARE-NAME `live_lag_status` seam and
    stays TOTAL if that seam raises,
  * `summarize_status` takes `lag_line` keyword-only, default `None`,
  * `company-status --json` per-product payloads carry both new keys.

ISOLATION CONTRACT (honored): this file was written from the iter-217 PM spec's
Expected Behaviors (1-8) and the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the dataclass via `foundry.StatusSummary(...)`, the pure builders via
`foundry.summarize_status(...)` / `foundry.summarize_company(...)`, the rendered
live-lag lines via `foundry.summarize_live_lag(...).render()`, and the CLIs via
`foundry.status_cli(...)` / `foundry.company_status_cli(...)` /
`foundry.main([...])` against TMP-`work_root` configs.

Fully offline & deterministic: every test that reaches `gather_status`
monkeypatches the `live_lag_status` seam, so NO test reads the real
`dispatcher.out` and NO test runs real git / subprocess / network. The real
foundry repo and state tree are NEVER touched or written.
"""
import dataclasses
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers  (mirror the iter-16 / iter-19 / iter-30 status-test conventions)
# --------------------------------------------------------------------------
SHIPPED_FIELDS = (
    "product", "repo", "branch", "latest_iter",
    "postrelease", "hotfix", "speed_story", "prd_line",
)
STORED_KEYS = SHIPPED_FIELDS + ("lag_line",)
DERIVED_KEYS = ("attention", "ok", "exit_code", "verdict", "lag_verdict")
EXPECTED_KEY_ORDER = list(STORED_KEYS) + list(DERIVED_KEYS)     # Behavior 4

# The eight substrings the iter-16 render contract pins (Behavior 3).
ITER16_PINS = (
    "branch main", "latest iteration:", "post-release:", "hotfix flag:",
    "speed-story flag:", "prd:",
)

# Rendered live-lag lines, produced by the PUBLIC iter-130 summariser.
LAG_WARN = foundry.summarize_live_lag(1000.0, (188, 190)).render()
LAG_OK = foundry.summarize_live_lag(1000.0).render()
LAG_UNKNOWN = foundry.summarize_live_lag(unknown_reason="x").render()
LAG_FOREIGN = "  hotfix flag: clear"
UNKNOWN_PLACEHOLDER = "  live-lag: unknown"

# Every lag_line value the report-only property (Behavior 5) must survive.
LAG_VALUES = (None, "", LAG_WARN, LAG_OK, LAG_UNKNOWN, LAG_FOREIGN, 7)


def _mk8(product="demoprod", repo="/tmp/repo", branch="main", latest_iter=1,
         postrelease="HEALTHY", hotfix=False, speed_story=False, prd_line=None):
    """Construct with EXACTLY the eight shipped positional args (Behavior 1)."""
    return foundry.StatusSummary(product, repo, branch, latest_iter,
                                 postrelease, hotfix, speed_story, prd_line)


def _mk9(lag_line, **over):
    """Construct with the ninth field supplied positionally, ninth."""
    base = dict(product="demoprod", repo="/tmp/repo", branch="main",
                latest_iter=1, postrelease="HEALTHY", hotfix=False,
                speed_story=False, prd_line=None)
    base.update(over)
    return foundry.StatusSummary(
        base["product"], base["repo"], base["branch"], base["latest_iter"],
        base["postrelease"], base["hotfix"], base["speed_story"],
        base["prd_line"], lag_line)


def _lines(summary):
    return summary.render().splitlines()


def _prd_index(lines):
    for i, ln in enumerate(lines):
        if ln.strip().startswith("prd:"):
            return i
    raise AssertionError("render() has no '  prd:' line:\n%s" % "\n".join(lines))


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (iter-16 convention); `repo` and
    `work_root` are TMP so the real foundry repo/state is NEVER touched."""
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


def _write_postrelease(cfg, iteration, verdict="HEALTHY"):
    """Make the TMP product genuinely healthy (iter-19 convention): a real
    `state/iter-NN/postrelease.md` under the tmp work_root, so `status` has an
    iteration to report and exits 0 rather than 2 ("no iterations yet")."""
    d = pathlib.Path(cfg.state) / ("iter-%02d" % iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "postrelease.md").write_text(
        "post-release verification report\n\nPOSTRELEASE: %s\n" % verdict)
    return d / "postrelease.md"


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"work_items": work_items}))
    return p


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters: Behavior 8 requires JSON to be the ENTIRE stdout."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _patch_lag(monkeypatch, line):
    """Script the live_lag_status seam OFFLINE so no test reads dispatcher.out.
    `line` may be a string (rendered by a stub) or an Exception to raise."""
    class _Stub:
        def render(self_inner):
            return line

    def _seam(cfg, *a, **k):
        if isinstance(line, BaseException):
            raise line
        return _Stub()

    monkeypatch.setattr(foundry, "live_lag_status", _seam)


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


# ==========================================================================
# Behavior 1 -- a NINTH field, LAST, defaulting to None
# ==========================================================================
def test_b1_eight_positional_args_still_construct_and_lag_is_none():
    s = _mk8()
    assert s.lag_line is None, (
        "the eight-argument construction must leave lag_line None, got %r"
        % (s.lag_line,))


def test_b1_lag_line_is_the_ninth_and_last_field_in_order():
    names = tuple(f.name for f in dataclasses.fields(foundry.StatusSummary))
    assert names[:8] == SHIPPED_FIELDS, (
        "the eight shipped fields moved -- positional construction in the "
        "iter-16/19/30 modules would silently transpose: %r" % (names,))
    assert names[8:] == ("lag_line",), (
        "lag_line must be the ninth and LAST field, got %r" % (names,))


def test_b1_ninth_positional_arg_populates_lag_line():
    s = _mk9(LAG_WARN)
    assert s.lag_line == LAG_WARN


def test_b1_default_survives_every_shipped_field_combination():
    for kw in ({}, dict(postrelease=None, latest_iter=0, hotfix=True),
               dict(postrelease="BROKEN", speed_story=True,
                    prd_line="demoprod: 1/2 pass")):
        assert _mk8(**kw).lag_line is None


# ==========================================================================
# Behavior 2 -- pure `lag_verdict` == live_lag_verdict(lag_line), module global
# ==========================================================================
def test_b2_lag_verdict_maps_the_three_rendered_verdicts():
    assert _mk9(LAG_WARN).lag_verdict == "WARN"
    assert _mk9(LAG_OK).lag_verdict == "OK"
    assert _mk9(LAG_UNKNOWN).lag_verdict == "UNKNOWN"


def test_b2_lag_verdict_is_empty_for_none_empty_nonstr_and_foreign():
    for value in (None, "", 7, LAG_FOREIGN, [], {}, 1.5, True):
        assert _mk9(value).lag_verdict == "", (
            "lag_verdict must be '' for %r, got %r"
            % (value, _mk9(value).lag_verdict))


def test_b2_lag_verdict_agrees_with_the_public_helper_on_every_value():
    for value in LAG_VALUES:
        assert _mk9(value).lag_verdict == foundry.live_lag_verdict(value)


def test_b2_lag_verdict_reads_the_module_global_at_call_time(monkeypatch):
    """The property must resolve `live_lag_verdict` by BARE NAME when called,
    not capture it at def time -- otherwise monkeypatching cannot reach it."""
    s = _mk9(LAG_WARN)
    assert s.lag_verdict == "WARN"      # pre-patch reading
    monkeypatch.setattr(foundry, "live_lag_verdict",
                        lambda line: "ZZSENTINELZZ")
    assert s.lag_verdict == "ZZSENTINELZZ", (
        "lag_verdict did not read the module global at call time")


def test_b2_lag_verdict_never_raises():
    class _Hostile:
        def __str__(self):
            raise RuntimeError("str() must not be reached")

        def __repr__(self):
            return "<hostile>"

    for value in (_Hostile(), object(), float("nan"), b"bytes", (), set()):
        try:
            got = _mk9(value).lag_verdict
        except Exception as exc:                      # pragma: no cover
            pytest.fail("lag_verdict raised on %r: %r" % (value, exc))
        assert isinstance(got, str)


def test_b2_lag_verdict_is_pure_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)
    for value in LAG_VALUES:
        _mk9(value).lag_verdict
    assert _snapshot_tree(tmp_path) == before, "lag_verdict touched the fs"


# ==========================================================================
# Behavior 3 -- render(): exactly ONE extra line, right after `  prd: ...`
# ==========================================================================
def test_b3_lag_line_is_rendered_verbatim_immediately_after_prd():
    for value in (LAG_WARN, LAG_OK, LAG_UNKNOWN, LAG_FOREIGN):
        lines = _lines(_mk9(value, prd_line="demoprod: 1/2 pass"))
        i = _prd_index(lines)
        assert lines[i + 1] == value, (
            "the line after '  prd:' must be lag_line VERBATIM.\n"
            " got: %r\nwant: %r" % (lines[i + 1], value))


def test_b3_unknown_placeholder_when_lag_line_is_absent_or_not_a_string():
    for value in (None, "", 7, [], object()):
        lines = _lines(_mk9(value))
        i = _prd_index(lines)
        assert lines[i + 1] == UNKNOWN_PLACEHOLDER, (
            "lag_line=%r must render the placeholder %r, got %r"
            % (value, UNKNOWN_PLACEHOLDER, lines[i + 1]))


def test_b3_exactly_one_additional_line_and_the_count_never_moves():
    """The lag signal contributes EXACTLY one line: the rendered line count is
    the same whether lag_line is set or None, and the two renders differ at
    exactly ONE index -- the slot right after `  prd:`."""
    base = _lines(_mk8(prd_line="demoprod: 1/2 pass"))
    assert len(base) == 9, (
        "expected the 8 iter-16 lines + exactly 1 live-lag line, got %d:\n%s"
        % (len(base), "\n".join(base)))
    for value in (LAG_WARN, LAG_OK, LAG_UNKNOWN):
        got = _lines(_mk9(value, prd_line="demoprod: 1/2 pass"))
        assert len(got) == len(base), (
            "line count moved with lag_line=%r: %d vs %d" % (value, len(got), len(base)))
        differing = [i for i in range(len(base)) if base[i] != got[i]]
        assert differing == [_prd_index(base) + 1], (
            "lag_line must change exactly the slot after '  prd:', changed %r"
            % (differing,))


def test_b3_iter16_pinned_substrings_and_prd_line_survive():
    prd = "demoprod: 4/9 stories pass (in progress)"
    for value in LAG_VALUES:
        out = _mk9(value, prd_line=prd).render()
        for pin in ITER16_PINS:
            assert pin in out, "iter-16 pin %r lost with lag_line=%r:\n%s" % (
                pin, value, out)
        assert prd in out, "the prd_line verbatim was lost with lag_line=%r" % (value,)
        assert "verdict:" in out


def test_b3_final_line_is_still_the_verdict_line():
    for value in LAG_VALUES:
        for kw in ({}, dict(postrelease="BROKEN"), dict(hotfix=True),
                   dict(postrelease=None, latest_iter=0)):
            lines = [ln for ln in _lines(_mk9(value, **kw)) if ln.strip()]
            assert lines[-1].startswith("verdict:"), (
                "the last non-empty render() line must stay the verdict line, "
                "got %r (lag_line=%r, %r)" % (lines[-1], value, kw))


def test_b3_verdict_token_still_appears_in_render():
    for value in LAG_VALUES:
        s = _mk9(value, postrelease="BROKEN")
        assert s.to_dict()["verdict"] in s.render()


# ==========================================================================
# Behavior 4 -- to_dict(): EXACTLY 14 keys, fixed order, JSON-native
# ==========================================================================
def test_b4_to_dict_has_exactly_fourteen_keys_in_order():
    for value in LAG_VALUES:
        d = _mk9(value).to_dict()
        assert list(d.keys()) == EXPECTED_KEY_ORDER, (
            "to_dict keys/order wrong for lag_line=%r.\n got: %s\nwant: %s"
            % (value, list(d.keys()), EXPECTED_KEY_ORDER))
        assert len(d) == 14


def test_b4_new_keys_mirror_the_stored_field_and_the_property():
    for value in (None, LAG_WARN, LAG_OK, LAG_UNKNOWN):
        s = _mk9(value)
        d = s.to_dict()
        assert d["lag_line"] == s.lag_line
        assert d["lag_verdict"] == s.lag_verdict
        assert isinstance(d["lag_verdict"], str)


def test_b4_json_native_and_round_trips():
    for value in (None, "", LAG_WARN, LAG_OK, LAG_UNKNOWN, LAG_FOREIGN):
        d = _mk9(value).to_dict()
        text = json.dumps(d)                      # must not raise
        assert json.loads(text) == d
        assert d["lag_line"] is None or isinstance(d["lag_line"], str)


def test_b4_to_dict_is_pure_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)
    for value in LAG_VALUES:
        _mk9(value).to_dict()
    assert _snapshot_tree(tmp_path) == before, "to_dict touched the fs"


# ==========================================================================
# Behavior 5 -- REPORT-ONLY: no exit code, verdict or attention ever moves
# ==========================================================================
DERIVED_SAFETY_KEYS = ("attention", "ok", "exit_code", "verdict")


def test_b5_derived_fields_are_identical_to_the_lag_none_summary():
    """The safety property: for EVERY lag_line value -- including a WARN line --
    attention / ok / exit_code / verdict equal the lag_line=None summary."""
    shapes = ({}, dict(postrelease="BROKEN"), dict(hotfix=True),
              dict(speed_story=True), dict(postrelease=None, latest_iter=0),
              dict(postrelease="HEALTHY", hotfix=True, speed_story=True))
    for kw in shapes:
        baseline = _mk9(None, **kw)
        want = tuple(getattr(baseline, k) for k in DERIVED_SAFETY_KEYS)
        for value in LAG_VALUES:
            s = _mk9(value, **kw)
            got = tuple(getattr(s, k) for k in DERIVED_SAFETY_KEYS)
            assert got == want, (
                "lag_line=%r moved a derived field for %r: %r != %r"
                % (value, kw, got, want))
            d = s.to_dict()
            assert tuple(d[k] for k in DERIVED_SAFETY_KEYS) == want


def test_b5_a_warn_lag_never_creates_attention():
    s = _mk9(LAG_WARN, postrelease="HEALTHY")
    assert s.lag_verdict == "WARN", "fixture is inert -- lag is not WARN"
    assert s.attention is False and s.ok is True and s.exit_code == 0
    assert s.verdict == "OK"


def test_b5_status_cli_still_exits_zero_on_a_healthy_lagging_product(
        tmp_path, monkeypatch):
    """A healthy product whose brain is lagging still exits 0 from `status`,
    and the WARN line IS printed."""
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 3, "HEALTHY")
    _patch_lag(monkeypatch, LAG_WARN)
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc == 0, "a lagging brain must not change the status exit code:\n%s" % out
    assert "WARN" in out, "the live-lag verdict was not printed:\n%s" % out
    assert LAG_WARN in out, "the WARN live-lag line was not printed:\n%s" % out
    # control: the SAME product with a clean brain also exits 0 -- so the 0 above
    # is not an artifact of the exit code being pinned to 0 for every input.
    _patch_lag(monkeypatch, LAG_OK)
    rc_clean, out_clean, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc_clean == 0 and "OK" in out_clean
    # ... and a genuinely BROKEN product still escalates, proving the exit path
    # is live rather than inert.
    _write_postrelease(cfg, 3, "BROKEN")
    rc_broken, _, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc_broken == 1, (
        "the status exit path is inert -- BROKEN did not escalate: %r" % rc_broken)


def test_b5_company_status_still_counts_a_lagging_product_in_n_ok():
    healthy = _mk9(None)
    lagging = _mk9(LAG_WARN, product="lagger")
    cs = foundry.summarize_company(dispatch_path="/d/foundry.config.json",
                                   products=(healthy, lagging),
                                   disabled=(), errors=())
    assert cs.n_ok == 2, "a lagging product must still count as ok: n_ok=%d" % cs.n_ok
    assert cs.n_attention == 0
    assert cs.exit_code == 0 and cs.ok is True
    assert cs.verdict == "OK"


def test_b5_company_exit_code_is_independent_of_the_lag_line():
    for value in LAG_VALUES:
        cs = foundry.summarize_company(
            dispatch_path="/d", products=(_mk9(value), _mk9(value, product="b")),
            disabled=(), errors=())
        assert (cs.exit_code, cs.verdict, cs.attention) == (0, "OK", False), (
            "lag_line=%r moved the company verdict: %r" % (value, cs.to_dict()))


# ==========================================================================
# Behavior 6 -- gather_status composes the BARE-NAME live_lag_status seam
# ==========================================================================
def test_b6_gather_status_uses_the_bare_name_seam(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    _patch_lag(monkeypatch, "live-lag: WARN -- ZZSENTINELZZ")
    s = foundry.gather_status(cfg)
    assert s.lag_line == "live-lag: WARN -- ZZSENTINELZZ", (
        "gather_status did not read the monkeypatched live_lag_status seam: %r"
        % (s.lag_line,))
    assert "ZZSENTINELZZ" in s.render()


def test_b6_gather_status_takes_render_of_the_seam_result(tmp_path, monkeypatch):
    """It must call `.render()` on the seam's return value, not str() it."""
    class _Obj:
        def render(self):
            return LAG_OK

        def __str__(self):                            # pragma: no cover
            return "WRONG -- str() was used instead of render()"

    monkeypatch.setattr(foundry, "live_lag_status", lambda cfg, *a, **k: _Obj())
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    s = foundry.gather_status(cfg)
    assert s.lag_line == LAG_OK
    assert s.lag_verdict == "OK"


def test_b6_gather_status_is_total_when_the_seam_raises(tmp_path, monkeypatch):
    """If the seam raises, lag_line is None and NO other field is disturbed."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    _patch_lag(monkeypatch, LAG_OK)
    good = foundry.gather_status(cfg)
    _patch_lag(monkeypatch, RuntimeError("seam exploded"))
    bad = foundry.gather_status(cfg)                    # must NOT raise
    assert bad.lag_line is None, (
        "a raising seam must degrade to None, got %r" % (bad.lag_line,))
    assert bad.lag_verdict == ""
    for f in SHIPPED_FIELDS:
        assert getattr(bad, f) == getattr(good, f), (
            "field %r was disturbed by the seam failure: %r != %r"
            % (f, getattr(bad, f), getattr(good, f)))
    for k in DERIVED_SAFETY_KEYS:
        assert getattr(bad, k) == getattr(good, k)


def test_b6_gather_status_survives_a_seam_returning_a_bad_shape(
        tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    for bogus in (None, 7, object()):
        monkeypatch.setattr(foundry, "live_lag_status",
                            lambda cfg, *a, **k: bogus)
        s = foundry.gather_status(cfg)                 # must NOT raise
        assert s.lag_verdict == ""
        assert isinstance(s.render(), str)


def test_b6_gather_status_writes_no_artifact(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _patch_lag(monkeypatch, LAG_WARN)
    before = _snapshot_tree(tmp_path)
    foundry.gather_status(cfg)
    assert _snapshot_tree(tmp_path) == before, "gather_status wrote a file"


# ==========================================================================
# Behavior 7 -- summarize_status: keyword-only lag_line, default None
# ==========================================================================
def _summarize(**over):
    kw = dict(product="p", repo="/r", branch="main", latest_iter=1,
              postrelease="HEALTHY", hotfix=False, speed_story=False,
              prd_line=None)
    kw.update(over)
    return foundry.summarize_status(**kw)


def test_b7_summarize_status_without_lag_line_yields_none():
    assert _summarize().lag_line is None


def test_b7_summarize_status_passes_lag_line_through_unchanged():
    for value in LAG_VALUES:
        assert _summarize(lag_line=value).lag_line == value or (
            value is None and _summarize(lag_line=value).lag_line is None)


def test_b7_summarize_status_never_raises_on_any_lag_value():
    for value in LAG_VALUES + (object(), [], {}):
        try:
            s = _summarize(lag_line=value)
        except Exception as exc:                       # pragma: no cover
            pytest.fail("summarize_status raised on lag_line=%r: %r" % (value, exc))
        assert isinstance(s.render(), str)
        assert isinstance(s.to_dict(), dict)


def test_b7_lag_line_is_keyword_only():
    """`summarize_status` is a keyword-only builder -- a positional lag_line
    must be refused rather than silently bound to another field."""
    with pytest.raises(TypeError):
        foundry.summarize_status("p", "/r", "main", 1, "HEALTHY", False, False,
                                 None, LAG_WARN)


# ==========================================================================
# Behavior 8 -- the JSON surfaces carry the two new keys
# ==========================================================================
def test_b8_status_json_equals_gather_status_to_dict(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    _patch_lag(monkeypatch, LAG_WARN)
    rc, out, err = _capture(lambda: foundry.status_cli(cfg, as_json=True))
    expected = foundry.gather_status(cfg).to_dict()
    assert out.rstrip("\n") == json.dumps(expected, indent=2), (
        "status --json stdout is not the single expected JSON document:\n%s" % out)
    parsed = json.loads(out)
    assert parsed == expected
    assert parsed["lag_line"] == LAG_WARN
    assert parsed["lag_verdict"] == "WARN"
    assert len(parsed) == 14
    assert rc == expected["exit_code"], (
        "the JSON path must return the summary's own exit code: %r != %r"
        % (rc, expected["exit_code"]))


def test_b8_status_json_exit_code_matches_the_human_path(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    for line in (LAG_WARN, LAG_OK, LAG_UNKNOWN):
        _patch_lag(monkeypatch, line)
        rc_human, _, _ = _capture(lambda: foundry.status_cli(cfg))
        rc_json, _, _ = _capture(lambda: foundry.status_cli(cfg, as_json=True))
        assert rc_human == rc_json, (
            "human/json exit codes diverged for %r: %r vs %r"
            % (line, rc_human, rc_json))


def test_b8_company_status_json_products_carry_both_new_keys(
        tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        {"name": "beta", "config": str(tmp_path / "beta.json"), "enabled": True},
    ])
    lag_by_name = {"alpha": LAG_WARN, "beta": None}

    class _Cfg:
        def __init__(self, path):
            self._path = path

    monkeypatch.setattr(foundry, "load_config", lambda p: _Cfg(p))

    def fake_gather(cfg):
        for name, lag in lag_by_name.items():
            if name in cfg._path:
                return _mk9(lag, product=name)
        return _mk9(None, product="unknown")           # pragma: no cover

    monkeypatch.setattr(foundry, "gather_status", fake_gather)
    rc, out, err = _capture(
        lambda: foundry.company_status_cli(str(disp), as_json=True))
    doc = json.loads(out)
    assert isinstance(doc["products"], list) and len(doc["products"]) == 2
    by_name = {p["product"]: p for p in doc["products"]}
    for name in ("alpha", "beta"):
        p = by_name[name]
        assert "lag_line" in p and "lag_verdict" in p, (
            "per-product payload for %s lacks the new keys: %s"
            % (name, sorted(p)))
        assert list(p.keys()) == EXPECTED_KEY_ORDER
        assert len(p) == 14
    assert by_name["alpha"]["lag_verdict"] == "WARN"
    assert by_name["alpha"]["lag_line"] == LAG_WARN
    assert by_name["beta"]["lag_verdict"] == ""
    assert by_name["beta"]["lag_line"] is None
    # REPORT-ONLY at the company level: a WARN product is still ok, exit 0.
    assert doc["n_ok"] == 2 and doc["n_attention"] == 0
    assert doc["exit_code"] == 0 and rc == 0


def test_b8_company_status_json_is_a_single_document(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])

    class _Cfg:
        def __init__(self, path):
            self._path = path

    monkeypatch.setattr(foundry, "load_config", lambda p: _Cfg(p))
    monkeypatch.setattr(foundry, "gather_status",
                        lambda cfg: _mk9(LAG_WARN, product="alpha"))
    rc, out, err = _capture(
        lambda: foundry.company_status_cli(str(disp), as_json=True))
    assert isinstance(json.loads(out), dict), (
        "company-status --json stdout must be ONE JSON document:\n%s" % out)


def test_b8_company_status_via_main_carries_the_keys(tmp_path, monkeypatch):
    disp = _write_dispatch(tmp_path, [
        {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
    ])

    class _Cfg:
        def __init__(self, path):
            self._path = path

    monkeypatch.setattr(foundry, "load_config", lambda p: _Cfg(p))
    monkeypatch.setattr(foundry, "gather_status",
                        lambda cfg: _mk9(LAG_OK, product="alpha"))
    rc, out, err = _capture(
        lambda: foundry.main(["company-status", "--config", str(disp), "--json"]))
    doc = json.loads(out)
    assert doc["products"][0]["lag_verdict"] == "OK"
    assert rc == 0


# ==========================================================================
# Regression guards -- importability and the CompanyStatus non-edit
# ==========================================================================
def test_modules_still_import():
    assert foundry is not None and dispatcher is not None
    assert hasattr(foundry, "live_lag_status")
    assert hasattr(foundry, "live_lag_verdict")
    assert hasattr(foundry, "summarize_live_lag")


def test_company_summary_key_set_is_unchanged():
    """Behavior 8 requires NO edit to CompanyStatus: its own key set is the
    iter-30/61 one, and the new keys appear ONLY inside `products[*]`."""
    cs = foundry.summarize_company(dispatch_path="/d", products=(_mk9(LAG_WARN),),
                                   disabled=(), errors=())
    d = cs.to_dict()
    assert "lag_line" not in d and "lag_verdict" not in d, (
        "the live-lag keys leaked onto CompanyStatus itself: %s" % sorted(d))
    for key in ("dispatch_config", "products", "disabled", "errors",
                "n_products", "n_ok", "n_attention", "n_disabled", "n_errors",
                "attention", "ok", "exit_code", "verdict"):
        assert key in d, "CompanyStatus lost key %r" % key
