"""Black-box behaviour tests for iter 181 -- `doctor`'s `learnings-head:` WARN NAMES the
worst-elided pinned `## Patterns` bullet (label + chars lost + truncated-vs-dropped),
instead of only counting how many bullets were cut.

Spec: products/_platform/state/iter-181/pm.md, Expected Behaviors 1-12.

  losses = head_bullet_losses(head_lines, bullet_cap, head_budget)
  1.  NOTHING ELIDED -> `()`: a within-budget/within-cap head, `[]`, a head with a
      preamble but no column-0 `- ` bullet, and the unbounded `(None, None)` shape.
  2.  FITS-WHOLE FAST PATH -> `()` even when one bullet is far over `bullet_cap`,
      because `_bound_head` emits such a head verbatim (iteration 138's path).
  3.  ONE `HeadBulletLoss` per elided block with exactly the fields
      index/label/raw_chars/elided_chars/kind; FROZEN and value-comparable.
  4.  `elided_chars` = `raw_chars` - delivered: `raw_chars - bullet_cap` when
      truncated (and > 0), `raw_chars` when dropped; `raw_chars` is
      `len("\\n".join(block))` over that block's OWN lines.
  5.  `kind` uses the module tokens `HEAD_LOSS_TRUNCATED` / `HEAD_LOSS_DROPPED`, and a
      budget-refused block is reported DROPPED ONLY, never also truncated.
  6.  Dropped blocks are the head's LAST blocks -- their `index` values are the `d`
      highest, where `d == _bound_head(...)[3]`.
  7.  WORST-FIRST under the TOTAL key `(-elided_chars, index)`, byte-identical across
      three `PYTHONHASHSEED` values for a head holding equal-loss bullets.
  8.  `LearningsHeadAudit.worst_loss` is DEFAULTED to None (the five-keyword
      construction still constructs); it is `losses[0]` exactly when `over_budget`,
      else None; the five pre-existing fields keep their values.
  9.  ORACLE -- truncated/dropped counts and `len(losses)` cannot drift from
      `_bound_head`'s own counts, nor from `learnings_digest`'s
      `> [head bounded: ...]` notice, across several cap/budget pairs.
  10. `label` is single-line, non-empty, whitespace-collapsed, marker-stripped and at
      most `HEAD_BULLET_LABEL_CHARS` chars.
  11. `learnings_head_line(cfg)`: the WARN branch is ONE line still carrying the
      prefix, the WARN token and the existing counts, PLUS the worst loss's label,
      `elided_chars` and `raw_chars`; the OK branch gains no loss clause; a
      missing/unreadable log still returns UNKNOWN; a raising `head_bullet_losses`
      is absorbed into one prefixed line.
  12. The line stays a pure reporter: `doctor` prints exactly ONE `learnings-head:`
      line and its exit code is unchanged by an over-budget head.
  Plus acceptance-criteria oracles: `foundry`/`dispatcher` still import, the five new
  module names exist, `head_bullet_losses` never raises and touches no subprocess/
  filesystem, and no test reads a real gitignored `products/*/LEARNINGS.md`.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-181 PM spec and the product's
OBSERVABLE surface -- importing the module, CALLING its public functions,
`inspect`/`dataclasses` introspection, driving the doctor CLI, and reading files under
`tests/` for CONVENTIONS. The implementation BODIES of foundry.py / dispatcher.py, the
engineer's notes, the reviewer's notes and `git diff` were NOT read. The head-region
rule and the bullet-BLOCK rule are RE-DERIVED here from the spec's own wording
(`_head_text`, `_blocks`), never mirrored from the implementation.

Fully offline and deterministic: synthetic fixture strings and `tmp_path` files only --
no git, no network, no agent run, no sleep, no clock dependence, nothing written outside
`tmp_path`, and NO read of any real gitignored learnings log. The only subprocess is
this same interpreter re-run under three `PYTHONHASHSEED` values (behavior 7).
"""
import contextlib
import dataclasses
import io
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

CAP = foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS      # 800
BUDGET = foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS   # 10000
TRUNC = foundry.HEAD_LOSS_TRUNCATED
DROPPED = foundry.HEAD_LOSS_DROPPED
LABEL_CHARS = foundry.HEAD_BULLET_LABEL_CHARS
NOTICE_RE = re.compile(
    r"^> \[head bounded: (\d+) of (\d+) bullets truncated, (\d+) dropped")


