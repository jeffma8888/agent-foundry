"""Black-box behaviour tests for iter 546 -- ``reverts`` classifies a bare
``ACTION: REVERTED`` sentinel from the iteration dir's reviewer verdict and
authoritative tester disposition instead of reporting ``unknown``.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-546 PM spec's Expected
Behaviors (1-12), the README, existing tests under ``tests/``, and the product's
OBSERVABLE behaviour (calling public functions, running the CLI).  The
implementation source, engineer/reviewer notes and ``git diff`` were NOT read.
Every fixture is built in tmp_path; nothing depends on the ambient tree.
"""
import inspect
import io
import itertools
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

TEST_TOKENS = ("PASS", "RED", "UNFINISHED", "BLOCKED", "NONE", "")
REVIEW_TOKENS = ("APPROVE", "CHANGES_REQUIRED", "NONE")
VALID = {"environmental", "review", "test", "gate", "unknown"}


def _cls(review, test):
    return foundry._classify_revert_from_verdicts(review, test)


# --------------------------------------------------------------------------
# fixture helpers
# --------------------------------------------------------------------------
def _cfg(tmp_path, name="fx"):
    wr = tmp_path / "wr"
    state = wr / "state"
    state.mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "name": name, "repo": "example-repo",
        "allowed_push_repo": "example-repo", "branch": "main",
        "work_root": str(wr),
    }))
    cfg = foundry.load_config(str(cfg_path))
    assert pathlib.Path(cfg.state) == state
    return cfg, str(cfg_path), state


def _iter_dir(state, n, final="ACTION: REVERTED", reviewer=None,
              testers=None):
    d = state / ("iter-%02d" % n)
    d.mkdir()
    (d / "final.md").write_text("# final\nsome detail\n" + final + "\n")
    if reviewer is not None:
        (d / "reviewer.md").write_text(
            "# Review\nnotes here\n" + reviewer + "\n")
    for fname, last in (testers or {}).items():
        (d / fname).write_text("# Tester\nI honored the contract.\n"
                               + last + "\n")
    return d


def _only(rs):
    assert rs.total == 1, rs
    assert len(rs.records) == 1
    return rs.records[0]


def _snapshot(root):
    return {str(p): (p.is_dir(), None if p.is_dir() else p.read_bytes())
            for p in root.rglob("*")}


# ==========================================================================
# EB1-4 -- the pure classifier
# ==========================================================================
class TestEB1to4PureClassifier:
    def test_function_is_module_level_and_takes_two_args(self):
        fn = foundry._classify_revert_from_verdicts
        assert callable(fn)
        params = list(inspect.signature(fn).parameters)
        assert params == ["review", "test"]

    @pytest.mark.parametrize("t", TEST_TOKENS)
    def test_eb1_changes_required_is_review(self, t):
        assert _cls("CHANGES_REQUIRED", t) == "review"

    def test_eb2_approve_pass_is_environmental(self):
        assert _cls("APPROVE", "PASS") == "environmental"

    @pytest.mark.parametrize("t", ("RED", "UNFINISHED", "BLOCKED", "NONE"))
    def test_eb3_approve_not_pass_is_test(self, t):
        assert _cls("APPROVE", t) == "test"

    @pytest.mark.parametrize("review,test", [
        ("APPROVE", ""), ("NONE", "PASS"), ("NONE", "RED"), ("NONE", ""),
        ("MAYBE", "PASS"),
    ])
    def test_eb4_unknown_pairs(self, review, test):
        assert _cls(review, test) == "unknown"

    def test_eb4_total_never_raises_and_stays_in_vocabulary(self):
        odd = ("", "approve", "APPROVE ", "x" * 500, "\n", "\u00e9", "PASS",
               "RED", "review", "test", "environmental")
        for r, t in itertools.product(REVIEW_TOKENS + odd,
                                      TEST_TOKENS + odd):
            out = _cls(r, t)
            assert out in VALID, (r, t, out)

    def test_eb4_unrecognised_test_token_with_approve_is_not_review(self):
        # spec: any unrecognized token -> unknown
        assert _cls("APPROVE", "MAYBE") == "unknown"

    def test_pure_repeatable(self):
        a = [_cls(r, t) for r in REVIEW_TOKENS for t in TEST_TOKENS]
        b = [_cls(r, t) for r in REVIEW_TOKENS for t in TEST_TOKENS]
        assert a == b


