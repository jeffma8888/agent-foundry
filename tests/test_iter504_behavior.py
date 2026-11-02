"""Iteration 504 -- BLACK-BOX behavior tests: a gitignored `config.local.json` may not
escalate push.  `overlay --set` refuses an edit that turns push ON or changes `repo` /
`allowed_push_repo`, and `lint-config` reports an existing escalating overlay as an
error naming the overlay file.

Spec under test: products/_platform/state/iter-504/pm.md, Expected Behaviors 1-12.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-504
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

GUARDED = ("push_enabled", "repo", "allowed_push_repo")


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


def _snap(O):
    return O.read_bytes() if O.exists() else None


def _cli(*args):
    proc = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), *args],
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def _overlay(P, *args):
    return _cli("overlay", "--config", str(P), *args)


def _lint(P, *extra):
    return _cli("lint-config", "--config", str(P), *extra)


def _assert_shape(O):
    text = O.read_text()
    obj = json.loads(text)
    assert text == json.dumps(obj, indent=2) + "\n", text
    return obj


# ------------------------------------------------------- 1. predicate, fixed order


TRACKED = {"push_enabled": False, "repo": "/a", "allowed_push_repo": "a"}


def test_b1_all_three_in_fixed_order():
    got = foundry.overlay_push_escalations(
        TRACKED, {"push_enabled": True, "repo": "/b", "allowed_push_repo": "b"})
    assert isinstance(got, tuple)
    assert got == ("push_enabled", "repo", "allowed_push_repo")


def test_b1_order_independent_of_overlay_key_order():
    got = foundry.overlay_push_escalations(
        TRACKED, {"allowed_push_repo": "b", "repo": "/b", "push_enabled": True})
    assert got == ("push_enabled", "repo", "allowed_push_repo")


def test_b1_unguarded_keys_never_escalate():
    got = foundry.overlay_push_escalations(
        TRACKED, {"auth_resume_max": 24, "branch": "x", "name": "n", "work_root": "/w"})
    assert got == ()


# ------------------------------------------------------- 2. push_enabled direction


@pytest.mark.parametrize("tracked,expected", [
    ({"push_enabled": False}, ("push_enabled",)),
    ({"push_enabled": True}, ()),
    ({}, ()),
])
def test_b2_push_enabled_true_overlay(tracked, expected):
    assert foundry.overlay_push_escalations(tracked, {"push_enabled": True}) == expected


@pytest.mark.parametrize("tracked", [{"push_enabled": True}, {"push_enabled": False}, {}])
def test_b2_push_enabled_false_overlay_never_escalates(tracked):
    assert foundry.overlay_push_escalations(tracked, {"push_enabled": False}) == ()


# ------------------------------------------------------- 3. same value


def test_b3_same_value_is_not_escalation():
    assert foundry.overlay_push_escalations(
        TRACKED, {"repo": "/a", "allowed_push_repo": "a"}) == ()
    assert foundry.overlay_push_escalations(
        TRACKED, {"repo": "/a", "allowed_push_repo": "a", "push_enabled": False}) == ()
    # one differing, one equal: only the differing one is reported
    assert foundry.overlay_push_escalations(
        TRACKED, {"repo": "/a", "allowed_push_repo": "zz"}) == ("allowed_push_repo",)


# ------------------------------------------------------- 4. totality


NON_DICTS = [None, [], ["repo"], "repo", "", 0]


@pytest.mark.parametrize("tracked", NON_DICTS + [{}, TRACKED])
@pytest.mark.parametrize("overlay", NON_DICTS + [{}])
def test_b4_non_dict_or_empty_overlay_returns_empty(tracked, overlay):
    assert foundry.overlay_push_escalations(tracked, overlay) == ()


def test_b4_non_dict_tracked_treated_as_empty():
    assert foundry.overlay_push_escalations(None, {"repo": "/x"}) == ("repo",)
    assert foundry.overlay_push_escalations(None, {"push_enabled": True}) == ()
    assert foundry.overlay_push_escalations("str", {"allowed_push_repo": "y"}) == (
        "allowed_push_repo",)
    assert foundry.overlay_push_escalations([1], {"push_enabled": True}) == ()


def test_b4_hostile_values_do_not_raise():
    class Hostile:
        def __eq__(self, other):
            raise RuntimeError("eq")

        def __ne__(self, other):
            raise RuntimeError("ne")

        def __bool__(self):
            raise RuntimeError("bool")

        __hash__ = object.__hash__

    got = foundry.overlay_push_escalations(
        {"repo": Hostile(), "push_enabled": Hostile()},
        {"repo": Hostile(), "push_enabled": Hostile(), "allowed_push_repo": Hostile()})
    assert isinstance(got, tuple)
    assert set(got) <= set(GUARDED)


# ------------------------------------------------------- 5. writer refuses push enable


@pytest.mark.parametrize("initial", [None, {"auth_resume_max": 24}])
def test_b5_refuses_push_enable(tmp_path, initial):
    P, O = _setup(tmp_path, push_enabled=False, content=initial)
    before = _snap(O)
    rc, out, err = _overlay(P, "--set", "push_enabled=true")
    assert rc == 1, (out, err)
    lines = out.splitlines()
    assert len(lines) == 1, out
    assert lines[0].startswith("overlay: refused:"), lines
    assert "push_enabled" in lines[0] and str(P) in lines[0], lines
    assert "invalid choice" not in out + err
    assert "Traceback" not in err, err
    assert _snap(O) == before
    if initial is None:
        assert not O.exists()


# ------------------------------------------------------- 6. writer refuses target change


@pytest.mark.parametrize("initial", [None, {"auth_resume_max": 24}])
@pytest.mark.parametrize("field", ["repo", "allowed_push_repo"])
def test_b6_refuses_push_target_change(tmp_path, field, initial):
    P, O = _setup(tmp_path, push_enabled=False, content=initial)
    other = tmp_path / "other_repo"
    other.mkdir()
    value = str(other) if field == "repo" else "other"
    before = _snap(O)
    rc, out, err = _overlay(P, "--set", f"{field}={value}")
    assert rc == 1, (out, err)
    lines = out.splitlines()
    assert len(lines) == 1, out
    assert lines[0].startswith("overlay: refused:"), lines
    assert field in lines[0], lines
    assert "Traceback" not in err, err
    assert _snap(O) == before


def test_b6_same_allowed_push_repo_allowed(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False, allowed_push_repo="none")
    rc, out, err = _overlay(P, "--set", "allowed_push_repo=none")
    assert rc == 0, (out, err)
    assert _assert_shape(O) == {"allowed_push_repo": "none"}


# ------------------------------------------------------- 7. safe direction / other keys


@pytest.mark.parametrize("tracked_push,arg,expected", [
    (True, "push_enabled=false", {"push_enabled": False}),
    (True, "push_enabled=true", {"push_enabled": True}),
    (False, "push_enabled=false", {"push_enabled": False}),
    (False, "branch=dev", {"branch": "dev"}),
    (False, "auth_resume_max=24", {"auth_resume_max": 24}),
])
def test_b7_allowed_edits(tmp_path, tracked_push, arg, expected):
    P, O = _setup(tmp_path, push_enabled=tracked_push)
    rc, out, err = _overlay(P, "--set", arg)
    assert rc == 0, (out, err)
    assert _assert_shape(O) == expected
    key = arg.split("=", 1)[0]
    assert out.splitlines() and out.splitlines()[0].startswith(f"overlay: {key} "), out
    assert "refused" not in out


@pytest.mark.parametrize("tracked_push", [True, False])
def test_b7_unset_push_enabled_always_allowed(tmp_path, tracked_push):
    P, O = _setup(tmp_path, push_enabled=tracked_push,
                  content={"auth_resume_max": 24, "push_enabled": True})
    rc, out, err = _overlay(P, "--unset", "push_enabled")
    assert rc == 0, (out, err)
    assert _assert_shape(O) == {"auth_resume_max": 24}


# ------------------------------------------------------- 8. type check first


def test_b8_type_check_precedes_escalation(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    rc, out, err = _overlay(P, "--set", "push_enabled=yes")
    assert rc == 1, (out, err)
    assert "wrong value type" in out + err, (out, err)
    assert not O.exists()
    # the message is exactly the one given where no escalation is possible (tracked true)
    _setup(tmp_path, push_enabled=True)
    assert _overlay(P, "--set", "push_enabled=yes") == (rc, out, err)
    assert not O.exists()


# ------------------------------------------------------- 9. lint flags escalation


def test_b9_lint_text_flags_push_enable(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    rc0, out0, err0 = _lint(P)
    assert rc0 == 0, (out0, err0)  # anti-vacuity: clean without O
    O.write_text(json.dumps({"push_enabled": True}) + "\n")
    rc, out, err = _lint(P)
    assert rc == 1, (out, err)
    assert "push_enabled" in out and "config.local.json" in out, out


def test_b9_lint_json_last_finding(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False, content={"push_enabled": True})
    rc, out, err = _lint(P, "--json")
    assert rc == 1, (out, err)
    doc = json.loads(out)
    last = doc["findings"][-1]
    assert last["field"] == "push_enabled" and last["level"] == "error", last
    assert "config.local.json" in last["detail"], last


def test_b9_lint_json_two_findings_in_order(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False,
                  content={"push_enabled": True, "allowed_push_repo": "other"})
    rc, out, err = _lint(P, "--json")
    assert rc == 1, (out, err)
    findings = json.loads(out)["findings"]
    assert len(findings) >= 2, findings
    assert [f["field"] for f in findings[-2:]] == ["push_enabled", "allowed_push_repo"]
    assert all(f["level"] == "error" for f in findings[-2:]), findings
    assert all("config.local.json" in f["detail"] for f in findings[-2:]), findings


# ------------------------------------------------------- 10. lint unchanged otherwise


@pytest.mark.parametrize("tracked_push,content", [
    (False, {"auth_resume_max": 24}),
    (True, {"push_enabled": False}),
    (True, {"push_enabled": True}),
])
@pytest.mark.parametrize("extra", [(), ("--json",)])
def test_b10_lint_unchanged_without_escalation(tmp_path, tracked_push, content, extra):
    P, O = _setup(tmp_path, push_enabled=tracked_push, content=content)
    with_o = _lint(P, *extra)[:2]
    O.unlink()
    without_o = _lint(P, *extra)[:2]
    assert with_o == without_o
    assert without_o[0] == 0, without_o  # anti-vacuity: a clean fixture


# ------------------------------------------------------- 11. overlay file exempt


def test_b11_overlay_path_passed_directly_is_exempt(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False)
    full = json.loads(P.read_text())
    full["push_enabled"] = True
    O.write_text(json.dumps(full, indent=2) + "\n")
    rc, out, err = _lint(O, "--json")
    findings = json.loads(out)["findings"]
    assert not [f for f in findings
                if f["field"] in GUARDED and f["level"] == "error"], findings
    # same document linted from an unrelated name with no sibling overlay
    alt_dir = tmp_path / "alt"
    alt_dir.mkdir()
    alt = alt_dir / "config.json"
    alt.write_text(O.read_text())
    rc_alt, out_alt, _ = _lint(alt, "--json")
    assert rc == rc_alt, (out, out_alt)
    assert findings == json.loads(out_alt)["findings"]


# ------------------------------------------------------- 12. live path untouched


def test_b12_escalating_overlay_still_loads(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False,
                  content={"push_enabled": True, "auth_resume_max": 24})
    cfg = foundry.load_config(P)
    # iter 505 re-pin: the load still succeeds, but the escalation is dropped.
    assert cfg.push_enabled is False
    assert cfg.auth_resume_max == 24


def test_b12_escalating_overlay_loads_in_subprocess(tmp_path):
    P, O = _setup(tmp_path, push_enabled=False, content={"push_enabled": True})
    code = ("import sys, foundry; cfg = foundry.load_config(sys.argv[1]); "
            "print(cfg.push_enabled is True)")
    proc = subprocess.run([sys.executable, "-c", code, str(P)], cwd=str(_ROOT),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    # iter 505 re-pin: the escalation is ignored at load time.
    assert proc.stdout.strip() == "False"


def test_b12_import_probe():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
