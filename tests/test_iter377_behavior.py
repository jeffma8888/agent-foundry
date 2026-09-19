"""Behavior tests for iteration 377 -- the `directions` winner-label vocabulary.

Spec: products/_platform/state/iter-377/pm.md (read black-box; the
implementation source, engineer/reviewer notes and `git diff` were NOT read).

  1. `foundry.directions_winner_label(entry, newest_iteration=None) -> str` is a
     module-level PURE function (no fs/subprocess/git/network/clock) and TOTAL.
  2. A recorded `entry.winner` wins outright, returned VERBATIM.
  3. `DirectionsEntry` takes a 7th, LAST, DEFAULTED `pm_present` (bool | None,
     default None); the class stays frozen; 6 positional args still construct.
  4. `DirectionsEntry.to_dict()` still returns EXACTLY its 6 pinned keys.
  5. With `winner is None` the four labels are these exact, distinct strings.
  6. Evidence (`pm_present is True`) beats the newest-row `pending` fallback.
  7. `render()` routes the winner line through the core BY BARE MODULE NAME,
     passing the same `max(e.iteration ...)` the `ship:` line computes.
  8. Pre-377 output preserved: an all-`pm_present=None` digest renders the old
     text, and `tests/test_iter115_behavior.py`'s winner fallback still holds
     UNEDITED.
  9. `gather_directions` sets `pm_present` from `pm.md` EXISTENCE, never `None`.

Offline only: every fixture lives under `tmp_path` (never the ambient repo and
never a gitignored path), the only git seam is monkeypatched away, and no test
spawns a subprocess or opens a socket.
"""

import dataclasses
import importlib.util
import inspect
import json
import pathlib
import shutil
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

# --------------------------------------------------------------- spec literals
UNPARSED = "unparsed (pm.md present)"
PENDING = "pending (not yet decided)"
ABSENT = "absent (no pm.md)"
UNKNOWN = "unknown"
ALL_LABELS = (UNPARSED, PENDING, ABSENT, UNKNOWN)
NEW_LABELS = (UNPARSED, PENDING, ABSENT)

EMDASH = "\u2014"


# --------------------------------------------------------------------- helpers
def _entry(iteration=1, winner=None, pm_present=None, action=None, sha=None,
           lenses=("new-capability",),
           candidates=("Candidate B3 " + EMDASH + " a measured thing",)):
    """A DirectionsEntry built by KEYWORD, with the new arg last."""
    return foundry.DirectionsEntry(
        iteration=iteration,
        lenses=tuple(lenses),
        candidates=tuple(candidates),
        winner=winner,
        action=action,
        sha=sha,
        pm_present=pm_present,
    )


def _digest(entries, subjects=()):
    return foundry.DirectionsDigest(
        product="demoprod", entries=tuple(entries), ship_subjects=tuple(subjects))


def _label(entry, newest=None):
    return foundry.directions_winner_label(entry, newest)


def _winner_lines(text):
    """Every `winner:` line, stripped, in document order."""
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("winner:")]


def _winner_line_of(text, iteration):
    """Anchored parse: the raw `winner:` line inside the `iter-<n>` block, or None."""
    want = "iter-" + str(iteration).zfill(2)
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("iter-"):
            inside = stripped == want
            continue
        if inside and stripped.startswith("winner:"):
            return line
    return None


def _fn_code_names(fn):
    """Every global/attribute name reachable from a function's code objects."""
    stack, seen, names = [fn.__code__], set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, types.CodeType):
                stack.append(c)
    return names


