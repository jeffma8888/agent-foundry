"""Iteration 232 -- BLACK-BOX behavior tests: the lesson tail can be role-scoped.

The product grows two PURE text oracles, ``foundry.lesson_role_tag`` (the role tag of
one lesson line) and ``foundry.stage_role_tags`` (the tags a pipeline stage counts as
on-role), one module constant ``PROMPT_LEARNINGS_ROLE_RESERVE``, and two OPTIONAL
keyword parameters on ``foundry.learnings_digest`` (``role_tags``, ``role_reserve``)
that reserve part of the inlined lesson tail for the newest ON-ROLE lessons that the
strict-chronological window would otherwise crowd out.  ``build_prompt`` opts in with
the stage name it already holds.  Default-off must be BYTE-IDENTICAL and the emitted
lesson COUNT must never move.

Spec under test (products/_platform/state/iter-232/pm.md), Expected Behaviors 1-7:
   1. ``lesson_role_tag(line)`` -> uppercased tag, ``None`` for every non-lesson line;
      a tag may hold only ``[A-Za-z0-9_]``.  Pure.
   2. ``stage_role_tags(stage)`` -> the on-role tuple per stage, an UNKNOWN stage
      falls back to ``(stage.upper(),)`` and ``""``/``None`` return ``()``.
   3. Default-off is byte-identical: ``role_tags=None`` / ``()`` / ``role_reserve=0``
      all equal the plain call, character for character.
   4. Reservation is COUNT-PRESERVING: exactly ``K`` lesson lines, the newest
      ``K - R`` any-role ones, ``R`` older on-role ones, in DOCUMENT order.
   5. Nothing is paid when there is nothing to gain: zero on-role lessons ->
      byte-identical; fewer than ``R`` older on-role -> unused slots refill with the
      next-newest any-role lessons, so the count still equals the unscoped count, and
      no lesson is emitted twice.
   6. ``build_prompt`` opts in AT CALL TIME: both ``PROMPT_LEARNINGS_ROLE_RESERVE``
      and ``stage_role_tags`` are read as module globals inside the function, so
      ``monkeypatch.setattr`` on either moves the built prompt with no re-import.
   7. Composition runs BEFORE the existing bounds: ``lesson_chars`` / ``max_chars``
      still hold, and the ``## Recent lessons (last K of M)`` header's ``K`` equals
      the number of lesson lines actually emitted while ``M`` counts every lesson
      line in the log.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-232 PM spec, the
conventions of ``tests/``, and the product's OWN OBSERVABLE surface -- importing
``foundry`` and calling its public functions.  The implementation TEXT of
``foundry.py`` was NOT read; where a criterion is only decidable from source text
(behavior 6's read-at-call-time claim) it is decided by MONKEYPATCHING and observing
the output change, never by reading the body.  ``engineer.md``, ``reviewer.md`` and
``git diff`` were NOT read.

Offline and deterministic: every assertion below is a pure in-process function call
over a fixture the test itself builds (behavior 6 builds its log under ``tmp_path``).
No subprocess, no git, no network, no clock, no assertion about the ambient repo tree
(OPERATOR 2026-08-11 -- a shipped iteration went post-release BROKEN on a precondition
that was only true in one working tree).
"""

import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402


# ==========================================================================
# Behavior 1 -- lesson_role_tag
# ==========================================================================
_TAGGED = [
    ("- [PM iter231] x", "PM"),
    ("  - [pm_scout_a iter232] y", "PM_SCOUT_A"),
    ("- [TEST iter231] a b", "TEST"),
    ("   - [REV iter9] q", "REV"),
    ("- [FINAL iter1]", "FINAL"),
    ("- [eng iter7] lower tag uppercases", "ENG"),
    ("- [FIX_2 iter7] digits and underscore are legal", "FIX_2"),
]

_UNTAGGED = [
    "- plain bullet",
    "## heading",
    "",
    "- [no iter token]",
    "- [ iter1] x",
]


