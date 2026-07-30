"""Black-box behaviour tests for iter 03 -- wiring the post-release fresh-clone
verification gate into the product loop (item 11, bite 2 of 2).

ISOLATION: written from the iter-03 PM spec (Expected Behaviors 1-13), the role
output contracts under `roles/` (the observable `VERDICT:`/`RESULT:`/`ACTION:`
sentinel vocabulary), and the product's own runtime interface only. The
implementation source of `foundry.py`, the engineer/reviewer notes for this
iteration, and `git diff` were NOT read. Public function signatures and the
shipped-dict shape were discovered by runtime introspection / driving the public
interface (permitted), not by reading source bodies.

Every external effect is forced through the documented module-level seams the
spec names -- `foundry.verify_fresh_clone`, `foundry.run_stage`,
`foundry.head_of_branch`, `foundry.postrelease_step`, `foundry.revert_repo`,
`foundry.power_state` -- so the suite is fully offline and deterministic: no real
network, git clone, or subprocess execution (the only subprocess calls are the
Behavior-13 `--help`/`import` probes, which touch no network).
"""
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (asserted importable in Behavior 13)


# --------------------------------------------------------------------------
# helpers / fixtures
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """Mirror the config-writing helper used by the other test modules."""
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _iter_dir(cfg, iteration):
    return cfg.state / f"iter-{iteration:02d}"


def _artifact(cfg, iteration):
    return _iter_dir(cfg, iteration) / "postrelease.md"


def _last_nonempty_line(path):
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def make_verify(recorder, result):
    """Scripted, offline replacement for foundry.verify_fresh_clone that records
    the args it receives and returns a fixed PostReleaseResult."""
    def _v(cfg, expected_sha, clone_dir, *a, **k):
        recorder.append({"cfg": cfg, "expected_sha": expected_sha,
                         "clone_dir": clone_dir})
        return result
    return _v


# ==========================================================================
# Behavior 1 -- hotfix_flag_path returns work_root/HOTFIX_NEEDED.md
# ==========================================================================
def test_b1_hotfix_flag_path(cfg):
    p = foundry.hotfix_flag_path(cfg)
    assert isinstance(p, pathlib.Path)
    assert p == pathlib.Path(cfg.work_root) / "HOTFIX_NEEDED.md"


# ==========================================================================
# Behavior 2 -- write_hotfix_flag creates the file with sha + detail; overwrites
# ==========================================================================
def test_b2_write_creates_with_sha_and_detail(cfg):
    foundry.write_hotfix_flag(cfg, "abc1234", "the fresh-clone smoke test failed")
    p = foundry.hotfix_flag_path(cfg)
    assert p.exists()
    txt = p.read_text()
    assert "abc1234" in txt                         # sha verbatim
    assert "the fresh-clone smoke test failed" in txt  # detail verbatim


def test_b2_write_overwrites_no_append_pileup(cfg):
    foundry.write_hotfix_flag(cfg, "old1111", "old breakage detail")
    foundry.write_hotfix_flag(cfg, "new2222", "new breakage detail")
    txt = foundry.hotfix_flag_path(cfg).read_text()
    assert "new2222" in txt and "new breakage detail" in txt
    assert "old1111" not in txt, "old sha leaked -> file appended, not overwritten"
    assert "old breakage detail" not in txt


def test_b2_write_does_not_raise_for_normal_dir(cfg):
    # must not raise for a normal writable work_root
    foundry.write_hotfix_flag(cfg, "s", "d")
    assert foundry.hotfix_flag_path(cfg).exists()


# ==========================================================================
# Behavior 3 -- clear_hotfix_flag removes if present; silent no-op if absent
# ==========================================================================
def test_b3_clear_removes_existing(cfg):
    foundry.write_hotfix_flag(cfg, "s", "d")
    assert foundry.hotfix_flag_path(cfg).exists()
    foundry.clear_hotfix_flag(cfg)
    assert not foundry.hotfix_flag_path(cfg).exists()


def test_b3_clear_absent_is_silent_noop(cfg):
    assert not foundry.hotfix_flag_path(cfg).exists()
    foundry.clear_hotfix_flag(cfg)  # must NOT raise
    assert not foundry.hotfix_flag_path(cfg).exists()


