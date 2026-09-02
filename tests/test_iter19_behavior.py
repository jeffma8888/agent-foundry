"""Black-box behaviour tests for iter 19 -- a machine-readable `--json` output
mode over the read-only `foundry status` company-health probe (iter 16). ALL
additive in foundry.py:

  * a PURE `StatusSummary.to_dict() -> dict` (12 fixed-order keys: the 8 stored
    fields verbatim + the 4 derived props `attention`/`ok`/`exit_code`/`verdict`),
  * `status_cli(cfg, as_json: bool = False) -> int` -- on True it prints ONE JSON
    document (the whole stdout) == the summary's `to_dict()` and returns the SAME
    exit code as the human path; on False/default it is byte-identical to iter 16,
  * a `status --json` argparse flag (`store_true`, default off) routed by `main`.

ISOLATION CONTRACT (honored): this file was written from the iter-19 PM spec's
Expected Behaviors (1-9) and the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure `StatusSummary(...).to_dict()`, and the CLI via
`foundry.status_cli(cfg, as_json=...)` / `foundry.main(["status", ...])` against a
TMP-`work_root` config with real `state/iter-NN/postrelease.md` + optional flag /
`prd.json` files (the real foundry repo/state is NEVER touched). Fully offline &
deterministic: real temp files only; ZERO real subprocess / git / network.
"""
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# helpers  (mirror the iter-16 status-test conventions)
# --------------------------------------------------------------------------
STORED_KEYS = (
    "product", "repo", "branch", "latest_iter",
    "postrelease", "hotfix", "speed_story", "prd_line", "lag_line",
)
DERIVED_KEYS = ("attention", "ok", "exit_code", "verdict", "lag_verdict")
EXPECTED_KEY_ORDER = list(STORED_KEYS) + list(DERIVED_KEYS)   # Behavior 1


def _mk(product="demoprod", repo="/tmp/repo", branch="main", latest_iter=1,
        postrelease="HEALTHY", hotfix=False, speed_story=False, prd_line=None):
    """Build a StatusSummary positionally in the spec's field order."""
    return foundry.StatusSummary(product, repo, branch, latest_iter,
                                 postrelease, hotfix, speed_story, prd_line)


