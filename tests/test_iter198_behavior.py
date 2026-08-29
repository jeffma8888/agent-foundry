"""Iteration 198 -- BLACK-BOX behavior tests: `foundry preship` discloses its own scope --
the sha the throwaway clone was verified at, and a one-line, content-free description of the
source worktree's uncommitted divergence -- as INERT diagnostics that can never move a verdict.

Spec under test: products/_platform/state/iter-198/pm.md, Expected Behaviors 1-16.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-198 PM spec, the conventions already
present under `tests/` (the seam-scripting harness of tests/test_iter156_behavior.py and the
compiled-bytecode introspection of tests/test_iter115_behavior.py), and the product's OWN
observable surface -- importing the public names, reading their signatures, scripting the
documented module seams, calling the CLI and reading TRACKED text files at runtime.  The
implementation TEXT of `foundry.py` was NOT read, nor were `engineer.md`, `fix_review.md`,
`reviewer.md` or any `git diff`.

Every behavior test here is OFFLINE: no real git, clone, subprocess or network call is made.
The single `subprocess` use is the spec's own `import foundry, dispatcher` importability
criterion.

  1. `worktree_scope_line("", "")` is EXACTLY the clean line, and so is any whitespace-only
     porcelain half for ANY shortstat half.
  2. A three-line porcelain plus a shortstat renders `<N> file(s) uncommitted vs HEAD; <stat>`.
  3. Non-empty porcelain with an empty/whitespace shortstat renders the count form ONLY --
     no trailing `;`, no empty tail.
  4. No repository CONTENT is ever echoed: the value is invariant under renaming every path.
  5. The echoed shortstat is bounded to its FIRST line and 120 characters.
  6. Total and never raises; a `PRESHIP:` token in the PORCELAIN half never reaches the value.
  7. `probe_worktree_scope` routes work through the bare-name `run_cmd` seam and issues exactly
     TWO repo-scoped commands (`status --porcelain`, then `diff HEAD --shortstat`).
  8. On a green scripted seam the probe returns exactly what `worktree_scope_line` returns.
  9. A FAILED porcelain command yields `None` -- never the clean line.
 10. A RAISING seam yields `None` and does not propagate.
 11. A failed shortstat alone still yields the behavior-3 count form.
 12. NO VERDICT MOVES: over all 16 clone/setup/test/sha combinations `verify_local_clone`'s
     verdict quintuple equals `preship_verdict`'s for the same five flags, and `verified_sha`
     equals the `expected_sha` it was handed.
 13. A DIAGNOSTIC FAILURE IS NEVER A VERDICT -- proved at the `verify_local_clone` level and,
     non-trivially, at the `preship_cli` level where the probe is actually wired.
 14. `render()` keeps detail-then-sentinel, exactly one `PRESHIP:` token, and prints `unknown`
     for a `None` diagnostic.
 15. `to_dict()` returns EXACTLY 8 JSON-native keys with the 6 existing values unchanged.
 16. BACK-COMPAT: 3- and 4-positional construction still work, new fields default to `None`,
     the record stays frozen, and `exit_code`/`sentinel` stay derived properties.

Also guarded, from the spec's ACCEPTANCE CRITERIA rather than its Expected Behaviors:
   A. Neither new VALUE can carry the token `PRESHIP:` (tests/test_iter156_behavior.py:558
      asserts `out.count("PRESHIP:") == 1` in `--json` mode, so a leaked token is a gate bug).
   B. `import foundry, dispatcher` still succeeds.
   C. BOTH roadmap records for iteration 198 are present in the SAME tree as the code.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import itertools
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

THIS_ITER = 198
SHA = "b" * 40
OTHER_SHA = "c" * 40
CLEAN = "clean -- no uncommitted changes vs HEAD"

WSL = "worktree_scope_line"
PROBE = "probe_worktree_scope"


def _wsl(porcelain: str, shortstat: str) -> str:
    return getattr(foundry, WSL)(porcelain, shortstat)


def _probe(repo):
    return getattr(foundry, PROBE)(repo)


# --------------------------------------------------------------------------
# helpers -- mirror tests/test_iter156_behavior.py's conventions
# --------------------------------------------------------------------------
def _cfg(tmp_path, **over):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    kw = dict(name="demo", repo=str(repo), allowed_push_repo="demo",
              work_root=str(work), test_cmd="uv run pytest", setup_cmd="uv sync")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _kind(argv):
    """Classify a scripted argv.  The two DIAGNOSTIC commands are classified FIRST so a
    probe command can never be mistaken for the suite step (the iter-156 harness would
    have called both of them "test")."""
    if "--porcelain" in argv:
        return "porcelain"
    if "--shortstat" in argv:
        return "shortstat"
    if "clone" in argv:
        return "clone"
    if "rev-parse" in argv:
        return "sha"
    if "sync" in argv:
        return "setup"
    return "test"


def _install(monkeypatch, *, clone_ok=True, setup_ok=True, test_ok=True, sha_ok=True,
             probe_raise=False, porcelain=" M a.py\n",
             shortstat=" 1 file changed, 2 insertions(+)"):
    """Script every documented seam by BARE module name; record the call order."""
    argvs: list[list[str]] = []
    flags = {"clone": clone_ok, "setup": setup_ok, "test": test_ok}

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        argvs.append(argv)
        kind = _kind(argv)
        if kind in ("porcelain", "shortstat"):
            if probe_raise:
                raise RuntimeError("probe-boom-xyz")
            return foundry.CmdResult(True, porcelain if kind == "porcelain" else shortstat)
        if kind == "sha":
            return foundry.CmdResult(True, (SHA if sha_ok else OTHER_SHA) + "\n")
        return foundry.CmdResult(bool(flags.get(kind, True)), f"{kind} output")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "cleanup_clone", lambda d: None)
    monkeypatch.setattr(foundry, "_monotonic", lambda: 0.0)
    return argvs


def _expected_verdict(c, s, t, sh):
    """The five flags a SHORT-CIRCUITING runner can have observed for this combo: a step
    that never ran cannot have succeeded."""
    return foundry.preship_verdict(clone_ok=c, setup_ok=(s and c), test_ok=(t and c and s),
                                   sha_ok=(sh and c and s and t), budget_exhausted=False)


def _quintuple(res):
    return (res.verified, res.incomplete, res.detail, res.exit_code, res.sentinel)


def _res(verified=True, incomplete=False, detail="d", secs=1.5, sha=None, scope=None):
    return foundry.PreshipResult(verified=verified, incomplete=incomplete, detail=detail,
                                 test_seconds=secs, verified_sha=sha, worktree_scope=scope)


def _cli(monkeypatch, tmp_path, *, as_json=False, probe_raise=False, probe_fail=False,
         result=None, porcelain=" M a.py\n?? b.txt\n"):
    """Drive `preship_cli` with every seam scripted -- no real git anywhere."""
    cfg = _cfg(tmp_path)

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        kind = _kind(argv)
        if kind == "porcelain":
            if probe_raise:
                raise RuntimeError("probe-boom-xyz")
            if probe_fail:
                return foundry.CmdResult(False, "fatal: not a git repository")
            return foundry.CmdResult(True, porcelain)
        if kind == "shortstat":
            return foundry.CmdResult(True, " 1 file changed, 2 insertions(+)")
        if kind == "sha":
            return foundry.CmdResult(True, SHA + "\n")
        return foundry.CmdResult(True, "")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "verify_local_clone",
                        lambda c, s, d: result if result is not None else _res())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.preship_cli(cfg, as_json=as_json)
    return rc, buf.getvalue()


# ==========================================================================
# Behavior 1 -- the clean line is exact, and whitespace-only porcelain is clean
# ==========================================================================
def test_b1_empty_porcelain_is_exactly_the_clean_line() -> None:
    assert _wsl("", "") == CLEAN


@pytest.mark.parametrize("porcelain", ["", " ", "\n", "\n \n", "\t\n  \n"])
@pytest.mark.parametrize("shortstat", ["", "  ", " 2 files changed, 15 insertions(+)"])
def test_b1_whitespace_only_porcelain_is_clean_for_any_shortstat(porcelain,
                                                                 shortstat) -> None:
    """An empty porcelain half means a clean tree WHATEVER the shortstat half says --
    the count is the authority, so no stat text may turn a clean tree dirty."""
    assert _wsl(porcelain, shortstat) == CLEAN


# ==========================================================================
# Behavior 2 -- count + stat form, verbatim
# ==========================================================================
def test_b2_count_and_shortstat_render_verbatim() -> None:
    got = _wsl(" M a.py\n?? b.txt\n M c.py\n",
               " 2 files changed, 15 insertions(+), 3 deletions(-)")
    assert got == ("3 file(s) uncommitted vs HEAD; "
                   "2 files changed, 15 insertions(+), 3 deletions(-)")


def test_b2_count_is_the_number_of_non_blank_porcelain_lines() -> None:
    """Blank lines and a missing trailing newline must not change the count."""
    assert _wsl(" M a\n\n?? b\n \n M c", " 1 file changed") == \
        "3 file(s) uncommitted vs HEAD; 1 file changed"


# ==========================================================================
# Behavior 3 -- count-only form has no trailing separator
# ==========================================================================
@pytest.mark.parametrize("shortstat", ["", " ", "   ", "\n", "\t \n"])
def test_b3_empty_shortstat_yields_the_bare_count_form(shortstat) -> None:
    got = _wsl(" M a.py\n", shortstat)
    assert got == "1 file(s) uncommitted vs HEAD"
    assert not got.endswith(";"), got
    assert "; " not in got, got


# ==========================================================================
# Behavior 4 -- repository CONTENT is never echoed
# ==========================================================================
def test_b4_no_path_from_the_porcelain_half_reaches_the_value() -> None:
    got = _wsl(" M secret/path.py\n?? other/file.txt\n", "")
    assert "secret/path.py" not in got, got
    assert "other/file.txt" not in got, got
    assert "secret" not in got and "other" not in got, got


def test_b4_value_is_invariant_under_renaming_every_path() -> None:
    """Built from the COUNT plus the stat text only -- so two porcelain halves with the
    same line count and different paths are indistinguishable in the report."""
    stat = " 2 files changed, 4 insertions(+)"
    a = _wsl(" M secret/path.py\n?? other/file.txt\n", stat)
    b = _wsl(" M x\n?? y\n", stat)
    c = _wsl("?? \u00e9\u00e0/\u4f60\u597d.py\n M zzz\n", stat)
    assert a == b == c, (a, b, c)


# ==========================================================================
# Behavior 5 -- the echoed shortstat is bounded
# ==========================================================================
def test_b5_only_the_first_shortstat_line_is_echoed() -> None:
    assert _wsl(" M a\n", "first line\nsecond line") == \
        "1 file(s) uncommitted vs HEAD; first line"
    assert "second line" not in _wsl(" M a\n", "first line\nsecond line")


def test_b5_a_pathological_shortstat_cannot_bloat_the_report() -> None:
    got = _wsl(" M a\n", "x" * 500)
    assert len(got) < 200, len(got)
    head = "1 file(s) uncommitted vs HEAD; "
    assert got.startswith(head), got
    assert len(got) - len(head) <= 120, len(got) - len(head)


# ==========================================================================
# Behavior 6 -- total, never raises, and never leaks the sentinel token
# ==========================================================================
_TOTALITY_INPUTS = [
    ("", ""),
    (" ", "  "),
    ("\n \n", "\t"),
    ("\n".join(" M f%d" % i for i in range(500)) + "\n", " 500 files changed"),
    ("PRESHIP: VERIFIED\n M a\n", " 1 file changed"),
    (" M a\n", "PRESHIP: BROKEN"),
    ("\x00", "\x00 1 file changed"),
    ("?? caf\u00e9/na\u00efve.py\n", " 1 file changed, \u00fcnicode(+)"),
    (" M a\n", ""),
    ("", "PRESHIP: INCOMPLETE"),
]


@pytest.mark.parametrize("porcelain,shortstat", _TOTALITY_INPUTS)
def test_b6_is_total_and_returns_a_str_for_every_input(porcelain, shortstat) -> None:
    got = _wsl(porcelain, shortstat)
    assert isinstance(got, str), type(got)
    assert got.strip(), repr(got)


_PORCELAIN_WITH_TOKEN = [(p, s) for p, s in _TOTALITY_INPUTS if "PRESHIP:" in p]


def test_b6_the_token_bearing_input_set_is_non_empty() -> None:
    """Guards the parametrization itself: a filter that silently matched nothing would
    make the next test vacuous rather than failing."""
    assert _PORCELAIN_WITH_TOKEN, _TOTALITY_INPUTS


@pytest.mark.parametrize("porcelain,shortstat", _PORCELAIN_WITH_TOKEN)
def test_b6_a_sentinel_token_in_the_porcelain_half_never_reaches_the_value(porcelain,
                                                                          shortstat):
    assert "PRESHIP:" not in _wsl(porcelain, shortstat), _wsl(porcelain, shortstat)


# --- acceptance criterion A (stronger than behavior 6, and the gate depends on it) ---
@pytest.mark.parametrize("porcelain,shortstat", _TOTALITY_INPUTS)
def test_aA_neither_half_can_smuggle_the_sentinel_token_into_the_value(porcelain,
                                                                      shortstat) -> None:
    """`tests/test_iter156_behavior.py:558` asserts the `--json` output holds exactly one
    `PRESHIP:` token, so a token echoed from EITHER half would break the gate's own
    sentinel invariant.  The spec's Expected Behavior 6 constrains only the porcelain
    half; this pins the acceptance criterion's stronger wording for both."""
    assert "PRESHIP:" not in _wsl(porcelain, shortstat), _wsl(porcelain, shortstat)


