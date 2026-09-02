"""Iteration 218 behaviors: `pm_recoverable_block` -- a retry-scoped, bounded,
report-only PM-prompt seam over the shipped `recoverable` verb.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-218 PM spec's Expected
Behaviors 1-8 and its Acceptance Criteria, the `tests/` conventions (esp.
tests/test_iter188_behavior.py for the `_write_cfg`/`_cfg`/`_prompt` fixture shape
and tests/test_iter208_behavior.py for the README dormancy + `ast` census pattern),
the TRACKED `README.md`, and the product's OBSERVABLE behaviour established by
CALLING its public functions and reading their return values. The engineer's notes,
the reviewer's notes and `git diff` were NOT read, and `foundry.py` was NOT read as
source for design -- it is opened here only as `ast` INPUT, because Behavior 7 and
Behavior 8 are themselves structural claims about the shipped module.

Fully offline and deterministic: `gather_recoverable` is scripted via monkeypatch in
every assertion that needs rows, summaries are built with the shipped
`recoverable_summary`/`RecoverableRow` constructors, and every fixture is a literal
or a `tmp_path` artifact -- never the ambient gitignored tree. No real subprocess,
git or network call is made. No absolute machine path appears in this file (the
iter-205 revert was caused by exactly such a literal in a patch-path fixture).
"""
import ast
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import foundry  # noqa: E402

THIS_ITER = 218
NON_PM_STAGES = ("engineer", "reviewer", "tester", "final", "pm_scout")
ALL_STAGES = ("pm",) + NON_PM_STAGES
README_ITEM = 53

# a RELATIVE patch path -- never an absolute machine path (iter-205 revert cause)
PRESERVED_PATH = "products/demoprod/state/iter-217/REVERTED_WORK_iter217.patch"
IN_FLIGHT_PATH = "products/demoprod/state/iter-218/IMPLEMENTATION.patch"
BASE_SHA = "0123abc"


# --------------------------------------------------------------------------
# fixtures -- mirror tests/test_iter188_behavior.py
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, sub="p", **over):
    root = pathlib.Path(tmp_path) / sub
    root.mkdir(parents=True, exist_ok=True)
    (root / "repo").mkdir(exist_ok=True)
    (root / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (root / "ROADMAP.md").write_text("- a roadmap item\n", encoding="utf-8")
    data = {
        "name": "demoprod",
        "repo": str(root / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(root / "VISION.md"),
        "roadmap": str(root / "ROADMAP.md"),
        "work_root": str(root / "work"),
    }
    data.update(over)
    p = root / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _cfg(tmp_path, sub="p", **over):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, sub=sub, **over)))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text("## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
                  encoding="utf-8")
    return cfg


def _row(path, kind, verdict, reasons=()):
    return foundry.RecoverableRow(path=path, kind=kind, verdict=verdict,
                                  reasons=tuple(reasons))


def _preserved_summary():
    rows = (
        _row(PRESERVED_PATH, foundry.RECOVERABLE_KIND_PRESERVED,
             foundry.RECOVERABLE_VERDICT_THREE_WAY, ("patch does not apply",)),
        _row(IN_FLIGHT_PATH, foundry.RECOVERABLE_KIND_IN_FLIGHT,
             foundry.RECOVERABLE_VERDICT_BLOCKED, ("already exists",)),
    )
    return foundry.recoverable_summary(rows, BASE_SHA)


def _in_flight_only_summary():
    rows = (_row(IN_FLIGHT_PATH, foundry.RECOVERABLE_KIND_IN_FLIGHT,
                 foundry.RECOVERABLE_VERDICT_BLOCKED, ("already exists",)),)
    return foundry.recoverable_summary(rows, BASE_SHA)


def _empty_summary():
    return foundry.recoverable_summary((), BASE_SHA)


