"""Black-box behaviour tests for iter 338 -- the read-only `foundry dormancy` verb.

The iteration ADOPTS an already-shipped primitive: `symbol_dormancy_class` (iter 326)
gains its first production consumer, a `dormancy --config C --symbol NAME ... [--json]`
verb that classifies named symbols over the product repo's TRACKED tree and returns
0 / 1 / 2 (all wired / >=1 dormant / undecidable).

Spec: products/_platform/state/iter-338/pm.md, Expected Behaviors 1-9.

  1. `dormancy_corpus_split(paths)` -- pure, TOTAL, module-level; repo-relative path
     STRINGS in, a frozen 3-tuple of sorted deduped tuples `(production, tests, prose)`
     out, by exactly three literal rules; three empty tuples for a non-iterable, for an
     all-non-`str` iterable, and for a bare `str` (which iterates characters).
  2. `DormancySummary` -- frozen dataclass, exactly the fields `rows`,
     `production_files`, `test_files`, `prose_files`, `errors`, `exit_code`; `rows` in
     REQUESTED order; `errors` sorted `<path>: <reason>` strings.
  3. `exit_code` derived and fail-CLOSED with precedence 2 > 1 > 0; each arm provable
     alone (no symbols / no production files / any `unparseable` -> 2; any `dormant` -> 1).
  4. `render()` is detail-then-sentinel and `to_dict()` is exactly the field names,
     `json.dumps`-able, with every printed figure equal to the field it came from.
  5. `gather_dormancy(cfg, symbols)` is the SINGLE I/O seam: `run_cmd` for
     `git -C <repo> ls-files`, unreadable files folded into `errors` rather than raised,
     BARE-name calls to `dormancy_corpus_split` and `symbol_dormancy_class`, and a failed
     listing yielding `production_files == 0` / `exit_code == 2` with no traceback.
  6. `dormancy_cli(cfg, symbols, as_json)` routes through the shared `_thin_gather_cli`
     printer; `--json` stdout is exactly ONE `json.dumps(..., indent=2)` document, else
     `render()` byte-for-byte; the return value is `exit_code` in both modes; no writes.
  7. `main(["dormancy", ...])` is registered, `--symbol` is repeatable, the exit code
     matches `dormancy_cli`, omitting `--symbol` fails naming it, `foundry_cli_verbs`
     contains `dormancy` and `readme_verb_index_gaps` over the live README is `ok`.
  8. LIVE-TREE, two-sided, over the checkout resolved at RUNTIME from
     `pathlib.Path(foundry.__file__).parent`: `run_iteration` -> `live`, a symbol name
     ASSEMBLED at runtime -> `dormant`, census non-vacuous.
  9. Adoption bookkeeping: `call_site_count(..., symbol="symbol_dormancy_class") >= 1`,
     iter 326's two dormancy-freezing pins re-pointed to LIVENESS while its RESUME pin
     survives, no `DORMANT:` docstring line, and no control-path file or loop entry
     point names anything new -- so a loop in flight resumes byte-identically.

ISOLATION CONTRACT (HONORED): every assertion was derived from the iteration's PM spec
and from the product's OBSERVABLE surface -- importing the module, CALLING its public
functions, `dataclasses` / `inspect` / `__code__` introspection, driving the CLI
in-process and as a subprocess, and reading files under `tests/` for CONVENTIONS plus
the TRACKED product README. The implementation BODIES of `foundry.py` / `dispatcher.py`,
the engineer's notes, the reviewer's notes, `IMPLEMENTATION.patch` and `git diff` were
NOT read. (Full disclosure: while scripting the Behavior-5 failure arm an early probe
raised `TypeError` from a wrong `CmdResult` keyword, and that traceback surfaced one
call line of `gather_dormancy`; no body was read and no assertion below is keyed to it.)

Behaviours 1-7 run entirely on in-memory strings and a `tmp_path` fixture repo with a
SCRIPTED `run_cmd` seam -- no real git, subprocess, network or clock. Behaviours 8-9
read TRACKED assets located at RUNTIME off `foundry.__file__` (never a source-literal
absolute path, never a gitignored `state/` path, never a count of ambient or untracked
files), so they hold in the throwaway fresh clone the post-release verifier builds.
"""

from __future__ import annotations

import dataclasses
import io
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402


# --------------------------------------------------------------------------
# runtime-built paths (never a source-literal home path) + shared helpers
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
_LIVE_CONFIG = _ROOT / "products" / "_platform" / "config.json"

VERB = "dormancy"
CLASSES = frozenset({"live", "unparseable", "test-only", "prose-only", "dormant"})
FIELDS = ["rows", "production_files", "test_files", "prose_files", "errors",
          "exit_code"]
NEW_SYMBOLS = ("dormancy_corpus_split", "DormancySummary", "gather_dormancy",
               "dormancy_cli")
CONTROL_PATHS = ("dispatcher.py", "watchdog.py", "launch.sh")
LOOP_ENTRY_POINTS = ("run_iteration", "run_stage", "build_prompt")