def test_b1_lesson_role_tag_reads_the_tag_and_refuses_a_non_lesson():
    for line, want in _TAGGED:
        assert foundry.lesson_role_tag(line) == want, f"tag of {line!r}"
    for line in _UNTAGGED:
        assert foundry.lesson_role_tag(line) is None, f"{line!r} is not a lesson line"
    # A tag may hold only [A-Za-z0-9_]; any other character yields None.
    for bad in "- .:/,+*()[]{}'\"\\!@#$%^&=|<>?~`":
        line = f"- [P{bad}M iter1] x"
        assert foundry.lesson_role_tag(line) is None, \
            f"{bad!r} must not be legal inside a role tag"
    # Total: no exception on a non-str, and no exception on any str.
    for weird in (None, 123, 1.5, [], {}, object()):
        assert foundry.lesson_role_tag(weird) is None, f"{weird!r} -> None"


def test_b1_lesson_role_tag_is_pure():
    """No filesystem, subprocess or network -- every seam the product owns is armed
    to RAISE, and 200 calls still return."""
    import subprocess as _sp
    fired = []

    class _Boom:
        def __call__(self, *a, **k):
            fired.append(a)
            raise AssertionError("lesson_role_tag must not perform I/O")

    saved = {}
    for name in ("run", "check_output", "Popen", "call"):
        if hasattr(_sp, name):
            saved[name] = getattr(_sp, name)
            setattr(_sp, name, _Boom())
    try:
        for line, want in _TAGGED:
            assert foundry.lesson_role_tag(line) == want
        for line in _UNTAGGED:
            assert foundry.lesson_role_tag(line) is None
    finally:
        for name, fn in saved.items():
            setattr(_sp, name, fn)
    assert fired == [], "lesson_role_tag reached a subprocess seam"


# ==========================================================================
# Behavior 2 -- stage_role_tags
# ==========================================================================
_STAGE_MAP = {
    "pm": ("PM",),
    "engineer": ("ENG",),
    "reviewer": ("REV",),
    "tester": ("TEST",),
    "final": ("FINAL",),
    "fix": ("FIX",),
    "pm_scout_a": ("PM_SCOUT_A", "SCOUT"),
    "pm_scout_b": ("PM_SCOUT_B", "SCOUT_B", "SCOUT"),
}


def test_b2_stage_role_tags_maps_every_pipeline_stage():
    for stage, want in _STAGE_MAP.items():
        got = foundry.stage_role_tags(stage)
        assert got == want, f"{stage!r} -> {got!r}, want {want!r}"
        assert isinstance(got, tuple), f"{stage!r} must return a tuple, got {type(got)}"


def test_b2_an_unknown_stage_scopes_to_its_own_tag_and_empty_means_nothing():
    # An UNKNOWN stage must NOT silently lose scoping -- it falls back to its own
    # upper-cased name so a stage added later is scoped to its own lessons.
    for stage in ("auditor", "release_manager", "pm_scout_c", "Weird_Stage"):
        assert foundry.stage_role_tags(stage) == (stage.upper(),), \
            f"unknown stage {stage!r} must fall back to (stage.upper(),), never ()"
    for empty in ("", None):
        assert foundry.stage_role_tags(empty) == (), f"{empty!r} -> ()"
    # every tag the map yields is itself a legal lesson tag (round-trips through b1)
    for stage, tags in _STAGE_MAP.items():
        for tag in tags:
            assert foundry.lesson_role_tag(f"- [{tag} iter1] x") == tag, \
                f"{tag!r} from stage {stage!r} is not a legal lesson tag"


# ==========================================================================
# fixture builders (mirror tests/test_iter104_behavior.py conventions)
# ==========================================================================
def _lesson(i, tag, length=None):
    """A role-tagged lesson line with a unique marker, optionally padded to `length`."""
    line = f"- [{tag} iter{i:03d}] {_marker(i)} durable detail text"
    if length is not None:
        assert length >= len(line), (length, len(line))
        line = line + "y" * (length - len(line))
    return line


def _marker(i):
    return f"mark-{i:03d}"


def _log(lessons):
    """A patterns head plus a chronological lessons tail, as the real log is shaped."""
    return ("## Patterns\n\n"
            "Read this head first; the tail is the full history.\n\n"
            "- a durable cross-role rule\n\n"
            "## Recent lessons\n\n" + "\n".join(lessons) + "\n")