class _Recorder:
    """A scripted `gather_recoverable` that records every call."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, cfg, *a, **kw):
        self.calls.append((a, kw))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _script(monkeypatch, result):
    rec = _Recorder(result)
    monkeypatch.setattr(foundry, "gather_recoverable", rec)
    return rec


def _prompt(cfg, stage):
    it_dir = pathlib.Path(cfg.work_root) / "state" / ("iter-%d" % THIS_ITER)
    it_dir.mkdir(parents=True, exist_ok=True)
    return foundry.build_prompt(cfg, THIS_ITER, stage, "%s.md" % stage,
                                it_dir / ("%s.md" % stage), it_dir, "extra!")


# --------------------------------------------------------------------------
# Behavior 1 -- every non-`pm` stage gets exactly ""
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stage", NON_PM_STAGES)
def test_b1_non_pm_stage_returns_empty_and_never_gathers(tmp_path, monkeypatch, stage):
    cfg = _cfg(tmp_path)
    rec = _script(monkeypatch, _preserved_summary())
    assert foundry.pm_recoverable_block(cfg, stage) == "", (
        "stage %r must render nothing" % stage)
    assert rec.calls == [], (
        "stage %r must not even gather -- saw %r" % (stage, rec.calls))


# --------------------------------------------------------------------------
# Behavior 2 -- a window with NO preserved rows renders nothing
# --------------------------------------------------------------------------
@pytest.mark.parametrize("summary_factory,label", [
    (_empty_summary, "empty window"),
    (_in_flight_only_summary, "in-flight-only window"),
])
def test_b2_no_preserved_rows_renders_nothing(tmp_path, monkeypatch,
                                              summary_factory, label):
    cfg = _cfg(tmp_path)
    summary = summary_factory()
    assert summary.preserved_rows == (), "fixture precondition: no preserved rows"
    _script(monkeypatch, summary)
    assert foundry.pm_recoverable_block(cfg, "pm") == "", (
        "%s must render nothing" % label)


def test_b2_in_flight_only_still_renders_a_nonempty_report(tmp_path):
    """Precondition guard: the SUMMARY is non-empty, so "" is the seam's choice."""
    summary = _in_flight_only_summary()
    assert summary.render().strip() != "", (
        "vacuous: if render() were empty the b2 assertion proves nothing")
    assert summary.in_flight == 1


