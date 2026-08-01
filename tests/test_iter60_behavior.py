"""Black-box behaviour tests for iter 60 -- the NEW read-only
`foundry lint-config --config <cfg> [--json]` product-config linter.

It inspects a resolved `ProductConfig` for the misconfigurations that silently
waste a shift or defeat the push guard and reports leveled findings with a
scriptable 0/1/2 exit code (0 OK-or-warnings-only / 1 config-errors /
2 unreadable-config). It is the CONFIG-validation complement to `doctor`'s ENV
validation and `lint-spec`'s SPEC validation. Purely additive / dormant.

ISOLATION CONTRACT (honored): every test below encodes the iter-60 PM spec's
Expected Behaviors (1-9) and is driven purely against the PUBLIC interface --
the pure `foundry.lint_config(cfg)` core over `ProductConfig`s built with the
product's own public constructor, its dataclass properties / `render()` /
`to_dict()`, and the `foundry.lint_config_cli(...)` / `foundry.main(["lint-config",
...])` CLI over temp config JSON files -- plus public RUNTIME introspection
(compiled `__code__.co_names`, `dispatcher` attributes) and the documented
`import foundry, dispatcher` subprocess probe. The implementation SOURCE
(foundry.py / dispatcher.py logic), the reviewer's notes, and `git diff` were
NOT read as logic to mirror; tests assert the SPEC's behaviors, not impl quirks.
DISCLOSURE: the engineer's `engineer.md` was inadvertently opened once at the
start of this stage; nothing from it was used to shape a test -- all assertions
below derive from the spec + observed public behaviour probed by running the
product. Fully offline & deterministic: no network, no git subprocess, no real
push; the sole subprocess is the `import foundry, dispatcher` dormancy probe.
Every path is built at RUNTIME from the pytest `tmp_path` fixture (never a
source-literal home path) and every string is SYNTHETIC, so the committed
leak-guard passes on the ship commit.
"""
import dataclasses
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# constants / helpers
# --------------------------------------------------------------------------
NEW_SYMBOLS = ("ConfigFinding", "ConfigLint", "lint_config", "lint_config_cli")
# the control-flow / pipeline fns must reference NONE of the new surface
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")
TO_DICT_KEYS = ("config_path", "findings", "n_errors", "n_warnings",
                "ok", "verdict", "exit_code")


def _valid_cfg(tmp_path, **over):
    """A directly-constructed, all-VALID ProductConfig using ABSOLUTE tmp paths
    (so `.resolve()` is a no-op on the set paths and writes nothing). repo has a
    `.git` entry; vision/roadmap/quality_ref/roles_dir all exist; name /
    allowed_push_repo / test_cmd non-empty; push_enabled True."""
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
    data = dict(
        name="prod",
        repo=str(repo),
        allowed_push_repo="prod",
        vision=str(vision),
        roadmap=str(roadmap),
        quality_ref=str(qref),
        roles_dir=str(roles),
        test_cmd="uv run pytest",
        push_enabled=True,
    )
    data.update(over)
    return foundry.ProductConfig(**data)


def _fields(lint):
    return [(f.field, f.level) for f in lint.findings]


def _by_field(lint, field):
    return [f for f in lint.findings if f.field == field]


