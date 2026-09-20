"""Behavior tests for iteration 382 -- a scout's FIRST checkpoint must be a valid
minimal slate, and `directions` labels a present-but-empty scout seat.

Spec: products/_platform/state/iter-382/pm.md (read black-box; the
implementation source, engineer/reviewer notes and `git diff` were NOT read).

  1. `roles/pm_scout.md` WRITE-EARLY section carries the exact first-checkpoint
     sentence; iter 112/139/233/379 anchors still hold.
  2. The sentence appears in NO other `roles/*.md` (scout-only rule); the needle
     is built by concatenation so this module never contains it verbatim.
  3. `DirectionsEntry` carries `empty_seats` as PROVENANCE, not a record:
     `fields()` still names six, `to_dict()` still emits 6 keys, and two
     entries differing only in `empty_seats` compare equal.
  4. `gather_directions` sets `empty_seats` = seats whose file EXISTS and yields
     zero candidates, in ("a", "b") order; absent file / >= 1 candidate are not.
  5. `render()` emits EXACTLY ONE `    empty: scout a, scout b -- file present,
     0 candidate headings` line per such block, after the last candidate line
     and any `stubs:` line, before `winner:`; the line never contains `stubs:`.
  6. `empty_seats == ()` renders byte-identically to HEAD 77d742c (frozen
     literal minted by running HEAD's own module once in the tester seat) and
     the substring `empty:` appears nowhere in such a block.
  7. `python3 foundry.py directions --config <cfg>` prints the line inside the
     `iter-90` block only; `--json` is unchanged (frozen literal, no new key).
  8. `refresh_directions_file(cfg)` writes the same line to DIRECTIONS.md.
  9. Additive-dormant: `dispatcher.py` never names `empty_seats`; no control-
     path function's code names it; `python -c "import foundry, dispatcher"` ok.

AMBIGUITY (PM feedback): behavior 3 names the MECHANISM "a second
`dataclasses.InitVar`", but `tests/test_iter377_behavior.py::test_b3_...` pins
`pm_present` as BOTH the LAST `inspect.signature` parameter and the 7th
positional, and the same spec says test_iter377 stays green unedited -- so any
extra constructor parameter is contradictory. These tests rule on the
OBSERVABLE properties behavior 3 lists (six fields, six keys, equality) plus the
published read-only `empty_seats` attribute, reached through whichever public
path the product exposes (`DirectionsEntry.with_empty_seats`, discovered via
`dir()` on the running product). `finalize_iteration` (behavior 9) exists in
neither module; the walker checks every named function that does exist.

Offline except two spawns of the product's own CLI and one `python -c` import
probe (all `sys.executable`, cwd = repo root, no git, no network). Every
fixture lives under `tmp_path`; nothing depends on gitignored local state.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import pathlib
import re
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

SCOUT_CARD = _ROOT / "roles" / "pm_scout.md"
WRITE_EARLY_HEADING = "## WRITE-EARLY (checkpoint-first)"

# Built by concatenation so this module never contains the needle verbatim
# (iter 381 TEST lesson: the self-scan must not find its own oracle).
SENTENCE = (
    "Your FIRST checkpoint must already be a valid slate: 2-3 `## Candidate` "
    "headings, each followed by one line stating a concrete hypothesis drawn "
    "from your lens and the inputs already in this prompt -- never a bare "
    "STATUS line and never a `(measuring ...)` placeholder; measure and rewrite "
    "those candidates in place afterwards."
)

SIX_FIELDS = ("iteration", "lenses", "candidates", "winner", "action", "sha")
EMPTY_TAIL = " -- file present, 0 candidate headings"
STUBS_TEXT = ("stubs: {k} of {n} candidate line(s) are write-early "
              "placeholders, not measured candidates")

# Behavior 6 oracle: `render()` of `_clean_digest()` under HEAD 77d742c, minted
# once by loading `git show HEAD:foundry.py` through importlib in the tester
# seat (never at test runtime -- that comparison goes vacuous the moment the
# fold commits and is unrunnable where git is absent).
EXPECTED_CLEAN_RENDER = (
    "foundry directions -- demoprod\n"
    "  iter-300\n"
    "    lenses: performance-and-throughput, narrative-and-docs\n"
    "    winner: unknown\n"
    "    ship: pending (not yet decided)\n"
    "  iter-299\n"
    "    lenses: performance-and-throughput, narrative-and-docs\n"
    "    - Candidate A1 -- (measuring)\n"
    "    - Candidate B1 -- real thing\n"
    "    " + STUBS_TEXT.format(k=1, n=2) + "\n"
    "    winner: B1\n"
    "    ship: unknown\n"
    "  iter-298\n"
    "    lenses: performance-and-throughput, narrative-and-docs\n"
    "    - Candidate A1 -- real\n"
    "    winner: A1\n"
    "    ship: PUSHED (per git)\n"
    "  iter-297\n"
    "    lenses: performance-and-throughput, narrative-and-docs\n"
    "    - Candidate A1 -- (measuring)\n"
    "    " + STUBS_TEXT.format(k=1, n=1) + "\n"
    "    winner: unknown\n"
    "    ship: unknown\n"
    "4 scouted iterations"
)

# Behavior 7 oracle: `gather_directions(cfg).to_dict()` for `_b7_fixture` under
# HEAD 77d742c (same minting), i.e. the `--json` document with NO new key.
EXPECTED_B7_JSON = {
    "product": "demoprod",
    "total": 2,
    "exit_code": 0,
    "entries": [
        {"iteration": 91, "lenses": ["x", "y"],
         "candidates": ["Candidate A1 -- real", "Candidate B1 -- real"],
         "winner": None, "action": None, "sha": None},
        {"iteration": 90,
         "lenses": ["performance-and-throughput", "narrative-and-docs"],
         "candidates": ["Candidate B1 -- thing one", "Candidate B2 -- thing two"],
         "winner": None, "action": None, "sha": None},
    ],
}


# --------------------------------------------------------------------- helpers
def _card_text() -> str:
    return SCOUT_CARD.read_text(encoding="utf-8")


def _write_early_section(text: str) -> str:
    """The text from the WRITE-EARLY heading up to the next `\\n## ` heading."""
    start = text.index(WRITE_EARLY_HEADING)
    nxt = text.find("\n## ", start + len(WRITE_EARLY_HEADING))
    return text[start:] if nxt < 0 else text[start:nxt]


def _entry(iteration=1, candidates=("Candidate A1 -- a real measured thing",),
           winner="A1", action=None, sha=None, pm_present=None,
           lenses=("performance-and-throughput", "narrative-and-docs")):
    return foundry.DirectionsEntry(
        iteration=iteration, lenses=tuple(lenses), candidates=tuple(candidates),
        winner=winner, action=action, sha=sha, pm_present=pm_present)


def _digest(entries, subjects=()):
    return foundry.DirectionsDigest(
        product="demoprod", entries=tuple(entries), ship_subjects=tuple(subjects))


def _clean_digest():
    """The 4-entry fixture EXPECTED_CLEAN_RENDER was minted from: a zero-
    candidate block, a stubbed block, a shipped block, a fully stubbed block."""
    return _digest((
        _entry(300, candidates=(), winner=None),
        _entry(299, candidates=("Candidate A1 -- (measuring)",
                                "Candidate B1 -- real thing"),
               winner="B1", pm_present=True),
        _entry(298, candidates=("Candidate A1 -- real",), winner="A1"),
        _entry(297, candidates=("Candidate A1 -- (measuring)",), winner=None),
    ), subjects=("chore: some change (foundry iter 298)",))


def _seated_digest():
    """`_clean_digest()` with seats on 300 (both) and 299 (b only)."""
    e = list(_clean_digest().entries)
    e[0] = e[0].with_empty_seats(("a", "b"))
    e[1] = e[1].with_empty_seats(("b",))
    return _digest(e, subjects=("chore: some change (foundry iter 298)",))


def _blocks(text):
    """Split a rendered log into {iteration: [lines]} -- anchored, no slicing."""
    out, cur = {}, None
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^iter-(\d+)$", stripped)
        if m:
            cur = int(m.group(1))
            out[cur] = []
        elif cur is not None and stripped:
            out[cur].append(line)
    return out


def _empty_lines(block):
    return [ln for ln in block if ln.strip().startswith("empty:")]


def _names(fn):
    """Every global/attribute name a function's code (and nested code) touches."""
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
def _write_cfg(tmp_path):
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
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


