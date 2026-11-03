"""Black-box behaviour tests for iter 509 -- `foundry status` (and so
`company-status`) reads the post-release verdict from the most recent PUSHED
iteration's dir, falling back to the newest iteration dir only when no PUSHED
outcome exists.

ISOLATION CONTRACT (honored): written from the iter-509 PM spec's Expected
Behaviors (1-9), the README, and the existing tests/ conventions ONLY. The
implementation source, the engineer's/reviewer's notes and `git diff` were NOT
read. Every fixture is a tmp_path product (no gitignored real state is used).
"""
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

HEALTHY = "post-release verification report\n\nPOSTRELEASE: HEALTHY\n"
BROKEN = "post-release verification report\n\nPOSTRELEASE: BROKEN\n"
PUSHED = "final gate\nVERIFIED: suite=green\n\nACTION: PUSHED abc1234\n"
REVERTED = "final gate\n\nACTION: REVERTED suite red\n"


def _capture(fn):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


class _LagStub:
    def render(self):
        return "  live-lag: OK -- stub"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(foundry, "live_lag_status",
                        lambda cfg, *a, **k: _LagStub())
    monkeypatch.setattr(foundry, "global_stop", lambda: False)


def _mk(tmp_path, spec, name="demoprod"):
    """spec = {iter_no: {filename: body}} -> loaded ProductConfig."""
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
    cfg_path = base / "config.json"
    cfg_path.write_text(json.dumps(data))
    cfg = foundry.load_config(str(cfg_path))
    for it, files in spec.items():
        d = pathlib.Path(cfg.state) / ("iter-%02d" % it)
        d.mkdir(parents=True, exist_ok=True)
        for fname, body in files.items():
            (d / fname).write_text(body)
    return cfg, cfg_path


def _tree(root):
    root = pathlib.Path(root)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _pr_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("  post-release:")]


# ---------------------------------------------------------------- B1
def test_b1_last_ship_healthy_read_while_newer_dir_in_flight(tmp_path):
    cfg, _ = _mk(tmp_path, {1: {"final.md": PUSHED, "postrelease.md": HEALTHY},
                            2: {"pm.md": "spec\n"}})
    s = foundry.gather_status(cfg)
    assert s.latest_iter == 2
    assert s.last_ship_iter == 1
    assert s.postrelease == "HEALTHY"
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc == 0
    assert "  post-release: HEALTHY" in out.splitlines()
    assert "  post-release: unknown" not in out.splitlines()


# ---------------------------------------------------------------- B2
def test_b2_last_ship_broken_sets_attention_and_exit_1(tmp_path):
    cfg, _ = _mk(tmp_path, {1: {"final.md": PUSHED, "postrelease.md": BROKEN},
                            2: {"pm.md": "spec\n"}})
    s = foundry.gather_status(cfg)
    assert s.postrelease == "BROKEN"
    assert s.attention is True
    assert s.exit_code == 1
    assert s.verdict == "ATTENTION"
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc == 1
    assert "  post-release: BROKEN" in out.splitlines()
    rc_j, out_j, _ = _capture(lambda: foundry.status_cli(cfg, as_json=True))
    assert rc_j == 1
    doc = json.loads(out_j)  # exactly one JSON document
    assert doc["postrelease"] == "BROKEN"


# ---------------------------------------------------------------- B3
def test_b3_revert_never_counts_as_last_ship(tmp_path):
    cfg, _ = _mk(tmp_path, {1: {"final.md": PUSHED, "postrelease.md": HEALTHY},
                            2: {"final.md": REVERTED},
                            3: {"pm.md": "spec\n"}})
    s = foundry.gather_status(cfg)
    assert s.latest_iter == 3
    assert s.last_ship_iter == 1
    assert s.postrelease == "HEALTHY"


def test_b3b_revert_carrying_a_postrelease_is_still_ignored(tmp_path):
    # Stronger reading: even a stray BROKEN postrelease.md in a REVERTED dir
    # must not be "the last ship's" verdict.
    cfg, _ = _mk(tmp_path, {1: {"final.md": PUSHED, "postrelease.md": HEALTHY},
                            2: {"final.md": REVERTED, "postrelease.md": BROKEN},
                            3: {"pm.md": "spec\n"}})
    s = foundry.gather_status(cfg)
    assert s.last_ship_iter == 1
    assert s.postrelease == "HEALTHY"
    assert s.exit_code == 0


# ---------------------------------------------------------------- B4
def test_b4_newest_ship_wins(tmp_path):
    cfg, _ = _mk(tmp_path, {1: {"final.md": PUSHED, "postrelease.md": BROKEN},
                            2: {"final.md": PUSHED, "postrelease.md": HEALTHY},
                            3: {"pm.md": "spec\n"}})
    s = foundry.gather_status(cfg)
    assert s.last_ship_iter == 2
    assert s.postrelease == "HEALTHY"
    assert s.exit_code == 0


def test_b4b_newest_ship_wins_across_digit_widths(tmp_path):
    # iter-99 vs iter-101: numeric, not lexical, ordering.
    cfg, _ = _mk(tmp_path, {99: {"final.md": PUSHED, "postrelease.md": HEALTHY},
                            101: {"final.md": PUSHED, "postrelease.md": BROKEN},
                            102: {"pm.md": "spec\n"}})
    s = foundry.gather_status(cfg)
    assert s.latest_iter == 102
    assert s.last_ship_iter == 101
    assert s.postrelease == "BROKEN"
    assert s.exit_code == 1


