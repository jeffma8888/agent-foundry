"""Black-box behaviour tests for iter 140 -- `foundry lint-config`, pointed at a DISPATCHER
ROSTER, must SAY SO and exit 2, and must never emit the `_`-prefix advice that would make the
dispatcher read zero work items and shut the whole company down.

Spec: products/_platform/state/iter-140/pm.md, Expected Behaviors 1-10.

  1. module-level pure `dispatch_roster_note(raw)` exists, is callable, touches no I/O, never
     mutates its argument, is deterministic, and never raises for ANY mapping.
  2. a ROSTER (top-level `work_items` is a list) -> a `str` naming the roster, the key, the
     phrase `not a product config`, and every non-empty `config` value IN FILE ORDER.
  3. a NON-roster mapping (no key / None / str / number / dict) and an empty mapping -> None.
  4. the note NEVER carries the destructive advice (`prefix it with`, `unknown config key`).
  5. hostile rosters still return a note and still do not raise.
  6. `lint_config_cli(path)` on a roster FILE returns 2 and prints the note, with neither
     `prefix it with` nor the historical `lint-config: cannot read config`.
  7. `--json` prints exactly ONE parseable document, top-level keys exactly
     ("config_path", "error", "exit_code", "kind") IN THAT ORDER, exit_code 2,
     kind "dispatch_roster", config_path the path passed in, error the human note, and
     NOTHING else on stdout.
  8. regressions unchanged: valid product config -> 0; typo'd key -> 1 with one unknown-key
     finding per bad key; missing file and invalid JSON -> 2 with exactly the 3-key document.
  9. seam + fail-safe: the CLI reaches `dispatch_roster_note` by BARE module name, and if that
     seam returns None OR raises, a roster falls back to the iteration-134 unknown-key report
     (exit 1) with no exception escaping.
 10. PM roadmap maintenance, read off the tree: `## Item 16` archived, one-line stub pointer
     left in the index, index under 54,000 chars, both gap brakes clean, and iteration 140's
     ledger row (<= 120 chars) plus its archive bullet present.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-140 PM spec's Expected Behaviors, the
conventions of tests/ (the `_capture`/`_valid_data` helpers of test_iter134_behavior.py and the
live-brake shape of test_iter124_behavior.py), and the OBSERVABLE surface of the product --
importing the modules, CALLING the public functions, reading committed repo docs off disk, and
runtime introspection of code objects. The implementation SOURCE text of foundry.py and
dispatcher.py, the engineer's notes (engineer.md), the reviewer's notes (reviewer.md) and
`git diff` were NOT read.

Offline and deterministic: every config is built in memory or under `tmp_path`, nothing in the
tree is mutated, and the single subprocess is a local fresh-interpreter import probe (no git
writes, no network, no agent run, no sleeps).
"""
from __future__ import annotations

import collections
import io
import json
import pathlib
import re
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (dormancy probe -- Behavior 10 support)

THIS_ITER = 140

# Contract literals, held here so the test pins the CONTRACT rather than echoing the module.
ROSTER_PHRASE = "dispatcher roster"
KEY_NAME = "work_items"
NOT_A_PRODUCT = "not a product config"
DESTRUCTIVE_ADVICE = "prefix it with"
UNKNOWN_KEY = "unknown config key"
CANNOT_READ = "lint-config: cannot read config"
ROSTER_JSON_KEYS = ("config_path", "error", "exit_code", "kind")
ERROR_JSON_KEYS = ("config_path", "error", "exit_code")
FINDINGS_JSON_KEYS = ("config_path", "findings", "n_errors", "n_warnings",
                      "ok", "verdict", "exit_code")

# names that would mean the "pure" helper reached the filesystem, a subprocess or the network
IO_NAMES = frozenset({
    "open", "read_text", "write_text", "read_bytes", "write_bytes", "Path",
    "mkdir", "unlink", "remove", "rename", "load_config", "loads", "dump",
    "dumps", "subprocess", "check_output", "Popen", "urlopen", "socket",
    "requests", "input", "shutil", "glob", "time", "sleep", "monotonic",
    "datetime", "now", "random", "environ", "getenv", "system", "popen",
})

