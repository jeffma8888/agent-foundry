"""Behaviour tests for iter 499 -- `foundry.config_type_findings` and
`lint-config` report every wrongly-typed config value as an error finding
(and `lint_config` stops crashing on one, e.g. `test_cmd=5`).

Spec: the iter-499 PM spec (pm.md), Expected Behaviors 1-10.

ISOLATION: written by the tester stage under its black-box contract -- the
spec, tests/, README/USAGE and the product's runtime output only; no
implementation source, no diff, no engineer/reviewer notes. Every CLI fixture
is built in tmp_path from the TRACKED _platform config.json; the census in
EB4 enumerates configs via `git ls-files` (never gitignored state).
"""
import builtins
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import typing

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  (import-safety probe)

OVERLAY = "config" + ".local.json"
TRACKED_CFG = REPO / "products" / "_platform" / "config.json"
TO_DICT_KEYS = ["config_path", "findings", "n_errors", "n_warnings",
                "ok", "verdict", "exit_code"]

STR_T = "str"
BOOL_T = "bool"
INT_T = "int"
OPT_T = "opt"
TUP_T = "tup"


def _kind(tp):
    if tp is bool:
        return BOOL_T
    if tp is int:
        return INT_T
    if tp is str:
        return STR_T
    args = typing.get_args(tp)
    if typing.get_origin(tp) is tuple:
        return TUP_T
    if set(args) == {str, type(None)}:
        return OPT_T
    return None


HINTS = typing.get_type_hints(foundry.ProductConfig)
FIELD_NAMES = [f.name for f in dataclasses.fields(foundry.ProductConfig)]
KINDS = {n: _kind(HINTS[n]) for n in FIELD_NAMES}

GOOD = {STR_T: ["", "x"], BOOL_T: [True, False], INT_T: [0, 24, -1],
        OPT_T: [None, "", "echo ok"],
        TUP_T: ["", "a", ("a", "b"), ["a"], [], ()]}
BAD = {STR_T: [5, None, 1.5, True, ["x"], {"a": 1}],
       BOOL_T: ["false", 1, 0, None, "true"],
       INT_T: ["24", 24.0, True, False, None],
       OPT_T: [5, False, ["x"]],
       TUP_T: [5, [1], ("a", 2), None, {"a": "b"}]}
EXPECTED_T = {STR_T: "expected str", BOOL_T: "expected bool",
              INT_T: "expected int", OPT_T: "expected str or null",
              TUP_T: "expected list of str"}


class ReprBomb:
    def __repr__(self):
        raise RuntimeError("repr boom")

    __str__ = __repr__


def _valid_cfg(tmp_path, **over):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    vision = tmp_path / "VISION.md"
    vision.write_text("intent")
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("roadmap")
    qref = tmp_path / "qref"
    qref.mkdir(exist_ok=True)
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    data = dict(name="prod", repo=str(repo), allowed_push_repo="prod",
                vision=str(vision), roadmap=str(roadmap),
                quality_ref=str(qref), roles_dir=str(roles),
                test_cmd="uv run pytest", push_enabled=True)
    data.update(over)
    return foundry.ProductConfig(**data)


def _proj(findings, tmp_path=None):
    out = []
    for f in findings:
        d = f.detail
        if tmp_path is not None:
            d = d.replace(str(tmp_path), "<TMP>")
        out.append((f.field, f.level, d))
    return out


# --- EB1 -------------------------------------------------------------------

def test_eb1_exists_and_returns_tuple(tmp_path):
    assert callable(getattr(foundry, "config_type_findings", None))
    res = foundry.config_type_findings(_valid_cfg(tmp_path))
    assert isinstance(res, tuple)
    assert res == ()


def test_eb1_every_field_mistyped_declaration_order(tmp_path):
    cfg = _valid_cfg(tmp_path)
    over = {n: BAD[KINDS[n]][0] for n in FIELD_NAMES if KINDS[n]}
    assert len(over) >= 20  # every declared field has a recognised kind
    bad = dataclasses.replace(cfg, **over)
    res = foundry.config_type_findings(bad)
    assert isinstance(res, tuple)
    assert all(isinstance(f, foundry.ConfigFinding) for f in res)
    got = [f.field for f in res]
    assert got == [n for n in FIELD_NAMES if n in over]
    assert len(set(got)) == len(got)
    assert {f.level for f in res} == {"error"}


