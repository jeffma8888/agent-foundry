"""Iteration 506 -- BLACK-BOX behavior tests: `main()`'s shared per-product config load
prints ONE `foundry <verb>: cannot read config <path>: <ExcType>: <message>` line on
stderr (exit 1, stdout empty) instead of a raw Python traceback, while `load_config`
itself still raises and the verbs dispatched before the shared load are untouched.

Spec under test: products/_platform/state/iter-506/pm.md, Expected Behaviors 1-9.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-506
PM spec, the product README / roadmap text, the conventions under `tests/`, and the
product's OWN observable behavior (its CLI run as a subprocess and its public names).
The implementation source, the engineer/reviewer notes, IMPLEMENTATION.patch and any
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

TYPO = {"auth_resum_max": 3}


# ---------------------------------------------------------------- helpers


def _setup(tmp_path: pathlib.Path, overlay=None, overlay_text=None, tracked_text=None):
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
        "allowed_push_repo": "none",
        "branch": "main",
        "vision": str(tmp_path / "VISION.md"),
        "roadmap": str(tmp_path / "ROADMAP.md"),
        "quality_ref": str(repo),
        "test_cmd": "true",
        "roles_dir": str(_ROOT / "roles"),
        "work_root": str(work_root),
        "quality_bar": "throwaway fixture",
        "push_enabled": False,
    }
    P = pdir / "config.json"
    if tracked_text is not None:
        P.write_text(tracked_text)
    else:
        P.write_text(json.dumps(data, indent=2) + "\n")
    O = pdir / "config.local.json"
    if overlay is not None:
        O.write_text(json.dumps(overlay, indent=2) + "\n")
    elif overlay_text is not None:
        O.write_text(overlay_text)
    return P, O


def _cli(*args):
    proc = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), *args],
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def _lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def _assert_one_clean_line(rc, out, err, prefix=None):
    assert rc == 1, (rc, out, err)
    assert out == "", out
    lines = _lines(err)
    assert len(lines) == 1, err
    assert "Traceback" not in err, err
    if prefix is not None:
        assert lines[0].startswith(prefix), lines[0]
    return lines[0]


# ---------------------------------------------------------------- EB1


def test_eb1_overlay_typo_status_one_line(tmp_path):
    P, O = _setup(tmp_path, overlay=TYPO)
    rc, out, err = _cli("status", "--config", str(P))
    line = _assert_one_clean_line(rc, out, err, "foundry status: cannot read config ")
    assert "ConfigKeyError" in line
    assert "auth_resum_max" in line
    assert "config.local.json" in line


def test_eb1_line_names_the_config_path(tmp_path):
    P, O = _setup(tmp_path, overlay=TYPO)
    rc, out, err = _cli("status", "--config", str(P))
    line = _assert_one_clean_line(rc, out, err)
    # spec format: `foundry <verb>: cannot read config <path>: <ExcType>: <message>`
    assert line.startswith(f"foundry status: cannot read config {P}: ConfigKeyError: "), line


# ---------------------------------------------------------------- EB2


def test_eb2_status_json_no_partial_json(tmp_path):
    P, O = _setup(tmp_path, overlay=TYPO)
    rc, out, err = _cli("status", "--config", str(P), "--json")
    line = _assert_one_clean_line(rc, out, err, "foundry status: cannot read config ")
    assert "ConfigKeyError" in line


# ---------------------------------------------------------------- EB3


def test_eb3_doctor_names_its_verb(tmp_path):
    P, O = _setup(tmp_path, overlay=TYPO)
    rc, out, err = _cli("doctor", "--config", str(P))
    line = _assert_one_clean_line(rc, out, err, "foundry doctor: cannot read config ")
    assert "ConfigKeyError" in line


def test_eb3_prompt_names_its_verb(tmp_path):
    P, O = _setup(tmp_path, overlay=TYPO)
    rc, out, err = _cli("prompt", "--config", str(P), "--stage", "pm")
    line = _assert_one_clean_line(rc, out, err, "foundry prompt: cannot read config ")
    assert "ConfigKeyError" in line


@pytest.mark.parametrize("verb", ["rescues", "history", "timing"])
def test_eb3_other_shared_path_verbs_name_their_verb(tmp_path, verb):
    # spec "Why": about 33 per-product verbs share the one load; sample a few more.
    P, O = _setup(tmp_path, overlay=TYPO)
    rc, out, err = _cli(verb, "--config", str(P))
    _assert_one_clean_line(rc, out, err, f"foundry {verb}: cannot read config ")


# ---------------------------------------------------------------- EB4


def test_eb4_missing_config_file(tmp_path):
    missing = tmp_path / "nope" / "config.json"
    rc, out, err = _cli("status", "--config", str(missing))
    line = _assert_one_clean_line(rc, out, err)
    assert "cannot read config" in line
    assert "FileNotFoundError" in line
    assert "nope" in line


# ---------------------------------------------------------------- EB5


def test_eb5_malformed_tracked_config(tmp_path):
    P, O = _setup(tmp_path, tracked_text="{not json")
    rc, out, err = _cli("status", "--config", str(P))
    line = _assert_one_clean_line(rc, out, err)
    assert "cannot read config" in line
    assert "JSONDecodeError" in line


# ---------------------------------------------------------------- EB6


def test_eb6_malformed_overlay(tmp_path):
    P, O = _setup(tmp_path, overlay_text="{oops")
    rc, out, err = _cli("status", "--config", str(P))
    line = _assert_one_clean_line(rc, out, err)
    assert "cannot read config" in line
    assert "ConfigOverlayError" in line
    assert "config.local.json" in line


# ---------------------------------------------------------------- EB7


def test_eb7_good_config_status_unchanged(tmp_path):
    P, O = _setup(tmp_path)
    rc, out, err = _cli("status", "--config", str(P))
    assert rc in (0, 1, 2), (rc, out, err)
    assert "cannot read config" not in err
    assert "Traceback" not in err
    assert out.strip(), "status on a good config prints a report"


def test_eb7_good_config_status_json_parses(tmp_path):
    P, O = _setup(tmp_path)
    rc, out, err = _cli("status", "--config", str(P), "--json")
    assert rc in (0, 1, 2), (rc, out, err)
    doc = json.loads(out)
    assert isinstance(doc, dict)
    assert "cannot read config" not in err
    assert "Traceback" not in err


# ---------------------------------------------------------------- EB8


def test_eb8_lint_config_keeps_its_historical_line(tmp_path):
    P, O = _setup(tmp_path, overlay=TYPO)
    rc, out, err = _cli("lint-config", "--config", str(P))
    assert rc == 2, (rc, out, err)
    assert "lint-config: cannot read config" in out, out
    assert "ConfigKeyError" in out, out
    # anti-vacuity: the per-product `foundry lint-config:` stderr prefix is NOT used
    assert "foundry lint-config: cannot read config" not in err, err


def test_eb8_overlay_unset_repairs_then_status_loads(tmp_path):
    P, O = _setup(tmp_path, overlay=TYPO)
    rc0, out0, err0 = _cli("status", "--config", str(P))
    assert "cannot read config" in err0  # broken before the repair
    rc, out, err = _cli("overlay", "--config", str(P), "--unset", "auth_resum_max")
    assert rc == 0, (rc, out, err)
    assert "invalid choice" not in err
    rc2, out2, err2 = _cli("status", "--config", str(P))
    assert "cannot read config" not in err2, err2
    assert "Traceback" not in err2, err2
    assert rc2 in (0, 1, 2)


# ---------------------------------------------------------------- EB9


def test_eb9_import_safety():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def test_eb9_load_config_still_raises(tmp_path):
    P, O = _setup(tmp_path, overlay=TYPO)
    with pytest.raises(foundry.ConfigKeyError):
        foundry.load_config(str(P))


def test_eb9_load_config_still_raises_on_bad_overlay_json(tmp_path):
    P, O = _setup(tmp_path, overlay_text="{oops")
    with pytest.raises(foundry.ConfigOverlayError):
        foundry.load_config(str(P))