def _emitted(digest):
    """The lesson lines a digest actually emitted, in emission order."""
    return [ln for ln in digest.splitlines() if ln.lstrip().startswith("- [")]


def _header(digest):
    """(K, M) from the `## Recent lessons (last K of M)` header, as ints."""
    m = re.search(r"## Recent lessons \(last (\d+) of (\d+)\)", digest)
    assert m, f"no `## Recent lessons (last K of M)` header in:\n{digest}"
    return int(m.group(1)), int(m.group(2))


# A multi-role log: 6 on-role (PM) lessons OLDEST, then 20 off-role ones, so the
# strict-chronological newest-10 window holds ZERO on-role lessons -- the exact
# starvation the spec's `## Why` measured on this iteration's own PM prompt.
_ON_ROLE = tuple(range(1, 7))
_OFF_ROLE = tuple(range(7, 27))
MULTI_ROLE_LOG = _log([_lesson(i, "PM") for i in _ON_ROLE]
                      + [_lesson(i, "TEST") for i in _OFF_ROLE])
TOTAL_LESSONS = len(_ON_ROLE) + len(_OFF_ROLE)


# ==========================================================================
# Behavior 3 -- default-off is BYTE-identical
# ==========================================================================
def test_b3_default_off_is_byte_identical():
    K = 10
    base = foundry.learnings_digest(MULTI_ROLE_LOG, recent=K)
    variants = {
        "role_tags=None": dict(role_tags=None),
        "role_tags=()": dict(role_tags=()),
        "role_reserve=0": dict(role_tags=("PM",), role_reserve=0),
        "role_tags=None,role_reserve=4": dict(role_tags=None, role_reserve=4),
        "role_tags=(),role_reserve=4": dict(role_tags=(), role_reserve=4),
    }
    for label, kw in variants.items():
        got = foundry.learnings_digest(MULTI_ROLE_LOG, recent=K, **kw)
        assert got == base, f"{label} moved the digest; default-off must not"
    # non-vacuity: the fixture is one where scoping DOES change the output, so the
    # five equalities above are statements about the defaults, not about a flat log.
    scoped = foundry.learnings_digest(MULTI_ROLE_LOG, recent=K,
                                      role_tags=("PM",), role_reserve=4)
    assert scoped != base, \
        "fixture is degenerate: scoping changes nothing, so b3 would pass vacuously"


# ==========================================================================
# Behavior 4 -- reservation is COUNT-PRESERVING and in DOCUMENT order
# ==========================================================================
@pytest.mark.parametrize("K,R", [(10, 4), (10, 1), (12, 6), (8, 7), (26, 5)])
def test_b4_reservation_is_count_preserving_and_document_ordered(K, R):
    assert 0 < R < K
    base = _emitted(foundry.learnings_digest(MULTI_ROLE_LOG, recent=K))
    got = _emitted(foundry.learnings_digest(MULTI_ROLE_LOG, recent=K,
                                            role_tags=("PM",), role_reserve=R))
    want_n = min(K, TOTAL_LESSONS)
    assert len(got) == want_n, f"emitted {len(got)} lesson lines, want exactly {want_n}"
    # the newest K-R any-role lessons are all still present
    newest_any = base[-(K - R):] if K - R else []
    missing = [ln for ln in newest_any if ln not in got]
    assert not missing, f"the newest {K - R} any-role lessons were dropped: {missing}"
    # DOCUMENT (ascending) order, never grouped by role
    order = [MULTI_ROLE_LOG.index(ln) for ln in got]
    assert order == sorted(order), f"lines are not in document order: {got}"
    # exactly R on-role lessons that the UNSCOPED window omitted, when the log has them
    older_on_role = [_lesson(i, "PM") for i in _ON_ROLE if _lesson(i, "PM") not in base]
    gained = [ln for ln in got if ln not in base]
    assert len(gained) == min(R, len(older_on_role)), \
        f"gained {len(gained)} previously-omitted lessons, want {min(R, len(older_on_role))}"
    for ln in gained:
        assert foundry.lesson_role_tag(ln) == "PM", f"a gained line is off-role: {ln}"
        assert ln in older_on_role, f"a gained line is not an OLDER on-role lesson: {ln}"
    # the gained ones are the NEWEST of the older on-role lessons
    if gained:
        assert gained == older_on_role[-len(gained):], \
            "the reserve must take the NEWEST of the older on-role lessons"


