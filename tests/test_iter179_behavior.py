"""Black-box behaviour tests for iter 179 -- git ship-truth OVERRIDES a stale `ACTION` line in the
tracked `DIRECTIONS.md` decision log, the newest (not-yet-decided) row stops asserting `unknown`,
and a `directions_ship_gaps` brake names any row still claiming `unknown` for an iteration git
PROVES shipped.

Spec: products/_platform/state/iter-179/pm.md, Expected Behaviors 1-13.

  1. `PUSHED <sha>` / `PUSHED` preserved (an explicit PUSHED verdict is authoritative).
  2. `REVERTED` outranks a matching git subject.
  3. Missing / empty / `PENDING` action + a matching subject -> `PUSHED (per git)`.
  4. Newest row, no matching subject -> `pending (not yet decided)`.
  5. Every remaining case -> `unknown` (the 7 honest unknowns keep it).
  6. `ship_subjects == ()` (missing infrastructure) -> byte-identical to today's `_ship_label`.
  7. Iteration matching is EXACT on the number, never a substring.
  8. `DirectionsDigest.render()` emits the new label and is otherwise byte-identical.
  9. `directions_ship_gaps(text, subjects)` -> one finding per lying row, naming the iteration.
 10. Two-sided calibration on real data: flags 118 and 177, NOT the 7 honest unknowns.
 11. `directions_ship_gaps(text, ())` -> `()`: the brake SKIPS on missing infrastructure.
 12. `gather_directions` gets truth via the BARE-NAME `git_ship_subjects` seam; the core is PURE;
     `render_directions_doc` / `DirectionsDigest.render` gain NO parameter.
 13. `refresh_directions_file` stays swallow-safe when the seam raises.

PROVENANCE (read this before editing): these 24 tests are iteration 178's tester module RE-LANDED
VERBATIM from `products/_platform/state/iter-178/UNGATED_tests_test_iter178_behavior.py`, as the
pinned `GATE 2026-08-14c` directive orders.  They were `RESULT: PASS` over two independent runs
there.  The engineer restored them because the implementation they cover was re-applied from the
same preserved patch; they are NOT newly authored here.

WHAT WAS DELIBERATELY DROPPED, AND WHY IT MUST NOT COME BACK: iteration 178's four `test_b14_*`
tests asserted on the CONTENT of the LIVE repo-root `DIRECTIONS.md`.  The orchestrator regenerates
that file immediately before every final stage using the `foundry` module the dispatcher imported
at launch, so those four tests were green for the engineer, reviewer and tester and RED for the
gate -- and iteration 178 reverted on exactly that with every other gate green.  Never pin the
content of a file the orchestrator also writes.  Iteration 179's spec replaces them with
behaviors 14-16, a `tmp_path`-hermetic end-to-end proof plus a scan asserting no test reads a
repo-root machine-written artifact; those belong to the TEST ENGINEER, not here.

Offline and deterministic: no network, no subprocess, no git, no agent run, no sleeps, no clock.
NOTHING outside `tmp_path` is written and NO ambient path is read, so a fresh-clone verify cannot
go red and no assertion depends on gitignored state (`state/`, `LEARNINGS.md`, iteration dirs).

XDIST-SAFETY: all mutation is `monkeypatch`-scoped and process-local, safe under `-n auto`.
"""
from __future__ import annotations

import dataclasses
import inspect
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

PER_GIT = "PUSHED (per git)"
PENDING = "pending (not yet decided)"
UNKNOWN = "unknown"
REVERTED = "REVERTED"

# Measured by the PM stage from the tracked log cross-joined with `git log --format=%s`.
HONEST_UNKNOWNS = (108, 109, 123, 150, 161, 171, 172)
GIT_PROVEN_SHIPPED = (118, 177)
STALE_ACTIONS = (None, "", "PENDING")


# --------------------------------------------------------------------------- helpers
def _entry(iteration, action=None, sha=None):
    return foundry.DirectionsEntry(
        iteration=iteration,
        lenses=("performance-and-throughput",),
        candidates=("Candidate A1 -- something",),
        winner="A1",
        action=action,
        sha=sha,
    )


def _subject(n) -> str:
    """A commit subject in the loop's own shape."""
    return "chore: some change (foundry iter " + str(n) + ")"


