"""Behaviour tests for iter 498 -- a malformed machine-local
`config.local.json` overlay raises `ConfigOverlayError(ValueError)` that
NAMES the overlay file, instead of a bare, file-less decode error.

Spec: the iter-498 PM spec (pm.md), Expected Behaviors 1-8.

ISOLATION: written by the tester stage under its black-box contract -- the
spec, tests/, README/USAGE and the product's runtime output only; no
implementation source, no diff, no engineer/reviewer notes. Every fixture is
built in tmp_path; the only live-repo read is the TRACKED _platform
config.json key set (never any gitignored overlay).
"""
import dataclasses
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe)

OVERLAY = "config" + ".local.json"
TRACKED_CFG = REPO / "products" / "_platform" / "config.json"

TRAILING_COMMA = '{"auth_resume_max": 24,}'
TRUNCATED = '{"auth_resume_max": '
BAD_UTF8 = b"\xff\xfe{"


def _base_config(root: pathlib.Path) -> dict:
    """The tracked _platform key set, every path re-pointed into tmp_path."""
    raw = json.loads(TRACKED_CFG.read_text())
    for key, val in list(raw.items()):
        if isinstance(val, str) and "{FOUNDRY}" in val:
            raw[key] = val.replace("{FOUNDRY}", str(root / "repo"))
    raw["repo"] = str(root / "repo")
    raw["work_root"] = str(root / "work")
    for k in ("gap_register", "practice_register", "gap_layers",
              "auth_resume_max"):
        raw.pop(k, None)
    return raw


def _write_cfg(d: pathlib.Path, raw: dict, overlay=None) -> pathlib.Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "repo").mkdir(exist_ok=True)
    p = d / "config.json"
    p.write_text(json.dumps(raw, indent=2))
    if overlay is not None:
        ov = d / OVERLAY
        if isinstance(overlay, bytes):
            ov.write_bytes(overlay)
        elif isinstance(overlay, str):
            ov.write_text(overlay)
        else:
            ov.write_text(json.dumps(overlay))
    return p


def _raise(p: pathlib.Path):
    with pytest.raises(foundry.ConfigOverlayError) as ei:
        foundry.load_config(p)
    return ei.value


def _lint(cfg: pathlib.Path, *extra):
    return subprocess.run(
        [sys.executable, str(REPO / "foundry.py"), "lint-config",
         "--config", str(cfg), *extra],
        capture_output=True, text=True, timeout=60)


# --- EB1 -------------------------------------------------------------------

def test_eb1_class_hierarchy():
    cls = foundry.ConfigOverlayError
    assert isinstance(cls, type)
    assert issubclass(cls, ValueError)
    assert not issubclass(cls, foundry.ConfigKeyError)
    assert cls.__doc__ and cls.__doc__.strip()


# --- EB2 -------------------------------------------------------------------

def test_eb2_trailing_comma_names_overlay_and_chains(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, TRAILING_COMMA)
    exc = _raise(p)
    msg = str(exc)
    assert str(tmp_path / OVERLAY) in msg
    assert "line 1 column" in msg
    assert isinstance(exc.__cause__, json.JSONDecodeError)
    assert not isinstance(exc, foundry.ConfigKeyError)


# --- EB3 -------------------------------------------------------------------

def test_eb3_truncated_overlay_names_path_no_dirs(tmp_path):
    raw = _base_config(tmp_path)
    work = pathlib.Path(raw["work_root"])
    assert not work.exists()
    p = _write_cfg(tmp_path, raw, TRUNCATED)
    exc = _raise(p)
    assert str(tmp_path / OVERLAY) in str(exc)
    assert isinstance(exc.__cause__, json.JSONDecodeError)
    assert not work.exists()
    assert not (work / "state").exists()


def test_eb3_empty_overlay_also_named(tmp_path):
    # not in the spec list, but an empty file is the same decode failure
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, "")
    exc = _raise(p)
    assert str(tmp_path / OVERLAY) in str(exc)


# --- EB4 -------------------------------------------------------------------

def test_eb4_non_utf8_overlay_names_path(tmp_path):
    raw = _base_config(tmp_path)
    work = pathlib.Path(raw["work_root"])
    p = _write_cfg(tmp_path, raw, BAD_UTF8)
    exc = _raise(p)
    assert type(exc) is not UnicodeDecodeError
    assert not isinstance(exc, UnicodeDecodeError)
    assert str(tmp_path / OVERLAY) in str(exc)
    assert isinstance(exc.__cause__, (UnicodeDecodeError,
                                      json.JSONDecodeError))
    assert not work.exists()