# ==========================================================================
# Behavior 5 -- nothing is paid when there is nothing to gain
# ==========================================================================
def test_b5_zero_on_role_lessons_is_byte_identical():
    log = _log([_lesson(i, "TEST") for i in range(1, 27)])
    base = foundry.learnings_digest(log, recent=10)
    for tags in (("PM",), ("PM", "PM_SCOUT_A"), ("NOSUCHROLE",)):
        got = foundry.learnings_digest(log, recent=10, role_tags=tags, role_reserve=4)
        assert got == base, f"role_tags={tags} moved a digest with zero on-role lessons"


@pytest.mark.parametrize("n_older_on_role", [0, 1, 2, 3])
def test_b5_short_reserve_refills_and_never_duplicates(n_older_on_role):
    """Fewer than R older on-role lessons -> the unused slots refill with the
    next-newest any-role lessons, so the emitted COUNT still equals the unscoped
    count, and no lesson is emitted twice."""
    K, R = 10, 4
    tags = ["TEST"] * 26
    for j in range(n_older_on_role):          # oldest indices, well outside the window
        tags[j] = "PM"
    tags[24] = "PM"                            # one on-role lesson INSIDE the window
    log = _log([_lesson(i, t) for i, t in enumerate(tags, 1)])

    base = _emitted(foundry.learnings_digest(log, recent=K))
    got = _emitted(foundry.learnings_digest(log, recent=K,
                                            role_tags=("PM",), role_reserve=R))
    assert len(got) == len(base) == K, \
        f"count moved: unscoped {len(base)}, scoped {len(got)}, K={K}"
    assert len(set(got)) == len(got), f"a lesson was emitted twice: {got}"
    gained = [ln for ln in got if ln not in base]
    assert len(gained) == n_older_on_role, \
        f"expected {n_older_on_role} older on-role lesson(s) pulled in, got {len(gained)}"
    # the in-window on-role lesson did NOT consume a reserve slot: it is still there
    inside = _lesson(25, "PM")
    assert inside in base and inside in got, \
        "an on-role lesson already inside the newest window must survive, not be re-paid"
    # the refill came from the next-newest ANY-role lessons, i.e. the emitted set is
    # still a contiguous newest-suffix once the gained older lines are removed
    suffix = [ln for ln in got if ln not in gained]
    assert suffix == base[-len(suffix):], \
        f"the unused reserve slots did not refill with the next-newest lessons: {suffix}"


# ==========================================================================
# Behavior 6 -- build_prompt opts in AT CALL TIME
# ==========================================================================
def _cfg_with_learnings(tmp_path, file_text):
    """Load a throwaway config and seed cfg.learnings with `file_text`.

    Everything lives under tmp_path, so no assertion here can depend on this
    machine's ambient (gitignored) product state -- the trap that took a shipped
    iteration post-release BROKEN in a fresh clone.
    """
    import json
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    cfg = foundry.load_config(str(cfg_path))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(file_text)
    return cfg


def _prompt(cfg, stage):
    it_dir = cfg.state / "iter-999"
    return foundry.build_prompt(cfg, 999, stage, f"{stage}.md",
                                it_dir / f"{stage}.md", it_dir, "")


def test_b6_the_constant_exists_next_to_its_siblings():
    assert isinstance(foundry.PROMPT_LEARNINGS_ROLE_RESERVE, int)
    assert foundry.PROMPT_LEARNINGS_ROLE_RESERVE == 4, \
        "the spec pins the default reserve at 4 of the tail slots"
    K = foundry.PROMPT_LEARNINGS_RECENT
    assert 0 < foundry.PROMPT_LEARNINGS_ROLE_RESERVE < K, \
        f"the reserve ({foundry.PROMPT_LEARNINGS_ROLE_RESERVE}) must be a PART of the {K}-slot tail"


