"""Black-box behaviour tests for iter 89 -- `foundry restaffing-review --json`
(item 22 bite 2, ORG_DESIGN section 10): a machine-readable JSON payload for the
read-only hysteresis-constrained re-staffing DIFF review CLI, the THIRD CLI in
the org-design decision-CLI `--json` cadence and the FIRST whose result is a
NESTED (composite) value object. The change is a clean ADD-A-METHOD (x3,
composing) + ADD-A-FLAG on the pre-existing DORMANT core (RestaffingChange /
RestaffingRejection / RestaffingDiff / decide_restaffing / restaffing_review_cli,
item 22 bite 2): three composing `to_dict()` methods + an `as_json: bool = False`
kw param on `restaffing_review_cli` + a `--json` store_true subparser arg + a
one-line dispatch edit. ZERO call site: nothing in the running loop invokes it.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the frozen composite value object via
`foundry.decide_restaffing` + the three new `to_dict` methods, and the CLI via
`foundry.restaffing_review_cli` / `foundry.main(["restaffing-review", ...])`. The
CLI's file/args parse is grounded in observed behaviour: a review JSON object
carries `changes`/`tenures`/`logged_triggers`/`k`/`cap`; the JSON-equality tests
supply ALL FIVE keys explicitly so the expected `decide_restaffing(...)` call is
independent of the CLI's absent-key defaults. The dormancy proof uses only public
runtime introspection -- compiled function name tables (`co_names` recursed via
`_co_names_deep`) + a `dispatcher.py` source symbol-count -- and the mechanical
ASCII acceptance check uses `inspect.getsource` SCOPED to the new/changed symbols
only (the established suite convention; never a whole-file scan / never
`git diff`). Fully offline and deterministic: no subprocess/git/network except
the fresh-import regression probe. There is deliberately NO `git diff --quiet
HEAD` control-path guard in this file -- the iter-86 fix removed that over-broad
freeze anti-pattern.
"""
import contextlib
import dataclasses
import importlib.util
import inspect
import io
import json
import os
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

# Fixed key orders each to_dict() must expose, exactly.
CHANGE_KEYS = ["action", "role", "trigger"]
REJECTION_KEYS = ["change", "rule"]
DIFF_KEYS = ["accepted", "rejected", "k", "cap",
             "accepted_count", "rejected_count", "has_diff", "verdict"]

# The SIX PRE-EXISTING restaffing symbols (shipped iter 79, so a whole-file grep
# would FALSE-POSITIVE -- their names are all over the CLI/subparser/dispatch).
# Dormancy is proven ONLY against these specific symbols + the command string --
# NOT the generic `to_dict` name (~30 classes own one).
RST_SYMBOLS = (
    "RestaffingChange",
    "RestaffingRejection",
    "RestaffingDiff",
    "decide_restaffing",
    "restaffing_review_cli",
    "_normalize_restaffing_change",
)


def _ch(action, role, trigger="t"):
    return {"action": action, "role": role, "trigger": trigger}


def _decide(changes, tenures=None, logged_triggers=None, k=None, cap=None):
    return foundry.decide_restaffing(changes, tenures=tenures,
                                     logged_triggers=logged_triggers, k=k, cap=cap)


# The four canonical decide_restaffing results (Behaviors 4/6/7).
def _fx_diff():
    # >=1 accepted change -> DIFF, has_diff True
    return _decide([_ch("activate", "a")], logged_triggers=["t"])


def _fx_noop():
    # 0 accepted (empty changes) -> NOOP, has_diff False
    return _decide([])


def _fx_all_rules():
    # cap=1: a accepted; b overflow -> cap; c unlogged trigger -> trigger;
    # d deactivate tenure 0 < k=3 -> tenure. All three rejection rules present,
    # >=1 accepted -> DIFF.
    return _decide(
        [_ch("activate", "a", "t"), _ch("activate", "b", "t"),
         _ch("activate", "c", "z"), _ch("deactivate", "d", "t")],
        tenures={"d": 0}, logged_triggers=["t"], k=3, cap=1)


def _fx_empty():
    return _decide([])