STATUS_ONLY = ("# PM_SCOUT_{S} -- iteration {n} -- lens: {lens}\n"
               "STATUS: IN PROGRESS -- measuring\n")
TWO_HEADINGS = ("# PM_SCOUT_{S} -- iteration {n} -- lens: {lens}\n\n## Slate\n"
                "## Candidate {S}1 -- thing one\nhyp\n"
                "## Candidate {S}2 -- thing two\nhyp\n")
ONE_HEADING = ("# PM_SCOUT_{S} -- iteration {n} -- lens: {lens}\n\n"
               "## Candidate {S}1 -- real\nhyp\n")


def _seat(cfg, iteration, seat, template, lens):
    d = pathlib.Path(cfg.state) / ("iter-" + str(iteration).zfill(2))
    d.mkdir(parents=True, exist_ok=True)
    (d / ("pm_scout_" + seat + ".md")).write_text(
        template.format(S=seat.upper(), n=iteration, lens=lens))
    return d


def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo_dir: ())
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _b7_fixture(tmp_path):
    """iter-90: seat a = STATUS-only, seat b = two headings; iter-91: both seats
    hold one heading. Returns the config path (the CLI takes a PATH)."""
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _seat(cfg, 90, "a", STATUS_ONLY, "performance-and-throughput")
    _seat(cfg, 90, "b", TWO_HEADINGS, "narrative-and-docs")
    _seat(cfg, 91, "a", ONE_HEADING, "x")
    _seat(cfg, 91, "b", ONE_HEADING, "y")
    return cfg_path