def test_eb1_types_read_at_call_time(tmp_path, monkeypatch):
    """Expected types come from get_type_hints at call time: re-declaring a
    field's annotation as `int` must flip a str value into a finding."""
    cfg = _valid_cfg(tmp_path)
    assert foundry.config_type_findings(cfg) == ()
    real = typing.get_type_hints

    def fake(obj, *a, **k):
        h = dict(real(obj, *a, **k))
        if obj is foundry.ProductConfig:
            h["name"] = int
        return h

    # foundry may reach get_type_hints as `typing.get_type_hints` or as a
    # module-level `from typing import get_type_hints` binding: patch both.
    monkeypatch.setattr(typing, "get_type_hints", fake)
    if hasattr(foundry, "get_type_hints"):
        monkeypatch.setattr(foundry, "get_type_hints", fake)
    res = foundry.config_type_findings(cfg)
    assert [f.field for f in res] == ["name"]
    assert "expected int" in res[0].detail


# --- EB2 / EB3 -------------------------------------------------------------

@pytest.mark.parametrize("field", [n for n in FIELD_NAMES if KINDS[n]])
def test_eb2_good_values_pass(tmp_path, field):
    cfg = _valid_cfg(tmp_path)
    for v in GOOD[KINDS[field]]:
        res = foundry.config_type_findings(dataclasses.replace(cfg, **{field: v}))
        assert res == (), (field, v, res)


@pytest.mark.parametrize("field", [n for n in FIELD_NAMES if KINDS[n]])
def test_eb2_eb3_bad_values_flagged(tmp_path, field):
    cfg = _valid_cfg(tmp_path)
    kind = KINDS[field]
    for v in BAD[kind]:
        res = foundry.config_type_findings(dataclasses.replace(cfg, **{field: v}))
        assert [f.field for f in res] == [field], (field, v, res)
        f = res[0]
        assert f.level == "error"
        assert EXPECTED_T[kind] in f.detail, (field, v, f.detail)
        assert f"got {type(v).__name__}" in f.detail, (field, v, f.detail)
        assert repr(v) in f.detail, (field, v, f.detail)


def test_eb3_spec_example_auth_resume_max(tmp_path):
    res = foundry.config_type_findings(
        _valid_cfg(tmp_path, auth_resume_max="24"))
    assert len(res) == 1
    f = res[0]
    assert (f.field, f.level) == ("auth_resume_max", "error")
    for s in ("expected int", "got str", "'24'"):
        assert s in f.detail


def test_eb2_named_examples(tmp_path):
    def one(**kw):
        return [f.field for f in foundry.config_type_findings(
            _valid_cfg(tmp_path, **kw))]
    assert one(push_enabled="false") == ["push_enabled"]
    assert one(push_enabled=1) == ["push_enabled"]
    assert one(auth_resume_max=24.0) == ["auth_resume_max"]
    assert one(auth_resume_max=True) == ["auth_resume_max"]
    assert one(test_cmd=5) == ["test_cmd"]
    assert one(test_cmd=None) == ["test_cmd"]
    assert one(smoke_cmd=None) == []
    assert one(smoke_cmd=5) == ["smoke_cmd"]
    assert one(gap_layers=[1]) == ["gap_layers"]
    assert one(gap_layers=5) == ["gap_layers"]
    assert one(gap_layers=["a", "b"]) == []
    assert one(gap_layers="a") == []


# --- EB4 -------------------------------------------------------------------

def test_eb4_never_raises_repr_bomb_every_field(tmp_path):
    cfg = _valid_cfg(tmp_path)
    for n in FIELD_NAMES:
        res = foundry.config_type_findings(
            dataclasses.replace(cfg, **{n: ReprBomb()}))
        assert isinstance(res, tuple)
        assert [f.field for f in res] == [n], (n, res)
    allbomb = dataclasses.replace(cfg, **{n: ReprBomb() for n in FIELD_NAMES})
    res = foundry.config_type_findings(allbomb)
    assert [f.field for f in res] == FIELD_NAMES


