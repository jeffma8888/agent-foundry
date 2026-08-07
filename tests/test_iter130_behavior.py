"""Black-box behaviour tests for iter 130 -- `foundry live-lag`: report the iterations
that git says are shipped but that the RUNNING brain cannot be executing, because they
were committed after the live dispatcher's launch instant.

Spec: products/_platform/state/iter-130/pm.md, Expected Behaviors 1-14.

  parse_brain_launch(log_text, year=Y)
  1.  LAST `dispatcher up` banner in the text wins, selected by POSITION (last
      occurrence), not by stamp ordering; returns a float epoch.
  2.  total: None for no banner / empty string / malformed stamp / out-of-range
      fields; never raises for ANY string input.
  3.  ignores non-banner lines; a lone banner among stage lines still parses.
  inert_iterations(launch_epoch, commits)
  4.  pure + total: commit_epoch STRICTLY GREATER than launch -> inert; ascending,
      deduplicated tuple.
  5.  commit_epoch == launch_epoch counts as LIVE.
  6.  launch None -> () (never guess); empty commits -> ().
  git_ship_commits(repo)  -- the ONE new I/O seam
  7.  (iteration, epoch) pairs via `iteration_from_subject`; () on EVERY failure
      mode, never raising, never printing a traceback.
  8.  tolerates malformed lines inside otherwise good output.
  live_lag_line(cfg)
  9.  composes the above through BARE module names; one-line string; carries the
      count and every inert iteration number; distinct healthy phrasing; never
      None, never raises even when a seam raises.
  10. UNKNOWN launch instant is distinguished from HEALTHY.
  CLI + dormancy
  11. `foundry live-lag` exits 0 when nothing inert or unknown, 2 when inert.
  12. `foundry doctor` gains exactly ONE line from the same core: WARN + count
      when inert, no WARN when clean; existing checks/exit contract unchanged.
  13. DORMANT on the control path (run_iteration, run_continuous, run_stage,
      build_prompt, postrelease_step) and `import foundry, dispatcher` succeeds.
  14. real-tree smoke: git_ship_commits on the actual product repo.
  Plus Acceptance-Criteria oracles: docstring purity/totality claims, the
  public-safety scan of the new code, the no-write proof, and the two roadmap
  ledger records.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-130 PM spec and from the
product's own OBSERVABLE surface -- importing the module, CALLING its public
functions, reading `__doc__` / `inspect.signature`, running the CLI, and reading
files under tests/. The implementation BODIES of foundry.py / dispatcher.py, the
engineer's notes, the reviewer's notes and `git diff` were NOT read. Behavior 13
and the public-safety oracle use `inspect.getsource` MECHANICALLY (substring
assertions only, never displayed), exactly as the spec mandates.

Offline and deterministic: synthetic fixture strings, throwaway tmp_path dirs, and
read-only `git log` against the product repo only where the spec asks for it
(Behavior 14's smoke test, and Behavior 7's "path is not a repository" mode, which
cannot be proven by faking the very call it is about). No network, no agent run,
no sleeps, no mutation of the product tree.
"""
import inspect
import json
import pathlib
import subprocess
import sys
from datetime import datetime

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- Acceptance Criteria)

BANNER_A = "- `08-03 09:41:14` dispatcher up; teams=2 concurrency=1\n"
BANNER_B = "- `08-05 15:13:46` dispatcher up; teams=2 concurrency=1\n"
STAGE_LINE = "- `08-05 16:02:11` iter 87 - **pm** attempt 1 started\n"

NEW_NAMES = ("parse_brain_launch", "inert_iterations", "git_ship_commits", "live_lag_line")
CONTROL_PATH_FNS = ("run_iteration", "run_continuous", "run_stage",
                    "build_prompt", "postrelease_step")


class _Proc:
    """Minimal CompletedProcess stand-in (mirrors the suite's convention)."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Chk:
    """Minimal stand-in check result for the doctor-CLI guards."""

    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


def _cfg(**over):
    kw = dict(name="demo", repo="/no/such/repo", allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _write_cfg(tmp_path, **over):
    """A minimal product config on disk (mirrors the suite's convention)."""
    data = {
        "name": "demo",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demo",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _snapshot(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _patch_lag(monkeypatch, launch, commits):
    """Script both upstream seams of live_lag_line, offline."""
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: launch)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: tuple(commits))