# --------------------------------------------------------------------------
# fixtures + helpers -- RE-DERIVED from the spec's wording
# --------------------------------------------------------------------------
def _bullet(name, n, ch="x"):
    return f"- **{name}** " + ch * n


def _log(head_bullets, *, tail=True):
    """A synthetic learnings log: a `## Patterns` head then chronological lessons."""
    parts = ["## Patterns", ""]
    for b in head_bullets:
        parts += [b, ""]
    if tail:
        parts += ["## Chronological lessons", "", "- [PM iter01] a lesson", ""]
    return "\n".join(parts)


def _head_text(text):
    """The head-region rule, re-derived: the contiguous slice of input lines from the
    `## Patterns` heading up to (exclusive) the first later `## ` heading OR the first
    lesson line (a line left-stripping to `- [`), whichever comes first."""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("## Patterns"):
            start = i
            break
    if start is None:
        return None
    head = [lines[start]]
    for ln in lines[start + 1:]:
        s = ln.lstrip()
        if s.startswith("## ") or s.startswith("- ["):
            break
        head.append(ln)
    return "\n".join(head)


def _head_lines_of(text):
    return _head_text(text).split("\n")


def _blocks(head):
    """The bullet-BLOCK rule, re-derived from the spec: a block OPENS on a head line
    starting with `- ` at COLUMN 0 and runs up to (exclusive) the next such line or the
    end of the head. Preamble prose before the first bullet is not a block."""
    out, cur = [], None
    for ln in head:
        if ln.startswith("- "):
            if cur is not None:
                out.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
    if cur is not None:
        out.append(cur)
    return out


def _notices(out):
    return [ln for ln in out.split("\n") if ln.startswith("> [head bounded:")]


# FITS-WHOLE: one bullet WAY over the per-bullet cap, whole head far under budget.
FITS = _log([_bullet("a", 1500), _bullet("b", 200, "y"), _bullet("c", 200, "z")])
# OVER-BUDGET, truncation only: the verbatim head exceeds the TOTAL budget.
OVER = _log([_bullet("a", 9000), _bullet("b", 700, "y"), _bullet("c", 700, "z")])
# DROPPING: many over-cap bullets -> even after truncation the head must shed some.
DROPPING = _log([_bullet(f"b{i}", 900) for i in range(20)])
# UNDER: nothing over the cap and the whole head far under budget.
UNDER = _log([_bullet("a", 100), _bullet("b", 100, "y")])
# PREAMBLE_ONLY: a head region with prose but no column-0 bullet at all.
PREAMBLE_ONLY = "\n".join(["## Patterns", "", "just prose, no bullets", "",
                           "## Chronological lessons", "", "- [PM iter01] x", ""])

# The fixtures' PREMISES are asserted, never assumed (a fixture that silently stops
# exercising its branch is the failure mode this guards).
assert len(_head_text(FITS)) <= BUDGET, len(_head_text(FITS))
assert any(len("\n".join(b)) > CAP for b in _blocks(_head_lines_of(FITS)))
assert len(_head_text(OVER)) > BUDGET, len(_head_text(OVER))
assert len(_head_text(DROPPING)) > BUDGET, len(_head_text(DROPPING))
assert len(_head_text(UNDER)) <= BUDGET, len(_head_text(UNDER))
assert all(len("\n".join(b)) <= CAP for b in _blocks(_head_lines_of(UNDER)))
assert _blocks(_head_lines_of(PREAMBLE_ONLY)) == [], _blocks(_head_lines_of(PREAMBLE_ONLY))
assert len(_blocks(_head_lines_of(DROPPING))) == 20


def _write_cfg(tmp_path, **over):
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


def _cfg_for(tmp_path, text=None, *, learnings=None, name="L.md"):
    """A ProductConfig whose `learnings` points into tmp_path (NEVER a real log)."""
    if learnings is None:
        target = tmp_path / name
        target.write_text(text if text is not None else "")
        learnings = str(target)
    return foundry.load_config(str(_write_cfg(tmp_path, learnings=learnings)))


class _Chk:
    """Minimal stand-in check result for the doctor-CLI guards (iter-136/145)."""

    def __init__(self, name, ok, detail="detail-text"):
        self.name = name
        self.ok = ok
        self.detail = detail


