"""ENGINEER-owned unit tests for iter 126 -- the two pure/seam helpers and the
retry-stage constant behind the UNFINISHED-vs-RED test-report disposition.

Scope split (mandated by the iter-126 spec's "Test routing" section, which exists
because iterations 121 and 125 shipped a green suite with ZERO tests naming any
new symbol after their single isolated tester stage was killed): this file covers
the spec's Expected Behaviors 1-6 -- `classify_test_report`, `read_test_disposition`
and `UNFINISHED_TEST_RETRY_STAGES`. The independent half (Behaviors 7-12: stage
routing on BOTH live paths and the `roles/tester.md` card contract) belongs to the
isolated tester in `tests/test_iter126_behavior.py`. Keeping helper coverage HERE
means a lost tester stage can no longer leave the new symbols untested.

Fully offline and deterministic: pure function calls plus `tmp_path` file reads.
No subprocess, no git, no network, no clock. Every path is built at RUNTIME from
`__file__` so no machine-specific path is ever committed.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

MARKER = "PROGRESS: CHECKPOINT"


# ---- Behavior 1: an earned PASS outranks a checkpoint claim ---------------- #
def test_b1_pass_verdict_classifies_pass():
    assert foundry.classify_test_report("all green\nRESULT: PASS") == "PASS"


def test_b1_pass_outranks_the_checkpoint_marker():
    body = f"wrote 3 of 9 behaviors\n{MARKER}\nRESULT: PASS"
    assert foundry.classify_test_report(body) == "PASS"


def test_b1_pass_tolerates_trailing_blank_lines_and_spacing():
    assert foundry.classify_test_report("  RESULT:  PASS  \n\n\n") == "PASS"


# ---- Behavior 2: marker + FAIL, and marker with no verdict at all ---------- #
def test_b2_marker_with_fail_sentinel_classifies_unfinished():
    body = f"tests/test_iter126_behavior.py created\n{MARKER}\nRESULT: FAIL"
    assert foundry.classify_test_report(body) == "UNFINISHED"


def test_b2_marker_without_any_result_line_classifies_unfinished():
    body = f"isolation honored\nran out of time\n{MARKER}\n"
    assert foundry.classify_test_report(body) == "UNFINISHED"


def test_b2_marker_anywhere_in_the_body_counts():
    body = f"{MARKER}\nprose after the marker\nRESULT: FAIL"
    assert foundry.classify_test_report(body) == "UNFINISHED"


# ---- Behavior 3: a genuinely red suite ------------------------------------- #
def test_b3_fail_sentinel_without_marker_classifies_red():
    body = ("2 failed: test_b7_order\nassert triples == expected\n"
            "RESULT: FAIL")
    assert foundry.classify_test_report(body) == "RED"


# ---- Behavior 4: nothing recognizable ------------------------------------- #
@pytest.mark.parametrize("text", ["", "   ", "\n\n\t\n", "no verdict here",
                                  "RESULT: MAYBE", "RESULT:",
                                  "VERDICT: APPROVE"])
def test_b4_unrecognizable_bodies_classify_none(text):
    assert foundry.classify_test_report(text) == "NONE"


# ---- Behavior 5: total -- never raises for any string input ---------------- #
@pytest.mark.parametrize("text", [
    "",
    "\x00\x01\x02 binary-ish \x7f",
    "lone surrogate \udcff and \udcfe",
    "RESULT: PASS\x00",
    "x" * 100_000 + "\nRESULT: PASS",
    "x" * 100_000,
    "\r\n\r\nRESULT: FAIL\r\n",
    "RESULT: FAIL\nprose follows the sentinel",
])
def test_b5_classifier_never_raises(text):
    assert foundry.classify_test_report(text) in ("PASS", "UNFINISHED", "RED",
                                                  "NONE")


def test_b5_result_fail_not_last_is_none_without_marker():
    """The anchored parser is reused on purpose: a stray earlier mention of the
    sentinel is NOT a verdict, so such a body is NONE rather than RED."""
    body = "RESULT: FAIL\nbut then I kept writing prose"
    assert foundry.classify_test_report(body) == "NONE"


def test_b5_result_fail_not_last_is_unfinished_with_marker():
    body = f"RESULT: FAIL\n{MARKER}\nstill writing"
    assert foundry.classify_test_report(body) == "UNFINISHED"


def test_b5_large_marked_body_classifies_unfinished():
    body = "detail\n" * 20_000 + MARKER + "\nRESULT: FAIL"
    assert foundry.classify_test_report(body) == "UNFINISHED"


# ---- Behavior 6: the I/O seam -------------------------------------------- #
def test_b6_reads_unfinished_body_from_disk(tmp_path):
    p = tmp_path / "tester.md"
    p.write_text(f"cut short\n{MARKER}\nRESULT: FAIL")
    assert foundry.read_test_disposition(p) == "UNFINISHED"


def test_b6_reads_red_and_pass_bodies_from_disk(tmp_path):
    red = tmp_path / "red.md"
    red.write_text("1 failed\nRESULT: FAIL")
    good = tmp_path / "green.md"
    good.write_text("RESULT: PASS")
    assert foundry.read_test_disposition(red) == "RED"
    assert foundry.read_test_disposition(good) == "PASS"


def test_b6_missing_path_degrades_to_red(tmp_path):
    """WHY RED and not NONE: RED is exactly today's behavior, so an unreadable
    report can never invent a new code path."""
    assert foundry.read_test_disposition(tmp_path / "absent.md") == "RED"


def test_b6_unreadable_path_degrades_to_red(tmp_path):
    a_dir = tmp_path / "not-a-file"
    a_dir.mkdir()
    assert foundry.read_test_disposition(a_dir) == "RED"


def test_b6_seam_calls_classifier_by_bare_module_name(tmp_path, monkeypatch):
    """Proves the seam reads the module global at call time, so the routing
    tests can monkeypatch either helper and have it bite."""
    p = tmp_path / "tester.md"
    p.write_text("RESULT: PASS")
    monkeypatch.setattr(foundry, "classify_test_report",
                        lambda text: "SCRIPTED")
    assert foundry.read_test_disposition(p) == "SCRIPTED"


def test_b6_marker_constant_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(foundry, "UNFINISHED_TEST_MARKER", "HALFWAY-DONE")
    assert foundry.classify_test_report("HALFWAY-DONE\nRESULT: FAIL") == \
        "UNFINISHED"
    assert foundry.classify_test_report(f"{MARKER}\nRESULT: FAIL") == "RED"


# ---- the retry-stage constant --------------------------------------------- #
def test_retry_stages_constant_shape_and_values():
    stages = foundry.UNFINISHED_TEST_RETRY_STAGES
    assert isinstance(stages, tuple)
    assert stages == (("tester-retry", "tester2.md"),
                      ("tester-retry2", "tester3.md"))
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in stages)


def test_retry_stages_constant_is_patchable(monkeypatch):
    monkeypatch.setattr(foundry, "UNFINISHED_TEST_RETRY_STAGES",
                        (("tester-retry", "t2.md"),))
    assert len(foundry.UNFINISHED_TEST_RETRY_STAGES) == 1


def test_retry_prompt_is_truthful_about_no_fix_having_happened():
    """The whole point of the branch: today's rerun prompt claims an engineering
    fix happened, which is false when nothing was ever red."""
    prompt = foundry.UNFINISHED_TEST_RETRY_PROMPT
    assert "UNFINISHED CHECKPOINT" in prompt
    assert "NO failing test" in prompt
    assert "CREATING" in prompt


def test_new_symbols_are_ascii_only():
    """Public-repo safety: no non-ASCII smuggled into the new module surface."""
    for text in (foundry.UNFINISHED_TEST_RETRY_PROMPT,
                 foundry.UNFINISHED_TEST_MARKER,
                 foundry.classify_test_report.__doc__ or "",
                 foundry.read_test_disposition.__doc__ or ""):
        text.encode("ascii")