def test_b6_build_prompt_pulls_an_on_role_lesson_without_moving_the_count(tmp_path):
    K = foundry.PROMPT_LEARNINGS_RECENT
    # newest-K window holds ZERO `[PM ` lessons, but older ones exist
    on_role = [_lesson(i, "PM") for i in range(1, 7)]
    off_role = [_lesson(i, "TEST") for i in range(7, 7 + 2 * K)]
    cfg = _cfg_with_learnings(tmp_path, _log(on_role + off_role))

    built = _prompt(cfg, "pm")
    lines = _emitted(built)
    pm_lines = [ln for ln in lines if ln.lstrip().startswith("- [PM iter")]
    assert pm_lines, ("the pm stage's prompt carries no `- [PM iter` lesson even "
                      "though the log holds six older ones")

    # count-preserving against the SAME prompt built with the reserve switched off
    saved = foundry.PROMPT_LEARNINGS_ROLE_RESERVE
    try:
        foundry.PROMPT_LEARNINGS_ROLE_RESERVE = 0
        unscoped = _emitted(_prompt(cfg, "pm"))
    finally:
        foundry.PROMPT_LEARNINGS_ROLE_RESERVE = saved
    assert len(lines) == len(unscoped), \
        f"scoped prompt emitted {len(lines)} lessons, unscoped {len(unscoped)}"
    assert not [ln for ln in unscoped if ln.lstrip().startswith("- [PM iter")], \
        "fixture is degenerate: the unscoped window already held a PM lesson"


def test_b6_both_globals_are_read_inside_the_function(tmp_path, monkeypatch):
    """monkeypatch on PROMPT_LEARNINGS_ROLE_RESERVE and on stage_role_tags must
    move the built prompt with NO re-import -- i.e. both are read at call time."""
    K = foundry.PROMPT_LEARNINGS_RECENT
    on_role = [_lesson(i, "PM") for i in range(1, 7)]
    off_role = [_lesson(i, "TEST") for i in range(7, 7 + 2 * K)]
    cfg = _cfg_with_learnings(tmp_path, _log(on_role + off_role))

    # (a) the CONSTANT is read at call time
    with_reserve = _prompt(cfg, "pm")
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_ROLE_RESERVE", 0)
    without = _prompt(cfg, "pm")
    assert with_reserve != without, \
        "PROMPT_LEARNINGS_ROLE_RESERVE is not read inside build_prompt (captured at def time?)"
    monkeypatch.setattr(foundry, "PROMPT_LEARNINGS_ROLE_RESERVE", 4)

    # (b) the FUNCTION is read at call time: scope the pm stage to TEST instead
    monkeypatch.setattr(foundry, "stage_role_tags", lambda stage: ("TEST",))
    as_test = _prompt(cfg, "pm")
    assert as_test != with_reserve, \
        "stage_role_tags is not read inside build_prompt (captured at def time?)"
    assert not [ln for ln in _emitted(as_test) if ln.lstrip().startswith("- [PM iter")], \
        "re-scoping the pm stage to TEST still pulled a PM lesson in"


# ==========================================================================
# Behavior 7 -- composition runs BEFORE the existing bounds
# ==========================================================================
def test_b7_bounds_still_hold_and_the_header_counts_what_was_emitted():
    K, R = 10, 4
    LEN = 200
    log = _log([_lesson(i, "PM", LEN) for i in _ON_ROLE]
               + [_lesson(i, "TEST", LEN) for i in _OFF_ROLE])
    lesson_chars, max_chars = 80, 400
    d = foundry.learnings_digest(log, recent=K, lesson_chars=lesson_chars,
                                max_chars=max_chars,
                                role_tags=("PM",), role_reserve=R)
    lines = _emitted(d)
    assert lines, "the bounded digest emitted no lesson lines at all"
    for ln in lines:
        assert len(ln) <= lesson_chars, f"lesson over the per-lesson cap: {len(ln)}"
    assert sum(len(ln) for ln in lines) <= max_chars, \
        f"lessons total {sum(len(ln) for ln in lines)} chars, cap {max_chars}"
    k, m = _header(d)
    assert k == len(lines), f"header says last {k}, but {len(lines)} lesson lines shipped"
    assert m == TOTAL_LESSONS, f"header says of {m}, but the log holds {TOTAL_LESSONS}"


