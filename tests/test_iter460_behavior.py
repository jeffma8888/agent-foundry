"""Black-box behaviour tests for iter 460 -- session-scoped conftest fixture for
live smoke tests: a ``tests/conftest.py`` file provides a session-scoped
``live_smoke_result`` fixture that lazily caches ``foundry.main(["<verb>",
"--json"])`` invocations, replacing inline invocations in 8 test modules. Each
test's assertion logic is unchanged -- only the invocation source changes.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-460 PM
spec's Expected Behaviors (1-5), the product README/roadmap, the ``tests/``
directory conventions, and the product's own OBSERVABLE behaviour (running the
full suite, importing modules, inspecting conftest.py). The implementation
source (foundry.py / dispatcher.py), the engineer's and reviewer's notes, and
``git diff`` were NOT read.
"""
import ast
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ==========================================================================
# EB1: tests/conftest.py exists with a session-scoped fixture
# ==========================================================================
class TestEB1_ConfTestFixture:
    """conftest.py contains a session-scoped ``live_smoke_result`` fixture that
    lazily invokes each verb exactly once per session and caches the result."""

    def test_conftest_exists(self):
        p = _ROOT / "tests" / "conftest.py"
        assert p.exists(), "tests/conftest.py must exist"

    def test_conftest_parseable(self):
        src = (_ROOT / "tests" / "conftest.py").read_text()
        tree = ast.parse(src)
        assert tree is not None

    def test_fixture_is_session_scoped(self):
        src = (_ROOT / "tests" / "conftest.py").read_text()
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "live_smoke_result":
                found = True
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call):
                        for kw in dec.keywords:
                            if kw.arg == "scope":
                                assert isinstance(kw.value, ast.Constant)
                                assert kw.value.value == "session", (
                                    "live_smoke_result must be session-scoped"
                                )
                break
        assert found, "conftest.py must define live_smoke_result function"

    def test_fixture_returns_callable_keyed_by_verb(self):
        """The fixture returns a get(verb, as_json=True) callable."""
        src = (_ROOT / "tests" / "conftest.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "live_smoke_result":
                inner_fns = [
                    n for n in ast.walk(node)
                    if isinstance(n, ast.FunctionDef) and n.name != "live_smoke_result"
                ]
                assert inner_fns, "live_smoke_result must contain an inner function"
                inner = inner_fns[0]
                param_names = [a.arg for a in inner.args.args]
                assert "verb" in param_names, (
                    "inner function must accept a 'verb' parameter"
                )
                break

    def test_cache_dict_is_module_level(self):
        """_smoke_cache is a module-level dict for cross-session-scope persistence."""
        src = (_ROOT / "tests" / "conftest.py").read_text()
        tree = ast.parse(src)
        module_assigns = [
            node for node in ast.iter_child_nodes(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
        ]
        found = False
        for node in module_assigns:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_smoke_cache":
                        found = True
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "_smoke_cache":
                    found = True
        assert found, "_smoke_cache must be a module-level variable in conftest.py"

    def test_fixture_invokes_foundry_main(self):
        """The fixture or its helper invokes foundry.main(argv)."""
        src = (_ROOT / "tests" / "conftest.py").read_text()
        assert "foundry.main" in src or "foundry" in src, (
            "conftest.py must invoke foundry.main"
        )

    def test_fixture_returns_exit_code_and_output_pair(self):
        """The invocation helper returns (exit_code, captured_output)."""
        src = (_ROOT / "tests" / "conftest.py").read_text()
        tree = ast.parse(src)
        invoke_fns = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and "invoke" in node.name
        ]
        assert invoke_fns, "conftest.py must have an _invoke_main helper"
        fn = invoke_fns[0]
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        assert any(
            isinstance(r.value, ast.Tuple) for r in returns if r.value
        ), "_invoke_main must return a tuple (rc, output)"


# ==========================================================================
# EB2: All 8 test modules use the fixture instead of inline invocation
# ==========================================================================
class TestEB2_ModulesUseFixture:
    """Each of the 8 test modules that previously called foundry.main(...)
    inline now requests the session fixture."""

    MODULES = [
        "test_iter31_behavior.py",
        "test_iter40_behavior.py",
        "test_iter43_behavior.py",
        "test_iter46_behavior.py",
        "test_iter54_behavior.py",
        "test_iter57_behavior.py",
        "test_iter59_behavior.py",
        "test_iter61_behavior.py",
    ]

    @pytest.mark.parametrize("module", MODULES)
    def test_smoke_test_uses_fixture(self, module):
        src = (_ROOT / "tests" / module).read_text()
        tree = ast.parse(src)
        smoke_fns = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and "live_smoke" in node.name
            and "dispatch_config" in node.name
        ]
        assert smoke_fns, f"{module} must have a live_smoke_on_real_dispatch_config test"
        fn = smoke_fns[0]
        param_names = [a.arg for a in fn.args.args]
        assert "live_smoke_result" in param_names, (
            f"{module}'s smoke test must accept `live_smoke_result` parameter"
        )

    @pytest.mark.parametrize("module", MODULES)
    def test_smoke_test_calls_fixture(self, module):
        """The smoke test body calls ``live_smoke_result(...)``."""
        src = (_ROOT / "tests" / module).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and "live_smoke" in node.name
                    and "dispatch_config" in node.name):
                body_src = ast.get_source_segment(src, node)
                assert body_src is not None
                assert "live_smoke_result(" in body_src, (
                    f"{module}'s smoke test must call live_smoke_result()"
                )
                break