# ==========================================================================
# Behavior 7 -- exactly two repo-scoped commands, through the bare-name seam
# ==========================================================================
def test_b7_probe_issues_exactly_two_repo_scoped_commands(monkeypatch, tmp_path) -> None:
    argvs = _install(monkeypatch)
    repo = tmp_path / "some" / "repo"
    _probe(repo)
    assert len(argvs) == 2, argvs
    first, second = argvs
    assert "status" in first and "--porcelain" in first, first
    assert "diff" in second and "HEAD" in second and "--shortstat" in second, second
    for argv in argvs:
        assert "-C" in argv, argv
        i = argv.index("-C")
        assert argv[i + 1] == str(repo), argv


def test_b7_the_seam_is_reached_by_bare_module_name(monkeypatch, tmp_path) -> None:
    """If the probe captured `run_cmd` at def-time, monkeypatching the module attribute
    would NOT intercept it and the recorder would stay empty (it would also have shelled
    out to real git)."""
    argvs = _install(monkeypatch)
    _probe(tmp_path / "repo")
    assert argvs, "monkeypatching foundry.run_cmd did not intercept the probe"


# ==========================================================================
# Behavior 8 -- the probe's value is exactly the pure function's value
# ==========================================================================
def test_b8_probe_returns_exactly_what_the_pure_function_returns(monkeypatch,
                                                                 tmp_path) -> None:
    _install(monkeypatch, porcelain=" M a.py\n",
             shortstat=" 1 file changed, 2 insertions(+)")
    got = _probe(tmp_path / "repo")
    assert got == _wsl(" M a.py\n", " 1 file changed, 2 insertions(+)")
    assert got == "1 file(s) uncommitted vs HEAD; 1 file changed, 2 insertions(+)"