def _digest(entries, subjects=()):
    return foundry.DirectionsDigest(product="p", entries=tuple(entries), ship_subjects=tuple(subjects))


def _label(entry, subjects=(), newest=None):
    return foundry.directions_ship_label(entry, subjects, newest)


def _log_text(rows) -> str:
    """Render a DIRECTIONS.md-shaped document from (iteration, ship_label) pairs."""
    out = ["foundry directions -- p"]
    for iteration, ship in rows:
        out += [
            "  iter-" + str(iteration),
            "    lenses: performance-and-throughput",
            "    - Candidate A1 -- something",
            "    winner: A1",
            "    ship: " + ship,
        ]
    out.append(str(len(rows)) + " scouted iterations")
    return "\n".join(out) + "\n"


def _ship_lines(text):
    return [ln for ln in text.splitlines() if ln.strip().startswith("ship:")]


def _ship_label_of(text, iteration):
    """Anchored parse: the `ship:` line inside the `iter-<n>` block, or None."""
    want = "iter-" + str(iteration)
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("iter-"):
            inside = stripped == want
        elif inside and stripped.startswith("ship:"):
            return stripped.split("ship:", 1)[1].strip()
    return None


def _tmp_cfg(tmp_path):
    repo = tmp_path / "repo"
    work = tmp_path / "work"
    (repo / "x").mkdir(parents=True)
    (work / "state").mkdir(parents=True)
    return foundry.ProductConfig(
        name="probe", repo=str(repo), allowed_push_repo="probe-repo", work_root=str(work)
    )


# --------------------------------------------------------------- Behaviour 1
def test_b1_explicit_pushed_verdict_is_preserved():
    assert _label(_entry(50, "PUSHED", "abc1234")) == "PUSHED abc1234"
    assert _label(_entry(50, "PUSHED", "")) == "PUSHED"
    assert _label(_entry(50, "PUSHED", None)) == "PUSHED"
    # ...and a matching git subject does not perturb it.
    subs = (_subject(50),)
    assert _label(_entry(50, "PUSHED", "abc1234"), subs, 99) == "PUSHED abc1234"
    assert _label(_entry(50, "PUSHED", None), subs, 99) == "PUSHED"


# --------------------------------------------------------------- Behaviour 2
def test_b2_reverted_outranks_a_matching_git_subject():
    subs = (_subject(50),)
    assert _label(_entry(50, "REVERTED", None), subs, 99) == REVERTED
    assert _label(_entry(50, "REVERTED", "abc1234"), subs, 99) == REVERTED
    # A revert can still leave an unrelated commit: the explicit decision wins.
    assert _label(_entry(50, "REVERTED", None), subs, 50) == REVERTED


# --------------------------------------------------------------- Behaviour 3
@pytest.mark.parametrize("action", STALE_ACTIONS)
def test_b3_stale_action_plus_matching_subject_reads_per_git(action):
    subs = ("feat: unrelated (foundry iter 7)", _subject(118))
    assert _label(_entry(118, action), subs, 178) == PER_GIT


def test_b3_any_other_action_token_also_defers_to_git():
    """The spec says "anything else (missing, empty, `PENDING`)" -- an unrecognised token is
    "anything else" too, and today's `_ship_label` already calls it `unknown`, so deferring to
    git cannot regress a decided verdict."""
    subs = (_subject(118),)
    assert foundry.DirectionsDigest._ship_label(_entry(118, "SKIPPED")) == UNKNOWN
    assert _label(_entry(118, "SKIPPED"), subs, 178) == PER_GIT


# --------------------------------------------------------------- Behaviour 4
@pytest.mark.parametrize("action", STALE_ACTIONS)
def test_b4_newest_row_with_no_matching_subject_is_pending(action):
    subs = (_subject(177), _subject(176))
    assert _label(_entry(178, action), subs, 178) == PENDING


def test_b4_pending_is_rendered_for_the_highest_iteration_in_the_log():
    """Observable at the render level: the newest block, and only it, reads pending."""
    text = _digest([_entry(178), _entry(150), _entry(149)], (_subject(1),)).render()
    assert _ship_label_of(text, 178) == PENDING
    assert _ship_label_of(text, 150) == UNKNOWN
    assert _ship_label_of(text, 149) == UNKNOWN