def _stub_checks(monkeypatch, ok=True):
    for nm in ("power", "agent", "uv", "remote"):
        monkeypatch.setattr(foundry, f"check_{nm}", lambda *a, _n=nm, **k: _Chk(_n, ok))


def _head_report_lines(out):
    return [ln for ln in out.splitlines() if foundry.LEARNINGS_HEAD_PREFIX in ln]


def _doctor_out(cfg):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.run_doctor_cli(cfg)
    return rc, buf.getvalue()


# --------------------------------------------------------------------- Behavior 1
def test_b1_a_head_within_both_bounds_reports_no_losses():
    assert foundry.head_bullet_losses(_head_lines_of(UNDER), CAP, BUDGET) == ()


def test_b1_empty_head_and_bulletless_head_report_no_losses():
    assert foundry.head_bullet_losses([], CAP, BUDGET) == ()
    assert foundry.head_bullet_losses(_head_lines_of(PREAMBLE_ONLY), CAP, BUDGET) == ()
    # A bullet INDENTED off column 0 is preamble, not a block -- even when huge.
    assert foundry.head_bullet_losses(
        ["## Patterns", "", "  - indented " + "q" * 5000], 10, 10) == ()


def test_b1_the_unbounded_call_shape_can_never_report_a_loss():
    for text in (FITS, OVER, DROPPING, UNDER):
        assert foundry.head_bullet_losses(_head_lines_of(text), None, None) == (), text[:40]


# --------------------------------------------------------------------- Behavior 2
def test_b2_fits_whole_head_reports_no_loss_despite_an_over_cap_bullet():
    """Iteration 138's fast path: raw head <= budget is emitted VERBATIM, so an
    over-cap bullet inside it loses nothing and must not be reported."""
    head = _head_lines_of(FITS)
    assert any(len("\n".join(b)) > CAP for b in _blocks(head)), "fixture stopped biting"
    assert foundry.head_bullet_losses(head, CAP, BUDGET) == ()
    # ... and the prompt path agrees it clipped nothing.
    assert foundry._bound_head(head, CAP, BUDGET)[2:] == (0, 0)


def test_b2_the_boundary_is_inclusive_at_exactly_the_budget():
    head = _head_lines_of(FITS)
    raw = len("\n".join(head))
    assert foundry.head_bullet_losses(head, CAP, raw) == (), "raw == budget must FIT"
    assert foundry.head_bullet_losses(head, CAP, raw - 1) != (), "raw > budget must clip"


# --------------------------------------------------------------------- Behavior 3
def test_b3_one_loss_per_elided_block_with_exactly_the_five_fields():
    names = [f.name for f in dataclasses.fields(foundry.HeadBulletLoss)]
    assert names == ["index", "label", "raw_chars", "elided_chars", "kind"], names
    losses = foundry.head_bullet_losses(_head_lines_of(DROPPING), CAP, BUDGET)
    seg, _total, tr, dr = foundry._bound_head(_head_lines_of(DROPPING), CAP, BUDGET)
    assert len(losses) == tr + dr == 20, (len(losses), tr, dr)
    assert len({l.index for l in losses}) == len(losses), "duplicate index"
    for l in losses:
        assert isinstance(l.index, int) and 1 <= l.index <= 20, l
        assert isinstance(l.label, str) and isinstance(l.kind, str), l
        assert isinstance(l.raw_chars, int) and isinstance(l.elided_chars, int), l


def test_b3_the_loss_type_is_frozen_and_value_comparable():
    a = foundry.HeadBulletLoss(index=1, label="L", raw_chars=10, elided_chars=2,
                               kind=TRUNC)
    b = foundry.HeadBulletLoss(index=1, label="L", raw_chars=10, elided_chars=2,
                               kind=TRUNC)
    assert a == b and a is not b
    assert foundry.HeadBulletLoss.__dataclass_params__.frozen is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.index = 2


# --------------------------------------------------------------------- Behavior 4
def test_b4_elided_chars_is_raw_minus_what_was_delivered():
    for text in (OVER, DROPPING):
        head = _head_lines_of(text)
        blocks = _blocks(head)
        for l in foundry.head_bullet_losses(head, CAP, BUDGET):
            raw = len("\n".join(blocks[l.index - 1]))
            assert l.raw_chars == raw, (l, raw)
            if l.kind == TRUNC:
                assert l.elided_chars == l.raw_chars - CAP, l
                assert l.elided_chars > 0, l
            else:
                assert l.elided_chars == l.raw_chars, l


