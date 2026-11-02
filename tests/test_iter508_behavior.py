"""Iteration 508 -- BLACK-BOX behavior tests: USAGE.md and README #27/#67 document the
overlay push guard (a gitignored `config.local.json` may turn push OFF but never ON, and
may not change `repo` / `allowed_push_repo`), and the documented claims are true.

Spec under test: products/_platform/state/iter-508/pm.md, Expected Behaviors 1-8.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-508
PM spec, the product README / USAGE / roadmap text, the conventions under `tests/`, and
the product's OWN observable behavior (its public names and its CLI).  The
implementation source, the engineer/reviewer notes, IMPLEMENTATION.patch and any
`git diff` were NOT read.

FIXTURE SAFETY: every product config and its config.local.json lives in tmp_path; no
real products/*/config.local.json (gitignored) is read or written, and no absolute
machine path appears in this file.  The guarded names are read from
`foundry.OVERLAY_PUSH_GUARDED_FIELDS` at CALL time, never hand-listed.
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

SITES = ("usage_overlay_paragraph", "usage_config_reference_intro",
         "readme_67", "readme_27")


# ---------------------------------------------------------------- doc slicing


def _usage():
    return (_ROOT / "USAGE.md").read_text(encoding="utf-8")


def _readme():
    return (_ROOT / "README.md").read_text(encoding="utf-8")


def _usage_overlay_paragraph():
    paras = [p for p in _usage().split("\n\n")
             if p.lstrip("\n").startswith("Machine-local operator knobs:")]
    assert len(paras) == 1, "exactly one 'Machine-local operator knobs:' paragraph"
    return paras[0]


def _usage_config_reference_intro():
    text = _usage()
    head = "\n## Product config reference\n"
    assert text.count(head) == 1
    after = text.split(head, 1)[1]
    assert "\n|" in after
    return after.split("\n|", 1)[0]


def _readme_line(num):
    lines = [ln for ln in _readme().splitlines() if ln.startswith(f"# {num}.")]
    assert len(lines) == 1, f"exactly one README line starting '# {num}.'"
    return lines[0]


def _site_text(site):
    return {
        "usage_overlay_paragraph": _usage_overlay_paragraph,
        "usage_config_reference_intro": _usage_config_reference_intro,
        "readme_67": lambda: _readme_line(67),
        "readme_27": lambda: _readme_line(27),
    }[site]()


def _missing_guarded(site):
    """Guarded field names (read from foundry at CALL time) absent from a doc site."""
    text = _site_text(site)
    return [f for f in foundry.OVERLAY_PUSH_GUARDED_FIELDS if f"`{f}`" not in text]


def _doc_check():
    """site -> list of guarded field names the site fails to mention (backticked)."""
    return {site: _missing_guarded(site) for site in SITES}


# ------------------------------------------------- 1. USAGE overlay paragraph


def test_b1_overlay_paragraph_names_every_guarded_field():
    assert _missing_guarded("usage_overlay_paragraph") == []


def test_b1_overlay_paragraph_says_ignored_and_off_allowed():
    para = _usage_overlay_paragraph()
    assert "ignored" in para
    assert "off" in para
    # the "push off is allowed" claim is concrete: the overlay false value is shown
    assert '"push_enabled": false' in para


# ------------------------------------------- 2. USAGE config-reference intro


def test_b2_config_reference_intro_drops_unqualified_win_claim():
    intro = _usage_config_reference_intro()
    flat = " ".join(intro.split())  # the HEAD claim was wrapped across a line break
    assert "(the overlay's keys win)" not in flat
    assert "overlay" in flat  # anti-vacuity: the slice really is the overlay intro
    assert "|" not in intro  # the slice really stops before the table


def test_b2_config_reference_intro_names_every_guarded_field():
    assert _missing_guarded("usage_config_reference_intro") == []


def test_b2_config_reference_intro_states_push_off_allowed():
    intro = _usage_config_reference_intro()
    assert "ignored" in intro
    assert "off" in intro


# ---------------------------------------------------------- 3. README #67


def test_b3_readme_67_names_guarded_fields_and_escalation():
    line = _readme_line(67)
    assert "`overlay`" in line
    assert _missing_guarded("readme_67") == []
    assert "escalat" in line


def test_b3_readme_67_says_set_refuses_escalation():
    line = _readme_line(67)
    assert "--set" in line
    assert "refuses a push escalation" in line


# ---------------------------------------------------------- 4. README #27


def test_b4_readme_27_overlay_escalation_is_an_error_per_key():
    line = _readme_line(27)
    assert "lint-config" in line or "Lint a PRODUCT config" in line
    assert "config.local.json" in line
    assert "escalat" in line
    assert ("ERROR" in line) or ("error" in line)
    assert "per key" in line


def test_b4_readme_27_names_every_guarded_field():
    assert _missing_guarded("readme_27") == []


# ------------------------------------- 5. names derived at call time (failable pin)


def test_b5_real_tuple_reports_nothing_missing():
    assert len(foundry.OVERLAY_PUSH_GUARDED_FIELDS) >= 3
    assert _doc_check() == {site: [] for site in SITES}


def test_b5_made_up_fourth_field_is_reported_missing_at_all_four_sites(monkeypatch):
    real = tuple(foundry.OVERLAY_PUSH_GUARDED_FIELDS)
    monkeypatch.setattr(foundry, "OVERLAY_PUSH_GUARDED_FIELDS", real + ("branch_x",))
    report = _doc_check()
    assert set(report) == set(SITES)
    for site in SITES:
        assert report[site] == ["branch_x"], site


def test_b5_dropping_a_name_from_the_tuple_shrinks_the_check(monkeypatch):
    monkeypatch.setattr(foundry, "OVERLAY_PUSH_GUARDED_FIELDS", ("no_such_field_q",))
    assert _doc_check() == {site: ["no_such_field_q"] for site in SITES}


# ------------------------------------------------ 6. the documented claims hold


def _setup(tmp_path, push_enabled, overlay):
    pdir = tmp_path / "products" / "x"
    pdir.mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (tmp_path / "work").mkdir()
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
        "work_root": str(tmp_path / "work"),
        "quality_bar": "throwaway fixture",
        "push_enabled": push_enabled,
    }
    P = pdir / "config.json"
    P.write_text(json.dumps(data, indent=2) + "\n")
    O = pdir / "config.local.json"
    if overlay is not None:
        O.write_text(json.dumps(overlay, indent=2) + "\n")
    return P, O


_LOAD_CODE = (
    "import sys, json, foundry\n"
    "cfg = foundry.load_config(sys.argv[1])\n"
    "print(json.dumps({'push_enabled': cfg.push_enabled,\n"
    "                  'auth_resume_max': cfg.auth_resume_max}))\n"
)


def _load_sub(path):
    proc = subprocess.run([sys.executable, "-c", _LOAD_CODE, str(path)], cwd=str(_ROOT),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout), proc.stderr


def _cli(*args):
    proc = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), *args],
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def test_b6_overlay_push_on_over_tracked_false_is_ignored(tmp_path):
    P, _ = _setup(tmp_path, False, {"push_enabled": True})
    vals, err = _load_sub(P)
    assert vals["push_enabled"] is False
    assert "ignored push_enabled" in err


def test_b6_overlay_push_off_over_tracked_true_is_allowed(tmp_path):
    P, _ = _setup(tmp_path, True, {"push_enabled": False})
    vals, err = _load_sub(P)
    assert vals["push_enabled"] is False
    assert "ignored" not in err


def test_b6_anti_vacuity_tracked_true_without_overlay_is_true(tmp_path):
    P, _ = _setup(tmp_path, True, None)
    vals, err = _load_sub(P)
    assert vals["push_enabled"] is True
    assert "ignored" not in err


def test_b6_other_overlay_keys_still_win(tmp_path):
    """USAGE: the overlay's keys win EXCEPT the push-safety fields."""
    P, _ = _setup(tmp_path, False, {"push_enabled": True, "auth_resume_max": 24})
    base, _ = _load_sub(_setup(tmp_path / "b", False, None)[0])
    assert base["auth_resume_max"] != 24
    vals, err = _load_sub(P)
    assert vals["auth_resume_max"] == 24
    assert vals["push_enabled"] is False