# --------------------------------------------------------------- Behaviour 5
def test_b5_the_seven_honest_unknowns_keep_reading_unknown():
    subs = tuple(_subject(n) for n in GIT_PROVEN_SHIPPED)
    for n in HONEST_UNKNOWNS:
        for action in STALE_ACTIONS:
            assert _label(_entry(n, action), subs, 178) == UNKNOWN, (n, action)


def test_b5_a_non_newest_row_without_proof_is_unknown_not_pending():
    assert _label(_entry(150), (_subject(177),), 178) == UNKNOWN
    # No newest known at all -> still the conservative label.
    assert _label(_entry(150), (_subject(177),), None) == UNKNOWN


# --------------------------------------------------------------- Behaviour 6
def test_b6_empty_subjects_is_byte_identical_to_todays_label():
    """Missing infrastructure must neither upgrade nor downgrade any row."""
    shapes = [
        _entry(118, "PUSHED", "abc1234"),
        _entry(118, "PUSHED", ""),
        _entry(118, "PUSHED", None),
        _entry(118, "REVERTED", None),
        _entry(118, "REVERTED", "abc1234"),
        _entry(118, None),
        _entry(118, ""),
        _entry(118, "PENDING"),
        _entry(178, "PENDING"),
        _entry(178, None),
    ]
    for e in shapes:
        old = foundry.DirectionsDigest._ship_label(e)
        for newest in (None, 178, e.iteration):
            assert _label(e, (), newest) == old, (e.iteration, e.action, e.sha, newest)


def test_b6_missing_infrastructure_outranks_the_pending_nicety():
    """Behaviours 4 and 6 collide for the newest row when subjects is `()`.  6 is the
    missing-infrastructure INVARIANT, 4 is a rendering nicety, so 6 must win -- and it does.
    Recorded as the tested reading of a spec ambiguity (see tester.md)."""
    assert _label(_entry(178, None), (), 178) == UNKNOWN
    assert _label(_entry(178, None), (), 178) == foundry.DirectionsDigest._ship_label(_entry(178, None))


def test_b6_render_with_no_subjects_matches_the_legacy_labels_everywhere():
    entries = [_entry(178), _entry(177, "PUSHED", "a5da0f7"), _entry(118, "PENDING"), _entry(150)]
    text = _digest(entries, ()).render()
    for e in entries:
        assert _ship_label_of(text, e.iteration) == foundry.DirectionsDigest._ship_label(e)


# --------------------------------------------------------------- Behaviour 7
def test_b7_iteration_matching_is_exact_not_substring():
    subs = (_subject(118),)
    assert _label(_entry(118, None), subs, 2000) == PER_GIT
    for other in (11, 18, 1180, 1118, 8):
        assert _label(_entry(other, None), subs, 2000) == UNKNOWN, other
    # ...and the converse direction: a longer number must not satisfy a shorter entry.
    assert _label(_entry(118, None), (_subject(1180),), 2000) == UNKNOWN
    assert _label(_entry(118, None), (_subject(11),), 2000) == UNKNOWN


def test_b7_subject_must_carry_the_loops_own_marker():
    """A bare number somewhere in a subject is not proof of a ship."""
    assert _label(_entry(118, None), ("fix: bump 118 things",), 2000) == UNKNOWN


# --------------------------------------------------------------- Behaviour 8
def test_b8_render_differs_from_the_no_git_render_only_on_ship_lines():
    entries = [_entry(178), _entry(177, "PUSHED", "a5da0f7"), _entry(118, "PENDING"), _entry(150)]
    subs = tuple(_subject(n) for n in GIT_PROVEN_SHIPPED)
    base = _digest(entries, ()).render()
    with_git = _digest(entries, subs).render()
    b_lines, g_lines = base.splitlines(), with_git.splitlines()
    assert len(b_lines) == len(g_lines)
    differing = [(a, b) for a, b in zip(b_lines, g_lines) if a != b]
    assert differing, "the git-aware render must change SOMETHING"
    for a, b in differing:
        assert a.strip().startswith("ship:") and b.strip().startswith("ship:"), (a, b)
    # Everything else -- header, iter-NN, lenses, candidates, winner, rollup -- is byte-identical.
    assert [ln for ln in b_lines if not ln.strip().startswith("ship:")] == [
        ln for ln in g_lines if not ln.strip().startswith("ship:")
    ]