def test_b4_raw_chars_counts_a_multi_line_block_including_its_blank_lines():
    head = ["## Patterns", "",
            "- **multi** " + "x" * 300, "continuation line", "",
            "- **other** " + "y" * 300, ""]
    blocks = _blocks(head)
    assert len(blocks) == 2 and len(blocks[0]) == 3, blocks
    losses = foundry.head_bullet_losses(head, 40, 60)
    assert len(losses) == 2, losses
    by_index = {l.index: l for l in losses}
    for i, blk in enumerate(blocks, start=1):
        assert by_index[i].raw_chars == len("\n".join(blk)), (i, by_index[i])


# --------------------------------------------------------------------- Behavior 5
def test_b5_kind_uses_the_module_tokens_only():
    assert TRUNC != DROPPED
    for text in (OVER, DROPPING):
        for l in foundry.head_bullet_losses(_head_lines_of(text), CAP, BUDGET):
            assert l.kind in (TRUNC, DROPPED), l


def test_b5_a_dropped_block_is_reported_dropped_only():
    head = _head_lines_of(DROPPING)
    losses = foundry.head_bullet_losses(head, CAP, BUDGET)
    _seg, _t, tr, dr = foundry._bound_head(head, CAP, BUDGET)
    assert dr > 0 and tr > 0, (tr, dr)
    dropped_ix = {l.index for l in losses if l.kind == DROPPED}
    trunc_ix = {l.index for l in losses if l.kind == TRUNC}
    assert dropped_ix and trunc_ix
    assert dropped_ix.isdisjoint(trunc_ix), (dropped_ix & trunc_ix)
    assert len(dropped_ix) == dr and len(trunc_ix) == tr, (len(dropped_ix), dr)


# --------------------------------------------------------------------- Behavior 6
def test_b6_dropped_blocks_are_the_heads_last_blocks():
    head = _head_lines_of(DROPPING)
    n = len(_blocks(head))
    losses = foundry.head_bullet_losses(head, CAP, BUDGET)
    d = foundry._bound_head(head, CAP, BUDGET)[3]
    assert d > 0, "fixture must drop"
    dropped_ix = sorted(l.index for l in losses if l.kind == DROPPED)
    assert dropped_ix == list(range(n - d + 1, n + 1)), (dropped_ix, n, d)


# --------------------------------------------------------------------- Behavior 7
def test_b7_losses_are_sorted_worst_first_then_by_index():
    for text, cap, budget in ((OVER, CAP, BUDGET), (DROPPING, CAP, BUDGET),
                              (DROPPING, 100, 900)):
        losses = foundry.head_bullet_losses(_head_lines_of(text), cap, budget)
        keys = [(-l.elided_chars, l.index) for l in losses]
        assert keys == sorted(keys), (text[:20], keys)


def test_b7_equal_losses_are_ordered_by_ascending_index():
    losses = foundry.head_bullet_losses(_head_lines_of(DROPPING), CAP, BUDGET)
    groups = {}
    for l in losses:
        groups.setdefault(l.elided_chars, []).append(l.index)
    assert any(len(v) > 1 for v in groups.values()), "fixture has no equal-loss pair"
    for size, ixs in groups.items():
        assert ixs == sorted(ixs), (size, ixs)


def test_b7_order_is_identical_across_three_python_hash_seeds():
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "import foundry\n"
        "head=['## Patterns','']\n"
        "for i in range(20):\n"
        "    head += ['- **b%%d** ' %% i + 'x'*900, '']\n"
        "print([(l.index, l.elided_chars, l.kind) for l in "
        "foundry.head_bullet_losses(head, %d, %d)])\n" % (str(_ROOT), CAP, BUDGET)
    )
    outs = []
    for seed in ("0", "1", "42"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True,
                           text=True, env=env, cwd=str(_ROOT), timeout=120)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout.strip())
    assert outs[0] and outs[0].count("(") >= 2, outs[0]
    assert len(set(outs)) == 1, outs


# --------------------------------------------------------------------- Behavior 8
def test_b8_worst_loss_is_defaulted_so_the_five_keyword_construction_still_works():
    fields = {f.name: f for f in dataclasses.fields(foundry.LearningsHeadAudit)}
    assert "worst_loss" in fields
    assert fields["worst_loss"].default is None, fields["worst_loss"].default
    a = foundry.LearningsHeadAudit(bullets=1, raw_chars=2, truncated=0, dropped=0,
                                   over_budget=False)
    assert a.worst_loss is None
    assert foundry.LearningsHeadAudit.__dataclass_params__.frozen is True


