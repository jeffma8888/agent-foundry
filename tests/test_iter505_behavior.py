"""Iteration 505 -- BLACK-BOX behavior tests: `load_config` IGNORES a push escalation in a
gitignored `config.local.json` (push turned on, or `repo` / `allowed_push_repo` changed)
-- the tracked value is kept, the rest of the overlay still merges, and one stderr line
per ignored key names the overlay, the tracked config and the `--unset` repair.

Spec under test: products/_platform/state/iter-505/pm.md, Expected Behaviors 1-9.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-505
PM spec, the product README / roadmap text, the conventions under `tests/`, and the
product's OWN observable behavior (calling its public names and its CLI).  The
implementation source, the engineer/reviewer notes, IMPLEMENTATION.patch and any
`git diff` were NOT read.

FIXTURE SAFETY: every P (product config) and O (its config.local.json) lives in
tmp_path; no real products/*/config.local.json (gitignored) is read or written, and no
absolute machine path appears in this file.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402


# ---------------------------------------------------------------- helpers


def _setup(tmp_path: pathlib.Path, push_enabled=False, content=None,
           allowed_push_repo="none", omit_push=False):
    """Build P (a loadable product config with a real repo dir) and O beside it."""
    pdir = tmp_path / "products" / "x"
    pdir.mkdir(parents=True, exist_ok=True)
    work_root = tmp_path / "work"
    work_root.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)  # lint-config checks for a .git entry
    (tmp_path / "VISION.md").write_text("vision\n")
    (tmp_path / "ROADMAP.md").write_text("roadmap\n")
    data = {
        "name": "x",
        "repo": str(repo),
        "allowed_push_repo": allowed_push_repo,
        "branch": "main",
        "vision": str(tmp_path / "VISION.md"),
        "roadmap": str(tmp_path / "ROADMAP.md"),
        "quality_ref": str(repo),
        "test_cmd": "true",
        "roles_dir": str(_ROOT / "roles"),
        "work_root": str(work_root),
        "quality_bar": "throwaway fixture",
        "push_enabled": push_enabled,
    }
    if omit_push:
        data.pop("push_enabled")
    P = pdir / "config.json"
    P.write_text(json.dumps(data, indent=2) + "\n")
    O = pdir / "config.local.json"
    if content is not None:
        O.write_text(json.dumps(content, indent=2) + "\n")
    return P, O


def _cli(*args):
    proc = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), *args],
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


_LOAD_CODE = (
    "import sys, json, foundry\n"
    "cfg = foundry.load_config(sys.argv[1])\n"
    "print(json.dumps({'push_enabled': cfg.push_enabled, 'repo': str(cfg.repo),\n"
    "                  'allowed_push_repo': cfg.allowed_push_repo,\n"
    "                  'branch': cfg.branch, 'auth_resume_max': cfg.auth_resume_max}))\n"
)


def _load_sub(path):
    """load_config in a fresh interpreter, so stderr is observable."""
    proc = subprocess.run([sys.executable, "-c", _LOAD_CODE, str(path)], cwd=str(_ROOT),
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def _lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


# ------------------------------------------------------- 1. push enable ignored


def test_b1_push_enable_ignored_rest_merged(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False,
                  content={"push_enabled": True, "auth_resume_max": 24})
    cfg = foundry.load_config(P)
    assert cfg.push_enabled is False
    assert cfg.auth_resume_max == 24


def test_b1_anti_vacuity_non_escalating_key_really_merges(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    base = foundry.load_config(P).auth_resume_max
    assert base != 24, base  # otherwise b1's == 24 would prove nothing
    O.write_text(json.dumps({"push_enabled": True, "auth_resume_max": 24}) + "\n")
    assert foundry.load_config(P).auth_resume_max == 24


# ------------------------------------------------------- 2. push target ignored


def test_b2_push_target_change_ignored(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False, allowed_push_repo="tracked-repo")
    baseline = foundry.load_config(P)
    other = tmp_path / "other_repo"
    other.mkdir()
    (other / ".git").mkdir()
    O.write_text(json.dumps({"repo": str(other), "allowed_push_repo": "other"}) + "\n")
    cfg = foundry.load_config(P)
    assert cfg.allowed_push_repo == "tracked-repo"
    assert str(cfg.repo) == str(baseline.repo)
    assert "other_repo" not in str(cfg.repo)


# ------------------------------------------------------- 3. stderr lines


def test_b3_one_stderr_line_per_key_in_order(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False, allowed_push_repo="tracked-repo",
                  content={"push_enabled": True, "allowed_push_repo": "other"})
    rc, out, err = _load_sub(P)
    assert rc == 0, err
    lines = _lines(err)
    assert len(lines) == 2, err
    assert "push_enabled" in lines[0] and "allowed_push_repo" not in lines[0], lines
    assert "allowed_push_repo" in lines[1], lines
    for line, key in zip(lines, ("push_enabled", "allowed_push_repo")):
        assert "config.local.json" in line, line
        assert str(P) in line, line
        assert f"--unset {key}" in line, line
    # stdout is unaffected: exactly the one JSON line, with tracked values
    got = json.loads(out)
    assert out.count("\n") == 1, out
    assert got["push_enabled"] is False and got["allowed_push_repo"] == "tracked-repo"


def test_b3_order_fixed_regardless_of_overlay_key_order(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False,
                  content={"allowed_push_repo": "other", "push_enabled": True})
    rc, out, err = _load_sub(P)
    assert rc == 0, err
    lines = _lines(err)
    assert len(lines) == 2, err
    assert "--unset push_enabled" in lines[0], lines
    assert "--unset allowed_push_repo" in lines[1], lines


def test_b3_repo_change_gets_its_own_line(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    other = tmp_path / "other_repo"
    other.mkdir()
    O.write_text(json.dumps({"repo": str(other)}) + "\n")
    rc, out, err = _load_sub(P)
    assert rc == 0, err
    lines = _lines(err)
    assert len(lines) == 1, err
    assert "--unset repo" in lines[0] and "config.local.json" in lines[0], lines


# ------------------------------------------------------- 4. nothing escalates


@pytest.mark.parametrize("tracked_push,omit,content,field,expected", [
    (True, False, {"push_enabled": False}, "push_enabled", False),
    (True, False, {"push_enabled": True}, "push_enabled", True),
    (False, True, {"push_enabled": True}, "push_enabled", True),
    (False, False, {"branch": "dev", "auth_resume_max": 3}, "branch", "dev"),
    (False, False, {"branch": "dev", "auth_resume_max": 3}, "auth_resume_max", 3),
    (False, False, {"allowed_push_repo": "tracked-repo"}, "allowed_push_repo",
     "tracked-repo"),
])
def test_b4_non_escalating_overlay_applies_silently(tmp_path, tracked_push, omit,
                                                    content, field, expected):
    P, O = _setup(tmp_path, push_enabled=tracked_push, omit_push=omit,
                  allowed_push_repo="tracked-repo", content=content)
    rc, out, err = _load_sub(P)
    assert rc == 0, err
    assert err == "", err
    assert json.loads(out)[field] == expected
    cfg = foundry.load_config(P)
    assert getattr(cfg, field) == expected


def test_b4_omitted_key_default_really_is_true(tmp_path):
    # anti-vacuity for the "omits the key (default True)" arm
    P, _ = _setup(tmp_path, omit_push=True)
    assert foundry.load_config(P).push_enabled is True


def test_b4_no_overlay_loads_silently(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    assert not O.exists()
    rc, out, err = _load_sub(P)
    assert rc == 0 and err == "", err
    assert json.loads(out)["push_enabled"] is False


# ------------------------------------------------------- 5. final-gate prompt


def test_b5_final_prompt_shows_reviewed_value(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False, allowed_push_repo="tracked-repo",
                  content={"push_enabled": True, "allowed_push_repo": "other"})
    rc, out, err = _cli("prompt", "--config", str(P), "--stage", "final")
    assert rc == 0, (out[-2000:], err)
    lines = [ln for ln in out.splitlines()
             if ln.startswith("- Push target (final gate only):")]
    assert len(lines) == 1, out[:3000]
    line = lines[0]
    assert "push_enabled=False" in line, line
    assert "'tracked-repo'" in line, line
    assert "'other'" not in line, line


def test_b5_anti_vacuity_prompt_reflects_tracked_true(tmp_path):
    # the prompt line really follows the loaded value (True when tracked True)
    P, O = _setup(tmp_path, push_enabled=True, allowed_push_repo="tracked-repo")
    rc, out, err = _cli("prompt", "--config", str(P), "--stage", "final")
    assert rc == 0, err
    line = [ln for ln in out.splitlines()
            if ln.startswith("- Push target (final gate only):")][0]
    assert "push_enabled=True" in line and "'tracked-repo'" in line, line


# ------------------------------------------------------- 6. existing errors win


def test_b6_unknown_key_still_raises_first(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False,
                  content={"push_enabled": True, "auth_resum_max": 1})
    with pytest.raises(foundry.ConfigKeyError) as ei:
        foundry.load_config(P)
    msg = str(ei.value)
    assert "config.local.json" in msg and "auth_resum_max" in msg, msg


def test_b6_unknown_key_no_ignored_line_first(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False,
                  content={"push_enabled": True, "auth_resum_max": 1})
    rc, out, err = _load_sub(P)
    assert rc != 0
    assert "ConfigKeyError" in err, err
    assert "--unset push_enabled" not in err, err


def test_b6_list_overlay_raises_config_key_error(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    O.write_text(json.dumps([{"push_enabled": True}]) + "\n")
    with pytest.raises(foundry.ConfigKeyError):
        foundry.load_config(P)


def test_b6_malformed_overlay_raises_overlay_error(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    O.write_text('{"push_enabled": true,\n')
    with pytest.raises(foundry.ConfigOverlayError):
        foundry.load_config(P)


# ------------------------------------------------------- 7. lint still flags


def test_b7_lint_still_flags_overlay(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False,
                  content={"push_enabled": True, "allowed_push_repo": "other"})
    rc, out, err = _cli("lint-config", "--config", str(P), "--json")
    assert rc == 1, (out, err)
    findings = json.loads(out)["findings"]
    assert [f["field"] for f in findings[-2:]] == ["push_enabled", "allowed_push_repo"]
    assert all(f["level"] == "error" for f in findings[-2:]), findings
    O.unlink()
    rc0, out0, err0 = _cli("lint-config", "--config", str(P), "--json")
    assert rc0 == 0, (out0, err0)


# ------------------------------------------------------- 8. overlay as config


def test_b8_overlay_file_passed_as_config_not_filtered(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    full = json.loads(P.read_text())
    full["push_enabled"] = True
    O.write_text(json.dumps(full, indent=2) + "\n")
    rc, out, err = _load_sub(O)
    assert rc == 0, err
    assert err == "", err
    assert json.loads(out)["push_enabled"] is True
    assert foundry.load_config(O).push_enabled is True


# ------------------------------------------------------- 9. live-path hygiene


def test_b9_import_probe():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def test_b9_guarded_fields_constant():
    assert foundry.OVERLAY_PUSH_GUARDED_FIELDS == ("push_enabled", "repo",
                                                   "allowed_push_repo")