# ---------------------------------------------------------------- B5
def test_b5_last_ship_without_postrelease_is_unknown_no_fallback(tmp_path):
    cfg, _ = _mk(tmp_path, {1: {"final.md": PUSHED, "postrelease.md": BROKEN},
                            2: {"final.md": PUSHED}})
    s = foundry.gather_status(cfg)
    assert s.last_ship_iter == 2
    assert s.postrelease is None
    assert s.exit_code == 0
    assert _pr_lines(s.render()) == ["  post-release: unknown"]


def test_b5_spec_shape_healthy_older(tmp_path):
    cfg, _ = _mk(tmp_path, {1: {"final.md": PUSHED, "postrelease.md": HEALTHY},
                            2: {"final.md": PUSHED}})
    s = foundry.gather_status(cfg)
    assert s.postrelease is None
    assert s.exit_code == 0
    rc, out, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc == 0
    assert _pr_lines(out) == ["  post-release: unknown"]


# ---------------------------------------------------------------- B6
@pytest.mark.parametrize("body,verdict,code", [(HEALTHY, "HEALTHY", 0),
                                                (BROKEN, "BROKEN", 1)])
def test_b6_fallback_to_newest_dir_when_nothing_pushed(tmp_path, body,
                                                       verdict, code):
    cfg, _ = _mk(tmp_path, {1: {"pm.md": "spec\n"},
                            2: {"postrelease.md": body}})
    s = foundry.gather_status(cfg)
    assert s.last_ship_iter is None
    assert s.latest_iter == 2
    assert s.postrelease == verdict
    assert s.exit_code == code


def test_b6b_only_reverts_also_falls_back_to_newest(tmp_path):
    cfg, _ = _mk(tmp_path, {1: {"final.md": REVERTED, "postrelease.md": BROKEN},
                            2: {"final.md": REVERTED, "postrelease.md": HEALTHY}})
    s = foundry.gather_status(cfg)
    assert s.last_ship_iter is None
    assert s.postrelease == "HEALTHY"


# ---------------------------------------------------------------- B7
def test_b7_outcomes_walk_raising_degrades_to_newest_dir(tmp_path,
                                                         monkeypatch):
    cfg, _ = _mk(tmp_path, {1: {"final.md": PUSHED, "postrelease.md": BROKEN},
                            2: {"postrelease.md": HEALTHY}})
    # anti-vacuity: without the patch the PUSHED iter-01 BROKEN verdict is read
    assert foundry.gather_status(cfg).postrelease == "BROKEN"

    def _boom(*a, **k):
        raise RuntimeError("outcomes walk exploded")

    monkeypatch.setattr(foundry, "gather_outcomes", _boom)
    s = foundry.gather_status(cfg)
    assert s.last_ship_iter is None
    assert s.latest_iter == 2
    assert s.postrelease == "HEALTHY"


# ---------------------------------------------------------------- B8
def test_b8_company_status_follows_last_ship_verdict(tmp_path):
    root = tmp_path / "fleet"
    root.mkdir()
    cfg, cfg_path = _mk(root, {1: {"final.md": PUSHED, "postrelease.md": BROKEN},
                               2: {"pm.md": "spec\n"}}, name="alpha")
    disp = root / "foundry.config.json"
    disp.write_text(json.dumps({"work_items": [
        {"name": "alpha", "config": str(cfg_path), "enabled": True}]}))
    rc, out, _ = _capture(lambda: foundry.company_status_cli(str(disp)))
    assert rc == 1, out


def test_b8b_company_status_ok_when_last_ship_healthy(tmp_path):
    # Anti-vacuity for B8: same shape with HEALTHY must not trip exit 1.
    root = tmp_path / "fleet"
    root.mkdir()
    cfg, cfg_path = _mk(root, {1: {"final.md": PUSHED, "postrelease.md": HEALTHY},
                               2: {"pm.md": "spec\n"}}, name="alpha")
    disp = root / "foundry.config.json"
    disp.write_text(json.dumps({"work_items": [
        {"name": "alpha", "config": str(cfg_path), "enabled": True}]}))
    rc, out, _ = _capture(lambda: foundry.company_status_cli(str(disp)))
    assert rc == 0, out


# ---------------------------------------------------------------- B9
SHAPES = [
    {1: {"final.md": PUSHED, "postrelease.md": HEALTHY}, 2: {"pm.md": "s\n"}},
    {1: {"final.md": PUSHED, "postrelease.md": BROKEN}, 2: {"pm.md": "s\n"}},
    {1: {"final.md": PUSHED, "postrelease.md": HEALTHY},
     2: {"final.md": REVERTED}, 3: {"pm.md": "s\n"}},
    {1: {"final.md": PUSHED, "postrelease.md": BROKEN},
     2: {"final.md": PUSHED, "postrelease.md": HEALTHY}, 3: {"pm.md": "s\n"}},
    {1: {"final.md": PUSHED, "postrelease.md": HEALTHY},
     2: {"final.md": PUSHED}},
    {2: {"postrelease.md": HEALTHY}},
]


@pytest.mark.parametrize("idx", range(len(SHAPES)))
def test_b9_read_only(tmp_path, idx):
    cfg, _ = _mk(tmp_path, SHAPES[idx])
    root = tmp_path / "demoprod"
    before = _tree(root)
    assert before  # anti-vacuity: the fixture tree is non-empty
    foundry.gather_status(cfg)
    _capture(lambda: foundry.status_cli(cfg))
    _capture(lambda: foundry.status_cli(cfg, as_json=True))
    assert _tree(root) == before
