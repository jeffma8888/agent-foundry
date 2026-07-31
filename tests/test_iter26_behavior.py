"""Black-box behaviour tests for iter 26 -- typed machine-readable events.

Roadmap item 10 (`events.jsonl`, iter 05) is completed here: every `log()`
event record is stamped with a stable semantic `kind`, derived by a pure
classifier `foundry.classify_event(msg) -> str`, so the JSONL stream is
filterable by event type instead of by re-parsing the free-form `msg` prose.

ISOLATION CONTRACT (honored): this file was written SOLELY from the iter-26 PM
spec's Expected Behaviors (1-18), the product README, the roadmap file, the
existing test conventions under `tests/`, and the product's own OBSERVABLE
runtime interface. The implementation SOURCE of `foundry.py`/`dispatcher.py`,
the engineer's and reviewer's notes for this iteration, and `git diff` were NOT
read. Every check drives the PUBLIC interface: the pure `foundry.classify_event`
(exercised over the foundry's own real `log()` fixture messages), the frozen
`foundry.emit_event(path, event, /, **fields)` append helper, and the
`foundry.log(cfg, msg)` integration with its documented monkeypatchable
`foundry.emit_event` seam. Behavior 18's off-control-path assertions use only
runtime introspection (`inspect.getsource` on live function/module objects and a
subprocess `import` probe) -- the spec explicitly specifies this mechanism; the
source text was not read by hand to shape any other test.

Fully offline & deterministic: no network, no real git/agent subprocess (except
the Behavior-18 `import foundry, dispatcher` probe, which touches nothing), no
sleeps. `emit_event`/`log` writes land only under a per-test `tmp_path`.
"""
import inspect
import json
import pathlib
import subprocess
import sys
from datetime import datetime

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers / fixtures (mirror the other test modules' conventions)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _nonempty_lines(path):
    return [ln for ln in path.read_text().splitlines() if ln.strip()]


# the four control-flow / pipeline fns the classifier must stay OFF of
CONTROL_FLOW_FNS = ("run_iteration", "run_continuous", "run_stage", "build_prompt")
# the sentinel contract that must stay intact (unchanged by this iteration)
SENTINELS = ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:")


# ==========================================================================
# classify_event(msg) -> str  -- the pure semantic classifier
# ==========================================================================

# Behavior 1 -- Ship
def test_b01_ship():
    assert foundry.classify_event(
        "iter 26 SHIPPED — origin/main now abc123") == "ship"


# Behavior 2 -- Revert (both forms); the "ship" substring must NOT trip ship
def test_b02_revert_both_forms():
    assert foundry.classify_event(
        "repo reverted to origin/main (external head moved)") == "revert"
    msg = "iter 26 completed WITHOUT ship (reverted; see final.md)"
    assert foundry.classify_event(msg) == "revert"
    # the ship token is "shipped", not "ship" -- guard against a loose match
    assert "ship" in msg.lower() and "shipped" not in msg.lower()


# Behavior 3 -- Post-release (both verdicts), never "ship"
def test_b03_postrelease_both_verdicts():
    assert foundry.classify_event(
        "iter 26 post-release POSTRELEASE: HEALTHY") == "postrelease"
    assert foundry.classify_event(
        "iter 26 post-release POSTRELEASE: BROKEN") == "postrelease"


# Behavior 4 -- Timing (both variants)
def test_b04_timing_both_variants():
    assert foundry.classify_event(
        "fresh-clone suite wall-time: 3.30s") == "timing"
    assert foundry.classify_event(
        "fresh-clone suite wall-time: 130.00s SLOW (>120.00s threshold; "
        "consider a speed story)") == "timing"


# Behavior 5 -- Backoff
def test_b05_backoff():
    assert foundry.classify_event(
        "iter 26 · pm backing off 10 min") == "backoff"
    assert foundry.classify_event(
        "infra streak 3 -> cooling down 20 min") == "backoff"


# Behavior 6 -- Stop
def test_b06_stop():
    # AC declares stop's triggers as ("stop requested", "stop honored"); both must
    # classify as "stop". Fixture 1 (unambiguous) exercises "stop requested":
    assert foundry.classify_event(
        "iter 26 · pm STOP requested; abandoning") == "stop"
    # Fixture 2 exercises the AC-declared "stop honored" trigger COLLISION-FREE.
    # ISOLATION / SPEC NOTE: the spec's LITERAL Behavior-6 second fixture is
    #   "STOP honored: session iters=5, shipped=3"
    # whose count token contains the substring "shipped" -- which, under the spec's
    # OWN first-match-wins rule (Behavior 12) + the AC rule order (ship = rule 0,
    # stop = rule 5), classifies as "ship", NOT "stop". That is a spec
    # self-contradiction (and violates the "fixtures are the foundry's own real
    # log() messages" invariant in the Expected-Behaviors preamble). Rather than
    # encode a broken fixture -- or import the implementation's real count token,
    # which the isolation contract forbids -- we exercise the AC's declared
    # "stop honored" trigger with NO ship-count token; this is provably "stop" from
    # the spec/AC alone. See tester2.md for the PM erratum + recommended fix.
    assert foundry.classify_event(
        "STOP honored: session iters=5") == "stop"
    # DOCUMENTED CONTRADICTION GUARD: the LITERAL spec fixture misclassifies under
    # the current (AC-mandated) rule order. Pinning the current behavior makes the
    # defect executable/visible instead of silently omitted; when the PM resolves it
    # (correct the pm.md fixture token, or reorder stop before ship), update this.
    assert foundry.classify_event(
        "STOP honored: session iters=5, shipped=3") == "ship"


# Behavior 7 -- Lifecycle
def test_b07_lifecycle():
    assert foundry.classify_event(
        "foundry started (continuous) for '_platform'; …") == "lifecycle"
    assert foundry.classify_event(
        "foundry stopped for '_platform'; report at …") == "lifecycle"


# Behavior 8 -- Fix
def test_b08_fix():
    assert foundry.classify_event(
        "iter 26 · review requires changes -> fix pass") == "fix"
    assert foundry.classify_event(
        "iter 26 · tests failed -> fix pass + retest") == "fix"


# Behavior 9 -- Iteration boundary
def test_b09_iteration_boundary():
    assert foundry.classify_event(
        "—— iteration 26 begins (origin/main 69ae4c7e7; power: Now drawing "
        "from 'AC Power') ——") == "iteration"


# Behavior 10 -- Stage (all three stage-lifecycle lines)
def test_b10_stage_all_three():
    assert foundry.classify_event("iter 26 · **pm** attempt 1 started") == "stage"
    assert foundry.classify_event("iter 26 · pm produced `pm.md`") == "stage"
    assert foundry.classify_event(
        "iter 26 · pm no output file (attempt 1)") == "stage"


# Behavior 11 -- Fallback -> "info" (unknown + empty)
def test_b11_fallback_info():
    assert foundry.classify_event("something totally unrecognized") == "info"
    assert foundry.classify_event("") == "info"
    # reinforce the acceptance-criterion default constant
    assert foundry.EVENT_KIND_DEFAULT == "info"


# Behavior 12 -- First-match-wins ordering (earlier rule in EVENT_KIND_RULES)
def test_b12_first_match_wins():
    # "shipped" + "reverted" both present; ship precedes revert
    assert foundry.classify_event("iter 26 SHIPPED but later reverted") == "ship"
    # "iteration" + "attempt" both present; iteration precedes stage
    assert foundry.classify_event(
        "iteration 26 · pm attempt 1 started") == "iteration"


# Behavior 13 -- Case-insensitive matching
def test_b13_case_insensitive():
    assert foundry.classify_event("ITER 26 SHIPPED") == "ship"
    assert foundry.classify_event("Repo Reverted To Origin") == "revert"


# Behavior 14 -- Call-time rule resolution (both globals read INSIDE the fn)
def test_b14_call_time_rule_resolution(monkeypatch):
    monkeypatch.setattr(foundry, "EVENT_KIND_RULES", (("custom", ("zzz",)),))
    monkeypatch.setattr(foundry, "EVENT_KIND_DEFAULT", "none")
    # the patched rule bites -> proves rules are read at call time
    assert foundry.classify_event("zzz here") == "custom"
    # "shipped" no longer has a rule -> patched default bites
    assert foundry.classify_event("iter 26 SHIPPED") == "none"


# ==========================================================================
# log(cfg, msg) integration -- the single existing emit_event site
# ==========================================================================

# Behavior 15 -- log() enriches the emitted event with kind (event="log" kept)
def test_b15_log_enriches_kind(cfg, monkeypatch):
    recorded = []

    def _rec(events_path, event, **fields):
        recorded.append((event, fields))

    monkeypatch.setattr(foundry, "emit_event", _rec)
    msg = "iter 26 SHIPPED — origin/main now abc123"
    foundry.log(cfg, msg)

    assert len(recorded) == 1, f"expected exactly 1 emit, got {len(recorded)}"
    event, fields = recorded[0]
    assert event == "log", f"positional event changed: {event!r} (must stay 'log')"
    assert fields["product"] == cfg.name
    assert fields["msg"] == msg
    assert fields["kind"] == foundry.classify_event(msg) == "ship"


# Behavior 16 -- durable NIGHT_LOG write unchanged + emit stays best-effort
def test_b16_night_log_unchanged_and_emit_swallowed(cfg, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("mirror emit exploded")

    monkeypatch.setattr(foundry, "emit_event", _boom)
    msg = "iter 26 SHIPPED — origin/main now abc123"
    # must NOT propagate even though the enriched emit raises
    foundry.log(cfg, msg)

    lines = _nonempty_lines(cfg.night_log)
    assert len(lines) == 1, f"expected exactly 1 human line, got {len(lines)}"
    last = lines[-1]
    # format: - `<ts>` [<name>] <msg>
    assert last.startswith("- `"), f"unexpected human line prefix: {last!r}"
    assert last.endswith("` [" + cfg.name + "] " + msg), (
        f"durable NIGHT_LOG line not written verbatim on emit failure: {last!r}")
    ts = last[len("- `"):last.index("` [")]
    assert ts.strip(), "backtick-wrapped timestamp is empty"


# ==========================================================================
# emit_event(path, event, /, **fields) -- reserved-key ordering + round-trip
# ==========================================================================

# Behavior 17 -- reserved event/ts win; kind/product/msg survive as fields
def test_b17_emit_event_reserved_keys_and_roundtrip(tmp_path):
    p = tmp_path / "e.jsonl"
    foundry.emit_event(
        p, "log", product="p", msg="m", kind="ship", ts="SHADOW", event="SHADOW")

    lines = _nonempty_lines(p)
    assert len(lines) == 1, f"expected exactly 1 line, got {len(lines)}"
    obj = json.loads(lines[0])
    assert isinstance(obj, dict)
    # reserved positional event wins over the caller's shadow kwarg
    assert obj["event"] == "log", f"event was shadowed to {obj['event']!r}"
    # reserved ts is the real tz-aware timestamp, never the caller's "SHADOW"
    assert obj["ts"] != "SHADOW", "caller-supplied ts wrongly shadowed the real one"
    dt = datetime.fromisoformat(obj["ts"])
    assert dt.tzinfo is not None, "ts must be tz-aware"
    # ordinary fields survive intact
    assert obj["kind"] == "ship"
    assert obj["product"] == "p"
    assert obj["msg"] == "m"


# ==========================================================================
# Behavior 18 -- off the control path / resume-safe / still importable
# ==========================================================================
def test_b18_off_control_path_and_resume_safe():
    banned = ("classify_event", "kind=", "EVENT_KIND_RULES")

    # 18a: the three tokens appear in NONE of the four control-flow / pipeline fns
    for name in CONTROL_FLOW_FNS:
        fn = getattr(foundry, name)
        src = inspect.getsource(fn)
        for tok in banned:
            assert tok not in src, (
                f"{tok!r} unexpectedly present in foundry.{name} "
                f"-- classifier leaked onto the control path")

    # 18b: the three tokens are absent from dispatcher.py entirely
    disp_src = inspect.getsource(dispatcher)
    for tok in banned:
        assert tok not in disp_src, (
            f"{tok!r} unexpectedly present in dispatcher.py "
            f"-- classifier leaked into the single-brain scheduler")

    # 18c: the sentinel contract is unchanged (all four still present in source)
    fsrc = inspect.getsource(foundry)
    for sentinel in SENTINELS:
        assert sentinel in fsrc, (
            f"sentinel {sentinel!r} missing from foundry.py "
            f"-- the parse contract was altered")

    # 18d: no run_continuous status branch reads a kind/event record. The
    # classifier machinery is already banned (18a); here we assert run_continuous
    # never *indexes* a kind field out of any record (dict-access / .get forms)
    # -- so the enrichment can never become a resume-affecting control input.
    rc_src = inspect.getsource(foundry.run_continuous)
    for read_pat in ('["kind"]', "['kind']", '.get("kind"', ".get('kind'"):
        assert read_pat not in rc_src, (
            f"run_continuous reads a kind field ({read_pat}) -- events must stay "
            f"a pure read-only diagnostic sink, never a control input")

    # 18e: both modules still import cleanly in a fresh interpreter
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        capture_output=True, text=True,
        cwd=str(pathlib.Path(foundry.__file__).resolve().parent))
    assert proc.returncode == 0, (
        "import foundry, dispatcher failed:\n" + proc.stdout + proc.stderr)