# ---------------------------------------------------------------- Behavior 1
def test_b1_last_banner_wins_by_position():
    text = BANNER_A + STAGE_LINE + BANNER_B
    got = foundry.parse_brain_launch(text, year=2026)
    assert got == datetime(2026, 8, 5, 15, 13, 46).timestamp()


def test_b1_last_banner_wins_even_when_earlier_stamp():
    """Selection is by POSITION IN THE TEXT, not by stamp ordering."""
    text = BANNER_B + BANNER_A
    got = foundry.parse_brain_launch(text, year=2026)
    assert got == datetime(2026, 8, 3, 9, 41, 14).timestamp()


def test_b1_returns_a_float():
    got = foundry.parse_brain_launch(BANNER_B, year=2026)
    assert isinstance(got, float) and not isinstance(got, bool)


def test_b1_year_argument_is_honoured():
    """The stamp has no year, so the caller's year must be the one used."""
    assert foundry.parse_brain_launch(BANNER_B, year=2025) == \
        datetime(2025, 8, 5, 15, 13, 46).timestamp()
    assert foundry.parse_brain_launch(BANNER_B, year=2026) != \
        foundry.parse_brain_launch(BANNER_B, year=2025)


# ---------------------------------------------------------------- Behavior 2
def test_b2_no_banner_returns_none():
    assert foundry.parse_brain_launch("", year=2026) is None
    assert foundry.parse_brain_launch("nothing to see here\n", year=2026) is None


def test_b2_malformed_stamp_returns_none():
    assert foundry.parse_brain_launch("- `not-a-date` dispatcher up; teams=2\n",
                                      year=2026) is None


def test_b2_out_of_range_stamp_returns_none():
    """Shape-valid but impossible fields must degrade, not raise."""
    assert foundry.parse_brain_launch("- `13-45 99:99:99` dispatcher up; teams=2\n",
                                      year=2026) is None


def test_b2_never_raises_for_arbitrary_string_input():
    junk = [
        "", "\n", "\n\n\n", "dispatcher up", "- `` dispatcher up;",
        "- `08-03` dispatcher up;", "- `08-03 09:41` dispatcher up;",
        "- `08-03 09:41:14` dispatcher down;",
        "\x00\x01 dispatcher up \x7f",
        "dispatcher up " * 5000,
        "- `08-03 09:41:14` dispatcher up;" + ("x" * 20000),
        "\u4e2d\u6587 dispatcher up \u2014 banner",
        BANNER_A.rstrip("\n"),
        STAGE_LINE + BANNER_A + "trailing junk without newline",
        "- `02-30 00:00:00` dispatcher up;",
        "- `00-00 00:00:00` dispatcher up;",
    ]
    for text in junk:
        got = foundry.parse_brain_launch(text, year=2026)
        assert got is None or isinstance(got, float), f"bad return for {text[:40]!r}: {got!r}"


def test_b2_absent_year_is_unknown_not_guessed():
    """The parser refuses to invent a year (documented totality contract)."""
    assert foundry.parse_brain_launch(BANNER_B) is None


def test_b2_unusable_year_returns_none_without_raising():
    for bad in ("abc", None, "", 3.7, object()):
        got = foundry.parse_brain_launch(BANNER_B, year=bad)
        assert got is None or isinstance(got, float), f"year={bad!r} -> {got!r}"


# ---------------------------------------------------------------- Behavior 3
def test_b3_banner_between_stage_lines_parses():
    text = STAGE_LINE + STAGE_LINE + BANNER_A + STAGE_LINE
    assert foundry.parse_brain_launch(text, year=2026) == \
        datetime(2026, 8, 3, 9, 41, 14).timestamp()


def test_b3_stage_lines_only_returns_none():
    assert foundry.parse_brain_launch(STAGE_LINE * 20, year=2026) is None