# --- EB5 -------------------------------------------------------------------

def test_eb5_repr_names_overlay(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, TRAILING_COMMA)
    exc = _raise(p)
    r = repr(exc)
    assert "ConfigOverlayError" in r
    assert str(tmp_path / OVERLAY) in r
    # the dispatcher log shape `config load failed for <team>: {exc!r}`
    line = f"config load failed for x: {exc!r}"
    assert str(tmp_path / OVERLAY) in line


# --- EB6 -------------------------------------------------------------------

def test_eb6_lint_config_plain_exit2_names_overlay(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, TRAILING_COMMA)
    r = _lint(p)
    assert r.returncode == 2, r.stdout + r.stderr
    assert str(tmp_path / OVERLAY) in r.stdout
    assert "ConfigOverlayError" in r.stdout


def test_eb6_lint_config_json_exit2_names_overlay(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, TRAILING_COMMA)
    r = _lint(p, "--json")
    assert r.returncode == 2, r.stdout + r.stderr
    json.loads(r.stdout)  # still a parseable document
    assert str(tmp_path / OVERLAY) in r.stdout


# --- EB7 -------------------------------------------------------------------

def test_eb7a_non_object_overlay_still_configkeyerror(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, [1, 2])
    with pytest.raises(foundry.ConfigKeyError) as ei:
        foundry.load_config(p)
    assert OVERLAY in str(ei.value)
    assert not isinstance(ei.value, foundry.ConfigOverlayError)


def test_eb7b_unknown_key_still_configkeyerror_and_lint_exit2(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, {"auth_resume_maxx": 24})
    with pytest.raises(foundry.ConfigKeyError) as ei:
        foundry.load_config(p)
    assert "auth_resume_maxx" in str(ei.value)
    r = _lint(p)
    assert r.returncode == 2, r.stdout + r.stderr
    assert OVERLAY in r.stdout


def test_eb7c_valid_overlay_loads(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw, {"auth_resume_max": 24})
    assert foundry.load_config(p).auth_resume_max == 24


def test_eb7d_no_overlay_unchanged(tmp_path):
    raw = _base_config(tmp_path)
    p = _write_cfg(tmp_path, raw)
    cfg = foundry.load_config(p)
    assert cfg.auth_resume_max == 0
    assert cfg.name == raw["name"]
    assert cfg.branch == raw["branch"]
    # same result loaded twice (deterministic, no hidden overlay)
    assert dataclasses.asdict(cfg) == dataclasses.asdict(
        foundry.load_config(p))


def test_eb7e_malformed_tracked_config_plain_decode_error(tmp_path):
    (tmp_path / "repo").mkdir()
    p = tmp_path / "config.json"
    p.write_text('{"name": "x",}')
    with pytest.raises(json.JSONDecodeError) as ei:
        foundry.load_config(p)
    assert not isinstance(ei.value, foundry.ConfigOverlayError)
    assert type(ei.value) is json.JSONDecodeError


# --- EB8 -------------------------------------------------------------------

def test_eb8_direct_overlay_load_valid_unchanged(tmp_path):
    raw = _base_config(tmp_path)
    raw["branch"] = "direct"
    (tmp_path / "repo").mkdir(exist_ok=True)
    direct = tmp_path / OVERLAY
    direct.write_text(json.dumps(raw))
    assert foundry.load_config(direct).branch == "direct"


def test_eb8_direct_overlay_load_malformed_plain_decode(tmp_path):
    (tmp_path / "repo").mkdir()
    direct = tmp_path / OVERLAY
    direct.write_text(TRAILING_COMMA)
    with pytest.raises(json.JSONDecodeError) as ei:
        foundry.load_config(direct)
    assert type(ei.value) is json.JSONDecodeError
    assert not isinstance(ei.value, foundry.ConfigOverlayError)


# --- hygiene ---------------------------------------------------------------

def test_import_and_hygiene():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=REPO, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    src = pathlib.Path(__file__).read_text()
    assert ("/" + "Us" + "ers/") not in src
    assert ("LEARN" + "INGS") not in src
    assert ("state/" + "iter-") not in src


def test_roadmap_records():
    idx = (REPO / "PLATFORM_ROADMAP.md").read_text().splitlines()
    assert len([ln for ln in idx if ln.startswith("- iter 498 ")]) == 1
    arc = (REPO / "PLATFORM_ROADMAP_ARCHIVE.md").read_text().splitlines()
    assert len([ln for ln in arc if ln.startswith("- **iter 498 ")]) == 1
