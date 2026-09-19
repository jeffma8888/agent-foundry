"""Iteration 380 -- BLACK-BOX behavior tests.

One private generator `_walk_attempt_logs(cfg, limit)` becomes the single place
`foundry.py` decides "what counts as an attempt"; `gather_attempt_records` and
`gather_rescues` become thin consumers whose outputs are UNCHANGED by the fold.

ISOLATION: written from the PM spec (`pm.md` in this iteration's state dir) plus the
repo's own `tests/` conventions, the roadmap files and the product's OWN OUTPUT by
running it.  No implementation source, no `git diff`, no engineer/reviewer/fix notes
were read.  Every assertion drives the public interface and grades observable output.

Expected Behaviors, numbered as the spec numbers them:
   1. On a mixed fixture (killed-with-output, killed-without-output, clean,
      undecodable, non-matching filename) both consumers return FROZEN literals --
      the outputs are unchanged by the fold.
   2. `_ATTEMPT_LOG_RE.match(` has exactly ONE call site in foundry.py, and it lies
      inside `_walk_attempt_logs`.
   3. Neither consumer names `_ATTEMPT_LOG_RE`; each names `_walk_attempt_logs(` once.
   4. `_walk_attempt_logs` is a generator function yielding `(str, int, int, bool, str)`
      5-tuples, raw text, `""` for an undecodable log, nothing for a missing state.
   5. Kill/kind independence: a `throttl` + `agent run timed out after` log is kind
      `service` for the records AND a kill for rescues.
   6. Seam liveness through BOTH consumers (`_ATTEMPT_LOG_RE`, `ATTEMPT_KILL_TOKENS`).
   7. Window parity: `limit=1` is the newest iteration for both; `0`/`None` are all.
   8. Control-path freeze: no control function names the walk or a consumer;
      `dispatcher.py` is byte-identical to HEAD.

The frozen literals in Behavior 1 were MEASURED against HEAD `5e3d8e9`'s own module
(loaded from `git show HEAD:foundry.py`) before being frozen here; HEAD and the fold
agreed for limit in (None, 0, 1, 2, -3, 99).
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402,F401  -- in-process import-safety probe

THIS_ITER = 380

FOUNDRY_SRC = _ROOT / "foundry.py"
DISPATCHER_SRC = _ROOT / "dispatcher.py"

# A RELATIVE literal: an absolute machine path in a shipped test is a leak-guard
# finding (OPERATOR 2026-08-30, which reverted iteration 205 over exactly this shape).
REL_REPO = "products/_platform/state/iter-380"

# Names are FIXED by the spec's vocabulary, so they are reached by STRING: a rename
# must fail loudly rather than silently stop testing anything.
WALK = "_walk_attempt_logs"
RECORDS = "gather_attempt_records"
RESCUES = "gather_rescues"
CONSUMERS = (RECORDS, RESCUES)
TRIO = (WALK, RECORDS, RESCUES)

CONTROL_FNS = ("run_stage", "run_iteration", "build_prompt", "postrelease_step",
               "run_continuous")

KILL_TEXT = "agent run timed out after 600s\n"
CLEAN_TEXT = "nothing notable\n"
UNDECODABLE = b"\xff\xfe\xfa\x80 not utf8\n"
THROTTLED_TEXT = "throttl ... agent run timed out after 600s\n"


def _cfg(**over):
    kw = dict(name="demo", repo=REL_REPO, allowed_push_repo="demo")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _fn(name):
    fn = getattr(foundry, name, None)
    assert callable(fn), f"{name} must exist at module level in foundry.py"
    return fn


def _src(name) -> str:
    return inspect.getsource(_fn(name))


def _fabricate(tmp_path, tree):
    """Build a state dir the REAL readers walk.  `tree` maps relpath -> str | bytes."""
    cfg = _cfg(work_root=str(tmp_path))
    state = pathlib.Path(cfg.state)
    for rel, body in tree.items():
        p = state / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
    return cfg


# The spec's Behavior-1 fixture: 3 iteration dirs, five files, one of each kind.
MIXED = {
    "iter-5/pm.attempt1.log": KILL_TEXT,          # killed, WITH output
    "iter-5/pm.md": "out\n",
    "iter-6/engineer.attempt1.log": KILL_TEXT,    # killed, WITHOUT output
    "iter-7/tester.attempt2.log": CLEAN_TEXT,     # clean
    "iter-7/reviewer.attempt1.log": UNDECODABLE,  # undecodable -> text ""
    "iter-7/notes.txt": "not a log\n",            # non-matching filename -> skipped
}

# FROZEN literals -- what HEAD produced for MIXED (see module docstring).
EXPECTED_RECORDS = (
    ("pm", 5, 1, True, "timeout"),
    ("engineer", 6, 1, False, "timeout"),
    ("reviewer", 7, 1, False, "other"),
    ("tester", 7, 2, False, "other"),
)
EXPECTED_RESCUES = {
    "product": "demo", "attempts": 4, "kills": 2, "rescued": 1, "lost": 1,
    "rescue_rate": 50.0, "kill_rate": 50.0, "exit_code": 1, "verdict": "LOST ATTEMPTS",
    "rows": [
        {"stage": "engineer", "attempts": 1, "kills": 1, "rescued": 0, "lost": 1,
         "rescue_rate": 0.0, "kill_rate": 100.0},
        {"stage": "pm", "attempts": 1, "kills": 1, "rescued": 1, "lost": 0,
         "rescue_rate": 100.0, "kill_rate": 100.0},
        {"stage": "reviewer", "attempts": 1, "kills": 0, "rescued": 0, "lost": 0,
         "rescue_rate": None, "kill_rate": 0.0},
        {"stage": "tester", "attempts": 1, "kills": 0, "rescued": 0, "lost": 0,
         "rescue_rate": None, "kill_rate": 0.0},
    ],
}
EXPECTED_RECORDS_NEWEST = EXPECTED_RECORDS[2:]
EXPECTED_WALK = (
    ("pm", 5, 1, True, KILL_TEXT),
    ("engineer", 6, 1, False, KILL_TEXT),
    ("reviewer", 7, 1, False, ""),
    ("tester", 7, 2, False, CLEAN_TEXT),
)


# ========================================================================== #
# Behavior 1 -- outputs are unchanged by the fold (frozen HEAD literals)
# ========================================================================== #
def test_b1_gather_attempt_records_equals_the_frozen_head_literal(tmp_path) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    recs = _fn(RECORDS)(cfg)
    assert isinstance(recs, tuple), f"the contract is a tuple, got {type(recs)}"
    assert recs == EXPECTED_RECORDS, f"the fold changed the records:\n{recs}"


def test_b1_gather_rescues_to_dict_equals_the_frozen_head_literal(tmp_path) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    summary = _fn(RESCUES)(cfg)
    assert isinstance(summary, getattr(foundry, "RescueSummary")), type(summary)
    assert summary.to_dict() == EXPECTED_RESCUES, \
        f"the fold changed the rescues summary:\n{json.dumps(summary.to_dict(), indent=1)}"
    assert summary.exit_code == EXPECTED_RESCUES["exit_code"]


def test_b1_the_frozen_literals_are_not_vacuous(tmp_path) -> None:
    """DISCRIMINATION: the literals really depend on the fixture -- removing the
    output file of the rescued attempt moves BOTH consumers."""
    cfg = _fabricate(tmp_path, MIXED)
    (pathlib.Path(cfg.state) / "iter-5" / "pm.md").unlink()
    recs = _fn(RECORDS)(cfg)
    assert recs != EXPECTED_RECORDS and recs[0] == ("pm", 5, 1, False, "timeout"), recs
    d = _fn(RESCUES)(cfg).to_dict()
    assert d != EXPECTED_RESCUES and d["rescued"] == 0 and d["lost"] == 2, d


def test_b1_the_rescues_cli_json_is_the_same_summary(tmp_path) -> None:
    """The one CLI reaching `gather_rescues` renders the identical payload."""
    cfg = _fabricate(tmp_path, MIXED)
    conf = tmp_path / "cfg.json"
    conf.write_text(json.dumps({"name": cfg.name, "repo": str(tmp_path),
                                "allowed_push_repo": cfg.name,
                                "work_root": str(tmp_path)}), encoding="utf-8")
    p = subprocess.run([sys.executable, str(FOUNDRY_SRC), "rescues",
                        "--config", str(conf), "--json"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert "Traceback" not in p.stderr, p.stderr[-400:]
    payload = json.loads(p.stdout)
    assert payload == EXPECTED_RESCUES, json.dumps(payload, indent=1)
    assert p.returncode == EXPECTED_RESCUES["exit_code"], p.returncode


# ========================================================================== #
# Behavior 2 -- exactly ONE regex call site, and it lives in the generator
# ========================================================================== #
_MATCH_SITE = re.compile(r"_ATTEMPT_LOG_RE\.match\(")


def test_b2_the_regex_match_call_site_is_exactly_one() -> None:
    src = FOUNDRY_SRC.read_text(encoding="utf-8")
    n = len(_MATCH_SITE.findall(src))
    assert n == 1, f"shared walk only: expected exactly 1 `_ATTEMPT_LOG_RE.match(` site, found {n}"


def test_b2_the_single_call_site_lies_inside_the_generator() -> None:
    assert len(_MATCH_SITE.findall(_src(WALK))) == 1, \
        f"{WALK} must be the place the filename regex is applied"


# ========================================================================== #
# Behavior 3 -- both consumers are thin: no regex, exactly one walk call
# ========================================================================== #
@pytest.mark.parametrize("consumer", CONSUMERS)
def test_b3_no_consumer_names_the_filename_regex(consumer) -> None:
    assert "_ATTEMPT_LOG_RE" not in _src(consumer), \
        f"{consumer} still carries its own copy of the attempt-log walk"


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_b3_each_consumer_calls_the_generator_exactly_once(consumer) -> None:
    n = _src(consumer).count(WALK + "(")
    assert n == 1, f"{consumer} must consume {WALK} exactly once, found {n}"


def test_b3_rescues_consumes_the_generator_not_the_records_tuple() -> None:
    """Its lens needs the raw text that the records tuple has classified away."""
    assert RECORDS + "(" not in _src(RESCUES), f"{RESCUES} must not re-classify"


# ========================================================================== #
# Behavior 4 -- the generator's own contract
# ========================================================================== #
def test_b4_the_walk_is_a_module_level_generator_function_with_a_docstring() -> None:
    fn = _fn(WALK)
    assert inspect.isgeneratorfunction(fn), f"{WALK} must be a generator function"
    assert getattr(fn, "__module__", "") == "foundry", fn
    assert getattr(fn, "__qualname__", "") == WALK, f"{WALK} must be a MODULE-LEVEL def"
    assert (inspect.getdoc(fn) or "").strip(), f"{WALK} needs a docstring (seam convention)"
    params = inspect.signature(fn).parameters
    assert list(params) == ["cfg", "limit"], list(params)
    assert params["limit"].default is None, params["limit"]


def test_b4_the_walk_yields_typed_5_tuples_with_raw_text(tmp_path) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    gen = _fn(WALK)(cfg)
    assert inspect.isgenerator(gen), f"calling {WALK} must return a generator: {gen!r}"
    rows = tuple(gen)
    assert rows == EXPECTED_WALK, rows
    for row in rows:
        assert isinstance(row, tuple) and len(row) == 5, f"5-tuple contract: {row!r}"
        s, i, a, p, t = row
        assert type(s) is str and type(i) is int and type(a) is int, row
        assert type(p) is bool and type(t) is str, row


def test_b4_an_undecodable_log_yields_an_empty_text_row_not_a_skip(tmp_path) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    rows = [r for r in _fn(WALK)(cfg) if r[:3] == ("reviewer", 7, 1)]
    assert rows == [("reviewer", 7, 1, False, "")], rows


def test_b4_a_missing_state_dir_yields_nothing(tmp_path) -> None:
    cfg = _cfg(work_root=str(tmp_path / "never-created"))
    assert not pathlib.Path(cfg.state).exists(), "precondition"
    assert list(_fn(WALK)(cfg)) == []
    assert _fn(RECORDS)(cfg) == ()
    assert _fn(RESCUES)(cfg).exit_code == 2


def test_b4_an_unreadable_state_path_yields_nothing_instead_of_raising(tmp_path) -> None:
    """The OSError fallback: `state` is a FILE, so the walk itself fails."""
    cfg = _cfg(work_root=str(tmp_path))
    p = pathlib.Path(cfg.state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not a directory\n", encoding="utf-8")
    assert list(_fn(WALK)(cfg)) == []
    assert _fn(RECORDS)(cfg) == ()
    assert _fn(RESCUES)(cfg).exit_code == 2


def test_b4_the_walk_is_lazy_and_re_callable(tmp_path) -> None:
    """A generator, not a cached list: a log added between two calls is seen."""
    cfg = _fabricate(tmp_path, MIXED)
    assert len(tuple(_fn(WALK)(cfg))) == 4
    extra = pathlib.Path(cfg.state) / "iter-8" / "pm.attempt1.log"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text(CLEAN_TEXT, encoding="utf-8")
    rows = tuple(_fn(WALK)(cfg))
    assert len(rows) == 5 and rows[-1] == ("pm", 8, 1, False, CLEAN_TEXT), rows


# ========================================================================== #
# Behavior 5 -- kill is TOKENS-over-TEXT, never `kind == "timeout"`
# ========================================================================== #
THROTTLED = {"iter-9/pm.attempt1.log": THROTTLED_TEXT}


def test_b5_a_throttled_timeout_is_kind_service_yet_still_a_kill(tmp_path) -> None:
    tokens = getattr(foundry, "ATTEMPT_KILL_TOKENS")
    assert any(tok in THROTTLED_TEXT for tok in tokens), "precondition: the text IS a kill"
    cfg = _fabricate(tmp_path, THROTTLED)
    recs = _fn(RECORDS)(cfg)
    assert recs == (("pm", 9, 1, False, "service"),), recs
    assert recs[0][4] != "timeout", "kind must be the classifier's verdict, not the kill"
    summary = _fn(RESCUES)(cfg)
    pm = [r for r in summary.rows if r.stage == "pm"]
    assert len(pm) == 1 and pm[0].attempts == 1, summary.rows
    assert pm[0].kills == 1, f"a throttled timeout must still count as killed: {pm[0]}"
    assert pm[0].lost == 1 and pm[0].rescued == 0, pm[0]
    assert summary.to_dict()["kills"] == 1, summary.to_dict()


def test_b5_a_clean_log_is_neither_a_kill_nor_a_timeout(tmp_path) -> None:
    """DISCRIMINATION for the pin above: the kill count follows the tokens."""
    cfg = _fabricate(tmp_path, {"iter-9/pm.attempt1.log": CLEAN_TEXT})
    assert _fn(RECORDS)(cfg) == (("pm", 9, 1, False, "other"),)
    pm = _fn(RESCUES)(cfg).rows[0]
    assert (pm.stage, pm.attempts, pm.kills) == ("pm", 1, 0), pm


# ========================================================================== #
# Behavior 6 -- seam liveness through BOTH consumers
# ========================================================================== #
def test_b6_the_filename_regex_seam_bites_through_both_consumers(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    assert _fn(RECORDS)(cfg) and _fn(RESCUES)(cfg).exit_code != 2, "precondition"
    monkeypatch.setattr(foundry, "_ATTEMPT_LOG_RE", re.compile(r"(?!)"))
    assert _fn(RECORDS)(cfg) == (), "the filename regex is captured at def time"
    assert _fn(RESCUES)(cfg).exit_code == 2, "rescues does not read the regex seam live"
    assert list(_fn(WALK)(cfg)) == []


def test_b6_the_kill_tokens_seam_bites_rescues_and_leaves_records_alone(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    before = _fn(RECORDS)(cfg)
    assert _fn(RESCUES)(cfg).to_dict()["kills"] == 2, "precondition"
    monkeypatch.setattr(foundry, "ATTEMPT_KILL_TOKENS", ())
    summary = _fn(RESCUES)(cfg)
    assert summary.rows, "the attempts are still counted"
    assert all(r.kills == 0 for r in summary.rows), summary.rows
    assert summary.to_dict()["kills"] == 0 and summary.to_dict()["attempts"] == 4
    assert _fn(RECORDS)(cfg) == before == EXPECTED_RECORDS, \
        "the kill tokens must not reach the records' kind"


def test_b6_the_glob_seam_bites_through_both_consumers(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    monkeypatch.setattr(foundry, "ATTEMPT_LOG_GLOB", "no-such-dir-*/*.attempt*.log")
    assert _fn(RECORDS)(cfg) == (), "the glob constant is captured at def time"
    assert _fn(RESCUES)(cfg).exit_code == 2


def test_b6_the_output_presence_seam_bites_through_both_consumers(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    monkeypatch.setattr(foundry, "_stage_output_present", lambda *a, **k: True)
    assert [r[3] for r in _fn(RECORDS)(cfg)] == [True] * 4
    d = _fn(RESCUES)(cfg).to_dict()
    assert d["kills"] == 2 and d["rescued"] == 2 and d["lost"] == 0, d


def test_b6_the_iteration_window_seam_bites_through_both_consumers(tmp_path, monkeypatch) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    assert len(_fn(RECORDS)(cfg, 1)) == 2, "precondition: a positive limit windows"
    monkeypatch.setattr(foundry, "iteration_numbers", lambda names: [])
    assert _fn(RECORDS)(cfg, 1) == (), "the window helper is captured at def time"
    assert _fn(RESCUES)(cfg, 1).exit_code == 2


# ========================================================================== #
# Behavior 7 -- window parity between the two consumers and the walk
# ========================================================================== #
def test_b7_limit_1_is_the_newest_iteration_for_both_consumers(tmp_path) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    recs = _fn(RECORDS)(cfg, 1)
    assert recs == EXPECTED_RECORDS_NEWEST, recs
    assert {r[1] for r in recs} == {7}
    d = _fn(RESCUES)(cfg, 1).to_dict()
    assert d["attempts"] == 2 and d["kills"] == 0 and d["exit_code"] == 0, d
    assert sorted(r["stage"] for r in d["rows"]) == ["reviewer", "tester"], d["rows"]
    assert [w[:3] for w in _fn(WALK)(cfg, 1)] == [r[:3] for r in recs]


@pytest.mark.parametrize("limit", [None, 0, -3])
def test_b7_a_none_or_non_positive_limit_scans_everything_for_both(tmp_path, limit) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    assert _fn(RECORDS)(cfg, limit) == EXPECTED_RECORDS, limit
    assert _fn(RESCUES)(cfg, limit).to_dict() == EXPECTED_RESCUES, limit
    assert tuple(_fn(WALK)(cfg, limit)) == EXPECTED_WALK, limit


@pytest.mark.parametrize("limit", [None, 0, 1, 2, 3, -3, 99])
def test_b7_the_walk_the_records_and_the_rescues_see_the_same_window(tmp_path, limit) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    walk_keys = [w[:3] for w in _fn(WALK)(cfg, limit)]
    recs = _fn(RECORDS)(cfg, limit)
    assert [r[:3] for r in recs] == walk_keys, (limit, recs, walk_keys)
    assert _fn(RESCUES)(cfg, limit).to_dict()["attempts"] == len(walk_keys), limit


def test_b7_a_positive_limit_keeps_the_newest_iterations_only(tmp_path) -> None:
    cfg = _fabricate(tmp_path, MIXED)
    assert sorted({r[1] for r in _fn(RECORDS)(cfg, 1)}) == [7]
    assert sorted({r[1] for r in _fn(RECORDS)(cfg, 2)}) == [6, 7]
    assert sorted({r[1] for r in _fn(RECORDS)(cfg, 3)}) == [5, 6, 7]
    assert _fn(RESCUES)(cfg, 2).to_dict()["attempts"] == 3
    assert _fn(RESCUES)(cfg, 99).to_dict() == EXPECTED_RESCUES


# ========================================================================== #
# Behavior 8 -- control path unmoved, so a loop in flight resumes identically
# ========================================================================== #
@pytest.mark.parametrize("fn", CONTROL_FNS)
@pytest.mark.parametrize("name", TRIO)
def test_b8_no_control_function_names_the_walk_or_a_consumer(fn, name) -> None:
    assert name not in _src(fn), \
        f"{fn} names {name}; a running loop's resume semantics moved"


@pytest.mark.parametrize("name", TRIO)
def test_b8_the_dispatcher_never_names_the_walk_or_a_consumer(name) -> None:
    assert name not in DISPATCHER_SRC.read_text(encoding="utf-8")


def test_b8_the_dispatcher_is_byte_identical_to_head() -> None:
    r = subprocess.run(["git", "show", "HEAD:dispatcher.py"], cwd=str(_ROOT),
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip("git history unavailable (not a checkout)")
    assert r.stdout == DISPATCHER_SRC.read_bytes(), "dispatcher.py differs from HEAD"


@pytest.mark.parametrize("mod", ["foundry", "dispatcher"])
def test_b8_both_modules_import_from_a_clean_interpreter(mod) -> None:
    p = subprocess.run([sys.executable, "-c", f"import {mod}"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert p.returncode == 0, f"import {mod} failed: {p.stderr[-400:]}"


def test_b8_the_generator_is_reachable_only_from_the_two_consumers() -> None:
    src = FOUNDRY_SRC.read_text(encoding="utf-8")
    n = len(re.findall(rf"(?<!def ){WALK}\(", src))
    assert n == 2, f"{WALK} has {n} call sites in foundry.py, expected 2"
