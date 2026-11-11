"""Iteration 523 -- BLACK-BOX behavior tests: `preflight --config`, `stop --config` and
`resume --config` print ONE `foundry <verb>: cannot read config <path>: <ExcType>: <msg>`
stderr line (stdout empty, rc 1) instead of a raw traceback when the config they must
read is missing, malformed or rejected by `load_config`; every readable path is unchanged.

Spec under test: products/_platform/state/iter-523/pm.md, Expected Behaviors 1-12.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-523
PM spec, the product README / roadmap text, the conventions under `tests/`, and the
product's OWN observable behavior (`foundry.main([...])` / the CLI run as a subprocess,
and its public names). The implementation source, the engineer/reviewer notes,
IMPLEMENTATION.patch and any `git diff` were NOT read.

FIXTURE SAFETY: every config lives in tmp_path; `foundry.FOUNDRY` is monkeypatched to an
empty tmp dir wherever a STOP file could be touched; no gitignored state is read, and no
absolute machine path appears in this file. Behavior 12's "dispatcher.py / launch.sh
unchanged" half is checked by hand (git diff exit code cited in tester.md), never here.
"""
from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402


# ---------------------------------------------------------------- helpers


@pytest.fixture
def iso_foundry(tmp_path, monkeypatch):
    """Point foundry.FOUNDRY at an empty tmp dir so no real company STOP is visible."""
    g = tmp_path / "company"
    g.mkdir()
    monkeypatch.setattr(foundry, "FOUNDRY", g)
    return g


def _product_data(tmp_path: pathlib.Path) -> dict:
    work_root = tmp_path / "work"
    work_root.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    (tmp_path / "VISION.md").write_text("vision\n")
    (tmp_path / "ROADMAP.md").write_text("roadmap\n")
    return {
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


def _product_config(tmp_path: pathlib.Path, **override) -> pathlib.Path:
    data = _product_data(tmp_path)
    for k, v in override.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    pdir = tmp_path / "products" / "x"
    pdir.mkdir(parents=True, exist_ok=True)
    p = pdir / "config.json"
    p.write_text(json.dumps(data, indent=2) + "\n")
    return p


def _bad_json(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "bad.json"
    p.write_text("{bad")
    return p


def _missing(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "nope" / "config.json"


def _roster(tmp_path: pathlib.Path, item_config: str, enabled=True, name="roster.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"work_items": [
        {"name": "x", "config": item_config, "priority": 0, "enabled": enabled},
    ]}))
    return p


def _main(capsys, argv):
    rc = foundry.main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _assert_one_line(rc, out, err, verb, path, exc_name=None):
    assert rc == 1, (rc, out, err)
    assert out == "", f"stdout must be empty, got {out!r}"
    assert "Traceback" not in err, err
    lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(lines) == 1, f"stderr must be exactly one line, got {lines!r}"
    prefix = f"foundry {verb}: cannot read config {path}: "
    assert lines[0].startswith(prefix), (lines[0], prefix)
    if exc_name is not None:
        assert lines[0].startswith(prefix + f"{exc_name}: "), lines[0]
    else:
        rest = lines[0][len(prefix):]
        exc = rest.split(":", 1)[0]
        assert exc and exc.isidentifier() and ": " in rest, lines[0]
    return lines[0]


def _stub_preflight_world(monkeypatch):
    monkeypatch.setattr(foundry, "run_doctor", lambda cfg: [
        foundry.Check("agent", True, "ok"), foundry.Check("uv", True, "ok")])
    monkeypatch.setattr(foundry, "running_dispatchers", lambda pattern="dispatcher.py": ())


def _stop_files(*roots):
    return sorted(str(p) for r in roots for p in r.rglob("STOP"))


# ---------------------------------------------------------------- B1-B3 preflight


@pytest.mark.parametrize("as_json", [False, True])
def test_b1_b3_preflight_missing(tmp_path, capsys, as_json):
    p = _missing(tmp_path)
    argv = ["preflight", "--config", str(p)] + (["--json"] if as_json else [])
    rc, out, err = _main(capsys, argv)
    _assert_one_line(rc, out, err, "preflight", p, "FileNotFoundError")


@pytest.mark.parametrize("as_json", [False, True])
def test_b2_b3_preflight_bad_json(tmp_path, capsys, as_json):
    p = _bad_json(tmp_path)
    argv = ["preflight", "--config", str(p)] + (["--json"] if as_json else [])
    rc, out, err = _main(capsys, argv)
    _assert_one_line(rc, out, err, "preflight", p, "JSONDecodeError")


def test_b1_cli_subprocess_no_traceback(tmp_path):
    p = _missing(tmp_path)
    proc = subprocess.run([sys.executable, str(_ROOT / "foundry.py"), "preflight",
                           "--config", str(p), "--json"],
                          capture_output=True, text=True, timeout=120)
    _assert_one_line(proc.returncode, proc.stdout, proc.stderr, "preflight", p,
                     "FileNotFoundError")


# ---------------------------------------------------------------- B4 roster -> missing item


