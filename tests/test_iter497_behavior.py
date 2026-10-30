"""Iteration 497 -- BLACK-BOX behavior tests: `foundry resume` is the LIFT half of the
STOP contract (the inverse of iter 371's `stop`).

Spec under test: products/_platform/state/iter-497/pm.md, Expected Behaviors 1-12.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-497
PM spec, the product README / roadmap text, the conventions under `tests/`, and the
product's OWN observable behavior (calling its public names and its CLI).  The
implementation source, the engineer/reviewer notes, IMPLEMENTATION.patch and any
`git diff` were NOT read.  Behavior 12's byte-safety pins are sha256 goldens of the
HEAD (pre-iteration) function sources, hashed without being read.

FLEET SAFETY: every `--global` call patches `foundry.FOUNDRY` into tmp_path first, so
the real company sentinel is never touched.  All fixtures live in tmp_path; nothing
gitignored is asserted; no absolute machine path appears in this file.
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import io
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  -- import-safety probe

FIELDS = ("action", "scope", "sentinel", "reason", "text", "existed", "error", "exit_code")
AUDIT_TEXT = "paused for audit; resume when audit closes\nsecond line\n"
AUDIT_REASON_LINE = "paused for audit; resume when audit closes"


# ---------------------------------------------------------------- helpers


def _capture(fn):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            rc = fn()
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 2
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _product_config(tmp_path: pathlib.Path, name: str = "team"):
    work_root = tmp_path / name
    work_root.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / (name + ".json")
    config_path.write_text(json.dumps({
        "name": name,
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "none",
        "branch": "main",
        "vision": str(tmp_path / "VISION.md"),
        "roadmap": str(tmp_path / "ROADMAP.md"),
        "quality_ref": str(tmp_path / "repo"),
        "test_cmd": "true",
        "roles_dir": str(_ROOT / "roles"),
        "work_root": str(work_root),
        "quality_bar": "throwaway fixture",
        "push_enabled": False,
    }, indent=2))
    return config_path, work_root


@pytest.fixture
def iso_foundry(tmp_path, monkeypatch):
    """Point foundry.FOUNDRY at an empty tmp dir so no real company STOP is visible."""
    g = tmp_path / "company"
    g.mkdir()
    monkeypatch.setattr(foundry, "FOUNDRY", g)
    return g


def _resume(*args):
    return _capture(lambda: foundry.main(["resume", *args]))


def _one_line(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, out
    return lines[0]


# ------------------------------------------------------------ 1. pure core


def test_b1_actions_and_fields():
    assert foundry.RESUME_ACTIONS == ("LIFTED", "ABSENT", "FAILED")
    names = tuple(f.name for f in dataclasses.fields(foundry.ResumeVerdict))
    assert names == FIELDS
    ec = [f for f in dataclasses.fields(foundry.ResumeVerdict) if f.name == "exit_code"][0]
    assert ec.init is False


def test_b1_rules_first_match_wins_and_exit_codes():
    v = foundry.resume_verdict("team", "S", existed=True, existing_reason="r", text="r\n")
    assert (v.action, v.exit_code, v.reason, v.text, v.existed, v.error) == (
        "LIFTED", 0, "r", "r\n", True, "")
    v = foundry.resume_verdict("team", "S", existed=False)
    assert (v.action, v.exit_code) == ("ABSENT", 1)
    # error outranks existed=True and existed=False
    v = foundry.resume_verdict("team", "S", existed=True, error="PermissionError")
    assert (v.action, v.exit_code, v.error) == ("FAILED", 2, "PermissionError")
    v = foundry.resume_verdict("global", "S", existed=False, error="boom")
    assert (v.action, v.exit_code, v.scope) == ("FAILED", 2, "global")


def test_b1_frozen_and_exit_code_not_init():
    v = foundry.resume_verdict("team", "S", existed=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.action = "ABSENT"  # type: ignore[misc]
    kwargs = {f.name: getattr(v, f.name) for f in dataclasses.fields(v) if f.init}
    with pytest.raises(TypeError):
        foundry.ResumeVerdict(**kwargs, exit_code=0)


def test_b1_total_coercion_and_equality():
    v = foundry.resume_verdict(None, None, existed=True, existing_reason=None, text=None,
                               error=None)
    assert (v.scope, v.sentinel, v.reason, v.text, v.error) == ("", "", "", "", "")
    assert v.action == "LIFTED"
    v = foundry.resume_verdict(7, pathlib.Path("a") / "STOP", existed=1,
                               existing_reason=3, text=4.5, error="")
    assert (v.scope, v.reason, v.text) == ("7", "3", "4.5")
    assert v.sentinel == str(pathlib.Path("a") / "STOP")
    assert isinstance(v.scope, str) and isinstance(v.sentinel, str)
    v = foundry.resume_verdict("team", "S", existed=False, error=ValueError)
    assert v.action == "FAILED" and isinstance(v.error, str) and v.error
    a = foundry.resume_verdict("team", "S", existed=True, existing_reason="x", text="x\n")
    b = foundry.resume_verdict("team", "S", existed=True, existing_reason="x", text="x\n")
    assert a == b
    assert a != foundry.resume_verdict("team", "S", existed=False)


def test_b1_to_dict_round_trips():
    v = foundry.resume_verdict("team", "S", existed=True, existing_reason="r", text="r\nz\n")
    d = v.to_dict()
    assert tuple(d.keys()) == FIELDS or set(d.keys()) == set(FIELDS)
    assert set(d.keys()) == set(FIELDS)
    assert json.loads(json.dumps(d)) == d
    assert d["exit_code"] == 0 and d["action"] == "LIFTED"


# ------------------------------------------------------- 2. team lift (human)


def test_b2_team_lift_human(tmp_path, iso_foundry):
    cfg_path, work_root = _product_config(tmp_path)
    stop = work_root / "STOP"
    stop.write_text(AUDIT_TEXT)
    rc, out, err = _resume("--config", str(cfg_path))
    assert rc == 0, (out, err)
    assert not stop.exists()
    cfg = foundry.load_config(str(cfg_path))
    assert foundry.stopping(cfg) is False
    line = _one_line(out)
    assert line.startswith("resume: LIFTED -- team scope; sentinel "), line
    assert AUDIT_REASON_LINE in line
    assert "next round" in line


# ------------------------------------------------------------ 3. JSON payload


def test_b3_team_lift_json(tmp_path, iso_foundry):
    cfg_path, work_root = _product_config(tmp_path)
    stop = work_root / "STOP"
    stop.write_text(AUDIT_TEXT)
    rc, out, err = _resume("--config", str(cfg_path), "--json")
    assert rc == 0, (out, err)
    doc = json.loads(out)  # exactly one JSON document
    assert set(doc.keys()) == set(FIELDS)
    assert doc["action"] == "LIFTED" and doc["scope"] == "team"
    assert doc["existed"] is True and doc["error"] == "" and doc["exit_code"] == 0
    assert doc["reason"] == foundry.stop_reason(AUDIT_TEXT)
    assert doc["reason"] == AUDIT_REASON_LINE
    assert doc["text"] == AUDIT_TEXT
    assert not stop.exists()


# ------------------------------------------------------------------ 4. absent


def test_b4_absent(tmp_path, iso_foundry):
    cfg_path, work_root = _product_config(tmp_path)
    stop = work_root / "STOP"
    rc, out, _ = _resume("--config", str(cfg_path))
    assert rc == 1
    line = _one_line(out)
    assert line.startswith("resume: ABSENT -- team scope; sentinel "), line
    assert "nothing to lift" in line
    assert not stop.exists()
    rc, out, _ = _resume("--config", str(cfg_path), "--json")
    assert rc == 1
    doc = json.loads(out)
    assert doc["action"] == "ABSENT" and doc["existed"] is False
    assert doc["reason"] == "" and doc["text"] == "" and doc["exit_code"] == 1
    assert not stop.exists() and not stop.is_dir()


# ------------------------------------------------------------ 5. global scope


def test_b5_global_scope_lifts_only_company_sentinel(tmp_path, iso_foundry, monkeypatch):
    cfg_path, work_root = _product_config(tmp_path)
    team_stop = work_root / "STOP"
    team_stop.write_bytes(b"team halt\n")
    g_stop = iso_foundry / "STOP"
    g_stop.write_text("company halt\n")

    def _no_load(*a, **k):
        raise AssertionError("load_config must not be called for --global")

    monkeypatch.setattr(foundry, "load_config", _no_load)
    rc, out, err = _resume("--global")
    assert rc == 0, (out, err)
    assert not g_stop.exists()
    assert team_stop.read_bytes() == b"team halt\n"
    line = _one_line(out)
    assert line.startswith("resume: LIFTED -- global scope; sentinel "), line
    assert "restart the dispatcher" in line


def test_b5_global_json(tmp_path, iso_foundry):
    (iso_foundry / "STOP").write_text("company halt\n")
    rc, out, _ = _resume("--global", "--json")
    assert rc == 0
    doc = json.loads(out)
    assert doc["scope"] == "global" and doc["action"] == "LIFTED"
    assert doc["reason"] == "company halt" and doc["text"] == "company halt\n"


# ---------------------------------------------- 6. a directory is never removed


def test_b6_directory_is_never_removed(tmp_path, iso_foundry):
    assert isinstance(foundry.RESUME_NOT_A_FILE_ERROR, str) and foundry.RESUME_NOT_A_FILE_ERROR
    cfg_path, work_root = _product_config(tmp_path)
    d = work_root / "STOP"
    d.mkdir()
    (d / "inner.txt").write_text("keep me")
    rc, out, _ = _resume("--config", str(cfg_path))
    assert rc == 2
    assert "nothing was removed" in _one_line(out)
    assert d.is_dir() and (d / "inner.txt").read_text() == "keep me"
    rc, out, _ = _resume("--config", str(cfg_path), "--json")
    assert rc == 2
    doc = json.loads(out)
    assert doc["action"] == "FAILED" and doc["exit_code"] == 2
    assert doc["error"] == foundry.RESUME_NOT_A_FILE_ERROR
    assert d.is_dir() and (d / "inner.txt").exists()


# --------------------------------------------------------- 7. unlink failure


def test_b7_unlink_failure_reports_type_name_only(tmp_path, iso_foundry, monkeypatch):
    cfg_path, work_root = _product_config(tmp_path)
    stop = work_root / "STOP"
    stop.write_text("held reason\n")
    leak = "/" + "abs" + "/path"

    def _raise(self, *a, **k):
        raise PermissionError("x " + leak)

    monkeypatch.setattr(pathlib.Path, "unlink", _raise)
    rc, out, _ = _resume("--config", str(cfg_path), "--json")
    assert rc == 2
    doc = json.loads(out)
    assert doc["action"] == "FAILED" and doc["error"] == "PermissionError"
    assert doc["reason"] == "held reason"
    assert leak not in out
    assert stop.exists()
    rc, out, _ = _resume("--config", str(cfg_path))
    assert rc == 2
    assert leak not in out and "held reason" in out
    assert stop.exists()


# ------------------------------------------------ 8. unreadable / empty text


def test_b8_unreadable_bytes_still_lift(tmp_path, iso_foundry):
    cfg_path, work_root = _product_config(tmp_path)
    stop = work_root / "STOP"
    stop.write_bytes(b"\xff\xfe\xfa")
    rc, out, _ = _resume("--config", str(cfg_path), "--json")
    assert rc == 0, out
    doc = json.loads(out)
    assert doc["action"] == "LIFTED"
    assert doc["reason"] == foundry.STOP_REASON_UNREADABLE
    assert doc["text"] == ""
    assert not stop.exists()


def test_b8_zero_byte_sentinel(tmp_path, iso_foundry):
    cfg_path, work_root = _product_config(tmp_path)
    stop = work_root / "STOP"
    stop.touch()
    rc, out, _ = _resume("--config", str(cfg_path))
    assert rc == 0
    assert "(no reason recorded)" in _one_line(out)
    assert not stop.exists()
    stop.touch()
    rc, out, _ = _resume("--config", str(cfg_path), "--json")
    assert rc == 0 and json.loads(out)["reason"] == ""


# --------------------------------------------- 9. target required & exclusive


def test_b9_target_required_and_exclusive(tmp_path, iso_foundry):
    cfg_path, work_root = _product_config(tmp_path)
    (work_root / "STOP").write_text("keep\n")
    with pytest.raises(SystemExit) as ei:
        _quiet(lambda: foundry.main(["resume"]))
    assert ei.value.code == 2
    with pytest.raises(SystemExit) as ei:
        _quiet(lambda: foundry.main(["resume", "--config", str(cfg_path), "--global"]))
    assert ei.value.code == 2
    assert (work_root / "STOP").read_text() == "keep\n"

    (iso_foundry / "STOP").write_text("g\n")
    before = sorted(p.name for p in tmp_path.rglob("*"))
    rc, out, _ = _capture(lambda: foundry.resume_cli(None, as_json=True))
    assert rc == 2
    doc = json.loads(out)
    assert doc["action"] == "FAILED" and doc["error"]
    assert (iso_foundry / "STOP").exists() and (work_root / "STOP").exists()
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
    rc, out, _ = _capture(lambda: foundry.resume_cli(None))
    assert rc == 2 and (iso_foundry / "STOP").exists()


def _quiet(fn):
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        return fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err


# --------------------------------------------------- 10. round trip with stop


def test_b10_round_trip_with_stop(tmp_path, iso_foundry):
    cfg_path, work_root = _product_config(tmp_path)
    rc, out, err = _capture(lambda: foundry.main(
        ["stop", "--config", str(cfg_path), "--reason", "r1"]))
    assert rc == 0, (out, err)
    assert (work_root / "STOP").exists()
    rc, out, _ = _resume("--config", str(cfg_path), "--json")
    assert rc == 0
    assert json.loads(out)["reason"] == "r1"
    assert not (work_root / "STOP").exists()
    rc, out, _ = _resume("--config", str(cfg_path), "--json")
    assert rc == 1 and json.loads(out)["action"] == "ABSENT"


# ------------------------------------------------------- 11. census and index


def test_b11_census_and_readme_index():
    src = (_ROOT / "foundry.py").read_text()
    verbs = foundry.foundry_cli_verbs(src)
    assert "resume" in verbs
    assert len(set(verbs)) == 65
    readme = (_ROOT / "README.md").read_text()
    audit = foundry.readme_verb_index_gaps(readme, verbs)
    assert audit.ok is True and tuple(audit.missing_verbs) == (), audit
    assert tuple(audit.unknown_invocations) == (), audit
    entry = [ln for ln in readme.splitlines() if ln.startswith("# 66.")]
    assert entry and "resume" in entry[0], entry
    t362 = (_ROOT / "tests" / "test_iter362_behavior.py").read_text()
    pin = [ln for ln in t362.splitlines() if ln.startswith("EXPECTED_VERB_COUNT")]
    assert len(pin) == 1 and pin[0].split("=")[1].split("#")[0].strip() == "65", pin


def test_b11_help_lists_resume():
    rc, out, _ = _capture(lambda: foundry.main(["resume", "--help"]))
    assert rc == 0
    for flag in ("--config", "--global", "--json"):
        assert flag in out


# --------------------------------------------------- 12. dormant & byte-safe

# sha256 of each function's source segment at the pre-iteration HEAD (6a1651b).
STOP_BODY_GOLDENS = {
    "stop_cli": "8da8e18fd8be6e447b62957e4c1d8505bb6ddc96ac3577fd04df4076ee63bbef",
    "stop_write_verdict": "74990aa9e505dab316cc8c0e348fb2133faf7f4863b7d46e151302a8a17a0c58",
    "render_stop_text": "589149d986f7c4f800a7e26e761a952fc6d3b2b76f0446b6bffac09c712ec50f",
    "stop_reason": "3c425d7cafbd03410723e8fd89a8c68f0d68ae113b63646526cd222b63608327",
    "gather_stop": "a2b9f6de19a39f48e59a3db7e5ae0efdd9455bf4aab43afc8e7f61fa02b869df",
    "global_stop": "85f65b78951aac937a0f42455d667dd16a6be35cfd7a31079e815d013d9b7d27",
    "stopping": "0b702df41e78031bca941a464a053da85a092d62c01d8d66028233be8051ccf1",
}


def _top_level_defs(src: str) -> dict:
    tree = ast.parse(src)
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def test_b12_stop_bodies_unchanged():
    src = (_ROOT / "foundry.py").read_text()
    defs = _top_level_defs(src)
    for name, golden in STOP_BODY_GOLDENS.items():
        seg = ast.get_source_segment(src, defs[name])
        assert hashlib.sha256(seg.encode()).hexdigest() == golden, name


def test_b12_no_orchestrator_references_resume():
    src = (_ROOT / "foundry.py").read_text()
    defs = _top_level_defs(src)
    for orch in ("run_iteration", "run_stage"):
        assert orch in defs, orch
        names = {n.id for n in ast.walk(defs[orch]) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(defs[orch]) if isinstance(n, ast.Attribute)}
        assert not names & {"resume_cli", "resume_verdict"}, orch
    # The only call sites of resume_cli live in main()/its CLI dispatch, never in an
    # orchestrator: every function that names it must be resume-family or main.
    callers = set()
    for name, node in defs.items():
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id in ("resume_cli", "resume_verdict"):
                callers.add(name)
    assert callers, "resume_cli must be reachable from the CLI"
    for c in callers:
        assert not c.startswith("run_"), callers
        assert "final" not in c and "gate" not in c and "iteration" not in c, callers
    dsrc = (_ROOT / "dispatcher.py").read_text()
    assert "resume_cli" not in dsrc and "resume_verdict" not in dsrc


def test_b12_usage_cheat_sheet_untouched_by_resume():
    usage = (_ROOT / "USAGE.md").read_text()
    head, _, rest = usage.partition("## Controls cheat-sheet")
    assert rest, "cheat-sheet section missing"
    section = rest.split("\n## ", 1)[0]
    assert "foundry resume" not in section and "resume --config" not in section