# ---------------------------------------------------------------- Behavior 4
def test_b4_strictly_greater_ascending_deduped():
    assert foundry.inert_iterations(100.0, [(5, 99), (7, 101), (6, 150), (7, 200)]) == (6, 7)


def test_b4_returns_an_immutable_tuple_of_ints():
    got = foundry.inert_iterations(0.0, [(3, 1), (1, 2), (2, 3)])
    assert isinstance(got, tuple) and got == (1, 2, 3)
    assert all(isinstance(i, int) for i in got)


def test_b4_accepts_any_iterable_not_only_a_list():
    gen = ((i, 500.0) for i in (9, 8, 9))
    assert foundry.inert_iterations(100.0, gen) == (8, 9)
    assert foundry.inert_iterations(100.0, ((4, 200), (5, 300))) == (4, 5)


def test_b4_everything_before_launch_is_empty():
    assert foundry.inert_iterations(1000.0, [(1, 1), (2, 2), (3, 999.999)]) == ()


def test_b4_is_pure_no_mutation_of_input():
    commits = [(6, 150), (7, 101)]
    before = list(commits)
    foundry.inert_iterations(100.0, commits)
    assert commits == before


def test_b4_malformed_pairs_are_skipped_not_raised():
    """Total: one bad row can never sink the whole report."""
    got = foundry.inert_iterations(100.0, [(6, 150), "nope", (7,), None,
                                           ("x", 150), (8, "y"), (9, 200)])
    assert got == (6, 9)


# ---------------------------------------------------------------- Behavior 5
def test_b5_equal_epoch_is_live():
    assert foundry.inert_iterations(100.0, [(9, 100)]) == ()


def test_b5_boundary_one_tick_either_side():
    assert foundry.inert_iterations(100.0, [(9, 100.0001)]) == (9,)
    assert foundry.inert_iterations(100.0, [(9, 99.9999)]) == ()


# ---------------------------------------------------------------- Behavior 6
def test_b6_unknown_launch_reports_nothing():
    assert foundry.inert_iterations(None, [(1, 10), (2, 10 ** 12)]) == ()
    assert foundry.inert_iterations(100.0, []) == ()


def test_b6_unknown_launch_and_empty_commits():
    assert foundry.inert_iterations(None, []) == ()
    assert foundry.inert_iterations(None, (x for x in [(1, 10 ** 12)])) == ()


# ---------------------------------------------------------------- Behavior 7
def _stdout(*rows):
    return "".join(f"{e}\t{s}\n" for e, s in rows)


def test_b7_success_returns_iteration_epoch_pairs(monkeypatch):
    out = _stdout((1700000200, "feat: add a thing (foundry iter 42)"),
                  (1700000100, "fix: another thing (foundry iter 41)"))
    monkeypatch.setattr(foundry.subprocess, "run", lambda *a, **k: _Proc(0, out, ""))
    got = foundry.git_ship_commits("/anywhere")
    assert set(got) == {(42, 1700000200.0), (41, 1700000100.0)}
    assert all(isinstance(i, int) and isinstance(e, float) for i, e in got)


def test_b7_subjects_without_an_iteration_are_skipped(monkeypatch):
    out = _stdout((1700000300, "chore: routine housekeeping"),
                  (1700000200, "docs: mentions iter 7 mid-sentence, not a ship tag"),
                  (1700000100, "feat: real ship (foundry iter 43)"))
    monkeypatch.setattr(foundry.subprocess, "run", lambda *a, **k: _Proc(0, out, ""))
    assert foundry.git_ship_commits("/anywhere") == ((43, 1700000100.0),)


def test_b7_non_existent_path_returns_empty(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert foundry.git_ship_commits(str(tmp_path / "does-not-exist")) == ()
    assert foundry.git_ship_commits(str(plain)) == ()


def test_b7_non_zero_exit_returns_empty(monkeypatch):
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: _Proc(128, "", "fatal: not a git repository"))
    assert foundry.git_ship_commits("/anywhere") == ()