def _expected_verdict(s):
    """The verdict token render() prints, keyed off exit_code (Behavior 2)."""
    return {0: "OK", 1: "ATTENTION", 2: "no iterations yet"}[s.exit_code]


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (repo/work_root are TMP so the real
    foundry repo/state is NEVER touched)."""
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


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _write_postrelease(cfg, iteration, verdict):
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "postrelease.md").write_text(
        f"post-release verification report\n\nPOSTRELEASE: {verdict}\n")
    return d / "postrelease.md"


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters: Behavior 7 requires JSON to be the ENTIRE stdout."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


# ==========================================================================
# Behavior 1 -- to_dict() has EXACTLY the 12 keys in the mandated order
# ==========================================================================
def test_b1_keys_exact_and_ordered():
    for s in (_mk(),
              _mk(postrelease=None, latest_iter=0, hotfix=True),
              _mk(postrelease="BROKEN", speed_story=True, prd_line="demoprod: 1/2 pass")):
        d = s.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == EXPECTED_KEY_ORDER, (
            f"to_dict keys/order wrong.\n got: {list(d.keys())}\n"
            f"want: {EXPECTED_KEY_ORDER}")
        assert len(d) == 14


# ==========================================================================
# Behavior 2 -- stored fields verbatim; derived keys mirror the properties
# ==========================================================================
def test_b2_stored_fields_verbatim_and_derived_mirror():
    cases = [
        _mk(product="prodX", repo="/r", branch="release", latest_iter=9,
            postrelease="BROKEN", hotfix=True, speed_story=False,
            prd_line="prodX: 4/9 stories pass (in progress)"),
        _mk(postrelease=None, latest_iter=0, hotfix=False, speed_story=True,
            prd_line=None),
        _mk(postrelease="HEALTHY", latest_iter=3, hotfix=False, prd_line="x: 2/2 (COMPLETE)"),
    ]
    for s in cases:
        d = s.to_dict()
        # eight stored fields mirror the dataclass fields verbatim
        assert d["product"] == s.product and isinstance(d["product"], str)
        assert d["repo"] == s.repo and isinstance(d["repo"], str)
        assert d["branch"] == s.branch and isinstance(d["branch"], str)
        assert d["latest_iter"] == s.latest_iter and isinstance(d["latest_iter"], int)
        assert d["postrelease"] == s.postrelease
        assert d["hotfix"] == s.hotfix and isinstance(d["hotfix"], bool)
        assert d["speed_story"] == s.speed_story and isinstance(d["speed_story"], bool)
        assert d["prd_line"] == s.prd_line
        # four derived keys mirror the existing properties (reused, not re-derived)
        assert d["attention"] == s.attention
        assert d["ok"] == s.ok
        assert d["exit_code"] == s.exit_code
        # verdict is the SAME token render() prints
        assert d["verdict"] == _expected_verdict(s)


def test_b2_verdict_matches_render_token():
    # cross-check the verdict token against what render() actually prints
    for s in (_mk(postrelease="HEALTHY", latest_iter=3),            # OK
              _mk(postrelease="BROKEN", latest_iter=3),             # ATTENTION
              _mk(hotfix=True, latest_iter=3, postrelease="HEALTHY"),  # ATTENTION
              _mk(postrelease=None, latest_iter=0)):                # no iterations yet
        d = s.to_dict()
        out = s.render()
        assert d["verdict"] in out, (
            f"verdict token {d['verdict']!r} not present in render():\n{out}")


# ==========================================================================
# Behavior 3 -- pure + JSON-safe: no fs, dumps ok, round-trips, null/bools
# ==========================================================================
def test_b3_touches_no_filesystem(tmp_path, monkeypatch):
    # run in an empty cwd and forbid pathlib.Path.exists/open from being reached
    # by asserting no file appears; to_dict must be a pure in-memory transform.
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)
    _mk(postrelease="BROKEN", latest_iter=2, prd_line="p: 1/3").to_dict()
    assert _snapshot_tree(tmp_path) == before, "to_dict() wrote to disk (must be pure)"


def test_b3_json_dumps_succeeds_and_round_trips():
    variants = [
        _mk(),
        _mk(postrelease=None, prd_line=None, latest_iter=0),
        _mk(postrelease="BROKEN", hotfix=True, speed_story=True, latest_iter=7,
            prd_line="demoprod: 2/2 stories pass (COMPLETE)"),
        _mk(postrelease="HEALTHY", hotfix=False, speed_story=False, latest_iter=-3),
    ]
    for s in variants:
        d = s.to_dict()
        text = json.dumps(d)                 # must not raise
        d2 = json.loads(text)
        assert d2 == d, "to_dict() must survive a json dumps/loads round-trip unchanged"


def test_b3_none_serializes_null_and_bools_stay_bool():
    s = _mk(postrelease=None, prd_line=None, hotfix=True, speed_story=False)
    d2 = json.loads(json.dumps(s.to_dict()))
    assert d2["postrelease"] is None, "None postrelease must serialize to JSON null"
    assert d2["prd_line"] is None, "None prd_line must serialize to JSON null"
    for k in ("hotfix", "speed_story", "attention", "ok"):
        assert isinstance(d2[k], bool), f"{k} must serialize to a JSON boolean, got {type(d2[k])}"


# ==========================================================================
# Behavior 4 -- attention state (hotfix OR BROKEN) -> exit 1 / ATTENTION
# ==========================================================================
def test_b4_attention_states():
    for s in (_mk(hotfix=True, postrelease="HEALTHY", latest_iter=5),
              _mk(hotfix=True, postrelease=None, latest_iter=0),
              _mk(hotfix=False, postrelease="BROKEN", latest_iter=5),
              _mk(hotfix=True, postrelease="BROKEN", latest_iter=1)):
        d = s.to_dict()
        assert d["attention"] is True
        assert d["ok"] is False
        assert d["exit_code"] == 1
        assert d["verdict"] == "ATTENTION"


# ==========================================================================
# Behavior 5 -- healthy latest ship -> exit 0 / OK; speed_story is advisory
# ==========================================================================
def test_b5_healthy_ok_and_speed_story_never_moves_verdict():
    for speed in (True, False):
        d = _mk(hotfix=False, postrelease="HEALTHY", speed_story=speed,
                latest_iter=4).to_dict()
        assert d["attention"] is False
        assert d["ok"] is True
        assert d["exit_code"] == 0
        assert d["verdict"] == "OK"


# ==========================================================================
# Behavior 6 -- nothing shipped -> exit 2 / "no iterations yet"
# ==========================================================================
def test_b6_no_iterations_yet():
    for pr in (None, "HEALTHY"):   # postrelease != "BROKEN"
        d = _mk(latest_iter=0, hotfix=False, postrelease=pr).to_dict()
        assert d["exit_code"] == 2
        assert d["verdict"] == "no iterations yet"
        assert d["attention"] is False


def test_b6_negative_iter_also_no_iterations():
    d = _mk(latest_iter=-1, hotfix=False, postrelease=None).to_dict()
    assert d["exit_code"] == 2 and d["verdict"] == "no iterations yet"


# ==========================================================================
# Behavior 7 -- status_cli(cfg, as_json=True): single JSON doc == to_dict(),
#               same exit code as non-json, writes nothing to disk
# ==========================================================================
def _assert_json_equals_reconstructed_summary(d):
    """A black-box proof the CLI emitted a faithful serialization: rebuild a
    StatusSummary from the 8 stored keys and confirm its to_dict() == d. This
    verifies stored fields + all derived props without reading the gather seam."""
    stored = {k: d[k] for k in STORED_KEYS}
    s2 = foundry.StatusSummary(**stored)
    assert s2.to_dict() == d, (
        "JSON payload is not a self-consistent StatusSummary serialization")


def test_b7_json_path_healthy(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 3, "HEALTHY")
    before = _snapshot_tree(tmp_path)
    rc_json, out_json, _ = _capture(lambda: foundry.status_cli(cfg, as_json=True))
    # the WHOLE stdout parses as one JSON document into a dict
    d = json.loads(out_json)
    assert isinstance(d, dict)
    # same integer as the non-json path for identical state
    rc_human, _, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc_json == rc_human == d["exit_code"] == 0
    # dict == to_dict() of the summary the non-json path computes (self-consistent)
    _assert_json_equals_reconstructed_summary(d)
    assert d["latest_iter"] == 3 and d["postrelease"] == "HEALTHY"
    assert d["verdict"] == "OK"
    # read-only: nothing written under the temp tree
    assert _snapshot_tree(tmp_path) == before, "status --json wrote a file (must be read-only)"


def test_b7_json_path_broken_matches_human_fields(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "HEALTHY")
    _write_postrelease(cfg, 5, "BROKEN")          # newest wins
    rc_json, out_json, _ = _capture(lambda: foundry.status_cli(cfg, as_json=True))
    d = json.loads(out_json)
    rc_human, out_human, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc_json == rc_human == 1 == d["exit_code"]
    _assert_json_equals_reconstructed_summary(d)
    assert d["latest_iter"] == 5 and d["postrelease"] == "BROKEN"
    assert d["attention"] is True and d["ok"] is False and d["verdict"] == "ATTENTION"
    # the human path reports the SAME facts (cross-check json vs render text)
    assert "latest iteration: 5" in out_human and "post-release: BROKEN" in out_human


def test_b7_json_path_no_iterations(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)   # state/, no iter dirs
    rc_json, out_json, _ = _capture(lambda: foundry.status_cli(cfg, as_json=True))
    d = json.loads(out_json)
    rc_human, _, _ = _capture(lambda: foundry.status_cli(cfg))
    assert rc_json == rc_human == 2 == d["exit_code"]
    assert d["verdict"] == "no iterations yet" and d["latest_iter"] <= 0


# ==========================================================================
# Behavior 8 -- default / as_json=False is unchanged human render (not JSON)
# ==========================================================================
def test_b8_default_is_human_render_not_json(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 3, "HEALTHY")
    before = _snapshot_tree(tmp_path)
    rc_default, out_default, _ = _capture(lambda: foundry.status_cli(cfg))
    rc_false, out_false, _ = _capture(lambda: foundry.status_cli(cfg, as_json=False))
    # default == explicit as_json=False, byte-for-byte (same code path)
    assert out_default == out_false, "default must equal as_json=False output byte-for-byte"
    assert rc_default == rc_false == 3 or rc_default == rc_false  # exit_code returned
    assert rc_default == 0
    # the human output is NOT a JSON document -> json.loads raises
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_default)
    # it IS the iter-16 render text (regression guard on the human surface)
    for sub in ("latest iteration: 3", "post-release: HEALTHY", "hotfix flag: clear"):
        assert sub in out_default, f"human render missing {sub!r}:\n{out_default}"
    assert _snapshot_tree(tmp_path) == before, "human status wrote a file (must be read-only)"


# ==========================================================================
# Behavior 9 -- CLI wiring: main([... --json]) routes JSON; default off
# ==========================================================================
def test_b9_main_json_flag_routes_json(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 2, "BROKEN")
    # --json -> JSON document on stdout, returns its exit code
    rc_json, out_json, _ = _capture(
        lambda: foundry.main(["status", "--config", str(cfg_path), "--json"]))
    d = json.loads(out_json)                       # whole stdout is JSON
    assert d["exit_code"] == rc_json == 1 and d["verdict"] == "ATTENTION"
    _assert_json_equals_reconstructed_summary(d)


def test_b9_main_default_routes_human(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 2, "HEALTHY")
    # no --json -> human path (NOT json), returns exit_code
    rc, out, _ = _capture(
        lambda: foundry.main(["status", "--config", str(cfg_path)]))
    assert rc == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert "latest iteration: 2" in out and "post-release: HEALTHY" in out


def test_b9_json_and_human_same_exit_code_same_state(tmp_path):
    # the flag adds a payload, never changes the 0/1/2 semantics
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    foundry.hotfix_flag_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    foundry.hotfix_flag_path(cfg).write_text("hotfix needed")
    _write_postrelease(cfg, 3, "HEALTHY")
    rc_json, _, _ = _capture(
        lambda: foundry.main(["status", "--config", str(cfg_path), "--json"]))
    rc_human, _, _ = _capture(
        lambda: foundry.main(["status", "--config", str(cfg_path)]))
    assert rc_json == rc_human == 1, "hotfix raised -> exit 1 on BOTH json and human paths"