def test_b8_a_clean_tree_reports_the_clean_line(monkeypatch, tmp_path) -> None:
    _install(monkeypatch, porcelain="", shortstat="")
    assert _probe(tmp_path / "repo") == CLEAN


# ==========================================================================
# Behaviors 9-11 -- an unperformed scan is UNKNOWN, never "clean"
# ==========================================================================
def test_b9_failed_porcelain_command_yields_none_not_the_clean_line(monkeypatch,
                                                                    tmp_path) -> None:
    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        if _kind(argv) == "porcelain":
            return foundry.CmdResult(False, "fatal: not a git repository")
        return foundry.CmdResult(True, " 1 file changed")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    got = _probe(tmp_path / "repo")
    assert got is None, got
    assert got != CLEAN


def test_b10_a_raising_seam_yields_none_and_does_not_propagate(monkeypatch,
                                                              tmp_path) -> None:
    def boom(*a, **kw):
        raise RuntimeError("probe-boom-xyz")

    monkeypatch.setattr(foundry, "run_cmd", boom)
    assert _probe(tmp_path / "repo") is None


def test_b11_a_failed_shortstat_alone_still_reports_the_count(monkeypatch,
                                                             tmp_path) -> None:
    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        if _kind(argv) == "porcelain":
            return foundry.CmdResult(True, " M a.py\n?? b.txt\n")
        return foundry.CmdResult(False, "fatal")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    got = _probe(tmp_path / "repo")
    assert got == "2 file(s) uncommitted vs HEAD", got
    assert got == _wsl(" M a.py\n?? b.txt\n", "")


