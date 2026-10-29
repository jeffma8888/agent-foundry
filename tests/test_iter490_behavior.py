"""Behaviour tests for iter 490 -- a machine-local, gitignored
`config.local.json` beside a product config is merged OVER the tracked
config by `load_config`, through the same fail-closed unknown-key check.

Spec: the iter-490 PM spec (pm.md), Expected Behaviors 1-14.

ISOLATION: written by the tester stage under its black-box contract -- the
spec, tests/, README/USAGE and the product's runtime output only; no
implementation source, no diff, no engineer/reviewer notes. Every fixture is
built in tmp_path; the only live-repo reads are TRACKED files (the _platform
config key set, products/.gitignore, USAGE.md, the roadmap files) and one
`git check-ignore` on a path that need not exist.

Spec ambiguity noted: EB2's example key `max_iterations` is not a
ProductConfig field, so a fail-closed overlay must REJECT it; the conflict
behaviour is exercised with the real field `branch` instead (and the
rejection of `max_iterations` is pinned as fail-closed).
"""
import dataclasses
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe)

OVERLAY = "config" + ".local.json"
TRACKED_CFG = REPO / "products" / "_platform" / "config.json"


def _base_config(root: pathlib.Path) -> dict:
    """The tracked _platform key set, every path re-pointed into tmp_path."""
    raw = json.loads(TRACKED_CFG.read_text())
    for key, val in list(raw.items()):
        if isinstance(val, str) and "{FOUNDRY}" in val:
            raw[key] = val.replace("{FOUNDRY}", str(root / "repo"))
    raw["repo"] = str(root / "repo")
    raw["work_root"] = str(root / "work")
    raw.pop("gap_register", None)
    raw.pop("practice_register", None)
    raw.pop("gap_layers", None)
    raw.pop("auth_resume_max", None)
    return raw


def _write_cfg(d: pathlib.Path, raw: dict, overlay=None) -> pathlib.Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "repo").mkdir(exist_ok=True)
    p = d / "config.json"
    p.write_text(json.dumps(raw, indent=2))
    if overlay is not None:
        text = overlay if isinstance(overlay, str) else json.dumps(overlay)
        (d / OVERLAY).write_text(text)
    return p


def test_eb8_constant():
    assert foundry.CONFIG_LOCAL_OVERLAY_NAME == "config.local.json"


def test_eb1_overlay_applies_and_tracked_bytes_unchanged(tmp_path):
    raw = _base_config(tmp_path)
    assert "auth_resume_max" not in raw
    p = _write_cfg(tmp_path, raw, {"auth_resume_max": 24})
    before = p.read_bytes()
    cfg = foundry.load_config(p)
    assert cfg.auth_resume_max == 24
    assert p.read_bytes() == before
    assert "auth_resume_max" not in json.loads(p.read_text())


def test_eb2_overlay_wins_on_conflict_others_keep_tracked(tmp_path):
    raw = _base_config(tmp_path)
    raw["branch"] = "main"
    p = _write_cfg(tmp_path, raw, {"branch": "overlay-branch"})
    cfg = foundry.load_config(p)
    assert cfg.branch == "overlay-branch"
    assert cfg.name == raw["name"]
    assert cfg.test_cmd == raw["test_cmd"]
    assert cfg.push_enabled is raw["push_enabled"]


def test_eb2_non_field_example_key_fails_closed(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, {"max_iterations": 7})
    with pytest.raises(foundry.ConfigKeyError) as ei:
        foundry.load_config(p)
    assert "max_iterations" in str(ei.value)
    assert OVERLAY in str(ei.value)


def test_eb3_no_overlay_is_identical(tmp_path):
    raw = _base_config(tmp_path / "a")
    a = _write_cfg(tmp_path / "a", raw)
    # identical bytes in a second dir (paths still point at dir a)
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = b_dir / "config.json"
    b.write_bytes(a.read_bytes())
    ca = foundry.load_config(a)
    cb = foundry.load_config(b)
    assert dataclasses.asdict(ca) == dataclasses.asdict(cb)
    assert ca.auth_resume_max == 0
    assert not (tmp_path / "a" / OVERLAY).exists()


def test_eb3_overlay_changes_only_named_field(tmp_path):
    raw = _base_config(tmp_path / "a")
    a = _write_cfg(tmp_path / "a", raw)
    plain = dataclasses.asdict(foundry.load_config(a))
    (tmp_path / "a" / OVERLAY).write_text(json.dumps({"auth_resume_max": 5}))
    merged = dataclasses.asdict(foundry.load_config(a))
    diff = {k for k in plain if plain[k] != merged[k]}
    assert diff == {"auth_resume_max"}
    assert merged["auth_resume_max"] == 5


