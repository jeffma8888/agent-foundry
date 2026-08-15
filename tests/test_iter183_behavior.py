"""Black-box behaviour tests for iter 183 -- the three `gather_*` test-quality
scanners collapse onto ONE shared private body `_gather_test_scan`, with the
detector and summarizer resolved by BARE NAME at call time so every existing
inner monkeypatch keeps biting.

Spec: products/_platform/state/iter-183/pm.md, Expected Behaviors 1-10.

  1.  Explicit file list -- `files=[p1, p2]` gives each member a summary with
      `product == cfg.name` and `files_scanned == 2`, and `_gather_weak_test_files`
      is NOT called (proved with a recording stub that would also have raised).
  2.  Discovery path -- `files=None` obtains paths from `_gather_weak_test_files`
      called with `cfg.repo`; rebinding that name on the module AFTER import
      changes what all three scan (bare-name resolution at call time).
  3.  Finding shape -- one finding `(str(path), name)` per detector-reported name,
      ordered path-major then in the detector's own order.
  4.  Graceful degradation per path -- a `SyntaxError` (and separately an
      `OSError`) out of `test_tree(path)` yields NO finding for that path, exactly
      one `parse_errors` entry `(str(path), "SyntaxError: <exc>")`, and the scan
      CONTINUES so a later good path's findings survive. Asserted for all three.
  5.  Detector isolation -- rebinding `find_assertionless_tests` moves ONLY
      `gather_weak_tests`; `find_constant_assert_tests` ONLY
      `gather_constant_asserts`; `find_always_skipped_tests` ONLY
      `gather_skipped_tests`. No cross-talk.
  6.  Summarizer seam -- rebinding `summarize_weak_tests` (and each sibling) to a
      recording stub makes the matching member return that stub's object, called
      once with NO positional args and exactly the four keyword args `product`,
      `files_scanned`, `findings`, `parse_errors`, the last two being `tuple`.
  7.  No frozen patch site -- `inspect.signature(_gather_test_scan)` shows no
      default for the detector/summarizer parameters; no member binds them in a
      default arg; none of the six seams is a `functools.partial`; the shared body
      names no detector/summarizer in its own `co_names`/`co_consts` (so it
      performs no internal lookup); and each wrapper passes them as bare
      `ast.Name` arguments.
  8.  One shared body -- `_gather_test_scan` is a module-level function and each
      member's body, docstring excluded, is a SINGLE `return` whose call target is
      the `ast.Name` `_gather_test_scan`.
  9.  Byte-identical reports -- `render()` pinned to an independently constructed
      golden over four input shapes (clean / findings-only / parse-error-only /
      mixed) x three members, `verdict:` is the LAST non-empty line, and
      `to_dict()` keeps exactly its eight keys.
  10. Docstring ownership -- each member keeps a substantial docstring of its own
      that references a numbered Behavior and names its OWN detector and its OWN
      summarizer; the three are pairwise distinct.
  Plus acceptance-criteria oracles: `foundry` and `dispatcher` still import, and
  the iter-183 roadmap records are present exactly once each in the two TRACKED
  roadmap documents.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-183 PM spec, the repo's
`tests/` conventions, the two tracked roadmap documents and the product's
OBSERVABLE surface -- importing the module, CALLING its public functions,
`inspect.signature`, `__doc__`, and an AST STRUCTURE census over the shipped
source text. The implementation bodies were not read as prose, the engineer's and
reviewer's notes and `IMPLEMENTATION.patch` were not opened, and `git diff` was
not run.

Offline and deterministic: `tmp_path` paths and synthetic stubs only. No
subprocess, no network, no clock dependence. Every `cfg.repo` points inside
`tmp_path`, so the real foundry repo is never written to. The parse-error goldens
use a STUBBED `test_tree` raising a fixed message, never CPython's own
version-dependent `SyntaxError` text.
"""
import ast
import functools
import inspect
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