# ==========================================================================
# Behavior 4 -- postrelease_step writes the sentinel artifact on every enabled path
# ==========================================================================
@pytest.mark.parametrize("healthy,skipped,sentinel", [
    (True, False, "POSTRELEASE: HEALTHY"),
    (False, False, "POSTRELEASE: BROKEN"),
])
def test_b4_writes_sentinel_artifact(cfg, monkeypatch, healthy, skipped, sentinel):
    result = foundry.PostReleaseResult(healthy, skipped, "detail-token-XYZ")
    assert result.sentinel == sentinel  # sanity: fixture matches expectation
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify([], result))
    ret = foundry.postrelease_step(cfg, 3, "sha99abcd")

    art = _artifact(cfg, 3)
    assert art.exists(), "postrelease.md artifact not written"
    assert _last_nonempty_line(art) == sentinel
    txt = art.read_text()
    assert "sha99abcd" in txt, "expected_sha missing from artifact"
    assert "detail-token-XYZ" in txt, "result.detail missing from artifact"
    assert ret.sentinel == sentinel


def test_b4_artifact_iteration_zero_padded(cfg, monkeypatch):
    result = foundry.PostReleaseResult(True, False, "ok")
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify([], result))
    foundry.postrelease_step(cfg, 7, "sha")
    assert _artifact(cfg, 7).exists()          # -> iter-07/postrelease.md
    assert (cfg.state / "iter-07" / "postrelease.md").exists()


# ==========================================================================
# Behavior 5 -- genuine HEALTHY (healthy & not skipped) clears a pre-existing flag
# ==========================================================================
def test_b5_genuine_healthy_clears_flag(cfg, monkeypatch):
    foundry.write_hotfix_flag(cfg, "stalesha", "stale breakage")  # pre-existing
    assert foundry.hotfix_flag_path(cfg).exists()
    result = foundry.PostReleaseResult(True, False, "all green on fresh clone")
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify([], result))

    ret = foundry.postrelease_step(cfg, 3, "newsha123")
    assert not foundry.hotfix_flag_path(cfg).exists(), "genuine HEALTHY did not clear the flag"
    assert _last_nonempty_line(_artifact(cfg, 3)) == "POSTRELEASE: HEALTHY"
    assert ret.sentinel == "POSTRELEASE: HEALTHY"


# ==========================================================================
# Behavior 6 -- infra-skipped HEALTHY does NOT create and does NOT clear the flag
# ==========================================================================
def test_b6_infra_skip_leaves_existing_flag_intact(cfg, monkeypatch):
    foundry.write_hotfix_flag(cfg, "keepsha", "keep this real breakage")
    before = foundry.hotfix_flag_path(cfg).read_text()
    result = foundry.PostReleaseResult(True, True, "clone infra failed -> skipped")
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify([], result))

    ret = foundry.postrelease_step(cfg, 3, "sha")
    assert foundry.hotfix_flag_path(cfg).exists(), "infra-skip wrongly cleared a real hotfix"
    assert foundry.hotfix_flag_path(cfg).read_text() == before
    assert _last_nonempty_line(_artifact(cfg, 3)) == "POSTRELEASE: HEALTHY"
    assert ret.skipped_infra is True


def test_b6_infra_skip_does_not_raise_false_flag(cfg, monkeypatch):
    assert not foundry.hotfix_flag_path(cfg).exists()
    result = foundry.PostReleaseResult(True, True, "skipped")
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify([], result))
    foundry.postrelease_step(cfg, 3, "sha")
    assert not foundry.hotfix_flag_path(cfg).exists(), "infra-skip raised a false hotfix flag"


# ==========================================================================
# Behavior 7 -- BROKEN raises the flag with the sha + detail
# ==========================================================================
def test_b7_broken_raises_flag(cfg, monkeypatch):
    assert not foundry.hotfix_flag_path(cfg).exists()
    result = foundry.PostReleaseResult(False, False, "tests failed on fresh clone")
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify([], result))

    ret = foundry.postrelease_step(cfg, 3, "brokensha9")
    p = foundry.hotfix_flag_path(cfg)
    assert p.exists(), "BROKEN did not raise the hotfix flag"
    txt = p.read_text()
    assert "brokensha9" in txt              # sha
    assert "tests failed on fresh clone" in txt  # detail
    assert _last_nonempty_line(_artifact(cfg, 3)) == "POSTRELEASE: BROKEN"
    assert ret.sentinel == "POSTRELEASE: BROKEN"