# ------------------------------------------------------------- tmp state trees
def _write_cfg(tmp_path, **over):
    """A minimal product config whose repo/work_root are TMP dirs, so the real
    foundry repo and its (gitignored) state tree are NEVER touched."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / ("iter-" + str(iteration).zfill(2))


def _write_state_iteration(cfg, iteration, *, scout=True, pm_text=None):
    """Create state/iter-NN/ with a scout file (the SCOUTED gate) and, when
    `pm_text` is not None, a pm.md holding exactly that text."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    if scout:
        (d / "pm_scout_a.md").write_text(
            "# PM_SCOUT_A " + EMDASH + " iteration " + str(iteration)
            + " " + EMDASH + " lens: new-capability\n\n"
            "## Slate\n## Candidate A1 " + EMDASH + " something\n")
    if pm_text is not None:
        (d / "pm.md").write_text(pm_text)
    return d


SPEC_WITH_WINNER = (
    "# PM SPEC " + EMDASH + " iteration n\n\n"
    "## Triage\n**PICK: A1** for measured reasons.\n\n## Feature\nbody\n")
SPEC_WITHOUT_WINNER = (
    "# PM SPEC " + EMDASH + " iteration n\n\n"
    "## Triage\nNo scout candidate won, so this row stays blank.\n\n"
    "## Feature\nbody\n")


def _gathered(tmp_path, monkeypatch, rows):
    """Build a tmp state tree from (iteration, pm_text_or_None) rows and gather
    it OFFLINE (the one git seam is scripted away)."""
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo_dir: ())
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    for iteration, pm_text in rows:
        _write_state_iteration(cfg, iteration, pm_text=pm_text)
    return cfg, foundry.gather_directions(cfg)


# ============================================================== Behavior 1
def test_b1_core_is_module_level_and_callable_with_nothing_but_an_entry():
    fn = getattr(foundry, "directions_winner_label", None)
    assert isinstance(fn, types.FunctionType), "must be a module-level function"
    params = list(inspect.signature(fn).parameters)
    assert params[0] == "entry" and params[1] == "newest_iteration"
    assert inspect.signature(fn).parameters["newest_iteration"].default is None
    # Callable with a hand-built entry and NOTHING else.
    assert fn(_entry(pm_present=True)) == UNPARSED


def test_b1_core_is_total_and_never_raises_for_any_combination():
    """Totality over the DECLARED domain (`winner: str | None`) crossed with
    off-domain `pm_present` / `newest_iteration` values."""
    declared_winners = (None, "B3", "", "unknown", "A1 " + EMDASH + " x")
    weird_presence = (True, False, None, 0, 1, "", "yes", [])
    weird_newest = (None, 0, -5, 1, 377, 10 ** 9)
    for w in declared_winners:
        for p in weird_presence:
            for n in weird_newest:
                out = _label(_entry(iteration=377, winner=w, pm_present=p), n)
                assert isinstance(out, str), (w, p, n, out)
                if w is None:
                    # A blank winner always gets a NON-EMPTY label.
                    assert out != "", (w, p, n)
                else:
                    # Behavior 2: a recorded winner comes back VERBATIM, even "".
                    assert out == w, (w, p, n, out)


def test_b1_core_does_not_raise_even_for_off_domain_winner_values():
    for w in (0, False, 1, 3.5, [], ("B3",)):
        for p in (True, False, None):
            foundry.directions_winner_label(
                _entry(iteration=377, winner=w, pm_present=p), 377)


def test_b1_core_touches_no_filesystem_subprocess_git_network_or_clock():
    banned = {
        "open", "read_text", "write_text", "exists", "glob", "iterdir", "mkdir",
        "subprocess", "run", "Popen", "check_output", "git_ship_subjects",
        "socket", "urlopen", "requests", "time", "sleep", "datetime", "now",
        "monotonic", "getenv", "environ", "system", "Path",
    }
    hits = banned & _fn_code_names(foundry.directions_winner_label)
    assert hits == set(), "the pure core reaches for I/O: " + repr(sorted(hits))


def test_b1_core_is_stable_and_side_effect_free_under_repetition():
    e = _entry(iteration=7, pm_present=False)
    first = _label(e, 7)
    for _ in range(5):
        assert _label(e, 7) == first
    assert e.pm_present is False and e.winner is None


