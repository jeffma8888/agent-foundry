"""Black-box behaviour tests for iter 144 -- the read-only `foundry prompt` verb.

ISOLATION CONTRACT (honored): these tests were written from the PM spec's Expected
Behaviors (1-16) and from the product's OWN observable output (obtained by RUNNING
`foundry.prompt_cli` / `foundry.main`). The implementation source of `foundry.py` /
`dispatcher.py` was NOT read by hand, and neither were the engineer's notes, the
reviewer's notes, the fix notes, or `git diff`. Everything is driven through the
PUBLIC surface: `foundry.prompt_stage_options`, `prompt_stage_args`,
`prompt_learnings_digest`, `render_stage_prompt`, `prompt_metrics`, `PromptMetrics`,
`prompt_cli`, `foundry.main([...])`, plus the already-public `build_prompt`,
`retry_directive`, `learnings_digest`, `iteration_numbers`, `load_config` and
`foundry_cli_verbs`.

The TEXT of `foundry.py` / `dispatcher.py` is used in exactly two places as INPUT
DATA to a mechanical structural check (behavior 15 feeds it to `foundry_cli_verbs`,
behavior 16 parses it with `ast` and asserts an absence-of-references census with its
own non-vacuity floor) -- never inspected by hand.

Fully offline and deterministic: real temp files under `tmp_path` only. NO network,
NO subprocess, NO git, NO `agent` run, NO clock dependence. Every path handed to the
code under test lives under `tmp_path`; the real repo is never a write target.
"""
import ast
import dataclasses
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe / behavior-16 census input)

VERB = "prompt"

# The six brand-new symbols this iteration introduces (behavior 16 census target).
NEW_SYMBOLS = (
    "prompt_cli",
    "render_stage_prompt",
    "prompt_metrics",
    "prompt_stage_args",
    "prompt_stage_options",
    "prompt_learnings_digest",
)

# Stage labels the spec pins for THIS tree (behavior 1). Held as data here so the
# assertion can also prove they are DERIVED from CORE_SEAT_STAGES at call time.
EXPECTED_LABELS = ("pm", "engineer", "reviewer", "tester", "final")

JSON_KEYS = {
    "product", "stage", "iteration", "attempt", "role_file", "out_file",
    "total_chars", "digest_chars", "digest_share_pct", "digest_embedded",
    "digest_truncations", "retry_chars", "rendered_against",
}

HONESTY_NOTE = "rendered against the CURRENT tree"


# --------------------------------------------------------------------------
# helpers -- tmp product configs (never the real repo) + tree snapshots
# --------------------------------------------------------------------------
def _patterns_head(*bullets):
    lines = ["## Patterns", "", "Read this head first; the tail is the full history.", ""]
    lines += ["- %s" % b for b in bullets]
    return "\n".join(lines)


def _lesson(i):
    return "- [ROLE iter%03d] lesson-marker-%03d %s" % (i, i, "detail " * 8)


def _learnings_text(n_head=4, n_lessons=30):
    head = _patterns_head(*["HEAD BULLET %d %s" % (i, "pattern text " * 12) for i in range(n_head)])
    tail = "\n".join(_lesson(i) for i in range(n_lessons))
    return head + "\n\n## Recent lessons\n" + tail + "\n"