INDEX_PATH = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE_PATH = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _capture(fn):
    """Run fn() with stdout and stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters for `--json`: the document must be the ENTIRE stdout."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _roster(*configs, **extra):
    """A dispatcher-roster-shaped mapping naming `configs` in the given order."""
    items = []
    for i, cfg in enumerate(configs):
        entry = {"name": "team%d" % i, "enabled": True}
        if cfg is not None:
            entry["config"] = cfg
        items.append(entry)
    data = {"work_items": items}
    data.update(extra)
    return data


def _valid_data(tmp_path):
    """A raw config MAPPING whose every key is a real `ProductConfig` field and whose every
    referenced path exists inside tmp_path, so it lints clean. `work_root` points under
    tmp_path so the loader's directory creation stays out of the product repo."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    vision = tmp_path / "VISION.md"
    vision.write_text("intent")
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("roadmap")
    (tmp_path / "qref").mkdir(exist_ok=True)
    (tmp_path / "roles").mkdir(exist_ok=True)
    return dict(
        name="prod",
        repo=str(repo),
        allowed_push_repo="prod",
        branch="main",
        vision=str(vision),
        roadmap=str(roadmap),
        quality_ref=str(tmp_path / "qref"),
        roles_dir=str(tmp_path / "roles"),
        work_root=str(tmp_path / "work"),
        test_cmd="uv run pytest",
        push_enabled=True,
    )


def _write(tmp_path, data, fname="config.json"):
    p = tmp_path / fname
    p.write_text(json.dumps(data))
    return str(p)


def _co_names_deep(fn):
    """Every name referenced by fn, including names inside nested code objects."""
    seen, names = set(), set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names.update(code.co_names)
        names.update(getattr(code, "co_varnames", ()))
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                stack.append(const)
    return names


# Hostile / exotic mappings: none of these may raise (Behaviors 1 and 5).
HOSTILE_MAPPINGS = [
    {},
    {"work_items": []},
    {"work_items": ["a string", None, 3, 4.5, True, (), []]},
    {"work_items": [{}, {"name": "no-config"}]},
    {"work_items": [{"config": 5}, {"config": None}, {"config": ""}, {"config": []}]},
    {"work_items": [{"config": "p/a.json"}, "junk", {"config": 7}]},
    {"work_items": [{"config": "p/a.json"}] * 40},
    {"work_items": None},
    {"work_items": "a string"},
    {"work_items": 7},
    {"work_items": {}},
    {"work_items": {"nested": "dict"}},
    {"work_items": True},
    {"name": "prod", "push_enabled": True},
    {"_comment": "a roster-shaped comment", "work_items": [{"config": "x"}]},
    collections.OrderedDict([("work_items", [{"config": "p/o.json"}])]),
    types.MappingProxyType({"work_items": [{"config": "p/m.json"}]}),
    {1: "non-str key", "work_items": [{"config": "p/n.json"}]},
    {"work_items": [{"config": "p/deep.json", "nested": {"a": [1, {"b": 2}]}}]},
]


# ==========================================================================
# Behavior 1 -- the pure seam exists, is total, and touches nothing
# ==========================================================================
def test_b1_dispatch_roster_note_exists_and_is_callable():
    fn = getattr(foundry, "dispatch_roster_note", None)
    assert fn is not None, "foundry.dispatch_roster_note is missing"
    assert callable(fn), "foundry.dispatch_roster_note is not callable"


def test_b1_never_raises_for_any_mapping():
    for raw in HOSTILE_MAPPINGS:
        try:
            got = foundry.dispatch_roster_note(raw)
        except Exception as exc:  # pragma: no cover - a raise IS the failure
            pytest.fail("dispatch_roster_note(%r) raised %r" % (raw, exc))
        assert got is None or isinstance(got, str), \
            "dispatch_roster_note(%r) returned %r, expected str or None" % (raw, got)


def test_b1_does_not_mutate_its_argument():
    raw = _roster("products/a/config.json", "products/b/config.json")
    snapshot = json.dumps(raw, sort_keys=True)
    foundry.dispatch_roster_note(raw)
    assert json.dumps(raw, sort_keys=True) == snapshot, \
        "dispatch_roster_note must not mutate its argument"


def test_b1_is_deterministic():
    raw = _roster("products/a/config.json", "products/b/config.json")
    first = foundry.dispatch_roster_note(raw)
    for _ in range(4):
        assert foundry.dispatch_roster_note(raw) == first, \
            "dispatch_roster_note must be deterministic"


def test_b1_touches_no_io():
    leaked = IO_NAMES & _co_names_deep(foundry.dispatch_roster_note)
    assert leaked == frozenset(), \
        "dispatch_roster_note must be pure; it references %s" % sorted(leaked)