def test_eb4_no_mutation_no_filesystem(tmp_path, monkeypatch):
    cfg = _valid_cfg(tmp_path, auth_resume_max="24", gap_layers=["a", 1],
                     push_enabled="false")
    before = {n: getattr(cfg, n) for n in FIELD_NAMES}
    before_layers = list(cfg.gap_layers)

    def boom(*a, **k):
        raise AssertionError("filesystem touched")

    fn = foundry.config_type_findings  # resolve before the fs is stubbed
    try:
        for name in ("exists", "is_file", "is_dir", "stat", "read_text",
                     "iterdir", "open"):
            monkeypatch.setattr(pathlib.Path, name, boom)
        monkeypatch.setattr(builtins, "open", boom)
        monkeypatch.setattr(os, "stat", boom)
        monkeypatch.setattr(os, "listdir", boom)
        res = fn(cfg)
    finally:
        monkeypatch.undo()
    assert [f.field for f in res] == ["push_enabled", "gap_layers",
                                      "auth_resume_max"]
    assert {n: getattr(cfg, n) for n in FIELD_NAMES} == before
    assert list(cfg.gap_layers) == before_layers


def test_eb4_tracked_configs_are_clean():
    out = subprocess.run(["git", "ls-files", "products/*/config.json"],
                         cwd=REPO, capture_output=True, text=True, check=True)
    paths = [REPO / p for p in out.stdout.split() if p]
    assert paths, "no tracked product configs"
    for p in paths:
        cfg = foundry.load_config(str(p))
        assert foundry.config_type_findings(cfg) == (), p


# --- EB5 -------------------------------------------------------------------

def test_eb5_type_findings_first_and_bare_name(tmp_path, monkeypatch):
    sentinel = foundry.ConfigFinding("zz_sentinel", "error", "injected")
    monkeypatch.setattr(foundry, "config_type_findings",
                        lambda cfg: (sentinel,))
    lint = foundry.lint_config(_valid_cfg(tmp_path, name=""))
    assert lint.findings[0] is sentinel or (
        (lint.findings[0].field, lint.findings[0].detail)
        == ("zz_sentinel", "injected"))
    assert [f.field for f in lint.findings][1:] == ["name"]


def test_eb5_type_findings_precede_existing(tmp_path):
    cfg = _valid_cfg(tmp_path, auth_resume_max="24", name="",
                     repo=str(tmp_path / "nope"))
    lint = foundry.lint_config(cfg)
    fields = [f.field for f in lint.findings]
    assert fields[0] == "auth_resume_max"
    assert "name" in fields and "repo" in fields
    assert fields.index("name") < fields.index("repo")


def test_eb5_skip_name_check(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, name=5))
    assert [(f.field, f.level) for f in lint.findings] == [("name", "error")]
    assert "expected str" in lint.findings[0].detail


def test_eb5_skip_push_rule_when_push_enabled_mistyped(tmp_path):
    lint = foundry.lint_config(
        _valid_cfg(tmp_path, push_enabled="false", allowed_push_repo=""))
    assert [f.field for f in lint.findings] == ["push_enabled"]
    assert "expected bool" in lint.findings[0].detail


def test_eb5_skip_push_rule_when_allowed_repo_mistyped(tmp_path):
    lint = foundry.lint_config(
        _valid_cfg(tmp_path, push_enabled=True, allowed_push_repo=5))
    assert [f.field for f in lint.findings] == ["allowed_push_repo"]
    assert "expected str" in lint.findings[0].detail


def test_eb5_push_rule_still_fires_when_well_typed(tmp_path):
    lint = foundry.lint_config(
        _valid_cfg(tmp_path, push_enabled=True, allowed_push_repo=""))
    assert [(f.field, f.level) for f in lint.findings] == [
        ("allowed_push_repo", "error")]