CANONICAL = (_fx_diff, _fx_noop, _fx_all_rules, _fx_empty)


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def _write(tmp_path, review, name="review.json"):
    p = tmp_path / name
    p.write_text(json.dumps(review), encoding="utf-8")
    return p


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
    spec = importlib.util.spec_from_file_location("leak_guard_iter89_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous (the four canonical
# cases really do behave as the spec's names claim)
# ==========================================================================
def test_precondition_canonical_cases_behave_as_named():
    d = _fx_diff()
    assert d.verdict == "DIFF" and d.has_diff is True and d.accepted_count >= 1
    n = _fx_noop()
    assert n.verdict == "NOOP" and n.has_diff is False and n.accepted_count == 0
    a = _fx_all_rules()
    assert a.verdict == "DIFF" and a.accepted_count == 1
    rules = sorted(r.rule for r in a.rejected)
    assert rules == ["cap", "tenure", "trigger"], (
        "all-three-rules fixture did not exercise every rejection rule: %r" % rules
    )
    e = _fx_empty()
    assert e.accepted == () and e.rejected == () and e.verdict == "NOOP"


# ==========================================================================
# Behavior 1 -- RestaffingChange.to_dict(): exactly 3 keys in order, str values
# ==========================================================================
def test_b01_change_to_dict_three_keys_str_values():
    for c in _fx_all_rules().accepted + tuple(r.change for r in _fx_all_rules().rejected):
        d = c.to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == CHANGE_KEYS, "change key order %r" % list(d.keys())
        assert d["action"] == c.action
        assert d["role"] == c.role
        assert d["trigger"] == c.trigger
        for v in d.values():
            assert type(v) is str
        json.dumps(d)  # never raises


# ==========================================================================
# Behavior 2 -- RestaffingRejection.to_dict(): 2 keys, change is a plain dict
# ==========================================================================
def test_b02_rejection_to_dict_change_is_plain_dict():
    for rej in _fx_all_rules().rejected:
        d = rej.to_dict()
        assert list(d.keys()) == REJECTION_KEYS, "rejection key order %r" % list(d.keys())
        assert d["change"] == rej.change.to_dict()
        assert type(d["change"]) is dict, "nested change is not a plain dict"
        assert not isinstance(d["change"], foundry.RestaffingChange)
        assert d["rule"] == rej.rule
        assert type(d["rule"]) is str
        json.dumps(d)


# ==========================================================================
# Behavior 3 -- RestaffingDiff.to_dict(): exactly 8 keys in order, NO exit_code
# ==========================================================================
def test_b03_diff_to_dict_eight_keys_no_exit_code():
    for fx in CANONICAL:
        d = fx().to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == DIFF_KEYS, "diff key order %r" % list(d.keys())
        assert len(d) == 8
        assert "exit_code" not in d
    # RD has no exit_code property either (the discriminator vs ConfigLint)
    assert not hasattr(foundry.RestaffingDiff, "exit_code")


# ==========================================================================
# Behavior 4 -- accepted/rejected are LISTS of dicts, in order
# ==========================================================================
def test_b04_accepted_rejected_are_lists_of_dicts_in_order():
    diff = _fx_all_rules()
    d = diff.to_dict()
    assert type(d["accepted"]) is list, "accepted is not a list (frozen tuple leaked)"
    assert type(d["rejected"]) is list, "rejected is not a list (frozen tuple leaked)"
    assert d["accepted"] == [c.to_dict() for c in diff.accepted]
    assert d["rejected"] == [r.to_dict() for r in diff.rejected]
    for el in d["accepted"]:
        assert type(el) is dict
    for el in d["rejected"]:
        assert type(el) is dict
        assert type(el["change"]) is dict
    # empty review -> empty lists (not tuples)
    e = _fx_empty().to_dict()
    assert e["accepted"] == [] and type(e["accepted"]) is list
    assert e["rejected"] == [] and type(e["rejected"]) is list


# ==========================================================================
# Behavior 5 -- scalar keys reuse the frozen fields/props; has_diff by IDENTITY
# ==========================================================================
def test_b05_scalars_reuse_frozen_props():
    for fx in CANONICAL:
        diff = fx()
        d = diff.to_dict()
        assert d["k"] == diff.k
        assert d["cap"] == diff.cap
        assert d["accepted_count"] == diff.accepted_count
        assert d["rejected_count"] == diff.rejected_count
        assert d["has_diff"] is diff.has_diff  # identity: a re-derived value cannot pass
        assert d["verdict"] == diff.verdict
        assert d["verdict"] in ("DIFF", "NOOP")
        assert type(d["k"]) is int and type(d["cap"]) is int
        assert type(d["accepted_count"]) is int and type(d["rejected_count"]) is int
        assert type(d["has_diff"]) is bool
        assert type(d["verdict"]) is str


# ==========================================================================
# Behavior 6 -- DISCRIMINATING nested two-level round-trip
# ==========================================================================
def test_b06_nested_round_trip_all_canonical():
    for fx in CANONICAL:
        d = fx().to_dict()
        s = json.dumps(d)  # must NOT raise (a tuple of frozen dataclasses would)
        assert json.loads(s) == d, (
            "to_dict did not two-level round-trip through JSON for %s" % fx.__name__
        )


# ==========================================================================
# Behavior 7 -- all three to_dict are PURE + READ-ONLY (fresh dict, no mutation)
# ==========================================================================
def test_b07_diff_to_dict_read_only_and_fresh():
    diff = _fx_all_rules()
    before = dataclasses.asdict(diff)
    d1 = diff.to_dict()
    # mutate aggressively: append, overwrite a scalar, and mutate a NESTED value
    d1["accepted"].append({"action": "x", "role": "y", "trigger": "z"})
    d1["verdict"] = "TAMPERED"
    d1["accepted"][0]["role"] = "TAMPERED"
    d2 = diff.to_dict()
    assert dataclasses.asdict(diff) == before, "to_dict mutated the frozen instance"
    assert d2 == _fx_all_rules().to_dict(), "second to_dict was affected by mutation"
    assert d1 is not d2, "to_dict returned the same dict object across calls"
    # nested elements are fresh too
    assert d2["accepted"][0]["role"] != "TAMPERED"


def test_b07_change_and_rejection_to_dict_fresh():
    c = _fx_diff().accepted[0]
    assert c.to_dict() == c.to_dict()
    assert c.to_dict() is not c.to_dict()
    rej = _fx_all_rules().rejected[0]
    assert rej.to_dict() == rej.to_dict()
    assert rej.to_dict() is not rej.to_dict()
    # mutating a change dict does not affect the frozen change
    cd = c.to_dict()
    cd["role"] = "TAMPERED"
    assert c.to_dict()["role"] != "TAMPERED"


# ==========================================================================
# Behavior 8 -- default == as_json=False human render, byte-for-byte + same rc
# ==========================================================================
def test_b08_default_equals_explicit_false(tmp_path):
    review = {"changes": [_ch("activate", "a", "t"), _ch("activate", "b", "t"),
                          _ch("activate", "c", "z"), _ch("deactivate", "d", "t")],
              "tenures": {"d": 0}, "logged_triggers": ["t"], "k": 3, "cap": 1}
    p = _write(tmp_path, review)
    rc_def, out_def = _cap(lambda: foundry.restaffing_review_cli(str(p)))
    rc_false, out_false = _cap(lambda: foundry.restaffing_review_cli(str(p), as_json=False))
    assert out_def == out_false, "default output != explicit as_json=False output"
    assert rc_def == rc_false
    # the human render carries the header, figures line, per-change +/- lines, verdict
    assert out_def.splitlines()[0].startswith("restaffing-review:")
    assert "k=3 cap=1 accepted=1 rejected=3" in out_def
    assert out_def.rstrip().splitlines()[-1] == "verdict: DIFF"


def test_b08_as_json_default_is_false():
    sig = inspect.signature(foundry.restaffing_review_cli)
    assert "as_json" in sig.parameters, "restaffing_review_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 9 -- default (human) stdout is NOT valid JSON
# ==========================================================================
def test_b09_default_output_not_json(tmp_path):
    p = _write(tmp_path, {"changes": [_ch("activate", "a")], "logged_triggers": ["t"]})
    _, out = _cap(lambda: foundry.restaffing_review_cli(str(p)))
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# ==========================================================================
# Behavior 10 -- as_json=True prints EXACTLY json.dumps(to_dict(), indent=2)+nl,
#                no human-report line leaks in
# ==========================================================================
def test_b10_json_output_is_exact_diff_and_noop(tmp_path):
    # DIFF review (2 accepted) and NOOP review (all rejected). All 5 keys explicit
    # so the expected decide_restaffing(...) call is default-independent.
    diff_review = {"changes": [_ch("activate", "a", "t"), _ch("deactivate", "b", "t")],
                   "tenures": {"b": 5}, "logged_triggers": ["t"], "k": 3, "cap": 2}
    noop_review = {"changes": [_ch("activate", "a", "z")],
                   "tenures": {}, "logged_triggers": ["t"], "k": 3, "cap": 2}
    for review in (diff_review, noop_review):
        p = _write(tmp_path, review, name="r.json")
        rc, out = _cap(lambda: foundry.restaffing_review_cli(str(p), as_json=True))
        expected_obj = _decide(review["changes"], tenures=review["tenures"],
                               logged_triggers=review["logged_triggers"],
                               k=review["k"], cap=review["cap"])
        expected = json.dumps(expected_obj.to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(), indent=2)+newline"
        assert json.loads(out) == expected_obj.to_dict()


def test_b10_no_human_lines_leak_into_json(tmp_path):
    review = {"changes": [_ch("activate", "a", "t"), _ch("activate", "b", "t"),
                          _ch("activate", "c", "z"), _ch("deactivate", "d", "t")],
              "tenures": {"d": 0}, "logged_triggers": ["t"], "k": 3, "cap": 1}
    p = _write(tmp_path, review)
    _, out = _cap(lambda: foundry.restaffing_review_cli(str(p), as_json=True))
    # human report lines strip to bare labels: "restaffing-review:", "k="/"cap="
    # figure line, "+ "/"- " change lines, "verdict:". A JSON line strips to a
    # leading double-quote or a bracket/brace -- a true discriminator.
    for ln in out.splitlines():
        s = ln.strip()
        assert not s.startswith("restaffing-review:"), "human header leaked: %r" % ln
        assert not s.startswith("k="), "figure line leaked: %r" % ln
        assert not s.startswith("cap="), "figure line leaked: %r" % ln
        assert not s.startswith("+ "), "accepted change line leaked: %r" % ln
        assert not s.startswith("- "), "rejected change line leaked: %r" % ln
        assert not s.startswith("verdict:"), "verdict line leaked: %r" % ln


# ==========================================================================
# Behavior 11 -- exit code identical both modes == 1 if has_diff else 0
# ==========================================================================
def test_b11_exit_code_identical_and_correct(tmp_path):
    fixtures = [
        ({"changes": [_ch("activate", "a")], "logged_triggers": ["t"]}, 1),   # DIFF
        ({"changes": [_ch("activate", "a", "z")], "logged_triggers": ["t"]}, 0),  # all-rej NOOP
        ({"changes": []}, 0),  # empty NOOP
    ]
    for review, code in fixtures:
        p = _write(tmp_path, review, name="r.json")
        rc_h, _ = _cap(lambda: foundry.restaffing_review_cli(str(p), as_json=False))
        rc_j, _ = _cap(lambda: foundry.restaffing_review_cli(str(p), as_json=True))
        assert rc_h == rc_j == code, (
            "exit diverged for %r: human=%r json=%r expected=%r" % (review, rc_h, rc_j, code)
        )


# ==========================================================================
# Behavior 12 -- the THREE error branches, byte-identical both modes, exit 2,
#                no JSON emitted
# ==========================================================================
def test_b12_error_branches_byte_identical_exit2_no_json(tmp_path):
    # missing file
    missing = str(tmp_path / "does_not_exist.json")
    # invalid JSON
    bad = tmp_path / "bad.json"
    bad.write_text("not json {", encoding="utf-8")
    # top-level non-object (a JSON list)
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2, 3]", encoding="utf-8")

    for path in (missing, str(bad), str(lst)):
        rc_h, out_h = _cap(lambda: foundry.restaffing_review_cli(path, as_json=False))
        rc_j, out_j = _cap(lambda: foundry.restaffing_review_cli(path, as_json=True))
        assert rc_h == rc_j == 2, "error branch did not return 2 in both modes: %r" % path
        assert out_h == out_j, "error message differs between modes: %r" % path
        assert out_h.strip() != "", "error branch named no problem: %r" % path
        assert "verdict:" not in out_h
        # no JSON payload emitted -- there is no RestaffingDiff to serialize
        with pytest.raises(json.JSONDecodeError):
            json.loads(out_h)