def test_b8_render_emits_exactly_the_behaviour_1_to_7_label_on_every_row():
    entries = [_entry(178), _entry(177, "PUSHED", "a5da0f7"), _entry(118, "PENDING"),
               _entry(172), _entry(150), _entry(120, "REVERTED")]
    subs = tuple(_subject(n) for n in (118, 177, 120))
    digest = _digest(entries, subs)
    text = digest.render()
    newest = max(e.iteration for e in entries)
    for e in entries:
        assert _ship_label_of(text, e.iteration) == _label(e, subs, newest), e.iteration
    assert len(_ship_lines(text)) == len(entries)
    assert text.startswith("foundry directions -- p")
    assert text.rstrip().endswith("scouted iterations")


# --------------------------------------------------------------- Behaviours 9-11
def test_b9_gaps_names_the_lying_iteration_and_returns_empty_when_clean():
    text = _log_text([(178, PENDING), (118, UNKNOWN), (150, UNKNOWN)])
    findings = foundry.directions_ship_gaps(text, (_subject(118),))
    assert isinstance(findings, tuple)
    assert len(findings) == 1
    assert "118" in findings[0]
    assert "150" not in findings[0]
    # Clean: nothing proven shipped among the unknown rows.
    assert foundry.directions_ship_gaps(text, (_subject(999),)) == ()


def test_b9_a_decided_row_is_never_flagged():
    text = _log_text([(178, PENDING), (177, "PUSHED a5da0f7"), (120, REVERTED), (118, PER_GIT)])
    subs = tuple(_subject(n) for n in (177, 120, 118, 178))
    assert foundry.directions_ship_gaps(text, subs) == ()


def test_b10_two_sided_calibration_on_the_real_measured_data():
    rows = [(178, PENDING)] + [(n, UNKNOWN) for n in sorted(
        set(HONEST_UNKNOWNS) | set(GIT_PROVEN_SHIPPED), reverse=True)]
    text = _log_text(rows)
    subs = tuple(_subject(n) for n in GIT_PROVEN_SHIPPED)
    findings = foundry.directions_ship_gaps(text, subs)
    assert len(findings) == len(GIT_PROVEN_SHIPPED), findings
    blob = " || ".join(findings)
    for n in GIT_PROVEN_SHIPPED:
        assert str(n) in blob, (n, blob)
    for n in HONEST_UNKNOWNS:
        assert not any(_finding_names(f, n) for f in findings), (n, findings)


def _finding_names(finding, iteration):
    """Whole-number containment, so 118 does not 'name' 11 or 1180."""
    import re

    return bool(re.search(r"(?<!\d)" + str(iteration) + r"(?!\d)", finding))


def test_b11_gaps_skips_on_missing_infrastructure():
    text = _log_text([(178, PENDING), (118, UNKNOWN), (150, UNKNOWN)])
    assert foundry.directions_ship_gaps(text, ()) == ()
    assert foundry.directions_ship_gaps("", ()) == ()
    assert foundry.directions_ship_gaps("", (_subject(118),)) == ()


# --------------------------------------------------------------- Behaviour 12
def test_b12_gather_directions_uses_the_bare_name_git_seam(monkeypatch, tmp_path):
    scripted = (_subject(118), _subject(177))
    calls = []

    def fake(repo_dir):
        calls.append(repo_dir)
        return scripted

    monkeypatch.setattr(foundry, "git_ship_subjects", fake)
    cfg = _tmp_cfg(tmp_path)
    digest = foundry.gather_directions(cfg)
    assert calls, "gather_directions must call git_ship_subjects by its BARE module name"
    assert tuple(digest.ship_subjects) == scripted