# --- EB6 -------------------------------------------------------------------

def test_eb6_test_cmd_int_no_crash(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, test_cmd=5))
    assert isinstance(lint, foundry.ConfigLint)
    assert lint.exit_code == 1
    assert len(lint.findings) == 1
    f = lint.findings[0]
    assert (f.field, f.level) == ("test_cmd", "error")
    assert "expected str" in f.detail
    assert "empty" not in f.detail


def test_eb6_never_raises_json_values_every_field(tmp_path):
    cfg = _valid_cfg(tmp_path)
    json_vals = [5, None, 1.5, True, False, "x", "", [1], ["a"], {"a": 1}, []]
    for n in FIELD_NAMES:
        for v in json_vals:
            lint = foundry.lint_config(dataclasses.replace(cfg, **{n: v}))
            assert isinstance(lint, foundry.ConfigLint), (n, v)
            assert lint.exit_code in (0, 1), (n, v)


# --- EB7 -------------------------------------------------------------------
# Literal goldens captured from the pre-change (HEAD) lint_config on these
# exact well-typed fixtures; tmp_path is normalised to <TMP>.

GOLDEN_VARIANTS = {
    "valid": {},
    "no_name": {"name": ""},
    "blank_test_cmd": {"test_cmd": "   "},
    "push_no_allow": {"allowed_push_repo": ""},
    "no_push_no_allow": {"allowed_push_repo": "", "push_enabled": False},
    "missing_repo": {"repo": "<TMP>/nope"},
    "no_vision": {"vision": ""},
    "missing_files": {"vision": "<TMP>/nv.md", "roadmap": "<TMP>/nr.md",
                      "quality_ref": "<TMP>/nq", "roles_dir": "<TMP>/nroles"},
    "combo": {"name": "", "test_cmd": "", "allowed_push_repo": "",
              "repo": "<TMP>/nope", "vision": ""},
}

_APR = ("allowed_push_repo", "error",
        "allowed_push_repo is empty while push_enabled is true -- the push "
        "guard would block EVERY ship")
_NAME = ("name", "error", "product name is empty")
_TCMD = ("test_cmd", "error", "test_cmd is empty (no quality-check command)")
_REPO = ("repo", "error", "repo path does not exist: '<TMP>/nope'")
_VIS = ("vision", "warn",
        "vision path is unset (no fixed product intent to hold to)")
GOLDENS = {
    "valid": ([], "OK", 0),
    "no_name": ([_NAME], "PROBLEMS", 1),
    "blank_test_cmd": ([_TCMD], "PROBLEMS", 1),
    "push_no_allow": ([_APR], "PROBLEMS", 1),
    "no_push_no_allow": ([], "OK", 0),
    "missing_repo": ([_REPO], "PROBLEMS", 1),
    "no_vision": ([_VIS], "WARNINGS", 0),
    "missing_files": ([
        ("roles_dir", "error", "roles_dir does not exist: '<TMP>/nroles'"),
        ("vision", "error", "vision file does not exist: '<TMP>/nv.md'"),
        ("roadmap", "warn", "roadmap file does not exist yet: '<TMP>/nr.md' "
         "(the PM creates it on the first iteration)"),
        ("quality_ref", "warn", "quality_ref path does not exist: '<TMP>/nq'"),
    ], "PROBLEMS", 1),
    "combo": ([_NAME, _REPO, _APR, _TCMD, _VIS], "PROBLEMS", 1),
}


def _variant_cfg(tmp_path, over):
    over = {k: (v.replace("<TMP>", str(tmp_path)) if isinstance(v, str) else v)
            for k, v in over.items()}
    return _valid_cfg(tmp_path, **over)


@pytest.mark.parametrize("variant", sorted(GOLDEN_VARIANTS))
def test_eb7_well_typed_lint_unchanged(tmp_path, variant):
    cfg = _variant_cfg(tmp_path, GOLDEN_VARIANTS[variant])
    lint = foundry.lint_config(cfg)
    got = (_proj(lint.findings, tmp_path), lint.verdict, lint.exit_code)
    assert got == GOLDENS[variant]