def test_b8_audit_reports_the_worst_loss_exactly_when_over_budget():
    for text in (OVER, DROPPING):
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        losses = foundry.head_bullet_losses(_head_lines_of(text), CAP, BUDGET)
        assert a.over_budget is True, a
        assert losses, text[:20]
        assert a.worst_loss == losses[0], (a.worst_loss, losses[0])
    for text in (FITS, UNDER, PREAMBLE_ONLY, "", "no patterns heading at all"):
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        assert a.over_budget is False, (text[:20], a)
        assert a.worst_loss is None, (text[:20], a)


def test_b8_the_five_pre_existing_fields_keep_their_values():
    for text in (FITS, OVER, DROPPING, UNDER, PREAMBLE_ONLY, ""):
        head = _head_text(text)
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        if head is None:
            continue
        lines = head.split("\n")
        _seg, _t, tr, dr = foundry._bound_head(lines, CAP, BUDGET)
        assert a.bullets == len(_blocks(lines)), (text[:20], a)
        assert a.raw_chars == len(head), (text[:20], a)
        assert (a.truncated, a.dropped) == (tr, dr), (text[:20], a)
        assert a.over_budget is bool(tr or dr), (text[:20], a)


# --------------------------------------------------------------------- Behavior 9
PAIRS = ((CAP, BUDGET), (100, 900), (200, 2000), (CAP, 3000))


def test_b9_loss_counts_never_drift_from_the_prompt_bounds():
    for text in (FITS, OVER, DROPPING, UNDER):
        for cap, budget in PAIRS:
            head = _head_lines_of(text)
            losses = foundry.head_bullet_losses(head, cap, budget)
            _seg, _t, tr, dr = foundry._bound_head(head, cap, budget)
            got_t = sum(1 for l in losses if l.kind == TRUNC)
            got_d = sum(1 for l in losses if l.kind == DROPPED)
            assert (got_t, got_d) == (tr, dr), (text[:20], cap, budget, got_t, tr)
            assert len(losses) == tr + dr, (text[:20], cap, budget, losses)


def test_b9_the_digest_notice_still_reports_the_same_three_numbers():
    """`_bound_head` is behavior-PRESERVED: the rendered `> [head bounded: ...]`
    notice and the loss report agree on truncated/dropped for the same bounds."""
    for text in (OVER, DROPPING):
        for cap, budget in ((CAP, BUDGET), (100, 900)):
            out = foundry.learnings_digest(text, 12, None, None, cap, budget)
            notices = _notices(out)
            assert len(notices) == 1, (text[:20], notices)
            m = NOTICE_RE.match(notices[0])
            assert m, notices[0]
            n_trunc, n_bullets, n_drop = (int(m.group(1)), int(m.group(2)),
                                          int(m.group(3)))
            head = _head_lines_of(text)
            _seg, _t, tr, dr = foundry._bound_head(head, cap, budget)
            assert (n_trunc, n_drop) == (tr, dr), (notices[0], tr, dr)
            assert n_bullets == len(_blocks(head)), (notices[0], len(_blocks(head)))
            losses = foundry.head_bullet_losses(head, cap, budget)
            assert len(losses) == n_trunc + n_drop, (notices[0], losses)


def test_b9_a_fitting_head_still_renders_no_notice_at_all():
    out = foundry.learnings_digest(FITS, 12, None, None, CAP, BUDGET)
    assert _notices(out) == []
    assert foundry.head_bullet_losses(_head_lines_of(FITS), CAP, BUDGET) == ()


# -------------------------------------------------------------------- Behavior 10
def test_b10_label_is_single_line_bounded_and_marker_stripped():
    head = ["## Patterns", "",
            "-   **A   B**\tC " + "z" * 300, "continuation", "",
            "- short one " + "y" * 300, ""]
    losses = foundry.head_bullet_losses(head, 40, 60)
    assert len(losses) == 2, losses
    for l in losses:
        assert l.label, l
        assert "\n" not in l.label, repr(l.label)
        assert len(l.label) <= LABEL_CHARS, (len(l.label), LABEL_CHARS)
        assert not l.label.startswith("- "), repr(l.label)
        assert "  " not in l.label and "\t" not in l.label, repr(l.label)
    by_index = {l.index: l for l in losses}
    assert by_index[1].label.startswith("**A B** C"), repr(by_index[1].label)
    assert by_index[2].label.startswith("short one"), repr(by_index[2].label)