def test_b12_the_pure_core_performs_no_io(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("the pure core called git")

    monkeypatch.setattr(foundry, "git_ship_subjects", boom)
    monkeypatch.setattr(foundry.subprocess, "run", boom)
    subs = (_subject(118),)
    assert _label(_entry(118, None), subs, 178) == PER_GIT
    assert foundry.directions_ship_gaps(_log_text([(118, UNKNOWN)]), subs) != ()
    assert _digest([_entry(118, "PENDING")], subs).render()


def test_b12_render_signatures_gained_no_parameter():
    assert list(inspect.signature(foundry.DirectionsDigest.render).parameters) == ["self"]
    assert len(inspect.signature(foundry.render_directions_doc).parameters) == 1
    names = [f.name for f in dataclasses.fields(foundry.DirectionsDigest)]
    assert names == ["product", "entries", "ship_subjects"]
    default = [f for f in dataclasses.fields(foundry.DirectionsDigest) if f.name == "ship_subjects"][0].default
    assert default == (), "the seam field must default to the missing-infrastructure case"


def test_b12_render_doc_wraps_the_digest_render_unchanged():
    """`render_directions_doc` adds only its pre-existing markdown title -- the git-aware body it
    wraps is the digest's own render, byte-for-byte."""
    subs = (_subject(118),)
    digest = _digest([_entry(178), _entry(118, "PENDING")], subs)
    doc = foundry.render_directions_doc(digest)
    body = digest.render()
    assert body in doc
    assert doc.endswith(body) or doc.endswith(body + "\n")
    assert _ship_label_of(doc, 118) == PER_GIT
    assert _ship_label_of(doc, 178) == PENDING


# --------------------------------------------------------------- Behaviour 13
def test_b13_refresh_is_swallow_safe_when_the_seam_raises(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(foundry, "git_ship_subjects", boom)
    cfg = _tmp_cfg(tmp_path)
    result = foundry.refresh_directions_file(cfg)
    assert isinstance(result, bool)


# ============================================================ Behaviours 14-16 (TEST ENGINEER)
# Iteration 178's four LIVE-ARTIFACT tests are deliberately absent (module docstring).  These are
# their hermetic replacement: the same end-to-end healing proved on a `tmp_path` fixture, plus a
# scan that stops any future test from pinning the CONTENT of a machine-written artifact again.
#
# NAMING NOTE (spec ambiguity -- reported in tester.md): behaviour 16 asks that "the four
# `test_b14_*` tests of iteration 178 are ABSENT", while behaviour 14 legitimately owns the
# `test_b14_` prefix.  A NAME therefore cannot be the oracle; the PROPERTY is, and it is measured
# over `tests/**/*.py` INCLUDING this module (`test_b16_*` below).
#
# The scan is AST-based on purpose: a text scan cannot tell a CALL from a SENTENCE about a call,
# and this module's own docstrings discuss the shape they forbid.

_ARTIFACTS = ("DIRECTIONS.md", "AGENTS.md")
_ROOT_ANCHORS = ("_ROOT", "parents[1]", "parents[ 1 ]", "ROOT /")
_FIXTURE_ANCHORS = ("cfg.repo", "tmp_path", "cfg_repo", "repo_dir")
_READERS = ("read_text", "read_bytes", "open")

# Planted samples, ASSEMBLED so the banned shape never appears contiguously in THIS file -- the
# self-domain discipline `tests/test_iter175_behavior.py` established.
_ART = "DIRECTIO" + "NS.md"
_BAD_CONSTANT_FORM = (
    "import pathlib\n"
    "_ROOT = pathlib.Path(__file__).resolve().parents[1]\n"
    "PINNED = _ROOT / \"" + _ART + "\"\n"
    "def test_x():\n"
    "    assert \"ship:\" in PINNED.read_text()\n"
)
_BAD_INLINE_FORM = (
    "import pathlib\n"
    "_ROOT = pathlib.Path(__file__).resolve().parents[1]\n"
    "def test_y():\n"
    "    text = (_ROOT / \"" + _ART + "\").read_text()\n"
    "    assert text\n"
)
_BAD_BUILTIN_OPEN_FORM = (
    "import pathlib\n"
    "_ROOT = pathlib.Path(__file__).resolve().parents[1]\n"
    "def test_v():\n"
    "    with open(_ROOT / \"" + _ART + "\") as fh:\n"
    "        assert fh.read()\n"
)
_GOOD_FIXTURE_FORM = (
    "import pathlib\n"
    "def test_z(cfg):\n"
    "    text = (pathlib.Path(cfg.repo) / \"" + _ART + "\").read_text()\n"
    "    assert text\n"
)
_GOOD_PROSE_FORM = (
    "\"\"\"Prose naming " + _ART + " and the repo root -- a sentence is not a pin.\"\"\"\n"
    "def test_w():\n"
    "    assert True\n"
)
# The two shapes the FIRST version of this scan missed (measured, not imagined): a repo root held
# under any name but `_ROOT`, read directly and via a second constant.
_BAD_ROOT_ALIAS_FORM = (
    "import pathlib\n"
    "REPO = pathlib.Path(__file__).resolve().parents[1]\n"
    "def test_u():\n"
    "    assert (REPO / \"" + _ART + "\").read_text()\n"
)
_BAD_ALIAS_TWO_HOP_FORM = (
    "import pathlib\n"
    "HERE = pathlib.Path(__file__).resolve().parents[1]\n"
    "PINNED_LOG = HERE / \"" + _ART + "\"\n"
    "def test_t():\n"
    "    assert PINNED_LOG.read_text()\n"
)
# ... and the false positive that alias tracking could have introduced: one NAME used as a root
# alias in one place and as a tmp_path fixture in another must stay clean.
_GOOD_SHADOWED_ALIAS_FORM = (
    "import pathlib\n"
    "p = pathlib.Path(__file__).resolve().parents[1] / \"foundry.py\"\n"
    "def test_s(tmp_path):\n"
    "    p = tmp_path\n"
    "    assert (p / \"" + _ART + "\").read_text()\n"
)


def _fixture_cfg(tmp_path):
    """A product config whose `repo`/`work_root` are TMP dirs, loaded through the PUBLIC
    `load_config` -- the convention `tests/test_iter131_behavior.py::_write_cfg` set, so the real
    foundry repo is never touched."""
    import json

    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "name": "probe",
        "repo": str(repo),
        "allowed_push_repo": "probe",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }))
    return foundry.load_config(str(cfg_path))