# ==========================================================================
# Behavior 2 -- a roster yields a note naming the roster and every config
# ==========================================================================
def test_b2_note_names_the_roster_the_key_and_the_kind():
    note = foundry.dispatch_roster_note(_roster("products/a/config.json"))
    assert isinstance(note, str) and note.strip(), "a roster must yield a non-empty str note"
    for needle in (ROSTER_PHRASE, KEY_NAME, NOT_A_PRODUCT):
        assert needle in note, "note is missing %r; note was:\n%s" % (needle, note)


def test_b2_note_lists_every_config_in_file_order():
    configs = ["products/zeta/config.json", "products/alpha/config.json",
               "products/mid/config.json", "products/_platform/config.json"]
    note = foundry.dispatch_roster_note(_roster(*configs))
    positions = []
    for cfg in configs:
        idx = note.find(cfg)
        assert idx >= 0, "note omits config %r; note was:\n%s" % (cfg, note)
        positions.append(idx)
    assert positions == sorted(positions), \
        "configs must appear in FILE order, got positions %r for %r" % (positions, configs)


def test_b2_note_omits_no_config_even_with_duplicate_names():
    note = foundry.dispatch_roster_note(_roster("p/one.json", "p/two.json", "p/one.json"))
    assert note.count("p/one.json") >= 1 and "p/two.json" in note


def test_b2_extra_top_level_keys_do_not_suppress_the_note():
    note = foundry.dispatch_roster_note(
        _roster("p/a.json", poll_seconds=30, _comment="hand-edited"))
    assert isinstance(note, str) and "p/a.json" in note


# ==========================================================================
# Behavior 3 -- a non-roster mapping yields None
# ==========================================================================
@pytest.mark.parametrize("raw", [
    {},
    {"name": "prod", "push_enabled": True},
    {"work_items": None},
    {"work_items": "products/a/config.json"},
    {"work_items": 0},
    {"work_items": 7},
    {"work_items": 1.5},
    {"work_items": {}},
    {"work_items": {"a": [{"config": "p/a.json"}]}},
])
def test_b3_non_roster_mappings_return_none(raw):
    got = foundry.dispatch_roster_note(raw)
    assert got is None, "dispatch_roster_note(%r) returned %r, expected None" % (raw, got)


def test_b3_only_a_list_counts_as_a_roster():
    """A tuple is not the JSON shape a roster file can hold, so the contract is a `list`."""
    assert isinstance(foundry.dispatch_roster_note({"work_items": []}), str)
    assert foundry.dispatch_roster_note({"work_items": {}}) is None


# ==========================================================================
# Behavior 4 -- the note never carries the destructive advice
# ==========================================================================
def test_b4_note_never_carries_the_destructive_advice():
    for raw in HOSTILE_MAPPINGS:
        note = foundry.dispatch_roster_note(raw)
        if note is None:
            continue
        assert DESTRUCTIVE_ADVICE not in note, \
            "note repeats the destructive advice %r for %r" % (DESTRUCTIVE_ADVICE, raw)
        assert UNKNOWN_KEY not in note, \
            "note repeats %r for %r" % (UNKNOWN_KEY, raw)


def test_b4_note_tells_the_operator_to_keep_the_key():
    """The whole point: the note must not read as permission to rename the key."""
    note = foundry.dispatch_roster_note(_roster("p/a.json"))
    assert "_work_items" not in note, \
        "note names the `_`-prefixed key, which is the destructive edit"


# ==========================================================================
# Behavior 5 -- hostile rosters still answer, and still do not raise
# ==========================================================================
@pytest.mark.parametrize("raw", [
    {"work_items": []},
    {"work_items": ["a string", None, 3]},
    {"work_items": [{}, {"name": "x"}]},
    {"work_items": [{"config": 5}, {"config": None}]},
    {"work_items": [{"config": "p/a.json"}, "junk", {"config": 7}]},
])
def test_b5_hostile_rosters_still_return_a_note(raw):
    note = foundry.dispatch_roster_note(raw)
    assert isinstance(note, str) and note.strip(), \
        "a list-valued work_items is a roster even when hostile; got %r" % (note,)
    for needle in (ROSTER_PHRASE, KEY_NAME, NOT_A_PRODUCT):
        assert needle in note, "hostile-roster note is missing %r" % (needle,)


