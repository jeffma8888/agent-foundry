"""Iteration 503 -- BLACK-BOX behavior tests: `foundry overlay` is the validated WRITER
for the machine-local `config.local.json` overlay beside a product config.

Spec under test: products/_platform/state/iter-503/pm.md, Expected Behaviors 1-13.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-503
PM spec, the product README / roadmap text, the conventions under `tests/`, and the
product's OWN observable behavior (calling its public names and its CLI).  The
implementation source, the engineer/reviewer notes, IMPLEMENTATION.patch and any
`git diff` were NOT read.  Behavior 13's byte-safety pins are sha256 goldens of the
pre-iteration HEAD (0034e68) function sources, hashed without being read.

FIXTURE SAFETY: every P (product config) and O (its config.local.json) lives in
tmp_path; no real products/*/config.local.json (gitignored) is read or written, and no
absolute machine path appears in this file.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  -- import-safety probe


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


def _setup(tmp_path: pathlib.Path, content=None, raw: bytes | None = None,
           filename: str = "config.json"):
    """Build P (a loadable product config) and O (its sibling overlay) in tmp_path."""
    pdir = tmp_path / "products" / "x"
    pdir.mkdir(parents=True, exist_ok=True)
    work_root = tmp_path / "work"
    work_root.mkdir(exist_ok=True)
    P = pdir / filename
    P.write_text(json.dumps({
        "name": "x",
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
        "push_enabled": True,
    }, indent=2) + "\n")
    O = pdir / "config.local.json"
    if raw is not None:
        O.write_bytes(raw)
    elif content is not None:
        O.write_text(json.dumps(content, indent=2) + "\n")
    return P, O


def _snap(P, O):
    return (P.read_bytes(), O.read_bytes() if O.exists() else None)


def _run(P, *args):
    return _capture(lambda: foundry.main(["overlay", "--config", str(P), *args]))


def _assert_no_leftovers(O, expected=("config.json", "config.local.json")):
    names = sorted(os.listdir(O.parent))
    allowed = set(expected)
    assert set(names) <= allowed, names
    assert not [n for n in names if n.endswith(".tmp")], names


def _assert_shape(O):
    text = O.read_text()
    obj = json.loads(text)
    assert text == json.dumps(obj, indent=2) + "\n", text
    return obj


# ---------------------------------------------------------------- 1. create


def test_b1_create(tmp_path):
    P, O = _setup(tmp_path)
    p_before = P.read_bytes()
    rc, out, err = _run(P, "--set", "auth_resume_max=24")
    assert rc == 0, (out, err)
    assert O.exists()
    obj = json.loads(O.read_text())
    assert obj == {"auth_resume_max": 24}
    assert type(obj["auth_resume_max"]) is int
    assert out.splitlines() == [f"overlay: auth_resume_max (unset) -> 24 ({O})"], out
    assert P.read_bytes() == p_before
    _assert_shape(O)
    _assert_no_leftovers(O)


# ---------------------------------------------------- 2. update preserves rest


def test_b2_update_preserves_other_keys_and_order(tmp_path):
    P, O = _setup(tmp_path, {"_comment": "keep me", "auth_resume_max": 24})
    p_before = P.read_bytes()
    rc, out, err = _run(P, "--set", "auth_resume_max=12")
    assert rc == 0, (out, err)
    obj = json.loads(O.read_text())
    assert obj == {"_comment": "keep me", "auth_resume_max": 12}
    assert list(obj) == ["_comment", "auth_resume_max"]
    assert out.splitlines() == [f"overlay: auth_resume_max 24 -> 12 ({O})"], out
    assert P.read_bytes() == p_before
    _assert_no_leftovers(O)


def test_b2_new_key_appended_at_end(tmp_path):
    P, O = _setup(tmp_path, {"_comment": "keep me", "auth_resume_max": 24})
    rc, out, err = _run(P, "--set", "branch=dev")
    assert rc == 0, (out, err)
    obj = json.loads(O.read_text())
    assert list(obj) == ["_comment", "auth_resume_max", "branch"]
    assert obj["branch"] == "dev"
    assert out.splitlines() == [f'overlay: branch (unset) -> "dev" ({O})'], out


# ---------------------------------------------------------------- 3. round trip


@pytest.mark.parametrize("arg,field,expected", [
    ("push_enabled=false", "push_enabled", False),
    ("auth_resume_max=24", "auth_resume_max", 24),
    ("branch=dev", "branch", "dev"),
])
def test_b3_round_trip_through_load_config(tmp_path, arg, field, expected):
    P, O = _setup(tmp_path)
    rc, out, err = _run(P, "--set", arg)
    assert rc == 0, (out, err)
    cfg = foundry.load_config(P)
    value = getattr(cfg, field)
    assert value == expected and type(value) is type(expected), value


# ------------------------------------------------------------ 4. value parsing


@pytest.mark.parametrize("arg,key,stored", [
    ("push_enabled=false", "push_enabled", False),
    ("push_enabled=true", "push_enabled", True),
    ("branch=dev", "branch", "dev"),
    ("branch=5", "branch", "5"),
    ("auth_resume_max=7", "auth_resume_max", 7),
])
def test_b4_first_type_valid_reading(tmp_path, arg, key, stored):
    P, O = _setup(tmp_path)
    rc, out, err = _run(P, "--set", arg)
    assert rc == 0, (out, err)
    obj = json.loads(O.read_text())
    assert obj == {key: stored}
    assert type(obj[key]) is type(stored), obj


def test_b4_value_split_on_first_equals(tmp_path):
    P, O = _setup(tmp_path)
    rc, out, err = _run(P, "--set", "test_cmd=make CHECK=1")
    assert rc == 0, (out, err)
    assert json.loads(O.read_text()) == {"test_cmd": "make CHECK=1"}


# -------------------------------------------------------- 5. wrong type refused


@pytest.mark.parametrize("arg,label", [
    ("auth_resume_max=24x", "int"),
    ("push_enabled=no", "bool"),
])
@pytest.mark.parametrize("initial", [None, {"_comment": "c", "auth_resume_max": 3}])
def test_b5_wrong_type_refused(tmp_path, arg, label, initial):
    P, O = _setup(tmp_path, initial)
    before = _snap(P, O)
    rc, out, err = _run(P, "--set", arg)
    assert rc == 1, (out, err)
    assert _snap(P, O) == before
    text = out + err
    assert "wrong value type" in text, text
    assert label in text, text
    _assert_no_leftovers(O)


# ----------------------------------------------------- 6. unknown key refused


@pytest.mark.parametrize("initial", [None, {"auth_resume_max": 24}])
def test_b6_unknown_key_refused_with_hint(tmp_path, initial):
    P, O = _setup(tmp_path, initial)
    before = _snap(P, O)
    rc, out, err = _run(P, "--set", "push_enable=true")
    assert rc == 1, (out, err)
    assert _snap(P, O) == before
    text = out + err
    assert "push_enable" in text
    assert "did you mean 'push_enabled'" in text, text
    _assert_no_leftovers(O)


def test_b6_comment_key_refused_for_set(tmp_path):
    P, O = _setup(tmp_path, {"_comment": "c"})
    before = _snap(P, O)
    rc, out, err = _run(P, "--set", "_comment=new")
    assert rc == 1, (out, err)
    assert _snap(P, O) == before
    _assert_no_leftovers(O)


# ---------------------------------------------------------------- 7. unset


def test_b7_unset_present_key(tmp_path):
    P, O = _setup(tmp_path, {"_comment": "c", "auth_resume_max": 24})
    p_before = P.read_bytes()
    rc, out, err = _run(P, "--unset", "auth_resume_max")
    assert rc == 0, (out, err)
    assert json.loads(O.read_text()) == {"_comment": "c"}
    assert out.splitlines() == [f"overlay: auth_resume_max 24 -> (unset) ({O})"], out
    assert P.read_bytes() == p_before
    _assert_shape(O)
    _assert_no_leftovers(O)


@pytest.mark.parametrize("initial", [None, {"_comment": "c"}])
def test_b7_unset_missing_key(tmp_path, initial):
    P, O = _setup(tmp_path, initial)
    before = _snap(P, O)
    rc, out, err = _run(P, "--unset", "auth_resume_max")
    assert rc == 1, (out, err)
    assert _snap(P, O) == before
    if initial is None:
        assert not O.exists()
    assert "not set" in out + err
    _assert_no_leftovers(O)


# ------------------------------------------------ 8. unset repairs a typo key


def test_b8_unset_removes_unknown_key(tmp_path):
    P, O = _setup(tmp_path, {"push_enable": True})
    rc, out, err = _run(P, "--unset", "push_enable")
    assert rc == 0, (out, err)
    assert json.loads(O.read_text()) == {}
    _assert_no_leftovers(O)


def test_b8_set_refuses_overlay_holding_unknown_key(tmp_path):
    P, O = _setup(tmp_path, {"push_enable": True})
    before = _snap(P, O)
    rc, out, err = _run(P, "--set", "auth_resume_max=24")
    assert rc == 2, (out, err)
    assert _snap(P, O) == before
    assert "push_enable" in out + err
    _assert_no_leftovers(O)


# --------------------------------------------- 9. broken overlay never written


BAD_JSON = b'{"auth_resume_max": 24,}'


@pytest.mark.parametrize("args", [
    ("--set", "auth_resume_max=12"),
    ("--unset", "auth_resume_max"),
])
def test_b9_invalid_json_never_overwritten(tmp_path, args):
    P, O = _setup(tmp_path, raw=BAD_JSON)
    before = _snap(P, O)
    rc, out, err = _run(P, *args)
    assert rc == 2, (out, err)
    assert _snap(P, O) == before
    text = out + err
    assert str(O) in text, text
    assert "not valid JSON" in text, text
    _assert_no_leftovers(O)


@pytest.mark.parametrize("raw", [b"[1]\n", b'{"branch": "\xff\xfe"}\n'])
@pytest.mark.parametrize("args", [
    ("--set", "auth_resume_max=12"),
    ("--unset", "auth_resume_max"),
])
def test_b9_non_object_and_non_utf8_refused(tmp_path, raw, args):
    P, O = _setup(tmp_path, raw=raw)
    before = _snap(P, O)
    rc, out, err = _run(P, *args)
    assert rc == 2, (out, err)
    assert _snap(P, O) == before
    # anti-vacuity: the refusal is the verb's own (names O), not an argparse reject
    assert str(O) in out + err, (out, err)
    assert "invalid choice" not in err, err
    _assert_no_leftovers(O)


# ---------------------------------------------------------------- 10. bad target


def test_b10_missing_config(tmp_path):
    missing = tmp_path / "products" / "nope" / "config.json"
    rc, out, err = _capture(lambda: foundry.main(
        ["overlay", "--config", str(missing), "--set", "auth_resume_max=24"]))
    assert rc == 2, (out, err)
    assert str(missing) in out + err, (out, err)
    assert "invalid choice" not in err, err
    assert not missing.parent.exists() or not os.listdir(missing.parent)
    assert not (missing.parent / "config.local.json").exists()


def test_b10_config_named_config_local_json(tmp_path):
    P, _ = _setup(tmp_path, filename="config.local.json")
    before = P.read_bytes()
    rc, out, err = _run(P, "--set", "auth_resume_max=24")
    assert rc == 2, (out, err)
    assert str(P) in out + err, (out, err)
    assert "invalid choice" not in err, err
    assert P.read_bytes() == before
    assert sorted(os.listdir(P.parent)) == ["config.local.json"]


# ---------------------------------------------------------- 11. output file shape


def test_b11_atomic_replace_in_same_dir(tmp_path, monkeypatch):
    P, O = _setup(tmp_path, {"_comment": "c"})
    calls = []
    real_replace = os.replace

    def spy(src, dst, *a, **kw):
        calls.append((pathlib.Path(src), pathlib.Path(dst)))
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(os, "replace", spy)
    rc, out, err = _run(P, "--set", "auth_resume_max=24")
    assert rc == 0, (out, err)
    assert len(calls) == 1, calls
    src, dst = calls[0]
    assert dst.resolve() == O.resolve()
    assert src.parent.resolve() == O.parent.resolve()
    assert _assert_shape(O) == {"_comment": "c", "auth_resume_max": 24}
    _assert_no_leftovers(O)


def test_b11_rewrite_normalises_shape(tmp_path):
    P, O = _setup(tmp_path, raw=b'{"_comment":"c","auth_resume_max":24}')
    rc, out, err = _run(P, "--set", "auth_resume_max=5")
    assert rc == 0, (out, err)
    assert _assert_shape(O) == {"_comment": "c", "auth_resume_max": 5}


# ---------------------------------------------------------- 12. parser contract


@pytest.mark.parametrize("args", [
    (),
    ("--set", "auth_resume_max=24", "--unset", "auth_resume_max"),
    ("--set", "auth_resume_max"),
])
def test_b12_parser_errors_exit_2(tmp_path, args):
    P, O = _setup(tmp_path, {"auth_resume_max": 3})
    before = _snap(P, O)
    rc, out, err = _run(P, *args)
    assert rc == 2, (out, err)
    assert "invalid choice" not in err, err
    assert "overlay" in err, err
    assert _snap(P, O) == before


def test_b12_help_lists_flags():
    rc, out, _ = _capture(lambda: foundry.main(["overlay", "--help"]))
    assert rc == 0
    for flag in ("--config", "--set", "--unset"):
        assert flag in out, out


def test_b12_cli_subprocess_works_with_broken_overlay(tmp_path):
    """Dispatched before the top-level load_config: a broken O yields the verb's own exit 2."""
    P, O = _setup(tmp_path, raw=BAD_JSON)
    before = _snap(P, O)
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "overlay", "--config", str(P),
         "--unset", "auth_resume_max"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "not valid JSON" in proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert _snap(P, O) == before


