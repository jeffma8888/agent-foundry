"""Black-box behaviour tests for iter 98 -- `foundry learnings --json`: a
machine-readable JSON decomposition of the bounded learnings digest (the pinned
`## Patterns` head + the recent lesson lines + total/kept counts) emitted by the
read-only, side-effect-free `learnings` CLI, on a NEW dormant frozen value
object `LearningsView` + a NEW pure function `learnings_view(text, recent=12)`
+ an `as_json` flag on the existing `learnings_cli`. The wired `learnings_digest`
renderer is NOT modified; the human CLI path keeps calling it verbatim.

Unlike the 0/1/2 CLIs of iters 92/94/95/96/97 this CLI is EXIT-0-ALWAYS in both
modes: `learnings_cli` reads `cfg.learnings` defensively (a missing file yields
an empty-text placeholder digest), prints, and returns 0 regardless of mode or
input. There is no error path.

The value object exposes FOUR stored fields in declaration order -- two str-list
tuples (`head`, `recent_lessons`) FIRST, two ints (`total`, `kept`) LAST -- and
NO derived properties, so the 4-key to_dict is ["head", "recent_lessons",
"total", "kept"]. This is a THIRD distinct str-list layout vs prd's `pending` /
lint-spec's `missing_sections` (a SINGLE str-list in the MIDDLE) and gate-scope
(four str-lists front, two props last). Each str-list bucket is `tuple[str, ...]`
so it must be coerced via `list(...)` or the JSON round-trip breaks (a bare tuple
reads back as a list).

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-18) and the product's own OBSERVABLE behaviour only (running it) plus
the pre-existing learnings-core test file under tests/ (test_iter07_behavior.py).
The implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` (and `git show HEAD:foundry.py`) were NOT read to design
these behaviour tests. Every check drives the PUBLIC interface: the pure core via
`foundry.learnings_view(...)` + `LearningsView.to_dict`, parity against the
public `foundry.learnings_digest(...)`, and the CLI via `foundry.learnings_cli`
and `foundry.main(["learnings", ...])` against a TMP config whose learnings file
lives under a temp work_root (the real foundry repo is NEVER touched). Behavior
13 encodes its own normative statement -- the human path prints exactly
`learnings_digest(text, recent) + "\n"` -- against the public `learnings_digest`
oracle (the byte-unchanged guarantee is transitively pinned by the iter-07 suite
tests + Behavior 11 parity), so no HEAD-module load / no source read is needed.
The head-extraction rule (Behavior 7) is reconstructed INDEPENDENTLY from the
spec's documented format and compared. The dormancy proof uses only public
runtime introspection -- compiled function name tables (`co_names` recursed via
`_co_names_deep`) + a `dispatcher.py` source symbol-count -- and the mechanical
ASCII acceptance check uses `inspect.getsource` SCOPED to the two BRAND-NEW
symbols only (`LearningsView.to_dict` + `learnings_view`), never the changed
`learnings_cli` (whose docstring carries PRE-EXISTING em-dashes -- the iter-67
whole-file/getsource trap) and never a whole-file scan / never `git diff`. Fully
offline and deterministic: real temp files only, no subprocess/git/network
(except the fresh-import regression probe). There is deliberately NO
`git diff --quiet HEAD` control-path guard in this file -- the iter-86 fix
removed that over-broad freeze anti-pattern.
"""
import contextlib
import dataclasses
import importlib.util
import inspect
import io
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (module located via the BARE __file__ object,
# never a quoted source-literal main-module name -- the iter-54 meta-scanner)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The 4 keys to_dict() must expose, IN THIS ORDER: the 2 stored str-list fields
# (head, recent_lessons) FIRST, THEN the 2 stored int fields (total, kept). No
# derived properties. NO exit_code key (this CLI has no error exit).
KEY_ORDER = ["head", "recent_lessons", "total", "kept"]
EXPECTED_KEYS = set(KEY_ORDER)

# The two BRAND-NEW symbols this iteration introduces. Dormancy is proven against
# these -- NEVER the generic `to_dict` name (~30 classes own one).
NEW_SYMBOLS = ("learnings_view", "LearningsView")

PLACEHOLDER_HEAD = ("## Patterns", "(none recorded yet)")


# --------------------------------------------------------------------------
# text fixtures + independent reconstruction helpers
# --------------------------------------------------------------------------
def _marker(i):
    return "marker-%03d" % i


def _lesson(i, tag="ROLE"):
    """A role-tagged lesson line (`- [ROLE iterNN] ...`) w/ a unique marker."""
    return "- [%s iter%02d] %s some durable detail text here" % (tag, i, _marker(i))


def _patterns_head(*bullets):
    """A `## Patterns` head: heading + blurb + plain `- ` pattern bullets."""
    lines = ["## Patterns", "", "Read this head first; the tail is the history.", ""]
    lines += ["- %s" % b for b in bullets]
    return "\n".join(lines)


def _is_lesson(line):
    return line.lstrip().startswith("- [")


def _is_h2(line):
    return line.lstrip().startswith("## ")


def _expected_head(text):
    """Reconstruct the EXPECTED head INDEPENDENTLY from the spec's Behavior-7/8
    documented rule: the verbatim block of lines from the `## Patterns` line up
    to (but excluding) the first later `## ` heading OR lesson line; the fixed
    placeholder when there is no `## Patterns` heading."""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("## Patterns"):
            start = i
            break
    if start is None:
        return PLACEHOLDER_HEAD
    head = [lines[start]]
    for ln in lines[start + 1:]:
        if _is_h2(ln) or _is_lesson(ln):
            break
        head.append(ln)
    return tuple(head)


def _all_lessons(text):
    """Every lesson line (left-stripped starts with `- [`), in document order."""
    return [ln for ln in text.split("\n") if _is_lesson(ln)]


# canonical fixtures
_RICH = (_patterns_head("rule alpha", "rule beta")
         + "\n\n## Chronological lessons\n\n"
         + "\n".join(_lesson(i) for i in range(1, 16)) + "\n")   # 15 lessons, head via `## ` term
_LESSONTERM = (_patterns_head("rule one", "rule two") + "\n"
               + "\n".join(_lesson(i) for i in range(1, 5)) + "\n")  # head via lesson-line term
_NOPAT = "\n".join(_lesson(i) for i in range(1, 4)) + "\n"          # no `## Patterns`, 3 lessons
_EMPTY = ""
_FEWER = "\n".join(_lesson(i) for i in range(1, 4)) + "\n"          # 3 lessons < default recent
_CASES = (("rich", _RICH, 5), ("nopat", _NOPAT, 12), ("empty", _EMPTY, 12), ("fewer", _FEWER, 12))


# --------------------------------------------------------------------------
# config + stdout helpers (mirror the suite convention)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def _cfg_with_learnings(tmp_path, file_text):
    """Load a config + seed <work_root>/LEARNINGS.md (cfg.learnings) with text."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(file_text)
    return cfg


def _cap(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing nested code objects. Pure
    runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter98_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous
# ==========================================================================
def test_precondition_fixtures_behave_as_named():
    rich = foundry.learnings_view(_RICH, recent=5)
    assert rich.total == 15 and rich.kept == 5
    assert len(rich.head) > 2 and rich.head[0] == "## Patterns"      # non-empty head
    assert type(rich.head) is tuple and type(rich.recent_lessons) is tuple
    nopat = foundry.learnings_view(_NOPAT, recent=12)
    assert nopat.head == PLACEHOLDER_HEAD and nopat.total == 3
    empty = foundry.learnings_view(_EMPTY, recent=12)
    assert empty.total == 0 and empty.kept == 0 and empty.recent_lessons == ()


# ==========================================================================
# Behavior 1 -- frozen dataclass, exactly 4 stored fields in declaration order,
#               correct types, no exit_code attribute
# ==========================================================================
def test_b01_frozen_dataclass_four_fields_in_order():
    assert dataclasses.is_dataclass(foundry.LearningsView)
    assert foundry.LearningsView.__dataclass_params__.frozen is True
    fields = [f.name for f in dataclasses.fields(foundry.LearningsView)]
    assert fields == KEY_ORDER, fields
    props = [n for n, v in vars(foundry.LearningsView).items() if isinstance(v, property)]
    assert props == [], "LearningsView must have NO derived properties: %r" % props


def test_b01_field_types_and_instance_types():
    v = foundry.learnings_view(_RICH, recent=5)
    assert type(v.head) is tuple and all(type(x) is str for x in v.head)
    assert type(v.recent_lessons) is tuple and all(type(x) is str for x in v.recent_lessons)
    assert type(v.total) is int and type(v.kept) is int


def test_b01_no_exit_code_attribute():
    assert not hasattr(foundry.LearningsView, "exit_code")


# ==========================================================================
# Behavior 2 -- to_dict() has EXACTLY the 4 keys in the pinned order; str-lists
#               are LISTs, ints are ints; no exit_code key
# ==========================================================================
def test_b02_to_dict_exact_4_keys_in_order():
    for _, txt, rec in _CASES:
        d = foundry.learnings_view(txt, recent=rec).to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == KEY_ORDER, "to_dict key order %r != %r" % (list(d.keys()), KEY_ORDER)
        assert set(d.keys()) == EXPECTED_KEYS
        assert len(d) == 4
        assert "exit_code" not in d


def test_b02_key_order_matches_field_declaration():
    """Independently derive the expected order from the public dataclass shape:
    stored fields in declaration order (there are no properties)."""
    fields = [f.name for f in dataclasses.fields(foundry.LearningsView)]
    assert fields == KEY_ORDER, fields


def test_b02_value_types_in_dict():
    for _, txt, rec in _CASES:
        d = foundry.learnings_view(txt, recent=rec).to_dict()
        assert type(d["head"]) is list
        assert type(d["recent_lessons"]) is list
        assert type(d["total"]) is int
        assert type(d["kept"]) is int


# ==========================================================================
# Behavior 3 -- one-level str-list coercion + JSON round-trip
# ==========================================================================
def test_b03_lists_equal_coerced_tuples_and_round_trip():
    for _, txt, rec in _CASES:
        v = foundry.learnings_view(txt, recent=rec)
        d = v.to_dict()
        assert d["head"] == list(v.head)
        assert d["recent_lessons"] == list(v.recent_lessons)
        assert all(type(x) is str for x in d["head"])
        assert all(type(x) is str for x in d["recent_lessons"])
        assert json.loads(json.dumps(d)) == d, "to_dict did not round-trip through JSON"


# ==========================================================================
# Behavior 4 -- round-trip holds for the four required shapes
# ==========================================================================
def test_b04_round_trip_all_four_shapes():
    shapes = {
        "patterns+more-than-recent": (_RICH, 5),   # head + total(15) > recent(5)
        "no-patterns": (_NOPAT, 12),
        "empty-string": (_EMPTY, 12),
        "fewer-than-recent": (_FEWER, 12),          # total(3) < recent(12)
    }
    for name, (txt, rec) in shapes.items():
        d = foundry.learnings_view(txt, recent=rec).to_dict()
        assert json.loads(json.dumps(d)) == d, "round-trip failed for %r" % name


# ==========================================================================
# Behavior 5 -- non-vacuity of the list() coercion for BOTH str-list buckets
# ==========================================================================
def test_b05_bare_tuple_head_breaks_round_trip():
    v = foundry.learnings_view(_RICH, recent=5)
    d = v.to_dict()
    assert len(d["head"]) > 0, "head empty -- guard would be vacuous"
    assert json.loads(json.dumps(d)) == d
    bad = dict(d)
    bad["head"] = v.head  # the raw frozen tuple
    assert isinstance(bad["head"], tuple)
    assert json.loads(json.dumps(bad)) != bad, (
        "round-trip check is vacuous -- a tuple-valued head did not break equality")


def test_b05_bare_tuple_recent_lessons_breaks_round_trip():
    v = foundry.learnings_view(_RICH, recent=5)
    d = v.to_dict()
    assert len(d["recent_lessons"]) > 0, "recent_lessons empty -- guard would be vacuous"
    bad = dict(d)
    bad["recent_lessons"] = v.recent_lessons  # the raw frozen tuple
    assert isinstance(bad["recent_lessons"], tuple)
    assert json.loads(json.dumps(bad)) != bad, (
        "round-trip check is vacuous -- a tuple-valued recent_lessons did not break equality")


# ==========================================================================
# Behavior 6 -- to_dict() is a FRESH dict each call; mutation isolation
# ==========================================================================
def test_b06_to_dict_read_only():
    for _, txt, rec in (("rich", _RICH, 5), ("fewer", _FEWER, 12)):
        v = foundry.learnings_view(txt, recent=rec)
        before = dataclasses.asdict(v)
        d1 = v.to_dict()
        d1["recent_lessons"].append("BOGUS LESSON")
        d1["total"] = 99999
        d1["NEWKEY"] = 1
        d2 = v.to_dict()
        assert dataclasses.asdict(v) == before, "to_dict mutated the frozen instance"
        assert d2 == foundry.learnings_view(txt, recent=rec).to_dict(), "second to_dict affected by mutation"
        assert "NEWKEY" not in d2
        assert d1 is not d2


def test_b06_two_calls_equal_but_distinct():
    v = foundry.learnings_view(_RICH, recent=5)
    a, b = v.to_dict(), v.to_dict()
    assert a == b
    assert a is not b
    assert a["recent_lessons"] is not b["recent_lessons"], "bucket list shared across calls"


# ==========================================================================
# Behavior 7 -- head is the verbatim block up to the first `## ` heading OR
#               lesson line, reconstructed independently from the spec's rule
# ==========================================================================
def test_b07_head_terminated_by_next_h2_heading():
    v = foundry.learnings_view(_RICH, recent=12)
    assert v.head == _expected_head(_RICH)
    # documented content is present, the next heading is excluded
    assert v.head[0] == "## Patterns"
    assert "- rule alpha" in v.head and "- rule beta" in v.head
    assert "## Chronological lessons" not in v.head
    # no lesson line leaked into the head
    assert not any(_is_lesson(ln) for ln in v.head)


def test_b07_head_terminated_by_first_lesson_line():
    v = foundry.learnings_view(_LESSONTERM, recent=12)
    assert v.head == _expected_head(_LESSONTERM)
    assert v.head[0] == "## Patterns"
    assert "- rule one" in v.head and "- rule two" in v.head
    assert not any(_is_lesson(ln) for ln in v.head), "a lesson line leaked into the head"


# ==========================================================================
# Behavior 8 -- no `## Patterns` heading -> fixed placeholder head
# ==========================================================================
def test_b08_no_patterns_placeholder_head():
    for txt in (_NOPAT, _EMPTY):
        v = foundry.learnings_view(txt, recent=12)
        assert v.head == PLACEHOLDER_HEAD == ("## Patterns", "(none recorded yet)")


# ==========================================================================
# Behavior 9 -- total = count of all lesson lines; recent_lessons = LAST
#               min(total, recent); kept == len(recent_lessons) == min(total,recent)
# ==========================================================================
def test_b09_total_recent_kept_selection():
    text = "\n".join(_lesson(i) for i in range(1, 11)) + "\n"  # 10 lessons
    all_lines = _all_lessons(text)
    assert len(all_lines) == 10
    for rec in (3, 10, 7):
        v = foundry.learnings_view(text, recent=rec)
        assert v.total == 10, "total must count every lesson line"
        expected_tail = tuple(all_lines[max(0, v.total - rec):])
        assert v.recent_lessons == expected_tail, "recent_lessons must be the LAST min(total,recent)"
        assert len(v.recent_lessons) == min(v.total, rec)
        assert v.kept == len(v.recent_lessons) == min(v.total, rec)


def test_b09_recent_lessons_are_the_newest_in_order():
    text = "\n".join(_lesson(i) for i in range(1, 11)) + "\n"
    v = foundry.learnings_view(text, recent=3)
    assert v.recent_lessons == (_lesson(8), _lesson(9), _lesson(10))


# ==========================================================================
# Behavior 10 -- bound behavior: recent=0 and recent > total
# ==========================================================================
def test_b10_recent_zero():
    v = foundry.learnings_view(_RICH, recent=0)
    assert v.kept == 0
    assert v.recent_lessons == ()
    assert v.total == 15, "total must be unchanged by recent=0"


def test_b10_recent_greater_than_total():
    v = foundry.learnings_view(_FEWER, recent=999)   # total 3
    assert v.total == 3
    assert v.kept == 3
    assert v.recent_lessons == tuple(_all_lessons(_FEWER)), "recent > total keeps every lesson in order"


# ==========================================================================
# Behavior 11 -- parity with the unchanged learnings_digest renderer
# ==========================================================================
def test_b11_parity_with_learnings_digest():
    cases = (("rich", _RICH, 3), ("recent>total", _RICH, 99), ("nopat", _NOPAT, 12),
             ("empty", _EMPTY, 12), ("recent0", _RICH, 0), ("fewer", _FEWER, 12))
    for name, txt, rec in cases:
        v = foundry.learnings_view(txt, recent=rec)
        digest = foundry.learnings_digest(txt, recent=rec)
        assert digest.startswith("\n".join(v.head)), "digest does not start with the view head (%s)" % name
        header = "## Recent lessons (last %d of %d)" % (v.kept, v.total)
        assert header in digest, "count header %r missing from digest (%s)" % (header, name)
        for lesson in v.recent_lessons:
            assert lesson in digest, "recent lesson missing from digest (%s): %r" % (name, lesson)


# ==========================================================================
# Behavior 12 -- signatures
# ==========================================================================
def test_b12_learnings_view_signature():
    params = inspect.signature(foundry.learnings_view).parameters
    assert list(params) == ["text", "recent"], list(params)
    assert params["recent"].default == 12


def test_b12_learnings_cli_signature():
    params = inspect.signature(foundry.learnings_cli).parameters
    assert list(params) == ["cfg", "recent", "as_json"], list(params)
    assert params["as_json"].default is False


# ==========================================================================
# Behavior 13 -- human path (as_json omitted/False) prints exactly
#                learnings_digest(text, recent) + "\n", returns 0, is NOT JSON
# ==========================================================================
def test_b13_human_path_equals_digest(tmp_path):
    cfg = _cfg_with_learnings(tmp_path, _RICH)
    for rec in (12, 3):
        rc, out = _cap(lambda: foundry.learnings_cli(cfg, recent=rec))
        assert rc == 0
        assert out == foundry.learnings_digest(_RICH, recent=rec) + "\n", (
            "human CLI output != learnings_digest(text, recent) + newline (recent=%d)" % rec)


def test_b13_default_equals_explicit_false(tmp_path):
    cfg = _cfg_with_learnings(tmp_path, _RICH)
    rc_def, out_def = _cap(lambda: foundry.learnings_cli(cfg, recent=5))
    rc_false, out_false = _cap(lambda: foundry.learnings_cli(cfg, recent=5, as_json=False))
    assert (rc_def, out_def) == (rc_false, out_false)


def test_b13_human_render_not_valid_json(tmp_path):
    cfg = _cfg_with_learnings(tmp_path, _RICH)
    _, human = _cap(lambda: foundry.learnings_cli(cfg, recent=5, as_json=False))
    with pytest.raises(json.JSONDecodeError):
        json.loads(human)


# ==========================================================================
# Behavior 14 -- JSON path prints exactly json.dumps(to_dict(),indent=2)+nl,
#                returns 0, parses back to the dict, NO human line leaks
# ==========================================================================
def test_b14_json_output_is_exact(tmp_path):
    cfg = _cfg_with_learnings(tmp_path, _RICH)
    for rec in (12, 3):
        rc, out = _cap(lambda: foundry.learnings_cli(cfg, recent=rec, as_json=True))
        expected = json.dumps(foundry.learnings_view(_RICH, recent=rec).to_dict(), indent=2) + "\n"
        assert rc == 0
        assert out == expected, "as_json output != json.dumps(to_dict(),indent=2)+nl (recent=%d)" % rec
        assert json.loads(out) == foundry.learnings_view(_RICH, recent=rec).to_dict()


def test_b14_json_lines_start_with_json_token(tmp_path):
    cfg = _cfg_with_learnings(tmp_path, _RICH)
    _, out = _cap(lambda: foundry.learnings_cli(cfg, recent=5, as_json=True))
    for ln in out.splitlines():
        s = ln.strip()
        assert s == "" or s[0] in "{}[]\"", "JSON line does not start with a JSON token: %r" % ln


def test_b14_leak_check_armed_by_human_complement(tmp_path):
    """The SAME structural check must FAIL on the human render -- else its pass on
    JSON is meaningless. The `## Patterns` / `## Recent` lines lead with `#`."""
    cfg = _cfg_with_learnings(tmp_path, _RICH)
    _, human = _cap(lambda: foundry.learnings_cli(cfg, recent=5, as_json=False))
    nonblank = [ln for ln in human.splitlines() if ln.strip()]
    assert nonblank, "human render empty"
    offenders = [ln for ln in nonblank if ln.strip()[0] not in "{}[]\""]
    assert offenders, "leak check inert -- every human line looked like JSON:\n%s" % human


# ==========================================================================
# Behavior 15 -- both modes return 0 for every input (incl. missing file);
#                writes NOTHING from an empty cwd in either mode
# ==========================================================================
def test_b15_both_modes_return_zero_missing_file(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert not pathlib.Path(cfg.learnings).exists(), "learnings file must be absent for this case"
    for as_json in (False, True):
        rc, out = _cap(lambda: foundry.learnings_cli(cfg, as_json=as_json))
        assert rc == 0, "missing-file must still return 0 (as_json=%s)" % as_json
        if as_json:
            d = json.loads(out)
            assert d["head"] == list(PLACEHOLDER_HEAD)
            assert d["total"] == 0 and d["kept"] == 0
        else:
            assert "(none recorded yet)" in out


def test_b15_both_modes_return_zero_rich_and_empty(tmp_path):
    for text in (_RICH, _EMPTY):
        cfg = _cfg_with_learnings(tmp_path / (text and "r" or "e"), text)
        for as_json in (False, True):
            rc, _ = _cap(lambda: foundry.learnings_cli(cfg, as_json=as_json))
            assert rc == 0


def test_b15_writes_nothing_from_empty_cwd(tmp_path, monkeypatch):
    cfg = _cfg_with_learnings(tmp_path, _RICH)
    cwd = tmp_path / "emptycwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    for as_json in (False, True):
        _cap(lambda: foundry.learnings_cli(cfg, recent=5, as_json=as_json))
    assert sorted(p.name for p in cwd.iterdir()) == [], "learnings_cli wrote to cwd"
    # missing-file path also writes nothing
    missing = foundry.load_config(str(_write_cfg(tmp_path / "m")))
    for as_json in (False, True):
        _cap(lambda: foundry.learnings_cli(missing, as_json=as_json))
    assert sorted(p.name for p in cwd.iterdir()) == [], "missing-file path wrote to cwd"


# ==========================================================================
# Behavior 16 -- argparse routing via foundry.main + a learnings_cli dispatch spy
# ==========================================================================
def test_b16_json_store_true_and_recent_passthrough(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    captured = {}

    def fake(cfg, recent=12, as_json=False):
        captured.clear()
        captured.update(recent=recent, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "learnings_cli", fake)
    foundry.main(["learnings", "--config", str(cfg_path), "--json", "--recent", "7"])
    assert captured == {"recent": 7, "as_json": True}
    foundry.main(["learnings", "--config", str(cfg_path), "--recent", "7"])
    assert captured == {"recent": 7, "as_json": False}
    foundry.main(["learnings", "--config", str(cfg_path)])
    assert captured["as_json"] is False


def test_b16_config_required_raises_systemexit():
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["learnings"])
    assert ei.value.code != 0


def test_b16_json_takes_no_value(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["learnings", "--config", str(cfg_path), "--json", "bogus"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 17 -- end-to-end via foundry.main on a real learnings file
# ==========================================================================
def test_b17_e2e_json(tmp_path):
    _cfg_with_learnings(tmp_path, _RICH)
    cfg_path = tmp_path / "config.json"
    rc, out = _cap(lambda: foundry.main(["learnings", "--config", str(cfg_path), "--json"]))
    assert rc == 0
    d = json.loads(out)
    assert list(d.keys()) == KEY_ORDER
    assert d["total"] >= 0 and d["kept"] <= d["total"]


def test_b17_e2e_without_json_is_human_digest(tmp_path):
    _cfg_with_learnings(tmp_path, _RICH)
    cfg_path = tmp_path / "config.json"
    rc, out = _cap(lambda: foundry.main(["learnings", "--config", str(cfg_path)]))
    assert rc == 0
    assert "## Patterns" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# ==========================================================================
# Behavior 18 -- DORMANCY + importability: orchestrators/dispatcher untouched
# ==========================================================================
def test_b18_orchestrators_do_not_reference_new_symbols():
    new = set(NEW_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references new symbol(s): %r" % (fn.__name__, refs)


def test_b18_dispatcher_has_zero_new_symbol_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for s in NEW_SYMBOLS:
        assert dtext.count(s) == 0, "dispatcher.py references %s" % s


def test_b18_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.learnings_view)
    assert callable(foundry.learnings_cli)
    assert callable(foundry.learnings_digest)
    assert dataclasses.is_dataclass(foundry.LearningsView)
    assert callable(foundry.LearningsView.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_learnings(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "learnings", "agents", "lint-spec", "prd", "gate-scope"):
        assert sub in out, "subcommand %r missing from --help (regression)" % sub


def test_ac_new_symbols_ascii():
    """Scoped to the two BRAND-NEW symbols via inspect.getsource -- NEVER the
    changed learnings_cli (its docstring carries pre-existing em-dashes) and
    NEVER a whole-file scan (the iter-67 trap)."""
    srcs = [
        inspect.getsource(foundry.LearningsView.to_dict),
        inspect.getsource(foundry.learnings_view),
    ]
    for src in srcs:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