def test_eb7_equal_with_type_core_stubbed(tmp_path, monkeypatch):
    """For well-typed configs the type core contributes nothing, so the
    result is == to the result with the core stubbed out."""
    for over in GOLDEN_VARIANTS.values():
        cfg = _variant_cfg(tmp_path, over)
        real = foundry.lint_config(cfg)
        monkeypatch.setattr(foundry, "config_type_findings", lambda c: ())
        stub = foundry.lint_config(cfg)
        monkeypatch.undo()
        assert real == stub


# --- EB8 / EB9 (CLI) -------------------------------------------------------

def _cli_cfg(tmp_path, overlay=None):
    raw = json.loads(TRACKED_CFG.read_text())
    raw["work_root"] = str(tmp_path / "work")
    p = tmp_path / "config.json"
    p.write_text(json.dumps(raw, indent=2))
    if overlay is not None:
        (tmp_path / OVERLAY).write_text(json.dumps(overlay))
    return p


def _lint_cli(cfg, *extra):
    return subprocess.run(
        [sys.executable, str(REPO / "foundry.py"), "lint-config",
         "--config", str(cfg), *extra],
        capture_output=True, text=True, timeout=60)


def _lines(out):
    return [ln for ln in out.splitlines() if ln.strip()]


def test_eb8_cli_auth_resume_max_string(tmp_path):
    r = _lint_cli(_cli_cfg(tmp_path, {"auth_resume_max": "24"}))
    assert r.returncode == 1, r.stdout + r.stderr
    lines = _lines(r.stdout)
    assert lines[-1] == "verdict: PROBLEMS"
    hits = [ln for ln in lines if ln.startswith("  [error] auth_resume_max: ")]
    assert len(hits) == 1 and "expected int" in hits[0]


def test_eb8_cli_push_enabled_string(tmp_path):
    r = _lint_cli(_cli_cfg(tmp_path, {"push_enabled": "false"}))
    assert r.returncode == 1, r.stdout + r.stderr
    hits = [ln for ln in _lines(r.stdout) if "[error] push_enabled:" in ln]
    assert len(hits) == 1 and "expected bool" in hits[0]


def test_eb8_cli_test_cmd_int_no_traceback(tmp_path):
    r = _lint_cli(_cli_cfg(tmp_path, {"test_cmd": 5}))
    assert r.returncode == 1, r.stdout + r.stderr
    lines = _lines(r.stdout)
    assert lines[-1] == "verdict: PROBLEMS"
    assert any("[error] test_cmd:" in ln for ln in lines)
    both = r.stdout + r.stderr
    assert "Traceback" not in both
    assert "AttributeError" not in both


def test_eb8_cli_no_overlay_ok(tmp_path):
    r = _lint_cli(_cli_cfg(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    lines = _lines(r.stdout)
    assert lines[-1] == "verdict: OK"
    assert not any("[error]" in ln for ln in lines)


def test_eb9_cli_json(tmp_path):
    r = _lint_cli(_cli_cfg(tmp_path, {"auth_resume_max": "24"}), "--json")
    assert r.returncode == 1, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert list(doc.keys()) == TO_DICT_KEYS
    f0 = doc["findings"][0]
    assert set(f0) == {"field", "level", "detail"}
    assert f0["field"] == "auth_resume_max"
    assert f0["level"] == "error"
    assert "expected int" in f0["detail"]
    assert doc["exit_code"] == 1
    assert doc["ok"] is False


# --- EB10 ------------------------------------------------------------------

def test_eb10_load_config_still_loads_mistyped(tmp_path):
    p = _cli_cfg(tmp_path, {"auth_resume_max": "24", "push_enabled": "false",
                            "test_cmd": 5})
    cfg = foundry.load_config(str(p))
    assert cfg.auth_resume_max == "24"
    assert cfg.push_enabled == "false"
    assert cfg.test_cmd == 5


def test_eb10_dispatcher_importable():
    # (No source-freeze assertion here: the repo's control-path guard audit
    # forbids narrow per-file freezes; importability is the observable pin.)
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=REPO, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