# ==========================================================================
# Behavior 12 -- NO VERDICT MOVES
# ==========================================================================
@pytest.mark.parametrize("combo", list(itertools.product((True, False), repeat=4)))
def test_b12_verdict_is_identical_to_the_pure_function_for_every_combo(monkeypatch,
                                                                      tmp_path,
                                                                      combo) -> None:
    c, s, t, sh = combo
    _install(monkeypatch, clone_ok=c, setup_ok=s, test_ok=t, sha_ok=sh)
    res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    assert _quintuple(res) == _quintuple(_expected_verdict(c, s, t, sh)), combo


def test_b12_all_three_exit_codes_are_still_reachable(monkeypatch, tmp_path) -> None:
    """A per-combo equality assertion is vacuous unless the combos actually span the
    verdict space -- assert the SET of exit codes and sentinels observed."""
    seen = set()
    for c, s, t, sh in itertools.product((True, False), repeat=4):
        _install(monkeypatch, clone_ok=c, setup_ok=s, test_ok=t, sha_ok=sh)
        res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
        seen.add((res.exit_code, res.sentinel))
    assert seen == {(0, "PRESHIP: VERIFIED"), (1, "PRESHIP: BROKEN"),
                    (2, "PRESHIP: INCOMPLETE")}, seen


def test_b12_verified_sha_is_the_expected_sha_it_was_handed(monkeypatch,
                                                            tmp_path) -> None:
    _install(monkeypatch)
    res = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")
    assert res.verified is True and res.exit_code == 0
    assert res.verified_sha == SHA, res.verified_sha


