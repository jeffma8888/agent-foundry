"""Iteration 529 -- BLACK-BOX behavior tests.

Only the NEWEST (numerically highest) attempt of each `(iteration, stage)` can
count as `produced` in `_walk_attempt_logs`; every earlier attempt in that
stage-run failed by construction (`run_stage` returns on first success), so a
later success must no longer retroactively erase earlier losses in `losses`,
`rescues` and doctor's `auth-loss` line.

ISOLATION CONTRACT (HONORED): written from the iter-529 PM spec's Expected
Behaviors 1-10, the conventions of tests/ (test_iter172/336/361/363/380), and the
product's OWN observable output. The implementation source, the engineer's and
reviewer's notes, IMPLEMENTATION.patch and `git diff` were NOT read. The only
source-text contact is B10's call-site COUNT, which the spec itself pins.

Every fixture lives in `tmp_path` (OPERATOR 2026-08-11: state/ is gitignored and
absent from the fresh clone). No git in this module.

Row shape (test_iter380 b4): `(stage, iteration, attempt, produced, text)`.
"""

from __future__ import annotations

import collections
import inspect
import os
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

REL_REPO = "products/_platform/state/iter-529"
AUTH = "foundry-engine: auth failed: credential command exited with status 1\n"
CLEAN = "ordinary stage narration, nothing notable\n"
KILL = "agent run failed: agent run timed out after 600s\n"
UNDECODABLE = b"\xff\xfe\xfa\x80 not utf8\n"


def _cfg(tmp_path):
    return foundry.ProductConfig(name="demo", repo=REL_REPO, allowed_push_repo="demo",
                                 work_root=str(tmp_path))


def _plant(cfg, iteration, stage, attempts, out="out\n", text=CLEAN):
    """`attempts` is an iterable of attempt numbers (or {n: text}); `out` None = no file."""
    d = pathlib.Path(cfg.state) / f"iter-{iteration}"
    d.mkdir(parents=True, exist_ok=True)
    items = attempts.items() if isinstance(attempts, dict) else ((n, text) for n in attempts)
    for n, body in items:
        p = d / f"{stage}.attempt{n}.log"
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
    if out is not None:
        (d / f"{stage}.md").write_text(out, encoding="utf-8")
    return d


def _walk(cfg, *a):
    return list(foundry._walk_attempt_logs(cfg, *a))


def _produced(rows, stage, iteration=None):
    return {r[2]: r[3] for r in rows
            if r[0] == stage and (iteration is None or r[1] == iteration)}


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in pathlib.Path(root).rglob("*"))


