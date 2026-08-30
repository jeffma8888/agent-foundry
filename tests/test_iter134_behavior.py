"""Black-box behaviour tests for iter 134 -- `foundry lint-config` reports a typo'd
product-config KEY as a structured error-level finding on the NORMAL lint report
with exit 1, instead of collapsing it into the "cannot read config" exit-2 path.

Spec: products/_platform/state/iter-134/pm.md, Expected Behaviors 1-10.

  1.  `config_key_findings(raw)` -> one error-level finding per unknown key, the
      offending KEY in the machine-readable `field` slot and the
      `suggest_config_key` hint inside `detail`
  2.  deterministic + ascending-sorted + pure: `_`-prefixed comment keys exempt,
      an all-valid mapping returns `()`, the input is not mutated, and no file is
      read or written (proved by recursive code-object introspection, not by the
      docstring)
  3.  honest no-suggestion case -- no bogus `did you mean` clause is invented
  4.  human report exits 1 (NOT 2), keeps the `foundry lint-config` header and a
      last non-empty line of exactly `verdict: PROBLEMS`
  5.  `--json` emits the NORMAL findings document: exactly one parseable doc, the
      seven top-level keys in order, and finding dicts still pinned to exactly
      three keys (the `ConfigFinding` schema is UNCHANGED)
  6.  the exit-2 contract is preserved exactly for a MISSING file and for
      invalid JSON, in both the human and the `--json` shape
  7.  `main()` routing unchanged -- no new subcommand, no new flag
  8.  fail-safe: the new path is reached through a BARE-NAME seam, and with that
      seam returning `()` or RAISING the verb degrades to the historical exit-2
      message and raises nothing
  9.  the fail-closed parser is untouched: `load_config` on the same typo'd file
      still raises `ConfigKeyError`, and a VALID config still exits 0 / `verdict: OK`
  10. still read-only: linting a typo'd config writes nothing into the repo tree
  Plus Acceptance-Criteria oracles: the new function is module-level with a
  docstring naming its inputs / ordering guarantee / purity, `ConfigFinding` and
  `ConfigLint` keep exactly their declared fields, and both modules still import.

ISOLATION CONTRACT (HONORED): written from the iter-134 PM spec and from the
OBSERVABLE surface of the modules under test -- importing them, CALLING the public
functions, capturing stdout/stderr, reading `__doc__`, and runtime introspection of
code objects. The implementation BODIES of foundry.py / dispatcher.py, the
engineer's notes (engineer.md), the reviewer's notes (reviewer.md) and `git diff`
were NOT read; this file reads no source text of either module.

Offline and deterministic: every config is written into pytest's `tmp_path`, every
config's `work_root` is redirected under `tmp_path` so the loader's own mkdir can
never touch the product repo, and there is no network, no git and no subprocess.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import foundry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

JSON_TOP_KEYS = ("config_path", "findings", "n_errors", "n_warnings",
                 "ok", "verdict", "exit_code")
FINDING_KEYS = ("field", "level", "detail")
ERROR_JSON_KEYS = ("config_path", "error", "exit_code")
CANNOT_READ = "lint-config: cannot read config"
UNKNOWN_PREFIX = "unknown config key"

# names that would mean the "pure" helper touched the filesystem or the network
IO_NAMES = frozenset({
    "open", "read_text", "write_text", "read_bytes", "write_bytes", "Path",
    "mkdir", "unlink", "remove", "rename", "load_config", "json", "loads",
    "dump", "dumps", "subprocess", "run", "check_output", "Popen", "urlopen",
    "socket", "requests", "print", "input", "os", "shutil", "glob",
})


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _valid_data(tmp_path):
    """A raw config MAPPING whose every key is a real `ProductConfig` field and
    whose every referenced path exists inside tmp_path, so it lints clean. The
    `work_root` deliberately points under tmp_path: the loader creates that
    directory, and this keeps that write out of the product repo."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    vision = tmp_path / "VISION.md"
    vision.write_text("intent")
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("roadmap")
    qref = tmp_path / "qref"
    qref.mkdir(exist_ok=True)
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    return dict(
        name="prod",
        repo=str(repo),
        allowed_push_repo="prod",
        branch="main",
        vision=str(vision),
        roadmap=str(roadmap),
        quality_ref=str(qref),
        roles_dir=str(roles),
        work_root=str(tmp_path / "work"),
        test_cmd="uv run pytest",
        push_enabled=True,
    )