# ---------------------------------------------------------------------------
# The triplet under test, described only by its PUBLIC names and REPORT text.
#   member, detector seam, summarizer seam, report verb, count label, verdict
# ---------------------------------------------------------------------------
TRIPLET = [
    (
        "gather_weak_tests",
        "find_assertionless_tests",
        "summarize_weak_tests",
        "weak-tests",
        "assertion-free tests",
        "WEAK TESTS FOUND",
    ),
    (
        "gather_constant_asserts",
        "find_constant_assert_tests",
        "summarize_constant_asserts",
        "constant-asserts",
        "constant-assert tests",
        "CONSTANT ASSERTS FOUND",
    ),
    (
        "gather_skipped_tests",
        "find_always_skipped_tests",
        "summarize_skipped_tests",
        "skipped-tests",
        "always-skipped tests",
        "ALWAYS-SKIPPED TESTS FOUND",
    ),
]
MEMBERS = [t[0] for t in TRIPLET]
DETECTORS = [t[1] for t in TRIPLET]
SUMMARIZERS = [t[2] for t in TRIPLET]
SUMMARY_KEYS = {
    "clean",
    "exit_code",
    "files_scanned",
    "findings",
    "parse_errors",
    "product",
    "total_findings",
    "verdict",
}


# ---------------------------------------------------------------------------
# helpers -- mirror tests/test_iter182_behavior.py's conventions; `repo` is
# ALWAYS a tmp dir so the real foundry repo can never be read or written
# ---------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _paths(tmp_path, *names):
    """tmp paths that need not EXIST -- `test_tree` is stubbed in most tests."""
    d = pathlib.Path(tmp_path) / "repo" / "tests"
    d.mkdir(parents=True, exist_ok=True)
    return [d / n for n in names]


def _stub_tree(monkeypatch):
    """Make `test_tree(path)` a pure, offline identity marker for that path."""

    def fake_tree(path):
        return ("TREE", str(path))

    monkeypatch.setattr(foundry, "test_tree", fake_tree)


def _stub_detector(monkeypatch, seam, by_path):
    """Rebind ONE detector seam so it reports `by_path[<path>]` for each tree."""

    def fake_detector(tree):
        assert isinstance(tree, tuple) and tree[0] == "TREE", tree
        return tuple(by_path.get(tree[1], ()))

    monkeypatch.setattr(foundry, seam, fake_detector)


def _no_discovery(monkeypatch):
    """Record every `_gather_weak_test_files` call; returning [] would make a
    stray call OBSERVABLE as files_scanned == 0 as well."""
    calls = []

    def fake(repo):
        calls.append(repo)
        return []

    monkeypatch.setattr(foundry, "_gather_weak_test_files", fake)
    return calls


def _expected_render(verb, label, verdict_found, product, scanned, findings, errors):
    """Independently CONSTRUCT the report text from the documented layout.

    Not a copy of the product's own rendering code -- built from the report
    format the CLI has published since these scanners existed, so a byte
    mismatch is a real regression rather than a tautology.
    """
    if scanned == 0:
        verdict = "nothing to scan"
    elif not findings and not errors:
        verdict = "clean"
    else:
        verdict = verdict_found
    lines = [
        f"foundry {verb} -- {product}",
        f"  files scanned: {scanned}",
        f"  {label}: {len(findings)}",
    ]
    lines += [f"  {p} :: {n}" for p, n in findings]
    lines.append(f"  parse errors: {len(errors)}")
    lines += [f"  {p}: {m}" for p, m in errors]
    lines.append(f"verdict: {verdict}")
    return "\n".join(lines)


def _module_ast():
    src = pathlib.Path(foundry.__file__).read_text()
    return ast.parse(src)