def test_b4_roster_item_missing_direct(tmp_path, capsys):
    item = tmp_path / "gone" / "config.json"
    roster = _roster(tmp_path, str(item))
    rc, out, err = _main(capsys, ["preflight", "--config", str(roster)])
    line = _assert_one_line(rc, out, err, "preflight", item, "FileNotFoundError")
    assert str(roster) not in line


@pytest.mark.parametrize("as_json", [False, True])
def test_b4_roster_item_missing_via_foundry_token(tmp_path, capsys, monkeypatch, as_json):
    root = tmp_path / "froot"
    root.mkdir()
    monkeypatch.setattr(foundry, "FOUNDRY", root)
    roster = _roster(tmp_path, "{FOUNDRY}/products/ghost/config.json")
    argv = ["preflight", "--config", str(roster)] + (["--json"] if as_json else [])
    rc, out, err = _main(capsys, argv)
    resolved = str(root / "products" / "ghost" / "config.json")
    line = _assert_one_line(rc, out, err, "preflight", resolved, "FileNotFoundError")
    assert "{FOUNDRY}" not in line
    assert str(roster) not in line


# ---------------------------------------------------------------- B5 roster -> rejected item


def test_b5_roster_item_unknown_key(tmp_path, capsys):
    item = _product_config(tmp_path, auth_resum_max=3)
    roster = _roster(tmp_path, str(item))
    rc, out, err = _main(capsys, ["preflight", "--config", str(roster)])
    line = _assert_one_line(rc, out, err, "preflight", item)
    assert str(roster) not in line


def test_b5_roster_item_missing_required_field(tmp_path, capsys):
    item = _product_config(tmp_path, allowed_push_repo=None)
    roster = _roster(tmp_path, str(item))
    rc, out, err = _main(capsys, ["preflight", "--config", str(roster), "--json"])
    line = _assert_one_line(rc, out, err, "preflight", item)
    assert str(roster) not in line


def test_b5_product_config_rejected_directly(tmp_path, capsys):
    p = _product_config(tmp_path, auth_resum_max=3)
    rc, out, err = _main(capsys, ["preflight", "--config", str(p)])
    _assert_one_line(rc, out, err, "preflight", p)


# ---------------------------------------------------------------- B6 try scope


class _GateCrash(ValueError):
    pass


def test_b6_preflight_cli_crash_propagates_product(tmp_path, capsys, monkeypatch):
    p = _product_config(tmp_path)

    def boom(*a, **k):
        raise _GateCrash("gate exploded")
    monkeypatch.setattr(foundry, "preflight_cli", boom)
    with pytest.raises(_GateCrash, match="gate exploded"):
        foundry.main(["preflight", "--config", str(p)])
    assert "cannot read config" not in capsys.readouterr().err


def test_b6_preflight_cli_crash_propagates_roster(tmp_path, capsys, monkeypatch):
    p = _product_config(tmp_path)
    roster = _roster(tmp_path, str(p))

    def boom(*a, **k):
        raise _GateCrash("gate exploded")
    monkeypatch.setattr(foundry, "preflight_cli", boom)
    with pytest.raises(_GateCrash):
        foundry._preflight_dispatch(str(roster))
    with pytest.raises(_GateCrash):
        foundry.main(["preflight", "--config", str(roster), "--json"])
    assert "cannot read config" not in capsys.readouterr().err


# ---------------------------------------------------------------- B7 readable unchanged


@pytest.mark.parametrize("as_json", [False, True])
def test_b7_product_and_roster_same_output(tmp_path, capsys, monkeypatch, as_json):
    _stub_preflight_world(monkeypatch)
    p = _product_config(tmp_path)
    roster = _roster(tmp_path, str(p))
    extra = ["--json"] if as_json else []
    rc1, out1, err1 = _main(capsys, ["preflight", "--config", str(p)] + extra)
    rc2, out2, err2 = _main(capsys, ["preflight", "--config", str(roster)] + extra)
    assert "cannot read config" not in err1 + err2
    assert rc1 == rc2 == 0, (rc1, rc2, out1, out2)
    assert out1 == out2 and out1.strip()
    if as_json:
        json.loads(out1)


def test_b7_no_enabled_item_still_nogo(tmp_path, capsys, monkeypatch):
    _stub_preflight_world(monkeypatch)
    roster = _roster(tmp_path, str(_missing(tmp_path)), enabled=False)
    rc, out, err = _main(capsys, ["preflight", "--config", str(roster)])
    assert rc == 1
    assert "cannot read config" not in err
    assert "NO-GO" in out.upper()
    rc, out, err = _main(capsys, ["preflight", "--config", str(roster), "--json"])
    assert rc == 1 and "cannot read config" not in err
    json.loads(out)


def test_b7_disabled_bad_item_skipped_for_enabled_good(tmp_path, capsys, monkeypatch):
    _stub_preflight_world(monkeypatch)
    good = _product_config(tmp_path)
    roster = tmp_path / "mixed.json"
    roster.write_text(json.dumps({"work_items": [
        {"name": "a", "config": str(_missing(tmp_path)), "priority": 0, "enabled": False},
        {"name": "b", "config": str(good), "priority": 1, "enabled": True},
    ]}))
    rc, out, err = _main(capsys, ["preflight", "--config", str(roster)])
    assert rc == 0 and "cannot read config" not in err, (rc, out, err)