def test_b12_error_messages_name_the_problem(tmp_path):
    missing = str(tmp_path / "gone.json")
    _, out = _cap(lambda: foundry.restaffing_review_cli(missing, as_json=True))
    assert "file not found" in out
    bad = tmp_path / "bad2.json"
    bad.write_text("{", encoding="utf-8")
    _, out = _cap(lambda: foundry.restaffing_review_cli(str(bad), as_json=True))
    assert "invalid JSON" in out
    num = tmp_path / "num.json"
    num.write_text("42", encoding="utf-8")
    _, out = _cap(lambda: foundry.restaffing_review_cli(str(num), as_json=True))
    assert "not a JSON object" in out


# ==========================================================================
# Behavior 13 -- CLI writes NOTHING to disk in EITHER mode
# ==========================================================================
def test_b13_writes_nothing_either_mode(tmp_path):
    cwd = tmp_path / "cwd"
    reviews = tmp_path / "reviews"
    cwd.mkdir()
    reviews.mkdir()
    rp = reviews / "r.json"
    rp.write_text(json.dumps({"changes": [_ch("activate", "a")], "logged_triggers": ["t"]}),
                  encoding="utf-8")
    prev = os.getcwd()
    os.chdir(cwd)
    try:
        before = sorted(x.name for x in cwd.iterdir())
        for as_json in (False, True):
            _cap(lambda: foundry.restaffing_review_cli(str(rp), as_json=as_json))
        after = sorted(x.name for x in cwd.iterdir())
    finally:
        os.chdir(prev)
    assert before == after == [], "CLI wrote to the working dir: %r -> %r" % (before, after)