def _write_cfg(tmp_path, fname="config.json", **over):
    """Write a product-config JSON to tmp AND set work_root under tmp so
    `load_config`'s mkdir(work_root) never pollutes the product repo tree."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    vision = tmp_path / "VISION.md"
    vision.write_text("intent")
    data = dict(
        name="prod",
        repo=str(repo),
        allowed_push_repo="prod",
        vision=str(vision),
        work_root=str(tmp_path / "work"),
        test_cmd="uv run pytest",
        push_enabled=True,
    )
    data.update(over)
    p = tmp_path / fname
    p.write_text(json.dumps(data))
    return str(p)


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters for the --json path: the JSON must be the ENTIRE
    stdout, uncontaminated by any stderr message."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


# ==========================================================================
# Behavior 1 -- an all-valid config is clean
# ==========================================================================
def test_b1_all_valid_is_clean(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path))
    assert lint.findings == (), f"expected no findings; got {_fields(lint)}"
    assert lint.ok is True
    assert lint.n_errors == 0
    assert lint.n_warnings == 0
    assert lint.verdict == "OK"
    assert lint.exit_code == 0


def test_b1_clean_holds_for_push_enabled_false(tmp_path):
    # push_enabled either value must still be clean when everything else is set
    lint = foundry.lint_config(_valid_cfg(tmp_path, push_enabled=False))
    assert lint.findings == ()
    assert lint.verdict == "OK"


# ==========================================================================
# Behavior 2 -- missing repo path is an error
# ==========================================================================
def test_b2_missing_repo_is_error(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, repo=str(tmp_path / "nope")))
    repo_findings = _by_field(lint, "repo")
    assert len(repo_findings) == 1, f"expected exactly one repo finding; got {_fields(lint)}"
    assert repo_findings[0].level == "error"
    assert "does not exist" in repo_findings[0].detail
    assert lint.ok is False
    assert lint.exit_code == 1
    assert lint.verdict == "PROBLEMS"


# ==========================================================================
# Behavior 3 -- a repo that exists but is not a git repo is an error
# ==========================================================================
def test_b3_repo_without_git_is_error(tmp_path):
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    lint = foundry.lint_config(_valid_cfg(tmp_path, repo=str(nogit)))
    repo_findings = _by_field(lint, "repo")
    assert len(repo_findings) == 1, f"expected exactly one repo finding; got {_fields(lint)}"
    assert repo_findings[0].level == "error"
    assert "not a git" in repo_findings[0].detail
    assert lint.ok is False
    assert lint.exit_code == 1


def test_b3_repo_with_git_produces_no_repo_finding(tmp_path):
    # the valid cfg's repo HAS a .git entry -> no repo finding at all
    lint = foundry.lint_config(_valid_cfg(tmp_path))
    assert _by_field(lint, "repo") == []


# ==========================================================================
# Behavior 4 -- empty allowed_push_repo is gated on push_enabled
# ==========================================================================
def test_b4_empty_push_repo_with_push_enabled_is_error(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, allowed_push_repo="", push_enabled=True))
    apr = _by_field(lint, "allowed_push_repo")
    assert len(apr) == 1, f"expected exactly one allowed_push_repo finding; got {_fields(lint)}"
    assert apr[0].level == "error"
    assert lint.exit_code == 1


def test_b4_empty_push_repo_with_push_disabled_is_no_finding(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, allowed_push_repo="", push_enabled=False))
    assert _by_field(lint, "allowed_push_repo") == []
    assert lint.ok is True
    assert lint.verdict == "OK"


# ==========================================================================
# Behavior 5 -- empty test_cmd and missing roles_dir are both errors,
#               in a FIXED order (test_cmd BEFORE roles_dir)
# ==========================================================================
def test_b5_test_cmd_and_roles_dir_errors_and_order(tmp_path):
    lint = foundry.lint_config(
        _valid_cfg(tmp_path, test_cmd="", roles_dir=str(tmp_path / "noroles"))
    )
    assert _by_field(lint, "test_cmd") and _by_field(lint, "test_cmd")[0].level == "error"
    assert _by_field(lint, "roles_dir") and _by_field(lint, "roles_dir")[0].level == "error"
    assert lint.n_errors >= 2
    order = [f.field for f in lint.findings]
    assert order.index("test_cmd") < order.index("roles_dir"), (
        f"test_cmd finding must precede roles_dir finding; order was {order}"
    )


def test_b5_whitespace_test_cmd_is_error(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, test_cmd="   "))
    tc = _by_field(lint, "test_cmd")
    assert len(tc) == 1 and tc[0].level == "error"


# ==========================================================================
# Behavior 6 -- vision: missing file is an error, an unset path is a warning
# ==========================================================================
def test_b6_vision_missing_file_is_error(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, vision=str(tmp_path / "novis.md")))
    v = _by_field(lint, "vision")
    assert len(v) == 1 and v[0].level == "error", f"got {_fields(lint)}"
    assert lint.exit_code == 1


def test_b6_vision_unset_is_warning(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, vision=""))
    v = _by_field(lint, "vision")
    assert len(v) == 1 and v[0].level == "warn", f"got {_fields(lint)}"
    assert lint.n_errors == 0
    assert lint.ok is True
    assert lint.exit_code == 0
    assert lint.verdict == "WARNINGS"
    assert lint.n_warnings == 1


# ==========================================================================
# Behavior 7 -- roadmap & quality_ref missing-file cases are warnings,
#               never errors; an EMPTY quality_ref is optional (no finding)
# ==========================================================================
def test_b7_roadmap_and_quality_ref_missing_are_warnings(tmp_path):
    lint = foundry.lint_config(
        _valid_cfg(tmp_path,
                   roadmap=str(tmp_path / "nr.md"),
                   quality_ref=str(tmp_path / "nq"))
    )
    rm = _by_field(lint, "roadmap")
    qr = _by_field(lint, "quality_ref")
    assert len(rm) == 1 and rm[0].level == "warn", f"got {_fields(lint)}"
    assert len(qr) == 1 and qr[0].level == "warn", f"got {_fields(lint)}"
    assert lint.n_errors == 0
    assert lint.n_warnings == 2
    assert lint.ok is True
    assert lint.exit_code == 0
    assert lint.verdict == "WARNINGS"


def test_b7_empty_quality_ref_is_optional_no_finding(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, quality_ref=""))
    assert _by_field(lint, "quality_ref") == []
    assert lint.verdict == "OK"


# ==========================================================================
# Behavior 8 -- rendering + serialization integrity
# ==========================================================================
def test_b8_to_dict_keys_order_and_finding_shape(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, repo=str(tmp_path / "nope")))
    d = lint.to_dict()
    assert tuple(d.keys()) == TO_DICT_KEYS, f"key order wrong: {list(d.keys())}"
    assert isinstance(d["findings"], list) and d["findings"], "expected >=1 finding dict"
    for entry in d["findings"]:
        assert tuple(entry.keys()) == ("field", "level", "detail"), entry


def test_b8_to_dict_json_round_trips(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, vision="", roadmap=str(tmp_path / "nr")))
    d = lint.to_dict()
    assert json.loads(json.dumps(d)) == d


def test_b8_render_first_line_names_config_last_line_verdict(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path, repo=str(tmp_path / "nope")))
    lines = lint.render().splitlines()
    assert lines[0].startswith("foundry lint-config"), f"first line: {lines[0]!r}"
    assert "prod" in lines[0], f"first line must name the config: {lines[0]!r}"
    assert lines[-1] == "verdict: PROBLEMS", f"last line: {lines[-1]!r}"


def test_b8_clean_render_lists_no_findings_still_verdict_ok(tmp_path):
    lint = foundry.lint_config(_valid_cfg(tmp_path))
    text = lint.render()
    lines = text.splitlines()
    assert lines[-1] == "verdict: OK", f"last line: {lines[-1]!r}"
    # a clean config lists NO per-finding lines
    assert "[error]" not in text and "[warn]" not in text, text


def test_b8_verdict_tokens_map_to_exit_codes(tmp_path):
    # OK -> 0, WARNINGS -> 0, PROBLEMS -> 1 (single source of truth)
    ok = foundry.lint_config(_valid_cfg(tmp_path))
    warn = foundry.lint_config(_valid_cfg(tmp_path, vision=""))
    prob = foundry.lint_config(_valid_cfg(tmp_path, repo=str(tmp_path / "nope")))
    assert (ok.verdict, ok.exit_code) == ("OK", 0)
    assert (warn.verdict, warn.exit_code) == ("WARNINGS", 0)
    assert (prob.verdict, prob.exit_code) == ("PROBLEMS", 1)


def test_b8_never_raises_and_does_not_mutate_caller(tmp_path):
    # a config with an unresolved {FOUNDRY} + empty paths must not raise and the
    # caller's own object must be byte-identical afterward (copy-then-resolve).
    cfg = foundry.ProductConfig(name="x", repo="{FOUNDRY}/z", allowed_push_repo="x")
    snap = dataclasses.asdict(cfg)
    lint = foundry.lint_config(cfg)  # must not raise
    assert isinstance(lint, foundry.ConfigLint)
    assert dataclasses.asdict(cfg) == snap, "lint_config must not mutate the caller"


# ==========================================================================
# Behavior 9 -- CLI + dispatch + dormancy
# ==========================================================================
def test_b9_cli_valid_returns_0_and_prints_render(tmp_path):
    rc, out, err = _capture(lambda: foundry.lint_config_cli(_write_cfg(tmp_path)))
    assert rc == 0, f"stderr={err!r}"
    assert out.splitlines()[0].startswith("foundry lint-config")
    assert out.strip().splitlines()[-1] == "verdict: OK"


def test_b9_cli_error_config_returns_1(tmp_path):
    path = _write_cfg(tmp_path, repo=str(tmp_path / "nope"))
    rc, out, err = _capture(lambda: foundry.lint_config_cli(path))
    assert rc == 1
    assert out.strip().splitlines()[-1] == "verdict: PROBLEMS"


def test_b9_cli_missing_config_returns_2_with_message(tmp_path):
    missing = str(tmp_path / "missing.json")
    rc, out, err = _capture(lambda: foundry.lint_config_cli(missing))
    assert rc == 2
    assert "lint-config" in (out + err)


def test_b9_cli_invalid_json_returns_2(tmp_path):
    bad = tmp_path / "inv.json"
    bad.write_text("{ not valid json")
    rc, out, err = _capture(lambda: foundry.lint_config_cli(str(bad)))
    assert rc == 2


def test_b9_cli_json_prints_parseable_doc_same_exit(tmp_path):
    good = _write_cfg(tmp_path, fname="good.json")
    rc, out, err = _capture(lambda: foundry.lint_config_cli(good, as_json=True))
    assert rc == 0
    doc = json.loads(out)  # entire stdout must be one parseable JSON document
    assert tuple(doc.keys()) == TO_DICT_KEYS

    prob = _write_cfg(tmp_path, fname="prob.json", repo=str(tmp_path / "nope"))
    rc, out, err = _capture(lambda: foundry.lint_config_cli(prob, as_json=True))
    assert rc == 1
    assert json.loads(out)["verdict"] == "PROBLEMS"


def test_b9_cli_writes_nothing_to_repo_tree(tmp_path):
    good = _write_cfg(tmp_path)
    repo = tmp_path / "repo"
    before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    _capture(lambda: foundry.lint_config_cli(good))
    after = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert before == after, "lint-config must not write into the repo tree"


def test_b9_main_routes_and_returns_same_code(tmp_path):
    good = _write_cfg(tmp_path, fname="good.json")
    bad = _write_cfg(tmp_path, fname="bad.json", repo=str(tmp_path / "nope"))
    rc, out, _ = _capture(lambda: foundry.main(["lint-config", "--config", good]))
    assert rc == 0
    rc, out, _ = _capture(lambda: foundry.main(["lint-config", "--config", bad]))
    assert rc == 1


def test_b9_main_missing_config_returns_2_proving_dispatch_before_load_config(tmp_path):
    # a missing --config path must return 2 GRACEFULLY; if lint-config were
    # dispatched AFTER the top-level load_config, load_config's own read would
    # raise unhandled instead.
    missing = str(tmp_path / "gone.json")
    rc, out, err = _capture(lambda: foundry.main(["lint-config", "--config", missing]))
    assert rc == 2


def test_b9_main_json_flag(tmp_path):
    good = _write_cfg(tmp_path)
    rc, out, _ = _capture(lambda: foundry.main(["lint-config", "--config", good, "--json"]))
    assert rc == 0
    assert json.loads(out)["verdict"] == "OK"


def test_b9_dormancy_control_flow_fns_do_not_reference_new_symbols():
    for fn_name in CONTROL_FLOW_FNS:
        refs = _co_names_deep(getattr(foundry, fn_name)) & set(NEW_SYMBOLS)
        assert not refs, f"{fn_name} unexpectedly references {refs}"


def test_b9_positive_wiring_main_and_cli():
    assert "lint_config_cli" in _co_names_deep(foundry.main)
    assert "lint_config" in _co_names_deep(foundry.lint_config_cli)


def test_b9_dispatcher_has_none_of_the_new_symbols():
    for s in NEW_SYMBOLS:
        assert not hasattr(dispatcher, s), f"dispatcher unexpectedly exposes {s}"


def test_b9_import_foundry_and_dispatcher_ok():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=root, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"import failed: {r.stderr}"


def test_b9_no_existing_subcommand_regressed(tmp_path):
    # adding lint-config must not break sibling on-demand subcommands; probe a
    # representative one that manages its own load (lint-spec) and confirm the
    # dispatcher/parser still routes it.
    spec = tmp_path / "pm.md"
    spec.write_text("# spec\n\n## Feature\nx\n\n## Why\nx\n\n"
                    "## Expected Behaviors\n1. x\n\n## Acceptance Criteria\n- x\n\n"
                    "## Out of Scope\nx\n\n## Size self-check\nx\n")
    rc, out, err = _capture(lambda: foundry.main(["lint-spec", "--file", str(spec)]))
    assert isinstance(rc, int)  # routed without raising