# ==========================================================================
# Behavior 13 -- a diagnostic failure is never a verdict
# ==========================================================================
@pytest.mark.parametrize("combo", [(True, True, True, True), (True, True, False, True),
                                   (True, False, True, True), (False, True, True, True)])
def test_b13_a_raising_probe_never_changes_the_verdict(monkeypatch, tmp_path,
                                                       combo) -> None:
    c, s, t, sh = combo
    _install(monkeypatch, clone_ok=c, setup_ok=s, test_ok=t, sha_ok=sh)
    good = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")

    def boom(*a, **kw):
        raise RuntimeError("probe-boom-xyz")

    _install(monkeypatch, clone_ok=c, setup_ok=s, test_ok=t, sha_ok=sh)
    monkeypatch.setattr(foundry, PROBE, boom)
    bad = foundry.verify_local_clone(_cfg(tmp_path), SHA, tmp_path / "clone")

    assert (bad.verified, bad.incomplete, bad.exit_code, bad.sentinel) == \
        (good.verified, good.incomplete, good.exit_code, good.sentinel), combo
    assert bad.worktree_scope is None, bad.worktree_scope
    assert bad.sentinel != "PRESHIP: INCOMPLETE" or good.sentinel == "PRESHIP: INCOMPLETE"


@pytest.mark.parametrize("mode", ["ok", "fail", "raise"])
def test_b13_cli_verdict_survives_every_diagnostic_outcome(monkeypatch, tmp_path,
                                                           mode) -> None:
    """The load-bearing half: the diagnostic IS wired on the CLI path, so a failing or
    raising probe must still leave rc and the sentinel byte-identical."""
    rc, out = _cli(monkeypatch, tmp_path, probe_fail=(mode == "fail"),
                   probe_raise=(mode == "raise"))
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert rc == 0, out
    assert lines[-1] == "PRESHIP: VERIFIED", out
    assert out.count("PRESHIP:") == 1, out
    if mode == "ok":
        assert "2 file(s) uncommitted vs HEAD" in out, out
    else:
        assert "unknown" in out, out
        assert "uncommitted vs HEAD" not in out, out