def test_b6_lint_config_reports_overlay_escalation_as_error(tmp_path):
    """README #27: one ERROR finding per escalating overlay key (exit 1)."""
    P, _ = _setup(tmp_path, False, {"push_enabled": True})
    rc, out, err = _cli("lint-config", "--config", str(P))
    assert rc == 1, (out, err)
    hits = [ln for ln in (out + err).splitlines()
            if "push_enabled" in ln and "error" in ln.lower()]
    assert len(hits) >= 1, (out, err)


def test_b6_lint_config_anti_vacuity_push_off_overlay_is_clean(tmp_path):
    P, _ = _setup(tmp_path, True, {"push_enabled": False})
    rc, out, err = _cli("lint-config", "--config", str(P))
    assert rc != 1 or "push_enabled" not in (out + err), (rc, out, err)


def test_b6_overlay_set_refuses_push_escalation(tmp_path):
    """README #67: `--set` refuses a push escalation (exit 1, nothing written)."""
    P, O = _setup(tmp_path, False, {"auth_resume_max": 24})
    before = O.read_bytes()
    rc, out, err = _cli("overlay", "--config", str(P), "--set", "push_enabled=true")
    assert rc == 1, (out, err)
    assert "invalid choice" not in err
    assert O.read_bytes() == before


def test_b6_overlay_set_push_off_is_allowed(tmp_path):
    P, O = _setup(tmp_path, True, {"auth_resume_max": 24})
    rc, out, err = _cli("overlay", "--config", str(P), "--set", "push_enabled=false")
    assert rc == 0, (out, err)
    assert json.loads(O.read_text())["push_enabled"] is False


# ------------------------------------------------------------------ 7. imports


def test_b7_foundry_and_dispatcher_import():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
