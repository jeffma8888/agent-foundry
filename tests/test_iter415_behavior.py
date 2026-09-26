"""Iteration 415 -- BLACK-BOX behavior tests: ``foundry staged-check``.

The product ships one pure parser (`staged_empty_blob_paths`) over `git ls-files -s -z`,
a count seam (`staged_paths_total`), a size seam (`worktree_size`) and a read-only,
fail-CLOSED 0/1/2 verb (`staged-check`) that names every INDEX path staged as the EMPTY
blob while its worktree file is non-empty -- the `git add -N` trap that bit iterations
154, 194 and 195 (porcelain said `A`, `git diff --cached --name-only` was empty).

Spec under test (products/_platform/state/iter-415/pm.md), Expected Behaviors 1-8:
   1. Pure core: `\\0` OR `\\n` separated `<mode> <sha> <stage>\\t<path>` records; a
      FINDING iff sha == EMPTY_BLOB_SHA1 (lowercase compare) AND size_of(path) is an
      int > 0; sorted + de-duplicated; malformed records, 0/None/raising sizes, empty,
      whitespace-only and non-str inputs are all excluded; never raises.
   2. `staged_paths_total` counts DISTINCT paths under the same parsing rules; 0 for
      empty/non-str.
   3. `worktree_size(repo, path)` is `os.path.getsize(Path(repo) / path)` or None on any
      OSError; never raises.
   4. Verb, human line: exactly ONE `run_cmd` read by BARE name with the pinned argv and
      `timeout=STAGED_CHECK_TIMEOUT_SECONDS`; sizes via `worktree_size` by BARE name;
      exactly one counts-only line; CLEAN -> 0, STAGED-EMPTY -> 1, UNKNOWN -> 2 on a
      not-ok result or a raising seam (never reads as clean).
   5. Verb, JSON: one `json.dumps(..., indent=2)` object with the five pinned keys;
      `staged` is None when UNKNOWN; findings are the sorted relative paths; the return
      value equals Behavior 4's.
   6. CLI wiring: `foundry.main(["staged-check", "--config", CFG, "--json"])` routes to
      the verb; `foundry_cli_verbs(source)` lists "staged-check"; `--help` lists it; the
      verb WRITES nothing (repo listing unchanged).
   7. Card + README adoption: `roles/final.md` ship section runs `staged-check` right
      after the `git add -A` bullet, names CLEAN and STAGED-EMPTY, keeps leak-guard
      before push; README `# 61.` with the usage line; `readme_verb_index_gaps` clean.
   8. Ledger rows land: exactly one 108-char `- iter 415 ` row directly under `- iter 414 `,
      the verbatim archive bullet, `roadmap_ledger_gaps(idx, arc, (415,)) == []`.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-415 PM spec, the
conventions of `tests/` (the scripted-seam `_install` + `_cfg_file(tmp_path)` idiom of
`tests/test_iter229_behavior.py`, the `# NN.` README section walker of
`tests/test_iter373_behavior.py`), the README, and the product's OWN OBSERVABLE surface
(importing the module, calling public functions, driving `foundry.main`).  The
implementation TEXT of `foundry.py` was NOT read by the author; `roles/final.md` and
`foundry.py` text are passed to PUBLIC oracles or machine scans only.  `engineer.md`,
`reviewer.md`, `IMPLEMENTATION.patch` and `git diff` were NOT read.

Offline and deterministic: no real git subprocess anywhere (`run_cmd` is scripted by
BARE module name), no network, no clock; `worktree_size` is exercised over real files
under `tmp_path`.  No absolute machine path appears as a literal (fixture literals are
relative; absolute values come from `tmp_path` at runtime).  No assertion reads a
gitignored path or counts files in the ambient `tests/` or `products/` tree.
"""

import io
import json
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 415
VERB = "staged-check"
EMPTY = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
OTHER = "0123456789abcdef0123456789abcdef01234567"
NUL = "\x00"  # NEVER an inline `\0` before a digit -- that is the octal escape `\010`

ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
README = _ROOT / "README.md"
SOURCE = _ROOT / "foundry.py"
FINAL_CARD = _ROOT / "roles" / "final.md"