@pytest.mark.parametrize("verified,incomplete,code,sent", [
    (True, False, 0, "PRESHIP: VERIFIED"),
    (False, True, 2, "PRESHIP: INCOMPLETE"),
    (False, False, 1, "PRESHIP: BROKEN"),
])
def test_b13_cli_exit_codes_are_unchanged_with_the_diagnostic_wired(monkeypatch, tmp_path,
                                                                    verified, incomplete,
                                                                    code, sent) -> None:
    rc, out = _cli(monkeypatch, tmp_path,
                   result=_res(verified=verified, incomplete=incomplete))
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert rc == code, out
    assert lines[-1] == sent, out


# ==========================================================================
# Behavior 14 -- render(): detail-then-sentinel, one token, `unknown` for None
# ==========================================================================
@pytest.mark.parametrize("verified,incomplete,sent", [
    (True, False, "PRESHIP: VERIFIED"),
    (False, True, "PRESHIP: INCOMPLETE"),
    (False, False, "PRESHIP: BROKEN"),
])
def test_b14_last_non_empty_line_is_the_sentinel_and_the_token_is_unique(verified,
                                                                        incomplete,
                                                                        sent) -> None:
    res = _res(verified=verified, incomplete=incomplete, sha=SHA,
               scope="3 file(s) uncommitted vs HEAD")
    out = res.render()
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[-1] == res.sentinel == sent, out
    assert out.count("PRESHIP:") == 1, out
    assert len(lines) > 1, out


def test_b14_both_diagnostics_are_printed_above_the_sentinel() -> None:
    scope = "3 file(s) uncommitted vs HEAD; 2 files changed"
    out = _res(sha=SHA, scope=scope).render()
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert SHA in out and scope in out, out
    assert lines.index([ln for ln in lines if SHA in ln][0]) < len(lines) - 1
    assert lines.index([ln for ln in lines if scope in ln][0]) < len(lines) - 1
    assert lines[-1] == "PRESHIP: VERIFIED", out


@pytest.mark.parametrize("sha,scope", [(None, None), (SHA, None), (None, "clean -- x")])
def test_b14_a_missing_diagnostic_prints_unknown_not_none(sha, scope) -> None:
    out = _res(sha=sha, scope=scope).render()
    assert "None" not in out, out
    assert out.count("unknown") == [sha, scope].count(None), out
    assert [ln for ln in out.splitlines() if ln.strip()][-1] == "PRESHIP: VERIFIED", out


# ==========================================================================
# Behavior 15 -- to_dict() is exactly 8 JSON-native keys
# ==========================================================================
def test_b15_to_dict_has_exactly_the_eight_keys() -> None:
    d = _res(sha=SHA, scope="clean -- x").to_dict()
    assert set(d) == {"verified", "incomplete", "exit_code", "detail", "sentinel",
                      "test_seconds", "verified_sha", "worktree_scope"}, sorted(d)
    assert len(d) == 8, d