def test_b7_missing_git_binary_returns_empty(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError(2, "No such file or directory: 'git'")
    monkeypatch.setattr(foundry.subprocess, "run", missing)
    assert foundry.git_ship_commits("/anywhere") == ()


def test_b7_timeout_returns_empty(monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd=["git", "log"], timeout=1)
    monkeypatch.setattr(foundry.subprocess, "run", slow)
    assert foundry.git_ship_commits("/anywhere") == ()


def test_b7_os_error_returns_empty(monkeypatch):
    def broken(*a, **k):
        raise OSError(13, "Permission denied")
    monkeypatch.setattr(foundry.subprocess, "run", broken)
    assert foundry.git_ship_commits("/anywhere") == ()


def test_b7_unparsable_output_returns_empty(monkeypatch):
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: _Proc(0, "\x00 not\tremotely a log \x01\n\n", ""))
    assert foundry.git_ship_commits("/anywhere") == ()


def test_b7_accepts_a_path_object(monkeypatch):
    out = _stdout((1700000000, "feat: p (foundry iter 44)"))
    monkeypatch.setattr(foundry.subprocess, "run", lambda *a, **k: _Proc(0, out, ""))
    assert foundry.git_ship_commits(pathlib.Path("/anywhere")) == ((44, 1700000000.0),)


def test_b7_never_prints_a_traceback(monkeypatch, capsys, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("scripted seam explosion")
    monkeypatch.setattr(foundry.subprocess, "run", boom)
    assert foundry.git_ship_commits("/anywhere") == ()
    assert foundry.git_ship_commits(str(tmp_path / "nope")) == ()
    cap = capsys.readouterr()
    assert "Traceback" not in (cap.out + cap.err)


def test_b7_iteration_numbers_agree_with_iteration_from_subject(monkeypatch):
    """B7 derives pairs VIA `iteration_from_subject`; prove the seam AGREES with it.

    A reimplemented, looser matcher would satisfy every other B7 test while
    counting non-ship commits as shipped iterations. The shipped helper anchors
    the ship tag at the END of the subject, so a number quoted mid-sentence is
    not a ship claim -- this table pins that contract AT the seam, without
    caring how the seam is written.
    """
    subjects = [
        "feat: add a thing (foundry iter 42)",
        "feat: ship iter 42 thing",
        "docs: iter 7 is mentioned mid-sentence",
        "chore: routine housekeeping",
        "fix: trailing tag wins (foundry iter 130)",
        "feat: iter 99",
        "feat: tag not last (foundry iter 8) then more words",
    ]
    rows = [(1700000000 + i, s) for i, s in enumerate(subjects)]
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: _Proc(0, _stdout(*rows), ""))
    got = foundry.git_ship_commits("/anywhere")
    expected = {(foundry.iteration_from_subject(s), float(e))
                for e, s in rows if foundry.iteration_from_subject(s) is not None}
    assert len(expected) >= 2, "fixture must carry at least two real ship tags"
    assert set(got) == expected, f"seam disagrees with the helper: {got!r} vs {expected!r}"
    assert len(got) == len(expected), f"duplicate or dropped rows: {got!r}"


def test_b7_iteration_from_subject_is_reused_not_reimplemented(monkeypatch):
    """The design constraint is REUSE, so patching the shipped helper must bite."""
    monkeypatch.setattr(foundry.subprocess, "run",
                        lambda *a, **k: _Proc(0, _stdout((1700000000, "anything at all")), ""))
    monkeypatch.setattr(foundry, "iteration_from_subject", lambda s: 777)
    assert foundry.git_ship_commits("/anywhere") == ((777, 1700000000.0),)


# ---------------------------------------------------------------- Behavior 8
def test_b8_malformed_lines_inside_good_output_are_skipped(monkeypatch):
    out = (
        "1700000500\tfeat: good one (foundry iter 45)\n"
        "1700000400 no-tab-at-all (foundry iter 46)\n"
        "not-an-int\tfeat: bad epoch (foundry iter 47)\n"
        "\n"
        "   \n"
    )
    monkeypatch.setattr(foundry.subprocess, "run", lambda *a, **k: _Proc(0, out, ""))
    assert foundry.git_ship_commits("/anywhere") == ((45, 1700000500.0),)