def test_b5_non_string_config_values_are_simply_absent():
    note = foundry.dispatch_roster_note({"work_items": [{"config": 5}, {"config": "p/ok.json"}]})
    assert "p/ok.json" in note
    assert DESTRUCTIVE_ADVICE not in note


# ==========================================================================
# Behavior 6 -- the CLI on a roster FILE: exit 2, the note, no bad advice
# ==========================================================================
def test_b6_cli_on_a_roster_file_exits_2_and_prints_the_note(tmp_path):
    path = _write(tmp_path, _roster("products/a/config.json", "products/b/config.json"),
                  "roster.json")
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 2, "lint_config_cli on a roster returned %r, expected 2" % (rc,)
    text = out + err
    for needle in (ROSTER_PHRASE, KEY_NAME, NOT_A_PRODUCT,
                   "products/a/config.json", "products/b/config.json"):
        assert needle in text, "CLI output is missing %r; output was:\n%s" % (needle, text)


def test_b6_cli_output_carries_neither_bad_advice_nor_cannot_read(tmp_path):
    path = _write(tmp_path, _roster("products/a/config.json"), "roster.json")
    _, out, err = _capture(lambda: foundry.lint_config_cli(path))
    text = out + err
    assert DESTRUCTIVE_ADVICE not in text, "CLI still emits %r" % (DESTRUCTIVE_ADVICE,)
    assert UNKNOWN_KEY not in text, "CLI still emits %r" % (UNKNOWN_KEY,)
    assert CANNOT_READ not in text, "CLI misreports a readable roster as unreadable"


def test_b6_empty_roster_file_still_exits_2(tmp_path):
    path = _write(tmp_path, {"work_items": []}, "empty_roster.json")
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 2
    assert ROSTER_PHRASE in out + err


# ==========================================================================
# Behavior 7 -- the --json document: exact keys, exact order, nothing else
# ==========================================================================
def test_b7_json_document_shape_and_key_order(tmp_path):
    raw = _roster("products/a/config.json", "products/b/config.json")
    path = _write(tmp_path, raw, "roster.json")
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    assert rc == 2
    doc = json.loads(out)  # raises if stdout is not exactly one document
    assert tuple(doc.keys()) == ROSTER_JSON_KEYS, \
        "top-level keys %r, expected %r" % (tuple(doc.keys()), ROSTER_JSON_KEYS)
    assert doc["exit_code"] == 2
    assert doc["kind"] == "dispatch_roster"
    assert doc["config_path"] == path, \
        "config_path %r must equal the path passed in (%r)" % (doc["config_path"], path)
    assert doc["error"] == foundry.dispatch_roster_note(raw), \
        "the document's error must be the human note verbatim"


def test_b7_json_stdout_is_only_the_document(tmp_path):
    path = _write(tmp_path, _roster("products/a/config.json"), "roster.json")
    _, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    assert out.strip().startswith("{") and out.strip().endswith("}"), \
        "stdout must be exactly one JSON document, got:\n%s" % out
    assert json.dumps(json.loads(out)) is not None
    assert DESTRUCTIVE_ADVICE not in out


def test_b7_json_error_is_multiline_note_not_truncated(tmp_path):
    path = _write(tmp_path, _roster("products/a/config.json"), "roster.json")
    _, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    err_text = json.loads(out)["error"]
    for needle in (ROSTER_PHRASE, KEY_NAME, NOT_A_PRODUCT, "products/a/config.json"):
        assert needle in err_text


# ==========================================================================
# Behavior 8 -- the three pre-existing paths, unchanged
# ==========================================================================
def test_b8_valid_product_config_still_exits_0(tmp_path):
    path = _write(tmp_path, _valid_data(tmp_path))
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 0, "a valid product config must still exit 0; output:\n%s%s" % (out, err)


def test_b8_typod_key_still_exits_1_with_one_finding_per_bad_key(tmp_path):
    data = _valid_data(tmp_path)
    data["push_enable"] = data.pop("push_enabled")
    data["totaly_bogus"] = 1
    path = _write(tmp_path, data)
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    text = out + err
    assert rc == 1, "a typo'd product config must still exit 1, got %r" % (rc,)
    assert text.count(UNKNOWN_KEY) == 2, \
        "expected one unknown-key finding per bad key, output was:\n%s" % text
    assert ROSTER_PHRASE not in text, "a product config must not be called a roster"