def test_b7_a_generous_budget_keeps_the_reserved_on_role_lessons():
    """With budgets set WIDE, the composition still happened -- so the ordering
    (compose, then bound) is observable rather than an accident of a tight cap."""
    K, R = 10, 4
    d = foundry.learnings_digest(MULTI_ROLE_LOG, recent=K,
                                 lesson_chars=500, max_chars=100_000,
                                 role_tags=("PM",), role_reserve=R)
    lines = _emitted(d)
    assert len(lines) == K, f"emitted {len(lines)} lesson lines, want {K}"
    on_role = [ln for ln in lines if foundry.lesson_role_tag(ln) == "PM"]
    assert len(on_role) == R, f"{len(on_role)} on-role lessons survived, want {R}"
    k, m = _header(d)
    assert (k, m) == (len(lines), TOTAL_LESSONS), (k, m, len(lines), TOTAL_LESSONS)


# ==========================================================================
# Acceptance criteria decidable from TRACKED text alone (so every verdict still
# holds in the throwaway fresh clone the release gate verifies from)
# ==========================================================================
THIS_ITER = 232
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
ALLOW_LIST_MODULE = _ROOT / "tests" / "test_iter204_behavior.py"


def test_ac_the_public_surface_named_by_the_criteria_exists():
    for name in ("lesson_role_tag", "stage_role_tags", "learnings_digest",
                 "build_prompt", "PROMPT_LEARNINGS_ROLE_RESERVE"):
        assert hasattr(foundry, name), f"foundry.{name} is missing"
    import inspect
    params = inspect.signature(foundry.learnings_digest).parameters
    for new in ("role_tags", "role_reserve"):
        assert new in params, f"learnings_digest is missing the {new} parameter"
        assert params[new].kind is inspect.Parameter.KEYWORD_ONLY, \
            f"{new} must be KEYWORD-ONLY so no positional caller can move"
        assert params[new].default in (None, 0), \
            f"{new} must default to a falsy value so existing callers are unmoved"


def test_ac_both_roadmap_records_land_in_this_same_diff():
    gaps = foundry.roadmap_ledger_gaps(ROADMAP.read_text(encoding="utf-8"),
                                       ARCHIVE.read_text(encoding="utf-8"),
                                       (THIS_ITER,))
    assert gaps == [], f"iteration(s) recorded in NEITHER roadmap file: {gaps}"
    rows = [ln for ln in ROADMAP.read_text(encoding="utf-8").splitlines()
            if ln.startswith(f"- iter {THIS_ITER} ")]
    assert len(rows) == 1, f"expected exactly one iter-{THIS_ITER} ledger row, got {len(rows)}"
    assert len(rows[0]) <= 120, f"the ledger row is {len(rows[0])} chars (max 120)"
    bullets = [ln for ln in ARCHIVE.read_text(encoding="utf-8").splitlines()
               if ln.startswith(f"- **iter {THIS_ITER} ")]
    assert len(bullets) == 1, f"expected exactly one iter-{THIS_ITER} archive bullet"


def test_ac_this_module_is_on_the_b15_allow_list():
    needle = f'"tests/{pathlib.Path(__file__).name}"'
    assert needle in ALLOW_LIST_MODULE.read_text(encoding="utf-8"), (
        f"{needle} must be allow-listed in {ALLOW_LIST_MODULE.name}, or the "
        "literal-class brake reds inside the gate's staging window")


def test_ac_both_top_level_modules_import_in_process():
    import dispatcher
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert callable(getattr(foundry, "main", None)), \
        "foundry must keep its public entry point"


def test_ac_this_module_spells_no_absolute_machine_path():
    """The banned shapes are ASSEMBLED, never spelled -- a literal leak-guard
    pattern written out in full makes this very test its own first finding (the
    self-matching-brake shape that reverted iteration 205 and cost 231 a round)."""
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    sep = "/"
    banned = [sep + "Users" + sep, sep + "home" + sep, "C:" + chr(92)]
    for shape in banned:
        assert shape not in src, f"absolute machine path shape {shape!r} in a shipped test"
    # non-vacuity: the detector really does detect, proven on synthetic text
    for shape in banned:
        assert shape in f"prefix {shape}someone/x suffix"