# ==========================================================================
# Behavior 8 -- disabled is a no-op skip (verify never called; flag untouched)
# ==========================================================================
def test_b8_disabled_is_noop_skip(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, postrelease_enabled=False)))
    assert cfg.postrelease_enabled is False
    foundry.write_hotfix_flag(cfg, "presha", "pre-existing detail")
    before = foundry.hotfix_flag_path(cfg).read_text()

    def _must_not_call(*a, **k):
        raise AssertionError("verify_fresh_clone called while postrelease disabled")
    monkeypatch.setattr(foundry, "verify_fresh_clone", _must_not_call)

    ret = foundry.postrelease_step(cfg, 3, "sha")  # must not raise (verify not called)
    art = _artifact(cfg, 3)
    assert art.exists()
    assert _last_nonempty_line(art) == "POSTRELEASE: HEALTHY"
    low = art.read_text().lower()
    # NOTE (ambiguity): the spec says the artifact "notes verification was
    # disabled" without fixing the exact wording; we accept any "disab"/"skip"
    # phrasing. Flagged to the PM as a wording ambiguity.
    assert ("disab" in low) or ("skip" in low), \
        "disabled artifact does not note that verification was skipped/disabled"
    assert ret.healthy is True
    assert ret.skipped_infra is True
    # pre-existing flag left completely untouched
    assert foundry.hotfix_flag_path(cfg).exists()
    assert foundry.hotfix_flag_path(cfg).read_text() == before


# ==========================================================================
# Behavior 9 -- a verify exception is treated as infra; never crashes the ship
# ==========================================================================
def test_b9_verify_exception_is_infra_and_not_propagated(cfg, monkeypatch):
    foundry.write_hotfix_flag(cfg, "keepsha", "keep")  # must survive
    before = foundry.hotfix_flag_path(cfg).read_text()

    def _boom(*a, **k):
        raise RuntimeError("clone blew up unexpectedly")
    monkeypatch.setattr(foundry, "verify_fresh_clone", _boom)

    ret = foundry.postrelease_step(cfg, 3, "sha")  # must NOT raise
    assert ret.healthy is True
    assert ret.skipped_infra is True
    assert isinstance(ret.detail, str) and ret.detail  # non-empty detail
    art = _artifact(cfg, 3)
    assert art.exists()
    assert _last_nonempty_line(art) == "POSTRELEASE: HEALTHY"
    # flag neither cleared nor a false one raised
    assert foundry.hotfix_flag_path(cfg).exists()
    assert foundry.hotfix_flag_path(cfg).read_text() == before


# ==========================================================================
# Behavior 10 -- passes the pushed sha (2nd arg) + an in-iteration clone dir
# ==========================================================================
def test_b10_passes_sha_and_in_iteration_clone_dir(cfg, monkeypatch):
    rec = []
    result = foundry.PostReleaseResult(True, False, "ok")
    monkeypatch.setattr(foundry, "verify_fresh_clone", make_verify(rec, result))

    foundry.postrelease_step(cfg, 3, "pushedsha1")
    assert len(rec) == 1, "verify_fresh_clone not invoked exactly once"
    call = rec[0]
    assert call["expected_sha"] == "pushedsha1", "expected_sha not passed as 2nd arg"
    clone_dir = pathlib.Path(str(call["clone_dir"]))
    iter_dir = _iter_dir(cfg, 3)
    assert clone_dir != iter_dir
    assert iter_dir in clone_dir.parents or clone_dir.parent == iter_dir, \
        f"clone_dir {clone_dir} is not located under {iter_dir}"


# ==========================================================================
# Behavior 11 -- run_iteration ships then verifies (integration, offline)
# ==========================================================================
def _make_run_stage(lines):
    """Scripted run_stage: writes the given sentinel lines to the stage's output
    file and returns (ok=True, path). Positive sentinels only, so no fix-loop or
    early diversion is triggered."""
    def _run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        it_dir = cfg.state / f"iter-{iteration:02d}"
        it_dir.mkdir(parents=True, exist_ok=True)
        out = it_dir / out_name
        out.write_text("\n".join(lines) + "\n")
        return True, out
    return _run_stage