def test_b8_missing_file_still_exits_2_with_the_three_key_document(tmp_path):
    missing = str(tmp_path / "nope.json")
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(missing, as_json=True))
    assert rc == 2
    assert tuple(json.loads(out).keys()) == ERROR_JSON_KEYS


def test_b8_invalid_json_still_exits_2_with_the_three_key_document(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(str(p), as_json=True))
    assert rc == 2
    assert tuple(json.loads(out).keys()) == ERROR_JSON_KEYS


def test_b8_missing_and_invalid_human_paths_still_say_cannot_read(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    for target in (str(tmp_path / "nope.json"), str(p)):
        rc, out, err = _capture(lambda: foundry.lint_config_cli(target))
        assert rc == 2
        assert CANNOT_READ in out + err, \
            "the historical unreadable-config message must survive for %r" % target


# ==========================================================================
# Behavior 9 -- bare-name seam and the two-way fail-safe
# ==========================================================================
def test_b9_cli_reaches_the_seam_by_bare_module_name(tmp_path, monkeypatch):
    path = _write(tmp_path, _roster("products/a/config.json"), "roster.json")
    seen = []

    def spy(raw):
        seen.append(raw)
        return "SCRIPTED ROSTER NOTE for the test"

    monkeypatch.setattr(foundry, "dispatch_roster_note", spy)
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    assert seen, "lint_config_cli must reach dispatch_roster_note by BARE module name"
    assert rc == 2
    assert "SCRIPTED ROSTER NOTE for the test" in out + err, \
        "the CLI must print what the seam returned"


def test_b9_seam_returning_none_falls_back_to_the_iter134_report(tmp_path, monkeypatch):
    path = _write(tmp_path, _roster("products/a/config.json"), "roster.json")
    monkeypatch.setattr(foundry, "dispatch_roster_note", lambda raw: None)
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    text = out + err
    assert rc == 1, "a suppressed seam must leave the iteration-134 behavior (exit 1), got %r" % (rc,)
    assert UNKNOWN_KEY in text, "the fallback must still be the unknown-key findings report"
    assert CANNOT_READ not in text, "the fallback must NOT become the unreadable-file path"


def test_b9_seam_raising_leaves_previous_behavior_exactly_unchanged(tmp_path, monkeypatch):
    path = _write(tmp_path, _roster("products/a/config.json"), "roster.json")

    def boom(raw):
        raise RuntimeError("seam exploded")

    monkeypatch.setattr(foundry, "dispatch_roster_note", boom)
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    text = out + err
    assert rc == 1, "a RAISING seam must not change the exit code from 1, got %r" % (rc,)
    assert UNKNOWN_KEY in text, "a raising seam must still leave the unknown-key report"
    assert CANNOT_READ not in text, \
        "a raising seam must not collapse into the unreadable-file path (exit 2)"


def test_b9_raising_seam_keeps_the_json_findings_document(tmp_path, monkeypatch):
    path = _write(tmp_path, _roster("products/a/config.json"), "roster.json")
    monkeypatch.setattr(foundry, "dispatch_roster_note",
                        lambda raw: (_ for _ in ()).throw(ValueError("nope")))
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    assert rc == 1
    assert tuple(json.loads(out).keys()) == FINDINGS_JSON_KEYS, \
        "the fallback must be the iteration-134 findings document, not the exit-2 shape"


def test_b9_valid_config_is_unaffected_by_a_raising_seam(tmp_path, monkeypatch):
    path = _write(tmp_path, _valid_data(tmp_path))
    monkeypatch.setattr(foundry, "dispatch_roster_note",
                        lambda raw: (_ for _ in ()).throw(ValueError("nope")))
    rc, _, _ = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 0, "a valid config never reaches the seam, so it must still exit 0"


# ==========================================================================
# Behavior 10 -- roadmap maintenance, read off the tree
# ==========================================================================
def _index_text():
    return INDEX_PATH.read_text()


def _archive_text():
    return ARCHIVE_PATH.read_text()


def _heading_positions(text, pattern):
    return [m.start() for m in re.finditer(pattern, text, re.M)]


def _section(text, start):
    """Slice from a heading to the next H1 OR H2 -- a `## `-only boundary steps straight
    over an intervening `# ` H1 and carries unrelated prose with it."""
    nxt = re.compile(r"^#{1,2} ", re.M).search(text, start + 3)
    return text[start:nxt.start()] if nxt else text[start:]


def test_b10_item16_section_lives_in_the_archive():
    starts = _heading_positions(_archive_text(), r"^## Item 16")
    assert len(starts) == 1, "expected exactly one `## Item 16` heading in the archive"
    section = _section(_archive_text(), starts[0])
    assert len(section) > 1000, "the archived Item 16 section is suspiciously short (%d chars)" % len(section)
    assert "leak" in section.lower(), "the archived section must be the leak-guard item"


def test_b10_index_keeps_only_a_one_line_stub_pointer():
    idx = _index_text()
    starts = _heading_positions(idx, r"^## Item 16")
    assert len(starts) == 1, "expected exactly one `## Item 16` line left in the index"
    stub = _section(idx, starts[0])
    assert len(stub) < 600, "the index stub must be short, got %d chars" % len(stub)
    assert "ARCHIV" in stub.upper(), "the stub must say the section was archived"
    assert "PLATFORM_ROADMAP_ARCHIVE.md" in stub, \
        "the stub must point at the archive file by name"


def test_b10_the_archived_body_is_gone_from_the_index():
    """A representative paragraph of the archived section must no longer be in the index."""
    starts = _heading_positions(_archive_text(), r"^## Item 16")
    section = _section(_archive_text(), starts[0])
    idx = _index_text()
    long_lines = [ln.strip() for ln in section.splitlines() if len(ln.strip()) > 60]
    assert long_lines, "the archived section has no substantial prose to check"
    still_present = [ln for ln in long_lines if ln in idx]
    assert still_present == [], \
        "%d archived line(s) are still in the index, e.g. %r" % (
            len(still_present), still_present[:1])


def test_b10_index_is_under_the_declared_budget():
    size = len(_index_text())
    wall = foundry.ROADMAP_INDEX_HARD_CHARS   # iter 145: single source of truth
    assert size < wall, (
        "PLATFORM_ROADMAP.md is %d chars, budget is < %d -- ARCHIVE spent prose to "
        "PLATFORM_ROADMAP_ARCHIVE.md; raising ROADMAP_INDEX_HARD_CHARS is NOT the remedy"
        % (size, wall))


def test_b10_both_gap_brakes_report_no_gaps():
    idx, arc = _index_text(), _archive_text()
    assert foundry.roadmap_archive_gaps(idx, arc) == [], \
        "roadmap_archive_gaps reports gaps: %r" % (foundry.roadmap_archive_gaps(idx, arc),)
    subjects = foundry.git_ship_subjects(str(_ROOT))
    if not subjects:
        pytest.skip("no git history available -- missing INFRA, not a lost record")
    shipped = set(foundry.shipped_iterations(subjects)) | {THIS_ITER}
    gaps = foundry.roadmap_ledger_gaps(idx, arc, tuple(sorted(shipped)))
    assert gaps == [], "roadmap_ledger_gaps reports gaps: %r" % (gaps,)


def test_b10_iteration_140_has_its_ledger_row_and_archive_bullet():
    rows = [ln for ln in _index_text().splitlines() if ln.startswith("- iter 140 ")]
    assert len(rows) == 1, "expected exactly one `- iter 140 ` ledger row, got %d" % len(rows)
    assert len(rows[0]) <= 120, "the ledger row is %d chars, budget is 120" % len(rows[0])
    bullets = [ln for ln in _archive_text().splitlines() if ln.startswith("- **iter 140 ")]
    assert len(bullets) == 1, \
        "expected exactly one `- **iter 140 ` archive bullet, got %d" % len(bullets)


# ==========================================================================
# Cross-cutting: the change stays off the control path, and this file is ASCII
# ==========================================================================
def test_no_new_cli_verb_named_for_the_roster():
    assert not hasattr(foundry, "lint_roster_cli"), \
        "a `lint-roster` verb is explicitly Out of Scope for this iteration"


def test_dispatcher_does_not_gain_the_seam():
    assert not hasattr(dispatcher, "dispatch_roster_note"), \
        "the seam belongs to foundry only; the dispatcher must be untouched"


def test_both_modules_still_import_in_a_fresh_interpreter():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher; print('ok')"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, "fresh import failed:\n%s\n%s" % (proc.stdout, proc.stderr)
    assert "ok" in proc.stdout


def test_this_test_file_is_pure_ascii():
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    bad = [(i + 1, ln) for i, ln in enumerate(text.splitlines()) if not ln.isascii()]
    assert bad == [], "non-ASCII on line(s): %r" % ([n for n, _ in bad],)
