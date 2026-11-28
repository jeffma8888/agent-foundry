"""Iteration 559 -- BLACK-BOX behavior tests: `live_lag_status` reads its ship
truth from the brain's own checkout (`foundry.FOUNDRY`), not from `cfg.repo`,
so a product repo's own `(foundry iter N)` commits never raise a
"restart the dispatcher" WARN.

ISOLATION CONTRACT (honored): written from the iter-559 PM spec's Expected
Behaviors 1-7, the fixture conventions under tests/ (test_iter130,
test_iter519) and the product's observable behaviour only. The
implementation source, engineer/reviewer notes and `git diff` were NOT read.

FRESH-CLONE SAFE: every git repo and dispatcher log is built in tmp_path;
`FOUNDRY` is redirected only via monkeypatch.setattr; nothing asserts on the
ambient (gitignored) dispatcher.out or on the real repo's history.
"""
from __future__ import annotations

import inspect
import os
import pathlib
import shutil
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

BANNER = "- `08-03 09:41:14` dispatcher up; teams=2 concurrency=1\n"
FUTURE = "2099-06-01T12:00:00"   # always after any year-less banner
PAST = "2001-01-01T12:00:00"     # always before it

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e.x",
                    "-c", "commit.gpgsign=false", *args],
                   check=True, capture_output=True, env=env, timeout=30)


def _repo(path, commits):
    """commits: iterable of (subject, iso-date)."""
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    for n, (subject, date) in enumerate(commits):
        (path / f"f{n}.txt").write_text(subject)
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", subject, date=date)
    return path


def _log(tmp_path, text=BANNER, name="dispatcher.out"):
    p = tmp_path / name
    p.write_text(text)
    return p


def _cfg(repo):
    return foundry.ProductConfig(name="demo", repo=str(repo), allowed_push_repo="demo")


def _product_repo(tmp_path):
    return _repo(tmp_path / "product", [
        ("feat: old thing (foundry iter 900)", PAST),
        ("feat: product a (foundry iter 901)", FUTURE),
        ("feat: product b (foundry iter 902)", FUTURE),
    ])


def _brain_quiet(tmp_path):
    return _repo(tmp_path / "brain", [
        ("feat: old brain (foundry iter 800)", PAST),
        ("docs: untagged future note", FUTURE),
    ])


def _brain_lagging(tmp_path, name="brain"):
    return _repo(tmp_path / name, [
        ("feat: old brain (foundry iter 800)", PAST),
        ("feat: brain a (foundry iter 903)", FUTURE),
        ("feat: brain b (foundry iter 904)", FUTURE),
    ])


def _empty_repo(tmp_path, name="empty"):
    return _repo(tmp_path / name, [("chore: nothing tagged", FUTURE)])


# ------------------------------------------------------------------ EB1

@needs_git
def test_eb1_product_only_ships_give_ok(monkeypatch, tmp_path):
    prod = _product_repo(tmp_path)
    monkeypatch.setattr(foundry, "FOUNDRY", _brain_quiet(tmp_path))
    log = _log(tmp_path)
    st = foundry.live_lag_status(_cfg(prod), log_path=log)
    assert st.verdict == "OK", st
    line = foundry.live_lag_line(_cfg(prod), log_path=log)
    assert line.startswith("live-lag: OK"), line
    assert "901" not in line and "902" not in line, line
    assert foundry.live_lag_verdict(line) == st.verdict


@needs_git
def test_eb1_product_ships_really_are_post_launch(tmp_path):
    """Fixture sanity: the product repo DOES hold post-launch ship commits, so
    EB1's OK is caused by reading the other repo, not by a dud fixture."""
    prod = _product_repo(tmp_path)
    iters = {i for i, _ in foundry.git_ship_commits(prod)}
    assert {901, 902} <= iters, iters
    launch = foundry.parse_brain_launch(BANNER, year=2026)
    assert launch is not None
    assert set(foundry.inert_iterations(launch, foundry.git_ship_commits(prod))) >= {901, 902}


# ------------------------------------------------------------------ EB2