def _split(arg):
    return foundry.dormancy_corpus_split(arg)


def _summary(**over):
    """Build a DormancySummary from its five INIT fields (exit_code is derived)."""
    kw = dict(rows=(("s", "live"),), production_files=1, test_files=1,
              prose_files=1, errors=())
    kw.update(over)
    return foundry.DormancySummary(**kw)


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY -> (rc, out, err).

    Separate capture matters: Behaviour 6 requires the JSON document to be the
    ENTIRE stdout, so stderr noise must never contaminate the parse.
    """
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    except SystemExit as exc:  # argparse's usage exit is a legitimate outcome
        rc = exc.code
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _fixture_repo(tmp_path, files=None, **over):
    """A tmp_path config + repo dir; returns (config_path, repo_path).

    Mirrors the fixture convention of tests/test_iter323_behavior.py. Nothing
    here is a real git checkout -- Behaviour 5's `run_cmd` seam is scripted.
    """
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    for rel, body in (files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    return cfg_path, repo


def _script_ls_files(monkeypatch, listing, ok=True, sink=None):
    """Replace the `run_cmd` SEAM so no real git ever runs."""
    def fake_run_cmd(args, cwd=None, timeout=600):
        if sink is not None:
            sink.append(list(args))
        return foundry.CmdResult(ok=ok, out=listing)
    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)


def _tree_snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# ==========================================================================
# Behaviour 1 -- the pure, total corpus splitter
# ==========================================================================

def test_b1_the_three_literal_classification_rules_hold():
    prod, tests, prose = _split([
        "foundry.py",                 # .py, not under tests/ -> PRODUCTION
        "scripts/leak_guard.py",      # nested .py -> PRODUCTION
        "tests/test_a.py",            # .py under tests/ -> TESTS
        "tests/deep/test_b.py",       # nested under tests/ -> TESTS
        "conftest.py",                # basename rule at the root -> TESTS
        "pkg/sub/conftest.py",        # basename rule anywhere -> TESTS
        "README.md",                  # not .py -> PROSE
        "tests/fixtures/data.txt",    # under tests/ but not .py -> PROSE
        "launch.sh",                  # not .py -> PROSE
    ])
    assert prod == ("foundry.py", "scripts/leak_guard.py"), prod
    assert tests == ("conftest.py", "pkg/sub/conftest.py", "tests/deep/test_b.py",
                     "tests/test_a.py"), tests
    assert prose == ("README.md", "launch.sh", "tests/fixtures/data.txt"), prose


def test_b1_the_result_is_a_three_tuple_of_sorted_deduped_tuples():
    got = _split(["b.py", "a.py", "b.py", "z.md", "z.md", "tests/t.py", "tests/t.py"])
    assert isinstance(got, tuple) and len(got) == 3, got
    for part in got:
        assert isinstance(part, tuple), type(part).__name__
        assert list(part) == sorted(part), part
        assert len(part) == len(set(part)), f"duplicates survived: {part}"
    assert got == (("a.py", "b.py"), ("tests/t.py",), ("z.md",)), got


def test_b1_totality_non_iterable_all_non_str_and_bare_str_give_three_empties():
    empty = ((), (), ())
    for bad in (None, 7, 3.5, object(), True):
        assert _split(bad) == empty, f"non-iterable {bad!r} must be total"
    assert _split([1, 2, None, object()]) == empty, "all-non-str members"
    # A bare `str` iterates its CHARACTERS, so it must yield three empties
    # rather than a partial answer that silently classified letters.
    assert _split("foundry.py") == empty, "a bare str must not be walked as paths"
    assert _split("") == empty
    assert _split([]) == empty
    assert _split(()) == empty


def test_b1_is_pure_deterministic_and_touches_no_io_seam(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("the splitter must perform NO I/O")
    monkeypatch.setattr(foundry, "run_cmd", explode)
    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(pathlib.Path, "read_text", explode)
    paths = ["no/such/file.py", "tests/also_absent.py", "gone.md"]
    first = _split(paths)
    assert first == (("no/such/file.py",), ("tests/also_absent.py",), ("gone.md",))
    assert _split(list(paths)) == first, "equal inputs must give == results"
    assert _split(iter(paths)) == first, "any iterable of str is accepted"


def test_b1_is_a_module_level_function_not_a_method_or_partial():
    fn = foundry.dormancy_corpus_split
    assert callable(fn), "dormancy_corpus_split must be callable"
    assert getattr(fn, "__module__", None) == "foundry", getattr(fn, "__module__", None)
    assert getattr(fn, "__qualname__", "") == "dormancy_corpus_split", fn.__qualname__


# ==========================================================================
# Behaviour 2 -- the frozen summary dataclass
# ==========================================================================

def test_b2_the_summary_is_a_frozen_dataclass_with_exactly_the_named_fields():
    s = _summary()
    assert dataclasses.is_dataclass(s), "DormancySummary must be a dataclass"
    assert [f.name for f in dataclasses.fields(s)] == FIELDS, \
        [f.name for f in dataclasses.fields(s)]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.production_files = 99
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.rows = ()


def test_b2_exit_code_is_derived_not_supplied_by_the_caller():
    """`exit_code` is a FIELD (Behaviour 2) that is DERIVED (Behaviour 3), so it
    must not be an init parameter -- a caller cannot contradict the census."""
    by_name = {f.name: f for f in dataclasses.fields(foundry.DormancySummary)}
    assert by_name["exit_code"].init is False, \
        "exit_code must be init=False so it cannot be forged by a caller"
    with pytest.raises(TypeError):
        foundry.DormancySummary(rows=(), production_files=1, test_files=0,
                                prose_files=0, errors=(), exit_code=0)


def test_b2_rows_are_symbol_class_pairs_in_the_order_requested(tmp_path,
                                                              monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"m.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "m.py\n")
    cfg = foundry.load_config(str(cfg_path))
    asked = ["zeta", "alpha", "mid"]
    s = foundry.gather_dormancy(cfg, asked)
    assert [r[0] for r in s.rows] == asked, \
        f"row order must follow the REQUEST, not sorting: {s.rows}"
    for sym, cls in s.rows:
        assert isinstance(sym, str) and isinstance(cls, str), (sym, cls)
        assert cls in CLASSES, f"{sym} got a non-class word {cls!r}"


def test_b2_errors_are_a_sorted_tuple_of_path_colon_reason_strings(tmp_path,
                                                                  monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"real.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "real.py\n")
    monkeypatch.setattr(
        foundry, "dormancy_corpus_split",
        lambda paths: (("zz_missing.py", "aa_missing.py", "real.py"), (), ()))
    cfg = foundry.load_config(str(cfg_path))
    s = foundry.gather_dormancy(cfg, ["x"])
    assert isinstance(s.errors, tuple), type(s.errors).__name__
    assert len(s.errors) == 2, s.errors
    assert list(s.errors) == sorted(s.errors), f"errors must be sorted: {s.errors}"
    for entry in s.errors:
        assert isinstance(entry, str) and ": " in entry, entry
        assert entry.split(": ", 1)[0].endswith("_missing.py"), entry
    assert s.production_files == 1, \
        f"only the READABLE production file is counted: {s.production_files}"


# ==========================================================================
# Behaviour 3 -- the derived, fail-CLOSED exit code (each arm alone)
# ==========================================================================

def test_b3_arm_zero_symbols_requested_is_undecidable():
    assert _summary(rows=(), production_files=9).exit_code == 2


def test_b3_arm_no_production_files_is_undecidable():
    assert _summary(rows=(("s", "live"),), production_files=0).exit_code == 2


def test_b3_arm_an_unparseable_row_is_undecidable():
    assert _summary(rows=(("s", "unparseable"),), production_files=9).exit_code == 2


def test_b3_arm_a_dormant_row_alone_is_one():
    assert _summary(rows=(("s", "dormant"),), production_files=9).exit_code == 1


def test_b3_arm_everything_wired_is_zero():
    for cls in ("live", "test-only", "prose-only"):
        assert _summary(rows=(("s", cls),), production_files=9).exit_code == 0, cls


def test_b3_precedence_is_two_over_one_over_zero():
    both = _summary(rows=(("a", "dormant"), ("b", "unparseable")), production_files=9)
    assert both.exit_code == 2, \
        "an unparseable row can never be reported as a clean or merely-dormant census"
    mixed = _summary(rows=(("a", "live"), ("b", "dormant")), production_files=9)
    assert mixed.exit_code == 1
    clean = _summary(rows=(("a", "live"), ("b", "live")), production_files=9)
    assert clean.exit_code == 0
    starved = _summary(rows=(("a", "dormant"),), production_files=0)
    assert starved.exit_code == 2, "no production corpus outranks a dormant finding"


# ==========================================================================
# Behaviour 4 -- detail-then-sentinel render + to_dict parity
# ==========================================================================

def test_b4_render_is_detail_then_sentinel_and_the_last_line_is_the_sentinel():
    s = _summary(rows=(("a", "live"), ("b", "dormant")), production_files=3,
                 test_files=4, prose_files=5, errors=("p.py: OSError",))
    lines = s.render().splitlines()
    assert lines[0] == "a: live", lines
    assert lines[1] == "b: dormant", lines
    assert lines[2] == "corpus: 3 production, 4 test, 5 prose file(s)", lines
    assert lines[3] == "p.py: OSError", lines
    non_empty = [ln for ln in lines if ln.strip()]
    assert non_empty[-1] == "dormancy: 2 symbol(s), 1 dormant, exit 1", non_empty[-1]
    # 2 row lines + 1 corpus line + 1 error line + 1 sentinel line
    assert len(non_empty) == 2 + 1 + 1 + 1, non_empty


def test_b4_every_printed_figure_equals_the_field_it_came_from():
    s = _summary(rows=(("a", "live"), ("b", "dormant"), ("c", "dormant")),
                 production_files=11, test_files=22, prose_files=33, errors=())
    lines = [ln for ln in s.render().splitlines() if ln.strip()]
    corpus = [ln for ln in lines if ln.startswith("corpus: ")][0]
    assert corpus == (f"corpus: {s.production_files} production, {s.test_files} test, "
                      f"{s.prose_files} prose file(s)"), corpus
    dormant = sum(1 for _, cls in s.rows if cls == "dormant")
    assert lines[-1] == (f"dormancy: {len(s.rows)} symbol(s), {dormant} dormant, "
                         f"exit {s.exit_code}"), lines[-1]
    assert dormant == 2 and s.exit_code == 1, (dormant, s.exit_code)


def test_b4_to_dict_is_exactly_the_field_names_and_json_dumpable():
    s = _summary(rows=(("a", "live"),), production_files=2, test_files=3,
                 prose_files=4, errors=("x.py: OSError",))
    d = s.to_dict()
    assert isinstance(d, dict), type(d).__name__
    assert list(d.keys()) == FIELDS, list(d.keys())
    # `to_dict` is a JSON view, so a tuple field legitimately arrives as a list;
    # compare after the same normalisation `json.dumps` would apply.
    def _plain(value):
        if isinstance(value, (list, tuple)):
            return [_plain(v) for v in value]
        return value

    for name in FIELDS:
        assert _plain(d[name]) == _plain(getattr(s, name)), \
            f"{name}: {d[name]!r} vs {getattr(s, name)!r}"
    reloaded = json.loads(json.dumps(d, indent=2))
    assert list(reloaded.keys()) == FIELDS, list(reloaded.keys())
    assert reloaded["exit_code"] == s.exit_code == 0, reloaded["exit_code"]
    assert reloaded["rows"] == [["a", "live"]], reloaded["rows"]


def test_b4_a_zero_row_render_still_ends_in_the_sentinel():
    s = _summary(rows=(), production_files=0, test_files=0, prose_files=0, errors=())
    lines = [ln for ln in s.render().splitlines() if ln.strip()]
    assert lines[-1] == "dormancy: 0 symbol(s), 0 dormant, exit 2", lines


# ==========================================================================
# Behaviour 5 -- gather_dormancy is the SINGLE I/O seam
# ==========================================================================

def test_b5_the_tracked_tree_is_listed_through_run_cmd_with_git_ls_files(tmp_path,
                                                                        monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"m.py": "def f():\n    pass\n"})
    seen = []
    _script_ls_files(monkeypatch, "m.py\n", sink=seen)
    cfg = foundry.load_config(str(cfg_path))
    foundry.gather_dormancy(cfg, ["f"])
    assert len(seen) == 1, f"exactly one listing command expected: {seen}"
    args = seen[0]
    assert args[:2] == ["git", "-C"], args
    assert args[2] == str(cfg.repo), args
    assert args[3] == "ls-files", args


def test_b5_a_failed_listing_yields_zero_production_files_and_exit_two(tmp_path,
                                                                      monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"m.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "", ok=False)
    cfg = foundry.load_config(str(cfg_path))
    s = foundry.gather_dormancy(cfg, ["anything"])   # must NOT raise
    assert s.production_files == 0, s.production_files
    assert s.test_files == 0 and s.prose_files == 0, (s.test_files, s.prose_files)
    assert s.exit_code == 2, s.exit_code
    assert s.errors, "a failed listing must be REPORTED, not silently empty"
    assert any("ls-files" in e for e in s.errors), s.errors


def test_b5_an_unreadable_file_is_folded_into_errors_rather_than_raised(tmp_path,
                                                                       monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"good.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "good.py\nvanished.py\nalso_gone.md\n")
    cfg = foundry.load_config(str(cfg_path))
    s = foundry.gather_dormancy(cfg, ["x"])          # must NOT raise
    assert s.production_files == 1, s.production_files
    assert len(s.errors) == 2, s.errors
    assert {e.split(": ", 1)[0] for e in s.errors} == {"vanished.py", "also_gone.md"}, \
        s.errors


def test_b5_the_splitter_is_called_by_bare_name_so_monkeypatch_bites(tmp_path,
                                                                    monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {
        "p.py": "x = 1\n", "tests/t.py": "y = 1\n", "R.md": "prose\n"})
    _script_ls_files(monkeypatch, "p.py\ntests/t.py\nR.md\n")
    cfg = foundry.load_config(str(cfg_path))
    real = foundry.gather_dormancy(cfg, ["x"])
    assert (real.production_files, real.test_files, real.prose_files) == (1, 1, 1), \
        (real.production_files, real.test_files, real.prose_files)
    handed = []

    def fake_split(paths):
        handed.append(sorted(paths))
        return (("p.py",), ("tests/t.py", "R.md"), ())

    monkeypatch.setattr(foundry, "dormancy_corpus_split", fake_split)
    patched = foundry.gather_dormancy(cfg, ["x"])
    assert handed == [["R.md", "p.py", "tests/t.py"]], \
        f"the seam must be handed the ls-files LINES: {handed}"
    assert (patched.production_files, patched.test_files, patched.prose_files) \
        == (1, 2, 0), "monkeypatching dormancy_corpus_split did not take effect"


def test_b5_the_classifier_is_called_by_bare_name_so_monkeypatch_bites(tmp_path,
                                                                      monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    calls = []

    def fake_class(**kwargs):
        calls.append(kwargs.get("symbol"))
        return "dormant"

    monkeypatch.setattr(foundry, "symbol_dormancy_class", fake_class)
    s = foundry.gather_dormancy(cfg, ["one", "two"])
    assert calls == ["one", "two"], \
        f"monkeypatching symbol_dormancy_class did not take effect: {calls}"
    assert s.rows == (("one", "dormant"), ("two", "dormant")), s.rows
    assert s.exit_code == 1, s.exit_code


def test_b5_zero_symbols_still_takes_the_census_and_reports_undecidable(tmp_path,
                                                                       monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    for symbols in (None, [], ()):
        s = foundry.gather_dormancy(cfg, symbols)
        assert s.rows == (), s.rows
        assert s.exit_code == 2, f"{symbols!r} -> {s.exit_code}"


def test_b5_gather_writes_nothing_to_disk(tmp_path, monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    before = _tree_snapshot(tmp_path)
    foundry.gather_dormancy(cfg, ["x"])
    assert _tree_snapshot(tmp_path) == before, "gather_dormancy must be read-only"


# ==========================================================================
# Behaviour 6 -- dormancy_cli routes through the shared thin printer
# ==========================================================================

def test_b6_the_cli_delegates_to_the_shared_thin_gather_printer(tmp_path,
                                                               monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    cfg = foundry.load_config(str(cfg_path))
    assert hasattr(foundry, "_thin_gather_cli"), \
        "the shared thin printer must still exist"
    seen = []

    def fake_thin(gather, cfg_arg, arg, as_json):
        seen.append((getattr(gather, "__name__", gather), arg, as_json))
        return 77

    monkeypatch.setattr(foundry, "_thin_gather_cli", fake_thin)
    rc = foundry.dormancy_cli(cfg, ["a"], True)
    assert rc == 77, "dormancy_cli did not route through _thin_gather_cli"
    assert seen == [("gather_dormancy", ["a"], True)], seen


def test_b6_json_mode_stdout_is_exactly_one_indent_two_document(tmp_path,
                                                               monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "def live():\n    live()\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    expected = foundry.gather_dormancy(cfg, ["live", "absent_one"])
    rc, out, err = _capture(lambda: foundry.dormancy_cli(cfg, ["live", "absent_one"],
                                                         True))
    assert out == json.dumps(expected.to_dict(), indent=2) + "\n", repr(out[:300])
    doc = json.loads(out)
    assert list(doc.keys()) == FIELDS, list(doc.keys())
    assert rc == expected.exit_code, (rc, expected.exit_code)


def test_b6_text_mode_stdout_is_render_byte_for_byte(tmp_path, monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "def live():\n    live()\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    expected = foundry.gather_dormancy(cfg, ["live"])
    rc, out, err = _capture(lambda: foundry.dormancy_cli(cfg, ["live"], False))
    assert out == expected.render() + "\n", repr(out)
    assert rc == expected.exit_code, (rc, expected.exit_code)


def test_b6_the_return_value_is_the_exit_code_in_both_modes(tmp_path, monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    monkeypatch.setattr(foundry, "symbol_dormancy_class", lambda **k: "dormant")
    for as_json in (False, True):
        rc, out, err = _capture(lambda: foundry.dormancy_cli(cfg, ["s"], as_json))
        assert rc == 1, f"as_json={as_json} -> {rc}"
    monkeypatch.setattr(foundry, "symbol_dormancy_class", lambda **k: "unparseable")
    for as_json in (False, True):
        rc, out, err = _capture(lambda: foundry.dormancy_cli(cfg, ["s"], as_json))
        assert rc == 2, f"as_json={as_json} -> {rc}"


def test_b6_the_cli_writes_nothing_to_disk(tmp_path, monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    before = _tree_snapshot(tmp_path)
    _capture(lambda: foundry.dormancy_cli(cfg, ["x"], False))
    _capture(lambda: foundry.dormancy_cli(cfg, ["x"], True))
    assert _tree_snapshot(tmp_path) == before, "dormancy_cli must be read-only"


def test_b6_default_arguments_are_offline_safe(tmp_path, monkeypatch):
    """`symbols=None, as_json=False` is the documented default signature."""
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    rc, out, err = _capture(lambda: foundry.dormancy_cli(cfg))
    assert rc == 2, rc
    assert out.strip().splitlines()[-1] == "dormancy: 0 symbol(s), 0 dormant, exit 2", \
        out


# ==========================================================================
# Behaviour 7 -- argparse registration + doc index
# ==========================================================================

def test_b7_main_accepts_repeated_symbol_flags_and_returns_the_cli_code(tmp_path,
                                                                       monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "def live():\n    live()\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    argv = [VERB, "--config", str(cfg_path), "--symbol", "live",
            "--symbol", "absent_two", "--json"]
    rc, out, err = _capture(lambda: foundry.main(argv))
    doc = json.loads(out)
    assert [r[0] for r in doc["rows"]] == ["live", "absent_two"], doc["rows"]
    expected = foundry.gather_dormancy(cfg, ["live", "absent_two"])
    assert rc == expected.exit_code, (rc, expected.exit_code)
    assert doc["exit_code"] == rc, (doc["exit_code"], rc)


def test_b7_omitting_symbol_fails_and_names_the_flag(tmp_path):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    rc, out, err = _capture(lambda: foundry.main([VERB, "--config", str(cfg_path)]))
    assert rc not in (0, None), f"a symbol-less invocation must fail, got {rc!r}"
    assert "--symbol" in (out + err), (out, err)


def test_b7_the_verb_census_and_the_readme_index_both_know_the_verb():
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    verbs = foundry.foundry_cli_verbs(src)
    assert VERB in verbs, f"{VERB} missing from the verb census: {len(verbs)} verbs"
    audit = foundry.readme_verb_index_gaps(
        (_ROOT / "README.md").read_text(encoding="utf-8"), verbs)
    assert audit.ok, (audit.missing_verbs, audit.sections_without_invocation,
                      audit.unknown_invocations)


def test_b7_the_readme_carries_a_numbered_section_invoking_the_verb():
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"foundry.py {VERB}" in readme, \
        "README must show the real invocation of the new verb"
    assert "--symbol" in readme, "README must document the repeatable flag"


# ==========================================================================
# Behaviour 8 -- LIVE-TREE, two-sided, over the checkout found at RUNTIME
# ==========================================================================

def _absent_symbol_name():
    """ASSEMBLE the probe name so this file cannot contain it verbatim and be
    found by the very census it is testing (iteration 154's self-hit trap)."""
    return "_".join(("zzz", "no", "such", "platform", "symbol")) + "_338"


def test_b8_the_live_tree_census_is_two_sided_and_non_vacuous():
    if not _LIVE_CONFIG.exists():
        pytest.skip("live product config absent")
    cfg = foundry.load_config(str(_LIVE_CONFIG))
    absent = _absent_symbol_name()
    assert absent not in pathlib.Path(__file__).read_text(encoding="utf-8"), \
        "the probe name must not appear verbatim in this file"
    s = foundry.gather_dormancy(cfg, ["run_iteration", absent])
    by_symbol = dict(s.rows)
    assert by_symbol["run_iteration"] == "live", \
        f"the loop entry point must classify live, got {by_symbol['run_iteration']}"
    assert by_symbol[absent] == "dormant", \
        f"an absent symbol must classify dormant, got {by_symbol[absent]}"
    assert s.production_files >= 3, \
        f"census is vacuous: {s.production_files} production file(s)"
    assert s.test_files >= 50, f"census is vacuous: {s.test_files} test file(s)"
    assert s.exit_code == 1, "one dormant row and no unparseable row -> exit 1"


def test_b8_the_adopted_classifier_reports_itself_live_on_the_live_tree():
    if not _LIVE_CONFIG.exists():
        pytest.skip("live product config absent")
    cfg = foundry.load_config(str(_LIVE_CONFIG))
    s = foundry.gather_dormancy(cfg, ["symbol_dormancy_class"])
    assert s.rows == (("symbol_dormancy_class", "live"),), s.rows
    assert s.exit_code == 0, s.exit_code


def test_ac_the_live_verb_runs_as_a_subprocess_with_the_documented_codes():
    if not _LIVE_CONFIG.exists():
        pytest.skip("live product config absent")
    rel_cfg = str(_LIVE_CONFIG.relative_to(_ROOT))
    base = [sys.executable, "foundry.py", VERB, "--config", rel_cfg]
    wired = subprocess.run(base + ["--symbol", "symbol_dormancy_class"],
                           cwd=str(_ROOT), capture_output=True, text=True,
                           timeout=180)
    assert wired.returncode == 0, (wired.returncode, wired.stdout, wired.stderr)
    assert "symbol_dormancy_class: live" in wired.stdout, wired.stdout
    absent = subprocess.run(base + ["--symbol", _absent_symbol_name()],
                            cwd=str(_ROOT), capture_output=True, text=True,
                            timeout=180)
    assert absent.returncode == 1, (absent.returncode, absent.stdout, absent.stderr)
    assert "dormant" in absent.stdout, absent.stdout
    as_json = subprocess.run(base + ["--symbol", "run_iteration", "--json"],
                             cwd=str(_ROOT), capture_output=True, text=True,
                             timeout=180)
    assert as_json.returncode == 0, (as_json.returncode, as_json.stderr)
    assert list(json.loads(as_json.stdout).keys()) == FIELDS, as_json.stdout


def test_ac_the_two_control_modules_still_import():
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (r.returncode, r.stderr)


# ==========================================================================
# Behaviour 9 -- adoption bookkeeping + resume safety
# ==========================================================================

def test_b9_the_classifier_now_has_at_least_one_production_call_site():
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    n = foundry.call_site_count(src, symbol="symbol_dormancy_class")
    assert n is not None, "call_site_count must parse the shipped module"
    assert n >= 1, f"the adopted primitive must be CALLED in production, got {n}"


def test_b9_the_classifier_docstring_no_longer_declares_itself_dormant():
    doc = foundry.symbol_dormancy_class.__doc__ or ""
    assert doc.strip(), "the classifier must keep a docstring"
    assert "DORMANT:" not in doc, \
        "the DORMANT: docstring line must be replaced once the symbol is wired"


def test_b9_iter326s_two_dormancy_pins_are_re_pointed_to_liveness():
    body = (pathlib.Path(__file__).resolve().parent
            / "test_iter326_behavior.py").read_text(encoding="utf-8")
    assert "def test_b9_the_new_function_has_zero_call_sites_in_foundry(" not in body, \
        "the zero-call-site pin must not survive adoption"
    assert 'def test_b9_the_dormancy_oracle_agrees_that_it_is_itself_not_' \
        'production_wired(' not in body, \
        "the not-production-wired pin must not survive adoption"
    for needle in ("is_now_production_wired", "is_itself_production_wired"):
        assert needle in body, f"expected a re-pointed liveness pin naming {needle}"


def test_b9_iter326s_resume_pin_survives_untouched():
    """The third member of that group is about RESUME, not adoption: a new verb
    inside foundry.py changes no control path, so it must stay green AND stay."""
    body = (pathlib.Path(__file__).resolve().parent
            / "test_iter326_behavior.py").read_text(encoding="utf-8")
    assert "def test_b9_the_new_function_is_named_in_no_control_path_file(" in body, \
        "the resume pin must not be collateral damage of the re-point"


def test_b9_no_control_path_file_names_any_new_symbol():
    for rel in CONTROL_PATHS:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        hits = [name for name in NEW_SYMBOLS if name in text]
        assert hits == [], f"{rel} must name nothing new, found {hits}"
    cards = sorted((_ROOT / "roles").glob("*.md"))
    assert len(cards) >= 5, f"expected the role-card set, found {len(cards)}"
    for card in cards:
        text = card.read_text(encoding="utf-8")
        hits = [name for name in NEW_SYMBOLS if name in text]
        assert hits == [], f"roles/{card.name} must name nothing new, found {hits}"


def test_b9_the_loop_entry_points_call_nothing_new():
    for entry in LOOP_ENTRY_POINTS:
        fn = getattr(foundry, entry, None)
        assert fn is not None and hasattr(fn, "__code__"), entry
        names = set(fn.__code__.co_names) | set(fn.__code__.co_consts_names) \
            if hasattr(fn.__code__, "co_consts_names") else set(fn.__code__.co_names)
        hits = sorted(set(NEW_SYMBOLS) & names)
        assert hits == [], f"{entry} must not reference {hits} -- resume safety"


def test_b9_the_verb_is_report_only_and_adds_no_config_field(tmp_path, monkeypatch):
    """Out of Scope: no suite brake FAILS on a dormant symbol, and no new config
    field is owed -- a config lacking any dormancy key must drive the verb."""
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert not [k for k in raw if VERB in k], \
        f"the fixture config declares no dormancy key: {sorted(raw)}"
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    monkeypatch.setattr(foundry, "symbol_dormancy_class", lambda **k: "dormant")
    s = foundry.gather_dormancy(cfg, ["s"])          # reports; must not raise
    assert s.exit_code == 1 and s.rows == (("s", "dormant"),), (s.exit_code, s.rows)


def test_ac_both_roadmap_records_name_this_iteration():
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert "- iter 338 " in index, "the ledger index row is owed in the SAME commit"
    assert "- **iter 338 " in archive, "the archive detail bullet is owed too"
    row = [ln for ln in index.splitlines() if ln.startswith("- iter 338 ")][0]
    assert len(row) <= 120, f"index row is {len(row)} chars: {row}"


# ==========================================================================
# ROUND 2 EXTENSIONS -- round 1 was cut at the per-stage cap; these close the
# gaps its 48 tests left against the same Expected Behaviors (no new spec).
# ==========================================================================

def test_b5_the_single_seam_means_no_real_subprocess_is_ever_launched(tmp_path,
                                                                     monkeypatch):
    """Behaviour 5: `run_cmd` is the SINGLE I/O seam, so with `subprocess.run`
    and `subprocess.Popen` both booby-trapped the gather must still succeed."""
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "def live():\n    live()\n"})
    cfg = foundry.load_config(str(cfg_path))
    _script_ls_files(monkeypatch, "p.py\n")

    def explode(*a, **k):
        raise AssertionError("gather_dormancy must not bypass the run_cmd seam")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    s = foundry.gather_dormancy(cfg, ["live"])
    assert s.production_files == 1, s.production_files
    assert [r[0] for r in s.rows] == ["live"], s.rows


