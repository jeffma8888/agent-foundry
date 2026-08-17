"""Iteration 188 -- BLACK-BOX behavior tests: the dormant gap-register reader.

Spec under test (products/_platform/state/iter-188/pm.md), Expected Behaviors 1-14:
   1. `gather_gaps(cfg)` shape; unconfigured returns the empty feed and reads NO file
   2. records are the STORED dicts unchanged -- no `priority`, no `confidence`
   3. `addressed` / `retired` excluded; `open` / `partially-addressed` kept
   4. `gap_layers` filter (empty = every layer survives)
   5. order = descending stored (severity, frequency, tractability), ties on id
   6. unparseable / non-dict / field-missing records are SKIPPED and COUNTED
   7. `gap_advice` is pure, deterministic, no trailing newline, caps at TOP_N
   8. a CONFIGURED register with zero survivors still renders a NON-EMPTY block
   9. `pm_gap_block` returns "" for every non-`pm` stage
  10. `pm_gap_block(cfg, "pm")` == `gap_advice(gather_gaps(cfg))` + exactly one "\n"
  11. either seam raising -> "" (no propagation), bare-name call so monkeypatch bites
  12. the two optional off-by-default `ProductConfig` fields, and their resolution
  13. ZERO call site -- the prompt is byte-identical with and without a register
  14. the frozen config-field list gained the two names in DECLARATION order

ISOLATION CONTRACT (HONORED): written from the iter-188 PM spec, the conventions of
the existing `tests/test_iter18*_behavior.py` modules, and the product's OWN
OBSERVABLE surface (calling its public functions).  `foundry.py`'s implementation
TEXT was not read, and neither were `engineer.md`, `reviewer.md`,
`IMPLEMENTATION.patch`, nor `git diff`.

OFFLINE + FRESH-CLONE SAFE: every register fixture is built in `tmp_path`; no test
reads the real `~/projects/agent-gap-radar`, asserts an absolute machine path, or
pins a record count.
"""
from __future__ import annotations

import builtins
import io
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 188

FEED_KEYS = {"register", "records", "unreadable"}
DERIVED = ("priority", "confidence")
NON_PM_STAGES = ("engineer", "reviewer", "tester", "fix", "final")
ALL_STAGES = ("pm",) + NON_PM_STAGES
KEEP_STATUS = ("open", "partially-addressed")
DROP_STATUS = ("addressed", "retired")


# --------------------------------------------------------------------------
# helpers -- mirror tests/test_iter183_behavior.py; `repo` and `work_root` are
# ALWAYS tmp dirs so the real foundry repo / state can never be touched
# --------------------------------------------------------------------------
def _record(gid, sev, freq, trac, layer="orchestration", status="open",
            classes=("peer-reviewed", "vendor-primary")):
    """A record spelled with the register's OWN 16 stored keys and nothing else."""
    return {
        "id": gid,
        "title": "title of %s" % gid,
        "layer": layer,
        "gap_type": "missing-primitive",
        "status": status,
        "problem": "problem text",
        "symptom": "symptom text",
        "why_now": "why now text",
        "existing": "existing text",
        "severity": sev,
        "frequency": freq,
        "tractability": trac,
        "evidence": [{"source_class": c, "locator": "https://example.test/%s" % c,
                      "excerpt": "an excerpt"} for c in classes],
        "build_hypothesis": "hypothesis text",
        "tags": ["a-tag"],
        "check": {"present_when": {"any_file_matches": ["x"]}},
    }


def _register(root, records=(), extra_files=()):
    """Build `<root>/gaps/<id>.json` for each record. Returns `str(root)`."""
    root = pathlib.Path(root)
    gaps = root / "gaps"
    gaps.mkdir(parents=True, exist_ok=True)
    for rec in records:
        (gaps / ("%s.json" % rec["id"])).write_text(json.dumps(rec), encoding="utf-8")
    for name, text in extra_files:
        (gaps / name).write_text(text, encoding="utf-8")
    return str(root)