UNKNOWN_LINE = "staged-check: UNKNOWN -- the ls-files read did not succeed"

ROADMAP_ROW = ("- iter 415 -- staged-check: names paths staged as the EMPTY blob over a "
               "non-empty worktree file; exit 0/1/2.")
ARCHIVE_BULLET = (
    "- **iter 415 -- `foundry staged-check`: the `git add -N` trap (a path listed in the "
    "index with the EMPTY blob while its worktree file is non-empty; porcelain says `A`, "
    "`git diff --cached --name-only` is empty) bit iters 154/194/195 and had only a "
    "rotating learnings bullet. Pure `staged_empty_blob_paths` over `git ls-files -s -z` "
    "+ `worktree_size` seam, thin CLI with fail-closed 0/1/2 (CLEAN/STAGED-EMPTY/UNKNOWN), "
    "`--json` carries the relative paths, the human line counts only; `roles/final.md` "
    "runs it right after the gate's `git add -A`; README `# 61.`. Additive-dormant, zero "
    "pipeline call sites. Scout A1 over B1 (the `--topic` card edit: a near-clone of iter "
    "414 that adds load to the 600 s-capped scout seat).**"
)


# --------------------------------------------------------------------------- #
# helpers -- scripted seams only, mirroring tests/test_iter229_behavior.py
# --------------------------------------------------------------------------- #
def _rec(sha: str, path: str, stage: int = 0, mode: str = "100644") -> str:
    return f"{mode} {sha} {stage}\t{path}"


def _ls(*records: str, sep: str = NUL, trailing: bool = True) -> str:
    return sep.join(records) + (sep if trailing else "")


def _clean_line(n: int) -> str:
    return (f"staged-check: CLEAN -- 0 of {n} staged path(s) hold the empty blob against "
            f"a non-empty worktree file")


def _empty_line(k: int, n: int) -> str:
    return (f"staged-check: STAGED-EMPTY -- {k} of {n} staged path(s) hold the empty blob "
            f"against a non-empty worktree file; re-run git add -A before committing")


def _install(monkeypatch, *, text="", ok=True, raises=False):
    """Script `run_cmd` by BARE module name and record every call's argv and kwargs."""
    calls: list[tuple[list[str], dict]] = []

    def fake_run_cmd(args, *rest, **kw):
        calls.append(([str(a) for a in args], dict(kw)))
        if raises:
            raise RuntimeError("ls-files-boom-xyz")
        return foundry.CmdResult(ok, text)

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    return calls


def _cfg_file(tmp_path):
    """A minimal on-disk product config, as tests/test_iter229_behavior.py builds one."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "placeholder.txt").write_text("x\n", encoding="utf-8")
    conf = tmp_path / "config.json"
    conf.write_text(
        json.dumps({
            "name": "t",
            "repo": str(repo),
            "allowed_push_repo": "unit-test-repo",
            "work_root": str(tmp_path / "work"),
        }),
        encoding="utf-8",
    )
    return conf, repo


def _capture(fn):
    """Run fn() with stdout captured; return (rc, stdout)."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn()
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