def _scouted(cfg, iteration, action=None):
    """Create `iter-<n>/` under `cfg.state` holding a scout slate (so the iteration is SCOUTED) and
    a spec; write `final.md` with that ACTION line only when `action` is given (no `final.md` is the
    real shape of an iteration the gate has not decided yet)."""
    d = pathlib.Path(cfg.state) / ("iter-" + str(iteration))
    d.mkdir(parents=True, exist_ok=True)
    (d / "pm_scout_a.md").write_text(
        "# PM_SCOUT_A -- iteration " + str(iteration) + " -- lens: probe\n\n"
        "## Slate\n## A1 -- candidate one\n")
    (d / "pm.md").write_text(
        "# PM SPEC -- iteration " + str(iteration) + "\n\n## Triage\n**PICK: A1** because.\n")
    if action is not None:
        (d / "final.md").write_text("gate report\n\nACTION: " + action + "\n")
    return d


def _written_log(cfg):
    """The decision log this FIXTURE wrote, read from `cfg.repo` (never the repo root)."""
    target = pathlib.Path(cfg.repo) / "DIRECTIONS.md"
    assert target.is_file(), "refresh_directions_file wrote no log under cfg.repo"
    return target.read_text()


def _tests_domain():
    """Every `tests/**/*.py` by DIRECTORY GLOB -- deliberately not `git ls-files`, so THIS module is
    inside its own domain immediately (no `git add -N` needed)."""
    tests_dir = _ROOT / "tests"
    return {str(q.relative_to(_ROOT)): q.read_text(encoding="utf-8")
            for q in sorted(tests_dir.rglob("*.py"))}


def _is_repo_root_artifact_expr(segment, aliases=()):
    """True when a path EXPRESSION names a machine-written artifact AND is anchored at the repo
    root.  Paths built from `cfg.repo` or `tmp_path` are explicitly allowed.

    `aliases` are names PROVED in this source to hold the repo root (`REPO = ...parents[1]`).
    Without them the scan is fail-open for every root spelled by any name but `_ROOT`: measured
    before this argument existed, `REPO = pathlib.Path(__file__).resolve().parents[1]` followed by
    `(REPO / "DIRECTIONS.md").read_text()` went UNDETECTED, and so did the two-hop constant form."""
    if not any(a in segment for a in _ARTIFACTS):
        return False
    if any(a in segment for a in _FIXTURE_ANCHORS):
        return False
    if any(a in segment for a in _ROOT_ANCHORS):
        return True
    return any(re.search(r"\b" + re.escape(name) + r"\b", segment) for name in aliases)