def _make_head(values):
    seq = list(values)
    def _head(cfg):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return _head


SHIP_LINES = ["VERDICT: APPROVE", "RESULT: PASS", "ACTION: PUSHED newhead99"]
NOSHIP_LINES = ["VERDICT: APPROVE", "RESULT: PASS", "ACTION: REVERTED"]


def test_b11_ship_then_verify(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "run_stage", _make_run_stage(SHIP_LINES))
    monkeypatch.setattr(foundry, "head_of_branch", _make_head(["base0000", "newhead99"]))
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "revert_repo", lambda *a, **k: None)  # defensive

    spy = []
    pr = foundry.PostReleaseResult(True, False, "spy-result")
    def _spy(cfg_, iteration_, expected_sha_):
        spy.append({"iteration": iteration_, "expected_sha": expected_sha_})
        return pr
    monkeypatch.setattr(foundry, "postrelease_step", _spy)

    res = foundry.run_iteration(cfg, 3)
    assert res["status"] == "shipped"
    assert res["head"] == "newhead99"
    assert res["iteration"] == 3
    assert len(spy) == 1, "postrelease_step not called exactly once on the ship path"
    assert spy[0]["expected_sha"] == "newhead99", "postrelease_step not given the new head sha"
    assert res["postrelease"] == pr.sentinel  # == "POSTRELEASE: HEALTHY"


# ==========================================================================
# Behavior 12 -- no ship => no verification, no postrelease key
# ==========================================================================
def test_b12_no_ship_no_verification(cfg, monkeypatch):
    monkeypatch.setattr(foundry, "run_stage", _make_run_stage(NOSHIP_LINES))
    monkeypatch.setattr(foundry, "head_of_branch", _make_head(["same1234"]))  # unchanged
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "revert_repo", lambda *a, **k: None)

    spy = []
    monkeypatch.setattr(foundry, "postrelease_step",
                        lambda *a, **k: spy.append(1))

    res = foundry.run_iteration(cfg, 3)
    assert res["status"] == "no-ship"
    assert spy == [], "postrelease_step called on the no-ship path"
    assert "postrelease" not in res or res.get("postrelease") is None


def test_b12_ship_branch_requires_head_change(cfg, monkeypatch):
    # PUSHED sentinel present, but head unchanged => still NOT a ship.
    monkeypatch.setattr(foundry, "run_stage", _make_run_stage(SHIP_LINES))
    monkeypatch.setattr(foundry, "head_of_branch", _make_head(["frozen00"]))  # never moves
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "revert_repo", lambda *a, **k: None)
    spy = []
    monkeypatch.setattr(foundry, "postrelease_step", lambda *a, **k: spy.append(1))

    res = foundry.run_iteration(cfg, 3)
    assert res["status"] == "no-ship"
    assert spy == []


# ==========================================================================
# Behavior 13 -- imports + CLI + sentinel/numbering/layout contract unchanged
# ==========================================================================
def test_b13_foundry_and_dispatcher_importable():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        capture_output=True, text=True,
        cwd=str(pathlib.Path(foundry.__file__).resolve().parent))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_b13_cli_help_lists_run_once_doctor():
    foundry_py = pathlib.Path(foundry.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(foundry_py), "--help"],
        capture_output=True, text=True, cwd=str(foundry_py.parent))
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    for sub in ("run", "once", "doctor"):
        assert sub in combined, f"subcommand {sub!r} missing from --help"


def test_b13_pipeline_and_new_names_coexist():
    for name in ("run_iteration", "run_continuous", "run_stage", "next_iteration",
                 "verify_fresh_clone", "postrelease_step", "hotfix_flag_path",
                 "write_hotfix_flag", "clear_hotfix_flag", "PostReleaseResult",
                 "sha_matches", "postrelease_verdict"):
        assert hasattr(foundry, name), f"expected module name {name!r} is missing"


def test_b13_iteration_numbering_and_layout_unchanged(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert foundry.next_iteration(cfg) == 1
    (cfg.state / "iter-03").mkdir(parents=True)
    (cfg.state / "iter-09").mkdir(parents=True)
    assert foundry.next_iteration(cfg) == 10
    assert cfg.state == pathlib.Path(cfg.work_root) / "state"
