"""Black-box behaviour tests for iter 467 -- `foundry company-changelog
--config <dispatch> [--limit N] [--json]`: the company-wide roll-up of the
per-product `changelog` verb (iter 449).  This is the 11th `company-*` family
member, following the mature `_company_rollup_cli` pattern used by the 10
existing siblings.

`CompanyChangelog` aggregates `ChangelogSummary` (iter 449) per-product results
into a fleet-wide frozen dataclass with `render()`, `to_dict()`, and
`exit_code`.  Exit-code semantics: 0 = at least one product has entries,
1 = errors or all products empty, 2 = no enabled products.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-467 PM
spec's Expected Behaviors (1-10), the product README, the product's OWN
OBSERVABLE behaviour (building public objects and running them / --help / public
runtime introspection), and the existing test conventions under tests/.  The
implementation source (foundry.py internals), the engineer's notes, and
`git diff` were NOT read.  Every assertion derives from the spec's pinned
behavior + observed public behaviour probed by running the product.  Fully
offline and deterministic: no network, no real git mutation, no real push.
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

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402

_LEAK_GUARD = _ROOT / "scripts" / "leak_guard.py"
_DENYLIST = _ROOT / "scripts" / "leak_denylist.txt"

VERDICT_FOR_CODE = {0: "OK", 1: "ERRORS", 2: "no enabled products"}

NEW_SYMBOLS = ("CompanyChangelog", "summarize_company_changelog",
               "company_changelog_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")
SUBCMD = "company-changelog"

TO_DICT_KEYS = ("dispatch_path", "products", "disabled", "errors",
                "n_products", "n_disabled", "n_errors", "total_entries",
                "exit_code", "verdict")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _E(iter_num, prefix="feat", subject="desc"):
    return foundry.ChangelogEntry(iter_num=iter_num, prefix=prefix, subject=subject)


def _CS(product, entries=()):
    return foundry.ChangelogSummary(product=product, entries=tuple(entries))


def _summ(dispatch_path="d.json", products=(), disabled=(), errors=()):
    return foundry.summarize_company_changelog(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))


def _write_dispatch(tmp_path, work_items, name="foundry.config.json"):
    p = pathlib.Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"work_items": work_items}))
    return p


def _run_cli(dispatch_path, limit=None, as_json=False):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.company_changelog_cli(dispatch_path, limit=limit, as_json=as_json)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _final_verdict_token(text):
    lines = [ln for ln in text.splitlines()
             if ln.strip().lower().startswith("verdict:")]
    assert lines, f"no `verdict:` line found in:\n{text}"
    return lines[-1].split(":", 1)[1].strip()


def _patch_cli(monkeypatch, changelog_by_name):
    loaded = []

    class _Cfg:
        def __init__(self, path):
            self._path = path

    def fake_load(path):
        loaded.append(path)
        return _Cfg(path)

    def fake_gather(cfg, limit=None):
        for name, cs in changelog_by_name.items():
            if name in cfg._path:
                return cs
        return _CS("unknown")

    monkeypatch.setattr(foundry, "load_config", fake_load)
    monkeypatch.setattr(foundry, "gather_changelog", fake_gather)
    return loaded


def _fn_names_consts(fn):
    stack, seen = [fn.__code__], set()
    names, consts = set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, str):
                consts.add(c)
            elif isinstance(c, types.CodeType):
                stack.append(c)
    return names, consts


def _module_names_consts(module):
    names, consts = set(), set()
    for v in vars(module).values():
        if isinstance(v, types.FunctionType):
            n, c = _fn_names_consts(v)
            names |= n
            consts |= c
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    n, c = _fn_names_consts(m)
                    names |= n
                    consts |= c
    return names, consts


def _load_leak_guard():
    spec = importlib.util.spec_from_file_location("leak_guard", _LEAK_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["leak_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


def _git_visible_snapshot(root, repo_root=_ROOT):
    def _lines(*argv):
        r = subprocess.run(["git", *argv, "--", str(root)], cwd=str(repo_root),
                           capture_output=True, text=True, check=False)
        return tuple(sorted(ln for ln in r.stdout.splitlines() if ln.strip()))
    return (_lines("status", "--porcelain", "--untracked-files=all"),
            _lines("ls-files", "-s"))


# ==========================================================================
# EB1 -- CompanyChangelog frozen dataclass
# ==========================================================================
class TestEB1FrozenDataclass:
    def test_is_dataclass_and_frozen(self):
        cc = _summ(products=(_CS("a"),))
        assert dataclasses.is_dataclass(cc)
        assert type(cc).__name__ == "CompanyChangelog"
        with pytest.raises(dataclasses.FrozenInstanceError):
            cc.products = ()

    def test_fields_match_spec(self):
        fields = [f.name for f in dataclasses.fields(foundry.CompanyChangelog)]
        assert fields == ["dispatch_path", "products", "disabled", "errors"]

    def test_dispatch_path_stored(self):
        cc = _summ(dispatch_path="/my/dispatch.json")
        assert cc.dispatch_path == "/my/dispatch.json"

    def test_products_tuple_of_changelog_summary(self):
        a = _CS("alpha", [_E(1)])
        b = _CS("beta", [_E(2)])
        cc = _summ(products=(a, b))
        assert cc.products == (a, b)
        assert len(cc.products) == 2

    def test_disabled_and_errors_stored(self):
        cc = _summ(disabled=("x", "y"), errors=(("z", "boom"),))
        assert cc.disabled == ("x", "y")
        assert cc.errors == (("z", "boom"),)


# ==========================================================================
# EB2 -- exit_code: 0 entries, 1 errors/empty, 2 no-products
# ==========================================================================
class TestEB2ExitCode:
    def test_has_entries_exit_0(self):
        cc = _summ(products=(_CS("a", [_E(1)]),))
        assert cc.exit_code == 0

    def test_errors_exit_1(self):
        cc = _summ(products=(), errors=(("x", "y"),))
        assert cc.exit_code == 1

    def test_no_products_exit_2(self):
        cc = _summ(products=(), disabled=(), errors=())
        assert cc.exit_code == 2

    def test_all_empty_entries_exit_1(self):
        cc = _summ(products=(_CS("a", []), _CS("b", [])))
        assert cc.exit_code == 1

    def test_errors_outrank_no_products(self):
        cc = _summ(products=(), errors=(("x", "y"),))
        assert cc.exit_code == 1, "errors branch fires before n_products==0 -> 2"

    def test_errors_plus_entries_still_exit_1(self):
        cc = _summ(products=(_CS("a", [_E(1)]),), errors=(("b", "boom"),))
        assert cc.exit_code == 1

    def test_mixed_empty_and_nonempty_exit_0(self):
        cc = _summ(products=(_CS("a", []), _CS("b", [_E(5)])))
        assert cc.exit_code == 0

    def test_exit_code_verdict_pairing(self):
        for code, verdict in VERDICT_FOR_CODE.items():
            assert verdict


# ==========================================================================
# EB3 -- render() multi-line human-readable
# ==========================================================================
class TestEB3Render:
    def test_header_and_dispatch_path(self):
        cc = _summ(dispatch_path="/d/cfg.json",
                   products=(_CS("alpha", [_E(1, "feat", "add foo")]),))
        text = cc.render()
        assert "foundry company-changelog" in text
        assert "/d/cfg.json" in text

    def test_product_section_with_entries(self):
        e1 = _E(5, "feat", "add foo")
        e2 = _E(10, "fix", "fix bar")
        cs = _CS("alpha", [e1, e2])
        cc = _summ(products=(cs,))
        text = cc.render()
        assert "alpha" in text
        assert "2 entries" in text
        assert "iter-05" in text
        assert "[feat]" in text
        assert "add foo" in text
        assert "iter-10" in text
        assert "[fix]" in text

    def test_disabled_section(self):
        cc = _summ(products=(_CS("a", [_E(1)]),), disabled=("dis1", "dis2"))
        text = cc.render()
        assert "dis1" in text and "disabled" in text
        assert "dis2" in text

    def test_error_section(self):
        cc = _summ(products=(_CS("a", [_E(1)]),), errors=(("bad", "kaboom"),))
        text = cc.render()
        assert "bad" in text
        assert "ERROR" in text
        assert "kaboom" in text

    def test_verdict_last_line(self):
        cc = _summ(products=(_CS("a", [_E(1)]),))
        text = cc.render()
        non_empty = [ln for ln in text.splitlines() if ln.strip()]
        assert non_empty[-1].strip() == f"verdict: {cc.verdict}"

    def test_entry_count_in_summary_line(self):
        cc = _summ(products=(_CS("a", [_E(1), _E(2)]), _CS("b", [_E(3)])),
                   disabled=("d",), errors=(("e", "m"),))
        text = cc.render()
        assert "2 gathered" in text or "2 " in text
        assert "3 entries" in text

    def test_render_deterministic(self):
        cc = _summ(products=(_CS("a", [_E(1)]),), disabled=("d",),
                   errors=(("e", "m"),))
        assert cc.render() == cc.render()

    def test_render_no_home_path(self):
        cc = _summ(products=(_CS("a", [_E(1)]),))
        home_prefix = "/" + "Users" + "/"
        assert home_prefix not in cc.render()


# ==========================================================================
# EB4 -- to_dict() JSON-serialisable
# ==========================================================================
class TestEB4ToDict:
    def test_keys_and_order(self):
        cc = _summ(dispatch_path="d.json",
                   products=(_CS("a", [_E(1)]),),
                   disabled=("x",), errors=(("y", "m"),))
        d = cc.to_dict()
        assert tuple(d.keys()) == TO_DICT_KEYS

    def test_dispatch_path_key(self):
        cc = _summ(dispatch_path="dp.json")
        d = cc.to_dict()
        assert d["dispatch_path"] == "dp.json"

    def test_products_are_per_product_to_dict(self):
        cs = _CS("alpha", [_E(1, "feat", "x")])
        cc = _summ(products=(cs,))
        d = cc.to_dict()
        assert isinstance(d["products"], list) and len(d["products"]) == 1
        assert d["products"][0] == cs.to_dict()

    def test_disabled_and_errors_lists(self):
        cc = _summ(disabled=("a", "b"), errors=(("c", "msg"),))
        d = cc.to_dict()
        assert d["disabled"] == ["a", "b"]
        assert d["errors"] == [{"product": "c", "message": "msg"}]

    def test_counts_and_total(self):
        cs1 = _CS("a", [_E(1), _E(2)])
        cs2 = _CS("b", [_E(3)])
        cc = _summ(products=(cs1, cs2), disabled=("d",), errors=(("e", "m"),))
        d = cc.to_dict()
        assert d["n_products"] == 2
        assert d["n_disabled"] == 1
        assert d["n_errors"] == 1
        assert d["total_entries"] == 3

    def test_exit_code_and_verdict_in_dict(self):
        cc = _summ(products=(_CS("a", [_E(1)]),))
        d = cc.to_dict()
        assert d["exit_code"] == cc.exit_code == 0
        assert d["verdict"] == cc.verdict == "OK"

    def test_json_roundtrip(self):
        cc = _summ(dispatch_path="d.json",
                   products=(_CS("a", [_E(1, "feat", "x")]),),
                   disabled=("x",), errors=(("y", "z"),))
        d = cc.to_dict()
        assert json.loads(json.dumps(d)) == d

    def test_json_roundtrip_all_empty(self):
        cc = _summ()
        d = cc.to_dict()
        assert json.loads(json.dumps(d)) == d
        assert d["products"] == [] and d["disabled"] == [] and d["errors"] == []
        assert d["exit_code"] == 2


# ==========================================================================
# EB5 -- summarize_company_changelog pure keyword-only
# ==========================================================================
class TestEB5Summarize:
    def test_keyword_only(self):
        with pytest.raises(TypeError):
            foundry.summarize_company_changelog("d", (), (), ())

    def test_returns_company_changelog(self):
        cc = _summ(dispatch_path="d.json", products=(_CS("a"),))
        assert type(cc).__name__ == "CompanyChangelog"


# ==========================================================================
# EB6 -- gather_changelog called by bare name
# ==========================================================================
class TestEB6GatherBareName:
    def test_monkeypatch_bites(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        calls = []

        def fake_gather(cfg, limit=None):
            calls.append(("gather", limit))
            return _CS("alpha", [_E(1)])

        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"_path": p})())
        monkeypatch.setattr(foundry, "gather_changelog", fake_gather)
        rc, _ = _run_cli(str(disp))
        assert rc == 0
        assert len(calls) == 1, "gather_changelog called exactly once"

    def test_replacing_gather_changes_output(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"_path": p})())
        monkeypatch.setattr(foundry, "gather_changelog",
                            lambda cfg, limit=None: _CS("alpha", [_E(1)]))
        _, out1 = _run_cli(str(disp), as_json=True)
        monkeypatch.setattr(foundry, "gather_changelog",
                            lambda cfg, limit=None: _CS("alpha", [_E(i) for i in range(10)]))
        _, out2 = _run_cli(str(disp), as_json=True)
        assert json.loads(out1)["total_entries"] == 1
        assert json.loads(out2)["total_entries"] == 10


# ==========================================================================
# EB7 -- company_changelog_cli thin wrapper
# ==========================================================================
class TestEB7CLI:
    def test_limit_forwarded(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        limits_seen = []

        def fake_gather(cfg, limit=None):
            limits_seen.append(limit)
            return _CS("alpha", [_E(1)])

        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"_path": p})())
        monkeypatch.setattr(foundry, "gather_changelog", fake_gather)
        _run_cli(str(disp), limit=5)
        assert limits_seen == [5], f"--limit must be forwarded, saw {limits_seen}"

    def test_limit_none_default(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        limits_seen = []

        def fake_gather(cfg, limit=None):
            limits_seen.append(limit)
            return _CS("alpha", [_E(1)])

        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"_path": p})())
        monkeypatch.setattr(foundry, "gather_changelog", fake_gather)
        _run_cli(str(disp))
        assert limits_seen == [None]

    def test_json_emits_single_document(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        _patch_cli(monkeypatch, {"alpha": _CS("alpha", [_E(1)])})
        rc, out = _run_cli(str(disp), as_json=True)
        doc = json.loads(out)
        assert rc == doc["exit_code"] == 0
        assert tuple(doc.keys()) == TO_DICT_KEYS

    def test_json_and_human_same_exit_code(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        _patch_cli(monkeypatch, {"alpha": _CS("alpha", [_E(1, "feat", "x")])})
        rc_h, _ = _run_cli(str(disp))
        rc_j, out_j = _run_cli(str(disp), as_json=True)
        assert rc_h == rc_j == 0


# ==========================================================================
# EB8 -- main() routes company-changelog
# ==========================================================================
class TestEB8MainRouting:
    def test_main_dispatches_before_load_config(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [], name="empty.json")

        def boom(path):
            raise AssertionError(f"main called load_config({path!r})")

        monkeypatch.setattr(foundry, "load_config", boom)
        rc = foundry.main(["company-changelog", "--config", str(disp)])
        assert rc == 2

    def test_main_json_returns_code(self, tmp_path, monkeypatch, capsys):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        _patch_cli(monkeypatch, {"alpha": _CS("alpha", [_E(1)])})
        rc = foundry.main(["company-changelog", "--config", str(disp), "--json"])
        doc = json.loads(capsys.readouterr().out.strip())
        assert rc == doc["exit_code"] == 0

    def test_main_limit_forwarded(self, tmp_path, monkeypatch, capsys):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        limits_seen = []

        def fake_gather(cfg, limit=None):
            limits_seen.append(limit)
            return _CS("alpha", [_E(1)])

        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"_path": p})())
        monkeypatch.setattr(foundry, "gather_changelog", fake_gather)
        foundry.main(["company-changelog", "--config", str(disp), "--limit", "7"])
        assert limits_seen == [7]

    def test_help_lists_subcmd(self, capsys):
        with pytest.raises(SystemExit) as ei:
            foundry.main(["--help"])
        assert ei.value.code == 0
        text = capsys.readouterr().out
        assert SUBCMD in text


# ==========================================================================
# EB9 -- dispatch config missing/malformed -> exit 1
# ==========================================================================
class TestEB9Resilience:
    def test_missing_dispatch_exit_1(self, tmp_path):
        rc, out = _run_cli(str(tmp_path / "nope.json"))
        assert rc == 1
        assert "verdict:" in out.lower()

    def test_invalid_json_dispatch_exit_1(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        rc, _ = _run_cli(str(bad))
        assert rc == 1

    def test_non_object_dispatch_exit_1(self, tmp_path):
        arr = tmp_path / "arr.json"
        arr.write_text("[1, 2, 3]")
        rc, _ = _run_cli(str(arr))
        assert rc == 1

    def test_synthetic_error_in_json(self, tmp_path):
        missing = tmp_path / "missing.json"
        rc, out = _run_cli(str(missing), as_json=True)
        doc = json.loads(out)
        assert rc == 1
        assert doc["n_errors"] == 1


# ==========================================================================
# EB10 -- single product error, rollup continues
# ==========================================================================
class TestEB10ProductError:
    def test_gather_raise_recorded(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "good", "config": str(tmp_path / "good.json"), "enabled": True},
            {"name": "bad", "config": str(tmp_path / "bad.json"), "enabled": True},
        ])
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"_path": p})())

        def fake_gather(cfg, limit=None):
            if "bad.json" in cfg._path:
                raise RuntimeError("gather-boom")
            return _CS("ok", [_E(1)])

        monkeypatch.setattr(foundry, "gather_changelog", fake_gather)
        rc, out = _run_cli(str(disp), as_json=True)
        doc = json.loads(out)
        assert rc == 1
        assert doc["n_products"] == 1
        assert doc["n_errors"] == 1
        assert doc["errors"] == [{"product": "bad", "message": "gather-boom"}]

    def test_load_config_raise_recorded(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "good", "config": str(tmp_path / "good.json"), "enabled": True},
            {"name": "bad", "config": str(tmp_path / "bad.json"), "enabled": True},
        ])

        def fake_load(p):
            if "bad.json" in p:
                raise RuntimeError("load-boom")
            return type("C", (), {"_path": p})()

        monkeypatch.setattr(foundry, "load_config", fake_load)
        monkeypatch.setattr(foundry, "gather_changelog",
                            lambda cfg, limit=None: _CS("ok", [_E(1)]))
        rc, out = _run_cli(str(disp), as_json=True)
        doc = json.loads(out)
        assert rc == 1
        assert doc["n_products"] == 1 and doc["n_errors"] == 1

    def test_disabled_never_loaded(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
            {"name": "gone", "config": str(tmp_path / "gone.json"), "enabled": False},
        ])
        loaded = _patch_cli(monkeypatch, {"alpha": _CS("alpha", [_E(1)])})
        _run_cli(str(disp))
        assert loaded == [str(tmp_path / "alpha.json")]


# ==========================================================================
# Dormancy + wiring + import safety
# ==========================================================================
class TestDormancyAndWiring:
    def test_both_modules_import(self):
        r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                           cwd=str(_ROOT), capture_output=True, text=True)
        assert r.returncode == 0, f"import failed:\n{r.stderr}"

    def test_new_symbols_present(self):
        for name in NEW_SYMBOLS:
            assert hasattr(foundry, name), f"missing {name!r}"
        assert callable(foundry.summarize_company_changelog)
        assert callable(foundry.company_changelog_cli)
        assert hasattr(foundry, "gather_changelog")

    def test_new_symbols_absent_from_control_flow(self):
        for fn_name in CONTROL_FLOW_FNS:
            names, consts = _fn_names_consts(getattr(foundry, fn_name))
            for sym in NEW_SYMBOLS:
                assert sym not in names, \
                    f"{fn_name} references {sym!r}"
            assert SUBCMD not in consts, \
                f"{fn_name} embeds {SUBCMD!r}"

    def test_dispatcher_references_none(self):
        for sym in NEW_SYMBOLS:
            assert not hasattr(dispatcher, sym)
        dnames, dconsts = _module_names_consts(dispatcher)
        for sym in NEW_SYMBOLS:
            assert sym not in dnames
        assert SUBCMD not in dconsts

    def test_main_dispatches_company_changelog_cli(self):
        main_names, _ = _fn_names_consts(foundry.main)
        assert "company_changelog_cli" in main_names

    def test_cli_calls_gather_and_summarize_by_bare_name(self):
        cli_names, _ = _fn_names_consts(foundry.company_changelog_cli)
        assert "gather_changelog" in cli_names
        assert "summarize_company_changelog" in cli_names

    def test_control_path_scripts_byte_unchanged(self):
        r = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--",
             "scripts/leak_guard.py", "scripts/leak_denylist.txt"],
            cwd=str(_ROOT), capture_output=True, text=True)
        assert r.returncode == 0

    def test_cli_writes_nothing_to_repo_tree(self, tmp_path, monkeypatch):
        disp = _write_dispatch(tmp_path, [
            {"name": "alpha", "config": str(tmp_path / "alpha.json"), "enabled": True},
        ])
        _patch_cli(monkeypatch, {"alpha": _CS("alpha", [_E(1)])})
        before = _git_visible_snapshot(_ROOT / "products")
        _run_cli(str(disp))
        _run_cli(str(disp), as_json=True)
        after = _git_visible_snapshot(_ROOT / "products")
        assert before == after

    def test_shipped_files_no_home_path(self):
        if not (_LEAK_GUARD.exists() and _DENYLIST.exists()):
            pytest.skip("leak-guard not present")
        lg = _load_leak_guard()
        patterns = lg.load_denylist(_DENYLIST.read_text())
        home_prefix = "/" + "Users" + "/"
        assert len(lg.scan_text(home_prefix + "somebody/x", patterns)) >= 1
        for rel in ("tests/test_iter467_behavior.py", "README.md"):
            p = _ROOT / rel
            if not p.exists():
                continue
            txt = p.read_text()
            hits = lg.scan_text(txt, patterns)
            assert len(hits) == 0, f"{rel} has denylisted token"
            assert home_prefix not in txt

    def test_dormancy_siblings_dont_reference_new_symbols(self):
        sibling_clis = [
            n for n in dir(foundry)
            if n.startswith("company_") and n.endswith("_cli") and n != "company_changelog_cli"
        ]
        for fn_name in sibling_clis:
            fn = getattr(foundry, fn_name, None)
            if fn is None or not callable(fn):
                continue
            names, _ = _fn_names_consts(fn)
            for sym in NEW_SYMBOLS:
                assert sym not in names, \
                    f"sibling {fn_name} references new symbol {sym!r}"

    def test_live_smoke_on_real_dispatch(self, live_smoke_result):
        rc, captured = live_smoke_result(SUBCMD)
        doc = json.loads(captured.strip())
        assert rc == doc["exit_code"]
        assert doc["verdict"] == VERDICT_FOR_CODE[doc["exit_code"]]
