"""Black-box behaviour tests for iter 96 -- `foundry lint-spec --json`: a
machine-readable JSON payload for the read-only, fully-DORMANT `lint-spec`
PM-spec linter CLI, added ON TOP of the pre-existing core (SpecLint / spec_lint
/ lint_spec_cli, shipped iter 10). The change is a clean ADD-A-METHOD +
ADD-A-FLAG: a new `SpecLint.to_dict()` + an `as_json: bool = False` kw on the
existing `lint_spec_cli` + a `--json` store_true subparser arg + a one-line
dispatch edit. It serves roadmap item 5 (the PM's own spec linter) for
CI / release-gate / operator gating on spec size + completeness.

This is a `--file` CLI whose exit is 0/1/2 (OK / REVIEW / file-not-found), the
SAME 0/1/2 shape as gate-precheck #31 / escalation-check #35, NOT the 0/1 flag
CLIs (role-model #33) nor product-gate #34's 0/1/2/3, and NOT prd #7's
missing-OR-invalid exit-2. Here exit 2 is file-not-found ONLY: `spec_lint`
never raises for any text (including the empty string), so there is no
invalid-content exit-2 case. The file-not-found branch prints the plain-text
`lint-spec: file not found: <path>` in BOTH modes (json.loads raises), never a
JSON object, never a FileNotFoundError. The str-list `missing_sections` is a
STORED field declared before the derived props, so it lands in the MIDDLE of the
9-key to_dict (the role-model `argv` / prd `pending` placement), and must be
coerced via `list(...)` so the JSON round-trip holds.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-15) and the product's own OBSERVABLE behaviour only (running it) plus
the pre-existing core test file under tests/ (test_iter10_behavior.py). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.spec_lint(...)` +
`SpecLint.to_dict`, the CLI via `foundry.lint_spec_cli(path, ...)` and
`foundry.main(["lint-spec", ...])` with tmp-path spec files (the real repo's
specs are NEVER used). The expected human render is reconstructed INDEPENDENTLY
from the spec's documented Behavior-8 format + the public `spec_lint`, then
compared byte-for-byte. The dormancy proof uses only public runtime
introspection -- compiled function name tables (`co_names` recursed via
`_co_names_deep`) + a `dispatcher.py` source symbol-count -- and the mechanical
ASCII acceptance check uses `inspect.getsource` SCOPED to the two new/changed
symbols only (the established suite convention; never a whole-file scan / never
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

# The 9 keys to_dict() must expose, IN THIS ORDER: the 5 stored fields in
# declaration order, THEN the 4 properties in declaration order. The str-list
# `missing_sections` is a STORED field declared before the derived props, so it
# lands in the MIDDLE (the role-model `argv` / prd `pending` placement), the
# four props last. NO exit_code key (the CLI derives the exit code).
KEY_ORDER = [
    "char_count", "num_behaviors", "missing_sections",
    "size_over_chars", "size_over_behaviors",
    "sections_ok", "size_ok", "ok", "verdict",
]
EXPECTED_KEYS = set(KEY_ORDER)

# The three PRE-EXISTING lint-spec symbols (the core shipped iter 10, so a
# whole-file grep would FALSE-POSITIVE). Dormancy is proven ONLY against these
# specific symbols + the command string -- NEVER the generic `to_dict` name.
LINT_SYMBOLS = ("lint_spec_cli", "spec_lint", "SpecLint")

# The 6 required section headings, in order (the default REQUIRED_SPEC_SECTIONS).
DEFAULT_SECTIONS = (
    "## Feature",
    "## Why",
    "## Expected Behaviors",
    "## Acceptance Criteria",
    "## Out of Scope",
    "## Size self-check",
)


# --------------------------------------------------------------------------
# helpers -- build synthetic spec strings + tmp files (never the real repo)
# --------------------------------------------------------------------------
def _behaviors_block(n):
    return "\n".join("%d. behaviour number %d" % (i, i) for i in range(1, n + 1))


def _full_spec(n_behaviors=3, pad_chars=0):
    """A structurally-complete spec: all 6 required sections, `n_behaviors`
    ordered items in Expected Behaviors, optional `pad_chars` filler to grow the
    char count."""
    pad = ("x" * pad_chars) if pad_chars else ""
    return (
        "## Feature\nA small additive feature.\n\n"
        "## Why\nBecause the guard is on-mission.\n\n"
        "## Expected Behaviors\n" + _behaviors_block(n_behaviors) + "\n\n"
        "## Acceptance Criteria\n- [ ] the thing is done\n\n"
        "## Out of Scope\n- wiring it into the pipeline\n\n"
        "## Size self-check\n- fits one context window " + pad + "\n"
    )


def _drop(text, *headings):
    """Remove whole section blocks so their headings go missing."""
    out = text
    blocks = {
        "## Why": "## Why\nBecause the guard is on-mission.\n\n",
        "## Out of Scope": "## Out of Scope\n- wiring it into the pipeline\n\n",
        "## Acceptance Criteria": "## Acceptance Criteria\n- [ ] the thing is done\n\n",
    }
    for h in headings:
        out = out.replace(blocks[h], "")
    return out


# Canonical spec strings (grounded in the observable behaviour of spec_lint).
OK_SPEC = _full_spec(3, pad_chars=40)                    # verdict OK, no missing
REVIEW_SPEC = _drop(_full_spec(), "## Out of Scope")     # 1 missing -> REVIEW
MULTI_REVIEW = _drop(_full_spec(), "## Why", "## Out of Scope")  # 2 missing
EMPTY_SPEC = ""                                          # all 6 missing -> REVIEW
# name -> spec text (for the value-object cases; empty is core-only, no file)
VALUE_CASES = {"ok": OK_SPEC, "review": REVIEW_SPEC,
               "multi": MULTI_REVIEW, "empty": EMPTY_SPEC}


def _write_spec(dir_path, text, name="spec.md"):
    p = pathlib.Path(dir_path) / name
    p.write_text(text)
    return str(p)


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


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
    spec = importlib.util.spec_from_file_location("leak_guard_iter96_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _expected_human(path):
    """Reconstruct the EXPECTED default human render for an EXISTING file from
    the spec's Behavior-8 documented format + the PUBLIC spec_lint -- independent
    of the CLI implementation. Reads the module thresholds at call time so it is
    correct under a monkeypatched SPEC_MAX_BEHAVIORS (the oversized case)."""
    sl = foundry.spec_lint(pathlib.Path(path).read_text())
    miss = ", ".join(sl.missing_sections) if sl.missing_sections else "(none)"
    lines = [
        "lint-spec: %s" % path,
        "  char_count: %d (warn > %d)" % (sl.char_count, foundry.SPEC_SIZE_WARN_CHARS),
        "  num_behaviors: %d (max %d)" % (sl.num_behaviors, foundry.SPEC_MAX_BEHAVIORS),
        "  missing sections: %s" % miss,
        "  size_over_chars: %s  size_over_behaviors: %s" % (
            sl.size_over_chars, sl.size_over_behaviors),
        "verdict: %s" % sl.verdict,
    ]
    return "\n".join(lines) + "\n"


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous (the canonical
# cases really do behave as the spec's names claim)
# ==========================================================================
def test_precondition_canonical_cases_behave_as_named():
    ok = foundry.spec_lint(OK_SPEC)
    assert ok.ok is True and ok.verdict == "OK" and ok.missing_sections == ()
    rev = foundry.spec_lint(REVIEW_SPEC)
    assert rev.ok is False and rev.verdict == "REVIEW"
    assert len(rev.missing_sections) >= 1
    assert type(rev.missing_sections) is tuple, (
        "raw missing_sections must be a tuple to arm the non-vacuity guard")
    multi = foundry.spec_lint(MULTI_REVIEW)
    assert multi.ok is False and len(multi.missing_sections) == 2
    empty = foundry.spec_lint(EMPTY_SPEC)
    assert empty.ok is False and empty.char_count == 0
    assert empty.verdict == "REVIEW"
    # default required-section set is the documented 6-tuple, in order
    assert foundry.REQUIRED_SPEC_SECTIONS == DEFAULT_SECTIONS


# ==========================================================================
# Behavior 1 -- to_dict() has EXACTLY 9 keys in the pinned order; no exit_code
# ==========================================================================
def test_b01_to_dict_exact_9_keys_in_order():
    for txt in VALUE_CASES.values():
        d = foundry.spec_lint(txt).to_dict()
        assert isinstance(d, dict)
        assert list(d.keys()) == KEY_ORDER, (
            "to_dict key order %r != %r" % (list(d.keys()), KEY_ORDER))
        assert set(d.keys()) == EXPECTED_KEYS
        assert len(d) == 9
        assert "exit_code" not in d


def test_b01_key_order_matches_field_then_property_declaration():
    """Independently derive the expected order from the public dataclass shape:
    stored fields in declaration order THEN properties in declaration order."""
    fields = [f.name for f in dataclasses.fields(foundry.SpecLint)]
    props = [n for n, v in vars(foundry.SpecLint).items() if isinstance(v, property)]
    assert fields + props == KEY_ORDER, (fields, props)


def test_b01_no_exit_code_attribute():
    assert not hasattr(foundry.SpecLint, "exit_code")


# ==========================================================================
# Behavior 2 -- scalar/bool keys equal their sources verbatim; props reused
# ==========================================================================
def test_b02_scalar_and_bool_keys_equal_sources():
    for txt in VALUE_CASES.values():
        sl = foundry.spec_lint(txt)
        d = sl.to_dict()
        assert d["char_count"] == sl.char_count and type(d["char_count"]) is int
        assert d["num_behaviors"] == sl.num_behaviors and type(d["num_behaviors"]) is int
        assert d["size_over_chars"] == sl.size_over_chars and type(d["size_over_chars"]) is bool
        assert d["size_over_behaviors"] == sl.size_over_behaviors and type(d["size_over_behaviors"]) is bool
        assert d["sections_ok"] == sl.sections_ok and type(d["sections_ok"]) is bool
        assert d["size_ok"] == sl.size_ok and type(d["size_ok"]) is bool
        assert d["ok"] == sl.ok and type(d["ok"]) is bool
        assert d["verdict"] == sl.verdict and type(d["verdict"]) is str


def test_b02_verdict_string_domain():
    assert foundry.spec_lint(OK_SPEC).to_dict()["verdict"] == "OK"
    for txt in (REVIEW_SPEC, MULTI_REVIEW, EMPTY_SPEC):
        assert foundry.spec_lint(txt).to_dict()["verdict"] == "REVIEW"


# ==========================================================================
# Behavior 3 -- missing_sections is a plain LIST == list(self.missing_sections)
# ==========================================================================
def test_b03_missing_sections_is_list_of_str():
    for txt in VALUE_CASES.values():
        sl = foundry.spec_lint(txt)
        d = sl.to_dict()
        assert type(d["missing_sections"]) is list, "missing_sections must be a list, not a tuple"
        assert d["missing_sections"] == list(sl.missing_sections)
        assert all(type(x) is str for x in d["missing_sections"])


def test_b03_ok_spec_empty_list():
    d = foundry.spec_lint(OK_SPEC).to_dict()
    assert d["missing_sections"] == []


def test_b03_multi_review_preserves_order():
    d = foundry.spec_lint(MULTI_REVIEW).to_dict()
    assert d["missing_sections"] == ["## Why", "## Out of Scope"]


# ==========================================================================
# Behavior 4 -- THE DISCRIMINATING ROUND-TRIP over 4 cases
# ==========================================================================
def test_b04_json_round_trip_all_cases(monkeypatch):
    # ok, review, multi, empty-string round-trip at default thresholds
    for name, txt in VALUE_CASES.items():
        d = foundry.spec_lint(txt).to_dict()
        s = json.dumps(d)  # must not raise
        assert json.loads(s) == d, (
            "to_dict did not round-trip through JSON for %r (tuple leaked?)" % name)
    # an OVERSIZED spec (over the behavior threshold) also round-trips
    monkeypatch.setattr(foundry, "SPEC_MAX_BEHAVIORS", 2)
    big = foundry.spec_lint(_full_spec(5, pad_chars=20)).to_dict()
    assert big["size_over_behaviors"] is True and big["ok"] is False
    assert json.loads(json.dumps(big)) == big


# ==========================================================================
# Behavior 5 -- non-vacuity: a bare-tuple missing_sections would FAIL round-trip
# ==========================================================================
def test_b05_round_trip_non_vacuous_bare_tuple_fails():
    """Prove the round-trip is a real discriminator: a variant whose
    `missing_sections` value is the RAW frozen tuple `self.missing_sections`
    breaks `==` (json reads a tuple back as a list). Armed on a REVIEW spec
    where missing_sections is non-empty."""
    sl = foundry.spec_lint(MULTI_REVIEW)
    d = sl.to_dict()
    assert len(d["missing_sections"]) > 0, "missing_sections empty -- guard would be vacuous"
    assert json.loads(json.dumps(d)) == d
    bad = dict(d)
    bad["missing_sections"] = sl.missing_sections  # the raw frozen tuple
    assert isinstance(bad["missing_sections"], tuple)
    assert json.loads(json.dumps(bad)) != bad, (
        "round-trip check is vacuous -- a tuple-valued missing_sections did not break equality")


# ==========================================================================
# Behavior 6 -- to_dict() is a FRESH dict each call; mutation isolation
# ==========================================================================
def test_b06_to_dict_read_only():
    for txt in (MULTI_REVIEW, OK_SPEC):
        sl = foundry.spec_lint(txt)
        before = dataclasses.asdict(sl)
        d1 = sl.to_dict()
        d1["missing_sections"].append("## BOGUS")
        d1["verdict"] = "TAMPERED"
        d1["NEWKEY"] = 1
        d2 = sl.to_dict()
        assert dataclasses.asdict(sl) == before, "to_dict mutated the frozen instance"
        assert d2 == foundry.spec_lint(txt).to_dict(), "second to_dict affected by mutation"
        assert "NEWKEY" not in d2
        assert d1 is not d2


def test_b06_two_calls_equal_but_distinct():
    sl = foundry.spec_lint(MULTI_REVIEW)
    a, b = sl.to_dict(), sl.to_dict()
    assert a == b
    assert a is not b
    assert a["missing_sections"] is not b["missing_sections"], (
        "missing_sections list is shared across calls")


# ==========================================================================
# Behavior 7 -- lint_spec_cli signature: params ["path","as_json"], default False
# ==========================================================================
def test_b07_signature_params_and_default():
    sig = inspect.signature(foundry.lint_spec_cli)
    assert list(sig.parameters) == ["path", "as_json"], list(sig.parameters)
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 8 -- DEFAULT (as_json=False) human render is byte-identical to the
#               spec's documented format, over OK / REVIEW / oversized
# ==========================================================================
def test_b08_default_human_render_byte_identical(tmp_path):
    for name, txt in (("ok", OK_SPEC), ("review", REVIEW_SPEC), ("multi", MULTI_REVIEW)):
        sub = tmp_path / name
        sub.mkdir()
        p = _write_spec(sub, txt)
        rc, out = _cap(lambda: foundry.lint_spec_cli(p, as_json=False))
        assert out == _expected_human(p), (
            "human render mismatch for %r:\n got=%r\n exp=%r" % (name, out, _expected_human(p)))


def test_b08_default_human_render_oversized(tmp_path, monkeypatch):
    p = _write_spec(tmp_path, _full_spec(5, pad_chars=20))
    monkeypatch.setattr(foundry, "SPEC_MAX_BEHAVIORS", 2)  # 5 > 2 -> oversized REVIEW
    rc, out = _cap(lambda: foundry.lint_spec_cli(p, as_json=False))
    assert rc == 1
    assert out == _expected_human(p), (
        "oversized human render mismatch:\n got=%r\n exp=%r" % (out, _expected_human(p)))
    assert "verdict: REVIEW" in out


def test_b08_default_equals_explicit_false(tmp_path):
    for name, txt in (("ok", OK_SPEC), ("review", REVIEW_SPEC)):
        sub = tmp_path / name
        sub.mkdir()
        p = _write_spec(sub, txt)
        rc_def, out_def = _cap(lambda: foundry.lint_spec_cli(p))
        rc_false, out_false = _cap(lambda: foundry.lint_spec_cli(p, as_json=False))
        assert out_def == out_false, "default != explicit as_json=False for %r" % name
        assert rc_def == rc_false


def test_b08_human_render_not_valid_json(tmp_path):
    for name, txt in (("ok", OK_SPEC), ("review", REVIEW_SPEC)):
        sub = tmp_path / name
        sub.mkdir()
        p = _write_spec(sub, txt)
        _, human = _cap(lambda: foundry.lint_spec_cli(p, as_json=False))
        with pytest.raises(json.JSONDecodeError):
            json.loads(human)


# ==========================================================================
# Behavior 9 -- as_json=True on an EXISTING file prints EXACTLY
#               json.dumps(to_dict(),indent=2)+newline; no human line leaks
# ==========================================================================
def test_b09_json_output_is_exact(tmp_path):
    for name, txt in (("ok", OK_SPEC), ("review", REVIEW_SPEC), ("multi", MULTI_REVIEW)):
        sub = tmp_path / name
        sub.mkdir()
        p = _write_spec(sub, txt)
        _, out = _cap(lambda: foundry.lint_spec_cli(p, as_json=True))
        expected = json.dumps(foundry.spec_lint(txt).to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(),indent=2)+nl for %r" % name
        assert json.loads(out) == foundry.spec_lint(txt).to_dict()


def test_b09_json_lines_start_with_json_token(tmp_path):
    for name, txt in (("ok", OK_SPEC), ("review", REVIEW_SPEC), ("multi", MULTI_REVIEW)):
        sub = tmp_path / name
        sub.mkdir()
        p = _write_spec(sub, txt)
        _, out = _cap(lambda: foundry.lint_spec_cli(p, as_json=True))
        for ln in out.splitlines():
            s = ln.strip()
            assert s == "" or s[0] in "{}[]\"", (
                "JSON line does not start with a JSON token (%r case): %r" % (name, ln))


def test_b09_leak_check_armed_by_human_complement(tmp_path):
    """The SAME structural check must FAIL on the human render -- else its pass
    on JSON is meaningless. Every human line leads with a letter."""
    for name, txt in (("ok", OK_SPEC), ("review", REVIEW_SPEC), ("multi", MULTI_REVIEW)):
        sub = tmp_path / name
        sub.mkdir()
        p = _write_spec(sub, txt)
        _, human = _cap(lambda: foundry.lint_spec_cli(p, as_json=False))
        nonblank = [ln for ln in human.splitlines() if ln.strip()]
        assert nonblank, "human render empty for %r" % name
        offenders = [ln for ln in nonblank if ln.strip()[0] not in "{}[]\""]
        assert offenders, (
            "leak check inert for %r -- every human line looked like JSON: %r" % (name, human))


# ==========================================================================
# Behavior 10 -- EXIT-CODE parity: identical in both modes; 0 OK / 1 REVIEW
# ==========================================================================
def test_b10_exit_code_parity(tmp_path):
    for name, txt, code in (("ok", OK_SPEC, 0), ("review", REVIEW_SPEC, 1),
                            ("multi", MULTI_REVIEW, 1)):
        sub = tmp_path / name
        sub.mkdir()
        p = _write_spec(sub, txt)
        rc_h, _ = _cap(lambda: foundry.lint_spec_cli(p, as_json=False))
        rc_j, _ = _cap(lambda: foundry.lint_spec_cli(p, as_json=True))
        assert rc_h == rc_j == code, (
            "exit diverged for %r: human=%r json=%r expected=%r" % (name, rc_h, rc_j, code))


def test_b10_oversized_exit1_both_modes(tmp_path, monkeypatch):
    p = _write_spec(tmp_path, _full_spec(5, pad_chars=20))
    monkeypatch.setattr(foundry, "SPEC_MAX_BEHAVIORS", 2)
    rc_h, _ = _cap(lambda: foundry.lint_spec_cli(p, as_json=False))
    rc_j, _ = _cap(lambda: foundry.lint_spec_cli(p, as_json=True))
    assert rc_h == rc_j == 1


# ==========================================================================
# Behavior 11 -- FILE-NOT-FOUND in BOTH modes: identical plain-text, rc 2, no raise
# ==========================================================================
def test_b11_missing_file_both_modes_plain_text(tmp_path):
    missing = str(tmp_path / "does_not_exist.md")
    assert not pathlib.Path(missing).exists()
    expected = "lint-spec: file not found: %s\n" % missing
    for as_json in (False, True):
        rc, out = _cap(lambda: foundry.lint_spec_cli(missing, as_json=as_json))
        assert rc == 2, "missing file returned %r (as_json=%s)" % (rc, as_json)
        assert out == expected, "missing-file line mismatch (as_json=%s): %r" % (as_json, out)
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)  # NOT JSON in either mode


def test_b11_missing_file_never_raises_filenotfound(tmp_path):
    missing = str(tmp_path / "nope.md")
    for as_json in (False, True):
        try:
            foundry.lint_spec_cli(missing, as_json=as_json)  # must not raise
        except FileNotFoundError:  # pragma: no cover
            pytest.fail("lint_spec_cli raised FileNotFoundError (as_json=%s)" % as_json)


# ==========================================================================
# Behavior 12 -- writes NOTHING in both modes, from an empty cwd, over all cases
# ==========================================================================
def test_b12_writes_nothing(tmp_path, monkeypatch):
    cwd = tmp_path / "emptycwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    cases = {"ok": OK_SPEC, "review": REVIEW_SPEC, "missing": None}
    for name, txt in cases.items():
        sub = tmp_path / ("case_" + name)
        sub.mkdir()
        if txt is None:
            p = str(sub / "absent.md")  # never created
        else:
            p = _write_spec(sub, txt)
        before = _snapshot_tree(sub)
        for as_json in (False, True):
            _cap(lambda: foundry.lint_spec_cli(p, as_json=as_json))
        assert sorted(q.name for q in cwd.iterdir()) == [], "CLI wrote to cwd for %r" % name
        assert _snapshot_tree(sub) == before, "CLI changed the spec dir for %r" % name


# ==========================================================================
# Behavior 13 -- argparse routing: --json is store_true; dispatch spy proves
#                as_json True/False; --file REQUIRED
# ==========================================================================
def test_b13_json_store_true_via_dispatch_spy(tmp_path, monkeypatch):
    p = _write_spec(tmp_path, OK_SPEC)
    captured = {}

    def fake(path, as_json=False):
        captured.update(path=path, as_json=as_json)
        return 0

    monkeypatch.setattr(foundry, "lint_spec_cli", fake)
    foundry.main(["lint-spec", "--file", p, "--json"])
    assert captured == {"path": p, "as_json": True}
    captured.clear()
    foundry.main(["lint-spec", "--file", p])
    assert captured == {"path": p, "as_json": False}


def test_b13_file_required_raises_systemexit():
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["lint-spec"])
    assert ei.value.code != 0


def test_b13_json_takes_no_value(tmp_path):
    p = _write_spec(tmp_path, OK_SPEC)
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["lint-spec", "--file", p, "--json", "bogus"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 14 -- end-to-end via foundry.main
# ==========================================================================
def test_b14_e2e_ok(tmp_path):
    p = _write_spec(tmp_path, OK_SPEC)
    rc, out = _cap(lambda: foundry.main(["lint-spec", "--file", p, "--json"]))
    d = json.loads(out)
    assert rc == 0
    assert d["verdict"] == "OK"
    assert d["ok"] is True
    assert d["missing_sections"] == []


def test_b14_e2e_review(tmp_path):
    p = _write_spec(tmp_path, MULTI_REVIEW)
    rc, out = _cap(lambda: foundry.main(["lint-spec", "--file", p, "--json"]))
    d = json.loads(out)
    assert rc == 1
    assert d["verdict"] == "REVIEW"
    assert d["ok"] is False
    assert isinstance(d["missing_sections"], list) and len(d["missing_sections"]) >= 1


def test_b14_e2e_missing_plain_text(tmp_path):
    missing = str(tmp_path / "gone.md")
    rc, out = _cap(lambda: foundry.main(["lint-spec", "--file", missing, "--json"]))
    assert rc == 2
    assert out == "lint-spec: file not found: %s\n" % missing
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# ==========================================================================
# Behavior 15 -- DORMANCY: the running loop is unaffected
# ==========================================================================
def test_b15_orchestrators_do_not_reference_lint_symbols():
    new = set(LINT_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references lint-spec symbol(s): %r" % (fn.__name__, refs)


def test_b15_dispatcher_has_zero_lint_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for s in LINT_SYMBOLS:
        assert dtext.count(s) == 0, "dispatcher.py references %s" % s
    assert dtext.count("lint-spec") == 0, "dispatcher.py names the 'lint-spec' command string"


def test_b15_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_b15_to_dict_does_not_change_field_equality():
    a = foundry.spec_lint(MULTI_REVIEW)
    b = foundry.spec_lint(MULTI_REVIEW)
    assert a == b, "adding to_dict must not change SpecLint value-equality"
    _ = a.to_dict()
    assert a == b


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.spec_lint)
    assert callable(foundry.lint_spec_cli)
    assert dataclasses.is_dataclass(foundry.SpecLint)
    assert callable(foundry.SpecLint.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_lint_spec(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "lint-spec" in out
    for sub in ("run", "once", "learnings", "agents", "prd"):
        assert sub in out, "subcommand %r missing from --help (regression)" % sub


def test_ac_new_symbols_ascii():
    """Scoped to the two symbols via inspect.getsource -- NOT a whole-file scan
    (foundry.py carries pre-existing non-ASCII elsewhere -- the iter-67 trap)."""
    srcs = [
        inspect.getsource(foundry.SpecLint.to_dict),
        inspect.getsource(foundry.lint_spec_cli),
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
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
