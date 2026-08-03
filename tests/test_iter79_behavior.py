"""Black-box behaviour tests for iter 79 -- item 22, bite 2 of ~3: the DORMANT
pure hysteresis-constrained re-staffing DIFF core
`decide_restaffing(changes, tenures=None, logged_triggers=None, *, k=None,
cap=None) -> RestaffingDiff` (frozen `RestaffingChange` / `RestaffingRejection`
/ `RestaffingDiff`), driven by patchable module constants
`RESTAFFING_MIN_TENURE_K = 3` and `RESTAFFING_MAX_CHANGES = 2` read at CALL
time, plus an on-demand read-only `foundry restaffing-review --file <path>`
CLI. It adopts ORG_DESIGN section-10's bounded re-staffing: team-composition
changes are PROPOSALS, not drift, partitioned by three hysteresis rules
(trigger citation, minimum tenure before deactivation, change cap). ZERO call
site: nothing in the pipeline invokes it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-17) and the product's own OBSERVABLE behaviour only (running it).
The implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.decide_restaffing`, the
patchable thresholds via the module attributes `foundry.RESTAFFING_MIN_TENURE_K`
/ `foundry.RESTAFFING_MAX_CHANGES`, and the CLI via
`foundry.main(["restaffing-review", ...])`. The dormancy / off-control-path
checks use only public RUNTIME introspection -- module attributes, compiled
function name tables (`__code__.co_names` recursed via `_co_names_deep`),
`--help` output, and a git `--quiet` exit-code probe -- plus, for the mechanical
ASCII / leak-clean acceptance criteria, `inspect.getsource` scoped to the NEW
symbols only (the established suite convention; never a whole-file scan / never
`git diff`). Fully offline and deterministic: NO subprocess/git/network/agent-run
except the fresh-import + `--help` regression probes and the control-path
byte-unchanged git `--quiet` probe. The dormancy proof is scoped to the SYMBOLS
and the `restaffing-review` command string in dispatcher.py ONLY -- never a bare
`rg restaffing-review foundry.py`, which now self-matches the new CLI code.
"""
import dataclasses
import importlib.util
import inspect
import io
import json
import contextlib
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# Fixed field orders of the three frozen result dataclasses.
CHANGE_ORDER = ("action", "role", "trigger")
REJECTION_ORDER = ("change", "rule")
DIFF_ORDER = ("accepted", "rejected", "k", "cap")