def _listing(root: pathlib.Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _pure(text, size_of):
    return foundry.staged_empty_blob_paths(text, size_of)


def _readme_section(text: str, heading_no: int) -> str:
    """The `# NN.` section body, up to (not including) the next `# NN.` heading."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^#\s*{heading_no}\.", ln):
            start = i
            break
    assert start is not None, f"README has no `# {heading_no}.` section"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^#\s*\d+\.", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


def _ship_section(card: str) -> str:
    m = re.search(r"^## If ALL pass.*?(?=^## If ANY fail)", card, re.S | re.M)
    assert m, "final card has no `## If ALL pass -- ship` section before `## If ANY fail`"
    return m.group(0)


def _bullets(section: str) -> list[str]:
    return [ln for ln in section.splitlines() if ln.lstrip().startswith(("- ", "* "))]


# ========================================================================== #
# Behavior 1 -- pure core
# ========================================================================== #
def test_b1_empty_blob_over_nonempty_file_is_a_finding():
    assert _pure(_rec(EMPTY, "src/new_module.py"), lambda p: 3) == ("src/new_module.py",)


def test_b1_two_sided_proof_same_sha_zero_byte_file_is_clean():
    text = _rec(EMPTY, "pkg/__init__.py")
    assert _pure(text, lambda p: 3) == ("pkg/__init__.py",)
    assert _pure(text, lambda p: 0) == ()


@pytest.mark.parametrize("size", [None, 0, -1, "3", 3.5])
def test_b1_size_not_a_positive_int_is_excluded(size):
    assert _pure(_rec(EMPTY, "a.py"), lambda p: size) == ()


def test_b1_size_of_raising_is_excluded_not_propagated():
    def boom(p):
        raise OSError("deleted worktree file")
    assert _pure(_rec(EMPTY, "gone.py"), boom) == ()


def test_b1_non_empty_blob_sha_is_never_a_finding():
    assert _pure(_rec(OTHER, "a.py"), lambda p: 900) == ()


def test_b1_sha_compare_is_case_insensitive():
    assert _pure(_rec(EMPTY.upper(), "a.py"), lambda p: 1) == ("a.py",)


def test_b1_module_constant_is_the_empty_blob_sha1():
    assert foundry.EMPTY_BLOB_SHA1 == EMPTY


@pytest.mark.parametrize("sep", [NUL, "\n"])
def test_b1_nul_and_newline_separated_records_both_parse(sep):
    text = _ls(_rec(EMPTY, "b.py"), _rec(OTHER, "c.py"), _rec(EMPTY, "a.py"), sep=sep)
    assert _pure(text, lambda p: 5) == ("a.py", "b.py")


def test_b1_mixed_separators_and_no_trailing_separator():
    text = _rec(EMPTY, "a") + NUL + _rec(EMPTY, "b") + "\n" + _rec(EMPTY, "c")
    assert _pure(text, lambda p: 1) == ("a", "b", "c")


def test_b1_findings_are_sorted_and_deduplicated():
    text = _ls(_rec(EMPTY, "z.py"), _rec(EMPTY, "a.py"), _rec(EMPTY, "z.py"),
               _rec(EMPTY, "m.py", stage=1), _rec(EMPTY, "m.py", stage=2))
    out = _pure(text, lambda p: 2)
    assert out == ("a.py", "m.py", "z.py")
    assert isinstance(out, tuple)


def test_b1_size_of_is_consulted_per_path():
    sizes = {"big.py": 902, "empty.py": 0}
    text = _ls(_rec(EMPTY, "big.py"), _rec(EMPTY, "empty.py"), _rec(OTHER, "ok.py"))
    assert _pure(text, lambda p: sizes.get(p)) == ("big.py",)


@pytest.mark.parametrize("bad_record", [
    "100644 " + EMPTY + " 0 a.py",       # no tab
    EMPTY + " 0\ta.py",                   # two fields before the tab
    EMPTY + "\ta.py",                     # one field before the tab
    "\ta.py",                             # nothing before the tab
    "garbage",
    "",
])
def test_b1_malformed_record_is_dropped_but_siblings_survive(bad_record):
    text = _ls(_rec(EMPTY, "keep.py"), bad_record, _rec(EMPTY, "also.py"))
    assert _pure(text, lambda p: 1) == ("also.py", "keep.py")


def test_b1_path_with_spaces_is_kept_whole():
    assert _pure(_rec(EMPTY, "dir/my file.py"), lambda p: 1) == ("dir/my file.py",)


@pytest.mark.parametrize("bad", ["", "   ", "\n\n", " \t\n", NUL + NUL, None, 42, 3.5,
                                 b"100644 x 0\ta", ["x"], {}])
def test_b1_empty_whitespace_or_non_str_input_returns_empty_tuple(bad):
    assert _pure(bad, lambda p: 1) == ()


@pytest.mark.parametrize("weird", [None, 42, "not-callable"])
def test_b1_never_raises_even_for_a_bad_size_of(weird):
    assert _pure(_rec(EMPTY, "a.py"), weird) == ()


# ========================================================================== #
# Behavior 2 -- count seam
# ========================================================================== #
def test_b2_total_counts_distinct_paths():
    text = _ls(_rec(EMPTY, "a"), _rec(OTHER, "b"), _rec(EMPTY, "a"),
               _rec(EMPTY, "c", stage=1), _rec(EMPTY, "c", stage=3))
    assert foundry.staged_paths_total(text) == 3


def test_b2_total_uses_the_same_parsing_rules():
    text = _ls(_rec(EMPTY, "a"), "garbage", EMPTY + " 0\tb", _rec(OTHER, "c"))
    assert foundry.staged_paths_total(text) == 2


@pytest.mark.parametrize("bad", ["", "  \n", None, 42, b"x", ["x"]])
def test_b2_total_is_zero_for_empty_or_non_str(bad):
    assert foundry.staged_paths_total(bad) == 0


@pytest.mark.parametrize("sep", [NUL, "\n"])
def test_b2_total_counts_under_both_separators(sep):
    assert foundry.staged_paths_total(_ls(_rec(EMPTY, "a"), _rec(OTHER, "b"), sep=sep)) == 2


# ========================================================================== #
# Behavior 3 -- size seam over REAL tmp_path files
# ========================================================================== #
def test_b3_worktree_size_reads_real_byte_counts(tmp_path):
    (tmp_path / "three.txt").write_bytes(b"abc")
    (tmp_path / "zero.txt").write_bytes(b"")
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_bytes(b"x" * 902)
    assert foundry.worktree_size(tmp_path, "three.txt") == 3
    assert foundry.worktree_size(tmp_path, "zero.txt") == 0
    assert foundry.worktree_size(str(tmp_path), "pkg/mod.py") == 902


def test_b3_worktree_size_is_none_on_any_oserror(tmp_path):
    assert foundry.worktree_size(tmp_path, "does-not-exist.py") is None
    assert foundry.worktree_size(tmp_path / "no-such-repo", "a.py") is None


@pytest.mark.parametrize("repo,path", [(None, "a.py"), (42, "a.py"), ("", None)])
def test_b3_worktree_size_never_raises(repo, path):
    assert foundry.worktree_size(repo, path) is None


# ========================================================================== #
# Behavior 4 -- verb, human line
# ========================================================================== #
def test_b4_clean_tree_prints_exactly_the_clean_line_and_returns_0(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "a.py").write_text("abc", encoding="utf-8")
    calls = _install(monkeypatch, text=_ls(_rec(OTHER, "a.py"), _rec(OTHER, "placeholder.txt")))
    rc, out = _capture(lambda: foundry.staged_check_cli(foundry.load_config(str(conf))))
    assert rc == 0
    assert out == _clean_line(2) + "\n"
    assert len(calls) == 1


def test_b4_exactly_one_run_cmd_read_with_the_pinned_argv_and_timeout(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    calls = _install(monkeypatch, text="")
    cfg = foundry.load_config(str(conf))
    _capture(lambda: foundry.staged_check_cli(cfg))
    assert len(calls) == 1
    argv, kw = calls[0]
    assert argv == ["git", "-C", str(cfg.repo), "ls-files", "-s", "-z"]
    assert kw.get("timeout") == foundry.STAGED_CHECK_TIMEOUT_SECONDS
    assert foundry.STAGED_CHECK_TIMEOUT_SECONDS == 20


def test_b4_empty_index_is_clean_with_zero_staged(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, text="")
    rc, out = _capture(lambda: foundry.staged_check_cli(foundry.load_config(str(conf))))
    assert rc == 0
    assert out == _clean_line(0) + "\n"


def test_b4_two_sided_proof_three_byte_file_flags_zero_byte_file_does_not(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "big.py").write_bytes(b"abc")
    (repo / "empty.py").write_bytes(b"")
    _install(monkeypatch, text=_ls(_rec(EMPTY, "big.py"), _rec(EMPTY, "empty.py"),
                                    _rec(OTHER, "placeholder.txt")))
    cfg = foundry.load_config(str(conf))
    rc, out = _capture(lambda: foundry.staged_check_cli(cfg))
    assert rc == 1
    assert out == _empty_line(1, 3) + "\n"
    # the zero-byte half alone reads CLEAN (exit 0)
    _install(monkeypatch, text=_ls(_rec(EMPTY, "empty.py"), _rec(OTHER, "placeholder.txt")))
    rc2, out2 = _capture(lambda: foundry.staged_check_cli(cfg))
    assert rc2 == 0
    assert out2 == _clean_line(2) + "\n"


def test_b4_no_path_ever_reaches_the_human_line(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "secret_module_name.py").write_bytes(b"abc")
    _install(monkeypatch, text=_ls(_rec(EMPTY, "secret_module_name.py")))
    rc, out = _capture(lambda: foundry.staged_check_cli(foundry.load_config(str(conf))))
    assert rc == 1
    assert "secret_module_name" not in out
    assert out.count("\n") == 1 and out.endswith("\n")


def test_b4_sizes_come_through_the_worktree_size_seam_by_bare_name(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    # no such files exist in the repo -- only a scripted seam can make them findings
    _install(monkeypatch, text=_ls(_rec(EMPTY, "ghost_a.py"), _rec(EMPTY, "ghost_b.py")))
    seen: list[tuple[str, str]] = []

    def fake_size(repo_arg, path):
        seen.append((str(repo_arg), path))
        return 7

    monkeypatch.setattr(foundry, "worktree_size", fake_size)
    cfg = foundry.load_config(str(conf))
    rc, out = _capture(lambda: foundry.staged_check_cli(cfg))
    assert rc == 1
    assert out == _empty_line(2, 2) + "\n"
    assert sorted(p for _, p in seen) == ["ghost_a.py", "ghost_b.py"]
    assert all(r == str(cfg.repo) for r, _ in seen)


def test_b4_not_ok_result_is_unknown_exit_2(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, text=_ls(_rec(OTHER, "a.py")), ok=False)
    rc, out = _capture(lambda: foundry.staged_check_cli(foundry.load_config(str(conf))))
    assert rc == 2
    assert out == UNKNOWN_LINE + "\n"


def test_b4_raising_seam_is_unknown_exit_2_never_clean(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, raises=True)
    rc, out = _capture(lambda: foundry.staged_check_cli(foundry.load_config(str(conf))))
    assert rc == 2
    assert out == UNKNOWN_LINE + "\n"
    assert "CLEAN" not in out


# ========================================================================== #
# Behavior 5 -- verb, JSON
# ========================================================================== #
def _json_run(tmp_path, monkeypatch, **install_kw):
    conf, repo = _cfg_file(tmp_path)
    _install(monkeypatch, **install_kw)
    cfg = foundry.load_config(str(conf))
    rc_h, _ = _capture(lambda: foundry.staged_check_cli(cfg))
    rc_j, out = _capture(lambda: foundry.staged_check_cli(cfg, as_json=True))
    return repo, rc_h, rc_j, out


def test_b5_json_findings_object_is_exact_and_sorted(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "z_last.py").write_bytes(b"abc")
    (repo / "a_first.py").write_bytes(b"abcd")
    (repo / "empty.py").write_bytes(b"")
    _install(monkeypatch, text=_ls(_rec(EMPTY, "z_last.py"), _rec(EMPTY, "empty.py"),
                                    _rec(EMPTY, "a_first.py"), _rec(OTHER, "placeholder.txt")))
    cfg = foundry.load_config(str(conf))
    rc_h, _ = _capture(lambda: foundry.staged_check_cli(cfg))
    rc_j, out = _capture(lambda: foundry.staged_check_cli(cfg, as_json=True))
    obj = {"product": "t", "verdict": "STAGED-EMPTY", "exit_code": 1, "staged": 4,
           "findings": ["a_first.py", "z_last.py"]}
    assert rc_j == rc_h == 1
    assert out == json.dumps(obj, indent=2) + "\n"
    assert list(json.loads(out).keys()) == ["product", "verdict", "exit_code", "staged", "findings"]
    assert "staged-check:" not in out


def test_b5_json_clean_object(tmp_path, monkeypatch):
    _, rc_h, rc_j, out = _json_run(tmp_path, monkeypatch,
                                   text=_ls(_rec(OTHER, "a.py"), _rec(OTHER, "b.py")))
    assert rc_j == rc_h == 0
    assert json.loads(out) == {"product": "t", "verdict": "CLEAN", "exit_code": 0,
                               "staged": 2, "findings": []}


def test_b5_json_unknown_has_null_staged_and_empty_findings(tmp_path, monkeypatch):
    _, rc_h, rc_j, out = _json_run(tmp_path, monkeypatch, text="x", ok=False)
    assert rc_j == rc_h == 2
    assert json.loads(out) == {"product": "t", "verdict": "UNKNOWN", "exit_code": 2,
                               "staged": None, "findings": []}
    assert out == json.dumps(json.loads(out), indent=2) + "\n"


def test_b5_json_unknown_on_raising_seam(tmp_path, monkeypatch):
    _, rc_h, rc_j, out = _json_run(tmp_path, monkeypatch, raises=True)
    assert rc_j == rc_h == 2
    assert json.loads(out)["verdict"] == "UNKNOWN"
    assert UNKNOWN_LINE not in out


# ========================================================================== #
# Behavior 6 -- CLI wiring
# ========================================================================== #
def test_b6_main_routes_the_verb_and_writes_nothing(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "big.py").write_bytes(b"abc")
    _install(monkeypatch, text=_ls(_rec(EMPTY, "big.py"), _rec(OTHER, "placeholder.txt")))
    foundry.load_config(str(conf))  # the config loader owns work_root; snapshot AFTER it
    before_repo, before_all = _listing(repo), _listing(tmp_path)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf), "--json"]))
    assert rc == 1
    assert json.loads(out) == {"product": "t", "verdict": "STAGED-EMPTY", "exit_code": 1,
                               "staged": 2, "findings": ["big.py"]}
    assert _listing(repo) == before_repo
    assert _listing(tmp_path) == before_all
    assert (repo / "big.py").read_bytes() == b"abc"


def test_b6_main_human_mode_clean_exit_0(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, text=_ls(_rec(OTHER, "placeholder.txt")))
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 0
    assert out == _clean_line(1) + "\n"


def test_b6_main_unknown_exit_2(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, ok=False)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 2
    assert out == UNKNOWN_LINE + "\n"


def test_b6_verb_census_lists_staged_check():
    verbs = foundry.foundry_cli_verbs(SOURCE.read_text(encoding="utf-8"))
    assert VERB in verbs
    assert len(verbs) >= 60  # 59 -> 60 per the spec; the exact pin lives in test_iter362


def test_b6_help_lists_the_verb_and_its_json_flag():
    with pytest.raises(SystemExit) as top:
        _capture(lambda: foundry.main(["--help"]))
    assert top.value.code == 0
    _, out = _capture(lambda: _swallow(lambda: foundry.main(["--help"])))
    assert VERB in out
    _, sub = _capture(lambda: _swallow(lambda: foundry.main([VERB, "--help"])))
    assert "--config" in sub and "--json" in sub


def _swallow(fn):
    try:
        return fn()
    except SystemExit as e:  # argparse --help
        return e.code


def test_b6_import_safety():
    assert hasattr(foundry, "staged_check_cli")
    assert hasattr(dispatcher, "__file__")


# ========================================================================== #
# Behavior 7 -- card + README adoption (public oracles + machine scans only)
# ========================================================================== #
def _final() -> str:
    return FINAL_CARD.read_text(encoding="utf-8")


def _live_verbs() -> tuple:
    return foundry.foundry_cli_verbs(SOURCE.read_text(encoding="utf-8"))


def test_b7_final_card_teaches_staged_check_with_no_verb_gaps():
    card = _final()
    assert VERB in foundry.role_card_verbs(card)
    assert foundry.role_card_verb_gaps(card, _live_verbs()) == ()


def test_b7_ship_section_runs_staged_check_right_after_git_add_A():
    bullets = _bullets(_ship_section(_final()))
    i_add = next(i for i, b in enumerate(bullets) if re.search(r"\badd -A\b", b))
    assert VERB in bullets[i_add + 1], "the bullet after `git add -A` must run staged-check"
    sc = bullets[i_add + 1]
    assert "CLEAN" in sc
    assert "STAGED-EMPTY" in sc
    assert "revert" in sc.lower()
    assert re.search(r"re-run\s+`?git add -A`?", sc)


def test_b7_leak_guard_still_precedes_push_in_ship_section():
    ship = _ship_section(_final())
    i_scan, i_push, i_sc = ship.find("leak_guard.py"), ship.find("push origin"), ship.find(VERB)
    assert -1 not in (i_scan, i_push, i_sc)
    assert i_scan < i_push
    assert i_sc < i_push


def test_b7_readme_has_section_61_with_the_usage_line():
    sec = _readme_section(README.read_text(encoding="utf-8"), 61)
    assert VERB in sec
    assert re.search(
        r"uv run python foundry\.py staged-check --config products/<name>/config\.json\s+#", sec)
    assert "0/1/2" in sec


def test_b7_readme_verb_index_is_clean_for_staged_check():
    audit = foundry.readme_verb_index_gaps(README.read_text(encoding="utf-8"), _live_verbs())
    assert VERB not in audit.missing_verbs
    assert VERB not in audit.unknown_invocations
    assert audit.missing_verbs == ()


def test_b7_deleting_section_61_reds_the_readme_audit():
    text = README.read_text(encoding="utf-8")
    section = _readme_section(text, 61)
    without = text.replace(section, "")
    assert without != text
    assert VERB in foundry.readme_verb_index_gaps(without, _live_verbs()).missing_verbs


# ========================================================================== #
# Behavior 8 -- ledger rows in the same diff
# ========================================================================== #
def test_b8_roadmap_row_is_exact_108_chars_and_directly_under_iter_414():
    lines = ROADMAP.read_text(encoding="utf-8").splitlines()
    rows = [ln for ln in lines if ln.startswith("- iter 415 ")]
    assert rows == [ROADMAP_ROW]
    assert len(ROADMAP_ROW) == 108
    i414 = next(i for i, ln in enumerate(lines) if ln.startswith("- iter 414 "))
    assert lines[i414 + 1] == ROADMAP_ROW


def test_b8_archive_bullet_is_verbatim_and_after_iter_414():
    lines = ARCHIVE.read_text(encoding="utf-8").splitlines()
    bullets = [ln for ln in lines if ln.startswith("- **iter 415 ")]
    assert bullets == [ARCHIVE_BULLET]
    i414 = next(i for i, ln in enumerate(lines) if ln.startswith("- **iter 414 "))
    assert lines.index(ARCHIVE_BULLET) > i414


def test_b8_ledger_oracle_reports_no_gap_for_415():
    idx = ROADMAP.read_text(encoding="utf-8")
    arc = ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_ledger_gaps(idx, arc, (415,)) == []
    # two-sided: the oracle records an iteration when EITHER file carries it (measured
    # before encoding -- stripping one side alone stays []), so strip BOTH and it flips
    idx_wo = idx.replace(ROADMAP_ROW + "\n", "")
    arc_wo = "\n".join(ln for ln in arc.splitlines() if not ln.startswith("- **iter 415 ")) + "\n"
    assert idx_wo != idx and arc_wo != arc
    assert foundry.roadmap_ledger_gaps(idx_wo, arc_wo, (415,)) == [415]
    assert foundry.roadmap_ledger_gaps(idx, arc, (999,)) == [999]