def test_b10_every_real_bullet_gets_a_non_empty_label():
    for text in (OVER, DROPPING):
        for l in foundry.head_bullet_losses(_head_lines_of(text), CAP, BUDGET):
            assert l.label.strip() == l.label and l.label, repr(l.label)


# -------------------------------------------------------------------- Behavior 11
def test_b11_warn_branch_names_the_worst_bullet_and_keeps_its_counts(tmp_path):
    for text in (OVER, DROPPING):
        cfg = _cfg_for(tmp_path, text, name=f"L-{len(text)}.md")
        line = foundry.learnings_head_line(cfg)
        a = foundry.learnings_head_audit(text, CAP, BUDGET)
        worst = a.worst_loss
        assert "\n" not in line, repr(line)
        assert foundry.LEARNINGS_HEAD_PREFIX in line, line
        assert foundry.LEARNINGS_HEAD_WARN in line, line
        # existing counts survive
        assert str(a.raw_chars) in line and str(a.bullets) in line, line
        assert f"{a.truncated} bullet(s) truncated" in line, line
        assert f"{a.dropped} dropped" in line, line
        # ... and the worst loser is NAMED
        assert worst is not None
        assert worst.label in line, (worst.label, line)
        assert str(worst.elided_chars) in line, (worst.elided_chars, line)
        assert str(worst.raw_chars) in line, (worst.raw_chars, line)
        assert worst.kind in line, (worst.kind, line)


def test_b11_ok_branch_gains_no_loss_clause(tmp_path):
    for name, text in (("fits", FITS), ("under", UNDER)):
        line = foundry.learnings_head_line(_cfg_for(tmp_path, text, name=f"{name}.md"))
        assert "\n" not in line and line.startswith(foundry.LEARNINGS_HEAD_PREFIX), line
        assert foundry.LEARNINGS_HEAD_WARN not in line, line
        assert "worst" not in line.lower(), line
        assert "losing" not in line.lower(), line


def test_b11_missing_log_still_returns_the_unknown_line(tmp_path):
    line = foundry.learnings_head_line(
        _cfg_for(tmp_path, learnings=str(tmp_path / "nope.md")))
    assert line and "\n" not in line, repr(line)
    assert line.startswith(foundry.LEARNINGS_HEAD_PREFIX), line
    assert "UNKNOWN" in line, line
    assert foundry.LEARNINGS_HEAD_WARN not in line, line


def test_b11_a_raising_loss_helper_is_absorbed(tmp_path, monkeypatch):
    cfg = _cfg_for(tmp_path, DROPPING)

    def boom(*a, **k):
        raise RuntimeError("scripted loss failure")

    monkeypatch.setattr(foundry, "head_bullet_losses", boom)
    line = foundry.learnings_head_line(cfg)      # must NOT propagate
    assert line and "\n" not in line, repr(line)
    assert foundry.LEARNINGS_HEAD_PREFIX in line, line


# -------------------------------------------------------------------- Behavior 12
def test_b12_doctor_prints_exactly_one_head_line_naming_the_worst(tmp_path,
                                                                 monkeypatch):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: "lag line")
    cfg = _cfg_for(tmp_path, DROPPING)
    rc, out = _doctor_out(cfg)
    lines = _head_report_lines(out)
    assert len(lines) == 1, f"expected exactly ONE head line:\n{out}"
    worst = foundry.learnings_head_audit(DROPPING, CAP, BUDGET).worst_loss
    assert worst.label in lines[0], (worst.label, lines[0])
    assert foundry.LEARNINGS_HEAD_WARN in lines[0], lines[0]
    assert rc == 0, out


def test_b12_an_over_budget_head_does_not_change_the_exit_code(tmp_path, monkeypatch):
    codes = {}
    for label, text in (("over", DROPPING), ("ok", UNDER)):
        for ok in (True, False):
            _stub_checks(monkeypatch, ok=ok)
            monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: "lag line")
            cfg = _cfg_for(tmp_path, text, name=f"L-{label}-{ok}.md")
            codes[(label, ok)] = _doctor_out(cfg)[0]
    assert codes[("over", True)] == codes[("ok", True)] == 0, codes
    assert codes[("over", False)] == codes[("ok", False)] == 1, codes