# ---------------------------------------------------------------- Behavior 9
INERT_FIXTURE = ((118, 900), (119, 1100), (122, 1200), (124, 1300))  # launch 1000 -> 3 inert


def test_b9_reports_count_and_every_inert_number(monkeypatch):
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    line = foundry.live_lag_line(_cfg())
    assert isinstance(line, str) and line.strip()
    assert "3" in line, f"inert COUNT missing from: {line!r}"
    for n in ("119", "122", "124"):
        assert n in line, f"inert iteration {n} missing from: {line!r}"


def test_b9_is_a_single_line(monkeypatch):
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    line = foundry.live_lag_line(_cfg())
    assert len(line.rstrip("\n").splitlines()) == 1, f"not one line: {line!r}"


def test_b9_live_iterations_are_not_listed_as_inert(monkeypatch):
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    line = foundry.live_lag_line(_cfg())
    assert "118" not in line, f"iteration committed BEFORE launch reported as inert: {line!r}"


def test_b9_healthy_phrasing_is_distinct(monkeypatch):
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    inert_line = foundry.live_lag_line(_cfg())
    _patch_lag(monkeypatch, 1000.0, ((118, 900), (119, 950)))
    healthy_line = foundry.live_lag_line(_cfg())
    assert isinstance(healthy_line, str) and healthy_line.strip()
    assert healthy_line != inert_line
    assert foundry.LIVE_LAG_WARN in inert_line
    assert foundry.LIVE_LAG_WARN not in healthy_line, f"clean state carries WARN: {healthy_line!r}"
    for n in ("119", "122", "124"):
        assert f": {n}" not in healthy_line
    assert "not live" not in healthy_line.lower(), f"inert-only wording leaked: {healthy_line!r}"


def test_b9_empty_ship_truth_is_not_a_warning(monkeypatch):
    _patch_lag(monkeypatch, 1000.0, ())
    line = foundry.live_lag_line(_cfg())
    assert isinstance(line, str) and line.strip()
    assert foundry.LIVE_LAG_WARN not in line


def test_b9_composes_seams_by_bare_module_name(monkeypatch):
    """Patching the middle pure function must change the rendered line."""
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    monkeypatch.setattr(foundry, "inert_iterations", lambda *a, **k: (4242,))
    line = foundry.live_lag_line(_cfg())
    assert "4242" in line, f"inert_iterations not called by bare name: {line!r}"


@pytest.mark.parametrize("seam", ["parse_brain_launch", "git_ship_commits", "inert_iterations"])
def test_b9_never_raises_when_a_seam_raises(monkeypatch, seam):
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)

    def boom(*a, **k):
        raise RuntimeError(f"scripted {seam} explosion")
    monkeypatch.setattr(foundry, seam, boom)
    line = foundry.live_lag_line(_cfg())
    assert isinstance(line, str) and line.strip(), f"{seam} raising produced {line!r}"


def test_b9_never_raises_on_a_bogus_cfg_and_missing_log(tmp_path):
    line = foundry.live_lag_line(_cfg(repo=str(tmp_path / "nope")),
                                 log_path=str(tmp_path / "absent.out"))
    assert isinstance(line, str) and line.strip()


# --------------------------------------------------------------- Behavior 10
def test_b10_unknown_launch_is_reported_as_unknown(monkeypatch):
    _patch_lag(monkeypatch, None, INERT_FIXTURE)
    line = foundry.live_lag_line(_cfg())
    assert isinstance(line, str) and line.strip()
    assert "unknown" in line.lower(), f"UNKNOWN state not stated: {line!r}"


def test_b10_unknown_does_not_claim_up_to_date(monkeypatch):
    _patch_lag(monkeypatch, None, INERT_FIXTURE)
    unknown = foundry.live_lag_line(_cfg())
    _patch_lag(monkeypatch, 1000.0, ((118, 900),))
    healthy = foundry.live_lag_line(_cfg())
    assert unknown != healthy
    assert "up to date" not in unknown.lower(), f"unknown claims freshness: {unknown!r}"
    assert foundry.LIVE_LAG_WARN not in unknown, "'cannot tell' must not raise a WARN"


