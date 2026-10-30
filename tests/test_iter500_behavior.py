"""Black-box behaviour tests for iter 500 -- `foundry status` REPORTS an
in-effect STOP sentinel as ONE conditional text line just before `verdict:`:

  * `  stop: <scope> -- <reason> (lift: <resume verb>)`, rendered ONLY when a
    team or global sentinel is in effect (global wins over team),
  * the unstopped render is byte-identical (10 lines, no stop line),
  * REPORT-ONLY: exit code / verdict / attention / ok never move,
  * `--json` / to_dict keeps exactly the 16 pre-iteration keys, in order,
  * `StatusSummary` gains `stop_scope="none"` / `stop_reason=""` LAST,
  * `summarize_status` accepts both as defaulted keyword args,
  * `gather_status` reads the BARE-NAME `gather_stop` seam and stays TOTAL,
  * status writes nothing; company-status per-product verdicts unchanged.

ISOLATION CONTRACT (honored): written from the iter-500 PM spec's Expected
Behaviors (1-11) and the product's observable behaviour ONLY. The
implementation source, the engineer's / reviewer's notes and `git diff` were
NOT read. Every fixture lives under tmp_path; `global_stop` and
`live_lag_status` are monkeypatched so NO test reads a real `<foundry>/STOP`
or the real dispatcher.out, and nothing runs git / subprocess / network.
"""
import dataclasses
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
from _shared import _snapshot_tree  # noqa: E402


# --------------------------------------------------------------------------
# constants -- the pre-iteration shapes (mirrors iter-19 / iter-217 pins)
# --------------------------------------------------------------------------
OLD_FIELDS = (
    "product", "repo", "branch", "latest_iter", "postrelease", "hotfix",
    "speed_story", "prd_line", "lag_line", "last_ship_iter",
    "iters_since_last_ship",
)
OLD_KEY_ORDER = list(OLD_FIELDS) + [
    "attention", "ok", "exit_code", "verdict", "lag_verdict"]
TEAM_LIFT = "(lift: foundry.py resume --config <config>)"
GLOBAL_LIFT = "(lift: foundry.py resume --global)"
TEAM_REASON = "Team retired 2026-08-03."
DERIVED = ("attention", "ok", "exit_code", "verdict")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _capture(fn):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _patch_lag(monkeypatch):
    class _Stub:
        def render(self_inner):
            return "  live-lag: OK -- stub"
    monkeypatch.setattr(foundry, "live_lag_status", lambda cfg, *a, **k: _Stub())


def _global(monkeypatch, value):
    monkeypatch.setattr(foundry, "global_stop", lambda: value)


def _write_cfg(tmp_path, name="demoprod"):
    base = tmp_path / name
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "repo": str(repo),
        "allowed_push_repo": name,
        "vision": str(base / "VISION.md"),
        "work_root": str(base / "work"),
    }
    p = base / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, monkeypatch, *, stop=None, name="demoprod",
         healthy_iter=3, verdict="HEALTHY"):
    """A tmp product; `stop` is None (no sentinel) or bytes/str to write."""
    _patch_lag(monkeypatch)
    cfg = foundry.load_config(str(_write_cfg(tmp_path, name)))
    if healthy_iter is not None:
        d = pathlib.Path(cfg.state) / ("iter-%02d" % healthy_iter)
        d.mkdir(parents=True, exist_ok=True)
        (d / "postrelease.md").write_text(
            "post-release verification report\n\nPOSTRELEASE: %s\n" % verdict)
    if stop is not None:
        target = pathlib.Path(cfg.stop_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(stop, bytes):
            target.write_bytes(stop)
        else:
            target.write_text(stop)
    return cfg


def _stop_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("  stop:")]