def test_b12_doctor_is_routable_and_survives_a_raising_loss_helper(tmp_path,
                                                                  monkeypatch):
    _stub_checks(monkeypatch)
    monkeypatch.setattr(foundry, "live_lag_line", lambda *a, **k: "lag line")

    def boom(*a, **k):
        raise RuntimeError("scripted loss failure")

    monkeypatch.setattr(foundry, "head_bullet_losses", boom)
    cfg_path = _write_cfg(tmp_path, learnings=str(tmp_path / "L.md"))
    (tmp_path / "L.md").write_text(DROPPING)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.main(["doctor", "--config", str(cfg_path)])
    out = buf.getvalue()
    assert rc == 0, out
    assert len(_head_report_lines(out)) == 1, out


# ------------------------------------------------- acceptance-criteria oracles
def test_ac_modules_import_and_the_new_module_names_exist():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
    for nm in ("head_bullet_losses", "HeadBulletLoss", "HEAD_LOSS_TRUNCATED",
               "HEAD_LOSS_DROPPED", "HEAD_BULLET_LABEL_CHARS"):
        assert hasattr(foundry, nm), nm
    assert isinstance(LABEL_CHARS, int) and LABEL_CHARS > 0
    # out of scope this iteration: the prompt bounds keep their shipped values
    assert (CAP, BUDGET) == (800, 10000), (CAP, BUDGET)


def test_ac_head_bullet_losses_is_pure_and_never_raises(monkeypatch, tmp_path):
    def no_subprocess(*a, **k):      # a call would prove impurity
        raise AssertionError("head_bullet_losses ran a subprocess")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    monkeypatch.setattr(subprocess, "check_output", no_subprocess)
    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    weird = [
        [], [""], ["- "], ["-"], ["## Patterns"], ["- x" * 5],
        ["- a", "", "- b"], ["   ", "\t", "- \u00e9" * 300],
        _head_lines_of(DROPPING),
    ]
    for head in weird:
        for cap, budget in ((None, None), (0, 0), (1, 1), (CAP, BUDGET), (-5, -5)):
            out = foundry.head_bullet_losses(head, cap, budget)
            assert isinstance(out, tuple), (head, cap, budget, out)
    # deterministic: the same input twice gives an EQUAL tuple
    h = _head_lines_of(DROPPING)
    assert foundry.head_bullet_losses(h, CAP, BUDGET) == \
        foundry.head_bullet_losses(h, CAP, BUDGET)
    assert sorted(p.name for p in tmp_path.iterdir()) == before, "wrote a file"


def test_ac_the_block_split_is_shared_not_copied():
    """One shared splitter: the helper both paths use segments a head into a leading
    PREAMBLE segment plus the column-0 `- ` bullet blocks this test re-derives from the
    spec -- so the loss report and the prompt path cannot disagree about block identity.
    (Observed contract, not source: the first segment may be preamble, which is why the
    1-based `index` counts BULLET blocks only.)"""
    assert hasattr(foundry, "_split_head_blocks"), "no shared splitter"
    for text in (FITS, OVER, DROPPING, UNDER, PREAMBLE_ONLY):
        head = _head_lines_of(text)
        preamble, blocks = foundry._split_head_blocks(head)
        assert [list(b) for b in blocks] == _blocks(head), (text[:20], blocks)
        assert all(b and b[0].startswith("- ") for b in blocks), blocks
        # every head line is accounted for exactly once, in document order
        flat = list(preamble) + [ln for b in blocks for ln in b]
        assert flat == head, (text[:20], flat[:3], head[:3])


def test_ac_every_fixture_log_lives_under_tmp_path(tmp_path):
    """Fixture provenance, mechanically: the only log this module can audit is one it
    just wrote under `tmp_path`, so a fresh clone (no gitignored state) behaves the
    same. Guards iteration 155's post-release BROKEN mode."""
    cfg = _cfg_for(tmp_path, DROPPING)
    target = pathlib.Path(cfg.learnings).resolve()
    assert target.is_relative_to(tmp_path.resolve()), target
    assert target.read_text() == DROPPING
    assert foundry.LEARNINGS_HEAD_WARN in foundry.learnings_head_line(cfg)