def _repo_root_artifact_reads(src, label="<src>"):
    """Findings for every read of a repo-root machine-written artifact in `src`.

    Two phases, because iteration 178's tests bound the path to a module-level CONSTANT first and
    the read site named only that constant."""
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError as exc:  # pragma: no cover - the shipped tree parses
        return (label + ": unparseable (" + str(exc) + ")",)
    assigns = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        if not targets:
            continue
        seg = ast.get_source_segment(src, node.value) or ""
        assigns.append((seg, [t.id for t in targets if isinstance(t, ast.Name)]))
    # PHASE 0 -- names proved to hold the REPO ROOT itself.  A name ALSO assigned from a fixture
    # anchor anywhere in this source is NOT a root alias, so a reused local (`p = _ROOT / "x"` in
    # one test, `p = tmp_path` in another) cannot make the scan cry wolf.
    roots, fixtures = set(), set()
    for seg, names in assigns:
        if any(a in seg for a in _FIXTURE_ANCHORS):
            fixtures.update(names)
        elif any(a in seg for a in _ROOT_ANCHORS) and not any(a in seg for a in _ARTIFACTS):
            roots.update(names)
    roots -= fixtures
    # PHASE 1 -- constants bound to a repo-root artifact PATH (iteration 178's exact shape).
    tainted = {}
    for seg, names in assigns:
        if _is_repo_root_artifact_expr(seg, roots):
            for name in names:
                tainted[name] = seg
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # `open(<repo-root artifact>)` -- the BUILTIN form, where the path is an ARGUMENT.
        if isinstance(node.func, ast.Name) and node.func.id == "open" and node.args:
            arg = (ast.get_source_segment(src, node.args[0]) or "").strip()
            if arg in tainted or _is_repo_root_artifact_expr(arg, roots):
                findings.append("%s:%d open(%s)" % (label, node.lineno, arg))
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _READERS:
            continue
        recv = (ast.get_source_segment(src, node.func.value) or "").strip()
        if recv in tainted:
            findings.append("%s:%d %s.%s() -- %s is bound to %s"
                            % (label, node.lineno, recv, node.func.attr, recv, tainted[recv]))
        elif _is_repo_root_artifact_expr(recv, roots):
            findings.append("%s:%d %s.%s()" % (label, node.lineno, recv, node.func.attr))
    return tuple(findings)


# --------------------------------------------------------------- Behaviour 14
def test_b14_the_healing_is_proved_on_a_tmp_path_fixture_not_the_live_repo(monkeypatch, tmp_path):
    """A stale `ACTION: PENDING` row for which git PROVES a ship reads `PUSHED (per git)` in the
    document `refresh_directions_file` actually wrote -- end-to-end, and entirely inside tmp_path."""
    cfg = _fixture_cfg(tmp_path)
    _scouted(cfg, 40, "PENDING")
    _scouted(cfg, 41, "PENDING")
    _scouted(cfg, 42)
    calls = []

    def fake(repo_dir):
        calls.append(repo_dir)
        return (_subject(40),)

    monkeypatch.setattr(foundry, "git_ship_subjects", fake)
    assert foundry.refresh_directions_file(cfg) is True
    assert calls == [cfg.repo], calls
    text = _written_log(cfg)
    assert _ship_label_of(text, 40) == PER_GIT, text
    # Hermetic by construction: the only log this test touched lives under tmp_path.
    assert str(pathlib.Path(cfg.repo)).startswith(str(tmp_path))


def test_b14_without_the_scripted_proof_the_same_fixture_row_stays_unknown(monkeypatch, tmp_path):
    """The other side of behaviour 14: the healing comes from the SUBJECTS, not from the fixture."""
    cfg = _fixture_cfg(tmp_path)
    _scouted(cfg, 40, "PENDING")
    _scouted(cfg, 41, "PENDING")
    _scouted(cfg, 42)
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo_dir: ())
    assert foundry.refresh_directions_file(cfg) is True
    assert _ship_label_of(_written_log(cfg), 40) == UNKNOWN