def _run_cli(*argv):
    return subprocess.run([sys.executable, "foundry.py", *argv], cwd=str(_ROOT),
                          capture_output=True, text=True, timeout=90)


# ============================================================== Behavior 1
def test_b1_write_early_section_contains_the_first_checkpoint_sentence():
    section = _write_early_section(_card_text())
    assert SENTENCE in section


def test_b1_the_sentence_is_not_placed_before_the_write_early_heading():
    text = _card_text()
    assert SENTENCE not in text[:text.index(WRITE_EARLY_HEADING)]
    assert text.count(SENTENCE) == 1


def test_b1_iter_112_and_139_anchors_still_hold_in_the_section():
    section = _write_early_section(_card_text())
    assert "WRITE-EARLY (checkpoint-first)" in section
    assert "write a complete-but-minimal version" in section


def test_b1_iter_139_ban_the_card_has_no_exception_for_this_card_clause():
    assert "EXCEPTION for this card" not in _card_text()


def test_b1_iter_233_anchor_directions_is_an_input_appears_after_the_heading():
    text = _card_text()
    head_at = text.index(WRITE_EARLY_HEADING)
    assert "DIRECTIONS.md is an INPUT" not in text[:head_at]
    assert text.find("DIRECTIONS.md is an INPUT", head_at) > head_at


def test_b1_iter_379_scout_lens_audit_stays_ok():
    audit = foundry.scout_lens_audit(foundry.PM_SCOUT_LENS_POOL, _card_text())
    assert audit.ok is True


# ============================================================== Behavior 2
def test_b2_the_sentence_appears_in_no_other_role_card():
    hits = sorted(p.name for p in (_ROOT / "roles").glob("*.md")
                  if SENTENCE in p.read_text(encoding="utf-8"))
    assert hits == ["pm_scout.md"]


