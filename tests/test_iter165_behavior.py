"""Black-box behaviour tests for iter 165 -- the eight per-product `--json` CLI
verbs collapse onto ONE shared thin-printer body (`_thin_gather_cli`) while every
OBSERVABLE behaviour stays unchanged.

Under test (spec Feature): `weak_tests_cli`, `constant_asserts_cli`,
`skipped_tests_cli`, `history_cli`, `novelty_check_cli`, `outcomes_cli`,
`directions_cli`, `timing_cli` -- each becomes a one-line delegation that keeps
its own name, signature and docstring, and each still resolves its own
`gather_*` seam from MODULE GLOBALS at CALL time (spec behavior 7).

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-165 PM
spec's Expected Behaviors (1-10), the tests/ conventions (esp.
tests/test_iter152_behavior.py and tests/test_iter137_behavior.py, the company-
side mirrors of this same collapse), and the product's OWN OBSERVABLE behaviour
(calling the eight public verbs plus the shared body with scripted seams and
reading their return code and stdout, and driving `main()`'s argparse dispatch).
foundry.py's implementation text was NOT read by hand, the engineer's notes, the
reviewer's notes and `git diff` were NOT consulted. Behavior 9 is a STRUCTURAL
acceptance criterion the spec states in AST terms, so it is asserted by parsing
`foundry.py` MECHANICALLY, scoped to exactly the eight named functions -- it
asserts nothing about any other function (foundry.py carries plenty of
pre-existing shapes this iteration must not police).
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

_SOURCE = _ROOT / "foundry.py"

# ---------------------------------------------------------------------------
# the family under test -- (cli name, gather seam, 2nd param, cli verb, 2nd flag)
# ---------------------------------------------------------------------------
EIGHT: tuple[tuple[str, str, str, str, str], ...] = (
    ("weak_tests_cli", "gather_weak_tests", "files", "weak-tests", "--files"),
    ("constant_asserts_cli", "gather_constant_asserts", "files",
     "constant-asserts", "--files"),
    ("skipped_tests_cli", "gather_skipped_tests", "files", "skipped-tests",
     "--files"),
    ("history_cli", "gather_history", "limit", "history", "--limit"),
    ("novelty_check_cli", "gather_novelty", "limit", "novelty-check", "--limit"),
    ("outcomes_cli", "gather_outcomes", "limit", "outcomes", "--limit"),
    ("directions_cli", "gather_directions", "limit", "directions", "--limit"),
    ("timing_cli", "gather_timing", "limit", "timing", "--limit"),
)

HELPER = "_thin_gather_cli"


# ---------------------------------------------------------------------------
# scripted doubles -- no real gather, no subprocess, no git, no network
# ---------------------------------------------------------------------------
class FakeResult:
    """A stand-in for the eight summary dataclasses: render / to_dict / exit_code."""

    def __init__(self, exit_code: int = 0, text: str = "HUMAN REPORT\nline two",
                 payload: dict | None = None) -> None:
        self.exit_code = exit_code
        self._text = text
        self._payload = {"kind": "fake", "n": 3} if payload is None else payload
        self.render_calls = 0
        self.to_dict_calls = 0

    def render(self) -> str:
        self.render_calls += 1
        return self._text

    def to_dict(self) -> dict:
        self.to_dict_calls += 1
        return self._payload


class RecordingGather:
    """Records EXACTLY how the wrapper called the seam."""

    def __init__(self, result: FakeResult) -> None:
        self.result = result
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs) -> FakeResult:
        self.calls.append((args, kwargs))
        return self.result


def _capture(fn, *args, **kwargs) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(*args, **kwargs)
    return code, buf.getvalue()


def _tree(root: pathlib.Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _bodies() -> dict[str, ast.FunctionDef]:
    """The eight FunctionDef nodes, parsed mechanically from foundry.py."""
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    wanted = {name for name, *_ in EIGHT}
    found: dict[str, ast.FunctionDef] = {}
    for node in tree.body:  # module level only -- these eight are module-level
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            assert node.name not in found, f"{node.name} defined twice at module level"
            found[node.name] = node
    missing = wanted - set(found)
    assert not missing, f"module-level defs not found: {sorted(missing)}"
    return found


def _executable_body(node: ast.FunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return body


# ---------------------------------------------------------------------------
# behavior 1 -- the shared helper exists and passes its arguments through
# ---------------------------------------------------------------------------
def test_b01_helper_exists_at_module_level_with_the_specified_signature() -> None:
    assert hasattr(foundry, HELPER), f"spec behavior 1: foundry.{HELPER} must exist"
    fn = getattr(foundry, HELPER)
    assert inspect.isfunction(fn), f"{HELPER} must be a plain module-level function"
    assert fn.__module__ == "foundry"
    params = tuple(inspect.signature(fn).parameters)
    assert params == ("gather", "cfg", "arg", "as_json"), params


@pytest.mark.parametrize("as_json", [False, True])
def test_b01_helper_calls_gather_once_with_two_positional_args_by_identity(as_json) -> None:
    result = FakeResult()
    gather = RecordingGather(result)
    cfg = object()
    arg = object()
    _capture(foundry._thin_gather_cli, gather, cfg, arg, as_json)
    assert len(gather.calls) == 1, f"gather called {len(gather.calls)}x, want exactly 1"
    args, kwargs = gather.calls[0]
    assert kwargs == {}, f"seam must be called positionally, got kwargs {kwargs}"
    assert len(args) == 2, f"seam must get exactly (cfg, arg), got {len(args)} args"
    assert args[0] is cfg, "cfg must pass through unchanged (identity)"
    assert args[1] is arg, "second argument must pass through unchanged (identity)"


# ---------------------------------------------------------------------------
# behaviors 2 + 3 -- the two print branches are mutually exclusive
# ---------------------------------------------------------------------------
def test_b02_human_mode_prints_render_only_and_never_calls_to_dict() -> None:
    result = FakeResult(text="HUMAN REPORT\nline two")
    _, out = _capture(foundry._thin_gather_cli, RecordingGather(result), object(),
                      None, False)
    assert out == "HUMAN REPORT\nline two\n", repr(out)
    assert result.render_calls == 1, result.render_calls
    assert result.to_dict_calls == 0, "human mode must not call to_dict()"


def test_b03_json_mode_prints_indent_two_json_only_and_never_calls_render() -> None:
    payload = {"kind": "fake", "rows": [1, 2], "nested": {"a": True}}
    result = FakeResult(payload=payload)
    _, out = _capture(foundry._thin_gather_cli, RecordingGather(result), object(),
                      None, True)
    assert out == json.dumps(payload, indent=2) + "\n", repr(out)
    assert json.loads(out) == payload, "stdout must be ONE parseable JSON document"
    assert result.to_dict_calls == 1, result.to_dict_calls
    assert result.render_calls == 0, "json mode must not call render()"


# ---------------------------------------------------------------------------
# behavior 4 -- exit code passes through untouched in both modes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", [0, 1, 2])
@pytest.mark.parametrize("as_json", [False, True])
def test_b04_helper_returns_result_exit_code_unchanged(code, as_json) -> None:
    result = FakeResult(exit_code=code)
    got, _ = _capture(foundry._thin_gather_cli, RecordingGather(result), object(),
                      None, as_json)
    assert got == code, f"helper must add no verdict logic: got {got}, want {code}"


# ---------------------------------------------------------------------------
# behavior 5 -- the helper touches no disk
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("as_json", [False, True])
def test_b05_helper_writes_nothing_to_disk(tmp_path, monkeypatch, as_json) -> None:
    monkeypatch.chdir(tmp_path)
    before = _tree(tmp_path)
    _capture(foundry._thin_gather_cli, RecordingGather(FakeResult()), object(),
             None, as_json)
    assert _tree(tmp_path) == before, "helper created files/directories"


# ---------------------------------------------------------------------------
# behavior 6 -- the eight public signatures are byte-for-byte load-bearing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,seam,second,verb,flag", EIGHT)
def test_b06_public_signature_names_order_and_defaults_are_unchanged(
        name, seam, second, verb, flag) -> None:
    fn = getattr(foundry, name)
    sig = inspect.signature(fn)
    assert tuple(sig.parameters) == ("cfg", second, "as_json"), tuple(sig.parameters)
    params = sig.parameters
    assert params["cfg"].default is inspect.Parameter.empty
    assert params[second].default is None, params[second].default
    assert params["as_json"].default is False, params["as_json"].default
    for p in params.values():
        assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, (p.name, p.kind)
    assert (fn.__doc__ or "").strip(), f"{name} must keep its docstring"


@pytest.mark.parametrize("name,seam,second,verb,flag", EIGHT)
def test_b06_callable_both_positionally_and_by_keyword(name, seam, second, verb,
                                                       flag, monkeypatch) -> None:
    cfg, arg = object(), object()
    for call in ("positional", "keyword"):
        gather = RecordingGather(FakeResult(exit_code=1))
        monkeypatch.setattr(foundry, seam, gather)
        fn = getattr(foundry, name)
        if call == "positional":
            code, _ = _capture(fn, cfg, arg, True)
        else:
            code, _ = _capture(fn, cfg, **{second: arg, "as_json": True})
        assert code == 1, f"{name} ({call}) returned {code}"
        assert len(gather.calls) == 1, f"{name} ({call}) seam calls: {gather.calls}"
        assert gather.calls[0][0][0] is cfg
        assert gather.calls[0][0][1] is arg


# ---------------------------------------------------------------------------
# behavior 7 -- SEAM VISIBILITY: monkeypatch of the module global still bites
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,seam,second,verb,flag", EIGHT)
@pytest.mark.parametrize("as_json", [False, True])
def test_b07_seam_is_resolved_from_module_globals_at_call_time(
        name, seam, second, verb, flag, as_json, monkeypatch) -> None:
    assert hasattr(foundry, seam), f"seam foundry.{seam} must exist"
    result = FakeResult(exit_code=2, text="STUBBED", payload={"stub": True})
    gather = RecordingGather(result)
    monkeypatch.setattr(foundry, seam, gather)
    cfg, arg = object(), object()
    code, out = _capture(getattr(foundry, name), cfg, arg, as_json)
    assert len(gather.calls) == 1, (
        f"{name} did not reach the monkeypatched {seam}: the seam is captured at "
        f"import/def time instead of resolved from module globals at CALL time"
    )
    assert code == 2, f"{name} must return the stub's exit_code, got {code}"
    expected = (json.dumps({"stub": True}, indent=2) if as_json else "STUBBED") + "\n"
    assert out == expected, repr(out)


# ---------------------------------------------------------------------------
# behavior 8 -- output preservation: every verb prints the SAME two shapes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,seam,second,verb,flag", EIGHT)
def test_b08_each_verb_output_matches_the_shared_contract(name, seam, second,
                                                          verb, flag,
                                                          monkeypatch) -> None:
    """The verb's observable output must equal the shared helper's, given the
    same result object -- that IS the parity the collapse promises."""
    payload = {"verb": verb, "rows": []}
    for as_json in (False, True):
        via_verb = FakeResult(exit_code=1, text="TEXT " + verb, payload=payload)
        monkeypatch.setattr(foundry, seam, RecordingGather(via_verb))
        code_v, out_v = _capture(getattr(foundry, name), object(), None, as_json)
        via_helper = FakeResult(exit_code=1, text="TEXT " + verb, payload=payload)
        code_h, out_h = _capture(foundry._thin_gather_cli,
                                 RecordingGather(via_helper), object(), None,
                                 as_json)
        assert (code_v, out_v) == (code_h, out_h), (
            f"{name} diverges from {HELPER} in as_json={as_json}: "
            f"{(code_v, out_v)!r} != {(code_h, out_h)!r}"
        )


# ---------------------------------------------------------------------------
# behavior 9 -- THINNESS META-TEST (scoped to the eight names ONLY)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,seam,second,verb,flag", EIGHT)
def test_b09_body_is_exactly_one_return_of_a_thin_gather_cli_call(
        name, seam, second, verb, flag) -> None:
    node = _bodies()[name]
    body = _executable_body(node)
    assert len(body) == 1, (
        f"{name} must have an executable body of exactly ONE statement "
        f"(docstring excluded), found {len(body)}: "
        f"{[type(s).__name__ for s in body]}"
    )
    stmt = body[0]
    assert isinstance(stmt, ast.Return), type(stmt).__name__
    assert isinstance(stmt.value, ast.Call), type(stmt.value).__name__
    call = stmt.value
    assert isinstance(call.func, ast.Name) and call.func.id == HELPER, (
        f"{name} must return a call to the bare name {HELPER}"
    )
    # spec Acceptance: the seam is a POSITIONAL argument resolved by BARE NAME --
    # no default-arg capture, no functools.partial, no import-time seam dict.
    assert call.args, f"{name} must pass the seam positionally"
    assert isinstance(call.args[0], ast.Name), (
        f"{name}: first argument must be the bare seam name, got "
        f"{type(call.args[0]).__name__}"
    )
    assert call.args[0].id == seam, (call.args[0].id, seam)
    for i, a in enumerate(call.args):
        assert isinstance(a, ast.Name), (
            f"{name}: positional arg {i} must be a bare Name, got "
            f"{type(a).__name__} (a partial/lambda/attribute would freeze the "
            f"seam at import time)"
        )
    for kw in call.keywords:
        assert kw.arg is not None, f"{name} must not splat **kwargs into {HELPER}"
        assert isinstance(kw.value, ast.Name), (
            f"{name}: keyword {kw.arg} must be a bare Name, got "
            f"{type(kw.value).__name__}"
        )


def test_b09_helper_docstring_states_call_time_seam_and_cites_the_sibling() -> None:
    doc = (foundry._thin_gather_cli.__doc__ or "")
    low = doc.lower()
    assert doc.strip(), f"{HELPER} must carry a docstring"
    assert "call" in low and "time" in low, (
        "docstring must state the CALL-TIME seam resolution requirement"
    )
    assert "_company_rollup_cli" in doc, (
        "docstring must cite _company_rollup_cli as its company-side sibling"
    )


# ---------------------------------------------------------------------------
# behavior 10 -- imports stay clean and the eight verbs stay reachable via main()
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("module", ["foundry", "dispatcher"])
def test_b10_module_imports_cleanly_in_a_fresh_interpreter(module) -> None:
    proc = subprocess.run([sys.executable, "-c", f"import {module}"],
                          cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]


@pytest.mark.parametrize("name,seam,second,verb,flag", EIGHT)
def test_b10_verb_is_registered_with_its_flags(name, seam, second, verb,
                                               flag) -> None:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        with pytest.raises(SystemExit):
            foundry.main([verb, "--help"])
    text = buf.getvalue()
    assert verb in text, text[:400]
    assert flag in text, text[:400]
    assert "--json" in text, text[:400]


@pytest.mark.parametrize("name,seam,second,verb,flag", EIGHT)
@pytest.mark.parametrize("as_json", [False, True])
def test_b10_main_argparse_dispatch_still_reaches_each_verb(
        name, seam, second, verb, flag, as_json, monkeypatch, tmp_path) -> None:
    """main() dispatches by KEYWORD, so a renamed parameter would break the CLI
    without any pure-function test noticing (spec behavior 6/10)."""
    result = FakeResult(exit_code=2, text="VIA MAIN", payload={"via": "main"})
    gather = RecordingGather(result)
    monkeypatch.setattr(foundry, seam, gather)
    cfg = types.SimpleNamespace(name="dummy-product")
    monkeypatch.setattr(foundry, "load_config", lambda *a, **k: cfg)
    argv = [verb, "--config", str(tmp_path / "config.json")]
    argv += [flag, "3"] if flag == "--limit" else [flag, "a_test.py"]
    if as_json:
        argv.append("--json")
    code, out = _capture(foundry.main, argv)
    assert code == 2, f"{verb} via main() returned {code}"
    assert len(gather.calls) == 1, f"{verb} via main() seam calls: {gather.calls}"
    assert gather.calls[0][0][0] is cfg, "main() must pass the loaded cfg through"
    passed = gather.calls[0][0][1]
    assert passed == (3 if flag == "--limit" else ["a_test.py"]), passed
    expected = (json.dumps({"via": "main"}, indent=2) if as_json else "VIA MAIN") + "\n"
    assert out == expected, repr(out)