def test_b12_cli_subprocess_set_end_to_end(tmp_path):
    P, O = _setup(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "overlay", "--config", str(P),
         "--set", "push_enabled=false"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json.loads(O.read_text()) == {"push_enabled": False}
    assert proc.stdout.splitlines() == [f"overlay: push_enabled (unset) -> false ({O})"]


# ------------------------------------------------------ 13. indexed and dormant


def test_b13_census_and_readme_index():
    src = (_ROOT / "foundry.py").read_text()
    verbs = foundry.foundry_cli_verbs(src)
    assert "overlay" in verbs
    assert len(set(verbs)) == 66
    readme = (_ROOT / "README.md").read_text()
    audit = foundry.readme_verb_index_gaps(readme, verbs)
    assert audit.ok is True and tuple(audit.missing_verbs) == (), audit
    entry = [ln for ln in readme.splitlines() if ln.startswith("# 67.")]
    assert entry and "overlay" in entry[0], entry


def _top_level_defs(src: str) -> dict:
    tree = ast.parse(src)
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def test_b13_overlay_cli_referenced_only_from_main():
    src = (_ROOT / "foundry.py").read_text()
    defs = _top_level_defs(src)
    assert "overlay_cli" in defs
    referrers = set()
    for name, node in defs.items():
        if name == "overlay_cli":
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == "overlay_cli":
                referrers.add(name)
    assert referrers == {"main"}, referrers
    assert "overlay_cli" not in (_ROOT / "dispatcher.py").read_text()


# sha256 of each function's source segment at the pre-iteration HEAD (0034e68).
# iter 505 re-pinned merge_local_overlay: it now drops overlay push escalations
# (load-side half of iter 504's guard); load_config's golden is unchanged.
READ_SIDE_GOLDENS = {
    "load_config": "5eccbde05ea36bb7f86ba3085437bb6b2af98a237aa4cd927d96e3bc8f40f241",
    "merge_local_overlay": "6eb3b6453d42a22ae5efcd963ca1c3a741f94492a10afa74794f92f66548e75f",
}


def test_b13_read_side_bodies_unchanged():
    src = (_ROOT / "foundry.py").read_text()
    defs = _top_level_defs(src)
    for name, golden in READ_SIDE_GOLDENS.items():
        seg = ast.get_source_segment(src, defs[name])
        assert hashlib.sha256(seg.encode()).hexdigest() == golden, name