@needs_git
def test_eb2_foundry_only_ships_give_warn(monkeypatch, tmp_path):
    prod = _empty_repo(tmp_path)
    monkeypatch.setattr(foundry, "FOUNDRY", _brain_lagging(tmp_path))
    log = _log(tmp_path)
    st = foundry.live_lag_status(_cfg(prod), log_path=log)
    assert st.verdict == "WARN", st
    assert tuple(st.inert) == (903, 904), st
    line = foundry.live_lag_line(_cfg(prod), log_path=log)
    assert line.startswith("live-lag: WARN"), line
    assert "903" in line and "904" in line, line
    assert "restart the dispatcher" in line, line
    assert foundry.live_lag_verdict(line) == st.verdict


# ------------------------------------------------------------------ EB3

class _Recorder:
    def __init__(self, ret=()):
        self.calls = []
        self.ret = list(ret)

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return list(self.ret)


def _seam_arg(call):
    a, k = call
    if a:
        return a[0]
    assert len(k) == 1, k
    return next(iter(k.values()))


def test_eb3_seam_called_once_with_foundry_not_cfg_repo(monkeypatch, tmp_path):
    rec = _Recorder()
    monkeypatch.setattr(foundry, "git_ship_commits", rec)
    brain = tmp_path / "brain-checkout"
    monkeypatch.setattr(foundry, "FOUNDRY", brain)
    foundry.live_lag_status(_cfg(tmp_path / "product-repo"), log_path=_log(tmp_path))
    assert len(rec.calls) == 1, rec.calls
    arg = _seam_arg(rec.calls[0])
    assert pathlib.Path(arg) == brain, rec.calls
    assert pathlib.Path(arg) != tmp_path / "product-repo"


def test_eb3_foundry_read_at_call_time(monkeypatch, tmp_path):
    rec = _Recorder()
    monkeypatch.setattr(foundry, "git_ship_commits", rec)
    log = _log(tmp_path)
    cfg = _cfg(tmp_path / "product-repo")
    for name in ("first", "second"):
        monkeypatch.setattr(foundry, "FOUNDRY", tmp_path / name)
        foundry.live_lag_status(cfg, log_path=log)
    assert [pathlib.Path(_seam_arg(c)) for c in rec.calls] == [tmp_path / "first",
                                                               tmp_path / "second"]


def test_eb3_unpatched_call_targets_the_real_foundry_global(monkeypatch, tmp_path):
    rec = _Recorder()
    monkeypatch.setattr(foundry, "git_ship_commits", rec)
    foundry.live_lag_status(_cfg(tmp_path / "elsewhere"), log_path=_log(tmp_path))
    assert [pathlib.Path(_seam_arg(c)) for c in rec.calls] == [pathlib.Path(foundry.FOUNDRY)]


# ------------------------------------------------------------------ EB4

@needs_git
def test_eb4_same_repo_output_matches_direct_scripting(monkeypatch, tmp_path):
    repo = _brain_lagging(tmp_path, name="shared")
    log = _log(tmp_path)
    cfg = _cfg(repo)
    monkeypatch.setattr(foundry, "FOUNDRY", repo)
    real_line = foundry.live_lag_line(cfg, log_path=log)
    real_status = foundry.live_lag_status(cfg, log_path=log)
    pairs = foundry.git_ship_commits(repo)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: list(pairs))
    scripted_line = foundry.live_lag_line(cfg, log_path=log)
    assert real_line == scripted_line
    assert real_status == foundry.live_lag_status(cfg, log_path=log)
    assert real_line == (
        "live-lag: WARN -- 2 iteration(s) shipped but NOT LIVE in the running brain "
        "(committed after launch 08-03 09:41:14): 903, 904 -- restart the dispatcher "
        "to activate")


# ------------------------------------------------------------------ EB5

@needs_git
def test_eb5_cfg_without_repo_attribute_still_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "FOUNDRY", _brain_lagging(tmp_path))
    cfg = types.SimpleNamespace(name="x")
    log = _log(tmp_path)
    st = foundry.live_lag_status(cfg, log_path=log)
    assert st.verdict == "WARN", st
    assert tuple(st.inert) == (903, 904)
    line = foundry.live_lag_line(cfg, log_path=log)
    assert foundry.live_lag_verdict(line) == "WARN", line


