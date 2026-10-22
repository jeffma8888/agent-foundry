"""Black-box behaviour tests for iter 468 -- ``foundry reverts --config CFG
[--limit N] [--json]``: a per-product revert inventory with reason text and
retry classification.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-468 PM
spec's Expected Behaviors (1-10), the product README, the product's own
OBSERVABLE behaviour (building public objects, running the CLI, public runtime
introspection), and the existing test conventions under ``tests/``.  The
implementation source (``foundry.py`` internals), the engineer's and reviewer's
notes, and ``git diff`` were NOT read.  Every assertion derives from the spec's
pinned behavior + observed public behaviour probed by running the product.
Fully offline and deterministic: no network, no real git mutation, no real push.
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

ITERATION = 468
SUBCMD = "reverts"

NEW_SYMBOLS = ("RevertRecord", "RevertSummary", "gather_reverts",
               "reverts_cli", "summarize_reverts")

CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration",
                     "run_continuous")

VERDICT_FOR_CODE = {0: "reverts found", 1: "no reverts", 2: "nothing scanned"}

TO_DICT_KEYS = ("product", "total", "exit_code", "verdict", "records")

RECORD_DICT_KEYS = ("iteration", "reason", "retry_class")

VALID_RETRY_CLASSES = {"environmental", "review", "test", "unknown"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _RR(iteration=1, reason="", retry_class="unknown"):
    return foundry.RevertRecord(iteration=iteration, reason=reason,
                                retry_class=retry_class)


def _summ(product="test", records=(), scanned=10):
    return foundry.summarize_reverts(product=product,
                                     records=tuple(records),
                                     scanned=scanned)


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
    spec = importlib.util.spec_from_file_location("leak_guard_468", _LEAK_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_cli(cfg_path, limit=None, as_json=False):
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.reverts_cli(cfg_path, limit=limit, as_json=as_json)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _write_state_dir(tmp_path, product_name, reverted_iters, pushed_iters=()):
    """Build a minimal state directory tree with final.md files.

    reverted_iters: dict mapping iteration_number -> reason_text
    pushed_iters: iterable of iteration numbers that were pushed
    """
    state_dir = tmp_path / "products" / product_name / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    for n, reason in reverted_iters.items():
        d = state_dir / ("iter-%d" % n)
        d.mkdir()
        action = "ACTION: REVERTED"
        if reason:
            action += " " + reason
        (d / "final.md").write_text(action + "\n")
    for n in pushed_iters:
        d = state_dir / ("iter-%d" % n)
        d.mkdir(exist_ok=True)
        (d / "final.md").write_text("ACTION: PUSHED abc123\n")
    cfg = {
        "name": product_name,
        "repo": "example-repo",
        "allowed_push_repo": "example-repo",
        "branch": "main",
    }
    cfg_path = tmp_path / "products" / product_name / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    return str(cfg_path), state_dir


# ==========================================================================
# EB1 -- RevertRecord frozen dataclass
# ==========================================================================
class TestEB1RevertRecord:
    def test_is_frozen_dataclass(self):
        rr = _RR()
        assert dataclasses.is_dataclass(rr)
        assert rr.__dataclass_params__.frozen

    def test_fields_match_spec(self):
        fields = [f.name for f in dataclasses.fields(foundry.RevertRecord)]
        assert fields == ["iteration", "reason", "retry_class"]

    def test_field_types(self):
        rr = _RR(iteration=42, reason="test failure", retry_class="test")
        assert isinstance(rr.iteration, int)
        assert isinstance(rr.reason, str)
        assert isinstance(rr.retry_class, str)

    def test_value_equality(self):
        a = _RR(iteration=5, reason="fail", retry_class="test")
        b = _RR(iteration=5, reason="fail", retry_class="test")
        assert a == b

    def test_value_inequality(self):
        a = _RR(iteration=5, reason="fail", retry_class="test")
        b = _RR(iteration=5, reason="fail", retry_class="unknown")
        assert a != b

    def test_frozen_immutable(self):
        rr = _RR()
        with pytest.raises(dataclasses.FrozenInstanceError):
            rr.iteration = 99


# ==========================================================================
# EB2 -- RevertSummary frozen dataclass with exit_code/verdict
# ==========================================================================
class TestEB2RevertSummary:
    def test_is_frozen_dataclass(self):
        rs = _summ()
        assert dataclasses.is_dataclass(rs)
        assert rs.__dataclass_params__.frozen
        assert type(rs).__name__ == "RevertSummary"

    def test_fields_match_spec(self):
        fields = [f.name for f in dataclasses.fields(foundry.RevertSummary)]
        assert "product" in fields
        assert "records" in fields
        assert "scanned" in fields

    def test_records_exist_exit_0(self):
        rs = _summ(records=(_RR(),), scanned=10)
        assert rs.exit_code == 0
        assert rs.verdict == "reverts found"

    def test_no_reverts_exit_1(self):
        rs = _summ(records=(), scanned=10)
        assert rs.exit_code == 1
        assert rs.verdict == "no reverts"

    def test_nothing_scanned_exit_2(self):
        rs = _summ(records=(), scanned=0)
        assert rs.exit_code == 2
        assert rs.verdict == "nothing scanned"

    def test_total_property(self):
        rs = _summ(records=(_RR(iteration=1), _RR(iteration=2)), scanned=10)
        assert rs.total == 2

    def test_total_empty(self):
        rs = _summ(records=(), scanned=5)
        assert rs.total == 0

    def test_product_stored(self):
        rs = _summ(product="my-product")
        assert rs.product == "my-product"

    def test_records_tuple(self):
        rr1 = _RR(iteration=10)
        rr2 = _RR(iteration=5)
        rs = _summ(records=(rr1, rr2))
        assert rs.records == (rr1, rr2)
        assert isinstance(rs.records, tuple)

    def test_frozen_immutable(self):
        rs = _summ()
        with pytest.raises(dataclasses.FrozenInstanceError):
            rs.product = "x"

    def test_exit_code_verdict_pairing(self):
        for code, verdict in VERDICT_FOR_CODE.items():
            assert isinstance(verdict, str) and verdict

    def test_exit_code_covers_all_three_branches(self):
        codes = set()
        codes.add(_summ(records=(_RR(),), scanned=1).exit_code)
        codes.add(_summ(records=(), scanned=5).exit_code)
        codes.add(_summ(records=(), scanned=0).exit_code)
        assert codes == {0, 1, 2}


# ==========================================================================
# EB3 -- gather_reverts reads state dirs
# ==========================================================================
class TestEB3GatherReverts:
    def test_is_callable(self):
        assert callable(foundry.gather_reverts)

    def test_returns_revert_summary(self, monkeypatch):
        rr = _RR(iteration=1, reason="timeout", retry_class="environmental")
        rs = _summ(product="probe", records=(rr,), scanned=5)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs)
        cfg = type("C", (), {"name": "probe"})()
        result = foundry.gather_reverts(cfg)
        assert type(result).__name__ == "RevertSummary"
        assert result.total == 1

    def test_missing_state_dir_exit_2(self, tmp_path):
        cfg_data = {
            "name": "ghost",
            "repo": "r",
            "allowed_push_repo": "r",
            "branch": "main",
        }
        cfg_path = tmp_path / "ghost.json"
        cfg_path.write_text(json.dumps(cfg_data))
        cfg = foundry.load_config(str(cfg_path))
        rs = foundry.gather_reverts(cfg)
        assert rs.exit_code == 2
        assert rs.total == 0
        assert len(rs.records) == 0

    def test_read_only_no_dirs_created(self, tmp_path):
        cfg_data = {
            "name": "readonly",
            "repo": "r",
            "allowed_push_repo": "r",
            "branch": "main",
        }
        cfg_path = tmp_path / "readonly.json"
        cfg_path.write_text(json.dumps(cfg_data))
        cfg = foundry.load_config(str(cfg_path))
        before = set(tmp_path.rglob("*"))
        foundry.gather_reverts(cfg)
        after = set(tmp_path.rglob("*"))
        assert after == before | {cfg_path}


# ==========================================================================
# EB4 -- reverts_cli delegates to _thin_gather_cli
# ==========================================================================
class TestEB4CLI:
    def test_reverts_cli_returns_exit_code(self, monkeypatch):
        rr = _RR(iteration=5, reason="timeout", retry_class="environmental")
        rs = _summ(product="x", records=(rr,), scanned=10)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        rc, out = _run_cli("/fake/config.json")
        assert rc == 0

    def test_exit_1_when_no_reverts(self, monkeypatch):
        rs = _summ(product="x", records=(), scanned=10)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        rc, _ = _run_cli("/fake/config.json")
        assert rc == 1

    def test_exit_2_when_nothing_scanned(self, monkeypatch):
        rs = _summ(product="x", records=(), scanned=0)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        rc, _ = _run_cli("/fake/config.json")
        assert rc == 2


# ==========================================================================
# EB5 -- render() deterministic multi-line report
# ==========================================================================
class TestEB5Render:
    def test_header_contains_product(self):
        rs = _summ(product="alpha", records=(_RR(),), scanned=1)
        text = rs.render()
        assert "foundry reverts" in text
        assert "alpha" in text

    def test_totals_line_with_records(self):
        rr1 = _RR(iteration=1, retry_class="environmental")
        rr2 = _RR(iteration=2, retry_class="test")
        rr3 = _RR(iteration=3, retry_class="unknown")
        rs = _summ(records=(rr1, rr2, rr3), scanned=10)
        text = rs.render()
        assert "total 3" in text
        assert "environmental 1" in text
        assert "test 1" in text
        assert "unknown 1" in text

    def test_per_record_lines(self):
        rr = _RR(iteration=42, reason="session expired", retry_class="environmental")
        rs = _summ(records=(rr,), scanned=10)
        text = rs.render()
        assert "[iter 042]" in text
        assert "environmental" in text
        assert "session expired" in text

    def test_newest_first_ordering(self):
        rr1 = _RR(iteration=1, reason="old")
        rr2 = _RR(iteration=99, reason="new")
        rs = _summ(records=(rr2, rr1), scanned=10)
        text = rs.render()
        lines = text.splitlines()
        record_lines = [ln for ln in lines if "[iter" in ln]
        assert len(record_lines) == 2
        assert "099" in record_lines[0]
        assert "001" in record_lines[1]

    def test_verdict_last_line(self):
        rs = _summ(records=(_RR(),), scanned=1)
        text = rs.render()
        non_empty = [ln for ln in text.splitlines() if ln.strip()]
        assert non_empty[-1].strip().startswith("verdict:")
        assert rs.verdict in non_empty[-1]

    def test_no_records_body(self):
        rs = _summ(records=(), scanned=5)
        text = rs.render()
        assert "no reverts" in text

    def test_nothing_scanned_body(self):
        rs = _summ(records=(), scanned=0)
        text = rs.render()
        assert "nothing scanned" in text

    def test_render_deterministic(self):
        rs = _summ(records=(_RR(iteration=5, reason="x"),), scanned=3)
        assert rs.render() == rs.render()


# ==========================================================================
# EB6 -- to_dict() JSON-safe with specified keys
# ==========================================================================
class TestEB6ToDict:
    def test_keys_match_spec(self):
        rs = _summ(records=(_RR(),), scanned=1)
        d = rs.to_dict()
        assert tuple(d.keys()) == TO_DICT_KEYS

    def test_product_in_dict(self):
        rs = _summ(product="myproduct", records=(_RR(),), scanned=1)
        d = rs.to_dict()
        assert d["product"] == "myproduct"

    def test_total_in_dict(self):
        rs = _summ(records=(_RR(), _RR(iteration=2)), scanned=5)
        d = rs.to_dict()
        assert d["total"] == 2

    def test_exit_code_in_dict(self):
        rs = _summ(records=(_RR(),), scanned=1)
        d = rs.to_dict()
        assert d["exit_code"] == 0

    def test_verdict_in_dict(self):
        rs = _summ(records=(_RR(),), scanned=1)
        d = rs.to_dict()
        assert d["verdict"] == "reverts found"

    def test_records_in_dict(self):
        rr = _RR(iteration=5, reason="boom", retry_class="test")
        rs = _summ(records=(rr,), scanned=1)
        d = rs.to_dict()
        assert len(d["records"]) == 1
        rec = d["records"][0]
        assert tuple(rec.keys()) == RECORD_DICT_KEYS
        assert rec["iteration"] == 5
        assert rec["reason"] == "boom"
        assert rec["retry_class"] == "test"

    def test_json_roundtrip(self):
        rr = _RR(iteration=10, reason="session expired",
                 retry_class="environmental")
        rs = _summ(records=(rr,), scanned=5)
        d = rs.to_dict()
        assert json.loads(json.dumps(d)) == d

    def test_json_roundtrip_empty(self):
        rs = _summ(records=(), scanned=0)
        d = rs.to_dict()
        assert json.loads(json.dumps(d)) == d
        assert d["records"] == []
        assert d["exit_code"] == 2


# ==========================================================================
# EB7 -- --limit restricts scan window
# ==========================================================================
class TestEB7Limit:
    def test_limit_forwarded_to_gather(self, monkeypatch):
        limits_seen = []

        def fake_gather(cfg, limit=None):
            limits_seen.append(limit)
            return _summ(product="x", records=(), scanned=0)

        monkeypatch.setattr(foundry, "gather_reverts", fake_gather)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        _run_cli("/fake.json", limit=7)
        assert limits_seen == [7]

    def test_limit_none_default(self, monkeypatch):
        limits_seen = []

        def fake_gather(cfg, limit=None):
            limits_seen.append(limit)
            return _summ(product="x", records=(), scanned=0)

        monkeypatch.setattr(foundry, "gather_reverts", fake_gather)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        _run_cli("/fake.json")
        assert limits_seen == [None]


# ==========================================================================
# EB8 -- keyword tuples at module level
# ==========================================================================
class TestEB8KeywordTuples:
    def test_env_keywords_is_tuple(self):
        kw = foundry._REVERT_ENV_KEYWORDS
        assert isinstance(kw, tuple)
        assert len(kw) > 0
        for k in ("stall", "kill", "timeout", "expired", "session",
                   "credential", "auth"):
            assert k in kw, "%s missing from env keywords" % k

    def test_review_keywords_is_tuple(self):
        kw = foundry._REVERT_REVIEW_KEYWORDS
        assert isinstance(kw, tuple)
        assert len(kw) > 0
        for k in ("review", "defect"):
            assert k in kw, "%s missing from review keywords" % k

    def test_test_keywords_is_tuple(self):
        kw = foundry._REVERT_TEST_KEYWORDS
        assert isinstance(kw, tuple)
        assert len(kw) > 0
        for k in ("test", "fail", "assertion"):
            assert k in kw, "%s missing from test keywords" % k

    def test_classify_env(self):
        for marker in foundry._REVERT_ENV_KEYWORDS:
            cls = foundry._classify_revert("reason with %s in text" % marker)
            assert cls == "environmental", \
                "%s -> %s, expected environmental" % (marker, cls)

    def test_classify_review(self):
        for marker in foundry._REVERT_REVIEW_KEYWORDS:
            cls = foundry._classify_revert("reason with %s in text" % marker)
            assert cls == "review", \
                "%s -> %s, expected review" % (marker, cls)

    def test_classify_test(self):
        for marker in foundry._REVERT_TEST_KEYWORDS:
            cls = foundry._classify_revert("reason with %s in text" % marker)
            assert cls == "test", \
                "%s -> %s, expected test" % (marker, cls)

    def test_classify_unknown(self):
        assert foundry._classify_revert("some random text") == "unknown"

    def test_classify_empty(self):
        assert foundry._classify_revert("") == "unknown"

    def test_classify_case_insensitive(self):
        assert foundry._classify_revert("CONNECTION STALL detected") == "environmental"
        assert foundry._classify_revert("REVIEW defect found") == "review"
        assert foundry._classify_revert("TEST FAILURE") == "test"

    def test_classify_returns_only_valid_classes(self):
        cases = [
            "timeout", "kill signal", "session expired",
            "review defect", "blocking-finding",
            "test failure", "assertion error",
            "random text", "",
        ]
        for text in cases:
            cls = foundry._classify_revert(text)
            assert cls in VALID_RETRY_CLASSES, \
                "%s -> %s, not in valid classes" % (text, cls)


# ==========================================================================
# EB9 -- argparse registration
# ==========================================================================
class TestEB9Argparse:
    def test_main_dispatches_reverts(self, monkeypatch, capsys):
        rs = _summ(product="x", records=(), scanned=0)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        rc = foundry.main(["reverts", "--config", "/fake.json"])
        assert rc == 2

    def test_main_with_json(self, monkeypatch, capsys):
        rr = _RR(iteration=1, reason="timeout", retry_class="environmental")
        rs = _summ(product="x", records=(rr,), scanned=5)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        rc = foundry.main(["reverts", "--config", "/fake.json", "--json"])
        out = capsys.readouterr().out
        doc = json.loads(out)
        assert rc == doc["exit_code"] == 0
        assert tuple(doc.keys()) == TO_DICT_KEYS

    def test_main_with_limit(self, monkeypatch, capsys):
        limits_seen = []

        def fake_gather(cfg, limit=None):
            limits_seen.append(limit)
            return _summ(product="x", records=(), scanned=0)

        monkeypatch.setattr(foundry, "gather_reverts", fake_gather)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        foundry.main(["reverts", "--config", "/fake.json", "--limit", "10"])
        assert limits_seen == [10]

    def test_help_lists_reverts(self, capsys):
        with pytest.raises(SystemExit) as ei:
            foundry.main(["--help"])
        assert ei.value.code == 0
        text = capsys.readouterr().out
        assert "reverts" in text

    def test_subparser_help_has_flags(self, capsys):
        with pytest.raises(SystemExit) as ei:
            foundry.main(["reverts", "--help"])
        assert ei.value.code == 0
        text = capsys.readouterr().out
        for flag in ("--config", "--limit", "--json"):
            assert flag in text, "%s missing from reverts --help" % flag


# ==========================================================================
# EB10 -- bare-name seam via monkeypatch
# ==========================================================================
class TestEB10BareNameSeam:
    def test_monkeypatch_gather_reverts_controls_output(self, monkeypatch):
        rr = _RR(iteration=42, reason="session expired",
                 retry_class="environmental")
        rs = _summ(product="x", records=(rr,), scanned=5)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        rc, out = _run_cli("/fake.json")
        assert rc == 0
        assert "session expired" in out

    def test_replacing_gather_changes_output(self, monkeypatch):
        rs1 = _summ(product="x", records=(_RR(iteration=1),), scanned=1)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs1)
        monkeypatch.setattr(foundry, "load_config",
                            lambda p: type("C", (), {"name": "x"})())
        _, out1 = _run_cli("/fake.json", as_json=True)
        d1 = json.loads(out1)

        rs2 = _summ(product="x",
                     records=tuple(_RR(iteration=i) for i in range(10)),
                     scanned=50)
        monkeypatch.setattr(foundry, "gather_reverts", lambda cfg, limit=None: rs2)
        _, out2 = _run_cli("/fake.json", as_json=True)
        d2 = json.loads(out2)

        assert d1["total"] == 1
        assert d2["total"] == 10

    def test_cli_resolves_gather_by_bare_name(self):
        names, _ = _fn_names_consts(foundry.reverts_cli)
        assert "gather_reverts" in names


# ==========================================================================
# Dormancy + wiring + import safety
# ==========================================================================
class TestDormancyAndWiring:
    def test_both_modules_import(self):
        r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                           cwd=str(_ROOT), capture_output=True, text=True)
        assert r.returncode == 0, "import failed:\n%s" % r.stderr

    def test_new_symbols_present(self):
        for name in NEW_SYMBOLS:
            assert hasattr(foundry, name), "missing %s" % name
        assert callable(foundry.gather_reverts)
        assert callable(foundry.reverts_cli)
        assert callable(foundry.summarize_reverts)

    def test_new_symbols_absent_from_control_flow(self):
        for fn_name in CONTROL_FLOW_FNS:
            names, consts = _fn_names_consts(getattr(foundry, fn_name))
            for sym in NEW_SYMBOLS:
                assert sym not in names, \
                    "%s references %s" % (fn_name, sym)
            assert SUBCMD not in consts, \
                "%s embeds %s" % (fn_name, SUBCMD)

    def test_dispatcher_references_none(self):
        for sym in NEW_SYMBOLS:
            assert not hasattr(dispatcher, sym)
        dnames, dconsts = _module_names_consts(dispatcher)
        for sym in NEW_SYMBOLS:
            assert sym not in dnames
        assert SUBCMD not in dconsts

    def test_main_dispatches_reverts_cli(self):
        main_names, _ = _fn_names_consts(foundry.main)
        assert "reverts_cli" in main_names

    def test_cli_calls_gather_and_summarize_by_bare_name(self):
        cli_names, _ = _fn_names_consts(foundry.reverts_cli)
        assert "gather_reverts" in cli_names

    def test_verb_census(self):
        text = (_ROOT / "foundry.py").read_text(encoding="utf-8")
        verbs = foundry.foundry_cli_verbs(text)
        assert "reverts" in verbs

    def test_readme_verb_index_has_no_gaps(self):
        text = (_ROOT / "foundry.py").read_text(encoding="utf-8")
        verbs = foundry.foundry_cli_verbs(text)
        readme = (_ROOT / "README.md").read_text(encoding="utf-8")
        audit = foundry.readme_verb_index_gaps(readme, verbs)
        assert audit.missing_verbs == (), audit.missing_verbs
        assert audit.unknown_invocations == (), audit.unknown_invocations
        assert audit.ok is True, audit


# ==========================================================================
# summarize_reverts keyword-only
# ==========================================================================
class TestSummarizeKeywordOnly:
    def test_positional_raises(self):
        with pytest.raises(TypeError):
            foundry.summarize_reverts("x", (), 0)

    def test_keyword_works(self):
        rs = foundry.summarize_reverts(product="x", records=(), scanned=0)
        assert type(rs).__name__ == "RevertSummary"


# ==========================================================================
# Leak guard + safety
# ==========================================================================
class TestSafety:
    def test_this_file_is_ascii(self):
        text = pathlib.Path(__file__).resolve().read_text(encoding="utf-8")
        non_ascii = [(i, c) for i, c in enumerate(text) if ord(c) >= 128]
        assert non_ascii == []

    def test_this_file_leak_clean(self):
        lg = _load_leak_guard()
        patterns = lg.load_denylist(_DENYLIST.read_text())
        text = pathlib.Path(__file__).resolve().read_text(encoding="utf-8")
        assert lg.scan_text(text, patterns) == (), \
            "this test file leaks a denylisted token"
        needle = "/" + "Users" + "/" + "nobody/secret.txt"
        assert lg.scan_text(needle, patterns), \
            "leak matcher is inert (false-clean risk)"

    def test_shipped_files_no_home_path(self):
        lg = _load_leak_guard()
        patterns = lg.load_denylist(_DENYLIST.read_text())
        home_prefix = "/" + "Users" + "/"
        assert len(lg.scan_text(home_prefix + "somebody/x", patterns)) >= 1
        for rel in ("tests/test_iter468_behavior.py", "README.md"):
            p = _ROOT / rel
            if not p.exists():
                continue
            txt = p.read_text()
            hits = lg.scan_text(txt, patterns)
            assert len(hits) == 0, "%s has denylisted token" % rel
            assert home_prefix not in txt
