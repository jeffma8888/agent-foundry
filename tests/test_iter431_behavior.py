"""Iteration 431 -- restore two missing product configs (reflect-mcp,
graphql-rest-gateway) from commit 7510487 with the repo field changed from
absolute-home path to tilde form.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-431 PM
spec's Expected Behaviors (1-7), the product README/roadmap, the `tests/`
conventions, and the product's OWN OBSERVABLE behaviour by RUNNING it (the
`foundry lint-config` CLI and `scripts/leak_guard.py`). The implementation
SOURCE of `foundry.py` / `dispatcher.py`, the engineer's and reviewer's notes,
and `git diff` were NOT read for their logic. Fully offline & deterministic:
the only subprocess is the documented CLI invocation.
"""
import json
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

_CONFIGS = [
    ("reflect-mcp", _ROOT / "products" / "reflect-mcp" / "config.json"),
    ("graphql-rest-gateway", _ROOT / "products" / "graphql-rest-gateway" / "config.json"),
]

_EXPECTED_KEYS = {
    "_comment", "name", "repo", "allowed_push_repo", "branch", "vision",
    "roadmap", "quality_ref", "test_cmd", "roles_dir", "work_root",
    "quality_bar", "push_enabled", "dual_pm_scouts",
}


# EB1 & EB2: configs exist and are valid JSON with correct repo field
@pytest.mark.parametrize("product,path", _CONFIGS, ids=[c[0] for c in _CONFIGS])
def test_b1b2_config_exists_and_valid_json(product, path):
    assert path.exists(), f"{path} must exist"
    data = json.loads(path.read_text())
    assert isinstance(data, dict), "config must be a JSON object"
    assert data["name"] == product, f"name must be {product!r}"
    assert data["repo"] == f"~/projects/{product}", (
        f"repo must be tilde form ~/projects/{product}"
    )
    assert set(data.keys()) == _EXPECTED_KEYS, (
        f"keys must match 7510487 exactly; extra={set(data.keys()) - _EXPECTED_KEYS}, "
        f"missing={_EXPECTED_KEYS - set(data.keys())}"
    )


# EB1 & EB2: non-repo fields preserved from 7510487
@pytest.mark.parametrize("product,path", _CONFIGS, ids=[c[0] for c in _CONFIGS])
def test_b1b2_non_repo_fields_preserved(product, path):
    data = json.loads(path.read_text())
    assert data["allowed_push_repo"] == product
    assert data["branch"] == "main"
    assert data["vision"] == f"~/projects/{product}/VISION.md"
    assert data["roadmap"] == f"~/projects/{product}/PRODUCT.md"
    assert data["roles_dir"] == "{FOUNDRY}/roles"
    assert data["work_root"] == f"{{FOUNDRY}}/products/{product}"
    assert data["push_enabled"] is True
    assert data["dual_pm_scouts"] is True


# EB3 & EB4: lint-config passes on both
@pytest.mark.parametrize("product,path", _CONFIGS, ids=[c[0] for c in _CONFIGS])
def test_b3b4_lint_config_passes(product, path):
    r = subprocess.run(
        [sys.executable, "foundry.py", "lint-config", "--config", str(path)],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (
        f"lint-config must exit 0 for {product}; stderr:\n{r.stderr}\nstdout:\n{r.stdout}"
    )
    combined = r.stdout + r.stderr
    assert re.search(r"errors:\s*0", combined), (
        f"lint-config must report 0 errors for {product}; output:\n{combined}"
    )


_DENYLIST_NEEDLE = "/" + "Users" + "/"


@pytest.mark.parametrize("product,path", _CONFIGS, ids=[c[0] for c in _CONFIGS])
def test_b5_no_users_path(product, path):
    text = path.read_text()
    assert _DENYLIST_NEEDLE not in text, (
        f"{product} config must not contain the absolute-home prefix"
    )


# EB6: leak guard reports zero findings on both configs
def test_b6_leak_guard_clean():
    config_paths = [str(p) for _, p in _CONFIGS]
    r = subprocess.run(
        [sys.executable, "scripts/leak_guard.py", "--files"] + config_paths,
        cwd=str(_ROOT), capture_output=True, text=True, timeout=30,
    )
    combined = r.stdout + r.stderr
    assert r.returncode == 0, (
        f"leak_guard must exit 0 on both configs; stderr:\n{r.stderr}\nstdout:\n{r.stdout}"
    )
    finding_match = re.search(r"(\d+)\s+finding", combined)
    if finding_match:
        assert finding_match.group(1) == "0", (
            f"leak_guard must report 0 findings; got {finding_match.group(1)}; output:\n{combined}"
        )


# EB5 (strengthened): tilde-form repo convention matches all external-repo configs
def test_b5_convention_all_external_repos_use_tilde():
    config_dir = _ROOT / "products"
    tilde_count = 0
    checked = 0
    for cfg_path in sorted(config_dir.glob("*/config.json")):
        data = json.loads(cfg_path.read_text())
        repo = data.get("repo", "")
        if repo.startswith("{"):
            continue
        checked += 1
        if repo.startswith("~/"):
            tilde_count += 1
        else:
            pytest.fail(
                f"{cfg_path.name} has non-tilde repo: {repo!r}"
            )
    assert checked >= 3, (
        f"expected at least 3 external-repo configs; found {checked}"
    )
    assert tilde_count == checked, "all external-repo configs must use tilde form"