def test_b2_the_scan_covers_every_role_card_and_this_module_is_not_a_hit():
    names = sorted(p.name for p in (_ROOT / "roles").glob("*.md"))
    assert {"pm.md", "pm_scout.md", "engineer.md", "tester.md",
            "reviewer.md", "final.md"} <= set(names)
    # The needle is built by concatenation above, so the module's own text is
    # never a false positive for the scout-only rule.
    assert SENTENCE not in pathlib.Path(__file__).read_text(encoding="utf-8")


# ============================================================== Behavior 3
def test_b3_fields_still_name_exactly_the_six_decision_fields_in_order():
    assert tuple(f.name for f in dataclasses.fields(foundry.DirectionsEntry)) \
        == SIX_FIELDS


def test_b3_to_dict_still_emits_the_pinned_six_key_payload_with_seats_set():
    plain = _entry(5)
    seated = plain.with_empty_seats(("a", "b"))
    assert tuple(plain.to_dict()) == SIX_FIELDS
    assert tuple(seated.to_dict()) == SIX_FIELDS
    assert seated.to_dict() == plain.to_dict()
    assert "empty_seats" not in json.dumps(seated.to_dict())


def test_b3_empty_seats_defaults_to_an_empty_tuple_and_is_published():
    e = _entry(5)
    assert e.empty_seats == ()
    assert isinstance(e.empty_seats, tuple)


def test_b3_two_entries_differing_only_in_empty_seats_compare_equal():
    plain = _entry(5)
    seated = plain.with_empty_seats(("a", "b"))
    assert seated.empty_seats == ("a", "b")
    assert seated == plain
    assert hash(seated) == hash(plain)
    assert plain.empty_seats == (), "with_empty_seats must copy, never mutate"


def test_b3_empty_seats_is_stored_as_a_tuple_from_any_iterable():
    assert _entry(5).with_empty_seats(["b"]).empty_seats == ("b",)
    assert _entry(5).with_empty_seats(s for s in "ab").empty_seats == ("a", "b")
    assert _entry(5).with_empty_seats(()).empty_seats == ()