def _cfg(tmp_path, learnings_text=None, learnings_path=None, sub="p"):
    """Loaded ProductConfig rooted entirely under tmp_path.

    NOTE: `load_config` itself creates the work/state dirs -- so behavior-7 snapshots
    are always taken AFTER this helper returns, and the `iter-NN` dir is what must
    stay absent.
    """
    root = tmp_path / sub
    (root / "repo").mkdir(parents=True, exist_ok=True)
    (root / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    roles = root / "roles"
    roles.mkdir(exist_ok=True)
    for label in foundry.prompt_stage_options():
        (roles / ("%s.md" % label)).write_text("# ROLE %s\ncard body\n" % label, encoding="utf-8")
    if learnings_path is None:
        learnings_path = root / "LEARNINGS.md"
        learnings_path.write_text(
            _learnings_text() if learnings_text is None else learnings_text, encoding="utf-8"
        )
    data = {
        "name": "demo",
        "repo": str(root / "repo"),
        "allowed_push_repo": "demo",
        "vision": str(root / "VISION.md"),
        "work_root": str(root / "work"),
        "learnings": str(learnings_path),
        "roles_dir": str(roles),
    }
    p = root / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return foundry.load_config(str(p))


def _snapshot(root):
    """({relative file path: bytes}, {relative dir path}) over the WHOLE tree."""
    root = pathlib.Path(root)
    files, dirs = {}, set()
    if not root.exists():
        return files, dirs
    for p in root.rglob("*"):
        rel = str(p.relative_to(root))
        if p.is_file():
            files[rel] = p.read_bytes()
        elif p.is_dir():
            dirs.add(rel)
    return files, dirs


def _it_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / ("iter-%02d" % iteration)


def _out(capsys):
    return capsys.readouterr().out


def _both(capsys):
    cap = capsys.readouterr()
    return cap.out + cap.err


def _small_budgets(monkeypatch, recent=25, budget=1500, lesson=90, head_bullet=70, head=600):
    """Budgets small enough that EVERY one of the five bites on the fixture text.

    `max_chars` bounds the LESSONS section only (the head has its own budget), so
    `recent` must be large enough that the lessons overflow `budget` -- with a tiny
    recent window the total-budget clamp is unobservable and a probe of it reads as
    an implementation defect when nothing is wrong."""
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_RECENT", recent)
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_BUDGET_CHARS", budget)
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_LESSON_CHARS", lesson)
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_BULLET_CHARS", head_bullet)
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_HEAD_BUDGET_CHARS", head)


def _func_segments(source_text, wanted):
    """{name: source text} for top-level-or-nested `def`s, by line slice (fast)."""
    lines = source_text.splitlines(keepends=True)
    out = {}
    for node in ast.walk(ast.parse(source_text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            if node.name in out:
                continue
            out[node.name] = "".join(lines[node.lineno - 1:node.end_lineno])
    return out


# --------------------------------------------------------------------------
# behavior 1 -- prompt_stage_options() derived from CORE_SEAT_STAGES at CALL time
# --------------------------------------------------------------------------
def test_b1_stage_options_are_the_core_seat_labels_in_insertion_order():
    labels = foundry.prompt_stage_options()
    assert isinstance(labels, tuple), "must be a tuple, got %r" % type(labels)
    assert labels == EXPECTED_LABELS, "labels %r != %r" % (labels, EXPECTED_LABELS)
    derived = tuple(v[0] for v in foundry.CORE_SEAT_STAGES.values())
    assert labels == derived, "labels %r are not CORE_SEAT_STAGES order %r" % (labels, derived)


def test_b1_stage_options_read_core_seat_stages_at_call_time(monkeypatch):
    monkeypatch.setattr(
        foundry,
        "CORE_SEAT_STAGES",
        {"zseat": ("zeta", "zeta.md", "zeta.md"), "aseat": ("alpha", "alpha.md", "alpha.md")},
    )
    assert foundry.prompt_stage_options() == ("zeta", "alpha"), (
        "monkeypatched CORE_SEAT_STAGES did not change the result -- the mapping is "
        "captured at import time instead of read at call time"
    )


def test_b1_new_functions_introduce_no_stage_label_literals():
    """Mechanical, scoped to the SIX new functions only (source used as data)."""
    src = pathlib.Path(foundry.__file__).resolve().read_text(encoding="utf-8")
    segs = _func_segments(src, set(NEW_SYMBOLS))
    missing = [n for n in NEW_SYMBOLS if n not in segs]
    assert not missing, "new symbols not found as module functions: %r" % missing
    offenders = {}
    for name, seg in segs.items():
        lits = {
            c.value
            for c in ast.walk(ast.parse(seg.lstrip()))
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        }
        bad = sorted(lits & set(EXPECTED_LABELS))
        if bad:
            offenders[name] = bad
    assert not offenders, "stage-label literals re-introduced: %r" % offenders


# --------------------------------------------------------------------------
# behavior 2 -- prompt_stage_args is total: pair for known, None for everything else
# --------------------------------------------------------------------------
def test_b2_stage_args_returns_role_and_out_pair_for_every_known_label():
    assert foundry.prompt_stage_args("pm") == ("pm.md", "pm.md")
    assert foundry.prompt_stage_args("final") == ("final.md", "final.md")
    for label in foundry.prompt_stage_options():
        pair = foundry.prompt_stage_args(label)
        assert isinstance(pair, tuple) and len(pair) == 2, "%s -> %r" % (label, pair)
        assert all(isinstance(x, str) and x for x in pair), "%s -> %r" % (label, pair)


@pytest.mark.parametrize("bad", ["", "  ", "PM", "scout", None, 123, ["pm"], {"pm": 1}, 0, True])
def test_b2_stage_args_returns_none_and_never_raises_for_unknown_values(bad):
    assert foundry.prompt_stage_args(bad) is None, "%r should map to None" % (bad,)


# --------------------------------------------------------------------------
# behavior 3 -- prompt_learnings_digest under the five budgets, read at CALL time
# --------------------------------------------------------------------------
def test_b3_digest_equals_learnings_digest_under_the_five_prompt_budgets(tmp_path):
    text = _learnings_text()
    cfg = _cfg(tmp_path, learnings_text=text)
    expected = foundry.learnings_digest(
        text,
        recent=foundry.PROMPT_LEARNINGS_RECENT,
        max_chars=foundry.PROMPT_LEARNINGS_BUDGET_CHARS,
        lesson_chars=foundry.PROMPT_LEARNINGS_LESSON_CHARS,
        head_bullet_chars=foundry.PROMPT_LEARNINGS_HEAD_BULLET_CHARS,
        head_chars=foundry.PROMPT_LEARNINGS_HEAD_BUDGET_CHARS,
    )
    assert foundry.prompt_learnings_digest(cfg) == expected


def test_b3_all_five_budgets_are_passed_through_at_call_time(tmp_path, monkeypatch):
    """Kwargs spy: proves call-time read AND verbatim pass-through in one assertion."""
    cfg = _cfg(tmp_path)
    seen = {}

    def spy(text, **kw):
        seen.update(kw)
        seen["text_len"] = len(text)
        return "SPY-DIGEST"

    _small_budgets(monkeypatch, recent=5, budget=1234, lesson=77, head_bullet=66, head=555)
    monkeypatch.setattr(foundry, "learnings_digest", spy)
    assert foundry.prompt_learnings_digest(cfg) == "SPY-DIGEST"
    assert seen.get("recent") == 5
    assert seen.get("max_chars") == 1234
    assert seen.get("lesson_chars") == 77
    assert seen.get("head_bullet_chars") == 66
    assert seen.get("head_chars") == 555
    assert seen.get("text_len", 0) > 0, "the learnings TEXT was not read"


@pytest.mark.parametrize(
    "name,value",
    [
        ("PROMPT_LEARNINGS_RECENT", 1),
        ("PROMPT_LEARNINGS_BUDGET_CHARS", 400),
        ("PROMPT_LEARNINGS_LESSON_CHARS", 40),
        ("PROMPT_LEARNINGS_HEAD_BULLET_CHARS", 30),
        ("PROMPT_LEARNINGS_HEAD_BUDGET_CHARS", 300),
    ],
)
def test_b3_patching_any_single_budget_changes_the_returned_string(tmp_path, monkeypatch, name, value):
    cfg = _cfg(tmp_path)
    # A baseline where all five bounds ALREADY bite: the head overflows its budget (so
    # the per-bullet cap applies -- a head that fits is emitted verbatim by design) and
    # the lessons section overflows the total budget.
    _small_budgets(monkeypatch)
    base = foundry.prompt_learnings_digest(cfg)
    monkeypatch.setattr(foundry, name, value)
    assert foundry.prompt_learnings_digest(cfg) != base, (
        "patching %s did not change the digest -- it is not read at call time" % name
    )


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_b3_unusable_learnings_path_reads_as_empty_text_and_never_raises(tmp_path, kind):
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    baseline = foundry.prompt_learnings_digest(_cfg(tmp_path, learnings_path=empty, sub="base"))
    if kind == "missing":
        target = tmp_path / "nope" / "absent.md"
    else:
        target = tmp_path / "a-directory"
        target.mkdir()
    got = foundry.prompt_learnings_digest(_cfg(tmp_path, learnings_path=target, sub=kind))
    assert got == baseline, "%s learnings did not read as empty text" % kind


# --------------------------------------------------------------------------
# behavior 4 -- DRIFT GUARD, two-sided
# --------------------------------------------------------------------------
def test_b4_digest_appears_verbatim_inside_build_prompt_for_every_core_stage(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _small_budgets(monkeypatch)
    digest = foundry.prompt_learnings_digest(cfg)
    assert digest.strip(), "the fixture produced an empty digest"
    assert foundry.LEARNINGS_TRUNCATION_MARKER in digest, (
        "fixture does not TRIP a truncation, so a verbatim match would be trivial"
    )
    it_dir = _it_dir(cfg, 7)
    for stage in foundry.prompt_stage_options():
        role_file, out_name = foundry.prompt_stage_args(stage)
        built = foundry.build_prompt(cfg, 7, stage, role_file, it_dir / out_name, it_dir, "")
        assert digest in built, (
            "DRIFT: prompt_learnings_digest output is not embedded in build_prompt for "
            "stage %r -- the two digest computations have diverged" % stage
        )


def test_b4_lesson_budget_forces_a_truncation_marker(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _small_budgets(monkeypatch, lesson=20000, budget=100000, head=100000, head_bullet=20000)
    loose = foundry.prompt_learnings_digest(cfg)
    assert foundry.LEARNINGS_TRUNCATION_MARKER not in loose, "loose budgets should not truncate"
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_LESSON_CHARS", 40)
    tight = foundry.prompt_learnings_digest(cfg)
    assert foundry.LEARNINGS_TRUNCATION_MARKER in tight, "tight lesson budget did not truncate"


# --------------------------------------------------------------------------
# behavior 5 / 6 -- render_stage_prompt composition + bare-name seams
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stage", list(EXPECTED_LABELS))
@pytest.mark.parametrize("attempt", [1, 3])
def test_b5_render_is_byte_identical_to_build_prompt_plus_retry_directive(tmp_path, stage, attempt):
    cfg = _cfg(tmp_path)
    role_file, out_name = foundry.prompt_stage_args(stage)
    it_dir = _it_dir(cfg, 11)
    out_file = it_dir / out_name
    expected = foundry.build_prompt(cfg, 11, stage, role_file, out_file, it_dir, "") + \
        foundry.retry_directive(attempt, stage, out_file)
    assert foundry.render_stage_prompt(cfg, 11, stage, attempt=attempt) == expected


@pytest.mark.parametrize("stage", ["", "  ", "PM", "scout", None, 42])
def test_b5_render_returns_none_for_any_stage_stage_args_rejects(tmp_path, stage):
    cfg = _cfg(tmp_path)
    assert foundry.render_stage_prompt(cfg, 3, stage) is None


def test_b6_render_calls_build_prompt_by_bare_module_name(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "build_prompt", lambda *a, **k: "SENTINEL-BUILD")
    got = foundry.render_stage_prompt(cfg, 4, "pm")
    assert got is not None and got.startswith("SENTINEL-BUILD"), (
        "monkeypatching build_prompt had no effect: %r" % (got or "")[:120]
    )


def test_b6_render_calls_retry_directive_by_bare_module_name(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "retry_directive", lambda *a, **k: "SENTINEL-RETRY")
    got = foundry.render_stage_prompt(cfg, 4, "pm", attempt=2)
    assert got is not None and got.endswith("SENTINEL-RETRY"), (
        "monkeypatching retry_directive had no effect"
    )


# --------------------------------------------------------------------------
# behavior 7 -- WRITES NOTHING, CREATES NOTHING
# --------------------------------------------------------------------------
def test_b7_render_and_cli_write_nothing_anywhere_in_the_tree(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    it_dir = _it_dir(cfg, 77)
    assert not it_dir.exists(), "fixture invalid: the iter dir already exists"
    before = _snapshot(tmp_path)
    for stage in foundry.prompt_stage_options():
        assert foundry.render_stage_prompt(cfg, 77, stage) is not None
        assert foundry.prompt_cli(cfg, stage, 77) == 0
        assert foundry.prompt_cli(cfg, stage, 77, as_json=True) == 0
    assert foundry.prompt_cli(cfg, "bogus-stage", 77) == 2
    capsys.readouterr()
    after = _snapshot(tmp_path)
    assert not it_dir.exists(), "the iter-NN state dir was CREATED"
    assert after[0] == before[0], "files changed/created: %r" % (
        sorted(set(after[0]) ^ set(before[0]))
        or [k for k in before[0] if before[0][k] != after[0].get(k)]
    )
    assert after[1] == before[1], "directories changed: %r" % sorted(after[1] ^ before[1])


# --------------------------------------------------------------------------
# behavior 8 -- attempt semantics
# --------------------------------------------------------------------------
def test_b8_attempt_one_carries_no_retry_block(tmp_path):
    cfg = _cfg(tmp_path)
    got = foundry.render_stage_prompt(cfg, 5, "engineer", attempt=1)
    assert foundry.RETRY_DIRECTIVE_MARKER not in got


def test_b8_attempt_two_ends_with_a_non_empty_retry_block(tmp_path):
    cfg = _cfg(tmp_path)
    stage = "engineer"
    _role, out_name = foundry.prompt_stage_args(stage)
    out_file = _it_dir(cfg, 5) / out_name
    block = foundry.retry_directive(2, stage, out_file)
    assert block.strip(), "retry_directive(2, ...) is empty -- fixture invalid"
    got = foundry.render_stage_prompt(cfg, 5, stage, attempt=2)
    assert foundry.RETRY_DIRECTIVE_MARKER in got
    assert got.endswith(block)


@pytest.mark.parametrize("attempt", [0, -5])
def test_b8_attempt_below_one_is_treated_exactly_as_one(tmp_path, attempt):
    cfg = _cfg(tmp_path)
    one = foundry.render_stage_prompt(cfg, 5, "reviewer", attempt=1)
    assert foundry.render_stage_prompt(cfg, 5, "reviewer", attempt=attempt) == one


# --------------------------------------------------------------------------
# behavior 9 / 10 -- PromptMetrics shape + metric values
# --------------------------------------------------------------------------
def test_b9_prompt_metrics_is_a_frozen_dataclass_with_exactly_six_fields():
    assert dataclasses.is_dataclass(foundry.PromptMetrics)
    assert foundry.PromptMetrics.__dataclass_params__.frozen is True
    names = [f.name for f in dataclasses.fields(foundry.PromptMetrics)]
    assert names == [
        "total_chars", "digest_chars", "digest_share_pct",
        "digest_embedded", "digest_truncations", "retry_chars",
    ], names


def test_b9_every_field_refuses_assignment():
    m = foundry.prompt_metrics("abc", "b", "")
    for f in dataclasses.fields(foundry.PromptMetrics):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(m, f.name, 0)


@pytest.mark.parametrize(
    "prompt,digest,retry",
    [("", "", ""), ("x", "", ""), ("", "y", ""), ("a" * 5, "a", "r" * 3), ("\x00\n", "\n", "")],
)
def test_b9_prompt_metrics_is_total_and_never_raises(prompt, digest, retry):
    m = foundry.prompt_metrics(prompt, digest, retry)
    assert isinstance(m, foundry.PromptMetrics)


def test_b10_three_lengths_are_the_three_lens():
    m = foundry.prompt_metrics("a" * 31, "b" * 7, "c" * 3)
    assert (m.total_chars, m.digest_chars, m.retry_chars) == (31, 7, 3)


@pytest.mark.parametrize(
    "total,digest,expected",
    [(7, 3, 42), (3, 1, 33), (2, 1, 50), (10, 10, 100), (100, 0, 0), (3, 2, 66)],
)
def test_b10_share_is_the_floor_of_the_percentage(total, digest, expected):
    m = foundry.prompt_metrics("a" * total, "a" * digest, "")
    assert m.digest_share_pct == expected, "%d/%d -> %r" % (digest, total, m.digest_share_pct)


def test_b10_share_is_zero_for_an_empty_prompt():
    assert foundry.prompt_metrics("", "abc", "").digest_share_pct == 0


def test_b10_digest_embedded_requires_a_non_empty_digest_that_occurs_in_the_prompt():
    assert foundry.prompt_metrics("hello world", "lo wo", "").digest_embedded is True
    assert foundry.prompt_metrics("hello world", "absent", "").digest_embedded is False
    assert foundry.prompt_metrics("hello world", "", "").digest_embedded is False
    assert foundry.prompt_metrics("", "", "").digest_embedded is False


def test_b10_truncations_count_the_marker_in_the_DIGEST_only():
    mk = foundry.LEARNINGS_TRUNCATION_MARKER
    assert foundry.prompt_metrics("p" + mk * 4, "a" + mk + "b" + mk, "").digest_truncations == 2
    assert foundry.prompt_metrics("p" + mk * 4, "clean digest", "").digest_truncations == 0


def test_b10_truncation_marker_is_read_from_the_module_global_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "LEARNINGS_TRUNCATION_MARKER", "<<CUT>>")
    m = foundry.prompt_metrics("x", "a<<CUT>>b<<CUT>>c", "")
    assert m.digest_truncations == 2, "the marker global is not read at call time"


# --------------------------------------------------------------------------
# behavior 11 -- human output is EXACTLY banner + blank line + rendered + newline
# --------------------------------------------------------------------------
def test_b11_human_output_is_banner_blank_rendered_newline(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    assert foundry.prompt_cli(cfg, "pm", 8) == 0
    out = _out(capsys)
    rendered = foundry.render_stage_prompt(cfg, 8, "pm")
    banner, rest = out.split("\n\n", 1)
    assert "\n" not in banner, "the banner is not a single line: %r" % banner
    assert rest == rendered + "\n", "body is not exactly the rendered prompt plus one newline"
    assert out == banner + "\n\n" + rendered + "\n"
    # `... | tail -n +3` must be the verbatim prompt
    assert "\n".join(out.split("\n")[2:]) == rendered + "\n"


def test_b11_banner_names_stage_iteration_attempt_metrics_and_the_honesty_note(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    assert foundry.prompt_cli(cfg, "reviewer", 8, attempt=2) == 0
    out = _out(capsys)
    banner = out.split("\n\n", 1)[0]
    rendered = foundry.render_stage_prompt(cfg, 8, "reviewer", attempt=2)
    _role, out_name = foundry.prompt_stage_args("reviewer")
    retry = foundry.retry_directive(2, "reviewer", _it_dir(cfg, 8) / out_name)
    digest = foundry.prompt_learnings_digest(cfg)
    m = foundry.prompt_metrics(rendered, digest, retry)
    assert HONESTY_NOTE in banner, "banner lacks the honesty note: %r" % banner
    assert "reviewer" in banner
    assert "8" in banner and "2" in banner, "iteration/attempt not named: %r" % banner
    for field in ("total_chars", "digest_chars", "digest_share_pct",
                  "digest_truncations", "retry_chars"):
        pair = "%s=%s" % (field, getattr(m, field))
        assert pair in banner, "banner does not report %s: %r" % (pair, banner)


# --------------------------------------------------------------------------
# behavior 12 -- --json prints ONLY a JSON object with exactly the pinned keys
# --------------------------------------------------------------------------
def test_b12_json_mode_prints_only_a_parseable_object_with_exact_keys(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    assert foundry.prompt_cli(cfg, "tester", 12, attempt=2, as_json=True) == 0
    out = _out(capsys)
    obj = json.loads(out)
    assert isinstance(obj, dict)
    assert set(obj) == JSON_KEYS, "key mismatch: %r" % (sorted(set(obj) ^ JSON_KEYS),)
    assert obj["product"] == cfg.name
    assert obj["stage"] == "tester"
    assert obj["iteration"] == 12
    assert obj["attempt"] == 2
    assert obj["rendered_against"] == "current tree"
    for key in ("role_file", "out_file"):
        assert isinstance(obj[key], str) and pathlib.Path(obj[key]).is_absolute(), (
            "%s is not an absolute path string: %r" % (key, obj[key])
        )
    assert obj["out_file"].endswith("tester.md")
    assert HONESTY_NOTE not in out, "the human banner leaked into --json output"


def test_b12_json_metrics_match_the_public_recomputation(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    assert foundry.prompt_cli(cfg, "final", 6, as_json=True) == 0
    obj = json.loads(_out(capsys))
    rendered = foundry.render_stage_prompt(cfg, 6, "final")
    digest = foundry.prompt_learnings_digest(cfg)
    _role, out_name = foundry.prompt_stage_args("final")
    retry = foundry.retry_directive(1, "final", _it_dir(cfg, 6) / out_name)
    m = foundry.prompt_metrics(rendered, digest, retry)
    for field in ("total_chars", "digest_chars", "digest_share_pct",
                  "digest_embedded", "digest_truncations", "retry_chars"):
        assert obj[field] == getattr(m, field), field


def test_b12_json_output_does_not_carry_the_rendered_prompt(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    assert foundry.prompt_cli(cfg, "pm", 6, as_json=True) == 0
    out = _out(capsys)
    rendered = foundry.render_stage_prompt(cfg, 6, "pm")
    assert rendered not in out
    assert "HARD RULES" not in out, "prompt body text leaked into the JSON"
    assert "READ AND FOLLOW EXACTLY" not in out


# --------------------------------------------------------------------------
# behavior 13 -- exit codes
# --------------------------------------------------------------------------
def test_b13_success_exit_code_is_zero_in_both_modes(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    assert foundry.prompt_cli(cfg, "pm", 2) == 0
    assert foundry.prompt_cli(cfg, "pm", 2, as_json=True) == 0
    assert _out(capsys)


@pytest.mark.parametrize("bad", ["bogus", "", "PM", "scout"])
def test_b13_unknown_stage_exits_two_and_names_value_and_every_label(tmp_path, capsys, bad):
    cfg = _cfg(tmp_path)
    assert foundry.prompt_cli(cfg, bad, 2) == 2
    text = _both(capsys)
    if bad:
        assert bad in text, "message does not name the offending value: %r" % text
    for label in foundry.prompt_stage_options():
        assert label in text, "message omits label %r: %r" % (label, text)
    assert HONESTY_NOTE not in text, "a banner was printed on the error path"
    assert "HARD RULES" not in text, "a prompt was printed on the error path"


# --------------------------------------------------------------------------
# behavior 14 -- --iter default
# --------------------------------------------------------------------------
def test_b14_iteration_defaults_to_the_highest_iter_dir(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    state = pathlib.Path(cfg.state)
    state.mkdir(parents=True, exist_ok=True)
    for name in ("iter-03", "iter-17", "iter-09", "junk", "iter-abc"):
        (state / name).mkdir(exist_ok=True)
    (state / "iter-99.txt").write_text("not a dir", encoding="utf-8")
    assert foundry.iteration_numbers(sorted(p.name for p in state.iterdir())) == [3, 9, 17]
    assert foundry.prompt_cli(cfg, "pm", None, as_json=True) == 0
    assert json.loads(_out(capsys))["iteration"] == 17


@pytest.mark.parametrize("mode", ["absent", "empty"])
def test_b14_iteration_defaults_to_one_without_any_iter_dir(tmp_path, capsys, mode):
    cfg = _cfg(tmp_path, sub=mode)
    state = pathlib.Path(cfg.state)
    if mode == "absent":
        import shutil

        shutil.rmtree(state, ignore_errors=True)
        assert not state.exists()
    else:
        state.mkdir(parents=True, exist_ok=True)
        (state / "notes.txt").write_text("x", encoding="utf-8")
    assert foundry.prompt_cli(cfg, "pm", None, as_json=True) == 0
    assert json.loads(_out(capsys))["iteration"] == 1


def test_b14_explicit_iteration_is_used_verbatim(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    state = pathlib.Path(cfg.state)
    state.mkdir(parents=True, exist_ok=True)
    (state / "iter-42").mkdir(exist_ok=True)
    assert foundry.prompt_cli(cfg, "pm", 5, as_json=True) == 0
    obj = json.loads(_out(capsys))
    assert obj["iteration"] == 5
    assert "iter-05" in obj["out_file"]


# --------------------------------------------------------------------------
# behavior 15 -- CLI reachability
# --------------------------------------------------------------------------
def test_b15_verb_is_reachable_from_the_cli_parse():
    src = pathlib.Path(foundry.__file__).resolve().read_text(encoding="utf-8")
    verbs = foundry.foundry_cli_verbs(src)
    assert len(verbs) >= 40, "non-vacuity floor: only %d verbs parsed" % len(verbs)
    assert VERB in verbs, "%r missing from parsed CLI verbs: %r" % (VERB, sorted(verbs))


@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_b15_main_dispatches_the_verb_and_prints_something(tmp_path, capsys, extra):
    cfg = _cfg(tmp_path, sub="main-%d" % len(extra))
    cfg_path = pathlib.Path(cfg.repo).parent / "config.json"
    rc = foundry.main(["prompt", "--config", str(cfg_path), "--stage", "pm"] + extra)
    assert rc == 0
    assert _out(capsys).strip()


# --------------------------------------------------------------------------
# behavior 16 -- OFF THE CONTROL PATH (census with its own non-vacuity floor)
# --------------------------------------------------------------------------
def test_b16_control_path_functions_and_dispatcher_never_reference_the_new_symbols():
    src = pathlib.Path(foundry.__file__).resolve().read_text(encoding="utf-8")
    frozen = ("run_stage", "run_iteration", "run_continuous", "build_prompt")
    segs = _func_segments(src, set(frozen) | {"main"})
    missing = [n for n in frozen if n not in segs]
    assert not missing, "control-path functions not found: %r" % missing
    # non-vacuity: the census MUST be able to see the real main dispatch reference
    main_seg = segs.get("main", "")
    assert main_seg, "main() not found -- the census would be vacuous"
    assert "prompt_cli" in main_seg, (
        "non-vacuity floor failed: main() does not reference prompt_cli, so an empty "
        "census below would prove nothing"
    )
    for name in frozen:
        hits = sorted(s for s in NEW_SYMBOLS if s in segs[name])
        assert not hits, "%s references the new symbols %r -- it is ON the control path" % (name, hits)
    disp_src = pathlib.Path(dispatcher.__file__).resolve().read_text(encoding="utf-8")
    assert "def main" in disp_src, "dispatcher source did not load -- census vacuous"
    hits = sorted(s for s in NEW_SYMBOLS if s in disp_src)
    assert not hits, "dispatcher.py references the new symbols %r" % hits