def test_b10_unknown_lists_no_iteration_numbers(monkeypatch):
    _patch_lag(monkeypatch, None, INERT_FIXTURE)
    line = foundry.live_lag_line(_cfg())
    for n in ("118", "119", "122", "124"):
        assert f": {n}" not in line


# --------------------------------------------------------------- Behavior 11
def test_b11_cli_exit_2_when_inert(monkeypatch, capsys, tmp_path):
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    rc = foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 2, f"inert must exit 2, got {rc}"
    assert foundry.LIVE_LAG_WARN in out and "124" in out


def test_b11_cli_exit_0_when_nothing_inert(monkeypatch, capsys, tmp_path):
    _patch_lag(monkeypatch, 1000.0, ((118, 900),))
    rc = foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0, f"clean must exit 0, got {rc}"
    assert out.strip()


def test_b11_cli_exit_0_when_unknown(monkeypatch, capsys, tmp_path):
    _patch_lag(monkeypatch, None, INERT_FIXTURE)
    rc = foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0, f"unknown must exit 0 (nothing proven), got {rc}"
    assert "unknown" in out.lower()


def test_b11_cli_reads_a_real_log_fixture_end_to_end(monkeypatch, capsys, tmp_path):
    """No parse patching: the banner comes off disk, only ship-truth is scripted."""
    log = tmp_path / "dispatcher.out"
    log.write_text(STAGE_LINE + BANNER_A + STAGE_LINE + BANNER_B + STAGE_LINE)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((130, 2.0e9),))
    rc = foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path)), "--log", str(log)])
    out = capsys.readouterr().out
    assert rc == 2 and "130" in out and foundry.LIVE_LAG_WARN in out

    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((7, 1.0e6),))
    rc = foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path)), "--log", str(log)])
    out = capsys.readouterr().out
    assert rc == 0 and foundry.LIVE_LAG_WARN not in out


def test_b11_cli_with_a_bannerless_log_is_unknown_and_zero(monkeypatch, capsys, tmp_path):
    log = tmp_path / "dispatcher.out"
    log.write_text(STAGE_LINE * 5)
    monkeypatch.setattr(foundry, "git_ship_commits", lambda *a, **k: ((130, 2.0e9),))
    rc = foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path)), "--log", str(log)])
    out = capsys.readouterr().out
    assert rc == 0 and "unknown" in out.lower()


def test_b11_live_lag_cli_returns_the_same_codes_directly(monkeypatch, capsys, tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    assert foundry.live_lag_cli(cfg) == 2
    _patch_lag(monkeypatch, 1000.0, ((118, 900),))
    assert foundry.live_lag_cli(cfg) == 0
    _patch_lag(monkeypatch, None, INERT_FIXTURE)
    assert foundry.live_lag_cli(cfg) == 0
    capsys.readouterr()


def test_b11_cli_never_gates_a_build_with_a_code_above_two(monkeypatch, capsys, tmp_path):
    for launch, commits in ((1000.0, INERT_FIXTURE), (1000.0, ()), (None, INERT_FIXTURE)):
        _patch_lag(monkeypatch, launch, commits)
        rc = foundry.main(["live-lag", "--config", str(_write_cfg(tmp_path))])
        assert rc in (0, 2), f"unexpected exit {rc}"
    capsys.readouterr()


def test_b11_cli_writes_nothing(monkeypatch, capsys, tmp_path):
    cfg_path = _write_cfg(tmp_path)
    before = _snapshot(tmp_path)
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    foundry.main(["live-lag", "--config", str(cfg_path)])
    capsys.readouterr()
    assert _snapshot(tmp_path) == before, "live-lag created or mutated a file"


# --------------------------------------------------------------- Behavior 12
def _stub_checks(monkeypatch, ok=True):
    for name in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(foundry, f"check_{name}", lambda *a, _n=name, **k: _Chk(_n, ok))


def test_b12_doctor_gains_exactly_one_line_from_the_shared_core(monkeypatch, capsys, tmp_path):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: "ZZSENTINELZZ one line only")
    foundry.main(["doctor", "--config", str(_write_cfg(tmp_path))])
    out = capsys.readouterr().out
    hits = [ln for ln in out.splitlines() if "ZZSENTINELZZ" in ln]
    assert len(hits) == 1, f"expected exactly ONE live_lag_line-sourced line, got {hits}"