# ========================================================================== #
# B1 -- three attempts, output present: only attempt 3 is produced
# ========================================================================== #
def test_b1_only_the_newest_of_three_attempts_is_produced(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", (1, 2, 3))
    rows = _walk(cfg)
    assert len([r for r in rows if r[0] == "pm"]) == 3, rows
    assert _produced(rows, "pm") == {1: False, 2: False, 3: True}, rows


def test_b1_rows_keep_the_five_tuple_shape(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", (1, 2, 3))
    for r in _walk(cfg):
        assert isinstance(r, tuple) and len(r) == 5, r
        assert [type(x) for x in r] == [str, int, int, bool, str], r


# ========================================================================== #
# B2 -- the max is NUMERIC, not lexicographic
# ========================================================================== #
def test_b2_attempt_12_not_attempt_9_is_the_newest(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", range(1, 13))
    rows = _walk(cfg)
    got = _produced(rows, "pm")
    assert len(got) == 12 and sorted(got) == list(range(1, 13)), got
    assert [n for n, p in got.items() if p] == [12], got
    assert got[9] is False, "attempt 9 is only the LEXICOGRAPHIC last filename"
    assert got[10] is False and got[1] is False, got


# ========================================================================== #
# B3 -- no output, or a zero-byte output: nothing is produced
# ========================================================================== #
@pytest.mark.parametrize("out", [None, ""], ids=["missing", "zero-byte"])
def test_b3_without_a_non_empty_output_no_attempt_is_produced(tmp_path, out):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", (1, 2, 3), out=out)
    rows = _walk(cfg)
    assert _produced(rows, "pm") == {1: False, 2: False, 3: False}, rows


# ========================================================================== #
# B4 -- single-attempt runs behave as before
# ========================================================================== #
@pytest.mark.parametrize("out,want", [("out\n", True), (None, False)])
def test_b4_a_single_attempt_reflects_the_output_file(tmp_path, out, want):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", (1,), out=out)
    assert _walk(cfg) == [("pm", 1, 1, want, CLEAN)]


# ========================================================================== #
# B5 -- the max is per (iteration, stage), never per stage or per iteration
# ========================================================================== #
def test_b5_newest_is_taken_per_iteration_and_stage(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", (1, 2, 3))
    _plant(cfg, 1, "engineer", (1,))
    _plant(cfg, 2, "pm", (1,))
    rows = _walk(cfg)
    assert _produced(rows, "engineer", 1) == {1: True}, "per-iteration max would lose it"
    assert _produced(rows, "pm", 2) == {1: True}, "per-stage max would lose it"
    assert _produced(rows, "pm", 1) == {1: False, 2: False, 3: True}, rows
    assert len(rows) == 5, rows


# ========================================================================== #
# B6 -- the row POPULATION is unchanged; only `produced` moved
# ========================================================================== #
def _mixed(cfg):
    _plant(cfg, 2, "pm", (1, 2))
    _plant(cfg, 9, "tester", {1: CLEAN, 2: UNDECODABLE})
    _plant(cfg, 10, "engineer", (1,), out=None)
    (pathlib.Path(cfg.state) / "iter-10" / "notes.txt").write_text("not a log\n")
    (pathlib.Path(cfg.state) / "iter-10" / "engineer.attempt.log").write_text("x\n")


EXPECTED_POPULATION = collections.Counter([
    ("pm", 2, 1, CLEAN), ("pm", 2, 2, CLEAN),
    ("tester", 9, 1, CLEAN), ("tester", 9, 2, ""),
    ("engineer", 10, 1, CLEAN),
])


def test_b6_the_multiset_of_rows_is_unchanged(tmp_path):
    cfg = _cfg(tmp_path)
    _mixed(cfg)
    rows = _walk(cfg)
    got = collections.Counter((r[0], r[1], r[2], r[4]) for r in rows)
    assert got == EXPECTED_POPULATION, rows
    assert _produced(rows, "tester", 9) == {1: False, 2: True}, \
        "an undecodable newest attempt still counts as produced when output exists"
    assert _produced(rows, "engineer", 10) == {1: False}, rows


@pytest.mark.parametrize("limit,iters", [
    (1, {10}), (2, {9, 10}), (3, {2, 9, 10}), (99, {2, 9, 10}),
    (None, {2, 9, 10}), (0, {2, 9, 10}),
])
def test_b6_a_limit_keeps_the_numerically_newest_iterations(tmp_path, limit, iters):
    cfg = _cfg(tmp_path)
    _mixed(cfg)
    rows = _walk(cfg, limit)
    assert {r[1] for r in rows} == iters, rows
    want = collections.Counter(k for k in EXPECTED_POPULATION.elements() if k[1] in iters)
    assert collections.Counter((r[0], r[1], r[2], r[4]) for r in rows) == want


def test_b6_an_unreadable_log_is_yielded_with_empty_text(tmp_path):
    cfg = _cfg(tmp_path)
    d = _plant(cfg, 1, "pm", (1, 2))
    p = d / "pm.attempt1.log"
    os.chmod(p, 0)
    try:
        locked = not os.access(p, os.R_OK)
        rows = _walk(cfg)
    finally:
        os.chmod(p, 0o644)
    assert [(r[2], r[3]) for r in rows] == [(1, False), (2, True)], rows
    if locked:
        assert rows[0][4] == "", rows
    assert rows[1][4] == CLEAN, rows


def test_b6_a_missing_state_dir_yields_nothing(tmp_path):
    cfg = _cfg(tmp_path / "nowhere")
    assert not pathlib.Path(cfg.state).exists()
    assert _walk(cfg) == []
    assert _walk(cfg, 3) == []


# ========================================================================== #
# B7 -- gather_losses now counts the earlier auth-failed attempts
# ========================================================================== #
def test_b7_two_auth_failures_before_a_success_are_two_auth_losses(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", {1: AUTH, 2: AUTH, 3: CLEAN})
    digest = foundry.gather_losses(cfg)
    assert digest.attempts == 3, digest
    assert sum(r.lost for r in digest.rows) == 2, digest
    assert [(r.kind, r.lost) for r in digest.rows] == [(foundry.AUTH_LOSS_KIND, 2)], digest
    assert foundry.AUTH_LOSS_KIND == "auth"


def test_b7_the_same_logs_without_output_lose_all_three(tmp_path):
    """Discrimination: the producing newest attempt is exactly what is spared."""
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", {1: AUTH, 2: AUTH, 3: CLEAN}, out=None)
    digest = foundry.gather_losses(cfg)
    assert digest.attempts == 3 and sum(r.lost for r in digest.rows) == 3, digest


# ========================================================================== #
# B8 -- auth_loss_line stays ACTIVE when the newest iteration had auth losses
# ========================================================================== #
def test_b8_auth_loss_line_is_active_not_already_cleared(tmp_path):
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", {1: AUTH}, out=None)
    _plant(cfg, 3, "pm", {1: AUTH, 2: AUTH, 3: CLEAN})
    line = foundry.auth_loss_line(cfg)
    assert line.startswith(foundry.AUTH_LOSS_PREFIX), line
    assert foundry.AUTH_LOSS_WARN in line, line
    assert foundry.AUTH_LOSS_HEALED not in line, line
    assert "ALREADY CLEARED" not in line, line
    assert "3/4" in line, f"3 of 4 scanned attempts were lost to auth: {line}"
    assert "a HUMAN must re-authenticate" in line, line


def test_b8_a_truly_healed_window_still_says_already_cleared(tmp_path):
    """Discrimination: the HEALED arm is still reachable when the newest
    iteration really had no auth loss."""
    cfg = _cfg(tmp_path)
    _plant(cfg, 1, "pm", {1: AUTH}, out=None)
    _plant(cfg, 3, "pm", {1: CLEAN})
    line = foundry.auth_loss_line(cfg)
    assert foundry.AUTH_LOSS_HEALED in line, line
    assert "1/2" in line, line


# ========================================================================== #
# B9 -- rescues: a killed attempt followed by a retry is LOST, not rescued
# ========================================================================== #
def _row_line(text, stage):
    hits = [ln for ln in text.splitlines() if f"[{stage}]" in ln]
    assert len(hits) == 1, text
    return hits[0]


def test_b9_killed_then_retried_is_lost_and_checkpoint_first_is_rescued(tmp_path):
    cfg = _cfg(tmp_path)
    assert any(t in KILL for t in foundry.ATTEMPT_KILL_TOKENS), foundry.ATTEMPT_KILL_TOKENS
    _plant(cfg, 1, "engineer", {1: KILL, 2: CLEAN})
    _plant(cfg, 2, "tester", {1: KILL})
    s = foundry.gather_rescues(cfg)
    rows = {r.stage: r for r in s.rows}
    e, t = rows["engineer"], rows["tester"]
    assert (e.attempts, e.kills, e.rescued, e.lost) == (2, 1, 0, 1), e
    assert (t.attempts, t.kills, t.rescued, t.lost) == (1, 1, 1, 0), t
    text = s.render()
    assert "kills 1  rescued 0  lost 1" in _row_line(text, "engineer"), text
    assert "kills 1  rescued 1  lost 0" in _row_line(text, "tester"), text


# ========================================================================== #
# B10 -- structure pins and read-only walk
# ========================================================================== #
def test_b10_the_filename_regex_has_one_match_site_inside_the_walker():
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    site = re.compile(r"_ATTEMPT_LOG_RE\.match\(")
    assert len(site.findall(src)) == 1, "exactly ONE _ATTEMPT_LOG_RE.match site"
    walker = inspect.getsource(foundry._walk_attempt_logs)
    assert len(site.findall(walker)) == 1, "the site must live inside _walk_attempt_logs"
    assert inspect.isgeneratorfunction(foundry._walk_attempt_logs)


def test_b10_the_walker_docstring_states_the_newest_attempt_rule():
    doc = (inspect.getdoc(foundry._walk_attempt_logs) or "").lower()
    assert "newest" in doc or "highest" in doc, doc


def test_b10_a_walk_writes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    _mixed(cfg)
    _plant(cfg, 3, "pm", {1: AUTH, 2: AUTH, 3: CLEAN})
    before = _tree(tmp_path)
    _walk(cfg)
    _walk(cfg, 2)
    foundry.gather_losses(cfg)
    foundry.gather_rescues(cfg)
    foundry.auth_loss_line(cfg)
    assert _tree(tmp_path) == before