# ==========================================================================
# Behavior 14 -- argparse routing via foundry.main
# ==========================================================================
def test_b14_main_routes_as_json(monkeypatch, tmp_path):
    captured = {}

    def fake(path, as_json=False):
        captured.update(path=path, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "restaffing_review_cli", fake)
    p = _write(tmp_path, {"changes": []})
    foundry.main(["restaffing-review", "--file", str(p), "--json"])
    assert captured == {"path": str(p), "as_json": True}
    captured.clear()
    foundry.main(["restaffing-review", "--file", str(p)])
    assert captured == {"path": str(p), "as_json": False}


def test_b14_main_end_to_end_json(tmp_path):
    # DIFF end-to-end (no spy): exit 1 + JSON stdout
    pd = _write(tmp_path, {"changes": [_ch("activate", "a")], "logged_triggers": ["t"]},
                name="diff.json")
    rc, out = _cap(lambda: foundry.main(["restaffing-review", "--file", str(pd), "--json"]))
    assert rc == 1
    d = json.loads(out)
    assert d["verdict"] == "DIFF" and d["has_diff"] is True
    # NOOP end-to-end: exit 0 + JSON stdout
    pn = _write(tmp_path, {"changes": [_ch("activate", "a", "z")], "logged_triggers": ["t"]},
                name="noop.json")
    rc, out = _cap(lambda: foundry.main(["restaffing-review", "--file", str(pn), "--json"]))
    assert rc == 0
    d = json.loads(out)
    assert d["verdict"] == "NOOP" and d["has_diff"] is False


