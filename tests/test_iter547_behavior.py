"""Black-box behaviour tests for iter 547 -- ``reverts`` classifies a
bare-sentinel APPROVE + PASS revert as ``gate`` when its final.md names a
failed gate item, ``environmental`` only on positive kill/push/auth/network
evidence, and ``unknown`` otherwise.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-547 PM spec's Expected
Behaviors (1-11), the README, existing tests under ``tests/``, and the
product's OBSERVABLE behaviour (calling public functions, running the CLI).
The implementation source, engineer/reviewer notes and ``git diff`` were NOT
read.  Every fixture is built in tmp_path with an explicit work_root; nothing
depends on the ambient products/*/state tree.
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

CLASSES = {"gate", "environmental", "unknown"}


def _ev(text, logs=()):
    return foundry._final_gate_evidence(text, logs)


# --------------------------------------------------------------------------
# fixture helpers (tmp_path only)
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
    assert tmp_path in pathlib.Path(cfg.state).parents
    return cfg, str(cfg_path), state


def _iter_dir(state, n, body="some detail", final="ACTION: REVERTED",
              reviewer=None, tester=None, logs=None):
    d = state / ("iter-%02d" % n)
    d.mkdir()
    (d / "final.md").write_text("# final\n" + body + "\n" + final + "\n")
    if reviewer is not None:
        (d / "reviewer.md").write_text("# Review\nnotes\n" + reviewer + "\n")
    if tester is not None:
        (d / "tester.md").write_text("# Tester\nhonored.\n" + tester + "\n")
    for fname, content in (logs or {}).items():
        p = d / fname
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)
    return d


def _only(rs):
    assert rs.total == 1, rs
    assert len(rs.records) == 1
    return rs.records[0]


def _snapshot(root):
    return {str(p): (p.is_dir(), None if p.is_dir() else p.read_bytes())
            for p in root.rglob("*")}


AP = dict(reviewer="VERDICT: APPROVE", tester="RESULT: PASS")


# ==========================================================================
# EB1-5 -- the pure detector
# ==========================================================================
class TestEB1to5Detector:
    def test_module_level_signature(self):
        fn = foundry._final_gate_evidence
        params = list(inspect.signature(fn).parameters)
        assert params[:2] == ["final_text", "attempt_logs"]
        assert inspect.signature(fn).parameters["attempt_logs"].default == ()

    @pytest.mark.parametrize("t", [
        "preship: BROKEN",
        "PRESHIP: BROKEN",
        "FAILED: suite=red key=abc",
        "leak-guard: LEAKED 2 paths",
        "3 failed, 13870 passed in 60s",
        "GATE 2: FAILED -- BLOCKING",
        "the suite is NOT green",
    ])
    def test_eb1_gate_texts(self, t):
        assert _ev(t) == "gate"
        assert foundry._final_gate_evidence(t) == "gate"

    @pytest.mark.parametrize("t", [
        "preship = **BROKEN**",
        "  FAILED: x",
        "notes\nFAILED: preship=BROKEN\nACTION: REVERTED",
        "suite: RED",
        "BLOCKING gate failure",
    ])
    def test_eb1_more_spec_examples_gate(self, t):
        assert _ev(t) == "gate"

    @pytest.mark.parametrize("t", [
        "", "13917 passed, 6 skipped", "0 failed", "All gate items verified.",
    ])
    def test_eb2_unknown_texts(self, t):
        assert _ev(t) == "unknown"
        assert foundry._final_gate_evidence(t) == "unknown"

    def test_eb2_failed_mid_line_is_not_ledger(self):
        # G2 is anchored per line: "FAILED:" not at a line start is no gate hit
        assert _ev("nothing FAILED: here") == "unknown"

    def test_eb3_checkpoint_kill_environmental(self):
        assert _ev("## STATUS: IN PROGRESS (checkpoint)\n"
                   "the stage was KILLED") == "environmental"

    def test_eb3_attempt_log_timeout_environmental(self):
        assert _ev("", ("agent run failed: agent run timed out after 600s",)
                   ) == "environmental"

    def test_eb3_attempt_log_connection_stall(self):
        assert _ev("", ("x", "Connection stalled, no data received")
                   ) == "environmental"

    @pytest.mark.parametrize("t", [
        "error: failed to push some refs",
        " ! [rejected]        main -> main (fetch first)",
        "fatal: Could not resolve host: example.com",
        "remote: Authentication failed for repo",
        "git@example: Permission denied (publickey).",
    ])
    def test_eb3_push_auth_network_literals(self, t):
        assert _ev(t) == "environmental"

    def test_eb3_log_without_kill_text_stays_unknown(self):
        assert _ev("all fine", ("agent finished normally",)) == "unknown"

    def test_eb4_gate_outranks_kill_text(self):
        t = "## STATUS: IN PROGRESS\npreship: BROKEN\nthe stage was KILLED"
        assert _ev(t) == "gate"

    def test_eb4_gate_outranks_attempt_log(self):
        assert _ev("3 failed", ("timed out after 600s",)) == "gate"

    def test_eb5_total(self):
        texts = ("", "\u00e9\u4e2d\U0001f600", "x" * 200000,
                 "preship" * 5000, "FAILED:\n" * 50, "\x00\r\n",
                 "leak-guard " + "y" * 5000, "STATUS: IN PROGRESS")
        logs = ((), ("",), ("\u00e9",), ("timed out after",),
                ("z" * 100000, "Connection stalled"))
        for t, lg in itertools.product(texts, logs):
            assert _ev(t, lg) in CLASSES, (t[:20], lg)

    def test_eb5_pure_repeatable(self):
        a = [_ev(t) for t in ("preship: BROKEN", "", "failed to push")]
        b = [_ev(t) for t in ("preship: BROKEN", "", "failed to push")]
        assert a == b == ["gate", "unknown", "environmental"]


# ==========================================================================
# EB6-8, 10 -- gather_reverts wiring
# ==========================================================================
class TestEB6to10Gather:
    def test_eb6_gate_row(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, body="preship: BROKEN", **AP)
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.iteration == 1
        assert rec.retry_class == "gate"
        assert rec.reason == "reviewer=APPROVE tester=PASS"

    def test_eb7_attempt_log_timeout_environmental(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, **AP, logs={
            "final.attempt1.log": "agent run timed out after 600s\n"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "environmental"
        assert rec.reason == "reviewer=APPROVE tester=PASS"

    def test_eb7_second_attempt_log_counts(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, **AP, logs={
            "final.attempt1.log": "ok\n",
            "final.attempt2.log": "Connection stalled for 120 s\n"})
        assert _only(foundry.gather_reverts(cfg)).retry_class == \
            "environmental"

    def test_eb7_non_final_log_is_ignored(self, tmp_path):
        # only final.attempt*.log files are evidence
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, **AP, logs={
            "tester.attempt1.log": "agent run timed out after 600s\n"})
        assert _only(foundry.gather_reverts(cfg)).retry_class == "unknown"

    def test_eb7_no_evidence_unknown(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, **AP)
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "unknown"
        assert rec.reason == "reviewer=APPROVE tester=PASS"

    def test_eb8_changes_required_stays_review(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, body="preship: BROKEN",
                  reviewer="VERDICT: CHANGES_REQUIRED")
        assert _only(foundry.gather_reverts(cfg)).retry_class == "review"

    def test_eb8_approve_fail_stays_test(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, body="preship: BROKEN",
                  reviewer="VERDICT: APPROVE", tester="RESULT: FAIL")
        assert _only(foundry.gather_reverts(cfg)).retry_class == "test"

    def test_eb8_explicit_reason_keyword_path(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, body="3 failed",
                  final="ACTION: REVERTED connection stall", **AP)
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class == "environmental"
        assert rec.reason == "connection stall"

    def test_eb8_no_stage_files_unknown(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, body="preship: BROKEN")
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.reason == ""
        assert rec.retry_class == "unknown"

    def test_eb8_confinement_multi_dir(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, body="preship: BROKEN\n3 failed",
                  reviewer="VERDICT: CHANGES_REQUIRED")
        _iter_dir(state, 2, body="preship: BROKEN\n3 failed",
                  reviewer="VERDICT: APPROVE", tester="RESULT: FAIL")
        _iter_dir(state, 3, body="preship: BROKEN\n3 failed",
                  final="ACTION: REVERTED connection stall", **AP)
        _iter_dir(state, 4, body="preship: BROKEN\n3 failed")
        _iter_dir(state, 5, body="preship: BROKEN\n3 failed", **AP)
        got = {r.iteration: r.retry_class
               for r in foundry.gather_reverts(cfg).records}
        assert got == {1: "review", 2: "test", 3: "environmental",
                       4: "unknown", 5: "gate"}

    def test_eb10_read_only(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, body="preship: BROKEN", **AP)
        _iter_dir(state, 2, **AP, logs={
            "final.attempt1.log": "timed out after 600s"})
        before = _snapshot(tmp_path)
        foundry.gather_reverts(cfg)
        foundry.gather_reverts(cfg, limit=1)
        assert _snapshot(tmp_path) == before

    def test_eb10_non_utf8_attempt_log(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, **AP, logs={
            "final.attempt1.log": b"\xff\xfe\x80 timed out after 600s"})
        rec = _only(foundry.gather_reverts(cfg))
        assert rec.retry_class in ("unknown", "environmental")

    def test_eb10_non_utf8_log_skipped_other_still_read(self, tmp_path):
        cfg, _, state = _cfg(tmp_path)
        _iter_dir(state, 1, **AP, logs={
            "final.attempt1.log": b"\xff\xfe\x80",
            "final.attempt2.log": "agent run timed out after 600s"})
        assert _only(foundry.gather_reverts(cfg)).retry_class == \
            "environmental"


# ==========================================================================
# EB9 -- CLI
# ==========================================================================
def _mixed(tmp_path):
    cfg, cfg_path, state = _cfg(tmp_path)
    _iter_dir(state, 1, body="preship: BROKEN", **AP)               # gate
    _iter_dir(state, 2, reviewer="VERDICT: CHANGES_REQUIRED")       # review
    _iter_dir(state, 3)                                             # unknown
    return cfg, cfg_path, state


def _cli(*args):
    return subprocess.run(
        [sys.executable, str(_ROOT / "foundry.py"), "reverts", *args],
        capture_output=True, text=True, cwd=str(_ROOT), timeout=120)


class TestEB9CLI:
    def test_text_totals_line(self, tmp_path):
        _, cfg_path, _ = _mixed(tmp_path)
        p = _cli("--config", cfg_path)
        assert p.returncode == 0, p.stderr
        lines = [ln.strip() for ln in p.stdout.splitlines()]
        assert ("total 3  environmental 0  review 1  test 0  gate 1  unknown 1"
                in lines), p.stdout

    def test_json_records(self, tmp_path):
        _, cfg_path, _ = _mixed(tmp_path)
        p = _cli("--config", cfg_path, "--json")
        assert p.returncode == 0, p.stderr
        doc = json.loads(p.stdout)
        recs = doc["records"]
        assert [r["retry_class"] for r in recs] == ["unknown", "review",
                                                    "gate"]
        assert [r["iteration"] for r in recs] == [3, 2, 1]
        for r in recs:
            assert set(r) == {"iteration", "reason", "retry_class"}
        assert doc["total"] == 3

    def test_in_process_cli_matches(self, tmp_path):
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
        assert classes == ["unknown", "review", "gate"]


# ==========================================================================
# EB11 -- pinned surfaces unchanged
# ==========================================================================
class TestEB11Pins:
    def test_verdict_classifier_unchanged(self):
        assert foundry._classify_revert_from_verdicts(
            "APPROVE", "PASS") == "environmental"

    def test_classify_revert_empty(self):
        assert foundry._classify_revert("") == "unknown"

    def test_gather_signature(self):
        sig = inspect.signature(foundry.gather_reverts)
        assert list(sig.parameters) == ["cfg", "limit"]
        assert sig.parameters["limit"].default is None

    def test_readme_65_names_gate_class(self):
        text = (_ROOT / "README.md").read_text(encoding="utf-8")
        start = text.find("\n# 65.")
        assert start != -1
        end = text.find("\n# ", start + 1)
        sec = " ".join(text[start:end if end != -1 else len(text)].split())
        assert "`gate`" in sec or " gate " in sec, sec[-600:]