# ============================================================== Behavior 2
def test_b2_a_recorded_decision_wins_outright_verbatim():
    for present in (True, False, None):
        for newest in (None, 0, 9, 377):
            assert _label(_entry(iteration=9, winner="B3", pm_present=present),
                          newest) == "B3", (present, newest)


def test_b2_the_specs_own_example_returns_the_winner_not_pending():
    # winner="B3", pm_present=False, iteration == newest_iteration -> "B3"
    assert _label(_entry(iteration=377, winner="B3", pm_present=False), 377) == "B3"


def test_b2_an_odd_winner_string_is_not_normalized():
    for w in ("A1 " + EMDASH + " alpha", "  C2  ", "unknown", "pending"):
        assert _label(_entry(winner=w, pm_present=True), 1) == w


# ============================================================== Behavior 3
def test_b3_pm_present_is_the_last_constructor_arg_and_defaults_to_none():
    params = list(inspect.signature(foundry.DirectionsEntry).parameters.items())
    name, param = params[-1]
    assert name == "pm_present", [p for p, _ in params]
    assert param.default is None
    assert [p for p, _ in params][:6] == [
        "iteration", "lenses", "candidates", "winner", "action", "sha"]


def test_b3_six_positional_args_still_construct_and_yield_none():
    e = foundry.DirectionsEntry(3, (), (), None, None, None)
    assert e.pm_present is None


def test_b3_the_seventh_arg_is_accepted_positionally_and_by_keyword():
    assert foundry.DirectionsEntry(3, (), (), None, None, None, True).pm_present is True
    assert foundry.DirectionsEntry(
        3, (), (), None, None, None, pm_present=False).pm_present is False