def test_b14_json_store_true_and_file_required(tmp_path):
    p = _write(tmp_path, {"changes": []})
    # store_true: a value after --json is rejected by argparse
    with pytest.raises(SystemExit):
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["restaffing-review", "--file", str(p), "--json", "x"])
    # --file omitted -> argparse exits non-zero
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["restaffing-review", "--json"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 15 -- DORMANCY unchanged: no orchestrator / dispatcher reference
# ==========================================================================
def test_b15_orchestrators_do_not_reference_restaffing_symbols():
    new = set(RST_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references restaffing symbol(s): %r" % (fn.__name__, refs)


def test_b15_dispatcher_has_zero_restaffing_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in RST_SYMBOLS:
        assert dtext.count(sym) == 0, "dispatcher.py references restaffing symbol %r" % sym
    assert dtext.count("restaffing-review") == 0, "dispatcher.py names the restaffing-review command"


def test_b15_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.decide_restaffing)
    assert callable(foundry.restaffing_review_cli)
    for cls in ("RestaffingChange", "RestaffingRejection", "RestaffingDiff"):
        c = getattr(foundry, cls)
        assert dataclasses.is_dataclass(c)
        assert callable(c.to_dict), "%s.to_dict missing" % cls
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    # reused prior-cadence cores remain present (no regression)
    assert callable(foundry.decide_cadence_review)
    assert callable(foundry.classify_escalation)
    assert dispatcher is not None


def test_ac_help_lists_restaffing_review(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "restaffing-review" in out
    for sub in ("cadence-review", "escalation-check"):
        assert sub in out, "prior subcommand %r missing (regression)" % sub


def test_ac_new_symbols_ascii():
    """The new/changed code is pure ASCII. Scoped to the new/changed symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 divider-em-dash trap)."""
    srcs = [
        inspect.getsource(foundry.RestaffingChange.to_dict),
        inspect.getsource(foundry.RestaffingRejection.to_dict),
        inspect.getsource(foundry.RestaffingDiff.to_dict),
        inspect.getsource(foundry.restaffing_review_cli),
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
    # matcher is ARMED (not inert): a runtime-built home path IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