def _nonempty(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def _summarize(**over):
    kw = dict(product="p", repo="/r", branch="main", latest_iter=1,
              postrelease="HEALTHY", hotfix=False, speed_story=False,
              prd_line=None)
    kw.update(over)
    return foundry.summarize_status(**kw)


# ==========================================================================
# Behavior 1 -- team sentinel
# ==========================================================================
def test_b1_team_sentinel_renders_exact_stop_line(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch, stop=TEAM_REASON + "\n")
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    lines = _stop_lines(out)
    assert lines == ["  stop: team -- %s %s" % (TEAM_REASON, TEAM_LIFT)], out


def test_b1_config_placeholder_is_literal(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch, stop=TEAM_REASON)
    _, out, _ = _capture(lambda: foundry.status_cli(cfg))
    (line,) = _stop_lines(out)
    assert line.endswith("--config <config>)")
    assert len("<config>") == 8
    assert str(tmp_path) not in line, "placeholder must not be a real path"


# ==========================================================================
# Behavior 2 -- global sentinel wins over team
# ==========================================================================
def test_b2_global_wins_and_exactly_one_line(tmp_path, monkeypatch):
    _global(monkeypatch, True)
    cfg = _cfg(tmp_path, monkeypatch, stop=TEAM_REASON)
    expected_reason = foundry.gather_stop(cfg).reason
    _, out, _ = _capture(lambda: foundry.status_cli(cfg))
    lines = _stop_lines(out)
    assert len(lines) == 1, out
    assert lines[0] == "  stop: global -- %s %s" % (expected_reason, GLOBAL_LIFT)
    assert TEAM_LIFT not in out


def test_b2_global_without_team_file(tmp_path, monkeypatch):
    _global(monkeypatch, True)
    cfg = _cfg(tmp_path, monkeypatch)
    _, out, _ = _capture(lambda: foundry.status_cli(cfg))
    (line,) = _stop_lines(out)
    assert line.startswith("  stop: global -- ") and line.endswith(GLOBAL_LIFT)


# ==========================================================================
# Behavior 3 -- empty sentinel
# ==========================================================================
def test_b3_zero_byte_sentinel(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch, stop=b"")
    assert pathlib.Path(cfg.stop_file).stat().st_size == 0
    _, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert _stop_lines(out) == [
        "  stop: team -- (no reason recorded) %s" % TEAM_LIFT], out


# ==========================================================================
# Behavior 4 -- nothing stopped: byte-identical output
# ==========================================================================
def test_b4_no_stop_line_when_nothing_stopped(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch)
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc == 0
    assert _stop_lines(out) == []
    assert "stop:" not in out


def test_b4_unstopped_render_is_ten_lines_and_matches_old_shape(
        tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch)
    s = foundry.gather_status(cfg)
    assert s.stop_scope == "none" and s.stop_reason == ""
    assert len(s.render().splitlines()) == 10
    old_kw = {f: getattr(s, f) for f in OLD_FIELDS}
    built_without = foundry.StatusSummary(**old_kw)
    assert s.render() == built_without.render()


def test_b4_stopped_render_differs_only_by_the_stop_line(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch)
    _, base_out, _ = _capture(lambda: foundry.status_cli(cfg))
    pathlib.Path(cfg.stop_file).write_text(TEAM_REASON)
    _, stopped_out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert len(_stop_lines(stopped_out)) == 1
    filtered = "\n".join(ln for ln in stopped_out.splitlines()
                         if not ln.startswith("  stop:"))
    assert filtered == "\n".join(base_out.splitlines())


# ==========================================================================
# Behavior 5 -- verdict, exit code, position unchanged
# ==========================================================================
def test_b5_stopped_healthy_still_ok_and_line_position(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch, stop=TEAM_REASON)
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc == 0, out
    lines = _nonempty(out)
    assert lines[-1].startswith("verdict:")
    assert "verdict: OK" in out
    assert lines[-2].startswith("  stop: team -- ")


def test_b5_hotfix_still_returns_one_when_stopped(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch, stop=TEAM_REASON)
    flag = foundry.hotfix_flag_path(cfg)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("hotfix needed")
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc == 1, out
    assert len(_stop_lines(out)) == 1
    assert _nonempty(out)[-1].startswith("verdict:")


def test_b5_derived_fields_ignore_stop_fields():
    for shape in ({}, dict(hotfix=True), dict(postrelease="BROKEN"),
                  dict(speed_story=True), dict(postrelease=None, latest_iter=0)):
        base = _summarize(**shape)
        want = tuple(getattr(base, k) for k in DERIVED)
        for scope, reason in (("team", "r"), ("global", "g"), ("weird", "x"),
                              ("none", "")):
            s = _summarize(stop_scope=scope, stop_reason=reason, **shape)
            assert tuple(getattr(s, k) for k in DERIVED) == want, (shape, scope)
    assert _summarize(hotfix=True, stop_scope="team",
                      stop_reason="r").exit_code == 1


# ==========================================================================
# Behavior 6 -- JSON unchanged
# ==========================================================================
def test_b6_json_has_exactly_the_old_16_keys(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch, stop=TEAM_REASON)
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg, as_json=True))
    doc = json.loads(out)
    assert list(doc.keys()) == OLD_KEY_ORDER
    assert len(doc) == 16
    assert "stop_scope" not in doc and "stop_reason" not in doc
    assert TEAM_REASON not in out