# The symbols this iteration ADDS. They must be dormant: no orchestrator and
# dispatcher.py reference any of them by name.
NEW_SYMBOLS = (
    "decide_restaffing",
    "RestaffingChange",
    "RestaffingRejection",
    "RestaffingDiff",
    "RESTAFFING_MIN_TENURE_K",
    "RESTAFFING_MAX_CHANGES",
    "restaffing_review_cli",
)

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects.
    Pure runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter79_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cli(args):
    """Drive the CLI via foundry.main, capturing stdout + exit code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.main(list(args))
    return rc, buf.getvalue()


def _cli_file(tmp_path, review, name="review.json"):
    """Write a JSON review object to a tmp file and drive the CLI on it."""
    p = tmp_path / name
    p.write_text(json.dumps(review), encoding="utf-8")
    return _cli(["restaffing-review", "--file", str(p)])


def _ch(action, role, trigger="t"):
    return {"action": action, "role": role, "trigger": trigger}


# ==========================================================================
# Behavior 1 -- pure, total, never-raises, offline, deterministic, value-equal;
# empty changes -> empty accepted/rejected tuples, verdict NOOP
# ==========================================================================
def test_b01_empty_changes_is_noop_with_empty_tuples():
    d = foundry.decide_restaffing([])
    assert d.accepted == ()
    assert d.rejected == ()
    assert d.verdict == "NOOP"
    assert isinstance(d.accepted, tuple) and isinstance(d.rejected, tuple)


def test_b01_total_never_raises_and_typed():
    cases = [
        ([], None, None),
        ([_ch("activate", "a")], None, None),
        ([_ch("activate", "a")], {}, []),
        ([_ch("deactivate", "z", "")], {"z": 0}, ["t"]),
        ([_ch("weird", "w")], {"w": 100}, ["t"]),
        ([_ch("activate", "a"), _ch("activate", "b"), _ch("activate", "c")], None, ["t"]),
    ]
    for changes, tenures, logged in cases:
        r = foundry.decide_restaffing(changes, tenures=tenures, logged_triggers=logged)
        assert type(r).__name__ == "RestaffingDiff", (
            f"decide_restaffing did not return RestaffingDiff for {changes!r}"
        )


def test_b01_deterministic_value_and_repr_equal():
    changes = [_ch("activate", "a"), _ch("deactivate", "b")]
    a = foundry.decide_restaffing(changes, tenures={"b": 9}, logged_triggers=["t"])
    b = foundry.decide_restaffing(changes, tenures={"b": 9}, logged_triggers=["t"])
    assert a == b, f"not value-equal: {a!r} vs {b!r}"
    assert repr(a) == repr(b), "repr not equal for equal inputs"


def test_b01_different_args_not_equal():
    base = [_ch("activate", "a")]
    assert (foundry.decide_restaffing(base, logged_triggers=["t"])
            != foundry.decide_restaffing(base, logged_triggers=[]))


def test_b01_no_filesystem_access(monkeypatch):
    """Pure: the core opens no file. Sabotage builtins.open; it still works."""
    def _boom(*a, **k):
        raise AssertionError("decide_restaffing performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    d = foundry.decide_restaffing([_ch("activate", "a")], logged_triggers=["t"])
    assert d.verdict == "DIFF"
    assert d.accepted_count == 1


# ==========================================================================
# Behavior 2 -- frozen RestaffingChange / RestaffingRejection / RestaffingDiff
# ==========================================================================
def test_b02_frozen_change():
    assert dataclasses.is_dataclass(foundry.RestaffingChange)
    c = foundry.RestaffingChange(action="activate", role="r", trigger="t")
    for field, value in (("action", "x"), ("role", "y"), ("trigger", "z")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(c, field, value)


def test_b02_frozen_rejection():
    assert dataclasses.is_dataclass(foundry.RestaffingRejection)
    d = foundry.decide_restaffing([_ch("activate", "r", "")], logged_triggers=["t"])
    rej = d.rejected[0]
    for field, value in (("change", None), ("rule", "x")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(rej, field, value)


def test_b02_frozen_diff():
    assert dataclasses.is_dataclass(foundry.RestaffingDiff)
    d = foundry.decide_restaffing([])
    for field, value in (("accepted", ()), ("rejected", ()), ("k", 1), ("cap", 1)):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(d, field, value)


def test_b02_field_names_and_order():
    assert tuple(f.name for f in dataclasses.fields(foundry.RestaffingChange)) == CHANGE_ORDER
    assert tuple(f.name for f in dataclasses.fields(foundry.RestaffingRejection)) == REJECTION_ORDER
    assert tuple(f.name for f in dataclasses.fields(foundry.RestaffingDiff)) == DIFF_ORDER


# ==========================================================================
# Behavior 3 -- change normalization (action lower+strip, role/trigger strip,
# missing key -> ""), pre-built RestaffingChange idempotent
# ==========================================================================
def test_b03_normalization_strips_and_lowercases():
    d = foundry.decide_restaffing(
        [{"action": "  DeAcTiVaTe ", "role": "  worker ", "trigger": "  T1 "}],
        tenures={"worker": 9}, logged_triggers=["T1"],
    )
    c = d.accepted[0]
    assert c.action == "deactivate", f"action not lower+stripped: {c.action!r}"
    assert c.role == "worker", f"role not stripped: {c.role!r}"
    assert c.trigger == "T1", f"trigger not stripped: {c.trigger!r}"


def test_b03_missing_keys_become_empty_string():
    d = foundry.decide_restaffing([{"action": "activate"}], logged_triggers=[""])
    # normalized change is observable via the rejection (empty trigger rejects)
    c = d.rejected[0].change
    assert c.action == "activate"
    assert c.role == ""
    assert c.trigger == ""


def test_b03_prebuilt_change_idempotent():
    pre = foundry.RestaffingChange(action="activate", role="r", trigger="t")
    d = foundry.decide_restaffing([pre], logged_triggers=["t"])
    assert d.accepted == (pre,), f"pre-built change not idempotent: {d.accepted!r}"


# ==========================================================================
# Behavior 4 -- rule "trigger" (citation)
# ==========================================================================
def test_b04_empty_trigger_rejected():
    d = foundry.decide_restaffing([_ch("activate", "r", "")], logged_triggers=["t"])
    assert d.rejected[0].rule == "trigger"
    assert d.verdict == "NOOP"


def test_b04_unlogged_trigger_rejected():
    d = foundry.decide_restaffing([_ch("activate", "r", "z")], logged_triggers=["t"])
    assert d.rejected[0].rule == "trigger"


def test_b04_logged_trigger_passes():
    d = foundry.decide_restaffing([_ch("activate", "r", "t")], logged_triggers=["t"])
    assert d.accepted and d.rejected == ()
    assert d.verdict == "DIFF"


def test_b04_none_logged_triggers_fails_every_citation():
    d = foundry.decide_restaffing([_ch("activate", "r", "t")], logged_triggers=None)
    assert d.rejected[0].rule == "trigger"
    assert d.accepted == ()


# ==========================================================================
# Behavior 5 -- rule "tenure" (min tenure before deactivation); activate never gated
# ==========================================================================
def test_b05_deactivate_below_k_rejected():
    d = foundry.decide_restaffing([_ch("deactivate", "r")], tenures={"r": 2},
                                  logged_triggers=["t"])  # k default 3
    assert d.rejected[0].rule == "tenure"
    assert d.verdict == "NOOP"


def test_b05_deactivate_at_or_above_k_passes():
    for tenure in (3, 4, 99):
        d = foundry.decide_restaffing([_ch("deactivate", "r")], tenures={"r": tenure},
                                      logged_triggers=["t"])
        assert d.accepted, f"deactivate at tenure {tenure} (>=3) not accepted"
        assert d.verdict == "DIFF"


def test_b05_activate_never_tenure_gated():
    for tenure in (0, 1, 2):
        d = foundry.decide_restaffing([_ch("activate", "r")], tenures={"r": tenure},
                                      logged_triggers=["t"])
        assert d.accepted, f"activate at tenure {tenure} was tenure-gated"
        assert d.rejected == ()


def test_b05_k_zero_boundary_deactivate_passes():
    # k=0 -> tenure 0 >= 0 -> passes
    d = foundry.decide_restaffing([_ch("deactivate", "r")], tenures={"r": 0},
                                  logged_triggers=["t"], k=0)
    assert d.accepted and d.verdict == "DIFF"


# ==========================================================================
# Behavior 6 -- tenure default 0 for absent role / tenures=None
# ==========================================================================
def test_b06_absent_role_defaults_to_zero_tenure():
    d = foundry.decide_restaffing([_ch("deactivate", "ghost")], tenures={},
                                  logged_triggers=["t"])  # k=3 > 0
    assert d.rejected[0].rule == "tenure"


def test_b06_tenures_none_defaults_to_zero():
    d = foundry.decide_restaffing([_ch("deactivate", "ghost")], tenures=None,
                                  logged_triggers=["t"])
    assert d.rejected[0].rule == "tenure"


# ==========================================================================
# Behavior 7 -- rule "cap": only accepted changes consume slots, input order,
# overflow -> "cap"; invalid change does not burn a slot
# ==========================================================================
def test_b07_cap_accepts_first_in_input_order():
    changes = [_ch("activate", "a"), _ch("activate", "b"),
               _ch("activate", "c"), _ch("activate", "d")]
    d = foundry.decide_restaffing(changes, logged_triggers=["t"])  # cap default 2
    assert [c.role for c in d.accepted] == ["a", "b"], "cap did not accept first-2 in order"
    assert [(r.change.role, r.rule) for r in d.rejected] == [("c", "cap"), ("d", "cap")]


def test_b07_invalid_change_does_not_consume_slot():
    # a bad-trigger change ahead of two valid ones: both valid still accepted at cap=2
    changes = [{"action": "activate", "role": "bad", "trigger": "nope"},
               _ch("activate", "a"), _ch("activate", "b")]
    d = foundry.decide_restaffing(changes, logged_triggers=["t"], cap=2)
    assert [c.role for c in d.accepted] == ["a", "b"], "invalid change burned a cap slot"
    assert [(r.change.role, r.rule) for r in d.rejected] == [("bad", "trigger")]


def test_b07_cap_zero_accepts_nothing():
    changes = [_ch("activate", "a"), _ch("activate", "b")]
    d = foundry.decide_restaffing(changes, logged_triggers=["t"], cap=0)
    assert d.accepted == ()
    assert all(r.rule == "cap" for r in d.rejected)
    assert d.verdict == "NOOP"


# ==========================================================================
# Behavior 8 -- deterministic rejection order trigger -> tenure -> cap;
# first failing rule tags
# ==========================================================================
def test_b08_empty_trigger_deactivate_tagged_trigger_not_tenure():
    # empty trigger AND tenure below k: the FIRST rule (trigger) tags it
    d = foundry.decide_restaffing([_ch("deactivate", "r", "")], tenures={"r": 0},
                                  logged_triggers=["t"])
    assert d.rejected[0].rule == "trigger", (
        f"expected 'trigger' to tag first, got {d.rejected[0].rule!r}"
    )


def test_b08_valid_trigger_low_tenure_tagged_tenure():
    d = foundry.decide_restaffing([_ch("deactivate", "r", "t")], tenures={"r": 0},
                                  logged_triggers=["t"])
    assert d.rejected[0].rule == "tenure"


def test_b08_overflow_valid_change_tagged_cap():
    # three fully-valid activates, cap 2 -> third is "cap" (not trigger/tenure)
    changes = [_ch("activate", "a"), _ch("activate", "b"), _ch("activate", "c")]
    d = foundry.decide_restaffing(changes, logged_triggers=["t"], cap=2)
    assert d.rejected[0].change.role == "c"
    assert d.rejected[0].rule == "cap"


# ==========================================================================
# Behavior 9 -- k read at CALL time via RESTAFFING_MIN_TENURE_K; monkeypatch
# flips a subsequent decide; restore reverts
# ==========================================================================
def test_b09_k_call_time_read(monkeypatch):
    orig = foundry.RESTAFFING_MIN_TENURE_K
    # at default k=3, a tenure-5 deactivate passes
    d0 = foundry.decide_restaffing([_ch("deactivate", "r")], tenures={"r": 5},
                                   logged_triggers=["t"])
    assert d0.verdict == "DIFF" and d0.k == orig
    # raise the knob to 10 -> tenure 5 < 10 -> now rejected; diff.k tracks
    monkeypatch.setattr(foundry, "RESTAFFING_MIN_TENURE_K", 10)
    d1 = foundry.decide_restaffing([_ch("deactivate", "r")], tenures={"r": 5},
                                   logged_triggers=["t"])
    assert d1.k == 10, "diff.k did not read the patched RESTAFFING_MIN_TENURE_K"
    assert d1.rejected[0].rule == "tenure", "patched-higher k still accepted (import-time capture?)"


def test_b09_restore_reverts():
    # after the previous test's monkeypatch is undone, default behaviour returns
    assert foundry.RESTAFFING_MIN_TENURE_K == 3
    d = foundry.decide_restaffing([_ch("deactivate", "r")], tenures={"r": 5},
                                  logged_triggers=["t"])
    assert d.verdict == "DIFF" and d.k == 3


def test_b09_lowering_k_accepts_shorter_tenure(monkeypatch):
    monkeypatch.setattr(foundry, "RESTAFFING_MIN_TENURE_K", 1)
    d = foundry.decide_restaffing([_ch("deactivate", "r")], tenures={"r": 1},
                                  logged_triggers=["t"])
    assert d.accepted and d.k == 1


# ==========================================================================
# Behavior 10 -- cap read at CALL time via RESTAFFING_MAX_CHANGES
# ==========================================================================
def test_b10_cap_call_time_read(monkeypatch):
    changes = [_ch("activate", "a"), _ch("activate", "b"), _ch("activate", "c")]
    d0 = foundry.decide_restaffing(changes, logged_triggers=["t"])  # cap default 2
    assert d0.accepted_count == 2 and d0.cap == foundry.RESTAFFING_MAX_CHANGES
    monkeypatch.setattr(foundry, "RESTAFFING_MAX_CHANGES", 1)
    d1 = foundry.decide_restaffing(changes, logged_triggers=["t"])
    assert d1.cap == 1, "diff.cap did not read the patched RESTAFFING_MAX_CHANGES"
    assert d1.accepted_count == 1, "patched cap not honored (import-time capture?)"


def test_b10_cap_restore_reverts():
    assert foundry.RESTAFFING_MAX_CHANGES == 2
    changes = [_ch("activate", "a"), _ch("activate", "b"), _ch("activate", "c")]
    d = foundry.decide_restaffing(changes, logged_triggers=["t"])
    assert d.accepted_count == 2 and d.cap == 2


# ==========================================================================
# Behavior 11 -- explicit k=/cap= override wins for that call only; diff.k/.cap
# report the effective thresholds
# ==========================================================================
def test_b11_explicit_overrides_win_over_patched_globals(monkeypatch):
    monkeypatch.setattr(foundry, "RESTAFFING_MIN_TENURE_K", 99)
    monkeypatch.setattr(foundry, "RESTAFFING_MAX_CHANGES", 99)
    changes = [_ch("deactivate", "r"), _ch("activate", "s")]
    d = foundry.decide_restaffing(changes, tenures={"r": 3}, logged_triggers=["t"],
                                  k=3, cap=1)
    assert d.k == 3, "explicit k= did not override module RESTAFFING_MIN_TENURE_K"
    assert d.cap == 1, "explicit cap= did not override module RESTAFFING_MAX_CHANGES"
    # tenure 3 >= k 3 -> deactivate accepted; cap 1 -> activate 's' overflow
    assert [c.role for c in d.accepted] == ["r"]
    assert [(x.change.role, x.rule) for x in d.rejected] == [("s", "cap")]


def test_b11_explicit_override_does_not_persist():
    # after an explicit-override call, the module defaults are unchanged
    assert foundry.RESTAFFING_MIN_TENURE_K == 3
    assert foundry.RESTAFFING_MAX_CHANGES == 2
    d = foundry.decide_restaffing([_ch("deactivate", "r")], tenures={"r": 3},
                                  logged_triggers=["t"])
    assert d.k == 3 and d.cap == 2


# ==========================================================================
# Behavior 12 -- derived-prop consistency
# ==========================================================================
def test_b12_derived_props_consistent():
    scenarios = [
        foundry.decide_restaffing([]),
        foundry.decide_restaffing([_ch("activate", "a")], logged_triggers=["t"]),
        foundry.decide_restaffing([_ch("activate", "a", "")], logged_triggers=["t"]),
        foundry.decide_restaffing(
            [_ch("activate", "a"), _ch("activate", "b"), _ch("activate", "c")],
            logged_triggers=["t"]),
    ]
    for d in scenarios:
        assert d.accepted_count == len(d.accepted)
        assert d.rejected_count == len(d.rejected)
        assert d.has_diff == bool(d.accepted)
        assert d.verdict == ("DIFF" if d.has_diff else "NOOP")


# ==========================================================================
# Behavior 13 -- CLI DIFF: exit 1, verdict line, figures, per-change lines
# ==========================================================================
def test_b13_cli_diff_exit1(tmp_path):
    review = {"changes": [_ch("activate", "a"), _ch("deactivate", "b")],
              "tenures": {"b": 5}, "logged_triggers": ["t"]}
    rc, out = _cli_file(tmp_path, review)
    assert rc == 1, f"DIFF returned {rc!r}, expected 1\n{out}"
    assert "verdict: DIFF" in out, f"verdict line missing/wrong:\n{out}"
    assert "accepted=2" in out, f"accepted figure missing:\n{out}"
    assert "rejected=0" in out, f"rejected figure missing:\n{out}"
    # the accepted roles appear on their own lines
    assert "a" in out and "b" in out


def test_b13_cli_reports_k_and_cap_figures(tmp_path):
    review = {"changes": [_ch("activate", "a")], "logged_triggers": ["t"]}
    rc, out = _cli_file(tmp_path, review)
    assert rc == 1
    assert "k=3" in out and "cap=2" in out, f"k/cap figures missing:\n{out}"


def test_b13_cli_prints_rejection_rule(tmp_path):
    # one accepted (DIFF) plus a cap-rejected change: the rule tag is observable
    review = {"changes": [_ch("activate", "a"), _ch("activate", "b")],
              "logged_triggers": ["t"], "cap": 1}
    rc, out = _cli_file(tmp_path, review)
    assert rc == 1
    assert "verdict: DIFF" in out
    assert "rule: cap" in out, f"rejection rule not reported:\n{out}"


# ==========================================================================
# Behavior 14 -- CLI NOOP: exit 0 (all rejected, empty, or absent changes)
# ==========================================================================
def test_b14_cli_all_rejected_is_noop(tmp_path):
    review = {"changes": [_ch("activate", "a", "nope")], "logged_triggers": ["t"]}
    rc, out = _cli_file(tmp_path, review)
    assert rc == 0, f"all-rejected returned {rc!r}, expected 0\n{out}"
    assert "verdict: NOOP" in out, f"verdict not NOOP:\n{out}"


def test_b14_cli_empty_changes_is_noop(tmp_path):
    rc, out = _cli_file(tmp_path, {"changes": []})
    assert rc == 0
    assert "verdict: NOOP" in out


def test_b14_cli_absent_changes_is_noop(tmp_path):
    rc, out = _cli_file(tmp_path, {})
    assert rc == 0, f"absent-changes returned {rc!r}, expected 0\n{out}"
    assert "verdict: NOOP" in out


# ==========================================================================
# Behavior 15 -- CLI file error: nonexistent path OR invalid JSON -> exit 2,
# no exception propagation, no DIFF/NOOP verdict, names the problem
# ==========================================================================
def test_b15_cli_nonexistent_file_exit2(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    rc, out = _cli(["restaffing-review", "--file", str(missing)])
    assert rc == 2, f"nonexistent file returned {rc!r}, expected 2\n{out}"
    assert "verdict: DIFF" not in out and "verdict: NOOP" not in out
    assert out.strip() != "", "did not name the problem"


def test_b15_cli_invalid_json_exit2(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json {", encoding="utf-8")
    rc, out = _cli(["restaffing-review", "--file", str(p)])
    assert rc == 2, f"invalid JSON returned {rc!r}, expected 2\n{out}"
    assert "verdict: DIFF" not in out and "verdict: NOOP" not in out
    assert out.strip() != "", "did not name the problem"


def test_b15_cli_top_level_non_object_exit2(tmp_path):
    # valid JSON but not a review object: must not propagate an exception
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    rc, out = _cli(["restaffing-review", "--file", str(p)])
    assert rc == 2, f"top-level non-object returned {rc!r}, expected 2\n{out}"
    assert "verdict: DIFF" not in out and "verdict: NOOP" not in out


# ==========================================================================
# Behavior 16 -- CLI input contract (defaults + k/cap overrides) + writes nothing
# ==========================================================================
def test_b16_cli_defaults_missing_optional_keys(tmp_path):
    # only changes present: tenures {} and logged_triggers [] default -> all fail citation
    review = {"changes": [_ch("activate", "a", "t")]}
    rc, out = _cli_file(tmp_path, review)
    assert rc == 0, f"missing logged_triggers should reject on citation -> NOOP\n{out}"
    assert "verdict: NOOP" in out


def test_b16_cli_k_cap_overrides_from_json(tmp_path):
    # cap override in the review object caps acceptance to 1
    review = {"changes": [_ch("activate", "a"), _ch("activate", "b")],
              "logged_triggers": ["t"], "cap": 1}
    rc, out = _cli_file(tmp_path, review)
    assert rc == 1
    assert "cap=1" in out, f"json cap override not applied:\n{out}"
    assert "accepted=1" in out


def test_b16_cli_k_override_from_json(tmp_path):
    # k override raises the tenure gate so a tenure-5 deactivate is rejected
    review = {"changes": [_ch("deactivate", "r")], "tenures": {"r": 5},
              "logged_triggers": ["t"], "k": 10}
    rc, out = _cli_file(tmp_path, review)
    assert rc == 0, f"json k override not applied (expected NOOP)\n{out}"
    assert "k=10" in out and "verdict: NOOP" in out


def test_b16_cli_writes_nothing(tmp_path):
    # empty working dir stays empty; review file lives in a separate reviews dir
    cwd = tmp_path / "cwd"
    reviews = tmp_path / "reviews"
    cwd.mkdir()
    reviews.mkdir()
    rp = reviews / "r.json"
    rp.write_text(json.dumps({"changes": [_ch("activate", "a")], "logged_triggers": ["t"]}),
                  encoding="utf-8")
    import os
    prev = os.getcwd()
    os.chdir(cwd)
    try:
        before = sorted(x.name for x in cwd.iterdir())
        for _ in range(3):
            _cli(["restaffing-review", "--file", str(rp)])
        after = sorted(x.name for x in cwd.iterdir())
    finally:
        os.chdir(prev)
    assert before == after == [], f"CLI wrote to the working dir: {before} -> {after}"


def test_b16_cli_dispatched_before_load_config(tmp_path):
    # no product --config is required; the CLI runs standalone (mirrors cadence-review)
    rc, out = _cli_file(tmp_path, {"changes": [_ch("activate", "a")], "logged_triggers": ["t"]})
    assert rc == 1, f"restaffing-review needed a --config (not dispatched before load_config)?\n{out}"


# ==========================================================================
# Behavior 15/help -- --help lists restaffing-review; prior subcommands intact
# ==========================================================================
def test_help_lists_restaffing_review_and_prior_subcommands(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "restaffing-review" in out, f"restaffing-review missing from --help:\n{out}"
    for sub in ("cadence-review", "escalation-check", "product-gate", "gate-verdict",
                "gate-precheck", "role-model", "gate-scope", "lint-spec"):
        assert sub in out, f"prior subcommand {sub!r} missing from --help (regression)"


def test_restaffing_review_subparser_help_ok(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["restaffing-review", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--file" in out, f"--file absent from subparser help:\n{out}"


# ==========================================================================
# Behavior 17 + acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_import_intact():
    assert callable(foundry.decide_restaffing)
    assert callable(foundry.restaffing_review_cli)
    for cls in ("RestaffingChange", "RestaffingRejection", "RestaffingDiff"):
        assert dataclasses.is_dataclass(getattr(foundry, cls))
    for const, default in (("RESTAFFING_MIN_TENURE_K", 3), ("RESTAFFING_MAX_CHANGES", 2)):
        v = getattr(foundry, const)
        assert isinstance(v, int) and not isinstance(v, bool)
        assert v == default, f"default {const} should be {default} (ORG_DESIGN section 10)"
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    # reused prior-bite cores remain present (no regression to the item-20/21/22 family)
    assert callable(foundry.decide_cadence_review)
    assert callable(foundry.classify_escalation)
    assert callable(foundry.product_gate_precheck)
    assert dispatcher is not None


def test_b17_dormant_zero_call_site():
    """No orchestrator and no dispatcher-module reference references any new
    symbol by name (compiled name tables -- no source text read), nor names the
    `restaffing-review` command string in dispatcher.py."""
    new = set(NEW_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"
    assert "restaffing-review" not in dtext, "dispatcher.py names the 'restaffing-review' command string"


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_new_symbols_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 trap)."""
    new_sources = [
        inspect.getsource(foundry.decide_restaffing),
        inspect.getsource(foundry.RestaffingChange),
        inspect.getsource(foundry.RestaffingRejection),
        inspect.getsource(foundry.RestaffingDiff),
        inspect.getsource(foundry.restaffing_review_cli),
    ]
    for src in new_sources:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_ac_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/", ".gitignore"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts / .gitignore NOT byte-unchanged from HEAD"