def _typo_data(tmp_path):
    """The same valid config with `push_enabled` misspelled `push_enable`."""
    data = _valid_data(tmp_path)
    data["push_enable"] = data.pop("push_enabled")
    return data


def _write(tmp_path, data, fname="config.json"):
    p = tmp_path / fname
    p.write_text(json.dumps(data))
    return str(p)


def _capture(fn):
    """Run fn() with stdout and stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters for `--json`: the document must be the ENTIRE stdout,
    uncontaminated by any human-facing message."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _last_nonempty(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _all_code_names(code, seen=None):
    """Every name referenced by a code object AND by its nested code objects.
    The nested walk matters: a comprehension or genexp lives in its own code
    object, so a shallow `co_names` read can miss the interesting call."""
    if seen is None:
        seen = set()
    seen.update(code.co_names)
    for const in code.co_consts:
        if hasattr(const, "co_names"):
            _all_code_names(const, seen)
    return seen


def _finding_fields(findings):
    return tuple(f.field for f in findings)


# --------------------------------------------------------------------------
# Behavior 1 -- the new pure helper names the offending key
# --------------------------------------------------------------------------
def test_b1_helper_exists_at_module_level_and_is_callable():
    assert callable(getattr(foundry, "config_key_findings", None)), \
        "config_key_findings must be a module-level function on foundry"


def test_b1_single_typo_yields_one_error_finding_naming_the_key():
    findings = foundry.config_key_findings({"name": "x", "push_enable": True})
    assert isinstance(findings, tuple), "must return a tuple, not a list"
    assert len(findings) == 1, f"expected exactly 1 finding, got {findings!r}"
    only = findings[0]
    assert only.field == "push_enable", \
        "the offending KEY belongs in the machine-readable `field` slot"
    assert only.level == "error"
    assert only.detail.startswith(UNKNOWN_PREFIX), \
        f"detail must start with {UNKNOWN_PREFIX!r}, got {only.detail!r}"
    assert "push_enabled" in only.detail, \
        "the suggest_config_key hint must reach the operator through `detail`"


def test_b1_findings_are_the_unchanged_ConfigFinding_type():
    findings = foundry.config_key_findings({"push_enable": True})
    assert isinstance(findings[0], foundry.ConfigFinding)
    assert tuple(f.name for f in dataclasses.fields(foundry.ConfigFinding)) == FINDING_KEYS


def test_b1_one_finding_per_offending_key():
    findings = foundry.config_key_findings(
        {"name": "x", "push_enable": True, "brnach": "main", "vison": "v"}
    )
    assert len(findings) == 3
    assert all(f.level == "error" for f in findings)


# --------------------------------------------------------------------------
# Behavior 2 -- deterministic, sorted, pure
# --------------------------------------------------------------------------
def test_b2_fields_come_back_in_ascending_order():
    findings = foundry.config_key_findings({"zz_bogus": 1, "aa_bogus": 2})
    assert _finding_fields(findings) == ("aa_bogus", "zz_bogus")


def test_b2_ordering_is_independent_of_insertion_order():
    a = foundry.config_key_findings({"zz_bogus": 1, "aa_bogus": 2, "mm_bogus": 3})
    b = foundry.config_key_findings({"mm_bogus": 3, "aa_bogus": 2, "zz_bogus": 1})
    assert _finding_fields(a) == _finding_fields(b) == (
        "aa_bogus", "mm_bogus", "zz_bogus")


def test_b2_all_valid_keys_return_empty_tuple(tmp_path):
    assert foundry.config_key_findings(_valid_data(tmp_path)) == ()


def test_b2_every_ProductConfig_field_is_accepted():
    every = {f.name: None for f in dataclasses.fields(foundry.ProductConfig)}
    assert foundry.config_key_findings(every) == ()


def test_b2_underscore_prefixed_comment_keys_are_exempt():
    assert foundry.config_key_findings({"_comment": "why", "_note": "x"}) == ()


def test_b2_underscore_exemption_does_not_hide_a_real_typo():
    findings = foundry.config_key_findings({"_comment": "why", "push_enable": True})
    assert _finding_fields(findings) == ("push_enable",)


def test_b2_input_mapping_is_not_mutated():
    raw = {"name": "x", "push_enable": True, "_c": 1}
    snapshot = dict(raw)
    foundry.config_key_findings(raw)
    assert raw == snapshot, "config_key_findings must not mutate its argument"


def test_b2_repeated_calls_are_identical():
    raw = {"zz_bogus": 1, "aa_bogus": 2}
    first = foundry.config_key_findings(raw)
    second = foundry.config_key_findings(raw)
    assert first == second


def test_b2_reads_and_writes_no_file():
    """Purity oracle by runtime introspection rather than by the docstring: the
    helper's own code (and every nested code object) may not reference any
    filesystem, network or printing name."""
    names = _all_code_names(foundry.config_key_findings.__code__)
    leaked = sorted(names & IO_NAMES)
    assert not leaked, f"pure helper references I/O names: {leaked}"


def test_b2_empty_mapping_is_clean():
    assert foundry.config_key_findings({}) == ()


def test_b2_hostile_shapes_do_not_raise():
    """Values are irrelevant to a KEY check, so odd values must not matter."""
    for raw in ({"push_enable": None}, {"push_enable": {"nested": [1, 2]}},
                {"push_enable": object()}, {"": 1}):
        foundry.config_key_findings(raw)


# --------------------------------------------------------------------------
# Behavior 3 -- honest no-suggestion case
# --------------------------------------------------------------------------
def test_b3_key_with_no_close_match_gets_no_did_you_mean():
    findings = foundry.config_key_findings({"zzzzzzzz": 1})
    assert len(findings) == 1
    detail = findings[0].detail
    assert detail.startswith(UNKNOWN_PREFIX)
    assert "did you mean" not in detail.lower(), \
        f"must not invent a suggestion for an unmatchable key: {detail!r}"


def test_b3_suggestion_is_present_only_when_the_guard_offers_one():
    """Cross-check against the existing guard, so this test cannot drift from it."""
    for key in ("zzzzzzzz", "push_enable"):
        detail = foundry.config_key_findings({key: 1})[0].detail
        expected = foundry.suggest_config_key(key)
        if expected is None:
            assert "did you mean" not in detail.lower()
        else:
            assert expected in detail


# --------------------------------------------------------------------------
# Behavior 4 -- human report, exit 1
# --------------------------------------------------------------------------
def test_b4_typo_config_exits_1_not_2(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 1, f"a typo'd KEY is a config ERROR (1), not an unreadable file (2); got {rc}"


def test_b4_human_report_shape(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    _, out, _ = _capture(lambda: foundry.lint_config_cli(path))
    lines = out.splitlines()
    assert lines[0].startswith("foundry lint-config"), \
        f"first line must keep the normal header, got {lines[0]!r}"
    assert _last_nonempty(out) == "verdict: PROBLEMS"
    assert any(ln.strip().startswith("[error] push_enable:") for ln in lines), \
        f"expected an `[error] push_enable:` line in:\n{out}"


def test_b4_human_report_is_not_the_unreadable_message(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    _, out, err = _capture(lambda: foundry.lint_config_cli(path))
    assert CANNOT_READ not in out + err, \
        "a typo'd key must no longer be reported as an unreadable config"


def test_b4_two_typos_report_both_lines(tmp_path):
    data = _typo_data(tmp_path)
    data["brnach"] = "main"
    path = _write(tmp_path, data)
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 1
    assert "[error] push_enable:" in out
    assert "[error] brnach:" in out


# --------------------------------------------------------------------------
# Behavior 5 -- --json emits the normal findings document
# --------------------------------------------------------------------------
def test_b5_json_document_is_the_whole_stdout_and_parses_once(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    doc = json.loads(out)          # raises if stdout is not EXACTLY one document
    assert rc == 1
    assert isinstance(doc, dict)


def test_b5_json_top_level_keys_in_declared_order(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    _, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    assert tuple(json.loads(out).keys()) == JSON_TOP_KEYS


def test_b5_json_payload_values(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    _, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    doc = json.loads(out)
    assert doc["exit_code"] == 1
    assert doc["ok"] is False
    assert doc["verdict"] == "PROBLEMS"
    assert doc["n_errors"] == 1
    assert doc["n_warnings"] == 0
    assert doc["config_path"] == path
    assert len(doc["findings"]) == 1
    assert doc["findings"][0]["field"] == "push_enable"
    assert doc["findings"][0]["level"] == "error"
    assert doc["findings"][0]["detail"].startswith(UNKNOWN_PREFIX)


def test_b5_finding_dicts_keep_exactly_three_keys(tmp_path):
    """The ConfigFinding schema is UNCHANGED -- no fourth `suggestion` field."""
    path = _write(tmp_path, _typo_data(tmp_path))
    _, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    for finding in json.loads(out)["findings"]:
        assert tuple(finding.keys()) == FINDING_KEYS


def test_b5_json_stdout_is_uncontaminated(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    _, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    assert not out.lstrip().startswith("foundry lint-config")
    assert CANNOT_READ not in out


def test_b5_n_errors_tracks_the_number_of_bad_keys(tmp_path):
    data = _typo_data(tmp_path)
    data["brnach"] = "main"
    data["vison"] = "v"
    path = _write(tmp_path, data)
    _, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    doc = json.loads(out)
    assert doc["n_errors"] == 3
    assert [f["field"] for f in doc["findings"]] == ["brnach", "push_enable", "vison"]


# --------------------------------------------------------------------------
# Behavior 6 -- the exit-2 contract is preserved exactly
# --------------------------------------------------------------------------
def test_b6_missing_config_still_exits_2(tmp_path):
    missing = str(tmp_path / "nope.json")
    rc, out, err = _capture(lambda: foundry.lint_config_cli(missing))
    assert rc == 2
    assert CANNOT_READ in out + err


def test_b6_invalid_json_still_exits_2(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json at all")
    rc, out, err = _capture(lambda: foundry.lint_config_cli(str(p)))
    assert rc == 2
    assert CANNOT_READ in out + err


def test_b6_missing_config_json_shape_unchanged(tmp_path):
    missing = str(tmp_path / "nope.json")
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(missing, as_json=True))
    doc = json.loads(out)
    assert rc == 2
    assert tuple(doc.keys()) == ERROR_JSON_KEYS
    assert doc["exit_code"] == 2
    assert doc["config_path"] == missing
    assert isinstance(doc["error"], str) and doc["error"]


def test_b6_invalid_json_json_shape_unchanged(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("[[[")
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(str(p), as_json=True))
    doc = json.loads(out)
    assert rc == 2
    assert tuple(doc.keys()) == ERROR_JSON_KEYS
    assert doc["exit_code"] == 2


def test_b6_directory_as_config_path_still_exits_2(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    rc, out, err = _capture(lambda: foundry.lint_config_cli(str(d)))
    assert rc == 2
    assert CANNOT_READ in out + err


# --------------------------------------------------------------------------
# Behavior 7 -- routing unchanged
# --------------------------------------------------------------------------
def test_b7_main_routes_typo_config_to_exit_1(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    rc, out, _ = _capture(lambda: foundry.main(["lint-config", "--config", path]))
    assert rc == 1
    assert "[error] push_enable:" in out


def test_b7_main_json_routes_and_prints_one_document(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    rc, out, _ = _capture(
        lambda: foundry.main(["lint-config", "--config", path, "--json"]))
    assert rc == 1
    assert json.loads(out)["findings"][0]["field"] == "push_enable"


def test_b7_main_still_routes_a_valid_config_to_zero(tmp_path):
    path = _write(tmp_path, _valid_data(tmp_path))
    rc, _, _ = _capture(lambda: foundry.main(["lint-config", "--config", path]))
    assert rc == 0


def test_b7_main_still_routes_a_missing_config_to_two(tmp_path):
    missing = str(tmp_path / "nope.json")
    rc, _, _ = _capture(lambda: foundry.main(["lint-config", "--config", missing]))
    assert rc == 2


# --------------------------------------------------------------------------
# Behavior 8 -- fail-safe: the new path can never make the old one worse
# --------------------------------------------------------------------------
def test_b8_seam_is_called_by_bare_module_name(tmp_path, monkeypatch):
    seen = []

    def spy(raw):
        seen.append(dict(raw))
        return ()

    monkeypatch.setattr(foundry, "config_key_findings", spy)
    path = _write(tmp_path, _typo_data(tmp_path))
    _capture(lambda: foundry.lint_config_cli(path))
    assert seen, "lint_config_cli must reach config_key_findings by BARE module name"
    assert "push_enable" in seen[0]


def test_b8_seam_returning_empty_degrades_to_exit_2(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "config_key_findings", lambda raw: ())
    path = _write(tmp_path, _typo_data(tmp_path))
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 2
    assert CANNOT_READ in out + err


def test_b8_seam_raising_degrades_to_exit_2_and_raises_nothing(tmp_path, monkeypatch):
    def boom(raw):
        raise RuntimeError("seam exploded")

    monkeypatch.setattr(foundry, "config_key_findings", boom)
    path = _write(tmp_path, _typo_data(tmp_path))
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 2
    assert CANNOT_READ in out + err


def test_b8_seam_raising_degrades_in_json_mode_too(tmp_path, monkeypatch):
    def boom(raw):
        raise RuntimeError("seam exploded")

    monkeypatch.setattr(foundry, "config_key_findings", boom)
    path = _write(tmp_path, _typo_data(tmp_path))
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    doc = json.loads(out)
    assert rc == 2
    assert tuple(doc.keys()) == ERROR_JSON_KEYS
    assert doc["exit_code"] == 2


def test_b8_seam_returning_no_findings_degrades_for_every_empty_shape(tmp_path,
                                                                      monkeypatch):
    """Behavior 8 spells out the "returns nothing" case as `()`. A seam that
    answers `None` is the same intent expressed differently, so both must take the
    historical exit-2 path rather than render an empty PROBLEMS report.

    SCOPE NOTE (see tester.md): a seam returning a TRUTHY value of the wrong TYPE
    (e.g. `"nonsense"`, `17`, `(None,)`) is a contract violation by the PATCHER and
    is unreachable in production, since the shipped `config_key_findings` returns a
    tuple of `ConfigFinding`. The spec names only `()` and RAISE, so that case is
    deliberately NOT asserted here; it is reported as PM feedback instead."""
    for label, junk in (("empty-tuple", ()), ("none", None)):
        monkeypatch.setattr(foundry, "config_key_findings", lambda raw, j=junk: j)
        path = _write(tmp_path, _typo_data(tmp_path), fname=f"c-{label}.json")
        rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
        assert rc == 2, f"{label} seam gave rc={rc}, expected the exit-2 fallback"
        assert CANNOT_READ in out + err, f"{label} seam lost the exit-2 diagnostic"


# --------------------------------------------------------------------------
# Behavior 9 -- the fail-closed parser is untouched
# --------------------------------------------------------------------------
def test_b9_load_config_still_raises_on_the_same_typo_file(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    with pytest.raises(foundry.ConfigKeyError):
        foundry.load_config(path)


def test_b9_load_config_still_accepts_a_valid_config(tmp_path):
    path = _write(tmp_path, _valid_data(tmp_path))
    cfg = foundry.load_config(path)
    assert cfg.name == "prod"
    assert cfg.push_enabled is True


def test_b9_valid_config_still_lints_ok(tmp_path):
    path = _write(tmp_path, _valid_data(tmp_path))
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 0
    assert _last_nonempty(out) == "verdict: OK"


def test_b9_valid_config_json_shape_still_ok(tmp_path):
    path = _write(tmp_path, _valid_data(tmp_path))
    rc, out, _ = _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    doc = json.loads(out)
    assert rc == 0
    assert tuple(doc.keys()) == JSON_TOP_KEYS
    assert doc["ok"] is True
    assert doc["verdict"] == "OK"
    assert doc["findings"] == []


def test_b9_neighbouring_guard_functions_still_answer(tmp_path):
    raw = _typo_data(tmp_path)
    assert foundry.unknown_config_keys(raw) == ("push_enable",)
    assert foundry.suggest_config_key("push_enable") == "push_enabled"
    assert isinstance(foundry.describe_config_key("push_enable"), str)


def test_b9_ConfigLint_schema_unchanged():
    assert tuple(f.name for f in dataclasses.fields(foundry.ConfigLint)) == \
        ("config_path", "findings")


# --------------------------------------------------------------------------
# Behavior 10 -- still read-only
# --------------------------------------------------------------------------
def _is_volatile_snapshot_path(rel: str) -> bool:
    """True when `rel` -- a repo-relative POSIX path string -- names a file some
    OTHER process may create or rewrite while a snapshot is open, so its
    appearance is no evidence about the code under test.  The rule: any path
    carrying a `__pycache__` COMPONENT, or any basename ending `.pyc` / `.pyo`.
    Pure -- same answer for the same input, reads and writes nothing.

    WHY a path COMPONENT and never a substring: `tests/data/__pycache__notes.md`
    is an ordinary tracked file that merely CONTAINS the token, and excluding it
    would blind the snapshot to a real write -- the exclusion has to be as narrow
    as the race it covers.

    WHY it is needed at all: on a COLD clone no `.pyc` exists yet, so the first
    xdist worker to import a module writes one DURING another worker's snapshot
    window, and the appearing file is then attributed to the read-only command
    under test.  Latent since this file shipped and invisible in a warm worktree,
    it reverted a fully green iteration 201 by reporting `lint-config` as having
    written `tests/__pycache__/test_iter154_behavior.cpython-313.pyc`."""
    parts = rel.split("/")
    return "__pycache__" in parts or parts[-1].endswith((".pyc", ".pyo"))


def _tree_snapshot(root: Path = REPO_ROOT) -> dict[str, str]:
    """Bounded byte-snapshot of the tracked, non-volatile part of the repo tree:
    every file directly under the root plus everything under tests/ and roles/.
    `.git`, `products/` (live loop state), `work*/` and every path
    `_is_volatile_snapshot_path` calls volatile are excluded because a
    concurrently running loop -- or a concurrent test worker writing bytecode --
    legitimately writes there.

    `root` is injectable ONLY so the exclusion rule can be exercised against a
    fixture tree offline; every call site passes nothing and snapshots the real
    repository, so the iteration-134 guarantee this helper exists for is
    unchanged."""
    items = {}
    for path in sorted(root.glob("*")):
        if path.is_file() and not _is_volatile_snapshot_path(path.name):
            items[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for sub in ("tests", "roles"):
        base = root / sub
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                if _is_volatile_snapshot_path(rel):
                    continue
                items[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return items


def test_b10_linting_a_typo_config_writes_nothing_into_the_repo_tree(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    before = _tree_snapshot()
    _capture(lambda: foundry.lint_config_cli(path))
    _capture(lambda: foundry.lint_config_cli(path, as_json=True))
    assert _tree_snapshot() == before, "lint-config must stay read-only"


def test_b10_linting_a_typo_config_creates_no_new_paths_in_tmp(tmp_path):
    path = _write(tmp_path, _typo_data(tmp_path))
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    _capture(lambda: foundry.lint_config_cli(path))
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before, \
        "a typo'd config never builds a ProductConfig, so nothing may be created"


# --------------------------------------------------------------------------
# Acceptance-Criteria oracles
# --------------------------------------------------------------------------
def test_ac_docstring_names_inputs_ordering_and_purity():
    doc = (foundry.config_key_findings.__doc__ or "").lower()
    assert doc.strip(), "config_key_findings needs a docstring"
    assert "raw" in doc, "the docstring must name its input"
    assert "order" in doc, "the docstring must state the ordering guarantee"
    assert "pure" in doc, "the docstring must state that it is pure"


def test_ac_both_modules_still_import_in_a_fresh_namespace():
    import importlib
    for name in ("foundry", "dispatcher"):
        mod = importlib.import_module(name)
        assert importlib.reload(mod) is not None


def test_ac_no_new_subcommand_appeared_for_this_feature():
    """The feature is delivered through the EXISTING verb -- no `lint-keys`,
    `config-keys` or similar was added."""
    def _help():
        # argparse's own --help action calls sys.exit(0); that is the CLI's normal
        # contract, so swallow it and assert on the printed text.
        with pytest.raises(SystemExit):
            foundry.main(["--help"])
        return 0

    _, out, err = _capture(_help)
    text = out + err
    for forbidden in ("lint-keys", "config-keys", "lint-config-keys",
                      "unknown-keys"):
        assert forbidden not in text, f"unexpected new subcommand {forbidden!r}"