def test_b5_the_listing_is_split_on_LINES_so_a_spaced_path_stays_one_file(tmp_path,
                                                                         monkeypatch):
    """Behaviour 5 says the input is the LINES of `git ls-files`. A path holding a
    space must therefore count as ONE prose file and raise no read error."""
    assert _split(["docs/my file.md"]) == ((), (), ("docs/my file.md",))
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n",
                                              "docs/my file.md": "prose\n"})
    _script_ls_files(monkeypatch, "p.py\ndocs/my file.md\n")
    cfg = foundry.load_config(str(cfg_path))
    s = foundry.gather_dormancy(cfg, ["x"])
    assert (s.production_files, s.prose_files) == (1, 1), \
        (s.production_files, s.test_files, s.prose_files)
    assert s.errors == (), f"a spaced path was mis-split: {s.errors}"


def test_b4_every_errors_member_gets_its_own_line_in_field_order():
    """Behaviour 4: ONE line per `errors` member, between the corpus line and the
    sentinel, in the order the field itself reports."""
    s = _summary(rows=(("a", "live"),), production_files=2, test_files=1,
                 prose_files=1,
                 errors=("a.py: UnicodeDecodeError", "b.py: OSError",
                         "c/d.md: OSError"))
    lines = [ln for ln in s.render().splitlines() if ln.strip()]
    assert lines[0] == "a: live", lines
    assert lines[1].startswith("corpus: "), lines
    assert lines[2:-1] == list(s.errors), (lines[2:-1], s.errors)
    assert lines[-1] == "dormancy: 1 symbol(s), 0 dormant, exit 0", lines[-1]