def test_eb5_cfg_without_repo_attribute_scripted(monkeypatch, tmp_path):
    rec = _Recorder(ret=[(905, 4070908800.0)])
    monkeypatch.setattr(foundry, "git_ship_commits", rec)
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path / "brain")
    st = foundry.live_lag_status(types.SimpleNamespace(name="x"), log_path=_log(tmp_path))
    assert st.verdict == "WARN" and tuple(st.inert) == (905,), st
    assert [pathlib.Path(_seam_arg(c)) for c in rec.calls] == [tmp_path / "brain"]


# ------------------------------------------------------------------ EB6

def _boom(*a, **k):
    raise RuntimeError("x")


def test_eb6_missing_log_is_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: [])
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    cfg = _cfg(tmp_path)
    log = tmp_path / "missing.out"
    st = foundry.live_lag_status(cfg, log_path=log)
    assert st.verdict == "UNKNOWN"
    assert st.unknown_reason == ("brain launch instant unknown (no datable `dispatcher up` "
                                 "banner in missing.out); cannot compare shipped against live")
    assert foundry.live_lag_verdict(foundry.live_lag_line(cfg, log_path=log)) == st.verdict


def test_eb6_bannerless_log_is_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: [(906, 4070908800.0)])
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    cfg = _cfg(tmp_path)
    log = _log(tmp_path, "hello\n", name="nb.out")
    st = foundry.live_lag_status(cfg, log_path=log)
    assert st.verdict == "UNKNOWN"
    assert st.unknown_reason == ("brain launch instant unknown (no datable `dispatcher up` "
                                 "banner in nb.out); cannot compare shipped against live")
    assert foundry.live_lag_verdict(foundry.live_lag_line(cfg, log_path=log)) == st.verdict


def test_eb6_raising_seam_is_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(foundry, "git_ship_commits", _boom)
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    cfg = _cfg(tmp_path / "product")
    log = _log(tmp_path)
    st = foundry.live_lag_status(cfg, log_path=log)
    assert st.verdict == "UNKNOWN"
    assert st.unknown_reason == "live-lag report unavailable (RuntimeError('x'))"
    line = foundry.live_lag_line(cfg, log_path=log)
    assert line == "live-lag: UNKNOWN -- live-lag report unavailable (RuntimeError('x'))"
    assert foundry.live_lag_verdict(line) == st.verdict


@needs_git
def test_eb6_foundry_not_a_git_repo_never_warns(monkeypatch, tmp_path):
    """A brain checkout git cannot read must never produce WARN from the
    product repo's commits (it may be OK or UNKNOWN, never a false WARN)."""
    prod = _product_repo(tmp_path)
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    monkeypatch.setattr(foundry, "FOUNDRY", plain)
    st = foundry.live_lag_status(_cfg(prod), log_path=_log(tmp_path))
    assert st.verdict in ("OK", "UNKNOWN"), st
    assert 901 not in st.inert and 902 not in st.inert


# ------------------------------------------------------------------ EB7 / AC

def test_eb7_untouched_helpers_still_public_and_callable():
    for name in ("git_ship_commits", "inert_iterations", "parse_brain_launch",
                 "summarize_live_lag", "live_lag_line", "live_lag_status"):
        assert callable(getattr(foundry, name)), name
    assert list(inspect.signature(foundry.live_lag_status).parameters) == ["cfg", "log_path"]
    assert list(inspect.signature(foundry.live_lag_line).parameters) == ["cfg", "log_path"]


def test_ac_docstring_names_the_brain_checkout():
    doc = foundry.live_lag_status.__doc__ or ""
    assert "FOUNDRY" in doc, doc
    assert "no usable `repo`" not in doc, doc


def test_ac_readme_live_lag_clause_mentions_foundry_checkout():
    text = (_ROOT / "README.md").read_text()
    lines = [ln for ln in text.splitlines() if "live-lag" in ln.lower()]
    assert lines, "README has no live-lag text"
    assert any("checkout" in ln.lower() and "product repo" in ln.lower() for ln in lines), \
        "README live-lag text does not say ship commits come from the foundry checkout"


def test_ac_imports_clean():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
