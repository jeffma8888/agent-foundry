"""Black-box behaviour tests for iter 137 -- `foundry new-product`: scaffold a
valid-by-construction product config, then lint it on the spot.

Spec: products/_platform/state/iter-137/pm.md, Expected Behaviors 1-13.

  product_config_template(name, repo, ...)  -- pure
  1.  returns a dict whose every key the schema accepts: `unknown_config_keys`
      returns `()` (underscore-prefixed comment keys are exempt).
  2.  `work_root` is exactly `"{FOUNDRY}/products/<name>"` -- never empty, so
      resolution can never fall back to the real foundry checkout.
  3.  carries an underscore-prefixed comment key holding a non-empty string, and
      the dict written to a file loads through `load_config` without raising.
  4.  after that round-trip: `name`, `repo` as given, and `push_enabled is False`
      -- a freshly scaffolded product never pushes until the operator opts in.
  new-product CLI
  5.  `main(["new-product", "--name", "mytool", "--repo", <git repo>])` writes
      `<FOUNDRY>/products/mytool/config.json` and returns 0.
  6.  a `--repo` that is a plain directory returns 1, STILL writes the config,
      and stdout carries both `repo` and `not a git repository`.
  7.  a second run returns 2, leaves the file BYTE-IDENTICAL, and names the path.
  8.  the second run with `--force` returns the normal lint code (0 or 1) and the
      file's bytes change.
  9.  an unsafe `--name` (`""`, `"a/b"`, `".."`) returns 2, prints a diagnostic
      naming `--name`, and creates NOTHING under `<FOUNDRY>/products/`.
  10. `--test-cmd` / `--branch` land verbatim in the written JSON; omitted,
      `branch` is `"main"`.
  11. stdout carries a paste-ready dispatch `work_items` snippet naming the
      written config path, and the repo's real `foundry.config.json` is
      byte-unchanged.
  12. with `FOUNDRY` patched, no `mytool` directory appears under the REAL
      foundry checkout's `products/`.
  doc truth
  13. `USAGE.md` names `new-product` and no longer carries the failing recipe
      line `cp products/repolens/config.json products/mytool/config.json`.
  Plus acceptance-criteria oracles: both modules import, the verb is registered
  in the CLI, the verb needs NO loadable product config (its dispatch precedes
  config loading), and the two iteration-137 roadmap records exist within the
  documented bounds.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-137 PM spec and the
product's OBSERVABLE surface -- importing the module, CALLING its public
functions, inspecting `--help`, running `main()` and reading its stdout, and
reading files under `tests/` for CONVENTIONS. The implementation BODIES of
foundry.py / dispatcher.py, the engineer's notes, the reviewer's notes, the
`rev_verify.py` helper and `git diff` were NOT read. Three SHIPPED docs
(`USAGE.md`, `PLATFORM_ROADMAP.md`, `PLATFORM_ROADMAP_ARCHIVE.md`) are read as
prose because Behavior 13 and the roadmap acceptance criterion are about them.

Fully offline and deterministic: `tmp_path` only, `FOUNDRY` monkeypatched so
nothing is ever written under the real `products/`, no network, no git remote,
no `git init`, no subprocess, no sleep, no clock dependence.
"""
import contextlib
import io
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

_USAGE = _ROOT / "USAGE.md"
_ROSTER = _ROOT / "foundry.config.json"
_REAL_PRODUCTS = _ROOT / "products"
_ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
_ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"

# The exact on-ramp line scout B RAN and found exits 1 (spec Behavior 13).
_OLD_RECIPE = "cp products/repolens/config.json products/mytool/config.json"

NAME = "mytool"