def test_b15_the_six_existing_keys_keep_their_values() -> None:
    res = _res(verified=False, incomplete=True, detail="why", secs=2.25, sha=SHA,
               scope="clean -- x")
    d = res.to_dict()
    assert d["verified"] is False and d["incomplete"] is True
    assert d["detail"] == "why" and d["test_seconds"] == 2.25
    assert d["exit_code"] == res.exit_code == 2
    assert d["sentinel"] == res.sentinel == "PRESHIP: INCOMPLETE"
    assert d["verified_sha"] == SHA and d["worktree_scope"] == "clean -- x"


@pytest.mark.parametrize("sha,scope", [(None, None), (SHA, "clean -- x")])
def test_b15_to_dict_round_trips_through_json(sha, scope) -> None:
    d = _res(sha=sha, scope=scope).to_dict()
    assert json.loads(json.dumps(d)) == d


def test_b15_json_cli_form_carries_both_new_keys(monkeypatch, tmp_path) -> None:
    rc, out = _cli(monkeypatch, tmp_path, as_json=True)
    doc = json.loads(out)
    assert set(doc) == {"verified", "incomplete", "exit_code", "detail", "sentinel",
                        "test_seconds", "verified_sha", "worktree_scope"}, sorted(doc)
    assert doc["worktree_scope"] == "2 file(s) uncommitted vs HEAD; 1 file changed, " \
                                    "2 insertions(+)", doc
    assert out.count("PRESHIP:") == 1, out
    assert rc == 0


# ==========================================================================
# Behavior 16 -- BACK-COMPAT
# ==========================================================================
def test_b16_three_and_four_positional_construction_still_work() -> None:
    a = foundry.PreshipResult(True, False, "d")
    b = foundry.PreshipResult(True, False, "d", 1.5)
    assert a.test_seconds is None and b.test_seconds == 1.5
    for r in (a, b):
        assert r.verified is True and r.incomplete is False and r.detail == "d"
        assert r.verified_sha is None and r.worktree_scope is None


def test_b16_record_is_still_frozen_and_the_verdict_stays_derived() -> None:
    assert dataclasses.is_dataclass(foundry.PreshipResult)
    assert foundry.PreshipResult.__dataclass_params__.frozen is True
    names = [f.name for f in dataclasses.fields(foundry.PreshipResult)]
    assert "exit_code" not in names and "sentinel" not in names, names
    assert names[:4] == ["verified", "incomplete", "detail", "test_seconds"], names
    for prop in ("exit_code", "sentinel"):
        assert isinstance(getattr(foundry.PreshipResult, prop), property), prop
    with pytest.raises(dataclasses.FrozenInstanceError):
        foundry.PreshipResult(True, False, "d").verified = False


def test_b16_the_two_new_fields_are_the_last_two_and_default_to_none() -> None:
    fields = {f.name: f for f in dataclasses.fields(foundry.PreshipResult)}
    for name in ("verified_sha", "worktree_scope"):
        assert name in fields, sorted(fields)
        assert fields[name].default is None, fields[name].default
    order = [f.name for f in dataclasses.fields(foundry.PreshipResult)]
    assert order[-2:] == ["verified_sha", "worktree_scope"], order


# ==========================================================================
# Acceptance criteria B and C
# ==========================================================================
def test_aB_both_modules_still_import() -> None:
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_aC_both_roadmap_records_for_this_iteration_are_present() -> None:
    idx = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    arc = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    ledger = [ln for ln in idx.splitlines() if ln.startswith("- iter %d " % THIS_ITER)]
    bullets = [ln for ln in arc.splitlines()
               if ln.startswith("- **iter %d " % THIS_ITER)]
    assert len(ledger) == 1, ledger
    assert len(bullets) == 1, bullets