# ==========================================================================
# EB5-10 -- gather_reverts fallback over tmp fixtures
# ==========================================================================
class TestEB5to10GatherFallback:
    # iter 547 (OPERATOR 2026-11-18 pin): a bare APPROVE + PASS revert with no
    # failed gate item and no kill/push/auth/network evidence is `unknown`.
    def test_eb5_bare_sentinel_approve_pass_no_evidence_unknown(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, reviewer="VERDICT: APPROVE",
                  testers={"tester.md": "RESULT: PASS"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.iteration == 1
        assert rec.retry_class == "unknown"
        assert rec.reason == "reviewer=APPROVE tester=PASS"

    def test_eb6_changes_required_no_tester_review(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, reviewer="VERDICT: CHANGES_REQUIRED")
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "review"
        assert rec.reason == "reviewer=CHANGES_REQUIRED tester=absent"

    def test_eb7_authoritative_later_round_wins(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, reviewer="VERDICT: APPROVE",
                  testers={"tester.md": "RESULT: FAIL",
                           "tester2.md": "RESULT: PASS"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "unknown"  # iter 547: no gate/kill evidence
        assert rec.reason == "reviewer=APPROVE tester=PASS"

    def test_eb7_single_failing_round_is_test(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, reviewer="VERDICT: APPROVE",
                  testers={"tester.md": "RESULT: FAIL"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "test"
        assert rec.reason.startswith("reviewer=APPROVE tester=")
        assert rec.reason != "reviewer=APPROVE tester=PASS"
        assert "tester=PASS" not in rec.reason

    def test_eb7_checkpoint_round_is_test(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, reviewer="VERDICT: APPROVE",
                  testers={"tester.md": "PROGRESS: CHECKPOINT\nRESULT: FAIL"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "test"
        assert rec.reason.startswith("reviewer=APPROVE tester=")

    def test_tester_only_no_reviewer_counts_as_none(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, testers={"tester.md": "RESULT: PASS"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "unknown"
        assert rec.reason == "reviewer=NONE tester=PASS"

    @pytest.mark.parametrize("reason,expected", [
        ("connection stall", "environmental"),
        ("review defect", "review"),
    ])
    def test_eb8_explicit_reason_wins(self, tmp_path, reason, expected):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, final="ACTION: REVERTED " + reason,
                  reviewer="VERDICT: APPROVE",
                  testers={"tester.md": "RESULT: PASS"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.reason == reason
        assert rec.retry_class == expected
        assert rec.retry_class == foundry._classify_revert(reason)

    def test_eb8_review_defect_not_verdict_derived(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, final="ACTION: REVERTED review defect",
                  reviewer="VERDICT: APPROVE",
                  testers={"tester.md": "RESULT: PASS"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class != _cls("APPROVE", "PASS")
        assert "reviewer=" not in rec.reason

    def test_eb9_no_stage_files_unchanged(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1)
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.reason == ""
        assert rec.retry_class == "unknown"

    def test_eb10_prose_quoted_verdict_is_none(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1,
                  reviewer="I considered CHANGES_REQUIRED but it is prose "
                           "and no verdict line follows.",
                  testers={"tester.md": "RESULT: PASS"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "unknown"
        assert rec.reason == "reviewer=NONE tester=PASS"

    def test_non_utf8_reviewer_does_not_raise(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        d = _iter_dir(state, 1, testers={"tester.md": "RESULT: PASS"})
        (d / "reviewer.md").write_bytes(b"\xff\xfe\x80 garbage\n")
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class in VALID
        assert rec.reason.endswith("tester=PASS")

    def test_pushed_dir_is_not_a_revert(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, final="ACTION: PUSHED abc123",
                  reviewer="VERDICT: APPROVE",
                  testers={"tester.md": "RESULT: PASS"})
        _iter_dir(state, 2, reviewer="VERDICT: APPROVE",
                  testers={"tester.md": "RESULT: PASS"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.iteration == 2


# ==========================================================================
# EB11 -- CLI JSON / text over a mixed fixture, read-only
# ==========================================================================
def _mixed(tmp_path):
    cfg, cfg_path, state = _cfg(tmp_path)
    _iter_dir(state, 1, reviewer="VERDICT: APPROVE",
              testers={"tester.md": "RESULT: PASS"})          # EB5
    _iter_dir(state, 2, reviewer="VERDICT: CHANGES_REQUIRED")  # EB6
    _iter_dir(state, 3)                                        # EB9
    return cfg, cfg_path, state


def _cli(*args):
    return subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "reverts", *args],
        capture_output=True, text=True, cwd=str(_ROOT), timeout=120)


class TestEB11CLI:
    def test_json_classes_newest_first_exit_0(self, tmp_path):
        _, cfg_path, _ = _mixed(tmp_path)
        p = _cli("--config", cfg_path, "--json")
        assert p.returncode == 0, p.stderr
        doc = json.loads(p.stdout)
        got = [(r["iteration"], r["retry_class"], r["reason"])
               for r in doc["records"]]
        assert got == [
            (3, "unknown", ""),
            (2, "review", "reviewer=CHANGES_REQUIRED tester=absent"),
            (1, "unknown", "reviewer=APPROVE tester=PASS"),  # iter 547
        ]
        assert doc["total"] == 3

    def test_text_totals_line(self, tmp_path):
        _, cfg_path, _ = _mixed(tmp_path)
        p = _cli("--config", cfg_path)
        assert p.returncode == 0, p.stderr
        lines = [ln.strip() for ln in p.stdout.splitlines()]
        assert ("total 3  environmental 0  review 1  test 0  gate 0  unknown 2"
                in lines), p.stdout

    def test_gather_is_read_only(self, tmp_path):
        cfg, _, _ = _mixed(tmp_path)
        before = _snapshot(tmp_path)
        foundry.gather_reverts(cfg)
        foundry.gather_reverts(cfg, limit=2)
        assert _snapshot(tmp_path) == before

    def test_reverts_cli_in_process_matches(self, tmp_path):
        cfg, _, _ = _mixed(tmp_path)
        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        try:
            rc = foundry.reverts_cli(cfg, limit=None, as_json=True)
        finally:
            sys.stdout = old
        assert rc == 0
        classes = [r["retry_class"]
                   for r in json.loads(out.getvalue())["records"]]
        assert classes == ["unknown", "review", "unknown"]  # iter 547


# ==========================================================================
# EB12 -- pinned surfaces unchanged
# ==========================================================================
class TestEB12Pins:
    def test_gather_signature(self):
        sig = inspect.signature(foundry.gather_reverts)
        assert list(sig.parameters) == ["cfg", "limit"]
        assert sig.parameters["limit"].default is None

    def test_classify_revert_empty_unknown(self):
        assert foundry._classify_revert("") == "unknown"

    def test_record_fields_unchanged(self):
        import dataclasses
        names = [f.name for f in dataclasses.fields(foundry.RevertRecord)]
        assert names == ["iteration", "reason", "retry_class"]

    def test_readme_section_65_mentions_fallback(self):
        text = (_ROOT / "README.md").read_text(encoding="utf-8")
        start = text.find("\n# 65.")
        assert start != -1
        end = text.find("\n# ", start + 1)
        sec = text[start:end if end != -1 else len(text)]
        flat = " ".join(sec.split())
        assert "reviewer=X tester=Y" in flat or "reviewer=<" in flat, flat[:400]