def test_b3_entry_is_still_frozen_including_the_new_attribute():
    e = _entry(pm_present=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.pm_present = False
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.iteration = 99
    assert e.pm_present is True


# ============================================================== Behavior 4
def test_b4_to_dict_still_has_exactly_its_six_pinned_keys_in_order():
    for present in (True, False, None):
        payload = _entry(winner="B3", action="PUSHED", sha="abc1234",
                         pm_present=present).to_dict()
        assert list(payload.keys()) == [
            "iteration", "lenses", "candidates", "winner", "action", "sha"]
        assert "pm_present" not in payload


def test_b4_to_dict_still_json_round_trips_including_nulls():
    e = _entry(winner=None, action=None, sha=None, pm_present=True)
    payload = e.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["winner"] is None


def test_b4_no_serialized_payload_mentions_the_new_render_input():
    blob = json.dumps(_digest([_entry(1, pm_present=True),
                               _entry(2, pm_present=False),
                               _entry(3, pm_present=None)]).to_dict())
    assert "pm_present" not in blob
    for row in json.loads(blob)["entries"]:
        assert list(row.keys()) == [
            "iteration", "lenses", "candidates", "winner", "action", "sha"]


# ============================================================== Behavior 5
def test_b5_the_four_blank_winner_labels_are_these_exact_strings():
    cases = (
        # (pm_present, iteration, newest_iteration, expected)
        (True, 377, 377, UNPARSED),
        (True, 300, 377, UNPARSED),
        (True, 377, None, UNPARSED),
        (False, 377, 377, PENDING),
        (False, 300, 377, ABSENT),
        (False, 377, None, ABSENT),
        (None, 377, 377, UNKNOWN),
        (None, 300, 377, UNKNOWN),
        (None, 377, None, UNKNOWN),
    )
    for present, iteration, newest, expected in cases:
        got = _label(_entry(iteration=iteration, winner=None, pm_present=present),
                     newest)
        assert got == expected, (present, iteration, newest, got)


def test_b5_the_four_labels_are_all_distinct():
    produced = {
        _label(_entry(iteration=1, pm_present=True), 1),
        _label(_entry(iteration=1, pm_present=False), 1),
        _label(_entry(iteration=1, pm_present=False), 2),
        _label(_entry(iteration=1, pm_present=None), 1),
    }
    assert produced == set(ALL_LABELS) and len(produced) == 4


def test_b5_absent_covers_both_non_newest_and_no_newest_at_all():
    assert _label(_entry(iteration=5, pm_present=False), 6) == ABSENT
    assert _label(_entry(iteration=5, pm_present=False), None) == ABSENT
    assert _label(_entry(iteration=5, pm_present=False), 5) == PENDING


# ============================================================== Behavior 6
def test_b6_evidence_beats_the_newest_row_fallback():
    newest_with_spec = _entry(iteration=377, winner=None, pm_present=True)
    assert _label(newest_with_spec, 377) == UNPARSED
    assert _label(newest_with_spec, 377) != PENDING


def test_b6_pending_fires_only_when_no_pm_md_exists():
    for present in (True, None):
        assert _label(_entry(iteration=42, pm_present=present), 42) != PENDING
    assert _label(_entry(iteration=42, pm_present=False), 42) == PENDING


def test_b6_unparsed_is_independent_of_newness():
    labels = {_label(_entry(iteration=10, pm_present=True), n)
              for n in (None, 0, 9, 10, 11, 999)}
    assert labels == {UNPARSED}


# ============================================================== Behavior 7
def test_b7_render_routes_every_winner_line_through_the_bare_module_name(monkeypatch):
    entries = (_entry(3, winner="B3", pm_present=True),
               _entry(2, winner=None, pm_present=False),
               _entry(1, winner=None, pm_present=None))
    monkeypatch.setattr(foundry, "directions_winner_label",
                        lambda *a, **k: "SENTINEL-W")
    text = _digest(entries).render()
    assert _winner_lines(text) == ["winner: SENTINEL-W"] * 3
    assert "winner: B3" not in text


def test_b7_render_passes_the_same_newest_the_ship_line_computes(monkeypatch):
    seen = []

    def spy(entry, newest_iteration=None):
        seen.append((entry.iteration, newest_iteration))
        return UNKNOWN

    monkeypatch.setattr(foundry, "directions_winner_label", spy)
    _digest([_entry(300), _entry(377), _entry(115)]).render()
    assert sorted(i for i, _ in seen) == [115, 300, 377]
    assert {n for _, n in seen} == {377}, seen


def test_b7_the_winner_line_keeps_its_four_space_indent_and_shape():
    text = _digest([_entry(377, winner=None, pm_present=False)]).render()
    assert _winner_line_of(text, 377) == "    winner: " + PENDING


def test_b7_a_real_render_shows_all_three_new_labels_on_the_right_rows():
    entries = (_entry(4, winner=None, pm_present=False),   # newest, no pm.md
               _entry(3, winner=None, pm_present=True),    # spec on disk
               _entry(2, winner=None, pm_present=False),   # older, no pm.md
               _entry(1, winner="A1", pm_present=True))    # decided
    text = _digest(entries).render()
    assert _winner_line_of(text, 4).strip() == "winner: " + PENDING
    assert _winner_line_of(text, 3).strip() == "winner: " + UNPARSED
    assert _winner_line_of(text, 2).strip() == "winner: " + ABSENT
    assert _winner_line_of(text, 1).strip() == "winner: A1"


# ============================================================== Behavior 8
def test_b8_an_all_none_digest_renders_the_pre_change_winner_text():
    pushed_no_sha = foundry.DirectionsEntry(1, (), (), None, "PUSHED", None)
    reverted = foundry.DirectionsEntry(2, (), (), None, "REVERTED", None)
    unknown = foundry.DirectionsEntry(3, (), (), None, None, None)
    decided = foundry.DirectionsEntry(4, ("l",), ("c",), "C1", "PUSHED", "abc123")
    text = foundry.DirectionsDigest(
        product="p", entries=(pushed_no_sha, reverted, unknown, decided)).render()
    assert _winner_lines(text) == [
        "winner: " + UNKNOWN, "winner: " + UNKNOWN, "winner: " + UNKNOWN,
        "winner: C1"]
    for label in NEW_LABELS:
        assert label not in text, label


def test_b8_the_iter115_winner_fallback_expectation_still_holds_unedited():
    path = _ROOT / "tests" / "test_iter115_behavior.py"
    src = path.read_text()
    assert 'assert "winner: unknown" in out' in src, (
        "iteration 115's winner fallback assertion must survive UNEDITED")
    spec = importlib.util.spec_from_file_location("_iter115_probe_377", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Re-run the pinned test itself: it must still pass against today's code.
    mod.test_b07_render_ship_and_lens_and_winner_fallbacks()
    mod.test_b05_entry_to_dict_exactly_six_keys_in_declaration_order()


# ============================================================== Behavior 9
def test_b9_gather_sets_pm_present_from_existence_never_none(tmp_path, monkeypatch):
    cfg, digest = _gathered(tmp_path, monkeypatch, (
        (1, SPEC_WITH_WINNER),      # scout + pm.md naming a winner
        (2, SPEC_WITHOUT_WINNER),   # scout + pm.md with NO resolvable winner
        (3, None),                  # scout, NO pm.md  (newest)
    ))
    by_iteration = {e.iteration: e for e in digest.entries}
    assert sorted(by_iteration) == [1, 2, 3]
    assert by_iteration[1].pm_present is True
    assert by_iteration[2].pm_present is True
    assert by_iteration[3].pm_present is False
    for e in digest.entries:
        assert e.pm_present is not None

    text = digest.render()
    assert _winner_line_of(text, 1).strip() == "winner: A1"
    assert _winner_line_of(text, 2).strip() == "winner: " + UNPARSED
    assert _winner_line_of(text, 3).strip() == "winner: " + PENDING


def test_b9_a_newer_iteration_moves_the_old_pending_row_to_absent(tmp_path, monkeypatch):
    cfg, _ = _gathered(tmp_path, monkeypatch, (
        (1, SPEC_WITH_WINNER), (2, SPEC_WITHOUT_WINNER), (3, None)))
    _write_state_iteration(cfg, 4, pm_text=None)
    text = foundry.gather_directions(cfg).render()
    assert _winner_line_of(text, 4).strip() == "winner: " + PENDING
    assert _winner_line_of(text, 3).strip() == "winner: " + ABSENT
    assert _winner_line_of(text, 2).strip() == "winner: " + UNPARSED
    assert _winner_line_of(text, 1).strip() == "winner: A1"


def test_b9_gather_never_raises_on_a_missing_or_odd_state_tree(tmp_path, monkeypatch):
    cfg, digest = _gathered(tmp_path, monkeypatch, ((1, SPEC_WITHOUT_WINNER),))
    assert digest.total == 1 and digest.entries[0].pm_present is True
    # pm.md as a DIRECTORY: it exists, so the label is honest and nothing raises.
    odd = _write_state_iteration(cfg, 2, pm_text=None)
    (odd / "pm.md").mkdir()
    again = foundry.gather_directions(cfg)
    assert {e.iteration: e.pm_present for e in again.entries} == {1: True, 2: True}
    # No state tree at all -> empty digest, still no raise.
    shutil.rmtree(cfg.state, ignore_errors=True)
    empty = foundry.gather_directions(cfg)
    assert empty.total == 0 and empty.entries == ()


def test_b9_an_empty_pm_md_still_counts_as_present(tmp_path, monkeypatch):
    # Out of scope by spec: existence is the rule, so an EMPTY spec is `unparsed`.
    cfg, digest = _gathered(tmp_path, monkeypatch, ((5, ""),))
    assert digest.entries[0].pm_present is True
    assert _winner_line_of(digest.render(), 5).strip() == "winner: " + UNPARSED