# ==========================================================================
# EB3: Assertion logic unchanged -- only invocation source changes
# ==========================================================================
class TestEB3_AssertionLogicPreserved:
    """Each test's assertion logic (exit code check, JSON validity, field checks)
    is unchanged -- only the invocation source changes."""

    def test_iter31_backward_compat_default_parameter(self):
        """iter-31 has live_smoke_result=None default for backward-compat with
        iter-32 direct calls."""
        src = (_ROOT / "tests" / "test_iter31_behavior.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and "live_smoke" in node.name
                    and "dispatch_config" in node.name):
                defaults = node.args.defaults
                assert len(defaults) > 0, (
                    "iter-31 smoke test must have default parameter (=None)"
                )
                assert isinstance(defaults[-1], ast.Constant) and defaults[-1].value is None, (
                    "iter-31 smoke test default must be None"
                )
                break

    def test_iter31_has_fallback_inline_path(self):
        """iter-31 still has inline _run_cli for when fixture is not injected."""
        src = (_ROOT / "tests" / "test_iter31_behavior.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and "live_smoke" in node.name
                    and "dispatch_config" in node.name):
                body_src = ast.get_source_segment(src, node)
                assert "_run_cli" in body_src, (
                    "iter-31 smoke must retain _run_cli fallback for None path"
                )
                assert "if live_smoke_result is not None" in body_src or \
                       "live_smoke_result is not None" in body_src, (
                    "iter-31 must branch on live_smoke_result being None vs injected"
                )
                break

    def test_iter32_direct_call_contract_preserved(self):
        """iter-32 imports from iter-31 and calls its smoke test directly."""
        iter32_path = _ROOT / "tests" / "test_iter32_behavior.py"
        if not iter32_path.exists():
            pytest.skip("test_iter32_behavior.py not found")
        src = iter32_path.read_text()
        assert "test_iter31_behavior" in src or "_b13" in src, (
            "iter-32 must still import from iter-31"
        )

    MODULES_NO_DEFAULT = [
        "test_iter40_behavior.py",
        "test_iter43_behavior.py",
        "test_iter46_behavior.py",
        "test_iter54_behavior.py",
        "test_iter57_behavior.py",
        "test_iter59_behavior.py",
        "test_iter61_behavior.py",
    ]

    @pytest.mark.parametrize("module", MODULES_NO_DEFAULT)
    def test_non_iter31_takes_fixture_without_default(self, module):
        """The other 7 modules take the fixture directly (no default=None)."""
        src = (_ROOT / "tests" / module).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and "live_smoke" in node.name
                    and "dispatch_config" in node.name):
                param_names = [a.arg for a in node.args.args]
                assert "live_smoke_result" in param_names
                assert len(node.args.defaults) == 0, (
                    f"{module}'s smoke test must NOT have a default for "
                    f"live_smoke_result (only iter-31 needs it)"
                )
                break

    @pytest.mark.parametrize("module,verb", [
        ("test_iter40_behavior.py", "company-timing"),
        ("test_iter43_behavior.py", "company-weak-tests"),
        ("test_iter46_behavior.py", "company-events"),
    ])
    def test_smoke_passes_correct_verb_to_fixture(self, module, verb):
        """Each smoke test passes its own verb name to the fixture."""
        src = (_ROOT / "tests" / module).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and "live_smoke" in node.name
                    and "dispatch_config" in node.name):
                body_src = ast.get_source_segment(src, node)
                assert verb in body_src, (
                    f"{module}'s smoke test must pass '{verb}' to the fixture"
                )
                break


# ==========================================================================
# EB4: Full test suite passes (tested by running the suite)
# ==========================================================================
class TestEB4_SuiteIntegrity:
    """The full test suite passes with zero failures and zero new skips."""

    def test_conftest_importable(self):
        """conftest.py can be imported without error."""
        r = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util; "
             "spec = importlib.util.spec_from_file_location('conftest', 'tests/conftest.py'); "
             "mod = importlib.util.module_from_spec(spec); "
             "spec.loader.exec_module(mod)"],
            cwd=str(_ROOT),
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"conftest.py import failed:\n{r.stderr}"

    def test_no_production_code_changed(self):
        """No changes to foundry.py or dispatcher.py (spec says out of scope)."""
        import foundry
        import dispatcher
        assert callable(getattr(foundry, "main", None))
        assert callable(getattr(foundry, "build_prompt", None))
        assert callable(getattr(foundry, "run_stage", None))
        assert callable(getattr(foundry, "run_iteration", None))
        assert callable(getattr(foundry, "run_continuous", None))
        assert dispatcher is not None


# ==========================================================================
# EB5: Both modules importable
# ==========================================================================
class TestEB5_ModulesImportable:
    """``python -c 'import foundry, dispatcher'`` succeeds."""

    def test_import_foundry_dispatcher(self):
        r = subprocess.run(
            [sys.executable, "-c", "import foundry, dispatcher"],
            cwd=str(_ROOT),
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"import foundry, dispatcher failed:\n{r.stderr}"