def test_eb4_bad_overlay_key_fails_closed_no_dirs(tmp_path):
    raw = _base_config(tmp_path)
    work = pathlib.Path(raw["work_root"])
    assert not work.exists()
    p = _write_cfg(tmp_path, raw, {"auth_resume_maxx": 24})
    with pytest.raises(foundry.ConfigKeyError) as ei:
        foundry.load_config(p)
    assert isinstance(ei.value, ValueError)
    msg = str(ei.value)
    assert OVERLAY in msg
    assert "auth_resume_maxx" in msg
    assert not work.exists()


def test_eb5_underscore_comment_keys_ignored(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, {"_note": "x", "auth_resume_max": 3})
    cfg = foundry.load_config(p)
    assert cfg.auth_resume_max == 3


def test_eb6_non_object_overlay_raises_no_dirs(tmp_path):
    raw = _base_config(tmp_path)
    work = pathlib.Path(raw["work_root"])
    p = _write_cfg(tmp_path, raw, [1, 2])
    with pytest.raises(foundry.ConfigKeyError) as ei:
        foundry.load_config(p)
    assert OVERLAY in str(ei.value)
    assert not work.exists()


def test_eb6_malformed_overlay_raises_valueerror_no_dirs(tmp_path):
    raw = _base_config(tmp_path)
    work = pathlib.Path(raw["work_root"])
    p = _write_cfg(tmp_path, raw, '{"auth_resume_max": ')
    with pytest.raises(ValueError):
        foundry.load_config(p)
    assert not work.exists()


def test_eb7_loading_overlay_file_directly(tmp_path):
    raw = _base_config(tmp_path)
    raw["branch"] = "direct"
    tmp_path.joinpath("repo").mkdir(exist_ok=True)
    direct = tmp_path / OVERLAY
    direct.write_text(json.dumps(raw))
    cfg = foundry.load_config(direct)
    assert cfg.branch == "direct"
    assert cfg.name == raw["name"]


def _lint(cfg: pathlib.Path):
    return subprocess.run(
        [sys.executable, str(REPO / "foundry.py"), "lint-config",
         "--config", str(cfg)],
        capture_output=True, text=True, timeout=60)


def test_eb9_cli_lint_config_sees_overlay(tmp_path):
    raw = _base_config(tmp_path / "bad")
    bad = _write_cfg(tmp_path / "bad", raw, {"auth_resume_maxx": 1})
    r = _lint(bad)
    assert r.returncode == 2, r.stdout + r.stderr
    assert OVERLAY in r.stdout

    raw2 = _base_config(tmp_path / "plain")
    plain = _write_cfg(tmp_path / "plain", raw2)
    base_rc = _lint(plain).returncode
    (tmp_path / "plain" / OVERLAY).write_text(
        json.dumps({"auth_resume_max": 24}))
    assert _lint(plain).returncode == base_rc


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=60)


def test_eb10_live_gitignore(tmp_path):
    rel = "products/_platform/" + OVERLAY
    r = _git("check-ignore", "-v", rel, cwd=REPO)
    assert r.returncode == 0, r.stderr
    source = r.stdout.split(":", 1)[0]
    assert source == "products/.gitignore"
    tracked = "products/_platform/config.json"
    assert tracked in _git("ls-files", cwd=REPO).stdout.splitlines()
    assert _git("check-ignore", "-q", tracked, cwd=REPO).returncode == 1


def test_eb11_hermetic_gitignore(tmp_path):
    if shutil.which("git") is None:
        pytest.fail("git is required")
    root = tmp_path / "g"
    (root / "products" / "x").mkdir(parents=True)
    shutil.copy(REPO / "products" / ".gitignore",
                root / "products" / ".gitignore")
    (root / "products" / "x" / "config.json").write_text("{}\n")
    (root / "products" / "x" / OVERLAY).write_text('{"auth_resume_max": 1}\n')
    assert _git("init", "-q", cwd=root).returncode == 0
    assert _git("add", "-A", cwd=root).returncode == 0
    staged = _git("diff", "--cached", "--name-only", cwd=root).stdout.split()
    assert "products/x/config.json" in staged
    assert "products/x/" + OVERLAY not in staged


def test_eb12_usage_doc():
    text = (REPO / "USAGE.md").read_text()
    paras = text.split("\n\n")
    hits = [p for p in paras if OVERLAY in p]
    assert hits
    assert any("gitignored" in p for p in hits)


def test_eb13_roadmap_records():
    idx = (REPO / "PLATFORM_ROADMAP.md").read_text().splitlines()
    rows = [ln for ln in idx if ln.startswith("- iter 490 ")]
    assert len(rows) == 1
    assert len(rows[0]) <= 120
    arc = (REPO / "PLATFORM_ROADMAP_ARCHIVE.md").read_text().splitlines()
    assert len([ln for ln in arc if ln.startswith("- **iter 490 ")]) == 1


def test_eb14_fresh_import_and_hygiene():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=REPO, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    src = pathlib.Path(__file__).read_text()
    assert ("/" + "Users/") not in src
    assert ("LEARN" + "INGS") not in src
    assert ("state/" + "iter-") not in src