@functools.lru_cache(maxsize=1)
def _top_level_functions():
    return {
        node.name: node
        for node in _module_ast().body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _body_without_docstring(node):
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


# ===========================================================================
# Behavior 1 -- explicit file list
# ===========================================================================
@pytest.mark.parametrize("member", MEMBERS)
def test_b1_explicit_file_list_never_discovers(tmp_path, monkeypatch, member):
    cfg = _cfg(tmp_path)
    p1, p2 = _paths(tmp_path, "test_a.py", "test_b.py")
    calls = _no_discovery(monkeypatch)
    _stub_tree(monkeypatch)
    for seam in DETECTORS:
        _stub_detector(monkeypatch, seam, {})

    summary = getattr(foundry, member)(cfg, files=[p1, p2])

    assert summary.product == cfg.name
    assert summary.files_scanned == 2
    assert calls == [], f"{member} called _gather_weak_test_files with {calls}"
    assert summary.findings == ()
    assert summary.parse_errors == ()


@pytest.mark.parametrize("member", MEMBERS)
def test_b1_empty_explicit_list_scans_nothing(tmp_path, monkeypatch, member):
    cfg = _cfg(tmp_path)
    calls = _no_discovery(monkeypatch)
    summary = getattr(foundry, member)(cfg, files=[])
    assert summary.files_scanned == 0
    assert calls == []
    assert summary.render().splitlines()[-1] == "verdict: nothing to scan"


# ===========================================================================
# Behavior 2 -- discovery path, resolved by BARE NAME at call time
# ===========================================================================
@pytest.mark.parametrize("member", MEMBERS)
def test_b2_discovery_uses_bare_name_seam(tmp_path, monkeypatch, member):
    cfg = _cfg(tmp_path)
    (only,) = _paths(tmp_path, "test_only.py")
    calls = []

    def fake_discovery(repo):
        calls.append(repo)
        return [only]

    monkeypatch.setattr(foundry, "_gather_weak_test_files", fake_discovery)
    _stub_tree(monkeypatch)
    for seam in DETECTORS:
        _stub_detector(monkeypatch, seam, {str(only): ("test_seen",)})

    summary = getattr(foundry, member)(cfg, files=None)

    assert calls == [cfg.repo], f"{member} discovery arg was {calls}"
    assert summary.files_scanned == 1
    assert summary.findings == ((str(only), "test_seen"),)


@pytest.mark.parametrize("member", MEMBERS)
def test_b2_discovery_is_the_default(tmp_path, monkeypatch, member):
    """Omitting `files` entirely takes the same discovery path."""
    cfg = _cfg(tmp_path)
    a, b = _paths(tmp_path, "test_1.py", "test_2.py")
    monkeypatch.setattr(foundry, "_gather_weak_test_files", lambda repo: [a, b])
    _stub_tree(monkeypatch)
    for seam in DETECTORS:
        _stub_detector(monkeypatch, seam, {})
    assert getattr(foundry, member)(cfg).files_scanned == 2


# ===========================================================================
# Behavior 3 -- finding shape and ordering
# ===========================================================================
@pytest.mark.parametrize("member,seam", [(t[0], t[1]) for t in TRIPLET])
def test_b3_findings_are_path_major_in_detector_order(
    tmp_path, monkeypatch, member, seam
):
    cfg = _cfg(tmp_path)
    p1, p2, p3 = _paths(tmp_path, "test_a.py", "test_b.py", "test_c.py")
    _no_discovery(monkeypatch)
    _stub_tree(monkeypatch)
    _stub_detector(
        monkeypatch,
        seam,
        {
            str(p1): ("test_zeta", "test_alpha"),  # NOT sorted -- detector order
            str(p3): ("test_mid",),
        },
    )

    summary = getattr(foundry, member)(cfg, files=[p1, p2, p3])

    assert summary.findings == (
        (str(p1), "test_zeta"),
        (str(p1), "test_alpha"),
        (str(p3), "test_mid"),
    )
    assert all(isinstance(p, str) and isinstance(n, str) for p, n in summary.findings)
    assert summary.files_scanned == 3
    assert summary.parse_errors == ()


# ===========================================================================
# Behavior 4 -- graceful degradation, per path, identical in all three
# ===========================================================================
@pytest.mark.parametrize("exc_cls", [SyntaxError, OSError])
@pytest.mark.parametrize("member,seam", [(t[0], t[1]) for t in TRIPLET])
def test_b4_parse_error_isolated_to_one_path(
    tmp_path, monkeypatch, member, seam, exc_cls
):
    cfg = _cfg(tmp_path)
    bad, good = _paths(tmp_path, "test_bad.py", "test_good.py")

    def fake_tree(path):
        if str(path) == str(bad):
            raise exc_cls("boom")
        return ("TREE", str(path))

    _no_discovery(monkeypatch)
    monkeypatch.setattr(foundry, "test_tree", fake_tree)
    _stub_detector(monkeypatch, seam, {str(good): ("test_survivor",)})

    summary = getattr(foundry, member)(cfg, files=[bad, good])

    # the bad path contributes NO finding ...
    assert summary.findings == ((str(good), "test_survivor"),)
    # ... exactly one parse_errors entry, "<ExcName>: <exc>" ...
    assert summary.parse_errors == ((str(bad), f"{exc_cls.__name__}: boom"),)
    # ... and both paths still counted, i.e. the scan CONTINUED
    assert summary.files_scanned == 2


@pytest.mark.parametrize("member,seam", [(t[0], t[1]) for t in TRIPLET])
def test_b4_every_path_can_fail(tmp_path, monkeypatch, member, seam):
    cfg = _cfg(tmp_path)
    p1, p2 = _paths(tmp_path, "test_x.py", "test_y.py")

    def boom(path):
        raise SyntaxError("nope")

    _no_discovery(monkeypatch)
    monkeypatch.setattr(foundry, "test_tree", boom)
    _stub_detector(monkeypatch, seam, {})

    summary = getattr(foundry, member)(cfg, files=[p1, p2])
    assert summary.findings == ()
    assert summary.parse_errors == (
        (str(p1), "SyntaxError: nope"),
        (str(p2), "SyntaxError: nope"),
    )
    assert summary.files_scanned == 2


@pytest.mark.parametrize("member", MEMBERS)
def test_b4_real_unparseable_file_degrades(tmp_path, monkeypatch, member):
    """No stubs at all: a genuinely unparseable file on disk is reported, not
    raised. Message TEXT is CPython-version dependent, so only its prefix is
    pinned here (the byte-golden tests use a stubbed message instead)."""
    cfg = _cfg(tmp_path)
    (bad,) = _paths(tmp_path, "test_broken.py")
    bad.write_text("def test_x(:\n    pass\n")
    _no_discovery(monkeypatch)

    summary = getattr(foundry, member)(cfg, files=[bad])
    assert summary.findings == ()
    assert len(summary.parse_errors) == 1
    path, msg = summary.parse_errors[0]
    assert path == str(bad)
    assert msg.startswith("SyntaxError: "), msg


# ===========================================================================
# Behavior 5 -- detector isolation, no cross-talk
# ===========================================================================
@pytest.mark.parametrize("owner,seam", [(t[0], t[1]) for t in TRIPLET])
def test_b5_detector_moves_only_its_own_member(tmp_path, monkeypatch, owner, seam):
    cfg = _cfg(tmp_path)
    (p,) = _paths(tmp_path, "test_only.py")
    p.write_text("def test_ok():\n    v = 1\n    assert v == 1\n")
    _no_discovery(monkeypatch)

    baseline = {m: getattr(foundry, m)(cfg, files=[p]).findings for m in MEMBERS}
    assert baseline[owner] == (), "fixture must be CLEAN for every member"

    monkeypatch.setattr(foundry, seam, lambda tree: ("test_injected",))
    after = {m: getattr(foundry, m)(cfg, files=[p]).findings for m in MEMBERS}

    assert after[owner] == ((str(p), "test_injected"),)
    for other in MEMBERS:
        if other != owner:
            assert after[other] == baseline[other], f"cross-talk into {other}"


# ===========================================================================
# Behavior 6 -- summarizer seam and its exact call shape
# ===========================================================================
@pytest.mark.parametrize("member,seam", [(t[0], t[2]) for t in TRIPLET])
def test_b6_summarizer_seam_call_shape(tmp_path, monkeypatch, member, seam):
    cfg = _cfg(tmp_path)
    bad, good = _paths(tmp_path, "test_bad.py", "test_good.py")
    sentinel = object()
    seen = []

    def recorder(*args, **kwargs):
        seen.append((args, kwargs))
        return sentinel

    def fake_tree(path):
        if str(path) == str(bad):
            raise SyntaxError("boom")
        return ("TREE", str(path))

    _no_discovery(monkeypatch)
    monkeypatch.setattr(foundry, "test_tree", fake_tree)
    monkeypatch.setattr(foundry, seam, recorder)
    for d in DETECTORS:
        _stub_detector(monkeypatch, d, {str(good): ("test_one",)})

    out = getattr(foundry, member)(cfg, files=[bad, good])

    assert out is sentinel, f"{member} did not return {seam}'s object"
    assert len(seen) == 1, seen
    args, kwargs = seen[0]
    assert args == (), f"{seam} received positional args {args!r}"
    assert set(kwargs) == {"product", "files_scanned", "findings", "parse_errors"}
    assert kwargs["product"] == cfg.name
    assert kwargs["files_scanned"] == 2
    assert type(kwargs["findings"]) is tuple
    assert type(kwargs["parse_errors"]) is tuple
    assert kwargs["findings"] == ((str(good), "test_one"),)
    assert kwargs["parse_errors"] == ((str(bad), "SyntaxError: boom"),)


@pytest.mark.parametrize("owner,seam", [(t[0], t[2]) for t in TRIPLET])
def test_b6_summarizer_seam_has_no_cross_talk(tmp_path, monkeypatch, owner, seam):
    cfg = _cfg(tmp_path)
    (p,) = _paths(tmp_path, "test_only.py")
    p.write_text("def test_ok():\n    v = 1\n    assert v == 1\n")
    sentinel = object()
    _no_discovery(monkeypatch)
    monkeypatch.setattr(foundry, seam, lambda **kw: sentinel)

    for m in MEMBERS:
        out = getattr(foundry, m)(cfg, files=[p])
        if m == owner:
            assert out is sentinel
        else:
            assert out is not sentinel, f"{seam} leaked into {m}"


# ===========================================================================
# Behavior 7 -- no frozen patch site
# ===========================================================================
def test_b7_shared_body_has_no_seam_defaults():
    sig = inspect.signature(foundry._gather_test_scan)
    assert list(sig.parameters) == ["cfg", "files", "detector", "summarize"]
    for name in ("detector", "summarize"):
        assert (
            sig.parameters[name].default is inspect.Parameter.empty
        ), f"_gather_test_scan.{name} carries a default -- frozen patch site"
    assert not (foundry._gather_test_scan.__defaults__ or ())
    assert not (foundry._gather_test_scan.__kwdefaults__ or {})


@pytest.mark.parametrize("member", MEMBERS)
def test_b7_member_binds_nothing_in_its_signature(member):
    sig = inspect.signature(getattr(foundry, member))
    assert list(sig.parameters) == ["cfg", "files"], f"{member} signature changed"
    assert sig.parameters["cfg"].default is inspect.Parameter.empty
    assert sig.parameters["files"].default is None
    fn = getattr(foundry, member)
    assert fn.__defaults__ == (None,), f"{member} defaults {fn.__defaults__!r}"
    assert not (fn.__kwdefaults__ or {})


@pytest.mark.parametrize("seam", DETECTORS + SUMMARIZERS)
def test_b7_seams_are_plain_patchable_functions(seam):
    obj = getattr(foundry, seam)
    assert not isinstance(obj, functools.partial), f"{seam} is a functools.partial"
    assert inspect.isfunction(obj), f"{seam} is not a plain module-level function"


def test_b7_shared_body_performs_no_seam_lookup():
    """The helper must not name any detector/summarizer itself -- that would be
    an internal table/lookup and would stop the module-level rebinds biting."""
    code = foundry._gather_test_scan.__code__
    referenced = set(code.co_names) | {
        c for c in code.co_consts if isinstance(c, str)
    }
    for seam in DETECTORS + SUMMARIZERS:
        assert seam not in referenced, f"_gather_test_scan names {seam} internally"


@pytest.mark.parametrize("member,det,summ", [(t[0], t[1], t[2]) for t in TRIPLET])
def test_b7_member_passes_seams_as_bare_names(member, det, summ):
    node = _top_level_functions()[member]
    body = _body_without_docstring(node)
    assert len(body) == 1 and isinstance(body[0], ast.Return)
    call = body[0].value
    assert isinstance(call, ast.Call)
    passed = [
        a.id
        for a in list(call.args) + [k.value for k in call.keywords]
        if isinstance(a, ast.Name)
    ]
    assert det in passed, f"{member} does not pass {det} as a bare name"
    assert summ in passed, f"{member} does not pass {summ} as a bare name"
    # nothing may be pre-bound at the call site
    for arg in list(call.args) + [k.value for k in call.keywords]:
        assert not isinstance(
            arg, (ast.Lambda, ast.Subscript)
        ), f"{member} pre-binds a seam at the call site"
        if isinstance(arg, ast.Call):
            assert not (
                isinstance(arg.func, ast.Attribute) and arg.func.attr == "partial"
            ), f"{member} wraps a seam in functools.partial"


# ===========================================================================
# Behavior 8 -- ONE shared body
# ===========================================================================
def test_b8_shared_body_is_a_module_level_function():
    fn = getattr(foundry, "_gather_test_scan", None)
    assert fn is not None and inspect.isfunction(fn)
    assert "_gather_test_scan" in _top_level_functions()


@pytest.mark.parametrize("member", MEMBERS)
def test_b8_member_body_is_one_return_into_the_shared_body(member):
    node = _top_level_functions()[member]
    body = _body_without_docstring(node)
    assert len(body) == 1, f"{member} body has {len(body)} statements, expected 1"
    stmt = body[0]
    assert isinstance(stmt, ast.Return), f"{member}'s only statement is not a return"
    assert isinstance(stmt.value, ast.Call)
    assert isinstance(stmt.value.func, ast.Name)
    assert stmt.value.func.id == "_gather_test_scan"


# ===========================================================================
# Behavior 9 -- byte-identical reports
# ===========================================================================
def _shapes(tmp_path):
    """(label, files, findings_by_path, failing_paths) for four input shapes."""
    p1, p2, p3 = _paths(tmp_path, "test_a.py", "test_b.py", "test_c.py")
    return [
        ("clean", [p1], {}, set()),
        (
            "findings-only",
            [p1, p2],
            {str(p1): ("test_one", "test_two"), str(p2): ("test_three",)},
            set(),
        ),
        ("parse-errors-only", [p1, p2], {}, {str(p1), str(p2)}),
        (
            "mixed",
            [p1, p2, p3],
            {str(p3): ("test_late",)},
            {str(p1)},
        ),
    ]


@pytest.mark.parametrize(
    "member,verb,label,verdict_found",
    [(t[0], t[3], t[4], t[5]) for t in TRIPLET],
)
def test_b9_render_is_byte_identical_to_golden(
    tmp_path, monkeypatch, member, verb, label, verdict_found
):
    cfg = _cfg(tmp_path)
    for shape, files, by_path, failing in _shapes(tmp_path):
        with monkeypatch.context() as mp:

            def fake_tree(path, _failing=failing):
                if str(path) in _failing:
                    raise SyntaxError("golden-boom")
                return ("TREE", str(path))

            calls = []
            mp.setattr(
                foundry,
                "_gather_weak_test_files",
                lambda repo: calls.append(repo) or [],
            )
            mp.setattr(foundry, "test_tree", fake_tree)
            for d in DETECTORS:
                _stub_detector(mp, d, by_path)

            summary = getattr(foundry, member)(cfg, files=files)

            findings = tuple(
                (str(p), n) for p in files for n in by_path.get(str(p), ())
            )
            errors = tuple(
                (str(p), "SyntaxError: golden-boom")
                for p in files
                if str(p) in failing
            )
            expected = _expected_render(
                verb, label, verdict_found, cfg.name, len(files), findings, errors
            )
            got = summary.render()
            assert got == expected, f"{member}/{shape} render drifted:\n{got!r}"

            non_empty = [ln for ln in got.splitlines() if ln.strip()]
            assert non_empty[-1].startswith(
                "verdict:"
            ), f"{member}/{shape} last non-empty line is {non_empty[-1]!r}"
            assert calls == []


@pytest.mark.parametrize("member", MEMBERS)
def test_b9_to_dict_keeps_its_keys(tmp_path, monkeypatch, member):
    cfg = _cfg(tmp_path)
    (p,) = _paths(tmp_path, "test_only.py")
    p.write_text("def test_ok():\n    v = 1\n    assert v == 1\n")
    _no_discovery(monkeypatch)
    d = getattr(foundry, member)(cfg, files=[p]).to_dict()
    assert set(d) == SUMMARY_KEYS, f"{member}.to_dict keys {sorted(d)}"
    assert d["product"] == cfg.name
    assert d["files_scanned"] == 1
    assert d["clean"] is True
    assert d["exit_code"] == 0
    assert d["total_findings"] == 0
    assert d["verdict"] == "clean"
    assert json.dumps(d)  # still JSON-serialisable for the --json verbs


# ===========================================================================
# Behavior 10 -- docstring ownership
# ===========================================================================
@pytest.mark.parametrize("member,det,summ", [(t[0], t[1], t[2]) for t in TRIPLET])
def test_b10_member_keeps_its_own_docstring(member, det, summ):
    doc = getattr(foundry, member).__doc__ or ""
    assert len(doc) >= 400, f"{member} docstring shrank to {len(doc)} chars"
    assert "Behavior" in doc, f"{member} docstring names no numbered Behavior"
    assert det in doc, f"{member} docstring does not name its own detector {det}"
    assert summ in doc, f"{member} docstring does not name its own summarizer"


def test_b10_docstrings_are_pairwise_distinct():
    docs = {m: (getattr(foundry, m).__doc__ or "").strip() for m in MEMBERS}
    assert len(set(docs.values())) == 3, "two members share a docstring"
    helper_doc = (foundry._gather_test_scan.__doc__ or "").strip()
    assert helper_doc, "_gather_test_scan has no docstring of its own"
    assert helper_doc not in docs.values()


# ===========================================================================
# Acceptance-criteria oracles
# ===========================================================================
def test_ac_modules_still_import():
    assert hasattr(foundry, "main")
    assert hasattr(dispatcher, "main")


def test_ac_iter183_roadmap_records_present_once():
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text()
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()
    assert (
        sum(1 for ln in index.splitlines() if ln.startswith("- iter 183 ")) == 1
    ), "the iter-183 ledger row is missing or duplicated in PLATFORM_ROADMAP.md"
    assert (
        sum(1 for ln in archive.splitlines() if ln.startswith("- **iter 183 ")) == 1
    ), "the iter-183 archive bullet is missing or duplicated"
