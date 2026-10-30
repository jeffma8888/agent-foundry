"""Black-box behaviour tests for iter 493 -- a `resume` event kind so the
iter-488 `auth resume k/M` log line is stamped `kind: "resume"` instead of
`info` in events.jsonl, and becomes visible to `events --kind resume`.

ISOLATION CONTRACT (honored): written solely from the iter-493 PM spec's
Expected Behaviors (1-8), the README/roadmap, the conventions under `tests/`
and the product's OBSERVABLE runtime interface (public functions, the
`events` CLI, the live EVENT_KIND_RULES value). The engineer's/reviewer's
notes and `git diff` were not read. Behavior 5 and 8 inspect run_stage's
source AT TEST TIME because the spec asks for exactly that drift guard.

Fully offline: every config / events file lands under a per-test tmp_path;
the only subprocess is the `import foundry, dispatcher` probe.
"""
import ast
import builtins
import inspect
import io
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import foundry  # noqa: E402

NEEDLE = "auth " + "resume"
REAL_RESUME_LINE = "iter 07 · engineer " + NEEDLE + " 1/24: re-running stage after hold"

# The table exactly as it stood before iter 493 (10 rows), as a golden.
PRE_EXISTING_RULES = (
    ("ship", ("shipped",)),
    ("revert", ("reverted",)),
    ("postrelease", ("postrelease", "post-release")),
    ("timing", ("suite wall-time",)),
    ("backoff", ("backing off", "cooling down")),
    ("stop", ("stop requested", "stop honored")),
    ("lifecycle", ("foundry started", "foundry stopped")),
    ("fix", ("fix pass",)),
    ("iteration", ("iteration",)),
    ("stage", ("attempt", "produced", "no output file")),
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path):
    data = {
        "name": "demoprod",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg_path(tmp_path):
    return _write_cfg(tmp_path)


@pytest.fixture
def cfg(cfg_path):
    return foundry.load_config(str(cfg_path))


def _capture(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn(*a, **k)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _events_json(cfg, kind):
    rc, out, _ = _capture(foundry.events_cli, cfg, kind=kind, as_json=True)
    return rc, json.loads(out)


def _read_events(cfg):
    path = pathlib.Path(cfg.events_log)
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


class _Sample:
    """Permissive stand-in for any f-string placeholder we cannot name."""

    def __init__(self, text="1"):
        self._text = text

    def __format__(self, spec):
        return self._text

    __str__ = __repr__ = lambda self: self._text

    def __getattr__(self, name):
        return self

    def __getitem__(self, key):
        return self

    def __call__(self, *a, **k):
        return self

    def _arith(self, other):
        return self

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _arith


class _SampleNS(dict):
    def __missing__(self, name):
        low = name.lower()
        if "iter" in low:
            return 7
        if "stage" in low or low in ("name", "role"):
            return "engineer"
        if "max" in low or "budget" in low or "limit" in low:
            return 24
        if hasattr(builtins, name):
            return getattr(builtins, name)
        return _Sample("1")


def _resume_fstrings():
    """Every f-string literal in run_stage whose constant text holds the needle."""
    src = textwrap.dedent(inspect.getsource(foundry.run_stage))
    tree = ast.parse(src)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            const = "".join(
                v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            if NEEDLE in const.lower():
                hits.append(node)
    return hits


def _render(node):
    code = compile(ast.Expression(body=node), "<run_stage-fstring>", "eval")
    return eval(code, {"__builtins__": builtins}, _SampleNS())


# --------------------------------------------------------------------------
# Behavior 1
# --------------------------------------------------------------------------
def test_behavior1_auth_resume_line_is_stamped_resume():
    assert foundry.classify_event(REAL_RESUME_LINE) == "resume"


# --------------------------------------------------------------------------
# Behavior 2
# --------------------------------------------------------------------------
@pytest.mark.parametrize("msg", ["AUTH RESUME 2/3", "Auth Resume 1/1", "x auth resume y"])
def test_behavior2_matching_is_case_insensitive(msg):
    assert foundry.classify_event(msg) == "resume"


# --------------------------------------------------------------------------
# Behavior 3
# --------------------------------------------------------------------------
def test_behavior3_exactly_one_resume_row_with_the_spec_needle():
    rows = [tuple(r) for r in foundry.EVENT_KIND_RULES]
    resume_rows = [r for r in rows if r[0] == "resume"]
    assert len(resume_rows) == 1, resume_rows
    assert tuple(resume_rows[0][1]) == (NEEDLE,)


def test_behavior3_pre_existing_rows_unchanged_in_order_and_table_is_11():
    rows = [(r[0], tuple(r[1])) for r in foundry.EVENT_KIND_RULES]
    assert len(rows) == 11
    assert len(rows) == len(PRE_EXISTING_RULES) + 1
    without = [r for r in rows if r[0] != "resume"]
    assert without == list(PRE_EXISTING_RULES)


def test_behavior3_resume_row_precedes_generic_iteration_and_stage_rows():
    kinds = [r[0] for r in foundry.EVENT_KIND_RULES]
    assert kinds.index("resume") < kinds.index("iteration")
    assert kinds.index("resume") < kinds.index("stage")


# --------------------------------------------------------------------------
# Behavior 4
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "msg,kind",
    [
        ("iter 07 · engineer backing off 30 min (failure kind: auth)", "backoff"),
        ("shipped iteration 7", "ship"),
        ("", "info"),
        ("auth hold: re-authenticate to resume", "info"),
    ],
)
def test_behavior4_neighbouring_lines_keep_their_kinds(msg, kind):
    assert foundry.classify_event(msg) == kind


def test_behavior4_every_old_needle_still_wins_its_own_kind():
    for kind, needles in PRE_EXISTING_RULES:
        for n in needles:
            assert foundry.classify_event("zz " + n + " zz") == kind, (kind, n)


# --------------------------------------------------------------------------
# Behavior 5 -- drift guard on the real run_stage f-string
# --------------------------------------------------------------------------
def test_behavior5_run_stage_logs_an_auth_resume_fstring():
    assert _resume_fstrings(), "run_stage no longer logs an 'auth resume' f-string"


def test_behavior5_real_fstring_rendered_with_samples_classifies_resume():
    nodes = _resume_fstrings()
    assert nodes
    for node in nodes:
        line = _render(node)
        assert isinstance(line, str) and line
        assert NEEDLE in line.lower(), line
        assert foundry.classify_event(line) == "resume", line
        # the same line as log() would see it with the iteration prefix
        assert foundry.classify_event("iter 07 · " + line) == "resume", line


def test_behavior5_guard_can_fail_on_a_reworded_line():
    # Rewording the logged line (dropping the needle) must flip the kind.
    reworded = REAL_RESUME_LINE.replace(NEEDLE, "auth re-run")
    assert foundry.classify_event(reworded) != "resume"


# --------------------------------------------------------------------------
# Behavior 6 -- end to end through log() and the events reader
# --------------------------------------------------------------------------
E2E_MSG = "iter 07 · pm " + NEEDLE + " 1/2: re-running stage after hold"


def test_behavior6_log_stamps_resume_and_events_kind_filter_sees_it(cfg):
    _capture(foundry.log, cfg, E2E_MSG)
    recs = _read_events(cfg)
    mine = [r for r in recs if r.get("msg") == E2E_MSG]
    assert len(mine) == 1, recs
    assert mine[0]["kind"] == "resume"

    rc, doc = _events_json(cfg, "resume")
    assert rc == 0
    assert [e["msg"] for e in doc["events"]] == [E2E_MSG]
    assert doc["kind_counts"].get("resume") == 1

    rc_info, doc_info = _events_json(cfg, "info")
    assert all(e["msg"] != E2E_MSG for e in doc_info["events"])
    assert doc_info["matched"] == 0

    summ = foundry.gather_events(cfg, kind="resume")
    assert summ.to_dict()["matched"] == 1


def test_behavior6_events_cli_subprocess_kind_resume(cfg, cfg_path):
    _capture(foundry.log, cfg, E2E_MSG)
    r = subprocess.run(
        [sys.executable, str(REPO / "foundry.py"), "events", "--config", str(cfg_path),
         "--kind", "resume", "--json"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert [e["kind"] for e in doc["events"]] == ["resume"]
    r2 = subprocess.run(
        [sys.executable, str(REPO / "foundry.py"), "events", "--config", str(cfg_path),
         "--kind", "info", "--json"],
        capture_output=True, text=True, timeout=60,
    )
    assert json.loads(r2.stdout)["matched"] == 0


# --------------------------------------------------------------------------
# Behavior 7 -- stored kinds are not rewritten
# --------------------------------------------------------------------------
def test_behavior7_historical_info_record_still_reads_back_info(cfg):
    path = pathlib.Path(cfg.events_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {"product": "demoprod", "msg": E2E_MSG, "kind": "info", "event": "log",
           "ts": "2026-01-01T00:00:00+00:00"}
    path.write_text(json.dumps(old) + "\n")
    rc, doc = _events_json(cfg, "info")
    assert rc == 0
    assert [e["msg"] for e in doc["events"]] == [E2E_MSG]
    assert doc["events"][0]["kind"] == "info"
    _, doc_r = _events_json(cfg, "resume")
    assert doc_r["matched"] == 0
    # the stored file is untouched by reading
    assert json.loads(path.read_text().splitlines()[0]) == old


# --------------------------------------------------------------------------
# Behavior 8 -- importable, run_stage untouched by the classifier
# --------------------------------------------------------------------------
def test_behavior8_foundry_and_dispatcher_import_cleanly():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(REPO), capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("token", ["classify_event", "EVENT_KIND_RULES", "kind="])
def test_behavior8_run_stage_source_has_no_classifier_reference(token):
    assert token not in inspect.getsource(foundry.run_stage)