def test_b3_the_class_stays_frozen_and_iter_377_constructor_pin_is_intact():
    e = _entry(5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.empty_seats = ("a",)  # type: ignore[misc]
    params = list(inspect.signature(foundry.DirectionsEntry).parameters)
    assert params[:6] == list(SIX_FIELDS)
    assert params[-1] == "pm_present"
    assert e.pm_present is None


# ============================================================== Behavior 4
def test_b4_a_present_status_only_seat_is_empty_and_a_two_heading_seat_is_not(
        tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    _seat(cfg, 90, "a", STATUS_ONLY, "performance-and-throughput")
    _seat(cfg, 90, "b", TWO_HEADINGS, "narrative-and-docs")
    (entry,) = foundry.gather_directions(cfg).entries
    assert entry.iteration == 90
    assert entry.empty_seats == ("a",)
    assert len(entry.candidates) == 2


def test_b4_both_seats_empty_are_reported_in_a_then_b_order(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    _seat(cfg, 90, "b", STATUS_ONLY, "narrative-and-docs")
    _seat(cfg, 90, "a", STATUS_ONLY, "performance-and-throughput")
    (entry,) = foundry.gather_directions(cfg).entries
    assert entry.empty_seats == ("a", "b")
    assert entry.candidates == ()


def test_b4_an_absent_file_is_not_an_empty_seat(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    _seat(cfg, 90, "b", STATUS_ONLY, "narrative-and-docs")
    (entry,) = foundry.gather_directions(cfg).entries
    assert entry.empty_seats == ("b",)


def test_b4_a_seat_with_at_least_one_candidate_is_never_empty(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    _seat(cfg, 91, "a", ONE_HEADING, "x")
    _seat(cfg, 91, "b", ONE_HEADING, "y")
    _seat(cfg, 92, "a", ONE_HEADING, "x")
    _seat(cfg, 92, "b", STATUS_ONLY, "y")
    by_iter = {e.iteration: e for e in foundry.gather_directions(cfg).entries}
    assert by_iter[91].empty_seats == ()
    assert by_iter[92].empty_seats == ("b",)


def test_b4_empty_seat_agrees_with_parse_scout_candidates_on_the_same_text():
    assert foundry.parse_scout_candidates(
        STATUS_ONLY.format(S="A", n=90, lens="l")) == ()
    assert len(foundry.parse_scout_candidates(
        TWO_HEADINGS.format(S="B", n=90, lens="l"))) == 2


# ============================================================== Behavior 5
def test_b5_a_two_seat_block_carries_exactly_the_specified_line_once():
    block = _blocks(_seated_digest().render())[300]
    assert _empty_lines(block) == ["    empty: scout a, scout b" + EMPTY_TAIL]


def test_b5_a_one_seat_block_names_only_that_seat():
    block = _blocks(_seated_digest().render())[299]
    assert _empty_lines(block) == ["    empty: scout b" + EMPTY_TAIL]


def test_b5_the_seat_list_follows_stored_order():
    e = _entry(300, candidates=(), winner=None).with_empty_seats(("b", "a"))
    block = _blocks(_digest((e,)).render())[300]
    assert _empty_lines(block) == ["    empty: scout b, scout a" + EMPTY_TAIL]


def test_b5_the_line_sits_after_the_stubs_line_and_before_winner():
    stripped = [ln.strip() for ln in _blocks(_seated_digest().render())[299]]
    stubs_at = stripped.index(STUBS_TEXT.format(k=1, n=2))
    empty_at = stripped.index("empty: scout b" + EMPTY_TAIL)
    winner_at = stripped.index("winner: B1")
    last_candidate_at = max(i for i, ln in enumerate(stripped) if ln.startswith("- "))
    assert last_candidate_at < stubs_at < empty_at < winner_at


def test_b5_without_a_stubs_line_it_sits_right_after_the_last_candidate():
    e = _entry(298, candidates=("Candidate A1 -- real",), winner="A1") \
        .with_empty_seats(("b",))
    stripped = [ln.strip() for ln in _blocks(_digest((e,)).render())[298]]
    assert "stubs:" not in "\n".join(stripped)
    assert stripped.index("- Candidate A1 -- real") + 1 \
        == stripped.index("empty: scout b" + EMPTY_TAIL)
    assert stripped.index("empty: scout b" + EMPTY_TAIL) + 1 \
        == stripped.index("winner: A1")


def test_b5_the_empty_line_never_contains_the_stubs_substring():
    for block in _blocks(_seated_digest().render()).values():
        for ln in _empty_lines(block):
            assert "stubs:" not in ln


def test_b5_zero_candidates_plus_empty_seats_still_adds_no_stubs_line():
    block = _blocks(_seated_digest().render())[300]
    assert [ln for ln in block if ln.strip().startswith("stubs:")] == []
    assert len(_empty_lines(block)) == 1


# ============================================================== Behavior 6
def test_b6_a_digest_with_no_empty_seats_renders_byte_identically_to_head():
    assert _clean_digest().render() == EXPECTED_CLEAN_RENDER


def test_b6_the_substring_empty_appears_nowhere_without_seats():
    text = _clean_digest().render()
    assert "empty:" not in text
    assert "empty:" not in foundry.render_directions_doc(_clean_digest())


def test_b6_iter_321_b6_zero_candidates_no_seats_adds_neither_label():
    block = _blocks(_digest((_entry(300, candidates=(), winner=None),)).render())[300]
    assert [ln for ln in block if ln.strip().startswith(("stubs:", "empty:"))] == []
    body = [ln.strip() for ln in block if not ln.strip().endswith("scouted iterations")]
    assert body == ["lenses: performance-and-throughput, narrative-and-docs",
                    "winner: unknown", "ship: unknown"]


def test_b6_the_empty_lines_are_the_only_residue_of_seating_a_digest():
    head = EXPECTED_CLEAN_RENDER.splitlines()
    seated = _seated_digest().render().splitlines()
    assert sorted(set(seated) - set(head)) == [
        "    empty: scout a, scout b" + EMPTY_TAIL,
        "    empty: scout b" + EMPTY_TAIL]
    assert set(head) - set(seated) == set()
    assert [ln for ln in seated if not ln.strip().startswith("empty:")] == head


def test_b6_to_dict_of_a_seated_digest_equals_the_clean_one():
    assert _seated_digest().to_dict() == _clean_digest().to_dict()


# ============================================================== Behavior 7
def test_b7_cli_prints_the_line_inside_iter_90_only(tmp_path):
    cfg_path = _b7_fixture(tmp_path)
    r = _run_cli("directions", "--config", str(cfg_path))
    assert r.returncode == 0, r.stderr
    blocks = _blocks(r.stdout)
    assert set(blocks) == {90, 91}
    assert _empty_lines(blocks[90]) == ["    empty: scout a" + EMPTY_TAIL]
    assert _empty_lines(blocks[91]) == []
    assert r.stdout.count("empty:") == 1


def test_b7_cli_json_is_unchanged_from_head_with_no_new_key(tmp_path):
    cfg_path = _b7_fixture(tmp_path)
    r = _run_cli("directions", "--config", str(cfg_path), "--json")
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc == EXPECTED_B7_JSON
    for entry in doc["entries"]:
        assert tuple(entry) == SIX_FIELDS
    assert "empty" not in r.stdout


def test_b7_in_process_gather_agrees_with_the_cli_seats(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo_dir: ())
    cfg = foundry.load_config(str(_b7_fixture(tmp_path)))
    seats = {e.iteration: e.empty_seats for e in foundry.gather_directions(cfg).entries}
    assert seats == {90: ("a",), 91: ()}


# ============================================================== Behavior 8
def test_b8_refresh_directions_file_writes_the_same_line(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo_dir: ())
    cfg = foundry.load_config(str(_b7_fixture(tmp_path)))
    assert foundry.refresh_directions_file(cfg) is True
    doc = (pathlib.Path(cfg.repo) / "DIRECTIONS.md").read_text(encoding="utf-8")
    blocks = _blocks(doc)
    assert _empty_lines(blocks[90]) == ["    empty: scout a" + EMPTY_TAIL]
    assert _empty_lines(blocks[91]) == []
    assert doc.count("empty:") == 1


def test_b8_refresh_composes_render_by_bare_name(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "git_ship_subjects", lambda repo_dir: ())
    cfg = foundry.load_config(str(_b7_fixture(tmp_path)))
    foundry.refresh_directions_file(cfg)
    doc = (pathlib.Path(cfg.repo) / "DIRECTIONS.md").read_text(encoding="utf-8")
    assert foundry.gather_directions(cfg).render() in doc


# ============================================================== Behavior 9
def test_b9_dispatcher_never_names_empty_seats():
    text = (_ROOT / "dispatcher.py").read_text(encoding="utf-8")
    assert "empty_seats" not in text
    assert "with_empty_seats" not in text


def test_b9_no_control_path_function_names_empty_seats():
    import dispatcher  # noqa: E402  (imported here so a failure names B9)
    wanted = ("run_stage", "run_iteration", "ship_decision",
              "finalize_iteration", "main")
    found = {}
    for mod in (foundry, dispatcher):
        for name in wanted:
            fn = getattr(mod, name, None)
            if callable(fn) and hasattr(fn, "__code__"):
                found[mod.__name__ + "." + name] = fn
    assert len(found) >= 4, sorted(found)
    for label, fn in found.items():
        assert "empty_seats" not in _names(fn), label
        assert "with_empty_seats" not in _names(fn), label


def test_b9_both_modules_import_in_a_fresh_interpreter():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