# ==========================================================================
# Behavior 7 -- new fields and kwargs
# ==========================================================================
def test_b7_fields_appended_after_iters_since_last_ship():
    names = tuple(f.name for f in dataclasses.fields(foundry.StatusSummary))
    assert names[:11] == OLD_FIELDS
    assert names[11:] == ("stop_scope", "stop_reason")
    defaults = {f.name: f.default for f in dataclasses.fields(foundry.StatusSummary)}
    assert defaults["stop_scope"] == "none" and defaults["stop_reason"] == ""


def test_b7_summarize_status_kwargs_default_and_pass_through():
    s = _summarize()
    assert (s.stop_scope, s.stop_reason) == ("none", "")
    s2 = _summarize(stop_scope="team", stop_reason="why")
    assert (s2.stop_scope, s2.stop_reason) == ("team", "why")


# ==========================================================================
# Behavior 8 -- render is pure over the fields
# ==========================================================================
def test_b8_render_global_from_fields():
    text = _summarize(stop_scope="global", stop_reason="x").render()
    assert "  stop: global -- x %s" % GLOBAL_LIFT in text.splitlines()


def test_b8_render_team_from_fields():
    text = _summarize(stop_scope="team", stop_reason="y").render()
    assert "  stop: team -- y %s" % TEAM_LIFT in text.splitlines()


def test_b8_unknown_scopes_render_no_line():
    base = _summarize().render()
    for scope in ("none", "weird", "", "Team", " team"):
        text = _summarize(stop_scope=scope, stop_reason="x").render()
        assert _stop_lines(text) == [], scope
        assert text == base, scope


# ==========================================================================
# Behavior 9 -- bare-name gather_stop seam
# ==========================================================================
def test_b9_patched_gather_stop_drives_the_line(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch)            # no real sentinel at all
    monkeypatch.setattr(foundry, "gather_stop", lambda cfg: foundry.StopRow(
        product=cfg.name, sentinel="s", stopped=True, scope="team",
        reason="patched"))
    _, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert _stop_lines(out) == ["  stop: team -- patched %s" % TEAM_LIFT], out
    s = foundry.gather_status(cfg)
    assert (s.stop_scope, s.stop_reason) == ("team", "patched")


# ==========================================================================
# Behavior 10 -- never raises
# ==========================================================================
def test_b10_raising_gather_stop_is_swallowed(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch, stop=TEAM_REASON)

    def boom(cfg):
        raise RuntimeError("seam exploded")

    monkeypatch.setattr(foundry, "gather_stop", boom)
    s = foundry.gather_status(cfg)
    assert s.stop_scope == "none"
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc == 0
    assert _stop_lines(out) == []
    assert _nonempty(out)[-1].startswith("verdict:")


# ==========================================================================
# Behavior 11 -- read-only; company-status unchanged
# ==========================================================================
def test_b11_status_writes_nothing(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch, stop=TEAM_REASON)
    before = _snapshot_tree(tmp_path)
    _capture(lambda: foundry.status_cli(cfg))
    _capture(lambda: foundry.status_cli(cfg, as_json=True))
    assert _snapshot_tree(tmp_path) == before


def test_b11_status_does_not_create_a_sentinel(tmp_path, monkeypatch):
    _global(monkeypatch, False)
    cfg = _cfg(tmp_path, monkeypatch)
    _capture(lambda: foundry.status_cli(cfg))
    assert not pathlib.Path(cfg.stop_file).exists()


def _company_out(tmp_path, monkeypatch, stopped):
    _global(monkeypatch, False)
    root = tmp_path / ("stopped" if stopped else "clear")
    root.mkdir()
    cfg = _cfg(root, monkeypatch, name="alpha",
               stop=TEAM_REASON if stopped else None)
    cfg_path = root / "alpha" / "config.json"
    disp = root / "foundry.config.json"
    disp.write_text(json.dumps({"work_items": [
        {"name": "alpha", "config": str(cfg_path), "enabled": True}]}))
    assert pathlib.Path(cfg.stop_file).exists() is stopped
    return _capture(lambda: foundry.company_status_cli(str(disp)))


def test_b11_company_status_per_product_line_and_rc_unchanged(
        tmp_path, monkeypatch):
    rc_clear, out_clear, _ = _company_out(tmp_path, monkeypatch, False)
    rc_stop, out_stop, _ = _company_out(tmp_path, monkeypatch, True)
    assert rc_stop == rc_clear == 0, (out_clear, out_stop)
    pick = lambda out: [ln for ln in out.splitlines()   # noqa: E731
                        if ln.strip().startswith("- alpha:")]
    assert pick(out_clear), out_clear
    assert pick(out_stop) == pick(out_clear)