# --------------------------------------------------------------------------
# helpers -- RE-DERIVED from the spec's own wording
# --------------------------------------------------------------------------
def _run(*argv):
    """Run the CLI, returning (exit_code, stdout+stderr)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = foundry.main(list(argv))
    return code, buf.getvalue()


def _git_repo(base, name="repo"):
    """A directory that IS a git repository, made without running git."""
    repo = base / name
    (repo / ".git").mkdir(parents=True)
    return repo


def _plain_dir(base, name="plain"):
    d = base / name
    d.mkdir(parents=True)
    return d


def _written(root, name=NAME):
    return root / "products" / name / "config.json"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """`FOUNDRY` redirected into `tmp_path` (the spec's design-note-4 seam), with a
    `roles/` dir present so the scaffold's own root is not the thing under test."""
    (tmp_path / "roles").mkdir()
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    return tmp_path


# --------------------------------------------------------------------------
# Behavior 1 -- the template emits only keys the schema accepts
# --------------------------------------------------------------------------
def test_b1_template_returns_a_dict_the_schema_fully_accepts():
    result = foundry.product_config_template(name=NAME, repo="/tmp/x/mytool")
    assert isinstance(result, dict)
    assert result, "the template must not be empty"
    assert foundry.unknown_config_keys(result) == ()


def test_b1_template_still_emits_the_fields_usage_tells_an_operator_to_edit():
    result = foundry.product_config_template(name=NAME, repo="/tmp/x/mytool")
    for key in ("name", "repo", "allowed_push_repo", "vision", "test_cmd",
                "work_root", "push_enabled"):
        assert key in result, f"scaffold should emit {key!r} for the operator to see"


def test_b1_template_is_pure_deterministic_and_writes_nothing(tmp_path, monkeypatch):
    """"pure (no I/O, no mutation)": two calls agree, mutating one result cannot
    leak into the next, and the call touches no filesystem."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    first = foundry.product_config_template(name=NAME, repo="/tmp/x/mytool")
    second = foundry.product_config_template(name=NAME, repo="/tmp/x/mytool")
    assert first == second
    first["name"] = "MUTATED"
    first["_injected"] = "MUTATED"
    third = foundry.product_config_template(name=NAME, repo="/tmp/x/mytool")
    assert third == second, "the template must not share mutable state between calls"
    assert list(tmp_path.iterdir()) == [], "a pure template must write nothing"


# --------------------------------------------------------------------------
# Behavior 2 -- work_root is always explicit
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", [NAME, "another-tool"])
def test_b2_work_root_is_the_explicit_foundry_placeholder(name):
    result = foundry.product_config_template(name=name, repo="/tmp/x")
    assert result["work_root"] == "{FOUNDRY}/products/" + name
    assert result["work_root"].strip() != ""


# --------------------------------------------------------------------------
# Behaviors 3 + 4 -- the template round-trips through the real loader
# --------------------------------------------------------------------------
def test_b3_template_carries_a_non_empty_comment_key():
    result = foundry.product_config_template(name=NAME, repo="/tmp/x")
    comments = [k for k in result if k.startswith(foundry.CONFIG_COMMENT_PREFIX)]
    assert comments, "template should carry an underscore-prefixed comment key"
    for key in comments:
        assert isinstance(result[key], str)
        assert result[key].strip(), f"{key!r} must hold a non-empty help string"


def test_b3_template_written_to_a_file_loads_without_raising(sandbox):
    repo = _git_repo(sandbox)
    path = sandbox / "scaffolded.json"
    path.write_text(json.dumps(foundry.product_config_template(name=NAME, repo=str(repo))))
    cfg = foundry.load_config(str(path))          # must not raise
    assert cfg is not None


def test_b4_round_trip_reports_name_repo_and_push_disabled(sandbox):
    repo = _git_repo(sandbox)
    path = sandbox / "scaffolded.json"
    path.write_text(json.dumps(foundry.product_config_template(name=NAME, repo=str(repo))))
    cfg = foundry.load_config(str(path))
    assert cfg.name == NAME
    assert str(cfg.repo) == str(repo)
    assert cfg.push_enabled is False


# --------------------------------------------------------------------------
# Behavior 5 -- the happy path
# --------------------------------------------------------------------------
def test_b5_cli_writes_the_config_and_returns_zero_for_a_git_repo(sandbox):
    repo = _git_repo(sandbox)
    code, out = _run("new-product", "--name", NAME, "--repo", str(repo))
    assert _written(sandbox).is_file()
    assert code == 0, out
    assert str(_written(sandbox)) in out
    loaded = json.loads(_written(sandbox).read_text())
    assert loaded["name"] == NAME
    assert loaded["repo"] == str(repo)


# --------------------------------------------------------------------------
# Behavior 6 -- a non-git repo is a finding, not a refusal
# --------------------------------------------------------------------------
def test_b6_non_git_repo_returns_one_writes_anyway_and_explains(sandbox):
    plain = _plain_dir(sandbox)
    code, out = _run("new-product", "--name", NAME, "--repo", str(plain))
    assert code == 1, out
    assert _written(sandbox).is_file(), "a lint finding must not discard the scaffold"
    assert "repo" in out
    assert "not a git repository" in out


# --------------------------------------------------------------------------
# Behaviors 7 + 8 -- refuse, then --force
# --------------------------------------------------------------------------
def test_b7_second_run_refuses_with_two_and_leaves_the_file_byte_identical(sandbox):
    repo = _git_repo(sandbox)
    _run("new-product", "--name", NAME, "--repo", str(repo))
    path = _written(sandbox)
    before = path.read_bytes()
    code, out = _run("new-product", "--name", NAME, "--repo", str(repo))
    assert code == 2, out
    assert path.read_bytes() == before
    assert str(path) in out


def test_b8_second_run_with_force_rewrites_the_file(sandbox):
    repo = _git_repo(sandbox)
    _run("new-product", "--name", NAME, "--repo", str(repo))
    path = _written(sandbox)
    before = path.read_bytes()
    code, out = _run("new-product", "--name", NAME, "--repo", str(repo),
                     "--branch", "trunk", "--force")
    assert code in (0, 1), out
    assert path.read_bytes() != before
    assert json.loads(path.read_text())["branch"] == "trunk"


def test_b8_note_force_is_byte_stable_when_every_argument_is_unchanged(sandbox):
    """AMBIGUITY (reported to PM): Behavior 8 says the bytes "change". The template
    is deterministic, so `--force` with IDENTICAL arguments legitimately rewrites
    the same bytes. Pinned here so the property is a decision, not an accident."""
    repo = _git_repo(sandbox)
    argv = ("new-product", "--name", NAME, "--repo", str(repo))
    _run(*argv)
    path = _written(sandbox)
    before = path.read_bytes()
    code, out = _run(*argv, "--force")
    assert code in (0, 1), out
    assert path.read_bytes() == before


def test_b8_force_on_a_fresh_root_just_writes(sandbox):
    repo = _git_repo(sandbox)
    code, out = _run("new-product", "--name", NAME, "--repo", str(repo), "--force")
    assert code in (0, 1), out
    assert _written(sandbox).is_file()


# --------------------------------------------------------------------------
# Behavior 9 -- an unsafe name is refused before anything is created
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "a/b", ".."])
def test_b9_unsafe_name_refuses_and_creates_nothing(sandbox, bad):
    repo = _git_repo(sandbox)
    code, out = _run("new-product", "--name", bad, "--repo", str(repo))
    assert code == 2, out
    assert "--name" in out
    products = sandbox / "products"
    leaked = sorted(p.name for p in products.rglob("*")) if products.exists() else []
    assert leaked == [], f"refusal must create nothing, found {leaked}"


# --------------------------------------------------------------------------
# Behavior 10 -- flags land verbatim, and the branch default is main
# --------------------------------------------------------------------------
def test_b10_flags_land_verbatim_in_the_written_json(sandbox):
    repo = _git_repo(sandbox)
    code, out = _run("new-product", "--name", NAME, "--repo", str(repo),
                     "--test-cmd", "pytest -q", "--branch", "trunk")
    assert code in (0, 1), out
    raw = json.loads(_written(sandbox).read_text())
    assert raw["test_cmd"] == "pytest -q"
    assert raw["branch"] == "trunk"


def test_b10_branch_defaults_to_main_when_both_flags_are_omitted(sandbox):
    repo = _git_repo(sandbox)
    _run("new-product", "--name", NAME, "--repo", str(repo))
    raw = json.loads(_written(sandbox).read_text())
    assert raw["branch"] == "main"
    assert raw["test_cmd"].strip(), "a scaffold must ship a runnable quality check"


# --------------------------------------------------------------------------
# Behavior 11 -- a paste-ready roster snippet, and the live roster untouched
# --------------------------------------------------------------------------
def test_b11_stdout_carries_a_paste_ready_work_items_snippet(sandbox):
    roster_before = _ROSTER.read_bytes() if _ROSTER.exists() else None
    repo = _git_repo(sandbox)
    code, out = _run("new-product", "--name", NAME, "--repo", str(repo))
    assert code in (0, 1), out
    assert "work_items" in out
    assert str(_written(sandbox)) in out
    snippet = out[out.index("work_items"):]
    assert '"name"' in snippet and '"config"' in snippet
    roster_after = _ROSTER.read_bytes() if _ROSTER.exists() else None
    assert roster_after == roster_before, "the verb must never edit the live roster"


# --------------------------------------------------------------------------
# Behavior 12 -- the scaffold never escapes its root
# --------------------------------------------------------------------------
def test_b12_scaffold_never_escapes_the_patched_foundry_root(sandbox):
    repo = _git_repo(sandbox)
    _run("new-product", "--name", NAME, "--repo", str(repo))
    assert _written(sandbox).is_file()
    assert not (_REAL_PRODUCTS / NAME).exists(), (
        "with FOUNDRY patched, nothing may be created under the real products/"
    )


def test_b12_a_refused_run_also_leaves_the_real_checkout_alone(sandbox):
    repo = _git_repo(sandbox)
    _run("new-product", "--name", "a/b", "--repo", str(repo))
    assert not (_REAL_PRODUCTS / "a").exists()
    assert not (_REAL_PRODUCTS / NAME).exists()


# --------------------------------------------------------------------------
# Behavior 13 -- the on-ramp doc uses the verb instead of the failing recipe
# --------------------------------------------------------------------------
def test_b13_usage_md_uses_the_new_verb_not_the_failing_cp_recipe():
    text = _USAGE.read_text()
    assert "new-product" in text
    assert _OLD_RECIPE not in text


# --------------------------------------------------------------------------
# Acceptance-criteria oracles
# --------------------------------------------------------------------------
def test_ac_both_modules_import_and_expose_the_new_surface():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert callable(foundry.product_config_template)
    assert callable(foundry.new_product_cli)


def test_ac_the_verb_is_registered_in_the_cli():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        with pytest.raises(SystemExit):
            foundry.main(["--help"])
    assert "new-product" in buf.getvalue()


def test_ac_new_product_requires_no_loadable_product_config(tmp_path, monkeypatch):
    """The newcomer case: no product config exists ANYWHERE yet -- which is only
    possible if the verb is dispatched BEFORE the config is loaded."""
    (tmp_path / "roles").mkdir()
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    monkeypatch.chdir(tmp_path)
    repo = _git_repo(tmp_path)
    code, out = _run("new-product", "--name", NAME, "--repo", str(repo))
    assert code == 0, out
    assert _written(tmp_path).is_file()


def test_ac_roadmap_records_exist_within_the_documented_bounds():
    index = _ROADMAP.read_text()
    archive = _ARCHIVE.read_text()
    rows = [ln for ln in index.splitlines() if ln.strip().startswith("- iter 137 ")]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, f"index row is {len(rows[0])} chars"
    assert [ln for ln in archive.splitlines() if ln.startswith("- **iter 137 ")]
    assert len(index) < foundry.ROADMAP_SIZE_WARN_CHARS
    assert foundry.roadmap_archive_gaps(index, archive) == []