# --------------------------------------------------------------- Behaviour 15
def test_b15_one_fixture_document_carries_all_three_labels(monkeypatch, tmp_path):
    """Anti-vacuous in ONE written document: the healed row, an untouched honest `unknown`, and the
    newest not-yet-decided row -- with a decided `PUSHED` row alongside as a regression anchor."""
    cfg = _fixture_cfg(tmp_path)
    _scouted(cfg, 40, "PENDING")           # stale PENDING + proof  -> healed
    _scouted(cfg, 41, "PENDING")           # stale PENDING, no proof, NOT newest -> unknown
    _scouted(cfg, 42, "PUSHED abc1234")    # decided -> untouched
    _scouted(cfg, 43)                      # newest, undecided, no proof -> pending
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo_dir: (_subject(40),))
    assert foundry.refresh_directions_file(cfg) is True
    text = _written_log(cfg)
    labels = {n: _ship_label_of(text, n) for n in (40, 41, 42, 43)}
    assert labels[40] == PER_GIT, labels
    assert labels[41] == UNKNOWN, labels
    assert labels[43] == PENDING, labels
    assert labels[42].startswith("PUSHED") and "per git" not in labels[42], labels
    # Three DISTINCT labels in one document is what makes the proof anti-vacuous.
    assert len({labels[40], labels[41], labels[43]}) == 3, labels


# --------------------------------------------------------------- Behaviour 16
@pytest.mark.parametrize("label,src", [("constant-form", _BAD_CONSTANT_FORM),
                                       ("inline-form", _BAD_INLINE_FORM),
                                       ("builtin-open-form", _BAD_BUILTIN_OPEN_FORM),
                                       ("root-alias-form", _BAD_ROOT_ALIAS_FORM),
                                       ("alias-two-hop-form", _BAD_ALIAS_TWO_HOP_FORM)])
def test_b16_the_banned_shape_is_detected(label, src):
    findings = _repo_root_artifact_reads(src, label)
    assert findings, "planted %s went undetected -- the scan is fail-open" % label
    assert all(label in f for f in findings), findings


@pytest.mark.parametrize("label,src", [("cfg-repo-fixture", _GOOD_FIXTURE_FORM),
                                       ("prose-only", _GOOD_PROSE_FORM),
                                       ("shadowed-alias", _GOOD_SHADOWED_ALIAS_FORM)])
def test_b16_fixture_paths_and_prose_are_never_flagged(label, src):
    assert _repo_root_artifact_reads(src, label) == ()


def test_b16_no_shipped_test_pins_a_machine_written_artifact():
    domain = _tests_domain()
    mine = str(pathlib.Path(__file__).resolve().relative_to(_ROOT))
    assert mine in domain, "the scanning module must be inside its own domain: %r" % mine
    assert len(domain) >= 100, "the tests domain collapsed to %d files" % len(domain)
    findings = []
    for rel, src in sorted(domain.items()):
        findings.extend(_repo_root_artifact_reads(src, rel))
    assert findings == [], "tests pinning a machine-written artifact: %r" % (findings,)
    # Anti-vacuous: the modules that legitimately NAME those artifacts are in the scanned domain
    # and stay green, so the clean result is not the result of an empty domain.
    mentioning = sorted(rel for rel, src in domain.items() if any(a in src for a in _ARTIFACTS))
    assert len(mentioning) >= 6, mentioning


def test_b16_this_module_binds_no_repo_root_artifact_path_at_all():
    """The direct replacement for iteration 178's dead `DIRECTIONS = <repo root> / ...` constant:
    not merely unread here, but never bound."""
    import ast

    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _repo_root_artifact_reads(src, "self") == ()
    bound = [t.id for node in ast.walk(ast.parse(src)) if isinstance(node, ast.Assign)
             for t in node.targets if isinstance(t, ast.Name)
             and _is_repo_root_artifact_expr(ast.get_source_segment(src, node.value) or "")]
    assert bound == [], bound