# --------------------------------------------------------------------------
# Behavior 3 -- a preserved row reaches the pm prompt block verbatim
# --------------------------------------------------------------------------
def test_b3_preserved_row_block_contains_render_verbatim(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    summary = _preserved_summary()
    assert len(summary.preserved_rows) == 1, "fixture precondition"
    _script(monkeypatch, summary)
    block = foundry.pm_recoverable_block(cfg, "pm")
    assert block.strip() != "", "a preserved row must render a block"
    rendered = summary.render()
    assert rendered in block, (
        "render() must reach the prompt VERBATIM; block=%r" % block)
    for needed in ("  base: %s" % BASE_SHA,
                   "  preserved 1",
                   "[%s] %s" % (foundry.RECOVERABLE_VERDICT_THREE_WAY,
                                PRESERVED_PATH),
                   "reasons: patch does not apply"):
        assert needed in block, "block is missing %r" % needed


# --------------------------------------------------------------------------
# Behavior 4 -- a fixed module-level LABEL precedes the rendered report
# --------------------------------------------------------------------------
def test_b4_label_constant_is_module_level_and_leads_the_block(tmp_path, monkeypatch):
    label = getattr(foundry, "PM_RECOVERABLE_LABEL", None)
    assert isinstance(label, str) and label.strip() != "", (
        "PM_RECOVERABLE_LABEL must be a non-empty module-level str, saw %r" % (label,))
    cfg = _cfg(tmp_path)
    summary = _preserved_summary()
    _script(monkeypatch, summary)
    block = foundry.pm_recoverable_block(cfg, "pm")
    assert label in block, "the label must reach the block"
    assert block.index(label) < block.index(summary.render()), (
        "the label must come BEFORE the rendered report")


# --------------------------------------------------------------------------
# Behavior 5 -- any exception degrades to exactly ""
# --------------------------------------------------------------------------
@pytest.mark.parametrize("exc", [
    RuntimeError("boom"),
    OSError("unreadable state dir"),
    ValueError("malformed"),
])
def test_b5_any_gather_exception_degrades_to_empty(tmp_path, monkeypatch, exc):
    cfg = _cfg(tmp_path)
    _script(monkeypatch, exc)
    assert foundry.pm_recoverable_block(cfg, "pm") == "", (
        "%r must degrade to empty, never propagate" % exc)


def test_b5_a_raising_gather_does_not_break_the_pm_prompt(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _script(monkeypatch, RuntimeError("boom"))
    prompt = _prompt(cfg, "pm")
    assert "- Iteration number for file naming:" in prompt


# --------------------------------------------------------------------------
# Behavior 6 -- gathered ONCE, by bare module name, with limit=PM_RECOVERABLE_LIMIT
# --------------------------------------------------------------------------
def test_b6_limit_constant_is_a_module_level_positive_int():
    limit = getattr(foundry, "PM_RECOVERABLE_LIMIT", None)
    assert isinstance(limit, int) and not isinstance(limit, bool), (
        "PM_RECOVERABLE_LIMIT must be an int, saw %r" % (limit,))
    assert limit > 0, "PM_RECOVERABLE_LIMIT must be positive, saw %r" % (limit,)


def _limit_of(call):
    a, kw = call
    if "limit" in kw:
        return kw["limit"]
    assert a, "gather_recoverable got no limit at all: %r" % (call,)
    return a[0]


def test_b6_gathers_exactly_once_with_the_constant(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rec = _script(monkeypatch, _preserved_summary())
    foundry.pm_recoverable_block(cfg, "pm")
    assert len(rec.calls) == 1, (
        "exactly ONE gather per block, saw %d" % len(rec.calls))
    assert _limit_of(rec.calls[0]) == foundry.PM_RECOVERABLE_LIMIT


def test_b6_limit_is_read_at_call_time(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rec = _script(monkeypatch, _preserved_summary())
    monkeypatch.setattr(foundry, "PM_RECOVERABLE_LIMIT", 7)
    foundry.pm_recoverable_block(cfg, "pm")
    assert _limit_of(rec.calls[0]) == 7, (
        "the limit must be read at CALL time, not captured at def time")


def test_b6_seam_is_called_by_bare_module_name(tmp_path, monkeypatch):
    """monkeypatching the module attribute must actually bite."""
    cfg = _cfg(tmp_path)
    _script(monkeypatch, _empty_summary())
    assert foundry.pm_recoverable_block(cfg, "pm") == "", (
        "a monkeypatched gather_recoverable did not take effect -- the seam is "
        "not called by bare module name")


# --------------------------------------------------------------------------
# Behavior 7 -- build_prompt consumes the seam once for EVERY stage
# --------------------------------------------------------------------------
def test_b7_build_prompt_body_calls_the_seam_exactly_once():
    src = (REPO_ROOT / "foundry.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "build_prompt"]
    assert len(fns) == 1, "expected exactly one build_prompt def, saw %d" % len(fns)
    names = [n.func.id for n in ast.walk(fns[0])
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert names.count("pm_recoverable_block") == 1, (
        "build_prompt must call pm_recoverable_block exactly once, saw %d"
        % names.count("pm_recoverable_block"))
    assert names.count("pm_gap_block") == 1, "pm_gap_block call site must survive"


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_b7_every_stage_consumes_the_seam_exactly_once(tmp_path, monkeypatch, stage):
    cfg = _cfg(tmp_path, sub="once-%s" % stage)
    seen = []

    def _seam(c, s):
        seen.append(s)
        return ""

    monkeypatch.setattr(foundry, "pm_recoverable_block", _seam)
    _prompt(cfg, stage)
    assert seen == [stage], (
        "stage %r must consume the seam exactly once with its own stage name, "
        "saw %r" % (stage, seen))


@pytest.mark.parametrize("stage", NON_PM_STAGES)
def test_b7_non_pm_prompt_is_byte_identical_with_the_seam_stubbed_empty(
        tmp_path, monkeypatch, stage):
    """The LIVE seam and a stubbed-to-"" seam must render the same non-pm prompt.

    Asserting the stub alone would only prove the stub works; this compares the
    shipped path (which really runs gather_recoverable) against "".
    """
    cfg = _cfg(tmp_path, sub="twin-%s" % stage)
    live = _prompt(cfg, stage)
    monkeypatch.setattr(foundry, "pm_recoverable_block", lambda c, s: "")
    stubbed = _prompt(cfg, stage)
    assert live == stubbed, (
        "stage %r prompt changed when the seam was stubbed to empty" % stage)


def test_b7_tmp_path_cfg_makes_the_live_seam_empty(tmp_path):
    """Acceptance: existing build_prompt fixtures are tmp_path-based, so the live
    seam returns "" for them -- verified, not assumed."""
    cfg = _cfg(tmp_path, sub="ambient")
    for stage in ALL_STAGES:
        assert foundry.pm_recoverable_block(cfg, stage) == "", (
            "a tmp_path cfg must hold no preserved patches (stage %r)" % stage)


def test_b7_block_ends_with_exactly_one_trailing_newline(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _script(monkeypatch, _preserved_summary())
    block = foundry.pm_recoverable_block(cfg, "pm")
    assert block.endswith("\n"), "block must end with a newline"
    assert not block.endswith("\n\n"), (
        "block must end with EXACTLY one newline, saw %r" % block[-4:])


def test_b7_iteration_line_keeps_its_own_line_when_the_block_is_present(
        tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _script(monkeypatch, _preserved_summary())
    prompt = _prompt(cfg, "pm")
    assert foundry.PM_RECOVERABLE_LABEL in prompt, "the block must reach the prompt"
    marker = "- Iteration number for file naming:"
    assert any(ln.startswith(marker) for ln in prompt.splitlines()), (
        "%r must start its own line" % marker)


# --------------------------------------------------------------------------
# Behavior 8 -- DOC-TRUTH BRAKE for README item 53 (two-sided)
# --------------------------------------------------------------------------
def _readme_text():
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _denials_in(text):
    low = text.lower()
    return [p for p in foundry.DORMANCY_DENIAL_PHRASES if p in low]


def test_b8_readme_item_53_entry_is_non_empty():
    entry = foundry.dormancy_entry_text(_readme_text(), README_ITEM)
    assert entry.strip() != "", (
        "item %d slice is EMPTY -- every later assertion would be vacuous"
        % README_ITEM)


def test_b8_readme_item_53_denies_no_call_site():
    entry = foundry.dormancy_entry_text(_readme_text(), README_ITEM)
    assert entry.strip() != "", "precondition: non-empty entry"
    assert _denials_in(entry) == [], (
        "item %d still denies its live call site: %r"
        % (README_ITEM, _denials_in(entry)))


def test_b8_readme_item_53_names_the_live_caller_positively():
    entry = foundry.dormancy_entry_text(_readme_text(), README_ITEM)
    assert "pm_recoverable_block" in entry, (
        "item %d must name the live caller positively" % README_ITEM)


@pytest.mark.parametrize("phrase", foundry.DORMANCY_DENIAL_PHRASES)
def test_b8_brake_is_two_sided(phrase):
    """Splice a denial phrase back on and the SAME check must fail."""
    entry = foundry.dormancy_entry_text(_readme_text(), README_ITEM)
    spliced = entry + " -- the pipeline and the gate %s." % phrase
    assert _denials_in(spliced) != [], (
        "the brake is fail-OPEN: it did not catch spliced phrase %r" % phrase)