# ---------------------------------------------------------------- B8 stop


@pytest.mark.parametrize("kind", ["missing", "bad"])
@pytest.mark.parametrize("as_json", [False, True])
def test_b8_stop_unreadable(tmp_path, capsys, iso_foundry, kind, as_json):
    p = _missing(tmp_path) if kind == "missing" else _bad_json(tmp_path)
    argv = ["stop", "--config", str(p), "--reason", "r"] + (["--json"] if as_json else [])
    rc, out, err = _main(capsys, argv)
    exc = "FileNotFoundError" if kind == "missing" else "JSONDecodeError"
    _assert_one_line(rc, out, err, "stop", p, exc)
    assert _stop_files(tmp_path, iso_foundry) == []


def test_b8_stop_rejected_config(tmp_path, capsys, iso_foundry):
    p = _product_config(tmp_path, auth_resum_max=3)
    rc, out, err = _main(capsys, ["stop", "--config", str(p), "--reason", "r"])
    _assert_one_line(rc, out, err, "stop", p)
    assert _stop_files(tmp_path, iso_foundry) == []


# ---------------------------------------------------------------- B9 resume


@pytest.mark.parametrize("kind", ["missing", "bad"])
@pytest.mark.parametrize("as_json", [False, True])
def test_b9_resume_unreadable(tmp_path, capsys, iso_foundry, kind, as_json):
    (iso_foundry / "STOP").write_text("company halt\n")
    p = _missing(tmp_path) if kind == "missing" else _bad_json(tmp_path)
    argv = ["resume", "--config", str(p)] + (["--json"] if as_json else [])
    rc, out, err = _main(capsys, argv)
    exc = "FileNotFoundError" if kind == "missing" else "JSONDecodeError"
    _assert_one_line(rc, out, err, "resume", p, exc)
    assert (iso_foundry / "STOP").read_text() == "company halt\n"


# ---------------------------------------------------------------- B7/B8/B9 good arms


def test_good_stop_then_resume_config(tmp_path, capsys, iso_foundry):
    p = _product_config(tmp_path)
    stop = tmp_path / "work" / "STOP"
    rc, out, err = _main(capsys, ["stop", "--config", str(p), "--reason", "maintenance"])
    assert rc == 0 and "cannot read config" not in err, (rc, out, err)
    assert stop.exists()
    rc, out, err = _main(capsys, ["resume", "--config", str(p), "--json"])
    assert rc == 0 and "cannot read config" not in err, (rc, out, err)
    assert json.loads(out)["action"] == "LIFTED"
    assert not stop.exists()


# ---------------------------------------------------------------- B10 --global / argparse


def test_b10_global_stop_resume(tmp_path, capsys, iso_foundry):
    rc, out, err = _main(capsys, ["stop", "--global", "--reason", "halt all"])
    assert rc == 0 and "cannot read config" not in err, (rc, out, err)
    assert (iso_foundry / "STOP").exists()
    rc, out, err = _main(capsys, ["resume", "--global", "--json"])
    assert rc == 0 and "cannot read config" not in err, (rc, out, err)
    assert not (iso_foundry / "STOP").exists()


def test_b10_argparse_exit_2_unchanged(tmp_path, capsys, iso_foundry):
    for argv in (["resume"], ["stop", "--reason", "r"],
                 ["resume", "--config", str(_missing(tmp_path)), "--global"]):
        with pytest.raises(SystemExit) as ei:
            foundry.main(argv)
        assert ei.value.code == 2, argv
    capsys.readouterr()


# ---------------------------------------------------------------- B11 shared line


def test_b11_status_line_unchanged(tmp_path, capsys):
    p = _missing(tmp_path)
    rc, out, err = _main(capsys, ["status", "--config", str(p)])
    line = _assert_one_line(rc, out, err, "status", p, "FileNotFoundError")
    assert line.startswith(f"foundry status: cannot read config {p}: FileNotFoundError: ")


def test_b11_same_format_across_verbs(tmp_path, capsys, iso_foundry):
    p = _bad_json(tmp_path)
    tails = set()
    for verb, extra in (("status", []), ("preflight", []), ("stop", ["--reason", "r"]),
                        ("resume", [])):
        rc, out, err = _main(capsys, [verb, "--config", str(p)] + extra)
        line = _assert_one_line(rc, out, err, verb, p, "JSONDecodeError")
        tails.add(line[len(f"foundry {verb}: "):])
    assert len(tails) == 1, tails


# ---------------------------------------------------------------- B12 load_config raises


def test_b12_load_config_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        foundry.load_config(str(_missing(tmp_path)))
    with pytest.raises(ValueError):
        foundry.load_config(str(_bad_json(tmp_path)))


def test_b12_import_probe():
    proc = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