def test_b12_doctor_warns_with_the_count_when_inert(monkeypatch, capsys, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    foundry.main(["doctor", "--config", str(_write_cfg(tmp_path))])
    out = capsys.readouterr().out
    warn_lines = [ln for ln in out.splitlines()
                  if foundry.LIVE_LAG_WARN in ln and "3" in ln]
    assert warn_lines, f"no WARN+count line in doctor output:\n{out}"
    assert "124" in "\n".join(warn_lines)


def test_b12_doctor_prints_the_line_without_warn_when_clean(monkeypatch, capsys, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch, 1000.0, ((118, 900),))
    foundry.main(["doctor", "--config", str(_write_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert "live-lag" in out, f"the new line vanished when clean:\n{out}"
    assert foundry.LIVE_LAG_WARN not in out, f"clean doctor carries WARN:\n{out}"


def test_b12_doctor_existing_checks_are_unchanged(monkeypatch, capsys, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    foundry.main(["doctor", "--config", str(_write_cfg(tmp_path))])
    out = capsys.readouterr().out
    for name in ("power", "agent", "uv", "remote"):
        assert name in out, f"doctor lost its {name} check:\n{out}"


def test_b12_run_doctor_still_returns_exactly_four_checks(monkeypatch, tmp_path):
    _stub_checks(monkeypatch)
    _patch_lag(monkeypatch, 1000.0, INERT_FIXTURE)
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert [c.name for c in foundry.run_doctor(cfg)] == ["power", "agent", "uv", "remote"]


def test_b12_doctor_exit_code_is_independent_of_the_lag(monkeypatch, capsys, tmp_path):
    cfg_path = str(_write_cfg(tmp_path))
    codes = {}
    for label, (launch, commits) in {"inert": (1000.0, INERT_FIXTURE),
                                     "clean": (1000.0, ()),
                                     "unknown": (None, INERT_FIXTURE)}.items():
        _stub_checks(monkeypatch, ok=True)
        _patch_lag(monkeypatch, launch, commits)
        codes[("ok", label)] = foundry.main(["doctor", "--config", cfg_path])
        _stub_checks(monkeypatch, ok=False)
        codes[("bad", label)] = foundry.main(["doctor", "--config", cfg_path])
    capsys.readouterr()
    assert {v for k, v in codes.items() if k[0] == "ok"} == {0}, codes
    assert len({v for k, v in codes.items() if k[0] == "bad"}) == 1, codes
    assert 0 not in {v for k, v in codes.items() if k[0] == "bad"}, codes


def test_b12_doctor_survives_a_raising_seam(monkeypatch, capsys, tmp_path):
    """live_lag_line must not raise (B9), so doctor cannot be broken by ship-truth."""
    _stub_checks(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("scripted git failure")
    monkeypatch.setattr(foundry, "git_ship_commits", boom)
    monkeypatch.setattr(foundry, "parse_brain_launch", lambda *a, **k: 1000.0)
    rc = foundry.main(["doctor", "--config", str(_write_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0 and "power" in out and "remote" in out


# --------------------------------------------------------------- Behavior 13
def _names_of(fn):
    code = fn.__code__
    seen = set(code.co_names) | set(code.co_varnames) | set(code.co_consts)
    return {n for n in seen if isinstance(n, str)}


def test_b13_control_path_source_has_no_reference_to_the_new_surface():
    for fname in CONTROL_PATH_FNS:
        fn = getattr(foundry, fname, None)
        assert callable(fn), f"foundry.{fname} missing/not callable (regression)"
        src = inspect.getsource(fn)
        for sym in NEW_NAMES + ("live_lag_cli", "LIVE_LAG_WARN", "live-lag"):
            assert sym not in src, f"{fname} references {sym!r} -- must stay dormant"


def test_b13_control_path_compiled_names_are_clean():
    for fname in CONTROL_PATH_FNS:
        names = _names_of(getattr(foundry, fname))
        for sym in NEW_NAMES + ("live_lag_cli",):
            assert sym not in names, f"{fname} calls {sym!r} at runtime"


def test_b13_both_modules_still_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b13_dispatcher_does_not_reference_the_new_surface():
    for sym in NEW_NAMES + ("live_lag_cli", "LIVE_LAG_WARN"):
        assert not hasattr(dispatcher, sym), f"dispatcher exposes {sym!r}"
    src = pathlib.Path(dispatcher.__file__).read_text()
    for sym in NEW_NAMES + ("live_lag_cli", "live-lag"):
        assert sym not in src, f"dispatcher.py mentions {sym!r}"


# --------------------------------------------------------------- Behavior 14
def test_b14_real_tree_smoke_git_ship_commits():
    pairs = foundry.git_ship_commits(_ROOT)
    assert pairs, "git_ship_commits found no ship commits in the real repo"
    assert all(isinstance(i, int) and i > 0 for i, _ in pairs), pairs[:5]
    assert all(isinstance(e, float) and e > 0 for _, e in pairs), pairs[:5]
    iters = {i for i, _ in pairs}
    assert iters & set(range(120, 130)), f"no iteration in 120-129 found: {sorted(iters)[-8:]}"


def test_b14_real_tree_report_is_consistent_with_the_seam():
    """End-to-end on the live tree: whatever is reported inert must be shipped."""
    cfg = _cfg(repo=str(_ROOT))
    line = foundry.live_lag_line(cfg)
    assert isinstance(line, str) and line.strip()
    shipped = {i for i, _ in foundry.git_ship_commits(_ROOT)}
    launch = foundry.parse_brain_launch(
        (_ROOT / "dispatcher.out").read_text() if (_ROOT / "dispatcher.out").exists() else "",
        year=2026)
    for n in foundry.inert_iterations(launch, foundry.git_ship_commits(_ROOT)):
        assert n in shipped


# --------------------------------------------------- Acceptance Criteria
def test_ac_docstrings_state_the_purity_and_totality_contracts():
    for name in NEW_NAMES:
        doc = (getattr(foundry, name).__doc__ or "")
        assert len(doc.strip()) > 40, f"{name} has no real docstring"
        low = doc.lower()
        assert "never" in low and ("rais" in low or "exception" in low), \
            f"{name} docstring does not state its totality contract"
    for pure in ("parse_brain_launch", "inert_iterations"):
        doc = (getattr(foundry, pure).__doc__ or "").lower()
        assert "pure" in doc and "total" in doc, f"{pure} docstring omits pure/total"


def test_ac_public_safety_no_machine_paths_or_operator_identifiers():
    # assembled from fragments so this oracle never matches its own source
    banned = ("/Us" + "ers/", "/Vol" + "umes/", "jin" + "cm", "615" + "45", "~/pro" + "jects")
    for name in NEW_NAMES + ("live_lag_cli",):
        src = inspect.getsource(getattr(foundry, name))
        for bad in banned:
            assert bad not in src, f"{name} leaks {bad!r}"
    own = pathlib.Path(__file__).read_text()
    for bad in banned:
        assert bad not in own, f"this test file leaks {bad!r}"


def test_ac_roadmap_and_archive_carry_the_iter130_records():
    road = (_ROOT / "PLATFORM_ROADMAP.md").read_text()
    rows = [ln for ln in road.splitlines() if ln.lstrip().startswith("- iter 130 ")]
    assert rows, "no iter-130 Done-ledger row in PLATFORM_ROADMAP.md"
    assert any(len(r) <= 120 for r in rows), \
        f"every iter-130 ledger row exceeds 120 chars: {[len(r) for r in rows]}"
    arch = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()
    assert "- **iter 130 " in arch, "verbatim `- **iter 130 ` detail bullet missing from archive"


def test_ac_no_new_module_level_config_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(foundry.ProductConfig)}
    for sym in ("live_lag", "lag", "brain_launch", "live_lag_enabled"):
        assert sym not in fields, f"ProductConfig gained a new field {sym!r}"