def _write_cfg(tmp_path, sub="p", **over):
    tmp_path = pathlib.Path(tmp_path) / sub
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "repo").mkdir(exist_ok=True)
    (tmp_path / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text("- a roadmap item\n", encoding="utf-8")
    data = {
        "name": "demoprod",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "roadmap": str(tmp_path / "ROADMAP.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _cfg(tmp_path, sub="p", **over):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, sub=sub, **over)))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text("## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
                  encoding="utf-8")
    return cfg


def _seeded(tmp_path, sub="p", records=(), extra_files=(), **over):
    """A cfg whose `gap_register` points at a freshly built tmp register."""
    reg = _register(pathlib.Path(tmp_path) / (sub + "-reg"), records, extra_files)
    return _cfg(tmp_path, sub=sub, gap_register=reg, **over), reg


def _ids(feed):
    return [r["id"] for r in feed["records"]]


def _line_for(block, gid):
    hits = [ln for ln in block.splitlines() if gid in ln]
    assert len(hits) == 1, "expected exactly one line naming %s, got %r" % (gid, hits)
    return hits[0]


# --------------------------------------------------------------------------
# behavior 1 -- shape, and the unconfigured feed touches no disk
# --------------------------------------------------------------------------
def test_b1_gather_gaps_exists_and_is_callable() -> None:
    """FILE-FIRST oracle: the seam this iteration owes must exist and be callable."""
    for name in ("gather_gaps", "gap_advice", "pm_gap_block", "GAP_BLOCK_TOP_N"):
        assert hasattr(foundry, name), "foundry.%s is missing" % name
    assert foundry.GAP_BLOCK_TOP_N == 5


def test_b1_feed_is_a_plain_dict_with_exactly_three_keys(tmp_path) -> None:
    cfg, reg = _seeded(tmp_path, records=[_record("GAP-001", 3, 3, 3)])
    feed = foundry.gather_gaps(cfg)
    assert type(feed) is dict
    assert set(feed) == FEED_KEYS
    assert feed["register"] == reg
    assert isinstance(feed["records"], tuple)
    assert isinstance(feed["unreadable"], int)


def test_b1_unconfigured_returns_empty_feed_and_reads_no_file(tmp_path, monkeypatch) -> None:
    """An unset `gap_register` must short-circuit BEFORE any file is opened."""
    cfg = _cfg(tmp_path)
    assert cfg.gap_register == ""

    def _boom(*a, **k):
        raise AssertionError("gather_gaps opened a file with no register configured")

    monkeypatch.setattr(io, "open", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(pathlib.Path, "glob", _boom)
    try:
        feed = foundry.gather_gaps(cfg)
    finally:
        monkeypatch.undo()  # restore BEFORE asserting, so pytest can read sources
    assert feed == {"register": "", "records": (), "unreadable": 0}


# --------------------------------------------------------------------------
# behavior 2 -- stored records, carried verbatim, nothing synthesized
# --------------------------------------------------------------------------
def test_b2_records_are_the_stored_dicts_unchanged(tmp_path) -> None:
    stored = _record("GAP-001", 4, 3, 2)
    cfg, _ = _seeded(tmp_path, records=[stored])
    (got,) = foundry.gather_gaps(cfg)["records"]
    assert type(got) is dict
    assert got == stored, "the record was not carried verbatim"
    for key in DERIVED:
        assert key not in got, "foundry synthesized a %r the register owns" % key


def test_b2_no_synthesized_key_on_any_record(tmp_path) -> None:
    recs = [_record("GAP-001", 5, 5, 5), _record("GAP-002", 1, 1, 1)]
    cfg, _ = _seeded(tmp_path, records=recs)
    by_id = {r["id"]: r for r in recs}
    for got in foundry.gather_gaps(cfg)["records"]:
        assert set(got) == set(by_id[got["id"]]), "key set changed for %s" % got["id"]


# --------------------------------------------------------------------------
# behavior 3 -- status filter (the register's real 4-value vocabulary)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status", KEEP_STATUS)
def test_b3_kept_statuses_survive(tmp_path, status) -> None:
    cfg, _ = _seeded(tmp_path, sub=status, records=[_record("GAP-001", 3, 3, 3, status=status)])
    assert _ids(foundry.gather_gaps(cfg)) == ["GAP-001"]


@pytest.mark.parametrize("status", DROP_STATUS)
def test_b3_dropped_statuses_are_excluded(tmp_path, status) -> None:
    cfg, _ = _seeded(tmp_path, sub=status, records=[
        _record("GAP-001", 3, 3, 3, status=status),
        _record("GAP-002", 1, 1, 1, status="open"),
    ])
    feed = foundry.gather_gaps(cfg)
    assert _ids(feed) == ["GAP-002"]
    assert feed["unreadable"] == 0, "a filtered record is not an unreadable one"


# --------------------------------------------------------------------------
# behavior 4 -- layer filter
# --------------------------------------------------------------------------
def test_b4_layer_filter_keeps_only_named_layers(tmp_path) -> None:
    recs = [_record("GAP-001", 3, 3, 3, layer="orchestration"),
            _record("GAP-002", 3, 3, 3, layer="memory"),
            _record("GAP-003", 3, 3, 3, layer="evaluation")]
    cfg, _ = _seeded(tmp_path, sub="lay", records=recs,
                     gap_layers=["memory", "evaluation"])
    assert cfg.gap_layers == ("memory", "evaluation")
    assert _ids(foundry.gather_gaps(cfg)) == ["GAP-002", "GAP-003"]


def test_b4_empty_layer_filter_keeps_every_layer(tmp_path) -> None:
    recs = [_record("GAP-001", 3, 3, 3, layer="orchestration"),
            _record("GAP-002", 3, 3, 3, layer="memory")]
    cfg, _ = _seeded(tmp_path, sub="nolay", records=recs)
    assert cfg.gap_layers == ()
    assert sorted(_ids(foundry.gather_gaps(cfg))) == ["GAP-001", "GAP-002"]


# --------------------------------------------------------------------------
# behavior 5 -- total, stable order on the STORED integers
# --------------------------------------------------------------------------
def test_b5_order_is_descending_stored_triple_with_id_tiebreak(tmp_path) -> None:
    """The spec's own worked case: (5,4,2) must sort ABOVE (3,3,5).

    That is the ordering the register's weighted sum produces and the ordering a
    naive severity*frequency*tractability PRODUCT would invert (45 vs 40).
    """
    recs = [_record("GAP-005", 3, 3, 5), _record("GAP-013", 5, 4, 2),
            _record("GAP-016", 5, 4, 4), _record("GAP-002", 4, 4, 4),
            _record("GAP-004", 4, 4, 4)]
    cfg, _ = _seeded(tmp_path, sub="ord", records=recs)
    got = _ids(foundry.gather_gaps(cfg))
    assert got == ["GAP-016", "GAP-013", "GAP-002", "GAP-004", "GAP-005"]
    assert got.index("GAP-013") < got.index("GAP-005"), "product ordering leaked in"
    # the (4,4,4) tie broke on ASCENDING id, so the order is total
    assert got.index("GAP-002") < got.index("GAP-004")


def test_b5_order_is_independent_of_filesystem_listing(tmp_path) -> None:
    """Same records, ids chosen so name order != score order: order still holds."""
    recs = [_record("AAA-1", 1, 1, 1), _record("BBB-2", 5, 5, 5),
            _record("CCC-3", 3, 3, 3)]
    cfg, _ = _seeded(tmp_path, sub="fs", records=recs)
    assert _ids(foundry.gather_gaps(cfg)) == ["BBB-2", "CCC-3", "AAA-1"]


# --------------------------------------------------------------------------
# behavior 6 -- unreadable records are skipped AND counted; siblings survive
# --------------------------------------------------------------------------
BAD_FILES = [
    ("not-json.json", "{ this is not json"),
    ("a-list.json", json.dumps([1, 2, 3])),
    ("a-string.json", json.dumps("just a string")),
]
MISSING_FIELD = ("id", "status", "layer", "severity", "frequency", "tractability")


@pytest.mark.parametrize("name,text", BAD_FILES)
def test_b6_unparseable_or_non_dict_is_skipped_and_counted(tmp_path, name, text) -> None:
    cfg, _ = _seeded(tmp_path, sub=name.replace(".", "-"),
                     records=[_record("GAP-001", 3, 3, 3)],
                     extra_files=[(name, text)])
    feed = foundry.gather_gaps(cfg)
    assert _ids(feed) == ["GAP-001"], "a valid sibling was lost"
    assert feed["unreadable"] == 1


@pytest.mark.parametrize("field", MISSING_FIELD)
def test_b6_record_missing_a_required_field_is_skipped_and_counted(tmp_path, field) -> None:
    bad = _record("GAP-999", 3, 3, 3)
    bad.pop(field)
    cfg, _ = _seeded(tmp_path, sub="miss-" + field,
                     records=[_record("GAP-001", 3, 3, 3)],
                     extra_files=[("bad.json", json.dumps(bad))])
    feed = foundry.gather_gaps(cfg)
    assert _ids(feed) == ["GAP-001"], "dropping %r lost the valid sibling too" % field
    assert feed["unreadable"] == 1, "a record missing %r was not counted" % field


def test_b6_unreadable_count_accumulates(tmp_path) -> None:
    cfg, _ = _seeded(tmp_path, sub="many-bad",
                     records=[_record("GAP-001", 3, 3, 3)],
                     extra_files=[(n, t) for n, t in BAD_FILES])
    feed = foundry.gather_gaps(cfg)
    assert _ids(feed) == ["GAP-001"]
    assert feed["unreadable"] == len(BAD_FILES)


# --------------------------------------------------------------------------
# behavior 7 -- gap_advice: pure, deterministic, capped, and self-describing
# --------------------------------------------------------------------------
def test_b7_empty_feed_renders_empty_string() -> None:
    assert foundry.gap_advice({"register": "", "records": (), "unreadable": 0}) == ""


def test_b7_advice_is_pure_and_deterministic(tmp_path, monkeypatch) -> None:
    cfg, _ = _seeded(tmp_path, sub="pure", records=[_record("GAP-001", 3, 3, 3)])
    feed = foundry.gather_gaps(cfg)

    def _boom(*a, **k):
        raise AssertionError("gap_advice touched the outside world")

    monkeypatch.setattr(io, "open", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    try:
        first = foundry.gap_advice(feed)
        second = foundry.gap_advice(feed)
    finally:
        monkeypatch.undo()
    assert first == second, "gap_advice is not deterministic for one feed"
    assert first, "a feed with a record rendered nothing"
    assert not first.endswith("\n"), "gap_advice must carry NO trailing newline"


def test_b7_one_line_per_record_carries_every_required_datum(tmp_path) -> None:
    rec = _record("GAP-001", 5, 4, 2, layer="memory",
                  classes=("peer-reviewed", "vendor-primary", "peer-reviewed"))
    cfg, _ = _seeded(tmp_path, sub="line", records=[rec])
    block = foundry.gap_advice(foundry.gather_gaps(cfg))
    line = _line_for(block, "GAP-001")
    for token in (rec["title"], rec["layer"], rec["gap_type"], rec["status"]):
        assert token in line, "%r missing from the record line" % token
    for label, value in (("severity", 5), ("frequency", 4), ("tractability", 2)):
        assert "%s=%d" % (label, value) in line, "%s not printed" % label
    # DISTINCT source_class values, each named once even though one repeats
    assert line.count("peer-reviewed") == 1
    assert line.count("vendor-primary") == 1


def test_b7_block_caps_at_top_n_and_says_so(tmp_path) -> None:
    n = foundry.GAP_BLOCK_TOP_N
    recs = [_record("GAP-%03d" % i, 5, 5, 5 - 0) for i in range(1, n + 3)]
    for i, r in enumerate(recs):          # strictly descending, so order is known
        r["severity"] = 9 - i
    cfg, _ = _seeded(tmp_path, sub="cap", records=recs)
    feed = foundry.gather_gaps(cfg)
    assert len(feed["records"]) == n + 2, "the FEED must not be truncated"
    block = foundry.gap_advice(feed)
    shown = [r["id"] for r in feed["records"][:n]]
    hidden = [r["id"] for r in feed["records"][n:]]
    for gid in shown:
        assert gid in block, "%s should be shown" % gid
    for gid in hidden:
        assert gid not in block, "%s is beyond TOP_N and must not be shown" % gid
    assert str(len(hidden)) in block, "the block does not say how many it withheld"


def test_b7_block_states_the_derived_scores_are_not_restated(tmp_path) -> None:
    cfg, _ = _seeded(tmp_path, sub="derived", records=[_record("GAP-001", 3, 3, 3)])
    block = foundry.gap_advice(foundry.gather_gaps(cfg))
    low = block.lower()
    for word in DERIVED + ("deriv",):
        assert word in low, "the block never mentions %r" % word
    line = _line_for(block, "GAP-001")
    for word in DERIVED:
        assert word not in line.lower(), "a record line restates %r" % word


# --------------------------------------------------------------------------
# behavior 8 -- a configured-but-empty register is NOT silence
# --------------------------------------------------------------------------
def test_b8_configured_register_with_zero_survivors_still_renders(tmp_path) -> None:
    cfg, reg = _seeded(tmp_path, sub="zero",
                       records=[_record("GAP-001", 3, 3, 3, status="addressed")],
                       extra_files=[("bad.json", "nope")])
    feed = foundry.gather_gaps(cfg)
    assert feed["records"] == () and feed["unreadable"] == 1
    block = foundry.gap_advice(feed)
    assert block, "a configured register that read nothing rendered SILENCE"
    assert reg in block, "the block does not name the register it read"
    assert "0" in block and "1" in block, "survivor/unreadable counts not reported"
    # and it is distinguishable from 'no register configured'
    assert foundry.gap_advice({"register": "", "records": (), "unreadable": 0}) == ""


def test_b8_misconfigured_register_path_is_still_reported(tmp_path) -> None:
    """A `gap_register` typo must not render as silence either.

    Deliberately assertion-weak on WHICH counts appear: the spec does not fix
    whether a missing `gaps/` child is an `unreadable` or a clean zero, so this
    only pins the property that matters -- the operator sees the path it read.
    """
    missing = pathlib.Path(tmp_path) / "typo" / "not-a-register"
    cfg = _cfg(tmp_path, sub="typo-cfg", gap_register=str(missing))
    feed = foundry.gather_gaps(cfg)
    assert set(feed) == FEED_KEYS
    assert feed["records"] == ()
    block = foundry.gap_advice(feed)
    assert block, "a misconfigured register rendered SILENCE"
    assert str(missing) in block


# --------------------------------------------------------------------------
# behaviors 9-11 -- pm_gap_block: stage gate, composition, and fail-soft
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stage", NON_PM_STAGES)
def test_b9_non_pm_stages_get_nothing(tmp_path, stage) -> None:
    cfg, _ = _seeded(tmp_path, sub="stage-" + stage,
                     records=[_record("GAP-001", 5, 5, 5)])
    assert foundry.gap_advice(foundry.gather_gaps(cfg)), "fixture must be non-empty"
    assert foundry.pm_gap_block(cfg, stage) == ""


def test_b10_pm_stage_is_advice_plus_exactly_one_newline(tmp_path) -> None:
    cfg, _ = _seeded(tmp_path, sub="pm-nl", records=[_record("GAP-001", 4, 4, 4),
                                                     _record("GAP-002", 2, 2, 2)])
    advice = foundry.gap_advice(foundry.gather_gaps(cfg))
    got = foundry.pm_gap_block(cfg, "pm")
    assert got == advice + "\n"
    assert not got.endswith("\n\n"), "more than one trailing newline"


def test_b10_pm_stage_is_empty_when_unconfigured(tmp_path) -> None:
    cfg = _cfg(tmp_path, sub="pm-off")
    assert cfg.gap_register == ""
    for stage in ALL_STAGES:
        assert foundry.pm_gap_block(cfg, stage) == ""


@pytest.mark.parametrize("seam", ("gather_gaps", "gap_advice"))
def test_b11_either_seam_raising_yields_empty_and_does_not_propagate(
        tmp_path, monkeypatch, seam) -> None:
    cfg, _ = _seeded(tmp_path, sub="raise-" + seam,
                     records=[_record("GAP-001", 5, 5, 5)])
    assert foundry.pm_gap_block(cfg, "pm"), "fixture must be non-empty before patching"

    def _explode(*a, **k):
        raise RuntimeError("scripted %s failure" % seam)

    monkeypatch.setattr(foundry, seam, _explode)      # bare-name call site proof
    assert foundry.pm_gap_block(cfg, "pm") == ""


def test_b11_seams_are_called_by_bare_module_name(tmp_path, monkeypatch) -> None:
    """A scripted substitute must be OBSERVED, else the call is not a seam."""
    cfg, _ = _seeded(tmp_path, sub="seam", records=[_record("GAP-001", 5, 5, 5)])
    monkeypatch.setattr(foundry, "gap_advice", lambda feed: "SCRIPTED-ADVICE")
    assert foundry.pm_gap_block(cfg, "pm") == "SCRIPTED-ADVICE\n"


# --------------------------------------------------------------------------
# behavior 12 -- the two optional, off-by-default config fields
# --------------------------------------------------------------------------
def test_b12_config_omitting_both_fields_loads_with_off_defaults(tmp_path) -> None:
    cfg = _cfg(tmp_path, sub="defaults")
    assert cfg.gap_register == ""
    assert cfg.gap_layers == ()


def test_b12_gap_register_expands_foundry_and_tilde(tmp_path) -> None:
    braced = _cfg(tmp_path, sub="brace", gap_register="{FOUNDRY}/some-register")
    assert "{FOUNDRY}" not in braced.gap_register
    assert braced.gap_register.startswith(str(foundry.FOUNDRY))
    assert braced.gap_register.endswith("some-register")

    tilde = _cfg(tmp_path, sub="tilde", gap_register="~/some-register")
    assert not tilde.gap_register.startswith("~")
    assert tilde.gap_register.endswith("some-register")


def test_b12_gap_layers_json_list_becomes_a_tuple_of_str(tmp_path) -> None:
    cfg = _cfg(tmp_path, sub="layers", gap_layers=["orchestration", "memory"])
    assert cfg.gap_layers == ("orchestration", "memory")
    assert all(isinstance(x, str) for x in cfg.gap_layers)


def test_b12_neither_field_is_a_new_accepted_unknown_key(tmp_path) -> None:
    """Both names must be REAL fields, so `unknown_config_keys` must not flag them."""
    assert foundry.unknown_config_keys({"gap_register": "x", "gap_layers": []}) == ()


def test_b12_only_platform_opts_in_and_it_does_so_clone_safely() -> None:
    """RETIRED BY ITERATION 192: `_platform` now DECLARES the opt-in deliberately.

    Iter 188's brake asserted no tracked config set either field, which is exactly
    the assertion iteration 192 makes false (it wired the seam and opted `_platform`
    in). The half worth keeping is the clone-safety half: a tracked file may not
    carry an absolute machine path, and no OTHER product may be switched on by
    accident. This asserts the DECLARED config only -- never that the register
    directory exists, because a fresh clone has no sibling register.
    """
    seen = 0
    for cfg_path in sorted((_ROOT / "products").glob("*/config.json")):
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        seen += 1
        if cfg_path.parent.name == "_platform":
            assert data["gap_register"].startswith("~/"), (
                "the tracked opt-in must be a ~ path, not an absolute machine path")
            assert isinstance(data["gap_layers"], list) and data["gap_layers"]
            continue
        assert "gap_register" not in data, "%s enables gap_register" % cfg_path.name
        assert "gap_layers" not in data, "%s enables gap_layers" % cfg_path.name
    assert seen >= 1, "no tracked product config was examined -- vacuous scan"


# --------------------------------------------------------------------------
# behavior 13 -- the call site, proved from OUTSIDE the module
# (iteration 192 wired the seam; both dormancy brakes below were RETIRED by it and
#  now assert the live wiring instead. The exhaustive prompt matrix lives in
#  tests/test_iter192_behavior.py.)
# --------------------------------------------------------------------------
def _prompt(cfg, stage, tmp_path):
    it_dir = pathlib.Path(cfg.work_root) / "state" / ("iter-%d" % THIS_ITER)
    it_dir.mkdir(parents=True, exist_ok=True)
    return foundry.build_prompt(cfg, THIS_ITER, stage, "%s.md" % stage,
                                it_dir / ("%s.md" % stage), it_dir, "extra!")


def _twin_cfgs(tmp_path):
    """Two configs over the SAME tmp tree, differing ONLY in `gap_register`.

    Both must share every other path: an earlier version of this test built them
    in two tmp subdirs, so `repo`/`work_root` differed and all 6 prompts
    'diverged' by the fixture's own path strings.  Uniform divergence of one
    magnitude across every stage is a MEASUREMENT bug, never data.
    """
    base = pathlib.Path(tmp_path) / "dorm"
    base.mkdir(parents=True, exist_ok=True)
    (base / "repo").mkdir(exist_ok=True)
    (base / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (base / "ROADMAP.md").write_text("- a roadmap item\n", encoding="utf-8")
    reg = _register(base / "reg", [_record("GAP-001", 5, 5, 5),
                                  _record("GAP-002", 4, 4, 4)])
    common = {
        "name": "demoprod",
        "repo": str(base / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(base / "VISION.md"),
        "roadmap": str(base / "ROADMAP.md"),
        "work_root": str(base / "work"),
    }
    out = []
    for label, extra in (("off", {}), ("on", {"gap_register": reg})):
        data = dict(common)
        data.update(extra)
        path = base / ("%s.json" % label)
        path.write_text(json.dumps(data), encoding="utf-8")
        cfg = foundry.load_config(str(path))
        lp = pathlib.Path(cfg.learnings)
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
                      encoding="utf-8")
        out.append(cfg)
    off, on = out
    assert off.repo == on.repo and off.work_root == on.work_root
    assert off.learnings == on.learnings and off.roles_dir == on.roles_dir
    return off, on, reg


def test_b13_register_moves_the_pm_prompt_and_only_the_pm_prompt(tmp_path) -> None:
    """RETIRED BY ITERATION 192: configuring the register now moves `pm`, only `pm`.

    Iter 188 asserted the opposite (no prompt moves at all) because the seam shipped
    with zero call site. The surviving guarantee is the one every non-opted-in
    product relies on: the delta is EXACTLY the seam's output, inserted once, in the
    `pm` prompt and nowhere else.
    """
    off, on, reg = _twin_cfgs(tmp_path)
    assert off.gap_register == "" and on.gap_register == reg
    block = foundry.pm_gap_block(on, "pm")
    assert block, "the ON fixture must render a block"
    for stage in ALL_STAGES:
        a = _prompt(off, stage, tmp_path)
        b = _prompt(on, stage, tmp_path)
        if stage == "pm":
            assert b != a, "the pm prompt must carry the configured register"
            assert len(b) == len(a) + len(block)
            assert b.replace(block, "", 1) == a, (
                "the pm delta is not EXACTLY one insertion of the seam's output")
        else:
            assert a == b, (
                "stage %r prompt changed when a gap register was configured" % stage)


def test_b13_every_stage_prompt_consumes_the_seam_exactly_once(tmp_path,
                                                               monkeypatch) -> None:
    """RETIRED BY ITERATION 192: the sentinel must now appear for EVERY stage.

    A stage-IGNORING scripted seam proves WHERE the gating lives: the call site is
    unconditional, so the `stage != "pm"` decision is inside `pm_gap_block` and no
    caller can get the branch wrong. Iter 188's version asserted the marker was
    absent everywhere, which is the assertion iteration 192 deliberately falsifies.
    """
    cfg, _ = _seeded(tmp_path, sub="sentinel", records=[_record("GAP-001", 5, 5, 5)])
    sentinel = "ZZ-GAP-BLOCK-SENTINEL-192-ZZ"
    monkeypatch.setattr(foundry, "pm_gap_block", lambda c, s: sentinel + "\n")
    for stage in ALL_STAGES:
        assert _prompt(cfg, stage, tmp_path).count(sentinel) == 1, (
            "stage %r does not consume pm_gap_block exactly once" % stage)


def test_b13_both_modules_still_import() -> None:
    """The product quality bar, asserted in-process (no subprocess, no 120s risk)."""
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert hasattr(dispatcher, "main")


# --------------------------------------------------------------------------
# behavior 14 -- the frozen field list GREW, in declaration order
# --------------------------------------------------------------------------
def test_b14_new_field_names_are_last_in_declaration_order() -> None:
    names = tuple(foundry.config_field_names())
    assert names[-2:] == ("gap_register", "gap_layers")
    assert len(set(names)) == len(names), "a config field name is duplicated"


def test_b14_prior_iteration_freezes_were_extended_not_weakened() -> None:
    """The two known schema freezes must still assert EXACTLY, not loosely."""
    text = (_ROOT / "tests" / "test_iter157_behavior.py").read_text(encoding="utf-8")
    assert "\"gap_register\", \"gap_layers\"," in text.replace("'", '"'), (
        "test_iter157's FROZEN_FIELDS was not extended with the two new names")
    assert "== FROZEN_FIELDS" in text, "iter157's exact-equality freeze was weakened"