def test_b2_the_count_fields_are_plain_ints_and_the_sequences_are_tuples(tmp_path,
                                                                        monkeypatch):
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    s = foundry.gather_dormancy(cfg, ["x"])
    for name in ("production_files", "test_files", "prose_files", "exit_code"):
        value = getattr(s, name)
        assert isinstance(value, int) and not isinstance(value, bool), \
            f"{name} is {type(value).__name__}"
    assert isinstance(s.rows, tuple) and isinstance(s.errors, tuple), \
        (type(s.rows).__name__, type(s.errors).__name__)
    for row in s.rows:
        assert isinstance(row, tuple) and len(row) == 2, row


def test_b7_main_in_text_mode_prints_render_and_ends_in_the_sentinel(tmp_path,
                                                                    monkeypatch):
    """Behaviour 6+7 through the registered verb: no `--json` means `render()`
    byte-for-byte on stdout and the same exit code."""
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "def live():\n    live()\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    cfg = foundry.load_config(str(cfg_path))
    expected = foundry.gather_dormancy(cfg, ["live"])
    rc, out, err = _capture(lambda: foundry.main(
        [VERB, "--config", str(cfg_path), "--symbol", "live"]))
    assert out == expected.render() + "\n", repr(out)
    assert [ln for ln in out.splitlines() if ln.strip()][-1] \
        == f"dormancy: 1 symbol(s), {sum(1 for _, c in expected.rows if c == 'dormant')}" \
           f" dormant, exit {expected.exit_code}", out
    assert rc == expected.exit_code, (rc, expected.exit_code)


def test_b7_main_propagates_the_fail_closed_undecidable_arm(tmp_path, monkeypatch):
    """Behaviour 3's fail-CLOSED precedence must survive the whole CLI path: an
    `unparseable` row reaches the caller as exit 2, never as a clean census."""
    cfg_path, repo = _fixture_repo(tmp_path, {"p.py": "x = 1\n"})
    _script_ls_files(monkeypatch, "p.py\n")
    monkeypatch.setattr(foundry, "symbol_dormancy_class", lambda **k: "unparseable")
    rc, out, err = _capture(lambda: foundry.main(
        [VERB, "--config", str(cfg_path), "--symbol", "s"]))
    assert rc == 2, (rc, out, err)
    assert [ln for ln in out.splitlines() if ln.strip()][-1] \
        == "dormancy: 1 symbol(s), 0 dormant, exit 2", out


def test_b7_the_verb_is_listed_in_the_top_level_help():
    rc, out, err = _capture(lambda: foundry.main(["--help"]))
    assert rc in (0, None), rc
    assert VERB in (out + err), "the registered verb must appear in --help"
